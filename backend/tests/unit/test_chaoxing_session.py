"""Durable, account-bound Chaoxing session.

Covers the account-binding regression (a stored jar for account A must never be
reused when the caller supplies account B), rehydration after a restart, the
7-day TTL, invalid-cookie fallback, and that the session endpoint never leaks
cookies. Network and storage are monkeypatched — no live Chaoxing, no Postgres.
"""

import json
import types
from datetime import UTC, datetime, timedelta

import pytest
import requests

import app.services.course.chaoxing.auth_service as auth_mod
import app.services.course.chaoxing.cookies as cookies_mod
import app.services.course.chaoxing.signin as signin_mod
import app.services.course.task_store as task_store_mod
from app.services.course.chaoxing.auth_service import ChaoxingAuthService
from app.services.course.chaoxing.cookies import (
    CHAOXING_SESSION_KIND,
    CHAOXING_SESSION_TTL,
    delete_session,
    load_session,
    save_session,
    session_metadata,
    touch_session,
)
from app.services.course.chaoxing.session_manager import SessionManager
from app.services.course.chaoxing.signin import ChaoxingSigninManager


class FakeTaskBackend:
    """In-memory stand-in for the storage adapter behind TaskStore."""

    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}

    def ensure_tables(self) -> None:
        pass

    def upsert_task(self, task_kind, payload):
        self.rows[(task_kind, str(payload.get("task_id")))] = json.loads(json.dumps(payload, default=str))

    def get_task(self, task_kind, task_id, user_id=None):
        row = self.rows.get((task_kind, str(task_id)))
        if row is None:
            return None
        if user_id and str(row.get("user_id")) != str(user_id):
            return None
        return dict(row)

    def list_tasks(self, task_kind, user_id=None, limit=50):
        return []

    def append_history(self, history_kind, user_id, record, max_records=500):
        pass

    def list_history(self, history_kind, user_id=None, limit=500):
        return []

    def raw(self, user_id):
        return self.rows.get((CHAOXING_SESSION_KIND, str(user_id)))


@pytest.fixture
def store(monkeypatch, tmp_path):
    """Route TaskStore at an in-memory backend and cookie files at tmp_path."""
    backend = FakeTaskBackend()
    monkeypatch.setattr(task_store_mod, "get_storage", lambda: types.SimpleNamespace(tasks=backend))
    monkeypatch.setattr(cookies_mod, "COOKIES_DIR", tmp_path)
    monkeypatch.setattr(cookies_mod, "COOKIES_FILE", tmp_path / "cookies.json")
    return backend


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeLoginSession:
    """Stands in for requests.Session() inside the password-login branch."""

    def __init__(self, uid="BBB"):
        self.cookies = requests.cookies.RequestsCookieJar()
        self.posted = []
        self._uid = uid

    def post(self, url, **kwargs):
        self.posted.append(kwargs.get("data") or {})
        self.cookies.set("_uid", self._uid)
        return FakeResponse({"status": True})


def _auth_service(monkeypatch, username, password, user_id, login_session):
    account = types.SimpleNamespace(username=username, password=password)
    session_manager = SessionManager()
    service = ChaoxingAuthService(account=account, session_manager=session_manager, user_id=user_id)
    service.cipher = types.SimpleNamespace(encrypt=lambda value: f"enc:{value}")
    monkeypatch.setattr(auth_mod.requests, "Session", lambda: login_session)
    return service, session_manager


def _make_manager():
    return ChaoxingSigninManager()


# ---------------------------------------------------------------------------
# Problem 0 — account binding
# ---------------------------------------------------------------------------


