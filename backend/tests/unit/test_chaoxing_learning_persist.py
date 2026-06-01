"""Regression tests for learning-task persistence throttling (F31).

High-frequency progress ticks must NOT issue one full main-DB JSONB upsert each;
they are coalesced. Status changes / terminal writes still persist immediately so
final state is never lost.
"""
import app.services.course.chaoxing.learning_manager as lm
from app.services.course.chaoxing.learning_manager import ChaoxingLearningManager


def _make_task(manager: ChaoxingLearningManager, task_id: str = "t1") -> None:
    manager._tasks[task_id] = {
        "task_id": task_id,
        "user_id": "u1",
        "platform": "chaoxing",
        "status": "running",
        "message": "",
        "current_task": "",
        "progress": manager._default_progress(),
        "logs": [],
        "_log_cursor": 0,
    }


def test_progress_updates_are_throttled(monkeypatch):
    """Rapid _update_progress calls coalesce into far fewer upserts."""
    manager = ChaoxingLearningManager.__new__(ChaoxingLearningManager)
    import threading

    manager._lock = threading.Lock()
    manager._tasks = {}
    manager._loaded_task_users = set()
    _make_task(manager)

    calls: list[dict] = []
    monkeypatch.setattr(
        lm.task_store,
        "upsert_task",
        lambda kind, payload: calls.append(payload),
    )

    # 50 rapid progress ticks (simulating ~1/sec video callbacks, but instant).
    for i in range(50):
        manager._update_progress("t1", video_progress={"current": i})

    # Without throttling this would be 50 upserts; with the >=5s throttle only
    # the first tick (and any after the interval elapses) writes — here just 1.
    assert len(calls) <= 2, f"expected throttled writes, got {len(calls)}"


def test_status_change_forces_persist_with_latest_progress(monkeypatch):
    """A forced status write persists immediately and carries the latest progress."""
    manager = ChaoxingLearningManager.__new__(ChaoxingLearningManager)
    import threading

    manager._lock = threading.Lock()
    manager._tasks = {}
    manager._loaded_task_users = set()
    _make_task(manager)

    calls: list[dict] = []
    monkeypatch.setattr(
        lm.task_store,
        "upsert_task",
        lambda kind, payload: calls.append(payload),
    )

    # Throttled progress ticks (most dropped) then a forced terminal status write.
    for i in range(10):
        manager._update_progress("t1", completed=i)
    manager._update_task("t1", status="completed", message="done")

    # The final forced write happened and carries the latest progress value.
    assert calls, "no upsert recorded"
    last = calls[-1]
    assert last["status"] == "completed"
    assert last["progress"]["completed"] == 9


def test_unchanged_update_task_skips_persist(monkeypatch):
    """Repeated identical _update_task calls (e.g. paused poll) do not re-upsert."""
    manager = ChaoxingLearningManager.__new__(ChaoxingLearningManager)
    import threading

    manager._lock = threading.Lock()
    manager._tasks = {}
    manager._loaded_task_users = set()
    _make_task(manager)

    calls: list[dict] = []
    monkeypatch.setattr(
        lm.task_store,
        "upsert_task",
        lambda kind, payload: calls.append(payload),
    )

    manager._update_task("t1", status="paused", message="Task paused", current_task="paused")
    first = len(calls)
    assert first == 1
    # Same payload repeated (as _wait_for_resume does) -> no further writes.
    for _ in range(20):
        manager._update_task("t1", status="paused", message="Task paused", current_task="paused")
    assert len(calls) == first, "identical status updates must not re-upsert"
