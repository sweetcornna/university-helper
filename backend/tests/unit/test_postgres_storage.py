from datetime import UTC, datetime

from psycopg2.extras import Json

import app.storage.postgres as pg
from app.storage.postgres import PostgresStorage


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        return None


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _FakeSessionCtx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        return False


def _patch_session(monkeypatch, cursor):
    monkeypatch.setattr(pg, "get_db_session", lambda: _FakeSessionCtx(_FakeConn(cursor)))


def test_list_tasks_uses_user_filter_and_updated_desc(monkeypatch):
    store = PostgresStorage().tasks
    monkeypatch.setattr(store, "ensure_tables", lambda: None)
    rows = [
        {
            "task_id": "task-new",
            "user_id": "user-1",
            "task_kind": "signin",
            "status": "running",
            "message": "new",
            "started_at": None,
            "updated_at": None,
            "payload": {"task_id": "task-new", "user_id": "user-1"},
        },
        {
            "task_id": "task-old",
            "user_id": "user-1",
            "task_kind": "signin",
            "status": "failed",
            "message": "old",
            "started_at": None,
            "updated_at": None,
            "payload": {"task_id": "task-old", "user_id": "user-1"},
        },
    ]
    cur = _FakeCursor(rows)
    _patch_session(monkeypatch, cur)
    tasks = store.list_tasks(task_kind="signin", user_id="user-1", limit=20)
    assert [t["task_id"] for t in tasks] == ["task-new", "task-old"]
    sql, params = cur.executed[0]
    assert "WHERE task_kind = %s AND user_id = %s" in sql
    assert "ORDER BY updated_at DESC NULLS LAST" in sql
    assert params == ("signin", "user-1", 20)


def test_get_task_uses_task_and_user_filters(monkeypatch):
    store = PostgresStorage().tasks
    monkeypatch.setattr(store, "ensure_tables", lambda: None)
    rows = [
        {
            "task_id": "task-1",
            "user_id": "user-1",
            "task_kind": "signin",
            "status": "running",
            "message": "active",
            "started_at": None,
            "updated_at": None,
            "payload": {"task_id": "task-1", "user_id": "user-1"},
        }
    ]
    cur = _FakeCursor(rows)
    _patch_session(monkeypatch, cur)
    task = store.get_task(task_kind="signin", task_id="task-1", user_id="user-1")
    assert task["task_id"] == "task-1"
    sql, params = cur.executed[0]
    assert "WHERE task_kind = %s AND task_id = %s AND user_id = %s" in sql
    assert params == ("signin", "task-1", "user-1")


def test_upsert_task_no_db_call_when_task_id_missing(monkeypatch):
    store = PostgresStorage().tasks
    calls = {"n": 0}
    monkeypatch.setattr(store, "ensure_tables", lambda: None)

    def _boom():
        # Increment first so a future regression that reaches the DB is caught
        # even though upsert_task swallows exceptions in its try/except.
        calls["n"] += 1
        raise AssertionError("db must not be touched when task_id is missing")

    monkeypatch.setattr(pg, "get_db_session", _boom)
    store.upsert_task("signin", {"user_id": "user-1", "status": "running"})  # no task_id
    assert calls["n"] == 0


def test_upsert_task_does_not_encrypt(monkeypatch):
    """Adapter must NOT call crypto — payload is stored exactly as received."""
    store = PostgresStorage().tasks
    monkeypatch.setattr(store, "ensure_tables", lambda: None)
    cur = _FakeCursor([])
    _patch_session(monkeypatch, cur)
    store.upsert_task("signin", {"task_id": "t1", "user_id": "u1", "password": "PLAINTEXT"})
    sql, params = cur.executed[0]
    json_arg = params[-1]  # psycopg2 Json wrapper
    assert isinstance(json_arg, Json)
    # `.adapted` is the Json wrapper's stored object — assert against it directly.
    assert json_arg.adapted["password"] == "PLAINTEXT"


