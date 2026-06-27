"""Storage Protocols + shared (crypto-free) shaping helpers.

This module is intentionally psycopg2-free so the SQLite path never imports it.
The shaping helpers are lifted verbatim from the pre-refactor TaskStore statics.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TaskStoreProtocol(Protocol):
    def ensure_tables(self) -> None: ...
    def upsert_task(self, task_kind: str, task_state_public: dict[str, Any]) -> None: ...
    def get_task(self, task_kind: str, task_id: str, user_id: str | None = None) -> dict[str, Any] | None: ...
    def list_tasks(self, task_kind: str, user_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]: ...
    def append_history(
        self, history_kind: str, user_id: str, record: dict[str, Any], max_records: int = 500
    ) -> None: ...
    def list_history(self, history_kind: str, user_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]: ...


@runtime_checkable
class DbProbe(Protocol):
    def ping(self) -> bool: ...


@runtime_checkable
class Storage(Protocol):
    tasks: TaskStoreProtocol
    probe: DbProbe


def _normalize_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        raw = value
    else:
        raw = {}
    try:
        return json.loads(json.dumps(raw, ensure_ascii=False, default=str))
    except Exception:
        return {}


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


def _datetime_to_iso(value: Any) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return ""
    return parsed.astimezone(UTC).isoformat()
