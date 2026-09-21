"""Unit tests for the mailer + email verification code logic.

Everything that would need Postgres or a live SMTP server is monkeypatched:
the DB accessor (``get_db_session``) is replaced with a fake cursor and
``smtplib`` with a fake client, so these run with no external services.
"""

import os
import smtplib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

# Same convention as tests/conftest.py: app.config builds its Settings singleton
# at import time, so the env must be complete before any app module is imported.
# (pytest.ini declares these under `env =`, which only takes effect when the
# optional pytest-env plugin is installed.)
os.environ.setdefault("SECRET_KEY", "test_secret_key_for_testing_only_min_32_chars")
os.environ.setdefault("CORS_ORIGINS", '["http://localhost:3000"]')
os.environ.setdefault("MAIN_DB_USER", "test_user")
os.environ.setdefault("MAIN_DB_PASSWORD", "test_password")

from app.core import mailer
from app.services import email_verification as ev


class _FakeCursor:
    """Minimal RealDictCursor stand-in: replays queued rows for fetchone()."""

    def __init__(self, rows):
        self._rows = list(rows)
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


@contextmanager
def _fake_session(cursor):
    yield _FakeConn(cursor)


@pytest.fixture
def fake_db(monkeypatch):
    """Install a fake get_db_session; the test queues the rows fetchone returns."""

    def install(rows):
        cursor = _FakeCursor(rows)
        monkeypatch.setattr(ev, "get_db_session", lambda: _fake_session(cursor))
        return cursor

    return install


@pytest.fixture
def sent_mail(monkeypatch):
    """Capture send_email calls instead of talking to SMTP."""
    captured = []
    monkeypatch.setattr(ev, "send_email", lambda **kwargs: captured.append(kwargs))
    return captured


# --------------------------------------------------------------------------
# code generation
# --------------------------------------------------------------------------


def test_generated_code_is_six_digits():
    for _ in range(200):
        code = ev._generate_code()
        assert len(code) == 6
        assert code.isdigit()


def test_generated_code_uses_secrets_not_random(monkeypatch):
    """Codes gate account access — they must come from the CSPRNG."""
    monkeypatch.setattr(ev.secrets, "randbelow", lambda n: 42)
    assert ev._generate_code() == "000042"


def test_mask_email_hides_local_part():
    assert ev._mask_email("student@example.com") == "s***@example.com"
    assert ev._mask_email("not-an-email") == "***"


# --------------------------------------------------------------------------
# send_code
# --------------------------------------------------------------------------


def test_send_code_stores_only_the_hash(fake_db, sent_mail):
    cursor = fake_db([{"email": "user@example.com"}])
    ev.send_code("User@Example.com", ev.SCENE_REGISTER)

    sql, params = cursor.executed[0]
    assert "INSERT INTO email_verification_codes" in sql
    email, scene, code_hash, expires_at, last_sent_at, cooldown_cutoff = params
    assert email == "user@example.com"  # normalized
    assert scene == ev.SCENE_REGISTER
    assert len(code_hash) == 64 and code_hash.isalnum()

    code = sent_mail[0]["text"].split("验证码：")[1].split("\n")[0]
    assert ev._hash_code(code) == code_hash
    assert all(str(param) != code for param in params)  # plaintext never reaches the DB
    assert (expires_at - last_sent_at).total_seconds() == ev.CODE_TTL_SECONDS
    assert (last_sent_at - cooldown_cutoff).total_seconds() == ev.RESEND_COOLDOWN_SECONDS


def test_send_code_sends_both_html_and_text(fake_db, sent_mail):
    fake_db([{"email": "user@example.com"}])
    ev.send_code("user@example.com", ev.SCENE_RESET)

    message = sent_mail[0]
    assert message["to"] == "user@example.com"
    assert "重置密码" in message["subject"]
    code = message["text"].split("验证码：")[1].split("\n")[0]
    assert code in message["html"]
    assert "10 分钟" in message["text"]
    assert "忽略本邮件" in message["text"]


def test_send_code_rejects_resend_within_cooldown(fake_db, sent_mail):
    # No RETURNING row => the UPSERT's cooldown guard refused the update.
    fake_db([])
    with pytest.raises(ev.VerificationError, match="频繁"):
        ev.send_code("user@example.com", ev.SCENE_REGISTER)
    assert sent_mail == []


def test_send_code_rejects_unknown_scene(fake_db, sent_mail):
    fake_db([{"email": "user@example.com"}])
    with pytest.raises(ev.VerificationError):
        ev.send_code("user@example.com", "login")
    assert sent_mail == []


