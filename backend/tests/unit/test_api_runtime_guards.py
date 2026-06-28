from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request as StarletteRequest

import app.api.v1.chaoxing as chaoxing_api
import app.api.v1.course as course_api
import app.api.v1.metrics as metrics_mod


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


@pytest.mark.asyncio
async def test_course_start_reports_thread_exhaustion_as_service_unavailable(monkeypatch):
    class FakeLearningManager:
        def start_task(self, **kwargs):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(course_api, "_get_learning_manager", lambda: FakeLearningManager())

    request = course_api.CourseStartRequest(platform="chaoxing", username="demo", password="secret")

    with pytest.raises(HTTPException) as exc_info:
        await course_api.start_course_learning(request=request, current_user={"user_id": "7"})

    assert exc_info.value.status_code == 503
    assert "cannot start a new background thread" in exc_info.value.detail


@pytest.mark.asyncio
async def test_zhihuishu_qr_login_reports_thread_exhaustion_as_service_unavailable(monkeypatch):
    class FailingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(course_api.threading, "Thread", FailingThread)
    with course_api._qr_sessions_lock:
        course_api._qr_sessions.clear()

    with pytest.raises(HTTPException) as exc_info:
        await course_api.start_zhihuishu_qr_login(current_user={"user_id": "7"})

    assert exc_info.value.status_code == 503
    assert "cannot start a new background thread" in exc_info.value.detail
    with course_api._qr_sessions_lock:
        assert course_api._qr_sessions == {}


@pytest.mark.asyncio
async def test_zhihuishu_start_reports_thread_exhaustion_as_service_unavailable(monkeypatch):
    fake_adapter = SimpleNamespace(
        start_course=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("can't start new thread"))
    )
    monkeypatch.setattr(course_api, "_get_zhihuishu_adapter", lambda user_id: fake_adapter)

    request = course_api.ZhihuishuCourseRequest(course_id="course-1")

    with pytest.raises(HTTPException) as exc_info:
        await course_api.zhihuishu_start_course(request=request, current_user={"user_id": "7"})

    assert exc_info.value.status_code == 503
    assert "cannot start a new background thread" in exc_info.value.detail