def test_stored_session_for_account_a_is_never_reused_for_account_b(store, monkeypatch, tmp_path):
    """Regression: A's jar must not authenticate a task started for account B."""
    save_session("user-1", "accountA", {"_uid": "AAA", "fid": "1"})
    # Also seed the legacy per-user cookie file: that is where the pre-fix code
    # read the jar from, and it must not be adopted either.
    (tmp_path / "cookies_user-1.json").write_text(json.dumps({"_uid": "AAA", "fid": "1"}))

    login_session = FakeLoginSession(uid="BBB")
    service, session_manager = _auth_service(monkeypatch, "accountB", "pw-b", "user-1", login_session)
    monkeypatch.setattr(
        ChaoxingAuthService,
        "_validate_cookie_session",
        lambda self: pytest.fail("account A's jar must not even be probed"),
    )

    result = service.login(login_with_cookies=True)

    assert result["status"] is True
    # B's credentials actually went to Chaoxing...
    assert login_session.posted and login_session.posted[0]["uname"] == "enc:accountB"
    # ...and the live jar is B's, not A's.
    assert session_manager.get_session().cookies.get("_uid") == "BBB"
    # The stale jar was replaced, so the next run is bound to B too.
    stored = load_session("user-1")
    assert stored["username"] == "accountB"
    assert stored["cookies"] == {"_uid": "BBB"}


def test_stored_session_is_reused_for_the_same_account(store, monkeypatch):
    save_session("user-1", "accountA", {"_uid": "AAA"})

    login_session = FakeLoginSession()
    service, session_manager = _auth_service(monkeypatch, "accountA", "pw-a", "user-1", login_session)
    monkeypatch.setattr(ChaoxingAuthService, "_validate_cookie_session", lambda self: True)

    result = service.login(login_with_cookies=True)

    assert result["status"] is True
    assert login_session.posted == []  # no password round-trip
    assert session_manager.get_session().cookies.get("_uid") == "AAA"


def test_cookie_login_without_a_username_refuses_to_adopt_any_jar(store, monkeypatch, tmp_path):
    """No username to bind against -> fail closed, never adopt a stored jar."""
    save_session("user-1", "accountA", {"_uid": "AAA"})
    (tmp_path / "cookies_user-1.json").write_text(json.dumps({"_uid": "AAA"}))

    login_session = FakeLoginSession()
    service, _ = _auth_service(monkeypatch, "", "", "user-1", login_session)
    monkeypatch.setattr(
        ChaoxingAuthService,
        "_validate_cookie_session",
        lambda self: pytest.fail("an unbound caller must not probe a stored jar"),
    )

    result = service.login(login_with_cookies=True)

    assert result["status"] is False
    assert login_session.posted == []


def test_unbound_stored_record_is_dropped_not_adopted(store):
    """A jar persisted without a username can't be attributed — never adopt it."""
    store.upsert_task(
        CHAOXING_SESSION_KIND,
        {
            "task_id": "user-1",
            "user_id": "user-1",
            "status": "active",
            "saved_at": datetime.now(UTC).isoformat(),
            "chaoxing_username": "",
            "chaoxing_cookies": json.dumps({"_uid": "AAA"}),
        },
    )

    assert load_session("user-1") is None
    assert store.raw("user-1")["status"] == "revoked"


def test_invalid_cookies_fall_back_to_password_login(store, monkeypatch):
    save_session("user-1", "accountA", {"_uid": "AAA"})

    login_session = FakeLoginSession(uid="AAA2")
    service, session_manager = _auth_service(monkeypatch, "accountA", "pw-a", "user-1", login_session)
    monkeypatch.setattr(ChaoxingAuthService, "_validate_cookie_session", lambda self: False)

    result = service.login(login_with_cookies=True)

    assert result["status"] is True
    assert login_session.posted and login_session.posted[0]["uname"] == "enc:accountA"
    # The rejected jar must not survive alongside the fresh one.
    assert session_manager.get_session().cookies.get("_uid") == "AAA2"
    assert load_session("user-1")["cookies"] == {"_uid": "AAA2"}


# ---------------------------------------------------------------------------
# Problem 1 — durable storage, TTL, rehydration
# ---------------------------------------------------------------------------


