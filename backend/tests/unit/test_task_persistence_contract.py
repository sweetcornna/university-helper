"""Strict success/failure contract for background-task persistence."""

from __future__ import annotations

import sqlite3
import threading
from copy import deepcopy

import pytest

import app.services.course.chaoxing.learning_manager as learning_module
import app.services.course.chaoxing.signin as signin_module
import app.services.course.task_store as task_store_module
import app.storage.postgres as postgres_module
import app.storage.sqlite as sqlite_module
from app.services.course.chaoxing.learning_manager import ChaoxingLearningManager
from app.services.course.chaoxing.signin import ChaoxingSigninManager
from app.services.course.chaoxing.task_admission import is_active_status
from app.services.course.task_store import TaskStore
from app.storage.postgres import PostgresStorage
from app.storage.sqlite import SqliteStorage


class _Cursor:
    def __init__(self, *, fail_execute: bool = False) -> None:
        self.executed: list[tuple[str, object]] = []
        self.fail_execute = fail_execute

    def execute(self, sql: str, params=None) -> None:
        if self.fail_execute:
            raise RuntimeError("cursor unavailable")
        self.executed.append((sql, params))

    def close(self) -> None:
        return None


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self.cursor_instance = cursor

    def cursor(self) -> _Cursor:
        return self.cursor_instance


class _Session:
    def __init__(self, connection: _Connection, *, commit_error: Exception | None = None) -> None:
        self.connection = connection
        self.commit_error = commit_error

    def __enter__(self) -> _Connection:
        return self.connection

    def __exit__(self, exc_type, exc, traceback) -> bool:
        del traceback
        if exc_type is None and self.commit_error is not None:
            raise self.commit_error
        return False


def test_sqlite_persistence_returns_strict_booleans_and_closed_connection_fails(tmp_path):
    storage = SqliteStorage(str(tmp_path / "tasks.db"))
    assert storage.tasks.ensure_tables() is True
    assert storage.tasks.upsert_task("signin", {"task_id": "ok", "user_id": "u1"}) is True
    assert storage.tasks.upsert_task("signin", {"user_id": "u1"}) is False
    assert storage.tasks.upsert_task("signin", "not-a-dict") is False

    storage._conn.close()

    assert storage.tasks.ensure_tables() is True  # cached initialization is still a valid result
    assert storage.tasks.upsert_task("signin", {"task_id": "closed", "user_id": "u1"}) is False
    assert storage.tasks.get_task("signin", "closed", "u1") is None


class _CommitOutcomeConnection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.close_calls = 0
        self.commit_calls = 0
        self.cursor_calls = 0
        self.execute_calls = 0
        self.fail_commit = False
        self.fail_rollback = False
        self.rollback_error_message = "rollback unavailable"

    def cursor(self, *args, **kwargs):
        self.cursor_calls += 1
        return super().cursor(*args, **kwargs)

    def execute(self, *args, **kwargs):
        self.execute_calls += 1
        return super().execute(*args, **kwargs)

    def commit(self):
        self.commit_calls += 1
        if self.fail_commit:
            raise OSError("commit failed after execute")
        return super().commit()

    def rollback(self):
        if self.fail_rollback:
            raise OSError(self.rollback_error_message)
        return super().rollback()

    def close(self):
        self.close_calls += 1
        return super().close()


class _CursorCloseFailure(sqlite3.Cursor):
    def close(self):
        raise OSError(self.connection.cursor_close_error_message)


