"""Shared admission and in-memory retention rules for background tasks."""

from __future__ import annotations

import time
from collections.abc import Mapping, MutableMapping
from datetime import UTC, datetime
from typing import Any

ACTIVE_TASK_STATUSES = frozenset({"running", "pending", "paused", "cancelling", "stopping"})
TERMINAL_TASK_STATUSES = frozenset({"completed", "failed", "cancelled", "error"})

# These limits apply to each manager's in-memory task registry.  They are
# deliberately conservative so a burst of users cannot retain an unbounded
# number of worker records, while still leaving enough room for task history.
MAX_ACTIVE_TASKS = 64
MAX_TASK_RECORDS = 256
TASK_RECORD_TTL_SECONDS = 2 * 60 * 60

TASK_ALREADY_ACTIVE_DETAIL = "An active task already exists for this user"
TASK_CAPACITY_DETAIL = "Task capacity reached; retry later"


class TaskAdmissionError(RuntimeError):
    """Safe, stable error raised when a background task cannot be admitted."""

    status_code = 409
    detail = TASK_ALREADY_ACTIVE_DETAIL

    def __init__(self, *, status_code: int | None = None, detail: str | None = None) -> None:
        if status_code is not None:
            self.status_code = status_code
        if detail is not None:
            self.detail = detail
        super().__init__(self.detail)


class TaskAlreadyActiveError(TaskAdmissionError):
    """The user already owns an active task for this manager."""

    def __init__(self) -> None:
        super().__init__(status_code=409, detail=TASK_ALREADY_ACTIVE_DETAIL)


class TaskCapacityError(TaskAdmissionError):
    """The manager has reached its active-task capacity."""

    def __init__(self) -> None:
        super().__init__(status_code=429, detail=TASK_CAPACITY_DETAIL)


def is_active_status(status: object) -> bool:
    return str(status or "").strip().lower() in ACTIVE_TASK_STATUSES


def is_terminal_status(status: object) -> bool:
    return str(status or "").strip().lower() in TERMINAL_TASK_STATUSES


def count_active_tasks(tasks: MutableMapping[str, dict[str, Any]]) -> int:
    return sum(1 for task in tasks.values() if is_active_status(task.get("status")))


_MIN_UTC_DATETIME = datetime.min.replace(tzinfo=UTC)


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        try:
            parsed = datetime.fromtimestamp(float(value), UTC)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None
    try:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
    except (OverflowError, OSError, ValueError):
        return None


def task_datetime(task: Mapping[str, Any]) -> datetime:
    """Return a fail-safe UTC timestamp from the task's existing time fields."""
    for key in ("updated_at", "started_at", "created_at", "start_time"):
        parsed = _parse_datetime(task.get(key))
        if parsed is not None:
            return parsed
    return _MIN_UTC_DATETIME


def task_sort_key(task: Mapping[str, Any]) -> tuple[datetime, str]:
    """Return a deterministic UTC timestamp and task-id tie-breaker."""
    return task_datetime(task), str(task.get("task_id") or "")


def sort_task_records(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort records newest-first, then by task id for deterministic ties."""
    by_task_id = sorted(tasks, key=lambda item: task_sort_key(item)[1])
    return sorted(by_task_id, key=lambda item: task_sort_key(item)[0], reverse=True)


def _task_timestamp(task: Mapping[str, Any]) -> float | None:
    parsed = task_datetime(task)
    if parsed == _MIN_UTC_DATETIME:
        return None
    return parsed.timestamp()


def cleanup_task_records(
    tasks: MutableMapping[str, dict[str, Any]],
    *,
    now: float | None = None,
    ttl_seconds: int = TASK_RECORD_TTL_SECONDS,
    max_records: int = MAX_TASK_RECORDS,
) -> None:
    """Remove expired/old non-active records while never evicting active work.

    Callers hold their manager lock while invoking this helper.  The storage
    payload is intentionally untouched: this is only an in-memory retention
    policy, and a recently completed task remains available until its TTL or
    the explicit LRU bound is reached.
    """
    current = time.time() if now is None else float(now)
    cutoff = current - max(0, int(ttl_seconds))

    for task_id, task in list(tasks.items()):
        if not is_terminal_status(task.get("status")):
            continue
        timestamp = _task_timestamp(task)
        if timestamp is not None and timestamp < cutoff:
            tasks.pop(task_id, None)

    overflow = len(tasks) - max(1, int(max_records))
    if overflow <= 0:
        return

    evictable: list[tuple[float, str]] = []
    for task_id, task in tasks.items():
        if is_active_status(task.get("status")):
            continue
        timestamp = _task_timestamp(task)
        evictable.append((timestamp if timestamp is not None else float("-inf"), task_id))
    evictable.sort(key=lambda item: (item[0], item[1]))
    for _, task_id in evictable[:overflow]:
        tasks.pop(task_id, None)
