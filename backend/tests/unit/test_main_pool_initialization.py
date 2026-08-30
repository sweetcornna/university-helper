import threading
from unittest.mock import Mock, patch

import pytest

import app.db.session as session_mod


def test_main_pool_initialized_once_under_concurrency():
    n_threads = 8
    start = threading.Barrier(n_threads + 1)
    creation_started = threading.Event()
    release_creation = threading.Event()
    pool = Mock()
    results = []
    errors = []

    def build_pool(*_args, **_kwargs):
        creation_started.set()
        assert release_creation.wait(timeout=5)
        return pool

    def worker():
        try:
            start.wait(timeout=5)
            results.append(session_mod._get_main_pool())
        except Exception as exc:  # pragma: no cover - assertion below reports worker failures
            errors.append(exc)

    previous_pool = session_mod.main_pool
    session_mod.main_pool = None
    threads = [threading.Thread(target=worker, daemon=True) for _ in range(n_threads)]
    try:
        with patch("psycopg2.pool.ThreadedConnectionPool", side_effect=build_pool) as pool_class:
            for thread in threads:
                thread.start()
            start.wait(timeout=5)
            assert creation_started.wait(timeout=5)
            release_creation.set()
            for thread in threads:
                thread.join(timeout=5)

            assert not errors
            assert len(results) == n_threads
            assert all(result is pool for result in results)
            pool_class.assert_called_once()
    finally:
        release_creation.set()
        start.abort()
        for thread in threads:
            thread.join(timeout=5)
        assert not any(thread.is_alive() for thread in threads)
        session_mod.main_pool = previous_pool


def test_main_pool_creation_failure_does_not_publish_and_can_retry():
    pool = Mock()
    previous_pool = session_mod.main_pool
    session_mod.main_pool = None
    try:
        with patch(
            "psycopg2.pool.ThreadedConnectionPool",
            side_effect=[RuntimeError("database unavailable"), pool],
        ) as pool_class:
            with pytest.raises(RuntimeError, match="database unavailable"):
                session_mod._get_main_pool()
            assert session_mod.main_pool is None

            assert session_mod._get_main_pool() is pool
            assert session_mod.main_pool is pool
            assert pool_class.call_count == 2
    finally:
        session_mod.main_pool = previous_pool
