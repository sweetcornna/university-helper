"""Process-singleton storage factory. Lazily imports the selected adapter."""

from __future__ import annotations

import threading

from app.config import settings
from app.storage.base import Storage

_storage: Storage | None = None
_lock = threading.Lock()


def _build_storage() -> Storage:
    backend = settings.STORAGE_BACKEND
    if backend == "sqlite":
        if not settings.SQLITE_PATH:
            raise RuntimeError("STORAGE_BACKEND=sqlite requires SQLITE_PATH to be set")
        from app.storage.sqlite import SqliteStorage  # lazy: no psycopg2

        return SqliteStorage(settings.SQLITE_PATH)
    from app.storage.postgres import PostgresStorage  # lazy: imports psycopg2/app.db.session

    return PostgresStorage()


def get_storage() -> Storage:
    global _storage
    if _storage is not None:
        return _storage
    with _lock:
        if _storage is None:
            _storage = _build_storage()
    return _storage


def _reset_for_tests() -> None:
    """Drop the singleton so the next get_storage() rebuilds. Tests only."""
    global _storage
    with _lock:
        _storage = None
