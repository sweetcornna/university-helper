"""Email-verification behaviour of the auth endpoints.

Everything that would touch Postgres or SMTP is monkeypatched, so these run
without a live database: `app.api.v1.auth` holds a module-level `auth_service`
instance and imports `email_verification` / `mailer` as modules, which makes
both the DB helpers and the verification service patchable by attribute.

The project-wide autouse `reset_auth_rate_limiter` fixture (tests/conftest.py)
clears the limiter between tests, so repeated posts to the same endpoint do not
bleed into each other as 429s.
"""

import time

import pytest
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from starlette.requests import Request

import app.api.v1.auth as auth_api
from app.main import app
from app.schemas.auth import SendCodeRequest


@pytest.fixture
def client():
    # base_url=http://localhost so TrustedHostMiddleware accepts the Host header
    return TestClient(app, base_url="http://localhost")


# Captured before the autouse fixture below stubs the module attribute out, so
# the cap's own tests can still exercise the real implementation.
_real_daily_cap = auth_api._check_send_code_daily_cap


@pytest.fixture(autouse=True)
def no_daily_cap(monkeypatch):
    """Neutralize the per-IP daily send-code cap.

    It is a real DB round-trip that fails CLOSED (503) when no Postgres is
    reachable, so without this every send-code test would 503 before reaching
    the behaviour under test. The cap itself is covered by its own tests below.
    """
    monkeypatch.setattr(auth_api, "_check_send_code_daily_cap", lambda req: None)


@pytest.fixture
def email_verification_on(monkeypatch):
    """Flag on, mailer configured, and no code floor so tests do not sleep."""
    monkeypatch.setattr(auth_api.settings, "EMAIL_VERIFICATION_ENABLED", True)
    monkeypatch.setattr(auth_api.mailer, "is_configured", lambda: True)
    monkeypatch.setattr(auth_api, "_RESET_SEND_FLOOR_SECONDS", 0.0)


@pytest.fixture
def spy_verification(monkeypatch):
    """Record calls into the verification service instead of hitting the DB."""
    calls = {"send": [], "verify": []}

    def fake_send_code(email, scene):
        calls["send"].append((email, scene))

    def fake_verify_code(email, scene, code):
        calls["verify"].append((email, scene, code))

    monkeypatch.setattr(auth_api.email_verification, "send_code", fake_send_code)
    monkeypatch.setattr(auth_api.email_verification, "verify_code", fake_verify_code)
    return calls


def _patch_registration(monkeypatch, email_exists=False):
    """Stub out both DB round-trips the register/send-code paths make."""

    async def fake_register_user(username, email, password):
        return {
            "access_token": "test-token",
            "token_type": "bearer",
            "user_id": 1,
            "tenant_db_name": f"tenant_{username}",
        }

    monkeypatch.setattr(auth_api.auth_service, "register_user", fake_register_user)
    monkeypatch.setattr(auth_api.auth_service, "email_exists", lambda email: email_exists)


def test_config_reports_flag_disabled(client, monkeypatch):
    monkeypatch.setattr(auth_api.settings, "EMAIL_VERIFICATION_ENABLED", False)

    response = client.get("/api/v1/auth/config")

    assert response.status_code == 200
    assert response.json() == {"email_verification_enabled": False}


def test_config_reports_flag_enabled(client, monkeypatch):
    monkeypatch.setattr(auth_api.settings, "EMAIL_VERIFICATION_ENABLED", True)

    response = client.get("/api/v1/auth/config")

    assert response.status_code == 200
    assert response.json() == {"email_verification_enabled": True}


def test_send_code_503_when_verification_disabled(client, monkeypatch, spy_verification):
    monkeypatch.setattr(auth_api.settings, "EMAIL_VERIFICATION_ENABLED", False)

    response = client.post(
        "/api/v1/auth/send-code",
        json={"email": "someone@example.com", "scene": "register"},
    )

    assert response.status_code == 503
    # The refusal must come before any DB or SMTP work.
    assert spy_verification["send"] == []


