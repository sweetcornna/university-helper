"""Task polling must preserve task identity and keep active platform sessions alive."""

import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.api.v1 import course as course_api


@pytest.fixture(autouse=True)
def isolated_registries(monkeypatch):
    monkeypatch.setattr(course_api, "_user_adapters", {})
    monkeypatch.setattr(course_api, "_course_tasks", {})
    monkeypatch.setattr(course_api, "_qr_sessions", {})


def _register_task(task_id="old-task", status="completed"):
    task = {
        "task_id": task_id,
        "platform": "zhihuishu",
        "user_id": "1",
        "course_id": "course-1",
        "status": status,
        "message": "Original task",
        "progress": {"completed": 2, "total": 2},
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    course_api._course_tasks[task_id] = task
    return task


@pytest.mark.asyncio
async def test_status_uses_requested_task_instead_of_latest_course_progress(monkeypatch):
    _register_task()
    requested_progress = {"task_id": "old-task", "status": "completed", "completed": 2, "total": 2}
    adapter = SimpleNamespace(get_task=Mock(return_value=requested_progress), get_progress=Mock())
    course_api._user_adapters["1"] = {"adapter": adapter, "last_access": 0}
    monkeypatch.setattr(course_api, "_get_learning_manager", lambda: SimpleNamespace(get_task=lambda **kw: None))

    response = await course_api.get_course_status("old-task", current_user={"user_id": 1})

    assert response.status == "completed"
    assert response.progress["completed"] == 2
    adapter.get_task.assert_called_once_with("old-task")
    adapter.get_progress.assert_not_called()
    assert course_api._user_adapters["1"]["last_access"] > 0


@pytest.mark.asyncio
async def test_legacy_status_does_not_copy_another_task_progress(monkeypatch):
    original = _register_task()
    adapter = SimpleNamespace(
        get_progress=lambda course_id: {"task_id": "new-task", "status": "running", "completed": 0}
    )
    course_api._user_adapters["1"] = {"adapter": adapter, "last_access": time.time()}
    monkeypatch.setattr(course_api, "_get_learning_manager", lambda: SimpleNamespace(get_task=lambda **kw: None))

    response = await course_api.get_course_status("old-task", current_user={"user_id": 1})

    assert response.status == "completed"
    assert response.progress == original["progress"]


@pytest.mark.asyncio
async def test_status_preserves_record_when_adapter_no_longer_has_task(monkeypatch):
    _register_task(status="failed")
    course_api._user_adapters["1"] = {
        "adapter": SimpleNamespace(get_task=lambda task_id: None),
        "last_access": time.time(),
    }
    monkeypatch.setattr(course_api, "_get_learning_manager", lambda: SimpleNamespace(get_task=lambda **kw: None))

    response = await course_api.get_course_status("old-task", current_user={"user_id": 1})

    assert response.status == "failed"
    assert response.progress == {"completed": 2, "total": 2}


@pytest.mark.parametrize("status", ["running", "paused", "pending"])
def test_cleanup_keeps_active_adapter_without_browser_polling(status):
    adapter = SimpleNamespace(get_status=lambda: {"has_task": True, "current_task": {"status": status}})
    course_api._user_adapters["1"] = {"adapter": adapter, "last_access": 0}

    course_api.cleanup_expired_entries()

    assert course_api._user_adapters["1"]["adapter"] is adapter


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "error"])
def test_cleanup_expires_inactive_adapter(status):
    adapter = SimpleNamespace(get_status=lambda: {"has_task": True, "current_task": {"status": status}})
    course_api._user_adapters["1"] = {"adapter": adapter, "last_access": 0}

    course_api.cleanup_expired_entries()

    assert "1" not in course_api._user_adapters


def test_cleanup_keeps_legacy_adapter_with_running_registered_task():
    _register_task(status="running")
    course_api._user_adapters["1"] = {"adapter": object(), "last_access": 0}

    course_api.cleanup_expired_entries()

    assert "1" in course_api._user_adapters


def test_cleanup_does_not_remove_session_refreshed_during_inspection():
    entry = {"last_access": 0}

    def get_status():
        entry["last_access"] = time.time()
        return {"has_task": False, "current_task": None}

    entry["adapter"] = SimpleNamespace(get_status=get_status)
    course_api._user_adapters["1"] = entry

    course_api.cleanup_expired_entries()

    assert course_api._user_adapters["1"] is entry


def test_cleanup_does_not_remove_replacement_login():
    replacement = {"adapter": object(), "last_access": time.time()}

    def get_status():
        course_api._user_adapters["1"] = replacement
        return {"has_task": False, "current_task": None}

    course_api._user_adapters["1"] = {"adapter": SimpleNamespace(get_status=get_status), "last_access": 0}

    course_api.cleanup_expired_entries()

    assert course_api._user_adapters["1"] is replacement


def test_cleanup_keeps_adapter_when_task_inspection_fails():
    def get_status():
        raise RuntimeError("Temporary status failure")

    course_api._user_adapters["1"] = {"adapter": SimpleNamespace(get_status=get_status), "last_access": 0}

    course_api.cleanup_expired_entries()

    assert "1" in course_api._user_adapters


@pytest.mark.asyncio
async def test_password_login_cancels_older_qr_login_for_same_user(monkeypatch):
    own_cancel = course_api.threading.Event()
    other_cancel = course_api.threading.Event()
    course_api._qr_sessions.update(
        {
            "old-qr": {"user_id": "1", "cancel_event": own_cancel},
            "other-user-qr": {"user_id": "2", "cancel_event": other_cancel},
        }
    )
    adapter = SimpleNamespace(login_with_password=lambda username, password: {"success": True})
    monkeypatch.setattr(course_api, "ZhihuishuAdapter", lambda: adapter)

    result = await course_api.zhihuishu_password_login(
        course_api.ZhihuishuPasswordLoginRequest(username="demo", password="test"),
        current_user={"user_id": 1},
    )

    assert result["status"] == "success"
    assert own_cancel.is_set()
    assert "old-qr" not in course_api._qr_sessions
    assert not other_cancel.is_set()
    assert "other-user-qr" in course_api._qr_sessions
    assert course_api._user_adapters["1"]["adapter"] is adapter
