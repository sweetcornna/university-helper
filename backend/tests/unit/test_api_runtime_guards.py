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
