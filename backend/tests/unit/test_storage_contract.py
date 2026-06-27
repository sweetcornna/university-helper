import uuid

import pytest

from app.storage.sqlite import SqliteStorage


def _pg_available():
    try:
        import psycopg2

        from app.config import settings

        conn = psycopg2.connect(
            host=settings.MAIN_DB_HOST,
            dbname=settings.MAIN_DB_NAME,
            user=settings.MAIN_DB_USER,
            password=settings.MAIN_DB_PASSWORD,
            port=settings.MAIN_DB_PORT,
            connect_timeout=2,
        )
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(params=["sqlite", "postgres"])
def storage(request, tmp_path):
    if request.param == "sqlite":
        return SqliteStorage(str(tmp_path / "uh.db"))
    if not _pg_available():
        pytest.skip("no reachable Postgres (set MAIN_DB_* / CI service container)")
    from app.storage.postgres import PostgresStorage

    return PostgresStorage()


def test_upsert_get_round_trip(storage):
    kind, user = f"k-{uuid.uuid4().hex}", f"u-{uuid.uuid4().hex}"
    storage.tasks.upsert_task(
        kind,
        {
            "task_id": "t1",
            "user_id": user,
            "status": "running",
            "message": "m",
            "started_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:05:00+00:00",
            "nested": {"a": 1},
            "password": "kept-verbatim",
        },
    )
    got = storage.tasks.get_task(kind, "t1", user)
    assert got["task_id"] == "t1"
    assert got["status"] == "running"
    assert got["updated_at"] == "2026-01-01T00:05:00+00:00"
    assert got["nested"] == {"a": 1}
    assert got["password"] == "kept-verbatim"


def test_list_user_filter_and_order(storage):
    kind, user = f"k-{uuid.uuid4().hex}", f"u-{uuid.uuid4().hex}"
    storage.tasks.upsert_task(
        kind,
        {"task_id": "a", "user_id": user, "status": "x", "updated_at": "2026-01-01T00:00:00+00:00"},
    )
    storage.tasks.upsert_task(
        kind,
        {"task_id": "b", "user_id": user, "status": "x", "updated_at": "2026-01-02T00:00:00+00:00"},
    )
    storage.tasks.upsert_task(
        kind,
        {"task_id": "z", "user_id": "other", "status": "x", "updated_at": "2026-01-09T00:00:00+00:00"},
    )
    ids = [t["task_id"] for t in storage.tasks.list_tasks(kind, user_id=user, limit=50)]
    assert ids == ["b", "a"]


def test_upsert_conflict_coalesces_started_at(storage):
    kind, user = f"k-{uuid.uuid4().hex}", f"u-{uuid.uuid4().hex}"
    storage.tasks.upsert_task(
        kind,
        {
            "task_id": "t1",
            "user_id": user,
            "status": "running",
            "started_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
    )
    storage.tasks.upsert_task(
        kind,
        {
            "task_id": "t1",
            "user_id": user,
            "status": "completed",
            "updated_at": "2026-01-01T02:00:00+00:00",
        },
    )
    got = storage.tasks.get_task(kind, "t1", user)
    assert got["status"] == "completed"
    assert got["started_at"] == "2026-01-01T00:00:00+00:00"


def test_history_append_list_and_prune(storage):
    kind, user = f"k-{uuid.uuid4().hex}", f"u-{uuid.uuid4().hex}"
    for i in range(5):
        storage.tasks.append_history(
            kind,
            user,
            {"message": f"m{i}", "timestamp": f"2026-01-0{i + 1}T00:00:00+00:00"},
            max_records=3,
        )
    hist = storage.tasks.list_history(kind, user_id=user, limit=50)
    assert [h["message"] for h in hist] == ["m4", "m3", "m2"]
