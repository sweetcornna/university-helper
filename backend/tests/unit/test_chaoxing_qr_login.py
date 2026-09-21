"""学习通 QR-code login: the protocol module and the manager that drives it.

The protocol lives in ``chaoxing/qr_login.py`` (pure functions over a
``requests.Session``) and the orchestration in ``ChaoxingSigninManager``. Both
are exercised offline: every upstream call is a fake session, every store call
is the in-memory backend used by ``test_chaoxing_session.py``.

The behaviour that matters is not "a QR is displayed" but that a confirmed scan
produces the SAME durable, account-bound session a password login does — that is
what lets the 签到 and 泛雅 pages share one login.
"""

import json
import types

import pytest
import requests

import app.services.course.chaoxing.cookies as cookies_mod
import app.services.course.chaoxing.qr_login as qr_mod
import app.services.course.chaoxing.signin as signin_mod
import app.services.course.task_store as task_store_mod
from app.services.course.chaoxing.cookies import (
    CHAOXING_SESSION_KIND,
    load_session,
)
from app.services.course.chaoxing.qr_login import ChaoxingQrError
from app.services.course.chaoxing.signin import ChaoxingSigninManager

UUID = "a" * 32
ENC = "b" * 32

LOGIN_PAGE_HTML = f'<html><body><input id="uuid" value="{UUID}"><input id="enc" value="{ENC}"></body></html>'


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
        return dict(row) if row else None

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
    backend = FakeTaskBackend()
    monkeypatch.setattr(task_store_mod, "get_storage", lambda: types.SimpleNamespace(tasks=backend))
    monkeypatch.setattr(cookies_mod, "COOKIES_DIR", tmp_path)
    monkeypatch.setattr(cookies_mod, "COOKIES_FILE", tmp_path / "cookies.json")
    return backend


@pytest.fixture
def manager(store, monkeypatch):
    """A manager whose stored sessions always validate."""
    monkeypatch.setattr(signin_mod, "validate_session_cookies", lambda cookies: True)
    return ChaoxingSigninManager()