def test_send_code_wraps_mailer_failure_without_leaking_detail(fake_db, monkeypatch):
    fake_db([{"email": "user@example.com"}])

    def boom(**kwargs):
        raise mailer.MailerError("SMTP is not configured (SMTP_HOST / SMTP_FROM missing)")

    monkeypatch.setattr(ev, "send_email", boom)
    with pytest.raises(ev.VerificationError) as excinfo:
        ev.send_code("user@example.com", ev.SCENE_REGISTER)
    assert "SMTP" not in str(excinfo.value)


# --------------------------------------------------------------------------
# verify_code
# --------------------------------------------------------------------------


def _row(code, attempts=0):
    return {"code_hash": ev._hash_code(code), "attempts": attempts}


def test_verify_code_consumes_the_row_on_success(fake_db):
    cursor = fake_db([_row("123456")])
    ev.verify_code("user@example.com", ev.SCENE_REGISTER, "123456")

    statements = [sql for sql, _ in cursor.executed]
    assert any(s.startswith("DELETE FROM email_verification_codes WHERE email") for s in statements), statements


def test_verify_code_uses_constant_time_compare(fake_db):
    cursor = fake_db([_row("123456")])
    with patch("app.services.email_verification.hmac.compare_digest", wraps=ev.hmac.compare_digest) as compare:
        ev.verify_code("user@example.com", ev.SCENE_REGISTER, "123456")
    assert compare.called
    assert cursor.executed  # sanity: we really went through the DB path


def test_verify_code_rejects_wrong_code_and_increments_attempts(fake_db):
    cursor = fake_db([_row("123456", attempts=1)])
    with pytest.raises(ev.VerificationError, match="验证码错误"):
        ev.verify_code("user@example.com", ev.SCENE_REGISTER, "000000")

    updates = [params for sql, params in cursor.executed if sql.startswith("UPDATE")]
    assert updates and updates[0][0] == 2


def test_verify_code_deletes_row_at_max_attempts(fake_db):
    cursor = fake_db([_row("123456", attempts=ev.MAX_ATTEMPTS - 1)])
    with pytest.raises(ev.VerificationError, match="次数过多"):
        ev.verify_code("user@example.com", ev.SCENE_REGISTER, "000000")

    statements = [sql for sql, _ in cursor.executed]
    assert not any(s.startswith("UPDATE") for s in statements)
    assert any(s.startswith("DELETE FROM email_verification_codes WHERE email") for s in statements)


def test_verify_code_treats_missing_row_as_expired(fake_db):
    fake_db([])
    with pytest.raises(ev.VerificationError, match="过期"):
        ev.verify_code("user@example.com", ev.SCENE_REGISTER, "123456")


def test_verify_code_sweeps_expired_rows_first(fake_db):
    cursor = fake_db([_row("123456")])
    ev.verify_code("user@example.com", ev.SCENE_REGISTER, "123456")

    first_sql, first_params = cursor.executed[0]
    assert first_sql == "DELETE FROM email_verification_codes WHERE expires_at <= %s"
    assert isinstance(first_params[0], datetime)


def test_verify_code_requires_a_code(fake_db):
    fake_db([])
    with pytest.raises(ev.VerificationError, match="请输入验证码"):
        ev.verify_code("user@example.com", ev.SCENE_REGISTER, "   ")


def test_hash_is_keyed_with_the_app_secret():
    """Regression: a bare SHA-256 over a 10^6 keyspace is not a protection.

    Anyone who could read `email_verification_codes` (leaked backup, read
    replica, any SQL read primitive) recovered every live code in seconds by
    enumerating 000000-999999. Keying the digest with SECRET_KEY makes the stored
    column useless on its own.
    """
    import hashlib
    import hmac

    from app.config import settings

    expected = hmac.new(settings.SECRET_KEY.encode("utf-8"), b"123456", hashlib.sha256).hexdigest()
    assert ev._hash_code("123456") == expected
    assert ev._hash_code("123456") != hashlib.sha256(b"123456").hexdigest()
    assert ev._hash_code("123456") != ev._hash_code("123457")
    # Same column type: CHAR(64) of hex.
    assert len(ev._hash_code("123456")) == 64


def test_hash_changes_with_the_secret(monkeypatch):
    baseline = ev._hash_code("123456")
    monkeypatch.setattr(ev.settings, "SECRET_KEY", "a-different-secret-key-at-least-32-chars")
    assert ev._hash_code("123456") != baseline


# --------------------------------------------------------------------------
# missing table (feature enabled before `alembic upgrade main_db@head` ran)
# --------------------------------------------------------------------------


