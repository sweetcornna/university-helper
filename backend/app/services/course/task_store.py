import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any

from psycopg2.extras import Json

from app.core.credential_crypto import (
    decrypt_dict_fields,
    encrypt_dict_fields,
)
from app.db.session import get_db_session

logger = logging.getLogger(__name__)

# Fields treated as sensitive credentials. Values are encrypted before JSONB
# serialization and decrypted on read. Kept conservative — extend only with
# evidence that the field actually holds a secret.
_SENSITIVE_FIELDS: tuple[str, ...] = (
    "password",
    "user_password",
    "third_party_password",
)
# Nested containers that may hold credentials. We recurse one level into them.
_SENSITIVE_CONTAINERS: tuple[str, ...] = ("credentials",)


def _encrypt_sensitive(payload: dict[str, Any]) -> dict[str, Any]:
    """Encrypt top-level + ``payload.credentials.*`` sensitive keys.

    Fail-closed: if encryption raises, the offending field is DROPPED rather
    than persisted in plaintext. Other fields pass through.
    """
    if not isinstance(payload, dict):
        return payload
    try:
        encrypted = encrypt_dict_fields(payload, _SENSITIVE_FIELDS)
    except Exception:
        logger.exception("task_store: encrypt top-level sensitive fields failed")
        encrypted = dict(payload)
        for field in _SENSITIVE_FIELDS:
            encrypted.pop(field, None)

    for container in _SENSITIVE_CONTAINERS:
        nested = encrypted.get(container)
        if isinstance(nested, dict):
            try:
                encrypted[container] = encrypt_dict_fields(nested, _SENSITIVE_FIELDS)
            except Exception:
                logger.exception("task_store: encrypt nested container=%s failed", container)
                cleaned = dict(nested)
                for field in _SENSITIVE_FIELDS:
                    cleaned.pop(field, None)
                encrypted[container] = cleaned
    return encrypted


def _decrypt_sensitive(payload: dict[str, Any]) -> dict[str, Any]:
    """Decrypt top-level + ``payload.credentials.*`` sensitive keys.

    Legacy (non-``fernet:``-prefixed) values pass through unchanged.
    """
    if not isinstance(payload, dict):
        return payload
    try:
        decrypted = decrypt_dict_fields(payload, _SENSITIVE_FIELDS)
    except Exception:
        logger.exception("task_store: decrypt top-level sensitive fields failed")
        decrypted = dict(payload)

    for container in _SENSITIVE_CONTAINERS:
        nested = decrypted.get(container)
        if isinstance(nested, dict):
            try:
                decrypted[container] = decrypt_dict_fields(nested, _SENSITIVE_FIELDS)
            except Exception:
                logger.exception("task_store: decrypt nested container=%s failed", container)
    return decrypted


