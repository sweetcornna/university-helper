from datetime import UTC, datetime

from app.storage.base import (
    DbProbe,
    Storage,
    TaskStoreProtocol,
    _datetime_to_iso,
    _normalize_json,
    _parse_datetime,
)


def test_protocols_are_runtime_checkable():
    class _T:
        def ensure_tables(self): ...
        def upsert_task(self, task_kind, task_state_public): ...
        def get_task(self, task_kind, task_id, user_id=None): ...
        def list_tasks(self, task_kind, user_id=None, limit=50): ...
        def append_history(self, history_kind, user_id, record, max_records=500): ...
        def list_history(self, history_kind, user_id=None, limit=500): ...

    class _P:
        def ping(self):
            return True

    class _S:
        tasks = _T()
        probe = _P()

    assert isinstance(_T(), TaskStoreProtocol)
    assert isinstance(_P(), DbProbe)
    assert isinstance(_S(), Storage)


def test_shaping_helpers_match_legacy_behavior():
    assert _normalize_json({"a": 1}) == {"a": 1}
    assert _normalize_json("nope") == {}
    dt = _parse_datetime("2026-01-02T03:04:05Z")
    assert dt == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert _datetime_to_iso(dt) == "2026-01-02T03:04:05+00:00"
    assert _datetime_to_iso(None) == ""