class _UndefinedTable(Exception):
    """Stand-in for psycopg2.errors.UndefinedTable — matched on pgcode."""

    pgcode = "42P01"


def _install_failing_db(monkeypatch, exc):
    @contextmanager
    def session():
        raise exc
        yield  # pragma: no cover - unreachable, keeps this a generator

    monkeypatch.setattr(ev, "get_db_session", session)


def test_send_code_reports_missing_table_as_unavailable(monkeypatch, sent_mail):
    _install_failing_db(monkeypatch, _UndefinedTable('relation "email_verification_codes" does not exist'))

    with pytest.raises(ev.VerificationUnavailableError) as excinfo:
        ev.send_code("user@example.com", ev.SCENE_REGISTER)

    assert "未初始化" in str(excinfo.value)
    assert sent_mail == []


def test_verify_code_reports_missing_table_as_unavailable(monkeypatch):
    _install_failing_db(monkeypatch, _UndefinedTable('relation "email_verification_codes" does not exist'))

    with pytest.raises(ev.VerificationUnavailableError):
        ev.verify_code("user@example.com", ev.SCENE_REGISTER, "123456")


def test_other_db_errors_are_not_mistaken_for_a_missing_table(monkeypatch):
    """Only 42P01 is translated; everything else keeps propagating as-is."""

    class _Deadlock(Exception):
        pgcode = "40P01"

    _install_failing_db(monkeypatch, _Deadlock("deadlock detected"))

    with pytest.raises(_Deadlock):
        ev.verify_code("user@example.com", ev.SCENE_REGISTER, "123456")


def test_missing_table_error_is_not_a_verification_error():
    """The API distinguishes them: 503 (operator) vs 400/429 (user)."""
    assert not issubclass(ev.VerificationUnavailableError, ev.VerificationError)


# --------------------------------------------------------------------------
# mailer
# --------------------------------------------------------------------------


class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.logged_in = None
        self.sent = []
        self.started_tls = False
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.logged_in = user

    def send_message(self, message):
        self.sent.append(message)


@pytest.fixture
def smtp_settings(monkeypatch):
    def apply(**overrides):
        values = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": 465,
            "SMTP_SSL": True,
            "SMTP_USER": "no-reply@example.com",
            "SMTP_PASSWORD": "super-secret",
            "SMTP_FROM": "no-reply@example.com",
            "SMTP_FROM_NAME": "学道",
        }
        values.update(overrides)
        for key, value in values.items():
            monkeypatch.setattr(mailer.settings, key, value)

    return apply


@pytest.fixture(autouse=True)
def _reset_fake_smtp():
    _FakeSMTP.instances = []
    yield
    _FakeSMTP.instances = []


def test_is_configured_requires_host_and_from(smtp_settings):
    smtp_settings()
    assert mailer.is_configured() is True
    smtp_settings(SMTP_HOST="")
    assert mailer.is_configured() is False
    smtp_settings(SMTP_FROM="")
    assert mailer.is_configured() is False


def test_send_email_refuses_when_unconfigured(smtp_settings):
    smtp_settings(SMTP_HOST="")
    with pytest.raises(mailer.MailerError):
        mailer.send_email("user@example.com", "s", "<p>hi</p>", "hi")


def test_send_email_uses_ssl_and_encodes_cjk_headers(smtp_settings, monkeypatch):
    smtp_settings()
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", _FakeSMTP)
    mailer.send_email("user@example.com", "学道 - 注册验证码", "<p>码</p>", "码")

    smtp = _FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example.com", 465)
    assert smtp.timeout == 10  # a hung server must not pin the worker thread
    assert smtp.logged_in == "no-reply@example.com"

    raw = smtp.sent[0].as_string()
    assert "学道" not in raw  # headers are RFC 2047 encoded, not raw UTF-8
    assert "=?utf-8?" in raw.lower()
    assert smtp.sent[0]["Subject"] == "学道 - 注册验证码"
    assert smtp.sent[0]["From"].endswith("<no-reply@example.com>")


def test_send_email_starttls_when_ssl_disabled(smtp_settings, monkeypatch):
    smtp_settings(SMTP_SSL=False, SMTP_PORT=587)
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    mailer.send_email("user@example.com", "s", "<p>hi</p>", "hi")

    smtp = _FakeSMTP.instances[0]
    assert smtp.started_tls is True
    assert smtp.port == 587


def test_send_email_always_includes_a_text_alternative(smtp_settings, monkeypatch):
    smtp_settings()
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", _FakeSMTP)
    mailer.send_email("user@example.com", "s", "<p>hello</p>")

    message = _FakeSMTP.instances[0].sent[0]
    subtypes = [part.get_content_subtype() for part in message.walk() if part.get_content_maintype() == "text"]
    assert "plain" in subtypes
    assert "html" in subtypes


