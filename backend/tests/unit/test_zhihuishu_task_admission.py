"""Concurrency and admission contracts for Zhihuishu course tasks."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import app.api.v1.course as course_api
import app.services.course.zhihuishu.adapter as adapter_module
from app.services.course.zhihuishu.adapter import (
    TASK_CONFLICT_DETAIL,
    ZhihuishuAdapter,
    ZhihuishuTaskConflictError,
)


def _videos(course_id: str) -> list[dict]:
    return [
        {
            "id": f"video-{course_id}",
            "video_id": f"video-{course_id}",
            "title": f"Video {course_id}",
            "video_sec": 1,
            "questions": [],
        }
    ]


def _adapter(monkeypatch: pytest.MonkeyPatch) -> ZhihuishuAdapter:
    adapter = ZhihuishuAdapter()
    adapter.learning = object()
    monkeypatch.setattr(adapter, "get_videos", _videos)
    return adapter


def _patch_thread(monkeypatch: pytest.MonkeyPatch, thread_type: type) -> None:
    # Patch the adapter's module binding instead of the shared threading module;
    # ThreadPoolExecutor must retain a real worker implementation for barriers.
    monkeypatch.setattr(
        adapter_module,
        "threading",
        SimpleNamespace(Lock=threading.Lock, Thread=thread_type),
    )


class _NoopThread:
    starts = 0

    def __init__(self, *args, **kwargs):
        del args, kwargs
        type(self).starts += 1

    def start(self):
        return None


def test_second_course_does_not_orphan_first_task(monkeypatch: pytest.MonkeyPatch):
    _NoopThread.starts = 0
    _patch_thread(monkeypatch, _NoopThread)
    adapter = _adapter(monkeypatch)

    first = adapter.start_course("course-a")
    first_progress = adapter.get_progress("course-a")

    with pytest.raises(ZhihuishuTaskConflictError) as exc_info:
        adapter.start_course("course-b")

    assert exc_info.value.detail == TASK_CONFLICT_DETAIL
    assert adapter._task_state is not None
    assert adapter._task_state["task_id"] == first["task_id"]
    assert adapter.get_progress("course-a") == first_progress
    assert list(adapter._tasks) == [first["task_id"]]
    assert _NoopThread.starts == 1


def test_concurrent_starts_admit_one_and_start_one_worker(monkeypatch: pytest.MonkeyPatch):
    _NoopThread.starts = 0
    _patch_thread(monkeypatch, _NoopThread)
    adapter = ZhihuishuAdapter()
    adapter.learning = object()
    barrier = threading.Barrier(2)

    def get_videos(course_id: str) -> list[dict]:
        barrier.wait(timeout=5)
        return _videos(course_id)

    monkeypatch.setattr(adapter, "get_videos", get_videos)

    def start(course_id: str):
        try:
            return (adapter.start_course(course_id), None)
        except ZhihuishuTaskConflictError as exc:
            return (None, exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(start, ("course-a", "course-b")))

    admitted = [result for result, error in outcomes if result is not None and error is None]
    rejected = [error for result, error in outcomes if result is None and error is not None]
    assert len(admitted) == 1
    assert len(rejected) == 1
    assert rejected[0].detail == TASK_CONFLICT_DETAIL
    assert len(adapter._tasks) == 1
    assert _NoopThread.starts == 1


@pytest.mark.parametrize("terminal_status", ("completed", "failed", "cancelled", "error"))
def test_terminal_task_allows_next_start(monkeypatch: pytest.MonkeyPatch, terminal_status: str):
    _NoopThread.starts = 0
    _patch_thread(monkeypatch, _NoopThread)
    adapter = _adapter(monkeypatch)

    first = adapter.start_course("course-a")
    with adapter._task_lock:
        assert adapter._task_state is not None
        adapter._task_state["status"] = terminal_status

    second = adapter.start_course("course-b")

    assert second["task_id"] != first["task_id"]
    assert len(adapter._tasks) == 2
    assert _NoopThread.starts == 2


@pytest.mark.parametrize("control", ("running", "paused", "stopping"))
def test_active_task_rejects_next_start(monkeypatch: pytest.MonkeyPatch, control: str):
    _NoopThread.starts = 0
    _patch_thread(monkeypatch, _NoopThread)
    adapter = _adapter(monkeypatch)

    first = adapter.start_course("course-a")
    if control == "paused":
        adapter.pause_task()
    elif control == "stopping":
        with adapter._task_lock:
            assert adapter._task_state is not None
            adapter._task_state["status"] = "stopping"

    with pytest.raises(ZhihuishuTaskConflictError):
        adapter.start_course("course-b")

    assert adapter._task_state is not None
    assert adapter._task_state["task_id"] == first["task_id"]
    assert adapter.get_progress("course-a")["status"] == control
    assert len(adapter._tasks) == 1
    assert _NoopThread.starts == 1


def test_thread_start_failure_marks_terminal_without_holding_task_lock(monkeypatch: pytest.MonkeyPatch):
    lock_states: list[bool] = []
    adapter = _adapter(monkeypatch)

    class FailingThread:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def start(self):
            lock_states.append(adapter._task_lock.locked())
            raise RuntimeError("can't start new thread")

    _patch_thread(monkeypatch, FailingThread)

    with pytest.raises(RuntimeError, match="cannot start a new background thread"):
        adapter.start_course("course-a")

    assert lock_states == [False]
    assert adapter.get_progress("course-a")["status"] == "error"


def test_oserror_during_thread_start_marks_error_and_allows_restart(monkeypatch: pytest.MonkeyPatch):
    lock_states: list[bool] = []
    adapter = _adapter(monkeypatch)

    class FailingThread:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def start(self):
            lock_states.append(adapter._task_lock.locked())
            raise OSError("resource temporarily unavailable")

    _patch_thread(monkeypatch, FailingThread)

    with pytest.raises(RuntimeError, match="cannot start a new background thread"):
        adapter.start_course("course-a")

    assert lock_states == [False]
    assert adapter.get_progress("course-a")["status"] == "error"
    assert adapter._task_state is not None
    failed_task_id = adapter._task_state["task_id"]

    _NoopThread.starts = 0
    _patch_thread(monkeypatch, _NoopThread)
    restarted = adapter.start_course("course-b")

    assert restarted["task_id"]
    assert restarted["task_id"] != failed_task_id
    assert adapter._tasks[failed_task_id]["status"] == "error"
    assert len(adapter._tasks) == 2
    assert _NoopThread.starts == 1


class _ConflictAdapter:
    def get_config(self):
        return {"speed": 1.0, "auto_answer": True}

    def start_course_task(self, *args, **kwargs):
        del args, kwargs
        raise ZhihuishuTaskConflictError()

    def start_ai_course_task(self, *args, **kwargs):
        del args, kwargs
        raise ZhihuishuTaskConflictError()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "payload"),
    (
        (
            course_api.zhihuishu_start_course,
            course_api.ZhihuishuCourseRequest(course_id="course-a"),
        ),
        (
            course_api.zhihuishu_start_course_task,
            course_api.ZhihuishuTaskStartRequest(course_id="course-a"),
        ),
        (
            course_api.zhihuishu_start_ai_course_task,
            course_api.ZhihuishuTaskStartRequest(course_id="course-a"),
        ),
    ),
)
async def test_all_zhihuishu_start_endpoints_map_conflict_to_common_409(
    monkeypatch: pytest.MonkeyPatch, endpoint, payload
):
    monkeypatch.setattr(course_api, "_get_zhihuishu_adapter", lambda user_id: _ConflictAdapter())

    with pytest.raises(HTTPException) as exc_info:
        await endpoint(payload, current_user={"user_id": "user-1"})

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == TASK_CONFLICT_DETAIL
