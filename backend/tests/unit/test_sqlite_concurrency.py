import threading

from app.storage.sqlite import SqliteStorage


def test_concurrent_upserts_no_database_locked(tmp_path):
    store = SqliteStorage(str(tmp_path / "uh.db"))
    store.tasks.ensure_tables()
    n_threads, per_thread = 20, 25
    errors: list[BaseException] = []
    barrier = threading.Barrier(n_threads)

    def worker(tid: int):
        try:
            barrier.wait()  # maximize contention
            for i in range(per_thread):
                store.tasks.upsert_task(
                    "signin",
                    {
                        "task_id": f"t-{tid}-{i}",
                        "user_id": f"u-{tid}",
                        "status": "running",
                        "message": f"{tid}:{i}",
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    },
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,), daemon=True) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"writer errors: {errors!r}"
    assert not any("database is locked" in str(e) for e in errors)
    total = len(store.tasks.list_tasks("signin", limit=2000))
    assert total == n_threads * per_thread
