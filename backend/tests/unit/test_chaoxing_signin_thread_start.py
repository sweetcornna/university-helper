import pytest

import app.services.course.chaoxing.signin as signin_module
from app.services.course.chaoxing.signin import ChaoxingSigninManager


def _manager(monkeypatch, persisted):
    monkeypatch.setattr(signin_module.task_store, "list_tasks", lambda *args, **kwargs: [])
    monkeypatch.setattr(signin_module.task_store, "list_history", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        signin_module.task_store,
        "upsert_task",
        lambda _kind, payload: persisted.append(dict(payload)),
    )
    return ChaoxingSigninManager()


def test_start_task_marks_thread_start_failure_and_reraises(monkeypatch):
    persisted = []

    class FailingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(signin_module.threading, "Thread", FailingThread)
    manager = _manager(monkeypatch, persisted)

    with pytest.raises(RuntimeError, match="can't start new thread"):
        manager.start_task("user-1", {"username": "demo"})

    task = manager.list_tasks("user-1")[0]
    assert task["status"] == "error"
    assert "can't start new thread" in task["message"]
    assert task["updated_at"] != task["created_at"]
    assert persisted[-1]["status"] == "error"
    assert "can't start new thread" in persisted[-1]["message"]
    assert persisted[-1]["updated_at"] == task["updated_at"]


def test_start_task_keeps_running_path_when_thread_starts(monkeypatch):
    persisted = []
    started = []

    class StartedThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            started.append(True)

    monkeypatch.setattr(signin_module.threading, "Thread", StartedThread)
    manager = _manager(monkeypatch, persisted)

    task_id = manager.start_task("user-1", {"username": "demo"})

    assert task_id
    assert started == [True]
    task = manager.get_task("user-1", task_id)
    assert task is not None
    assert task["status"] == "running"
    assert persisted[-1]["status"] == "running"
