"""Regression tests for Chaoxing CLI cookie login."""

import json

from app.services.course.chaoxing import cookies
from app.services.course.chaoxing.auth_service import ChaoxingAuthService
from app.services.course.chaoxing.session_manager import SessionManager


def _service():
    return ChaoxingAuthService(session_manager=SessionManager())


def test_cookie_login_loads_file_cookies_into_existing_session(tmp_path, monkeypatch):
    cookie_file = tmp_path / "cookies.json"
    cookie_file.write_text(json.dumps({"_uid": "12345", "fid": "42"}))
    monkeypatch.setattr(cookies, "COOKIES_FILE", cookie_file)

    service = _service()
    monkeypatch.setattr(service, "_validate_cookie_session", lambda: True)

    result = service.login(login_with_cookies=True)

    assert result == {"status": True, "msg": "登录成功"}
    assert service.session_manager.get_session().cookies.get_dict() == {"_uid": "12345", "fid": "42"}


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
