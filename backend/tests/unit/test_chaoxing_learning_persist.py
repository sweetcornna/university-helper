"""Regression tests for learning-task persistence throttling (F31).

High-frequency progress ticks must NOT issue one full main-DB JSONB upsert each;
they are coalesced. Status changes / terminal writes still persist immediately so
final state is never lost.
"""

import threading

import app.services.course.chaoxing.learning_manager as lm
from app.services.course.chaoxing.learning_manager import ChaoxingLearningManager


def _record_payload(target: list[dict], kind, payload) -> bool:
    del kind
    target.append(payload)
    return True


def _record_message(target: list[str], kind, payload) -> bool:
    del kind
    target.append(payload["message"])
    return True


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
    manager._lock = threading.Lock()
    manager._tasks = {}
    manager._loaded_task_users = set()
    _make_task(manager)

    calls: list[dict] = []
    monkeypatch.setattr(
        lm.task_store,
        "upsert_task",
        lambda kind, payload: _record_payload(calls, kind, payload),
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
    manager._lock = threading.Lock()
    manager._tasks = {}
    manager._loaded_task_users = set()
    _make_task(manager)

    calls: list[dict] = []
    monkeypatch.setattr(
        lm.task_store,
        "upsert_task",
        lambda kind, payload: _record_payload(calls, kind, payload),
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
    manager._lock = threading.Lock()
    manager._tasks = {}
    manager._loaded_task_users = set()
    _make_task(manager)

    calls: list[dict] = []
    monkeypatch.setattr(
        lm.task_store,
        "upsert_task",
        lambda kind, payload: _record_payload(calls, kind, payload),
    )

    manager._update_task("t1", status="paused", message="Task paused", current_task="paused")
    first = len(calls)
    assert first == 1
    # Same payload repeated (as _wait_for_resume does) -> no further writes.
    for _ in range(20):
        manager._update_task("t1", status="paused", message="Task paused", current_task="paused")
    assert len(calls) == first, "identical status updates must not re-upsert"


def test_older_snapshot_cannot_overwrite_newer_snapshot(monkeypatch):
    """An older blocked upsert must not commit after a terminal snapshot."""
    manager = ChaoxingLearningManager.__new__(ChaoxingLearningManager)
    manager._lock = threading.Lock()
    manager._tasks = {}
    manager._loaded_task_users = set()
    _make_task(manager)

    older_write_started = threading.Event()
    newer_write_committed = threading.Event()
    persisted: dict[str, object] = {}
    persisted_lock = threading.Lock()

    def controlled_upsert(kind, payload):
        del kind
        if payload["message"] == "older":
            older_write_started.set()
            # In the vulnerable implementation the newer write enters the store
            # concurrently and releases us, so this old snapshot commits last.
            # In the fixed implementation it waits behind this write and commits
            # afterward. The timeout is only the escape hatch for that expected
            # serialization; no scheduler sleep is used.
            newer_write_committed.wait(timeout=1)
        with persisted_lock:
            persisted.clear()
            persisted.update(payload)
        if payload["message"] == "newer":
            newer_write_committed.set()
        return True

    monkeypatch.setattr(lm.task_store, "upsert_task", controlled_upsert)

    older = threading.Thread(
        target=manager._update_task,
        args=("t1",),
        kwargs={"status": "paused", "message": "older"},
    )
    newer = threading.Thread(
        target=manager._update_task,
        args=("t1",),
        kwargs={"status": "completed", "message": "newer"},
    )
    older.start()
    assert older_write_started.wait(timeout=1)
    newer.start()
    older.join(timeout=2)
    newer.join(timeout=2)

    assert not older.is_alive()
    assert not newer.is_alive()
    assert persisted["status"] == "completed"
    assert persisted["message"] == "newer"


def test_continuous_updates_persist_in_state_mutation_order(monkeypatch):
    manager = ChaoxingLearningManager.__new__(ChaoxingLearningManager)
    manager._lock = threading.Lock()
    manager._tasks = {}
    manager._loaded_task_users = set()
    _make_task(manager)

    persisted_messages: list[str] = []
    monkeypatch.setattr(
        lm.task_store,
        "upsert_task",
        lambda kind, payload: _record_message(persisted_messages, kind, payload),
    )

    for index in range(10):
        manager._update_task("t1", message=f"update-{index}")
    manager._update_task("t1", status="completed", message="terminal")

    assert persisted_messages == [*[f"update-{index}" for index in range(10)], "terminal"]


def test_failed_write_does_not_block_later_snapshot(monkeypatch):
    manager = ChaoxingLearningManager.__new__(ChaoxingLearningManager)
    manager._lock = threading.Lock()
    manager._tasks = {}
    manager._loaded_task_users = set()
    _make_task(manager)

    attempts: list[str] = []
    persisted: list[dict] = []

    def fail_once(kind, payload):
        del kind
        attempts.append(payload["message"])
        if len(attempts) == 1:
            raise RuntimeError("temporary store failure")
        persisted.append(dict(payload))
        return True

    monkeypatch.setattr(lm.task_store, "upsert_task", fail_once)

    manager._update_task("t1", status="paused", message="failed-write")
    manager._update_task("t1", status="completed", message="recovered")

    assert attempts == ["failed-write", "recovered"]
    assert persisted[-1]["status"] == "completed"
    assert persisted[-1]["message"] == "recovered"


def test_blocked_task_does_not_serialize_other_tasks(monkeypatch):
    manager = ChaoxingLearningManager.__new__(ChaoxingLearningManager)
    manager._lock = threading.Lock()
    manager._tasks = {}
    manager._loaded_task_users = set()
    _make_task(manager, "blocked-task")
    _make_task(manager, "other-task")

    blocked_write_started = threading.Event()
    release_blocked_write = threading.Event()
    other_write_committed = threading.Event()

    def controlled_upsert(kind, payload):
        del kind
        if payload["task_id"] == "blocked-task":
            blocked_write_started.set()
            release_blocked_write.wait(timeout=2)
        else:
            other_write_committed.set()
        return True

    monkeypatch.setattr(lm.task_store, "upsert_task", controlled_upsert)

    blocked = threading.Thread(
        target=manager._update_task,
        args=("blocked-task",),
        kwargs={"message": "blocked"},
    )
    other = threading.Thread(
        target=manager._update_task,
        args=("other-task",),
        kwargs={"message": "independent"},
    )
    blocked.start()
    assert blocked_write_started.wait(timeout=1)
    other.start()
    try:
        assert other_write_committed.wait(timeout=1)
    finally:
        release_blocked_write.set()
    blocked.join(timeout=2)
    other.join(timeout=2)

    assert not blocked.is_alive()
    assert not other.is_alive()