def test_send_code_503_when_mailer_unconfigured(client, monkeypatch, spy_verification):
    """Flag on but no SMTP settings is still a 503, not a 500 at send time."""
    monkeypatch.setattr(auth_api.settings, "EMAIL_VERIFICATION_ENABLED", True)
    monkeypatch.setattr(auth_api.mailer, "is_configured", lambda: False)

    response = client.post(
        "/api/v1/auth/send-code",
        json={"email": "someone@example.com", "scene": "register"},
    )

    assert response.status_code == 503
    assert spy_verification["send"] == []


def test_send_code_rejects_register_scene_for_existing_email(
    client, monkeypatch, email_verification_on, spy_verification
):
    _patch_registration(monkeypatch, email_exists=True)

    response = client.post(
        "/api/v1/auth/send-code",
        json={"email": "taken@example.com", "scene": "register"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "该邮箱已注册"
    assert spy_verification["send"] == []


def test_send_code_reset_scene_hides_unknown_email(client, monkeypatch, email_verification_on, spy_verification):
    """An unregistered address must look exactly like a successful send."""
    _patch_registration(monkeypatch, email_exists=False)

    response = client.post(
        "/api/v1/auth/send-code",
        json={"email": "ghost@example.com", "scene": "reset"},
    )

    assert response.status_code == 200
    assert response.json() == {"sent": True}
    # ...but nothing was actually generated or mailed.
    assert spy_verification["send"] == []


@pytest.mark.parametrize("email_exists", [True, False])
def test_send_code_reset_scene_pads_both_branches(client, monkeypatch, spy_verification, email_exists):
    """Known and unknown addresses must both be held to the same time floor.

    Padding only the unknown branch would merely invert the oracle, so this
    asserts the floor on both. A short floor keeps the test fast; only the lower
    bound is asserted, which cannot flake.
    """
    floor = 0.25
    monkeypatch.setattr(auth_api.settings, "EMAIL_VERIFICATION_ENABLED", True)
    monkeypatch.setattr(auth_api.mailer, "is_configured", lambda: True)
    monkeypatch.setattr(auth_api, "_RESET_SEND_FLOOR_SECONDS", floor)
    _patch_registration(monkeypatch, email_exists=email_exists)

    started = time.monotonic()
    response = client.post(
        "/api/v1/auth/send-code",
        json={"email": "someone@example.com", "scene": "reset"},
    )
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert response.json() == {"sent": True}
    assert elapsed >= floor


def test_send_code_rejects_unknown_scene(client, email_verification_on):
    response = client.post(
        "/api/v1/auth/send-code",
        json={"email": "someone@example.com", "scene": "login"},
    )

    assert response.status_code == 422


def test_register_unchanged_when_verification_disabled(client, monkeypatch, spy_verification):
    """The pre-existing payload (no `code`) must keep working untouched."""
    monkeypatch.setattr(auth_api.settings, "EMAIL_VERIFICATION_ENABLED", False)
    _patch_registration(monkeypatch)

    response = client.post(
        "/api/v1/auth/register",
        json={"username": "testuser", "email": "test@example.com", "password": "Test1234"},
    )

    assert response.status_code == 201
    assert response.json()["access_token"] == "test-token"
    # No code was demanded and none was consumed.
    assert spy_verification["verify"] == []


def test_register_requires_code_when_verification_enabled(client, monkeypatch, email_verification_on, spy_verification):
    _patch_registration(monkeypatch)

    response = client.post(
        "/api/v1/auth/register",
        json={"username": "testuser", "email": "test@example.com", "password": "Test1234"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "请先获取邮箱验证码"
    assert spy_verification["verify"] == []


def test_register_consumes_code_before_creating_user(client, monkeypatch, email_verification_on, spy_verification):
    _patch_registration(monkeypatch)

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "Test1234",
            "code": "123456",
        },
    )

    assert response.status_code == 201
    assert spy_verification["verify"] == [("test@example.com", "register", "123456")]


def test_register_rejects_bad_code(client, monkeypatch, email_verification_on, spy_verification):
    created = []

    async def fake_register_user(username, email, password):
        created.append(username)
        return {}

    def reject(email, scene, code):
        raise auth_api.email_verification.VerificationError("验证码错误，还可尝试 4 次")

    monkeypatch.setattr(auth_api.auth_service, "register_user", fake_register_user)
    monkeypatch.setattr(auth_api.email_verification, "verify_code", reject)

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "Test1234",
            "code": "000000",
        },
    )

    assert response.status_code == 400
    assert "验证码错误" in response.json()["detail"]
    # A rejected code must never reach user creation.
    assert created == []