class FakeResponse:
    def __init__(self, *, text="", content=b"", payload=None, content_type="image/png", status_code=200):
        self.text = text
        self.content = content
        self._payload = payload
        self.headers = {"content-type": content_type}
        self.status_code = status_code

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class FakeSession:
    """Records requests and replays canned responses, keyed by URL fragment."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.cookies = requests.cookies.RequestsCookieJar()

    def _respond(self, url):
        self.calls.append(url)
        for fragment, response in self.routes.items():
            if fragment in url:
                return response(url) if callable(response) else response
        raise AssertionError(f"unexpected request: {url}")

    def get(self, url, **kwargs):
        return self._respond(url)

    def post(self, url, **kwargs):
        return self._respond(url)


def _qr_ready_session(poll_payload):
    return FakeSession(
        {
            "mlogin": FakeResponse(text=LOGIN_PAGE_HTML),
            "createqr": FakeResponse(content=b"\x89PNG-qr-bytes"),
            "getauthstatus": FakeResponse(payload=poll_payload),
        }
    )


# ---------------------------------------------------------------------------
# Protocol module
# ---------------------------------------------------------------------------


def test_create_qr_session_extracts_uuid_enc_and_image():
    session = _qr_ready_session({"status": False, "type": 0})

    result = qr_mod.create_qr_session(session)

    assert result["uuid"] == UUID
    assert result["enc"] == ENC
    assert result["image"] == b"\x89PNG-qr-bytes"
    assert result["content_type"] == "image/png"


def test_create_qr_session_rejects_a_page_without_usable_fields():
    """A changed login page must fail loudly, not yield an unscannable image."""
    session = FakeSession({"mlogin": FakeResponse(text="<html><body>nothing here</body></html>")})

    with pytest.raises(ChaoxingQrError):
        qr_mod.create_qr_session(session)


def test_declared_jpeg_is_corrected_when_the_bytes_are_png():
    """Upstream really does serve a PNG while declaring `image/jpeg`.

    The SPA puts this in a `data:` URI, where the declared type is what the
    browser believes, so the magic bytes win over the header.
    """
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    session = FakeSession({"createqr": FakeResponse(content=png, content_type="image/jpeg")})

    result = qr_mod.fetch_qr_image(session, UUID, ENC)

    assert result["content_type"] == "image/png"


def test_a_genuine_jpeg_keeps_its_declared_type():
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 16
    session = FakeSession({"createqr": FakeResponse(content=jpeg, content_type="image/jpeg")})

    result = qr_mod.fetch_qr_image(session, UUID, ENC)

    assert result["content_type"] == "image/jpeg"


def test_an_empty_image_is_an_error():
    session = FakeSession({"createqr": FakeResponse(content=b"")})

    with pytest.raises(ChaoxingQrError):
        qr_mod.fetch_qr_image(session, UUID, ENC)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"status": True}, qr_mod.QR_STATUS_CONFIRMED),
        ({"status": False, "type": 4}, qr_mod.QR_STATUS_SCANNED),
        ({"status": False, "type": 6}, qr_mod.QR_STATUS_EXPIRED),
        ({"status": False, "type": 0}, qr_mod.QR_STATUS_PENDING),
        # A missing / unparsable type must degrade to "keep waiting", not crash.
        ({"status": False}, qr_mod.QR_STATUS_PENDING),
        ({"status": False, "type": "nonsense"}, qr_mod.QR_STATUS_PENDING),
    ],
)
def test_poll_qr_login_maps_upstream_status(payload, expected):
    """`type` 4 = scanned, 6 = expired; `status: true` is the only confirmation."""
    session = _qr_ready_session(payload)

    assert qr_mod.poll_qr_login(session, UUID, ENC) == expected


def test_poll_qr_login_rejects_a_non_json_body():
    session = FakeSession({"getauthstatus": FakeResponse(text="<html>nope</html>")})

    with pytest.raises(ChaoxingQrError):
        qr_mod.poll_qr_login(session, UUID, ENC)


def test_fetch_profile_returns_identity():
    session = FakeSession(
        {
            "userLogin4Uname": FakeResponse(
                payload={"msg": {"uid": "999", "puid": "888", "fid": "1", "name": "张三", "uname": "student01"}}
            )
        }
    )

    profile = qr_mod.fetch_profile(session)

    assert profile["uid"] == "999"
    assert profile["uname"] == "student01"
    assert profile["name"] == "张三"


def test_fetch_profile_without_a_uid_is_an_error():
    session = FakeSession({"userLogin4Uname": FakeResponse(payload={"msg": {"name": "张三"}})})

    with pytest.raises(ChaoxingQrError):
        qr_mod.fetch_profile(session)


# ---------------------------------------------------------------------------
# Manager orchestration
# ---------------------------------------------------------------------------


def _stub_protocol(monkeypatch, *, poll_state, profile=None, refresh_uuid=None):
    """Replace the network-facing protocol functions with fakes."""
    created = {"n": 0}

    def _create(session):
        created["n"] += 1
        return {
            "uuid": refresh_uuid or f"{created['n']:032x}",
            "enc": ENC,
            "image": b"PNG-" + str(created["n"]).encode(),
            "content_type": "image/png",
        }

    monkeypatch.setattr(qr_mod, "create_qr_session", _create)
    monkeypatch.setattr(qr_mod, "poll_qr_login", lambda session, uuid, enc: poll_state)
    if profile is not None:
        monkeypatch.setattr(qr_mod, "fetch_profile", lambda session: profile)
    return created


def test_start_qr_login_returns_an_image_and_a_session_id(manager, monkeypatch):
    _stub_protocol(monkeypatch, poll_state=qr_mod.QR_STATUS_PENDING)

    result = manager.start_qr_login("u1")

    assert result["qr_status"] == "pending"
    assert result["session_id"]
    assert result["qr_code"] == "UE5HLTE="  # base64 of b"PNG-1"
    assert result["qr_content_type"] == "image/png"
    assert result["session_id"] in manager._qr_sessions


def test_poll_reports_not_found_for_an_unknown_session(manager):
    result = manager.poll_qr_login("u1", "does-not-exist")

    assert result["qr_status"] == "not_found"


def test_poll_reports_not_found_for_another_users_session(manager, monkeypatch):
    """Session ids must not be usable to probe for someone else's login."""
    _stub_protocol(monkeypatch, poll_state=qr_mod.QR_STATUS_PENDING)
    started = manager.start_qr_login("u1")

    result = manager.poll_qr_login("u2", started["session_id"])

    assert result["qr_status"] == "not_found"
    assert started["session_id"] in manager._qr_sessions  # untouched


