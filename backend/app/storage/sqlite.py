"""SQLite storage adapter: one WAL connection, write-lock, plain-dict rows. No crypto here."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import UTC, datetime
from typing import Any

from app.storage.base import _datetime_to_iso, _normalize_json, _parse_datetime

logger = logging.getLogger(__name__)


def _dict_row(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def _iso_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


class _SqliteTaskStore:
    def __init__(self, conn: sqlite3.Connection, write_lock: threading.Lock) -> None:
        self._conn = conn
        self._write_lock = write_lock  # serializes writes (spec §5)
        self._init_lock = threading.Lock()
        self._initialized = False

    def ensure_tables(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            try:
                with self._write_lock:
                    cur = self._conn.cursor()
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS course_task_store (
                            task_id TEXT NOT NULL,
                            user_id TEXT NOT NULL,
                            task_kind TEXT NOT NULL,
                            status TEXT NOT NULL,
                            message TEXT,
                            started_at TEXT,
                            updated_at TEXT,
                            payload TEXT NOT NULL DEFAULT '{}',
                            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                            PRIMARY KEY (task_kind, task_id)
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_course_task_store_lookup
                        ON course_task_store (task_kind, user_id, updated_at DESC)
                        """
                    )
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS course_task_history (
                            id INTEGER PRIMARY KEY,
                            history_kind TEXT NOT NULL,
                            user_id TEXT NOT NULL,
                            status TEXT,
                            message TEXT,
                            event_time TEXT NOT NULL,
                            payload TEXT NOT NULL DEFAULT '{}',
                            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_course_task_history_lookup
                        ON course_task_history (history_kind, user_id, event_time DESC, id DESC)
                        """
                    )
                    self._conn.commit()
                self._initialized = True
            except Exception:
                logger.exception("sqlite ensure_tables failed")

    def upsert_task(self, task_kind: str, task_state_public: dict[str, Any]) -> None:
        if not task_kind or not isinstance(task_state_public, dict):
            return
        task_id = str(task_state_public.get("task_id") or "").strip()
        user_id = str(task_state_public.get("user_id") or "").strip()
        if not task_id or not user_id:
            return
        status = str(task_state_public.get("status") or "pending")
        message = str(task_state_public.get("message") or "")
        started_at = _parse_datetime(task_state_public.get("started_at") or task_state_public.get("created_at"))
        updated_at = _parse_datetime(task_state_public.get("updated_at")) or started_at or datetime.now(UTC)
        payload = _normalize_json(task_state_public)
        self.ensure_tables()
        try:
            with self._write_lock:
                self._conn.execute(
                    """
                    INSERT INTO course_task_store
                    (task_id, user_id, task_kind, status, message, started_at, updated_at, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (task_kind, task_id)
                    DO UPDATE SET
                        user_id = excluded.user_id,
                        status = excluded.status,
                        message = excluded.message,
                        started_at = COALESCE(course_task_store.started_at, excluded.started_at),
                        updated_at = excluded.updated_at,
                        payload = excluded.payload
                    """,
                    (
                        task_id,
                        user_id,
                        task_kind,
                        status,
                        message,
                        _iso_or_none(started_at),
                        _iso_or_none(updated_at),
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
                self._conn.commit()
        except Exception:
            logger.exception("sqlite upsert_task failed: kind=%s task_id=%s", task_kind, task_id)

    def get_task(self, task_kind: str, task_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        if not task_kind or not task_id:
            return None
        self.ensure_tables()
        try:
            if user_id:
                cur = self._conn.execute(
                    """
                    SELECT task_id, user_id, task_kind, status, message, started_at, updated_at, payload
                    FROM course_task_store
                    WHERE task_kind = ? AND task_id = ? AND user_id = ?
                    LIMIT 1
                    """,
                    (task_kind, str(task_id), str(user_id)),
                )
            else:
                cur = self._conn.execute(
                    """
                    SELECT task_id, user_id, task_kind, status, message, started_at, updated_at, payload
                    FROM course_task_store
                    WHERE task_kind = ? AND task_id = ?
                    LIMIT 1
                    """,
                    (task_kind, str(task_id)),
                )
            row = cur.fetchone()
        except Exception:
            logger.exception("sqlite get_task failed: kind=%s task_id=%s", task_kind, task_id)
            return None
        if not row:
            return None
        return self._row_to_task(row)

    def list_tasks(self, task_kind: str, user_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if not task_kind:
            return []
        safe_limit = max(1, min(int(limit or 50), 2000))
        self.ensure_tables()
        try:
            if user_id:
                cur = self._conn.execute(
                    """
                    SELECT task_id, user_id, task_kind, status, message, started_at, updated_at, payload
                    FROM course_task_store
                    WHERE task_kind = ? AND user_id = ?
                    ORDER BY (updated_at IS NULL), updated_at DESC, task_id DESC
                    LIMIT ?
                    """,
                    (task_kind, str(user_id), safe_limit),
                )
            else:
                cur = self._conn.execute(
                    """
                    SELECT task_id, user_id, task_kind, status, message, started_at, updated_at, payload
                    FROM course_task_store
                    WHERE task_kind = ?
                    ORDER BY (updated_at IS NULL), updated_at DESC, task_id DESC
                    LIMIT ?
                    """,
                    (task_kind, safe_limit),
                )
            rows = cur.fetchall() or []
        except Exception:
            logger.exception("sqlite list_tasks failed: kind=%s user=%s", task_kind, user_id)
            return []
        return [self._row_to_task(r) for r in rows]

    def append_history(self, history_kind: str, user_id: str, record: dict[str, Any], max_records: int = 500) -> None:
        if not history_kind or not user_id or not isinstance(record, dict):
            return
        payload = _normalize_json(record)
        event_time = (
            _parse_datetime(payload.get("timestamp")) or _parse_datetime(payload.get("updated_at")) or datetime.now(UTC)
        )
        if not payload.get("timestamp"):
            payload["timestamp"] = _datetime_to_iso(event_time)
        safe_keep = max(1, min(int(max_records or 500), 5000))
        self.ensure_tables()
        try:
            with self._write_lock:
                self._conn.execute(
                    """
                    INSERT INTO course_task_history
                    (history_kind, user_id, status, message, event_time, payload)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        history_kind,
                        str(user_id),
                        str(payload.get("status") or ""),
                        str(payload.get("message") or ""),
                        _iso_or_none(event_time),
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
                self._conn.execute(
                    """
                    DELETE FROM course_task_history
                    WHERE history_kind = ?
                      AND user_id = ?
                      AND id NOT IN (
                          SELECT id FROM course_task_history
                          WHERE history_kind = ? AND user_id = ?
                          ORDER BY event_time DESC, id DESC
                          LIMIT ?
                      )
                    """,
                    (history_kind, str(user_id), history_kind, str(user_id), safe_keep),
                )
                self._conn.commit()
        except Exception:
            logger.exception("sqlite append_history failed: kind=%s user=%s", history_kind, user_id)

    def list_history(self, history_kind: str, user_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        if not history_kind:
            return []
        safe_limit = max(1, min(int(limit or 500), 5000))
        self.ensure_tables()
        try:
            if user_id:
                cur = self._conn.execute(
                    """
                    SELECT user_id, event_time, payload
                    FROM course_task_history
                    WHERE history_kind = ? AND user_id = ?
                    ORDER BY event_time DESC, id DESC
                    LIMIT ?
                    """,
                    (history_kind, str(user_id), safe_limit),
                )
            else:
                cur = self._conn.execute(
                    """
                    SELECT user_id, event_time, payload
                    FROM course_task_history
                    WHERE history_kind = ?
                    ORDER BY event_time DESC, id DESC
                    LIMIT ?
                    """,
                    (history_kind, safe_limit),
                )
            rows = cur.fetchall() or []
        except Exception:
            logger.exception("sqlite list_history failed: kind=%s user=%s", history_kind, user_id)
            return []
        history: list[dict[str, Any]] = []
        for row in rows:
            payload = self._load_payload(row.get("payload"))
            if not payload.get("timestamp"):
                payload["timestamp"] = _datetime_to_iso(row.get("event_time"))
            if not user_id:
                payload["user_id"] = str(row.get("user_id") or "")
            history.append(payload)
        return history

    # --- shaping (mirrors the row→dict logic in task_store.py:242-261/311-330) ---
    @staticmethod
    def _load_payload(raw: Any) -> dict[str, Any]:
        if isinstance(raw, str) and raw:
            try:
                loaded = json.loads(raw)
            except Exception:
                loaded = {}
        elif isinstance(raw, dict):
            loaded = raw
        else:
            loaded = {}
        return dict(loaded) if isinstance(loaded, dict) else {}

    def _row_to_task(self, row: dict[str, Any]) -> dict[str, Any]:
        item = self._load_payload(row.get("payload"))
        item["task_id"] = str(row.get("task_id") or item.get("task_id") or "")
        item["user_id"] = str(row.get("user_id") or item.get("user_id") or "")
        item["status"] = str(row.get("status") or item.get("status") or "")
        item["message"] = str(row.get("message") or item.get("message") or "")
        started_at = _datetime_to_iso(row.get("started_at"))
        updated_at = _datetime_to_iso(row.get("updated_at"))
        if started_at:
            item["started_at"] = started_at
        elif item.get("started_at") is not None:
            item["started_at"] = str(item.get("started_at"))
        if updated_at:
            item["updated_at"] = updated_at
        elif item.get("updated_at") is not None:
            item["updated_at"] = str(item.get("updated_at"))
        return item


class _SqliteProbe:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def ping(self) -> bool:
        try:
            self._conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            logger.exception("sqlite probe ping failed")
            return False


class SqliteStorage:
    def __init__(self, path: str) -> None:
        if not path:
            raise ValueError("SqliteStorage requires a non-empty path (set SQLITE_PATH)")
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = _dict_row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        write_lock = threading.Lock()
        self.tasks = _SqliteTaskStore(self._conn, write_lock)
        self.probe = _SqliteProbe(self._conn)