def test_reset_password_rejects_weak_password(client, email_verification_on, spy_verification):
    """The reset path reuses the registration strength rules (schema layer)."""
    response = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "test@example.com", "code": "123456", "new_password": "weak"},
    )

    assert response.status_code == 422
    # Rejected before the code is consumed, so the user can retry with the same one.
    assert spy_verification["verify"] == []


def test_reset_password_success(client, monkeypatch, email_verification_on, spy_verification):
    reset_calls = []

    async def fake_reset_password(email, new_password):
        reset_calls.append((email, new_password))

    monkeypatch.setattr(auth_api.auth_service, "reset_password", fake_reset_password)

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "test@example.com", "code": "123456", "new_password": "Test1234"},
    )

    assert response.status_code == 200
    assert response.json() == {"reset": True}
    assert spy_verification["verify"] == [("test@example.com", "reset", "123456")]
    assert reset_calls == [("test@example.com", "Test1234")]


def test_reset_password_rejects_bad_code(client, monkeypatch, email_verification_on):
    def reject(email, scene, code):
        raise auth_api.email_verification.VerificationError("验证码已过期或不存在，请重新获取")

    changed = []

    async def fake_reset_password(email, new_password):
        changed.append(email)

    monkeypatch.setattr(auth_api.email_verification, "verify_code", reject)
    monkeypatch.setattr(auth_api.auth_service, "reset_password", fake_reset_password)

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "test@example.com", "code": "000000", "new_password": "Test1234"},
    )

    assert response.status_code == 400
    assert changed == []


# --------------------------------------------------------------------------
# F1 — the reset scene must never leak the send-side outcome
# --------------------------------------------------------------------------


def _reset_send_outcomes():
    """(label, send_code stub) pairs covering every way a real send can end."""

    def ok(email, scene):
        return None

    def cooldown(email, scene):
        raise auth_api.email_verification.VerificationError("发送过于频繁，请 60 秒后再试")

    def smtp_down(email, scene):
        raise auth_api.email_verification.VerificationError("验证码邮件发送失败，请稍后再试")

    def mailer_error(email, scene):
        raise auth_api.mailer.MailerError("SMTP is not configured")

    def table_missing(email, scene):
        raise auth_api.email_verification.VerificationUnavailableError("邮箱验证服务未初始化，请联系管理员执行数据库迁移")

    def crash(email, scene):
        raise RuntimeError("connection reset by peer")

    return [
        ("ok", ok),
        ("cooldown", cooldown),
        ("smtp-down", smtp_down),
        ("mailer-error", mailer_error),
        ("table-missing", table_missing),
        ("crash", crash),
    ]


@pytest.mark.parametrize("label,send_stub", _reset_send_outcomes(), ids=[label for label, _ in _reset_send_outcomes()])
@pytest.mark.parametrize("email_exists", [True, False])
def test_send_code_reset_response_is_identical_for_every_outcome(
    client, monkeypatch, email_verification_on, email_exists, label, send_stub
):
    """Status AND body must not depend on existence, nor on how the send ended.

    Regression (F1): a REGISTERED address that hit the 60s resend cooldown got a
    429 with a distinctive body, while an UNREGISTERED address never created a
    row and always got 200 {"sent": true} — two requests ~2s apart told an
    attacker whether the address had an account.
    """
    _patch_registration(monkeypatch, email_exists=email_exists)
    monkeypatch.setattr(auth_api.email_verification, "send_code", send_stub)

    response = client.post(
        "/api/v1/auth/send-code",
        json={"email": "someone@example.com", "scene": "reset"},
    )

    assert (response.status_code, response.json()) == (200, {"sent": True}), label