class _CursorCloseFailureConnection(_CommitOutcomeConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cursor_close_error_message = "cursor close unavailable"

    def cursor(self, *args, **kwargs):
        self.cursor_calls += 1
        kwargs["factory"] = _CursorCloseFailure
        return sqlite3.Connection.cursor(self, *args, **kwargs)


def _controlled_sqlite_store(path=":memory:"):
    connection = sqlite3.connect(path, factory=_CommitOutcomeConnection)
    connection.row_factory = sqlite_module._dict_row
    return sqlite_module._SqliteTaskStore(connection, threading.Lock()), connection


def test_sqlite_ensure_commit_failure_resets_initialization_and_can_retry():
    store, connection = _controlled_sqlite_store()
    connection.fail_commit = True

    assert store.ensure_tables() is False
    assert connection.in_transaction is False
    assert store._initialized is False

    connection.fail_commit = False
    assert store.ensure_tables() is True


def test_sqlite_upsert_commit_failure_rolls_back_without_leaking_on_next_commit():
    store, connection = _controlled_sqlite_store()
    assert store.ensure_tables() is True
    connection.fail_commit = True

    assert store.upsert_task("signin", {"task_id": "failed", "user_id": "u1"}) is False
    assert connection.in_transaction is False
    assert store.get_task("signin", "failed", "u1") is None
    assert store.list_tasks("signin", user_id="u1") == []

    connection.fail_commit = False
    assert store.upsert_task("signin", {"task_id": "committed", "user_id": "u1"}) is True
    assert [task["task_id"] for task in store.list_tasks("signin", user_id="u1")] == ["committed"]


def test_sqlite_append_history_commit_failure_rolls_back_without_leaking_on_next_commit():
    store, connection = _controlled_sqlite_store()
    assert store.ensure_tables() is True
    connection.fail_commit = True

    assert store.append_history("signin", "u1", {"message": "failed"}) is None
    assert connection.in_transaction is False
    assert store.list_history("signin", user_id="u1") == []

    connection.fail_commit = False
    store.append_history("signin", "u1", {"message": "committed"})
    assert [item["message"] for item in store.list_history("signin", user_id="u1")] == ["committed"]


def test_sqlite_rollback_failure_poisons_connection_without_leaking_transaction(tmp_path, caplog):
    database_path = tmp_path / "rollback-poison.db"
    store, connection = _controlled_sqlite_store(database_path)
    assert store.ensure_tables() is True
    connection.fail_commit = True
    connection.fail_rollback = True
    sentinel = "ROLLBACK-SECRET-SENTINEL"
    connection.rollback_error_message = sentinel

    assert store.upsert_task("signin", {"task_id": "rollback-failed", "user_id": "u1"}) is False
    assert store._usable is False
    assert store._initialized is False
    assert connection.close_calls == 1

    calls_after_poison = (connection.commit_calls, connection.cursor_calls, connection.execute_calls)
    assert store.upsert_task("signin", {"task_id": "later", "user_id": "u1"}) is False
    assert store.append_history("signin", "u1", {"message": "later"}) is None
    assert store.ensure_tables() is False
    assert store.get_task("signin", "rollback-failed", "u1") is None
    assert store.list_tasks("signin", user_id="u1") == []
    assert store.list_history("signin", user_id="u1") == []
    assert store.ping() is False
    assert (connection.commit_calls, connection.cursor_calls, connection.execute_calls) == calls_after_poison

    store.close()
    store.close()
    assert connection.close_calls == 1
    assert sentinel not in caplog.text

    with sqlite3.connect(database_path) as observer:
        assert observer.execute("SELECT COUNT(*) FROM course_task_store").fetchone()[0] == 0


def test_sqlite_storage_close_is_idempotent_and_fail_closed(tmp_path):
    storage = SqliteStorage(str(tmp_path / "close.db"))
    assert storage.tasks.ensure_tables() is True

    storage.close()
    storage.close()

    assert storage.tasks.ensure_tables() is False
    assert storage.tasks.upsert_task("signin", {"task_id": "closed", "user_id": "u1"}) is False
    assert storage.tasks.get_task("signin", "closed", "u1") is None
    assert storage.tasks.list_tasks("signin") == []
    assert storage.tasks.list_history("signin") == []
    assert storage.probe.ping() is False


def test_sqlite_close_waits_for_writer_without_deadlock():
    store, connection = _controlled_sqlite_store()
    close_started = threading.Event()
    close_finished = threading.Event()

    def close_store():
        close_started.set()
        store.close()
        close_finished.set()

    store._write_lock.acquire()
    closer = threading.Thread(target=close_store)
    try:
        closer.start()
        assert close_started.wait(timeout=1)
        assert not close_finished.wait(timeout=0.05)
    finally:
        store._write_lock.release()
    closer.join(timeout=1)

    assert not closer.is_alive()
    assert close_finished.is_set()
    assert connection.close_calls == 1


def test_sqlite_cursor_close_log_omits_exception_details(caplog):
    sentinel = "CURSOR-CLOSE-SECRET-SENTINEL"
    connection = sqlite3.connect(":memory:", factory=_CursorCloseFailureConnection)
    connection.row_factory = sqlite_module._dict_row
    connection.cursor_close_error_message = sentinel
    store = sqlite_module._SqliteTaskStore(connection, threading.Lock())

    assert store.ensure_tables() is True
    assert "sqlite cursor close failed" in caplog.text
    assert sentinel not in caplog.text

    store.close()


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param("cursor", id="cursor"),
        pytest.param("commit", id="commit"),
    ],
)
def test_postgres_initialization_failure_is_false_and_blocks_upsert(monkeypatch, failure):
    cursor = _Cursor(fail_execute=failure == "cursor")
    connection = _Connection(cursor)
    session = _Session(connection, commit_error=RuntimeError("commit unavailable") if failure == "commit" else None)
    monkeypatch.setattr(postgres_module, "get_db_session", lambda: session)

    store = PostgresStorage().tasks

    assert store.ensure_tables() is False
    assert store.upsert_task("signin", {"task_id": "t1", "user_id": "u1"}) is False


def test_postgres_successful_upsert_returns_true(monkeypatch):
    cursor = _Cursor()
    connection = _Connection(cursor)
    session = _Session(connection)
    monkeypatch.setattr(postgres_module, "get_db_session", lambda: session)

    store = PostgresStorage().tasks
    assert store.ensure_tables() is True
    assert store.upsert_task("signin", {"task_id": "t1", "user_id": "u1", "status": "running"}) is True
    assert any("INSERT INTO course_task_store" in sql for sql, _ in cursor.executed)


