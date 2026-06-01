from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.api.v1.chaoxing as chaoxing_api
import app.api.v1.course as course_api
import app.main as main_mod


class _FakeCursor:
    def __init__(self, execute_error=None):
        self._execute_error = execute_error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *a, **kw):
        if self._execute_error is not None:
            raise self._execute_error

    def fetchone(self):
        return (1,)


class _FakeConn:
    def __init__(self, execute_error=None):
        self.autocommit = False
        self._execute_error = execute_error

    def cursor(self):
        return _FakeCursor(self._execute_error)


def test_health_resets_autocommit_when_select_raises(monkeypatch):
    """If SELECT 1 raises mid-health-check, the pooled connection must NOT be
    left in autocommit=True — otherwise the next user of that pooled connection
    silently loses transactional rollback semantics."""
    fake_conn = _FakeConn(execute_error=RuntimeError("transient db blip"))

    @contextmanager
    def fake_session(db_name=None):
        yield fake_conn

    monkeypatch.setattr(main_mod, "get_db_session", fake_session)

    with pytest.raises(HTTPException) as exc_info:
        main_mod.health()

    assert exc_info.value.status_code == 503
    assert fake_conn.autocommit is False, "autocommit leaked True after SELECT 1 raised"


def test_health_resets_autocommit_on_success(monkeypatch):
    """Happy path: autocommit is restored to False after the probe."""
    fake_conn = _FakeConn()

    @contextmanager
    def fake_session(db_name=None):
        yield fake_conn

    monkeypatch.setattr(main_mod, "get_db_session", fake_session)

    result = main_mod.health()

    assert result["db"] == "ok"
    assert fake_conn.autocommit is False


import app.api.v1.metrics as metrics_mod
from starlette.requests import Request as StarletteRequest


def _metrics_request(authorization=None):
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("latin-1")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/metrics",
        "headers": headers,
        "query_string": b"",
    }
    return StarletteRequest(scope)


def test_metrics_open_when_no_token_configured(monkeypatch):
    monkeypatch.setattr(metrics_mod.settings, "METRICS_TOKEN", None, raising=False)
    resp = metrics_mod.metrics(_metrics_request())
    assert resp.status_code == 200


def test_metrics_rejects_missing_token_when_configured(monkeypatch):
    monkeypatch.setattr(metrics_mod.settings, "METRICS_TOKEN", "s3cret", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        metrics_mod.metrics(_metrics_request())
    assert exc_info.value.status_code == 401


def test_metrics_rejects_wrong_token_when_configured(monkeypatch):
    monkeypatch.setattr(metrics_mod.settings, "METRICS_TOKEN", "s3cret", raising=False)
    with pytest.raises(HTTPException) as exc_info:
        metrics_mod.metrics(_metrics_request(authorization="Bearer wrong"))
    assert exc_info.value.status_code == 401


def test_metrics_accepts_correct_token_when_configured(monkeypatch):
    monkeypatch.setattr(metrics_mod.settings, "METRICS_TOKEN", "s3cret", raising=False)
    resp = metrics_mod.metrics(_metrics_request(authorization="Bearer s3cret"))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_chaoxing_login_offloads_blocking_work(monkeypatch):
    request = chaoxing_api.ChaoxingLoginRequest(username="demo", password="secret", use_cookies=False)
    calls = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return {"status": True, "message": "ok", "data": {}}

    monkeypatch.setattr(chaoxing_api.asyncio, "to_thread", fake_to_thread)

    response = await chaoxing_api.chaoxing_login(request=request, user_id="7")

    assert response["status"] is True
    assert calls == [
        (
            chaoxing_api.signin_manager.login,
            (),
            {"user_id": "7", "username": "demo", "password": "secret"},
        )
    ]


@pytest.mark.asyncio
async def test_chaoxing_courses_offloads_blocking_work(monkeypatch):
    calls = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return [{"courseId": "101", "name": "Algorithms"}]

    monkeypatch.setattr(chaoxing_api.asyncio, "to_thread", fake_to_thread)

    response = await chaoxing_api.chaoxing_courses(user_id="9")

    assert response["data"] == [{"courseId": "101", "name": "Algorithms"}]
    assert calls == [
        (
            chaoxing_api.signin_manager.get_courses,
            ("9",),
            {},
        )
    ]


@pytest.mark.asyncio
async def test_zhihuishu_get_courses_hides_internal_error_details(monkeypatch):
    fake_adapter = SimpleNamespace(
        get_courses=lambda: (_ for _ in ()).throw(RuntimeError("upstream token=secret exploded"))
    )
    monkeypatch.setattr(course_api, "_get_zhihuishu_adapter", lambda user_id: fake_adapter)

    with pytest.raises(HTTPException) as exc_info:
        await course_api.zhihuishu_get_courses(current_user={"user_id": 1})

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to load Zhihuishu courses"