def test_send_code_register_scene_still_reports_send_failures(client, monkeypatch, email_verification_on):
    """The register scene keeps reporting errors — it reveals existence by design."""
    _patch_registration(monkeypatch, email_exists=False)

    def cooldown(email, scene):
        raise auth_api.email_verification.VerificationError("发送过于频繁，请 60 秒后再试")

    monkeypatch.setattr(auth_api.email_verification, "send_code", cooldown)

    response = client.post(
        "/api/v1/auth/send-code",
        json={"email": "someone@example.com", "scene": "register"},
    )

    assert response.status_code == 429
    assert "频繁" in response.json()["detail"]


# --------------------------------------------------------------------------
# F4 — SMTP latency must not reopen the timing oracle
# --------------------------------------------------------------------------


def _asgi_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/send-code",
            "headers": [],
            "client": ("203.0.113.7", 51234),
            "server": ("localhost", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("email_exists", [True, False])
async def test_reset_scene_hands_delivery_to_a_background_task(monkeypatch, email_verification_on, email_exists):
    """The handler must return without waiting on SMTP.

    Regression (F4): _RESET_SEND_FLOOR_SECONDS is a FLOOR, not a budget. The
    known-email branch used to await the real SMTP submission (0.5-3s against a
    remote provider, capped only by the mailer's 10s socket timeout), so whenever
    that exceeded the floor the response was measurably longer than the unknown
    branch's near-exact 1.000s. Delivery now runs after the response is sent.

    The endpoint is called directly rather than through TestClient because
    TestClient drains background tasks before handing back the response, which
    would hide exactly the property under test.
    """
    delivered = []

    def slow_send(email, scene):
        time.sleep(1.0)
        delivered.append(email)

    monkeypatch.setattr(auth_api, "_RESET_SEND_FLOOR_SECONDS", 0.1)
    monkeypatch.setattr(auth_api.rate_limiter, "check_rate_limit", lambda req: None)
    monkeypatch.setattr(auth_api.auth_service, "email_exists", lambda email: email_exists)
    monkeypatch.setattr(auth_api.email_verification, "send_code", slow_send)

    background_tasks = BackgroundTasks()
    started = time.monotonic()
    result = await auth_api.send_code(
        SendCodeRequest(email="someone@example.com", scene="reset"),
        _asgi_request(),
        background_tasks,
    )
    elapsed = time.monotonic() - started

    assert result == {"sent": True}
    # Held to the pad, but nowhere near the 1.0s the send costs.
    assert 0.1 <= elapsed < 0.6, elapsed
    assert delivered == [], "SMTP ran inline; the known-email branch is still slower"
    # ...and the send really was scheduled for the address that exists.
    assert len(background_tasks.tasks) == (1 if email_exists else 0)


@pytest.mark.asyncio
async def test_reset_scene_background_task_swallows_send_failures(monkeypatch, email_verification_on):
    """The deferred send must not raise out of the background task."""

    def boom(email, scene):
        raise auth_api.email_verification.VerificationError("发送过于频繁，请 60 秒后再试")

    monkeypatch.setattr(auth_api.email_verification, "send_code", boom)
    auth_api._dispatch_code_silently("someone@example.com", "reset")  # must not raise


# --------------------------------------------------------------------------
# F2 — one canonical email form for the whole stack
# --------------------------------------------------------------------------


def test_reset_password_normalizes_email_before_the_update(client, monkeypatch, email_verification_on):
    """Regression (F2): a user registered as `Alice@example.com` could verify a
    reset code (keyed lowercase by email_verification._normalize) and then have
    the UPDATE against the case-sensitive `users.email` match zero rows — and the
    anti-enumeration wording meant they never learned why."""
    verified = []
    reset_calls = []

    def fake_verify_code(email, scene, code):
        verified.append(email)

    async def fake_reset_password(email, new_password):
        reset_calls.append(email)

    monkeypatch.setattr(auth_api.email_verification, "verify_code", fake_verify_code)
    monkeypatch.setattr(auth_api.auth_service, "reset_password", fake_reset_password)

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "  Alice@Example.COM  ", "code": "123456", "new_password": "Test1234"},
    )

    assert response.status_code == 200
    # Both sides of the reset now see the SAME canonical string.
    assert verified == ["alice@example.com"]
    assert reset_calls == ["alice@example.com"]