def test_send_email_wraps_smtp_errors_without_leaking_password(smtp_settings, monkeypatch, caplog):
    smtp_settings()

    class _FailingSMTP(_FakeSMTP):
        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, b"auth failed")

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", _FailingSMTP)
    with caplog.at_level("ERROR"):
        with pytest.raises(mailer.MailerError) as excinfo:
            mailer.send_email("user@example.com", "s", "<p>hi</p>", "hi")

    assert "super-secret" not in str(excinfo.value)
    assert "super-secret" not in caplog.text


def test_send_email_wraps_connection_errors(smtp_settings, monkeypatch):
    smtp_settings()

    def refuse(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", refuse)
    with pytest.raises(mailer.MailerError):
        mailer.send_email("user@example.com", "s", "<p>hi</p>", "hi")


def test_expiry_window_matches_ttl(fake_db, sent_mail):
    """The stored expires_at must be TTL seconds after last_sent_at, in UTC."""
    cursor = fake_db([{"email": "user@example.com"}])
    before = datetime.now(UTC)
    ev.send_code("user@example.com", ev.SCENE_REGISTER)

    _, params = cursor.executed[0]
    expires_at = params[3]
    assert expires_at.tzinfo is not None
    assert before + timedelta(seconds=ev.CODE_TTL_SECONDS - 1) <= expires_at


# --- transaction semantics -------------------------------------------------
#
# The `fake_db` fixture above yields a connection and nothing more, so it cannot
# see the difference between a write that commits and one that is thrown away.
# The real get_db_session (app/db/session.py) commits on a clean exit and ROLLS
# BACK on exception, which makes "mutate, then raise inside the block" a silent
# no-op. These tests model that.


class _TransactionalSession:
    """get_db_session stand-in that records whether the block committed."""

    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    @contextmanager
    def __call__(self):
        try:
            yield _FakeConn(self._cursor)
        except Exception:
            self.rolled_back = True
            raise
        else:
            self.committed = True


def _install_transactional_db(monkeypatch, rows):
    cursor = _FakeCursor(rows)
    session = _TransactionalSession(cursor)
    monkeypatch.setattr(ev, "get_db_session", session)
    return cursor, session


def test_wrong_code_commits_the_attempt_increment(monkeypatch):
    """A wrong guess must PERSIST attempts, or the lockout can never trigger.

    Regression: the increment used to be followed by `raise` inside the
    `with get_db_session()` block. get_db_session rolls back on exception, so
    attempts reset to 0 after every wrong guess and MAX_ATTEMPTS was
    unreachable — the code could be brute-forced for its whole 10-minute life.
    """
    cursor, session = _install_transactional_db(
        monkeypatch, [{"code_hash": ev._hash_code("111111"), "attempts": 0}]
    )

    with pytest.raises(ev.VerificationError):
        ev.verify_code("user@example.com", ev.SCENE_REGISTER, "999999")

    assert session.committed, "the attempts increment was rolled back and is lost"
    assert not session.rolled_back
    updates = [sql for sql, _ in cursor.executed if sql.startswith("UPDATE")]
    assert updates, "expected an UPDATE bumping attempts"


def test_lockout_commits_the_row_deletion(monkeypatch):
    """Hitting MAX_ATTEMPTS must persist the DELETE that burns the code."""
    cursor, session = _install_transactional_db(
        monkeypatch,
        [{"code_hash": ev._hash_code("111111"), "attempts": ev.MAX_ATTEMPTS - 1}],
    )

    with pytest.raises(ev.VerificationError, match="次数过多"):
        ev.verify_code("user@example.com", ev.SCENE_REGISTER, "999999")

    assert session.committed, "the lockout DELETE was rolled back"
    deletes = [sql for sql, _ in cursor.executed if sql.startswith("DELETE FROM email_verification_codes WHERE email")]
    assert deletes, "expected the code row to be deleted on lockout"


def test_correct_code_still_commits_its_deletion(monkeypatch):
    """The success path must keep committing the single-use DELETE."""
    cursor, session = _install_transactional_db(
        monkeypatch, [{"code_hash": ev._hash_code("123456"), "attempts": 0}]
    )

    ev.verify_code("user@example.com", ev.SCENE_REGISTER, "123456")

    assert session.committed
    deletes = [sql for sql, _ in cursor.executed if sql.startswith("DELETE FROM email_verification_codes WHERE email")]
    assert deletes, "a consumed code must be deleted"
