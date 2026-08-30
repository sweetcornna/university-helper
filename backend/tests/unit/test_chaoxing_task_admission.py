"""Concurrency and retention contracts for Chaoxing background tasks."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import app.api.v1.chaoxing as chaoxing_api
import app.api.v1.course as course_api
import app.services.course.chaoxing.learning_manager as learning_module
import app.services.course.chaoxing.signin as signin_module
from app.services.course.chaoxing.learning_manager import ChaoxingLearningManager
from app.services.course.chaoxing.signin import ChaoxingSigninManager
from app.services.course.chaoxing.task_admission import (
    MAX_ACTIVE_TASKS,
    MAX_TASK_RECORDS,
    TASK_ALREADY_ACTIVE_DETAIL,
    TASK_CAPACITY_DETAIL,
    TASK_RECORD_TTL_SECONDS,
    TaskAdmissionError,
    TaskAlreadyActiveError,
    TaskCapacityError,
    is_active_status,
)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _bare_manager(manager_type):
    manager = manager_type.__new__(manager_type)
    manager._lock = threading.Lock()
    manager._tasks = {}
    manager._loaded_task_users = set()
    manager._persist_task_state = lambda *args, **kwargs: None
    if manager_type is ChaoxingSigninManager:
        manager._clients = {}
        manager._history = {}
        manager._loaded_history_users = set()
    return manager


class _StartedThread:
    starts = 0

    def __init__(self, *args, **kwargs):
        del args, kwargs

    def start(self):
        type(self).starts += 1


@pytest.mark.parametrize(
    ("manager_type", "module", "payload"),
    [
        (ChaoxingLearningManager, learning_module, {"tiku_config": {}}),
        (ChaoxingSigninManager, signin_module, {}),
    ],
)
def test_duplicate_user_admission_does_not_create_second_task(monkeypatch, manager_type, module, payload):
    manager = _bare_manager(manager_type)
    _StartedThread.starts = 0
    monkeypatch.setattr(module.threading, "Thread", _StartedThread)

    first_id = manager.start_task("same-user", payload)

    with pytest.raises(TaskAdmissionError) as exc_info:
        manager.start_task("same-user", payload)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == TASK_ALREADY_ACTIVE_DETAIL
    assert len(manager._tasks) == 1
    assert first_id in manager._tasks
    assert _StartedThread.starts == 1


@pytest.mark.parametrize(
    ("manager_type", "module", "payload"),
    [
        (ChaoxingLearningManager, learning_module, {"tiku_config": {}}),
        (ChaoxingSigninManager, signin_module, {}),
    ],
)
def test_active_task_cap_is_atomic_under_concurrent_starts(monkeypatch, manager_type, module, payload):
    manager = _bare_manager(manager_type)
    # Keep real ``threading.Thread`` available to the executor itself.  The
    # manager worker is a no-op so admitted tasks cannot perform network work.
    monkeypatch.setattr(manager, "_run_task_worker_guarded", lambda *args, **kwargs: None)
    barrier = threading.Barrier(MAX_ACTIVE_TASKS + 16)

    def start_one(index: int):
        barrier.wait(timeout=5)
        try:
            return manager.start_task(f"user-{index}", payload), None
        except TaskAdmissionError as exc:
            return None, exc

    with ThreadPoolExecutor(max_workers=MAX_ACTIVE_TASKS + 16) as pool:
        outcomes = list(pool.map(start_one, range(MAX_ACTIVE_TASKS + 16)))

    admitted = [task_id for task_id, error in outcomes if task_id is not None and error is None]
    rejected = [error for task_id, error in outcomes if task_id is None and error is not None]
    assert len(admitted) == MAX_ACTIVE_TASKS
    assert len(rejected) == 16
    assert all(error.status_code == 429 and error.detail == TASK_CAPACITY_DETAIL for error in rejected)
    assert len(manager._tasks) == MAX_ACTIVE_TASKS


@pytest.mark.parametrize(
    ("manager_type", "module", "payload"),
    [
        (ChaoxingLearningManager, learning_module, {"tiku_config": {}}),
        (ChaoxingSigninManager, signin_module, {}),
    ],
)
def test_terminal_records_are_ttl_and_hard_cap_bounded(monkeypatch, manager_type, module, payload):
    manager = _bare_manager(manager_type)
    _StartedThread.starts = 0
    monkeypatch.setattr(module.threading, "Thread", _StartedThread)

    now = datetime.now(UTC)
    manager._tasks["expired"] = {
        "task_id": "expired",
        "user_id": "old-user",
        "status": "completed",
        "updated_at": _iso(now - timedelta(seconds=TASK_RECORD_TTL_SECONDS + 1)),
    }
    manager._tasks["recent"] = {
        "task_id": "recent",
        "user_id": "recent-user",
        "status": "completed",
        "updated_at": _iso(now),
    }

    task_id = manager.start_task("new-user", payload)

    assert "expired" not in manager._tasks
    assert manager.get_task("recent-user", "recent") is not None
    assert task_id in manager._tasks

    with manager._lock:
        manager._tasks[task_id]["status"] = "completed"
        manager._tasks[task_id]["updated_at"] = _iso(datetime.now(UTC))

    for index in range(1000):
        created = manager.start_task(f"bulk-user-{index}", payload)
        with manager._lock:
            manager._tasks[created]["status"] = "completed"
            manager._tasks[created]["updated_at"] = _iso(datetime.now(UTC))

    assert len(manager._tasks) <= MAX_TASK_RECORDS
    assert all(
        str(task.get("status")) not in {"running", "pending", "paused", "cancelling"}
        for task in manager._tasks.values()
    )


@pytest.mark.parametrize(
    ("manager_type", "module"),
    [
        (ChaoxingLearningManager, learning_module),
        (ChaoxingSigninManager, signin_module),
    ],
)
def test_task_listing_sorts_offsets_and_bad_timestamps_deterministically(manager_type, module):
    del module
    manager = _bare_manager(manager_type)
    manager._loaded_task_users.add("user-1")
    future = datetime.now(UTC) + timedelta(days=1)
    offset_time = future.replace(hour=14, minute=0, second=0, microsecond=0, tzinfo=timezone(timedelta(hours=-8)))
    z_time = future.replace(hour=21, minute=30, second=0, microsecond=0)
    naive_time = future.replace(hour=22, minute=30, second=0, microsecond=0, tzinfo=None)
    for task_id, timestamp in (
        ("offset", offset_time.isoformat()),
        ("z-time", z_time.isoformat().replace("+00:00", "Z")),
        ("naive", naive_time.isoformat()),
        ("bad", "not-a-timestamp"),
        ("missing", None),
    ):
        task = {"task_id": task_id, "user_id": "user-1", "status": "completed"}
        if timestamp is not None:
            task["updated_at"] = timestamp
        manager._tasks[task_id] = task

    listed = manager.list_tasks("user-1")

    assert [task["task_id"] for task in listed] == ["naive", "offset", "z-time", "bad", "missing"]


@pytest.mark.parametrize(
    ("manager_type", "module", "payload"),
    [
        (ChaoxingLearningManager, learning_module, {"tiku_config": {}}),
        (ChaoxingSigninManager, signin_module, {}),
    ],
)
@pytest.mark.parametrize("failure", [OSError("storage unavailable"), False])
def test_persist_failure_keeps_unstarted_task_terminal(monkeypatch, manager_type, module, payload, failure):
    manager = _bare_manager(manager_type)
    _StartedThread.starts = 0
    monkeypatch.setattr(module.threading, "Thread", _StartedThread)

    def fail_persist(*args, **kwargs):
        del args, kwargs
        if failure is False:
            return False
        raise failure

    manager._persist_task_state = fail_persist

    with pytest.raises((OSError, RuntimeError)):
        manager.start_task("user-1", payload)

    assert len(manager._tasks) == 1
    task_id, task = next(iter(manager._tasks.items()))
    assert task["status"] == ("failed" if manager_type is ChaoxingLearningManager else "error")
    assert not is_active_status(task["status"])
    manager._loaded_task_users.add("user-1")
    assert not is_active_status(manager.get_task("user-1", task_id)["status"])
    assert all(not is_active_status(item["status"]) for item in manager.list_tasks("user-1"))
    assert _StartedThread.starts == 0


@pytest.mark.parametrize(
    ("manager_type", "module", "payload", "task_kind", "terminal_status"),
    [
        (
            ChaoxingLearningManager,
            learning_module,
            {"tiku_config": {}},
            "chaoxing_learning",
            "failed",
        ),
        (ChaoxingSigninManager, signin_module, {}, "chaoxing_signin", "error"),
    ],
)
def test_write_then_raise_is_compensated_on_restart_without_active_ghost(
    monkeypatch,
    manager_type,
    module,
    payload,
    task_kind,
    terminal_status,
):
    class WriteThenRaiseStore:
        def __init__(self):
            self.rows = {}
            self.upsert_calls = 0

        def upsert_task(self, kind, task):
            assert kind == task_kind
            self.upsert_calls += 1
            if self.upsert_calls == 1:
                self.rows[task["task_id"]] = deepcopy(task)
                raise OSError("commit outcome unknown")
            if self.upsert_calls == 2:
                raise OSError("compensation unavailable")
            self.rows[task["task_id"]] = deepcopy(task)

        def list_tasks(self, *, task_kind, user_id, limit):
            del limit
            assert task_kind == task_kind_value
            return [deepcopy(task) for task in self.rows.values() if user_id is None or task.get("user_id") == user_id]

        def get_task(self, *, task_kind, task_id, user_id=None):
            assert task_kind == task_kind_value
            task = self.rows.get(task_id)
            if task is None or (user_id is not None and task.get("user_id") != user_id):
                return None
            return deepcopy(task)

        def list_history(self, **kwargs):
            del kwargs
            return []

    task_kind_value = task_kind
    store = WriteThenRaiseStore()
    monkeypatch.setattr(module, "task_store", store)
    _StartedThread.starts = 0
    monkeypatch.setattr(module.threading, "Thread", _StartedThread)
    manager = manager_type()

    with pytest.raises(RuntimeError):
        manager.start_task("user-1", payload)

    task_id = next(iter(manager._tasks))
    assert store.rows[task_id]["status"] in {"pending", "running"}
    assert manager.get_task("user-1", task_id)["status"] == terminal_status
    assert manager.list_tasks("user-1")[0]["status"] == terminal_status
    assert _StartedThread.starts == 0

    restarted = manager_type()

    assert restarted.get_task("user-1", task_id)["status"] == terminal_status
    assert restarted.list_tasks("user-1")[0]["status"] == terminal_status
    assert store.rows[task_id]["status"] == terminal_status
    assert store.upsert_calls == 3


@pytest.mark.parametrize(
    ("manager_type", "module", "payload", "terminal_status", "raised_type"),
    [
        (ChaoxingLearningManager, learning_module, {"tiku_config": {}}, "failed", RuntimeError),
        (ChaoxingSigninManager, signin_module, {}, "error", OSError),
    ],
)
def test_thread_start_failure_does_not_leave_active_ghost(
    monkeypatch, manager_type, module, payload, terminal_status, raised_type
):
    manager = _bare_manager(manager_type)

    class FailingThread:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def start(self):
            raise OSError("thread start unavailable")

    monkeypatch.setattr(module.threading, "Thread", FailingThread)

    with pytest.raises(raised_type):
        manager.start_task("user-1", payload)

    assert len(manager._tasks) == 1
    task = next(iter(manager._tasks.values()))
    assert task["status"] == terminal_status
    assert not is_active_status(task["status"])


@pytest.mark.parametrize(
    ("manager_type", "module", "payload"),
    [
        (ChaoxingLearningManager, learning_module, {"tiku_config": {}}),
        (ChaoxingSigninManager, signin_module, {}),
    ],
)
def test_active_records_are_never_evicted_when_cap_is_reached(monkeypatch, manager_type, module, payload):
    manager = _bare_manager(manager_type)
    _StartedThread.starts = 0
    monkeypatch.setattr(module.threading, "Thread", _StartedThread)
    old = _iso(datetime.now(UTC) - timedelta(days=30))
    for index in range(MAX_ACTIVE_TASKS):
        manager._tasks[f"active-{index}"] = {
            "task_id": f"active-{index}",
            "user_id": f"active-user-{index}",
            "status": "stopping" if index == 0 else "running",
            "updated_at": old,
        }
    manager._tasks["expired"] = {
        "task_id": "expired",
        "user_id": "expired-user",
        "status": "failed",
        "updated_at": old,
    }

    with pytest.raises(TaskAdmissionError) as exc_info:
        manager.start_task("new-user", payload)

    assert exc_info.value.status_code == 429
    assert "expired" not in manager._tasks
    assert len(manager._tasks) == MAX_ACTIVE_TASKS
    assert all(task_id in manager._tasks for task_id in (f"active-{i}" for i in range(MAX_ACTIVE_TASKS)))
    assert _StartedThread.starts == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [409, 429])
async def test_course_start_maps_task_admission_errors(monkeypatch, status_code):
    class FakeLearningManager:
        def start_task(self, **kwargs):
            del kwargs
            raise (TaskAlreadyActiveError() if status_code == 409 else TaskCapacityError())

    monkeypatch.setattr(course_api, "_get_learning_manager", lambda: FakeLearningManager())
    request = course_api.CourseStartRequest(platform="chaoxing", username="demo", password="secret")

    with pytest.raises(HTTPException) as exc_info:
        await course_api.start_course_learning(request=request, current_user={"user_id": "user-1"})

    assert exc_info.value.status_code == status_code
    assert exc_info.value.detail in {TASK_ALREADY_ACTIVE_DETAIL, TASK_CAPACITY_DETAIL}


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [409, 429])
async def test_chaoxing_start_maps_task_admission_errors(monkeypatch, status_code):
    async def fake_parse_request_payload(request):
        del request
        return {"username": "demo", "password": "secret"}

    def fail_start(**kwargs):
        del kwargs
        raise (TaskAlreadyActiveError() if status_code == 409 else TaskCapacityError())

    monkeypatch.setattr(chaoxing_api, "_parse_request_payload", fake_parse_request_payload)
    monkeypatch.setattr(chaoxing_api.signin_manager, "start_task", fail_start)

    scope = {"type": "http", "method": "POST", "path": "/start", "headers": [], "query_string": b""}
    from starlette.requests import Request

    with pytest.raises(HTTPException) as exc_info:
        await chaoxing_api.chaoxing_start(Request(scope), user_id="user-1")

    assert exc_info.value.status_code == status_code
    assert exc_info.value.detail in {TASK_ALREADY_ACTIVE_DETAIL, TASK_CAPACITY_DETAIL}
