from app.storage.sqlite import SqliteStorage


def _store(tmp_path):
    return SqliteStorage(str(tmp_path / "uh.db")).tasks


def test_upsert_then_get_round_trip(tmp_path):
    s = _store(tmp_path)
    s.upsert_task(
        "signin",
        {
            "task_id": "t1",
            "user_id": "u1",
            "status": "running",
            "message": "go",
            "started_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:05:00+00:00",
            "extra": {"k": "v"},
            "password": "secret-stays-as-is",
        },
    )
    got = s.get_task("signin", "t1", "u1")
    assert got["task_id"] == "t1"
    assert got["user_id"] == "u1"
    assert got["status"] == "running"
    assert got["message"] == "go"
    assert got["updated_at"] == "2026-01-01T00:05:00+00:00"
    assert got["extra"] == {"k": "v"}
    assert got["password"] == "secret-stays-as-is"  # adapter does NOT encrypt


def test_upsert_conflict_updates_and_coalesces_started_at(tmp_path):
    s = _store(tmp_path)
    s.upsert_task(
        "signin",
        {
            "task_id": "t1",
            "user_id": "u1",
            "status": "running",
            "started_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
    )
    s.upsert_task(
        "signin", {"task_id": "t1", "user_id": "u1", "status": "completed", "updated_at": "2026-01-01T01:00:00+00:00"}
    )
    got = s.get_task("signin", "t1")
    assert got["status"] == "completed"
    assert got["started_at"] == "2026-01-01T00:00:00+00:00"  # COALESCE kept the original


def test_list_orders_updated_desc_nulls_last_and_filters_user(tmp_path):
    s = _store(tmp_path)
    s.upsert_task("signin", {"task_id": "a", "user_id": "u1", "status": "x", "updated_at": "2026-01-01T00:00:00+00:00"})
    s.upsert_task("signin", {"task_id": "b", "user_id": "u1", "status": "x", "updated_at": "2026-01-02T00:00:00+00:00"})
    s.upsert_task("signin", {"task_id": "c", "user_id": "u2", "status": "x", "updated_at": "2026-01-03T00:00:00+00:00"})
    ids = [t["task_id"] for t in s.list_tasks("signin", user_id="u1", limit=50)]
    assert ids == ["b", "a"]


def test_history_append_list_and_prune(tmp_path):
    s = _store(tmp_path)
    for i in range(5):
        s.append_history(
            "signin", "u1", {"message": f"m{i}", "timestamp": f"2026-01-0{i + 1}T00:00:00+00:00"}, max_records=3
        )
    hist = s.list_history("signin", user_id="u1", limit=50)
    assert [h["message"] for h in hist] == ["m4", "m3", "m2"]  # newest 3 kept, DESC