def test_register_normalizes_email(client, monkeypatch, email_verification_on):
    seen = []

    async def fake_register_user(username, email, password):
        seen.append(email)
        return {"access_token": "t", "token_type": "bearer", "user_id": 1, "tenant_db_name": "tenant_testuser"}

    monkeypatch.setattr(auth_api.auth_service, "register_user", fake_register_user)
    monkeypatch.setattr(auth_api.auth_service, "email_exists", lambda email: False)
    monkeypatch.setattr(auth_api.email_verification, "verify_code", lambda email, scene, code: None)

    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "testuser",
            "email": "Alice@Example.COM",
            "password": "Test1234",
            "code": "123456",
        },
    )

    assert response.status_code == 201
    assert seen == ["alice@example.com"]


def test_login_normalizes_email(client, monkeypatch):
    seen = []

    async def fake_login_user(email, password):
        seen.append(email)
        raise ValueError("Invalid credentials")

    monkeypatch.setattr(auth_api.auth_service, "login_user", fake_login_user)

    client.post("/api/v1/auth/login", json={"email": "Alice@Example.COM", "password": "Test1234"})

    assert seen == ["alice@example.com"]


def test_send_code_normalizes_email(client, monkeypatch, email_verification_on):
    looked_up = []
    monkeypatch.setattr(auth_api.auth_service, "email_exists", lambda email: looked_up.append(email) or False)

    client.post("/api/v1/auth/send-code", json={"email": "Alice@Example.COM", "scene": "reset"})

    assert looked_up == ["alice@example.com"]


# --------------------------------------------------------------------------
# F6 — reset-password must honour EMAIL_VERIFICATION_ENABLED
# --------------------------------------------------------------------------


def test_reset_password_503_when_verification_disabled(client, monkeypatch, spy_verification):
    """Regression (F6): without this guard the route always reached verify_code ->
    get_db_session. On the frozen desktop build (PROFILE=local, sqlite backend)
    psycopg2 is not bundled, so it 500'd with an ImportError instead."""
    monkeypatch.setattr(auth_api.settings, "EMAIL_VERIFICATION_ENABLED", False)

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "test@example.com", "code": "123456", "new_password": "Test1234"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "邮箱验证未启用，请联系管理员"
    # The refusal must land before any DB work.
    assert spy_verification["verify"] == []


def test_reset_password_503_when_mailer_unconfigured(client, monkeypatch, spy_verification):
    monkeypatch.setattr(auth_api.settings, "EMAIL_VERIFICATION_ENABLED", True)
    monkeypatch.setattr(auth_api.mailer, "is_configured", lambda: False)

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "test@example.com", "code": "123456", "new_password": "Test1234"},
    )

    assert response.status_code == 503
    assert spy_verification["verify"] == []


# --------------------------------------------------------------------------
# F7 — a 422 must not echo the rejected password back
# --------------------------------------------------------------------------


def test_reset_password_422_does_not_echo_the_password(client, email_verification_on, spy_verification):
    """Regression (F7): pydantic v2 puts the rejected value in each error's
    "input" key, and FastAPI's default handler serialized it verbatim — so a
    too-weak password came straight back in the HTTP response body."""
    secret = "hunter2plaintext"

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "test@example.com", "code": "123456", "new_password": secret},
    )

    assert response.status_code == 422
    assert secret not in response.text
    for error in response.json()["detail"]:
        assert "input" not in error
        assert "ctx" not in error
        # The shape frontend/src/utils/api.js renders is preserved.
        assert set(error) == {"loc", "msg", "type"}
        assert error["loc"][:2] == ["body", "new_password"]
    assert "密码" in response.text