def test_cookie_jar_is_encrypted_at_rest(store, monkeypatch):
    from cryptography.fernet import Fernet

    from app.core import credential_crypto

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    credential_crypto._reset_for_tests()
    try:
        save_session("user-1", "accountA", {"_uid": "super-secret-value"})
        stored_blob = store.raw("user-1")["chaoxing_cookies"]
        assert stored_blob.startswith("fernet:")
        assert "super-secret-value" not in stored_blob
        # ...and it still round-trips through the reader.
        assert load_session("user-1")["cookies"] == {"_uid": "super-secret-value"}
    finally:
        credential_crypto._reset_for_tests()


def test_encryption_failure_drops_the_jar_instead_of_persisting_plaintext(store, monkeypatch):
    def _boom(payload, fields):
        raise RuntimeError("cipher unavailable")

    monkeypatch.setattr(task_store_mod, "encrypt_dict_fields", _boom)

    save_session("user-1", "accountA", {"_uid": "AAA"})

    row = store.raw("user-1")
    assert "chaoxing_cookies" not in row
    assert "AAA" not in json.dumps(row)
    assert load_session("user-1") is None


def test_session_past_the_ttl_is_treated_as_absent_and_deleted(store):
    save_session("user-1", "accountA", {"_uid": "AAA"})
    expired = datetime.now(UTC) - CHAOXING_SESSION_TTL - timedelta(minutes=1)
    store.rows[(CHAOXING_SESSION_KIND, "user-1")]["saved_at"] = expired.isoformat()

    assert load_session("user-1") is None
    assert session_metadata("user-1") is None
    assert store.raw("user-1")["status"] == "revoked"


def test_session_just_inside_the_ttl_still_loads(store):
    save_session("user-1", "accountA", {"_uid": "AAA"})
    almost = datetime.now(UTC) - CHAOXING_SESSION_TTL + timedelta(hours=1)
    store.rows[(CHAOXING_SESSION_KIND, "user-1")]["saved_at"] = almost.isoformat()

    assert load_session("user-1")["cookies"] == {"_uid": "AAA"}


def test_touch_session_rolls_the_window_forward(store):
    save_session("user-1", "accountA", {"_uid": "AAA"})
    stale = datetime.now(UTC) - timedelta(days=6)
    store.rows[(CHAOXING_SESSION_KIND, "user-1")]["saved_at"] = stale.isoformat()

    touch_session("user-1")

    expires_at = datetime.fromisoformat(session_metadata("user-1")["expires_at"])
    assert expires_at - datetime.now(UTC) > CHAOXING_SESSION_TTL - timedelta(minutes=5)


def test_delete_session_drops_the_stored_jar(store):
    save_session("user-1", "accountA", {"_uid": "AAA"})

    delete_session("user-1")

    assert load_session("user-1") is None
    assert session_metadata("user-1") is None


def test_sessions_are_isolated_per_platform_user(store):
    save_session("user-1", "accountA", {"_uid": "AAA"})
    save_session("user-2", "accountB", {"_uid": "BBB"})

    assert load_session("user-1")["cookies"] == {"_uid": "AAA"}
    assert load_session("user-2")["cookies"] == {"_uid": "BBB"}
    delete_session("user-1")
    assert load_session("user-2")["cookies"] == {"_uid": "BBB"}


def test_manager_rehydrates_a_client_from_the_stored_session(store, monkeypatch):
    """A restart wipes _clients; the durable jar must rebuild the client."""
    save_session("user-1", "accountA", {"_uid": "AAA"})
    monkeypatch.setattr(signin_mod, "validate_session_cookies", lambda cookies: True)

    manager = _make_manager()
    assert manager._clients == {}

    client = manager.get_client("user-1")

    assert client is not None
    assert client.session.cookies.get("_uid") == "AAA"
    assert client.username == "accountA"
    # Cached afterwards, so the next call costs no Chaoxing round-trip.
    monkeypatch.setattr(
        signin_mod,
        "validate_session_cookies",
        lambda cookies: pytest.fail("cached client must not re-probe"),
    )
    assert manager.get_client("user-1") is client


