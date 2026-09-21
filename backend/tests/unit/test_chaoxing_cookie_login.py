"""Regression tests for the Chaoxing cookie-reuse path.

The legacy shared `/tmp/cookies.json` jar (`cookies.use_cookies`) is gone: one
file served every caller, so a jar could be adopted by a request with no claim
to it. Sessions are now bound to a Chaoxing account and refused when nothing
binds them. These tests pin that contract, including the failure message the
callers match on.
"""

import json

from app.services.course.chaoxing import cookies
from app.services.course.chaoxing.auth_service import ChaoxingAuthService
from app.services.course.chaoxing.session_manager import SessionManager


def _service():
    return ChaoxingAuthService(session_manager=SessionManager())


def test_cookie_login_refuses_a_jar_nothing_binds_to_an_account(tmp_path, monkeypatch):
    """A present, valid-looking jar is still refused when no account binds it.

    A stored jar authenticates with no password and no MFA, so without an
    account to bind it against there is no way to prove it belongs to the
    caller. `cookies.use_cookies()` — the reader for this file — has no caller
    left; what remains is the guarantee, not the loader.
    """
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(json.dumps({"_uid": "12345", "fid": "42"}))
    monkeypatch.setattr(cookies, "COOKIES_FILE", cookie_file)

    service = _service()
    monkeypatch.setattr(service, "_validate_cookie_session", lambda: True)

    result = service.login(login_with_cookies=True)

    assert result == {"status": False, "msg": "cookies 已失效，请更新 cookies 或提供账号密码"}
    assert service.session_manager.get_session().cookies.get("_uid") is None


def test_cookie_login_keeps_missing_file_failure_semantics(tmp_path, monkeypatch):
    monkeypatch.setattr(cookies, "COOKIES_FILE", tmp_path / "missing-cookies.json")

    service = _service()

    result = service.login(login_with_cookies=True)

    assert result == {"status": False, "msg": "cookies 已失效，请更新 cookies 或提供账号密码"}
    assert service.session_manager.get_session().cookies.get("_uid") is None


def test_cookie_login_keeps_invalid_file_failure_semantics(tmp_path, monkeypatch):
    cookie_file = tmp_path / "invalid-cookies.json"
    cookie_file.write_text("not-json")
    monkeypatch.setattr(cookies, "COOKIES_FILE", cookie_file)

    service = _service()

    result = service.login(login_with_cookies=True)

    assert result == {"status": False, "msg": "cookies 已失效，请更新 cookies 或提供账号密码"}
    assert service.session_manager.get_session().cookies.get("_uid") is None