def test_register_422_does_not_echo_the_password(client, monkeypatch, spy_verification):
    """The same pre-existing leak on /auth/register."""
    monkeypatch.setattr(auth_api.settings, "EMAIL_VERIFICATION_ENABLED", False)
    secret = "weakplaintext"

    response = client.post(
        "/api/v1/auth/register",
        json={"username": "testuser", "email": "test@example.com", "password": secret},
    )

    assert response.status_code == 422
    assert secret not in response.text


# --------------------------------------------------------------------------
# F3 — a missing email_verification_codes table is a 503, not a 500
# --------------------------------------------------------------------------


def test_send_code_503_when_table_missing(client, monkeypatch, email_verification_on):
    _patch_registration(monkeypatch, email_exists=False)

    def unmigrated(email, scene):
        raise auth_api.email_verification.VerificationUnavailableError("邮箱验证服务未初始化，请联系管理员执行数据库迁移")

    monkeypatch.setattr(auth_api.email_verification, "send_code", unmigrated)

    response = client.post(
        "/api/v1/auth/send-code",
        json={"email": "someone@example.com", "scene": "register"},
    )

    assert response.status_code == 503
    assert "数据库迁移" in response.json()["detail"]


def test_reset_password_503_when_table_missing(client, monkeypatch, email_verification_on):
    def unmigrated(email, scene, code):
        raise auth_api.email_verification.VerificationUnavailableError("邮箱验证服务未初始化，请联系管理员执行数据库迁移")

    monkeypatch.setattr(auth_api.email_verification, "verify_code", unmigrated)

    response = client.post(
        "/api/v1/auth/reset-password",
        json={"email": "test@example.com", "code": "123456", "new_password": "Test1234"},
    )

    assert response.status_code == 503
    assert "数据库迁移" in response.json()["detail"]


# --------------------------------------------------------------------------
# F5 — per-IP daily cap on send-code
# --------------------------------------------------------------------------


class _CapCursor:
    def __init__(self, counts):
        self._counts = list(counts)
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return {"count": self._counts.pop(0)}


class _CapConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def _install_cap_db(monkeypatch, counts):
    from contextlib import contextmanager

    cursor = _CapCursor(counts)

    @contextmanager
    def session():
        yield _CapConn(cursor)

    monkeypatch.setattr(auth_api, "get_db_session", session)
    return cursor


def test_daily_cap_allows_up_to_the_limit(monkeypatch):
    cursor = _install_cap_db(monkeypatch, [auth_api._SEND_CODE_DAILY_LIMIT])

    _real_daily_cap(_asgi_request())  # must not raise

    sql, params = cursor.executed[0]
    assert "INSERT INTO rate_limit_counters" in sql
    client_id, window_start = params
    # Namespaced so it cannot collide with the per-minute limiter's bare-IP keys.
    assert client_id == "send-code:203.0.113.7"
    # window_start holds the END of the day so RateLimiter's 2-minute sweep does
    # not delete the counter out from under us mid-day.
    assert (window_start.hour, window_start.minute) == (0, 0)
    assert window_start > auth_api.datetime.now(auth_api.UTC)


def test_daily_cap_blocks_past_the_limit(monkeypatch):
    from fastapi import HTTPException

    _install_cap_db(monkeypatch, [auth_api._SEND_CODE_DAILY_LIMIT + 1])

    with pytest.raises(HTTPException) as excinfo:
        _real_daily_cap(_asgi_request())

    assert excinfo.value.status_code == 429


def test_daily_cap_fails_closed_when_the_counter_is_unreachable(monkeypatch):
    from fastapi import HTTPException

    def broken():
        raise RuntimeError("could not connect to server")

    monkeypatch.setattr(auth_api, "get_db_session", broken)

    with pytest.raises(HTTPException) as excinfo:
        _real_daily_cap(_asgi_request())

    assert excinfo.value.status_code == 503