class TaskStore:
    def __init__(self) -> None:
        self._init_lock = threading.Lock()
        self._initialized = False

    def ensure_tables(self) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            try:
                with get_db_session() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS course_task_store (
                            task_id VARCHAR(64) NOT NULL,
                            user_id VARCHAR(64) NOT NULL,
                            task_kind VARCHAR(64) NOT NULL,
                            status VARCHAR(32) NOT NULL,
                            message TEXT,
                            started_at TIMESTAMPTZ,
                            updated_at TIMESTAMPTZ,
                            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
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
                            id BIGSERIAL PRIMARY KEY,
                            history_kind VARCHAR(64) NOT NULL,
                            user_id VARCHAR(64) NOT NULL,
                            status VARCHAR(32),
                            message TEXT,
                            event_time TIMESTAMPTZ NOT NULL,
                            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                        """
                    )
                    cur.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_course_task_history_lookup
                        ON course_task_history (history_kind, user_id, event_time DESC, id DESC)
                        """
                    )
                    cur.close()
                self._initialized = True
            except Exception:
                logger.exception("task_store ensure_tables failed")

    def upsert_task(self, task_kind: str, task_state_public: dict[str, Any]) -> None:
        if not task_kind or not isinstance(task_state_public, dict):
            return
        task_id = str(task_state_public.get("task_id") or "").strip()
        user_id = str(task_state_public.get("user_id") or "").strip()
        if not task_id or not user_id:
            return

        status = str(task_state_public.get("status") or "pending")
        message = str(task_state_public.get("message") or "")
        started_at = self._parse_datetime(task_state_public.get("started_at") or task_state_public.get("created_at"))
        updated_at = self._parse_datetime(task_state_public.get("updated_at")) or started_at or datetime.now(UTC)
        payload = self._normalize_json(task_state_public)
        payload = _encrypt_sensitive(payload)

        self.ensure_tables()
        try:
            with get_db_session() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO course_task_store
                    (task_id, user_id, task_kind, status, message, started_at, updated_at, payload)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (task_kind, task_id)
                    DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        status = EXCLUDED.status,
                        message = EXCLUDED.message,
                        started_at = COALESCE(course_task_store.started_at, EXCLUDED.started_at),
                        updated_at = EXCLUDED.updated_at,
                        payload = EXCLUDED.payload
                    """,
                    (
                        task_id,
                        user_id,
                        task_kind,
                        status,
                        message,
                        started_at,
                        updated_at,
                        Json(payload),
                    ),
                )
                cur.close()
        except Exception:
            logger.exception(
                "task_store upsert_task failed: kind=%s task_id=%s",
                task_kind,
                task_id,
            )

    def get_task(
        self,
        task_kind: str,
        task_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not task_kind or not task_id:
            return None

        self.ensure_tables()
        try:
            with get_db_session() as conn:
                cur = conn.cursor()
                if user_id:
                    cur.execute(
                        """
                        SELECT task_id, user_id, task_kind, status, message, started_at, updated_at, payload
                        FROM course_task_store
                        WHERE task_kind = %s AND task_id = %s AND user_id = %s
                        LIMIT 1
                        """,
                        (task_kind, str(task_id), str(user_id)),
                    )
                else:
                    cur.execute(
                        """
                        SELECT task_id, user_id, task_kind, status, message, started_at, updated_at, payload
                        FROM course_task_store
                        WHERE task_kind = %s AND task_id = %s
                        LIMIT 1
                        """,
                        (task_kind, str(task_id)),
                    )
                row = cur.fetchone()
                cur.close()
        except Exception:
            logger.exception(
                "task_store get_task failed: kind=%s task_id=%s user=%s",
                task_kind,
                task_id,
                user_id,
            )
            return None

        if not row:
            return None

        payload = row.get("payload")
        item = dict(payload) if isinstance(payload, dict) else {}
        item = _decrypt_sensitive(item)
        item["task_id"] = str(row.get("task_id") or item.get("task_id") or "")
        item["user_id"] = str(row.get("user_id") or item.get("user_id") or "")
        item["status"] = str(row.get("status") or item.get("status") or "")
        item["message"] = str(row.get("message") or item.get("message") or "")

        started_at = self._datetime_to_iso(row.get("started_at"))
        updated_at = self._datetime_to_iso(row.get("updated_at"))
        if started_at:
            item["started_at"] = started_at
        elif item.get("started_at") is not None:
            item["started_at"] = str(item.get("started_at"))
        if updated_at:
            item["updated_at"] = updated_at
        elif item.get("updated_at") is not None:
            item["updated_at"] = str(item.get("updated_at"))

        return item

    def list_tasks(
        self,
        task_kind: str,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not task_kind:
            return []

        safe_limit = max(1, min(int(limit or 50), 2000))
        self.ensure_tables()
        try:
            with get_db_session() as conn:
                cur = conn.cursor()
                if user_id:
                    cur.execute(
                        """
                        SELECT task_id, user_id, task_kind, status, message, started_at, updated_at, payload
                        FROM course_task_store
                        WHERE task_kind = %s AND user_id = %s
                        ORDER BY updated_at DESC NULLS LAST, task_id DESC
                        LIMIT %s
                        """,
                        (task_kind, str(user_id), safe_limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT task_id, user_id, task_kind, status, message, started_at, updated_at, payload
                        FROM course_task_store
                        WHERE task_kind = %s
                        ORDER BY updated_at DESC NULLS LAST, task_id DESC
                        LIMIT %s
                        """,
                        (task_kind, safe_limit),
                    )
                rows = cur.fetchall() or []
                cur.close()
        except Exception:
            logger.exception(
                "task_store list_tasks failed: kind=%s user=%s",
                task_kind,
                user_id,
            )
            return []

        result: list[dict[str, Any]] = []
        for row in rows:
            payload = row.get("payload")
            item = dict(payload) if isinstance(payload, dict) else {}
            item = _decrypt_sensitive(item)
            item["task_id"] = str(row.get("task_id") or item.get("task_id") or "")
            item["user_id"] = str(row.get("user_id") or item.get("user_id") or "")
            item["status"] = str(row.get("status") or item.get("status") or "")
            item["message"] = str(row.get("message") or item.get("message") or "")

            started_at = self._datetime_to_iso(row.get("started_at"))
            updated_at = self._datetime_to_iso(row.get("updated_at"))
            if started_at:
                item["started_at"] = started_at
            elif item.get("started_at") is not None:
                item["started_at"] = str(item.get("started_at"))
            if updated_at:
                item["updated_at"] = updated_at
            elif item.get("updated_at") is not None:
                item["updated_at"] = str(item.get("updated_at"))

            result.append(item)
        return result

    def append_history(
        self,
        history_kind: str,
        user_id: str,
        record: dict[str, Any],
        max_records: int = 500,
    ) -> None:
        if not history_kind or not user_id or not isinstance(record, dict):
            return

        payload = self._normalize_json(record)
        event_time = (
            self._parse_datetime(payload.get("timestamp"))
            or self._parse_datetime(payload.get("updated_at"))
            or datetime.now(UTC)
        )
        if not payload.get("timestamp"):
            payload["timestamp"] = self._datetime_to_iso(event_time)
        payload = _encrypt_sensitive(payload)

        safe_keep = max(1, min(int(max_records or 500), 5000))
        self.ensure_tables()
        try:
            with get_db_session() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO course_task_history
                    (history_kind, user_id, status, message, event_time, payload)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        history_kind,
                        str(user_id),
                        str(payload.get("status") or ""),
                        str(payload.get("message") or ""),
                        event_time,
                        Json(payload),
                    ),
                )
                cur.execute(
                    """
                    DELETE FROM course_task_history
                    WHERE history_kind = %s
                      AND user_id = %s
                      AND id NOT IN (
                          SELECT id FROM course_task_history
                          WHERE history_kind = %s AND user_id = %s
                          ORDER BY event_time DESC, id DESC
                          LIMIT %s
                      )
                    """,
                    (
                        history_kind,
                        str(user_id),
                        history_kind,
                        str(user_id),
                        safe_keep,
                    ),
                )
                cur.close()
        except Exception:
            logger.exception(
                "task_store append_history failed: kind=%s user=%s",
                history_kind,
                user_id,
            )

    def list_history(
        self,
        history_kind: str,
        user_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if not history_kind:
            return []

        safe_limit = max(1, min(int(limit or 500), 5000))
        self.ensure_tables()
        try:
            with get_db_session() as conn:
                cur = conn.cursor()
                if user_id:
                    cur.execute(
                        """
                        SELECT user_id, event_time, payload
                        FROM course_task_history
                        WHERE history_kind = %s AND user_id = %s
                        ORDER BY event_time DESC, id DESC
                        LIMIT %s
                        """,
                        (history_kind, str(user_id), safe_limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT user_id, event_time, payload
                        FROM course_task_history
                        WHERE history_kind = %s
                        ORDER BY event_time DESC, id DESC
                        LIMIT %s
                        """,
                        (history_kind, safe_limit),
                    )
                rows = cur.fetchall() or []
                cur.close()
        except Exception:
            logger.exception(
                "task_store list_history failed: kind=%s user=%s",
                history_kind,
                user_id,
            )
            return []

        history: list[dict[str, Any]] = []
        for row in rows:
            payload = row.get("payload")
            item = dict(payload) if isinstance(payload, dict) else {}
            item = _decrypt_sensitive(item)
            if not item.get("timestamp"):
                item["timestamp"] = self._datetime_to_iso(row.get("event_time"))
            if not user_id:
                item["user_id"] = str(row.get("user_id") or "")
            history.append(item)
        return history

    @staticmethod
    def _normalize_json(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            raw = value
        else:
            raw = {}
        try:
            return json.loads(json.dumps(raw, ensure_ascii=False, default=str))
        except Exception:
            return {}

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=UTC)
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed
        return None

    @staticmethod
    def _datetime_to_iso(value: Any) -> str:
        parsed = TaskStore._parse_datetime(value)
        if parsed is None:
            return ""
        return parsed.astimezone(UTC).isoformat()


task_store = TaskStore()