def test_manager_drops_a_stored_session_that_no_longer_authenticates(store, monkeypatch):
    save_session("user-1", "accountA", {"_uid": "AAA"})
    monkeypatch.setattr(signin_mod, "validate_session_cookies", lambda cookies: False)

    manager = _make_manager()

    assert manager.get_client("user-1") is None
    assert load_session("user-1") is None


def test_manager_ignores_an_expired_stored_session(store, monkeypatch):
    save_session("user-1", "accountA", {"_uid": "AAA"})
    expired = datetime.now(UTC) - CHAOXING_SESSION_TTL - timedelta(minutes=1)
    store.rows[(CHAOXING_SESSION_KIND, "user-1")]["saved_at"] = expired.isoformat()
    monkeypatch.setattr(
        signin_mod,
        "validate_session_cookies",
        lambda cookies: pytest.fail("an expired jar must never reach the network"),
    )

    assert _make_manager().get_client("user-1") is None


def test_drop_session_forgets_cached_client_and_stored_jar(store, monkeypatch):
    save_session("user-1", "accountA", {"_uid": "AAA"})
    monkeypatch.setattr(signin_mod, "validate_session_cookies", lambda cookies: True)
    manager = _make_manager()
    assert manager.get_client("user-1") is not None

    manager.drop_session("user-1")

    assert manager._clients == {}
    assert load_session("user-1") is None
    assert manager.get_session_state("user-1") == {"active": False, "username": None, "expires_at": None}


def test_session_state_reports_account_and_expiry_without_cookies(store, monkeypatch):
    save_session("user-1", "accountA", {"_uid": "AAA"})
    monkeypatch.setattr(signin_mod, "validate_session_cookies", lambda cookies: True)

    state = _make_manager().get_session_state("user-1")

    assert state["active"] is True
    assert state["username"] == "accountA"
    assert state["expires_at"]
    assert set(state) == {"active", "username", "expires_at"}


# ---------------------------------------------------------------------------
# API contract
# ---------------------------------------------------------------------------


def test_session_endpoint_never_returns_cookies(store, monkeypatch):
    from fastapi.testclient import TestClient

    from tests.conftest import build_app

    save_session("local", "accountA", {"_uid": "super-secret-value"})
    monkeypatch.setattr(signin_mod, "validate_session_cookies", lambda cookies: True)

    with build_app("local", ENFORCE_HTTPS="false") as app:
        import app.api.v1.chaoxing as chaoxing_mod

        monkeypatch.setattr(chaoxing_mod, "signin_manager", _make_manager())
        client = TestClient(app, base_url="http://localhost")
        response = client.get("/api/v1/chaoxing/session")

    assert response.status_code == 200
    body = response.json()
    assert body["active"] is True
    assert body["username"] == "accountA"
    assert body["expires_at"]
    assert set(body) == {"active", "username", "expires_at"}
    assert "super-secret-value" not in response.text
    assert "cookie" not in response.text.lower()


def test_delete_session_endpoint_drops_the_session(store, monkeypatch):
    from fastapi.testclient import TestClient

    from tests.conftest import build_app

    save_session("local", "accountA", {"_uid": "AAA"})
    monkeypatch.setattr(signin_mod, "validate_session_cookies", lambda cookies: True)

    with build_app("local", ENFORCE_HTTPS="false") as app:
        import app.api.v1.chaoxing as chaoxing_mod

        monkeypatch.setattr(chaoxing_mod, "signin_manager", _make_manager())
        client = TestClient(app, base_url="http://localhost")
        response = client.delete("/api/v1/chaoxing/session")

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    assert load_session("local") is None


def test_session_endpoint_reports_inactive_when_nothing_is_stored(store, monkeypatch):
    from fastapi.testclient import TestClient

    from tests.conftest import build_app

    with build_app("local", ENFORCE_HTTPS="false") as app:
        import app.api.v1.chaoxing as chaoxing_mod

        monkeypatch.setattr(chaoxing_mod, "signin_manager", _make_manager())
        client = TestClient(app, base_url="http://localhost")
        response = client.get("/api/v1/chaoxing/session")

    assert response.status_code == 200
    assert response.json() == {"active": False, "username": None, "expires_at": None}