def test_expired_qr_is_refreshed_in_place(manager, monkeypatch):
    """The browser keeps polling the same id, so the new image rides back here."""
    created = _stub_protocol(monkeypatch, poll_state=qr_mod.QR_STATUS_EXPIRED)
    started = manager.start_qr_login("u1")
    first_uuid = manager._qr_sessions[started["session_id"]]["uuid"]

    result = manager.poll_qr_login("u1", started["session_id"])

    assert result["qr_status"] == "pending"
    assert result["qr_code"]  # a fresh image came back
    assert created["n"] == 2
    assert manager._qr_sessions[started["session_id"]]["uuid"] != first_uuid


def test_scan_and_confirm_persists_the_same_session_a_password_login_would(manager, monkeypatch):
    """The whole point: a scan yields a durable, account-bound session."""
    _stub_protocol(
        monkeypatch,
        poll_state=qr_mod.QR_STATUS_CONFIRMED,
        profile={"uid": "999", "puid": "888", "fid": "1", "name": "张三", "uname": "student01"},
    )
    started = manager.start_qr_login("u1")
    entry = manager._qr_sessions[started["session_id"]]
    client = entry["client"]
    # Upstream confirms the credentials by leaving an authenticated cookie.
    client.session.cookies.set("_d", "session-token")

    result = manager.poll_qr_login("u1", started["session_id"])

    assert result["qr_status"] == "success"
    assert result["username"] == "student01"
    # The uid cookie the QR flow omits is seeded from the profile — without it
    # every later sign-in request would carry an empty uid.
    assert client.session.cookies.get("_uid") == "999"
    stored = load_session("u1", expected_username="student01")
    assert stored is not None
    assert stored["username"] == "student01"
    # Cached, so the next request needs no rehydration round-trip.
    assert manager._clients["u1"] is client
    # The finished QR session is dropped, not left to be swept later.
    assert started["session_id"] not in manager._qr_sessions


def test_confirmed_scan_that_fails_validation_does_not_persist(manager, monkeypatch):
    _stub_protocol(
        monkeypatch,
        poll_state=qr_mod.QR_STATUS_CONFIRMED,
        profile={"uid": "999", "puid": "888", "fid": "1", "name": "张三", "uname": "student01"},
    )
    monkeypatch.setattr(signin_mod, "validate_session_cookies", lambda cookies: False)
    started = manager.start_qr_login("u1")

    result = manager.poll_qr_login("u1", started["session_id"])

    assert result["qr_status"] == "failed"
    assert load_session("u1") is None
    assert manager._clients == {}


def test_cancel_drops_the_session(manager, monkeypatch):
    _stub_protocol(monkeypatch, poll_state=qr_mod.QR_STATUS_PENDING)
    started = manager.start_qr_login("u1")

    assert manager.cancel_qr_login("u1", started["session_id"]) is True
    assert manager.cancel_qr_login("u1", started["session_id"]) is False
    assert manager.poll_qr_login("u1", started["session_id"])["qr_status"] == "not_found"


