from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.api.v1.chaoxing as chaoxing_api
import app.api.v1.course as course_api


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