class _DelegatingTasks:
    def __init__(self, ensure_result=True, upsert_result=True) -> None:
        self.ensure_result = ensure_result
        self.upsert_result = upsert_result
        self.calls: list[str] = []

    def ensure_tables(self):
        self.calls.append("ensure_tables")
        return self.ensure_result

    def upsert_task(self, task_kind, task_state_public):
        del task_kind, task_state_public
        self.calls.append("upsert_task")
        return self.upsert_result


class _Storage:
    def __init__(self, tasks) -> None:
        self.tasks = tasks


@pytest.mark.parametrize("result", [True, False])
def test_task_store_passes_through_adapter_results(monkeypatch, result):
    tasks = _DelegatingTasks(ensure_result=result, upsert_result=result)
    monkeypatch.setattr(task_store_module, "get_storage", lambda: _Storage(tasks))

    store = TaskStore()
    assert store.ensure_tables() is result
    assert store.upsert_task("signin", {"task_id": "t1", "user_id": "u1"}) is result
    assert tasks.calls == ["ensure_tables", "upsert_task"]


def test_task_store_invalid_input_and_adapter_exception_are_false(monkeypatch):
    tasks = _DelegatingTasks()
    monkeypatch.setattr(task_store_module, "get_storage", lambda: _Storage(tasks))
    store = TaskStore()
    assert store.upsert_task("", {"task_id": "t1", "user_id": "u1"}) is False
    assert store.upsert_task("signin", "not-a-dict") is False
    assert tasks.calls == []

    def fail_upsert(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("storage unavailable")

    tasks.upsert_task = fail_upsert
    assert store.upsert_task("signin", {"task_id": "t1", "user_id": "u1"}) is False


class _NoStartThread:
    starts = 0

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    def start(self) -> None:
        type(self).starts += 1


def _bare_manager(manager_type):
    manager = manager_type.__new__(manager_type)
    manager._lock = threading.Lock()
    manager._tasks = {}
    manager._loaded_task_users = set()
    if manager_type is ChaoxingSigninManager:
        manager._clients = {}
        manager._history = {}
        manager._loaded_history_users = set()
    return manager


@pytest.mark.parametrize(
    ("manager_type", "module", "payload", "terminal_status"),
    [
        (ChaoxingLearningManager, learning_module, {"tiku_config": {}}, "failed"),
        (ChaoxingSigninManager, signin_module, {}, "error"),
    ],
)
@pytest.mark.parametrize("persist_result", [False, None, 1])
def test_managers_require_true_before_starting_worker(
    monkeypatch,
    manager_type,
    module,
    payload,
    terminal_status,
    persist_result,
):
    manager = _bare_manager(manager_type)
    _NoStartThread.starts = 0
    monkeypatch.setattr(module.threading, "Thread", _NoStartThread)
    manager._persist_task_state = lambda *args, **kwargs: persist_result

    with pytest.raises(RuntimeError):
        manager.start_task("u1", deepcopy(payload))

    assert _NoStartThread.starts == 0
    task = next(iter(manager._tasks.values()))
    assert task["status"] == terminal_status
    assert not is_active_status(task["status"])


class _WriteThenRaiseStore:
    def __init__(self, task_kind: str) -> None:
        self.task_kind = task_kind
        self.rows: dict[str, dict] = {}
        self.calls = 0

    def upsert_task(self, task_kind: str, task: dict) -> bool:
        assert task_kind == self.task_kind
        self.calls += 1
        self.rows[task["task_id"]] = deepcopy(task)
        if self.calls == 1:
            raise OSError("commit outcome unknown")
        return True

    def list_tasks(self, *, task_kind: str, user_id: str | None, limit: int) -> list[dict]:
        assert task_kind == self.task_kind
        del limit
        return [deepcopy(task) for task in self.rows.values() if user_id is None or task.get("user_id") == user_id]

    def list_history(self, **kwargs) -> list[dict]:
        del kwargs
        return []


@pytest.mark.parametrize(
    ("manager_type", "module", "payload", "task_kind", "terminal_status"),
    [
        (ChaoxingLearningManager, learning_module, {"tiku_config": {}}, "chaoxing_learning", "failed"),
        (ChaoxingSigninManager, signin_module, {}, "chaoxing_signin", "error"),
    ],
)
def test_write_then_raise_is_compensated_before_worker_and_restart(
    monkeypatch, manager_type, module, payload, task_kind, terminal_status
):
    store = _WriteThenRaiseStore(task_kind)
    monkeypatch.setattr(module, "task_store", store)
    _NoStartThread.starts = 0
    monkeypatch.setattr(module.threading, "Thread", _NoStartThread)

    manager = manager_type()
    with pytest.raises(RuntimeError, match="persist"):
        manager.start_task("u1", payload)

    assert _NoStartThread.starts == 0
    task_id = next(iter(store.rows))
    assert store.rows[task_id]["status"] == terminal_status
    assert not is_active_status(store.rows[task_id]["status"])

    restarted = manager_type()
    restored = restarted.get_task("u1", task_id)
    assert restored is not None
    assert restored["status"] == terminal_status
    assert not is_active_status(restored["status"])