def test_cancel_refuses_another_users_session(manager, monkeypatch):
    _stub_protocol(monkeypatch, poll_state=qr_mod.QR_STATUS_PENDING)
    started = manager.start_qr_login("u1")

    assert manager.cancel_qr_login("u2", started["session_id"]) is False
    assert started["session_id"] in manager._qr_sessions


def test_abandoned_qr_sessions_are_swept_after_the_ttl(manager, monkeypatch):
    _stub_protocol(monkeypatch, poll_state=qr_mod.QR_STATUS_PENDING)
    started = manager.start_qr_login("u1")
    # Age it past the TTL rather than waiting.
    manager._qr_sessions[started["session_id"]]["created_at"] = 0.0

    manager._cleanup_qr_sessions()

    assert manager._qr_sessions == {}


def test_qr_sessions_are_not_persisted_to_the_store(manager, monkeypatch, store):
    """A half-finished scan is browser-tied; nothing about it belongs in the DB."""
    _stub_protocol(monkeypatch, poll_state=qr_mod.QR_STATUS_PENDING)

    manager.start_qr_login("u1")

    assert store.rows == {}


# ---------------------------------------------------------------------------
# HTTP contract
# ---------------------------------------------------------------------------


def test_qr_login_endpoint_returns_an_image(store, monkeypatch):
    monkeypatch.setattr(signin_mod, "validate_session_cookies", lambda cookies: True)
    _stub_protocol(monkeypatch, poll_state=qr_mod.QR_STATUS_PENDING)

    from fastapi.testclient import TestClient

    from tests.conftest import build_app

    with build_app("local", ENFORCE_HTTPS="false") as app:
        import app.api.v1.chaoxing as chaoxing_mod

        monkeypatch.setattr(chaoxing_mod, "signin_manager", ChaoxingSigninManager())
        response = TestClient(app, base_url="http://localhost").post("/api/v1/chaoxing/qr-login")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["qr_code"]
    assert body["session_id"]


def test_qr_login_endpoint_reports_upstream_failure_as_502(store, monkeypatch):
    """No session was created, so there is nothing to poll — not a client error."""
    monkeypatch.setattr(signin_mod, "validate_session_cookies", lambda cookies: True)

    def _boom(session):
        raise ChaoxingQrError("学习通扫码登录页没有返回二维码参数，请稍后重试")

    monkeypatch.setattr(qr_mod, "create_qr_session", _boom)

    from fastapi.testclient import TestClient

    from tests.conftest import build_app

    with build_app("local", ENFORCE_HTTPS="false") as app:
        import app.api.v1.chaoxing as chaoxing_mod

        monkeypatch.setattr(chaoxing_mod, "signin_manager", ChaoxingSigninManager())
        response = TestClient(app, base_url="http://localhost").post("/api/v1/chaoxing/qr-login")

    assert response.status_code == 502


def test_qr_status_endpoint_404s_for_an_unknown_session(store, monkeypatch):
    monkeypatch.setattr(signin_mod, "validate_session_cookies", lambda cookies: True)

    from fastapi.testclient import TestClient

    from tests.conftest import build_app

    with build_app("local", ENFORCE_HTTPS="false") as app:
        import app.api.v1.chaoxing as chaoxing_mod

        monkeypatch.setattr(chaoxing_mod, "signin_manager", ChaoxingSigninManager())
        response = TestClient(app, base_url="http://localhost").get("/api/v1/chaoxing/qr-login/nope")

    assert response.status_code == 404


def test_qr_cancel_endpoint_404s_for_an_unknown_session(store, monkeypatch):
    monkeypatch.setattr(signin_mod, "validate_session_cookies", lambda cookies: True)

    from fastapi.testclient import TestClient

    from tests.conftest import build_app

    with build_app("local", ENFORCE_HTTPS="false") as app:
        import app.api.v1.chaoxing as chaoxing_mod

        monkeypatch.setattr(chaoxing_mod, "signin_manager", ChaoxingSigninManager())
        response = TestClient(app, base_url="http://localhost").delete("/api/v1/chaoxing/qr-login/nope")

    assert response.status_code == 404
