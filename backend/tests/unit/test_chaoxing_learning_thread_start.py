import pytest

import app.services.course.chaoxing.learning_manager as lm
from app.services.course.chaoxing.learning_manager import ChaoxingLearningManager


def test_start_task_marks_failed_when_worker_thread_cannot_start(monkeypatch):
    monkeypatch.setattr(lm.task_store, "list_tasks", lambda *args, **kwargs: [])

    persisted: list[dict] = []
    monkeypatch.setattr(lm.task_store, "upsert_task", lambda kind, payload: persisted.append(dict(payload)))

    class FailingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(lm.threading, "Thread", FailingThread)

    manager = ChaoxingLearningManager()

    with pytest.raises(RuntimeError, match="cannot start a new background thread"):
        manager.start_task("u1", {"username": "demo"})

    task = manager.list_tasks("u1")[0]
    assert task["status"] == "failed"
    assert "cannot start a new background thread" in task["message"]
    assert persisted[-1]["status"] == "failed"
