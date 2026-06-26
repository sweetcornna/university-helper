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
    monkeypatch.setattr(pg, "get_db_session", lambda: (_ for _ in ()).throw(AssertionError("db touched")))
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
    assert "PLAINTEXT" in str(json_arg.adapted if hasattr(json_arg, "adapted") else json_arg)


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