def test_append_history_inserts_then_prunes_and_sets_timestamp(monkeypatch):
    store = PostgresStorage().tasks
    monkeypatch.setattr(store, "ensure_tables", lambda: None)
    cur = _FakeCursor([])
    _patch_session(monkeypatch, cur)
    store.append_history(
        "signin",
        "user-1",
        {"status": "completed", "message": "done"},  # no timestamp supplied
        max_records=10,
    )

    assert len(cur.executed) == 2

    insert_sql, insert_params = cur.executed[0]
    assert "INSERT INTO course_task_history" in insert_sql
    assert "(history_kind, user_id, status, message, event_time, payload)" in insert_sql
    assert len(insert_params) == 6
    assert insert_params[0] == "signin"
    assert insert_params[1] == "user-1"
    assert insert_params[2] == "completed"
    assert insert_params[3] == "done"
    assert isinstance(insert_params[4], datetime)  # event_time
    json_arg = insert_params[5]  # psycopg2 Json wrapper
    assert isinstance(json_arg, Json)
    # payload["timestamp"] is populated BEFORE the insert fires.
    assert json_arg.adapted.get("timestamp")
    assert json_arg.adapted["status"] == "completed"

    prune_sql, prune_params = cur.executed[1]
    assert "DELETE FROM course_task_history" in prune_sql
    assert "WHERE history_kind = %s" in prune_sql
    assert "id NOT IN (" in prune_sql  # correlated subquery prune
    assert "ORDER BY event_time DESC, id DESC" in prune_sql
    assert "LIMIT %s" in prune_sql
    assert prune_params == ("signin", "user-1", "signin", "user-1", 10)


def test_list_history_with_user_id_orders_and_falls_back_timestamp(monkeypatch):
    store = PostgresStorage().tasks
    monkeypatch.setattr(store, "ensure_tables", lambda: None)
    event_dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    rows = [{"user_id": "user-1", "event_time": event_dt, "payload": {"message": "no-ts"}}]
    cur = _FakeCursor(rows)
    _patch_session(monkeypatch, cur)
    history = store.list_history("signin", user_id="user-1", limit=25)

    sql, params = cur.executed[0]
    assert "WHERE history_kind = %s AND user_id = %s" in sql
    assert "ORDER BY event_time DESC, id DESC" in sql
    assert params == ("signin", "user-1", 25)
    # event_time → timestamp fallback when the payload carries no timestamp.
    assert history[0]["timestamp"] == event_dt.astimezone(UTC).isoformat()
    # user_id is NOT injected when the caller already scoped to a user.
    assert "user_id" not in history[0]


def test_list_history_without_user_id_injects_user_id_and_keeps_timestamp(monkeypatch):
    store = PostgresStorage().tasks
    monkeypatch.setattr(store, "ensure_tables", lambda: None)
    event_dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    rows = [{"user_id": "user-9", "event_time": event_dt, "payload": {"timestamp": "kept", "message": "x"}}]
    cur = _FakeCursor(rows)
    _patch_session(monkeypatch, cur)
    history = store.list_history("signin", limit=99)

    sql, params = cur.executed[0]
    assert "WHERE history_kind = %s" in sql
    assert "AND user_id = %s" not in sql
    assert "ORDER BY event_time DESC, id DESC" in sql
    assert params == ("signin", 99)
    # Existing payload timestamp is preserved (no fallback applied).
    assert history[0]["timestamp"] == "kept"
    # user_id is injected from the row when the caller did not scope to a user.
    assert history[0]["user_id"] == "user-9"


def test_probe_ping_true_on_success(monkeypatch):
    cur = _FakeCursor([{"?column?": 1}])

    class _Conn(_FakeConn):
        autocommit = False

        def cursor(self):  # context-manager cursor for the probe path
            outer = self

            class _C:
                def __enter__(self_):
                    return outer._cursor

                def __exit__(self_, *a):
                    return False

            return _C()

    monkeypatch.setattr(pg, "get_db_session", lambda: _FakeSessionCtx(_Conn(cur)))
    assert PostgresStorage().probe.ping() is True


def test_probe_ping_false_on_failure(monkeypatch):
    monkeypatch.setattr(pg, "get_db_session", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert PostgresStorage().probe.ping() is False
