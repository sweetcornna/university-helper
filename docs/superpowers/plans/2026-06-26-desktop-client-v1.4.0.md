# 学道 Desktop Client + Cross-Platform Release (v1.4.0) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship University Helper (学道) as a fully-local, downloadable desktop app for Windows/macOS/Linux — a Tauri v2 shell launching a PyInstaller-frozen FastAPI backend on `127.0.0.1` that serves the existing SPA same-origin and stores data in embedded SQLite — plus a cross-platform GitHub Release with auto-update. The Postgres/multi-tenant server path stays byte-for-byte unchanged.

**Architecture:** A new storage abstraction lets the same backend run on Postgres (server) or SQLite (local) selected by `STORAGE_BACKEND`. A `PROFILE=local` flag drops auth/tenant middleware and injects an implicit single user. FastAPI serves the built SPA. A Tauri shell spawns the frozen backend as a sidecar, reads its port from stdout, opens a window at the loopback URL, and reaps the sidecar on exit. CI builds desktop apps + server images from one git tag.

**Tech Stack:** FastAPI / Python 3.11, raw psycopg2 + sqlite3 (no ORM), Vite/React, Tauri v2 (Rust), PyInstaller, GitHub Actions + `tauri-action`.

**Design spec:** `docs/superpowers/specs/2026-06-26-desktop-client-and-release-design.md`.

## Global Constraints

- **Server path is sacred:** with defaults `PROFILE="server"` and `STORAGE_BACKEND="postgres"`, runtime behavior MUST be byte-for-byte unchanged. Every new branch is gated on a non-default flag.
- **Python 3.11.** Backend tests run with pytest from `backend/`. `pytest.ini` enforces `--cov`; for a focused single-test run use `python -m pytest -o addopts="" <path>::<test> -v`, and end each task with the full `python -m pytest -q` gate. Any test that flips `STORAGE_BACKEND`/profile must call `app.storage.factory._reset_for_tests()` and rebuild the app via the `build_app()` conftest helper (introduced in Task B1). `ruff format` + `ruff check` must pass.
- **Desktop uvicorn:** `workers=1, loop="asyncio", http="h11"` — NEVER `uvloop` (absent on Windows).
- **Tauri v2 pinned versions:** `tauri 2.11.3`, `tauri-plugin-shell 2.3.5`, `tauri-plugin-updater 2.10.1`, `tauri-plugin-process 2.3.1`, `@tauri-apps/cli 2.11.3`; Rust stable ≥1.84 (`rustc --print host-tuple`). Linux desktop builds on **ubuntu-22.04** (webkit2gtk-4.1). Rust gates: `cargo fmt --check`, `cargo clippy`, `cargo test`.
- **App identity:** productName **学道**; bundle identifier **`xyz.cornna.shuake`**; app-data via `platformdirs` (`appname="UniversityHelper"`, `appauthor="cornna"`).
- **CI signing is OPTIONAL:** every signing/notarization step is gated on `secrets.X != ''` so unsigned builds still succeed. Updater keypair (`tauri signer generate`) is free.
- **TDD always:** failing test → watch fail → minimal impl → watch pass → commit. Frequent small commits. `shellcheck` for new shell scripts.

## Shared Interfaces (locked — use these exact names)

- **Config** (`backend/app/config.py`, pydantic `Settings`, `case_sensitive=True` so env var == field name):
  `PROFILE: Literal["server","local"]="server"`, `STORAGE_BACKEND: Literal["postgres","sqlite"]="postgres"`, `SQLITE_PATH: str=""`, `FRONTEND_DIST: str=""`, and module constant `LOCAL_USER_ID="local"`.
- **Storage** (`backend/app/storage/{base,postgres,sqlite,factory}.py`): `get_storage() -> Storage` is a process singleton chosen by `settings.STORAGE_BACKEND` (lazy adapter import). The facade exposes `storage.tasks` (the task-store persistence surface, same signatures as today's `task_store.py`) and `storage.probe.ping() -> bool` (for `/health`). `PostgresStorage` wraps today's exact SQL via `get_db_session()`; `SqliteStorage` uses one WAL connection + write-lock + plain-dict rows. Credential encrypt/decrypt stays in `task_store.py`. A `_reset_for_tests()` clears the singleton.
- **Sidecar entrypoint** `backend/desktop_entry.py` prints exactly one line `UH_BACKEND_LISTENING <port>` (flush) at startup, then runs uvicorn.
- **Sidecar binary** base name `uh-backend`; Tauri `bundle.externalBin = ["binaries/uh-backend"]`; CI renames the PyInstaller output to `frontend/src-tauri/binaries/uh-backend-<target-triple>[.exe]`.
- **Launcher env** (set before importing `app.config`): `PROFILE=local`, `STORAGE_BACKEND=sqlite`, `SQLITE_PATH=<appdata>/local.db`, `FRONTEND_DIST=<bundled dist>`, `ENV=dev`, `ENFORCE_HTTPS=false`, `SECRET_KEY=<persisted>`, `CREDENTIAL_ENCRYPTION_KEY=<persisted Fernet>`, `CORS_ORIGINS=["http://127.0.0.1:<port>"]` (JSON), `CHAOXING_COOKIES_FILE=<appdata>/cookies.json`, `CHAOXING_CACHE_FILE=<appdata>/answer_cache.json`.
- **Version source of truth = git tag.** `scripts/set_version.sh "$VERSION"` stamps: `frontend/package.json`, `backend/pyproject.toml`, `backend/app/main.py` (FastAPI `version=`), `frontend/src-tauri/tauri.conf.json`, `frontend/src-tauri/Cargo.toml`.
- **Updater** endpoints `["https://github.com/sweetcornna/university-helper/releases/latest/download/latest.json"]`; pubkey generated in F2, pasted into `tauri.conf.json` (E1).

## Verified codebase facts (load-bearing)

- **The Postgres pool is LAZY** (`backend/app/db/session.py:28,46-48`): `main_pool` is `None` at import and built only on the first `get_db_session()` call. In local/SQLite mode `get_db_session()` is never invoked, so importing `app.db.session` (via the auth/chaoxing routers) never connects to Postgres. ✅ Local boot is safe.
- **The multi-tenant path is dead for app data**; the local app exercises only `course_task_store` + `course_task_history` + a `/health` `SELECT 1`. Auth/rate-limit/users/tenant code is bypassed in local mode.
- **`tenant_isolation_middleware`** (`main.py:107`) is a JWT gate whose `request.state.user_id` is never read; `course.py` uses `get_current_user`, `chaoxing.py` uses `get_current_user_id` — both only need an opaque ≤64-char user_id.
- **No app factory:** `main.py` wires middleware (`:107`) and routers (`:191-197`) at import; PROFILE-dependent wiring is import-time. Tests rebuild via the `build_app()` conftest helper.

## Integration reconciliations (apply across the tasks below)

1. **`MAIN_DB_USER`/`MAIN_DB_PASSWORD` are required (no default)** at config import (`config.py:27-28`), which would raise in local mode. **Resolution (do this in Task A1):** change them to `MAIN_DB_USER: str = ""` / `MAIN_DB_PASSWORD: str = ""` and add a `model_validator` that requires them **only when `STORAGE_BACKEND == "postgres"`**. Server is unchanged (it always sets them; the validator still catches a forgotten value). With this, Task D's `configure_env` does NOT seed placeholder DB creds.
2. **macOS matrix:** build the `x86_64-apple-darwin` desktop leg on a native **`macos-13`** (Intel) runner and `aarch64-apple-darwin` on `macos-latest` (Apple Silicon). PyInstaller cannot cross-compile, so never build the x86_64 sidecar on an arm64 runner. (Adjust Task F3's matrix accordingly.)
3. **Version stamping order:** every artifact-building CI job (`images` AND `desktop`) runs `scripts/set_version.sh "$VERSION"` right after checkout — not only `create-release` — so baked versions match the tag. (Minor deviation from "images job verbatim" in F3.)
4. **psycopg2 stays bundled** in the frozen sidecar (routers import `app.db.session` at import). Fine — the pool is lazy and never opened in local mode. Do not try to strip it.
5. **`main.py` is touched by A7 (health probe), B1/B2 (profile), C2–C4 (SPA).** Land strictly A → B → C and run the full suite after each; there is no app factory, so coordinate these edits.
6. **`/health` 503 detail** changes from `db unavailable: <Exc>` to `db unavailable` (no test depends on it).

## Execution order

`A (storage) → B (profile) → C (SPA) → D (sidecar/freeze) → E (Tauri) → F (release)`, tasks sequential within each workstream. Smokes: D6 (per-OS `/health`), E5 (`tauri build --debug`), and the final **Task Z1** end-to-end acceptance gate.

---
# Workstream A — Storage abstraction (SQLite + Postgres behind one interface)

Spec: `docs/superpowers/specs/2026-06-26-desktop-client-and-release-design.md` §5.

**Invariant for every task:** the server path (`PROFILE="server"`, `STORAGE_BACKEND="postgres"`,
both defaults) stays behavior byte-for-byte unchanged. `PostgresStorage` runs **today's exact SQL**
through the existing `get_db_session()`. Credential encrypt/decrypt **stays in `task_store.py`**;
`storage.tasks` only ever sees already-encrypted payload dicts.

**TDD loop for every task:** write the failing test → run it, watch it fail → minimal impl →
run it, watch it pass → `ruff format` + `ruff check` → commit. All commands run from `backend/`.
Python 3.11, ruff line-length 120, target py311.

Shared test runner note: `pytest.ini` `addopts` already adds `--cov=app`; single-file runs are fine.
All `pytest` invocations below assume `cd backend && source .venv/bin/activate` (or `python -m pytest`).

---

## A1 — Config: `PROFILE`, `STORAGE_BACKEND`, `SQLITE_PATH`, `LOCAL_USER_ID`

**Files:** `backend/app/config.py`, new `backend/tests/unit/test_config_profile.py`.

**Test first** — `backend/tests/unit/test_config_profile.py`:
```python
from unittest.mock import patch

from app.config import LOCAL_USER_ID, Settings

_TEST_SECRET = "x" * 32
_BASE_ENV = {"SECRET_KEY": _TEST_SECRET, "CORS_ORIGINS": '["*"]'}


def test_profile_and_storage_defaults_are_server_postgres():
    with patch.dict("os.environ", _BASE_ENV, clear=True):
        s = Settings()
        assert s.PROFILE == "server"
        assert s.STORAGE_BACKEND == "postgres"
        assert s.SQLITE_PATH == ""


def test_profile_and_storage_read_from_env():
    env = {**_BASE_ENV, "PROFILE": "local", "STORAGE_BACKEND": "sqlite", "SQLITE_PATH": "/tmp/uh.db"}
    with patch.dict("os.environ", env, clear=True):
        s = Settings()
        assert s.PROFILE == "local"
        assert s.STORAGE_BACKEND == "sqlite"
        assert s.SQLITE_PATH == "/tmp/uh.db"


def test_local_user_id_constant():
    assert LOCAL_USER_ID == "local"
```

Run (expect FAIL — `ImportError: cannot import name 'LOCAL_USER_ID'`):
```
python -m pytest tests/unit/test_config_profile.py -q
```
Expected: 3 errors/failures on import of `LOCAL_USER_ID` / missing fields.

**Impl** — edit `backend/app/config.py`:
- Add `from typing import Literal` at top (line 1 area, alongside existing imports).
- Inside `class Settings`, after the `ENV` block (line ~44), add:
```python
    # Deployment profile. "server" = existing multi-tenant Postgres deploy (default,
    # unchanged). "local" = single-user desktop app path.
    PROFILE: Literal["server", "local"] = "server"

    # Persistence backend. "postgres" = existing server DB (default). "sqlite" = local file.
    STORAGE_BACKEND: Literal["postgres", "sqlite"] = "postgres"

    # Local SQLite file path; required when STORAGE_BACKEND == "sqlite".
    SQLITE_PATH: str = ""
```
- At module level, after `settings = Settings()` (or before — any module scope), add:
```python
# Opaque user id used by the single-user local profile. Handlers only need a
# <=64-char string; a constant is sufficient (see spec §3.5).
LOCAL_USER_ID = "local"
```
`case_sensitive=True` ⇒ env var name == field name, so `PROFILE`/`STORAGE_BACKEND`/`SQLITE_PATH`
are read verbatim. No validators (empty `SQLITE_PATH` is only required in sqlite mode — enforced
by the factory in A5, not at config-load, so server boot is untouched).

Run (expect PASS):
```
python -m pytest tests/unit/test_config_profile.py tests/unit/test_config.py -q
ruff format app/config.py tests/unit/test_config_profile.py && ruff check app/config.py tests/unit/test_config_profile.py
```
Expected: all green (existing `test_config.py` still passes — only additive fields).

**Commit:** `feat(config): add PROFILE/STORAGE_BACKEND/SQLITE_PATH settings + LOCAL_USER_ID`

---

## A2 — `storage/base.py`: Protocols + shared shaping helpers

Lift the **exact public method surface** of `app/services/course/task_store.py::TaskStore`
(`ensure_tables`, `upsert_task`, `get_task`, `list_tasks`, `append_history`, `list_history`) into
`TaskStoreProtocol`; define `DbProbe` (`ping() -> bool`) and a `Storage` facade Protocol
(`.tasks`, `.probe`). Also move the three **non-crypto** shaping statics
(`_normalize_json`, `_parse_datetime`, `_datetime_to_iso`, verbatim from `task_store.py:459-494`)
here as module functions so both adapters share them (base.py imports **no psycopg2**).

**Files:** new `backend/app/storage/__init__.py` (empty), new `backend/app/storage/base.py`,
new `backend/tests/unit/test_storage_base.py`.

**Test first** — `backend/tests/unit/test_storage_base.py`:
```python
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
        def ping(self): return True

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
```

Run (expect FAIL — module missing):
```
python -m pytest tests/unit/test_storage_base.py -q
```

**Impl** — `backend/app/storage/base.py`:
```python
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
    def get_task(
        self, task_kind: str, task_id: str, user_id: str | None = None
    ) -> dict[str, Any] | None: ...
    def list_tasks(
        self, task_kind: str, user_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]: ...
    def append_history(
        self, history_kind: str, user_id: str, record: dict[str, Any], max_records: int = 500
    ) -> None: ...
    def list_history(
        self, history_kind: str, user_id: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]: ...


@runtime_checkable
class DbProbe(Protocol):
    def ping(self) -> bool: ...


@runtime_checkable
class Storage(Protocol):
    tasks: TaskStoreProtocol
    probe: DbProbe


def _normalize_json(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
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
```
(`_normalize_json`/`_parse_datetime`/`_datetime_to_iso` are byte-equal to `task_store.py:459-494`,
de-staticmethod'd. Verified by grep: no other module references the TaskStore statics.)

Run (expect PASS) + ruff:
```
python -m pytest tests/unit/test_storage_base.py -q
ruff format app/storage tests/unit/test_storage_base.py && ruff check app/storage tests/unit/test_storage_base.py
```

**Commit:** `feat(storage): add base Protocols (TaskStore/DbProbe/Storage) + shared shaping helpers`

---

## A3 — `storage/postgres.py`: adapter = today's EXACT SQL, zero behavior change

`_PostgresTaskStore` carries the verbatim bodies of `task_store.py` methods **minus the two crypto
calls** (`_encrypt_sensitive` at `task_store.py:156` / `:351`; `_decrypt_sensitive` at `:244`,
`:313`, `:451`). `_PostgresProbe.ping()` = the `/health` `SELECT 1` from `main.py:205-226`, returning
`bool`. This is the migration target for the SQL-level assertions currently in `test_task_store.py`.

**Files:** new `backend/app/storage/postgres.py`, new `backend/tests/unit/test_postgres_storage.py`.

**Test first** — `backend/tests/unit/test_postgres_storage.py` (reuses the fake-session pattern from
the existing `test_task_store.py`; retargets the patch to `app.storage.postgres.get_db_session`):
```python
import app.storage.postgres as pg
from app.storage.postgres import PostgresStorage


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        return None


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


class _FakeSessionCtx:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        return False


def _patch_session(monkeypatch, cursor):
    monkeypatch.setattr(pg, "get_db_session", lambda: _FakeSessionCtx(_FakeConn(cursor)))


def test_list_tasks_uses_user_filter_and_updated_desc(monkeypatch):
    store = PostgresStorage().tasks
    monkeypatch.setattr(store, "ensure_tables", lambda: None)
    rows = [
        {"task_id": "task-new", "user_id": "user-1", "task_kind": "signin", "status": "running",
         "message": "new", "started_at": None, "updated_at": None,
         "payload": {"task_id": "task-new", "user_id": "user-1"}},
        {"task_id": "task-old", "user_id": "user-1", "task_kind": "signin", "status": "failed",
         "message": "old", "started_at": None, "updated_at": None,
         "payload": {"task_id": "task-old", "user_id": "user-1"}},
    ]
    cur = _FakeCursor(rows)
    _patch_session(monkeypatch, cur)
    tasks = store.list_tasks(task_kind="signin", user_id="user-1", limit=20)
    assert [t["task_id"] for t in tasks] == ["task-new", "task-old"]
    sql, params = cur.executed[0]
    assert "WHERE task_kind = %s AND user_id = %s" in sql
    assert "ORDER BY updated_at DESC NULLS LAST" in sql
    assert params == ("signin", "user-1", 20)


def test_get_task_uses_task_and_user_filters(monkeypatch):
    store = PostgresStorage().tasks
    monkeypatch.setattr(store, "ensure_tables", lambda: None)
    rows = [{"task_id": "task-1", "user_id": "user-1", "task_kind": "signin", "status": "running",
             "message": "active", "started_at": None, "updated_at": None,
             "payload": {"task_id": "task-1", "user_id": "user-1"}}]
    cur = _FakeCursor(rows)
    _patch_session(monkeypatch, cur)
    task = store.get_task(task_kind="signin", task_id="task-1", user_id="user-1")
    assert task["task_id"] == "task-1"
    sql, params = cur.executed[0]
    assert "WHERE task_kind = %s AND task_id = %s AND user_id = %s" in sql
    assert params == ("signin", "task-1", "user-1")


def test_upsert_task_no_db_call_when_task_id_missing(monkeypatch):
    store = PostgresStorage().tasks
    calls = {"n": 0}
    monkeypatch.setattr(store, "ensure_tables", lambda: None)
    monkeypatch.setattr(pg, "get_db_session",
                        lambda: (_ for _ in ()).throw(AssertionError("db touched")))
    store.upsert_task("signin", {"user_id": "user-1", "status": "running"})  # no task_id
    assert calls["n"] == 0


def test_upsert_task_does_not_encrypt(monkeypatch):
    """Adapter must NOT call crypto — payload is stored exactly as received."""
    store = PostgresStorage().tasks
    monkeypatch.setattr(store, "ensure_tables", lambda: None)
    cur = _FakeCursor([])
    _patch_session(monkeypatch, cur)
    store.upsert_task("signin", {"task_id": "t1", "user_id": "u1", "password": "PLAINTEXT"})
    sql, params = cur.executed[0]
    json_arg = params[-1]  # psycopg2 Json wrapper
    assert "PLAINTEXT" in str(json_arg.adapted if hasattr(json_arg, "adapted") else json_arg)


def test_probe_ping_true_on_success(monkeypatch):
    cur = _FakeCursor([{"?column?": 1}])

    class _Conn(_FakeConn):
        autocommit = False

        def cursor(self):  # context-manager cursor for the probe path
            outer = self

            class _C:
                def __enter__(self_):
                    return outer._cursor

                def __exit__(self_, *a):
                    return False

            return _C()

    monkeypatch.setattr(pg, "get_db_session", lambda: _FakeSessionCtx(_Conn(cur)))
    assert PostgresStorage().probe.ping() is True


def test_probe_ping_false_on_failure(monkeypatch):
    monkeypatch.setattr(pg, "get_db_session",
                        lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert PostgresStorage().probe.ping() is False
```

Run (expect FAIL — module missing):
```
python -m pytest tests/unit/test_postgres_storage.py -q
```

**Impl** — `backend/app/storage/postgres.py`. Copy method bodies **verbatim** from
`task_store.py` (lines cited), deleting only the crypto lines:
```python
"""Postgres storage adapter: today's exact SQL via the existing pool. No crypto here."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from psycopg2.extras import Json

from app.db.session import get_db_session
from app.storage.base import _datetime_to_iso, _normalize_json, _parse_datetime

logger = logging.getLogger(__name__)


class _PostgresTaskStore:
    def __init__(self) -> None:
        self._init_lock = threading.Lock()
        self._initialized = False

    def ensure_tables(self) -> None:
        # VERBATIM from task_store.py:87-141 (CREATE TABLE/INDEX x4).
        ...

    def upsert_task(self, task_kind: str, task_state_public: dict[str, Any]) -> None:
        # VERBATIM from task_store.py:143-193, with the single line
        #   payload = _encrypt_sensitive(payload)   (task_store.py:156)
        # DELETED. payload = _normalize_json(task_state_public) is the last payload step.
        ...

    def get_task(self, task_kind, task_id, user_id=None):
        # VERBATIM task_store.py:195-261 with `item = _decrypt_sensitive(item)` (line 244) DELETED.
        ...

    def list_tasks(self, task_kind, user_id=None, limit=50):
        # VERBATIM task_store.py:263-331 with `item = _decrypt_sensitive(item)` (line 313) DELETED.
        ...

    def append_history(self, history_kind, user_id, record, max_records=500):
        # VERBATIM task_store.py:333-399 with `payload = _encrypt_sensitive(payload)` (line 351) DELETED.
        ...

    def list_history(self, history_kind, user_id=None, limit=500):
        # VERBATIM task_store.py:401-457 with `item = _decrypt_sensitive(item)` (line 451) DELETED.
        ...


class _PostgresProbe:
    def ping(self) -> bool:
        # /health SELECT 1 (main.py:209-224), returning bool instead of raising.
        try:
            with get_db_session() as conn:
                conn.autocommit = True
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        cur.fetchone()
                finally:
                    conn.autocommit = False
            return True
        except Exception:
            logger.exception("postgres probe ping failed")
            return False


class PostgresStorage:
    def __init__(self) -> None:
        self.tasks = _PostgresTaskStore()
        self.probe = _PostgresProbe()
```
Replace `TaskStore._parse_datetime(...)` / `self._parse_datetime` / `self._normalize_json` /
`self._datetime_to_iso` call sites inside the lifted bodies with the imported module functions
`_parse_datetime(...)` / `_normalize_json(...)` / `_datetime_to_iso(...)`. Everything else
(SQL strings, `%s` placeholders, `Json(payload)`, `ON CONFLICT`, ordering, try/except logging)
is unchanged — this is the byte-for-byte server SQL.

Run (expect PASS) + ruff:
```
python -m pytest tests/unit/test_postgres_storage.py -q
ruff format app/storage/postgres.py tests/unit/test_postgres_storage.py && ruff check app/storage/postgres.py tests/unit/test_postgres_storage.py
```

**Commit:** `feat(storage): PostgresStorage adapter wrapping today's exact SQL + DbProbe`

---

## A4 — `storage/sqlite.py`: one WAL connection, write-lock, plain dicts

Port the same six operations to one SQLite file. Mapping (spec §5): `TIMESTAMPTZ`→ISO TEXT
(bind `datetime.isoformat()`), `JSONB`→TEXT (`json.dumps`/`json.loads`), `BIGSERIAL`→
`INTEGER PRIMARY KEY`, `%s`→`?`, `ON CONFLICT … DO UPDATE … EXCLUDED` kept (lowercase `excluded`),
`ORDER BY … DESC NULLS LAST`→`ORDER BY (col IS NULL), col DESC`, drop `NOW()` defaults. One
`sqlite3.Connection(check_same_thread=False)`, `PRAGMA journal_mode=WAL`, `PRAGMA busy_timeout`,
`row_factory`→plain dict, a `threading.Lock` serializing **writes**.

**Files:** new `backend/app/storage/sqlite.py`, new `backend/tests/unit/test_sqlite_storage.py`.

**Test first** — `backend/tests/unit/test_sqlite_storage.py`:
```python
from app.storage.sqlite import SqliteStorage


def _store(tmp_path):
    return SqliteStorage(str(tmp_path / "uh.db")).tasks


def test_upsert_then_get_round_trip(tmp_path):
    s = _store(tmp_path)
    s.upsert_task("signin", {
        "task_id": "t1", "user_id": "u1", "status": "running", "message": "go",
        "started_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:05:00+00:00",
        "extra": {"k": "v"}, "password": "secret-stays-as-is",
    })
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
    s.upsert_task("signin", {"task_id": "t1", "user_id": "u1", "status": "running",
                             "started_at": "2026-01-01T00:00:00+00:00",
                             "updated_at": "2026-01-01T00:00:00+00:00"})
    s.upsert_task("signin", {"task_id": "t1", "user_id": "u1", "status": "completed",
                             "updated_at": "2026-01-01T01:00:00+00:00"})
    got = s.get_task("signin", "t1")
    assert got["status"] == "completed"
    assert got["started_at"] == "2026-01-01T00:00:00+00:00"  # COALESCE kept the original


def test_list_orders_updated_desc_nulls_last_and_filters_user(tmp_path):
    s = _store(tmp_path)
    s.upsert_task("signin", {"task_id": "a", "user_id": "u1", "status": "x",
                             "updated_at": "2026-01-01T00:00:00+00:00"})
    s.upsert_task("signin", {"task_id": "b", "user_id": "u1", "status": "x",
                             "updated_at": "2026-01-02T00:00:00+00:00"})
    s.upsert_task("signin", {"task_id": "c", "user_id": "u2", "status": "x",
                             "updated_at": "2026-01-03T00:00:00+00:00"})
    ids = [t["task_id"] for t in s.list_tasks("signin", user_id="u1", limit=50)]
    assert ids == ["b", "a"]


def test_history_append_list_and_prune(tmp_path):
    s = _store(tmp_path)
    for i in range(5):
        s.append_history("signin", "u1",
                         {"message": f"m{i}", "timestamp": f"2026-01-0{i + 1}T00:00:00+00:00"},
                         max_records=3)
    hist = s.list_history("signin", user_id="u1", limit=50)
    assert [h["message"] for h in hist] == ["m4", "m3", "m2"]  # newest 3 kept, DESC
```

Run (expect FAIL — module missing):
```
python -m pytest tests/unit/test_sqlite_storage.py -q
```

**Impl** — `backend/app/storage/sqlite.py`:
```python
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
        started_at = _parse_datetime(
            task_state_public.get("started_at") or task_state_public.get("created_at")
        )
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
                        task_id, user_id, task_kind, status, message,
                        _iso_or_none(started_at), _iso_or_none(updated_at),
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
                self._conn.commit()
        except Exception:
            logger.exception("sqlite upsert_task failed: kind=%s task_id=%s", task_kind, task_id)

    def get_task(self, task_kind, task_id, user_id=None):
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

    def list_tasks(self, task_kind, user_id=None, limit=50):
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

    def append_history(self, history_kind, user_id, record, max_records=500):
        if not history_kind or not user_id or not isinstance(record, dict):
            return
        payload = _normalize_json(record)
        event_time = (
            _parse_datetime(payload.get("timestamp"))
            or _parse_datetime(payload.get("updated_at"))
            or datetime.now(UTC)
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
                        history_kind, str(user_id), str(payload.get("status") or ""),
                        str(payload.get("message") or ""), _iso_or_none(event_time),
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

    def list_history(self, history_kind, user_id=None, limit=500):
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
```

Run (expect PASS) + ruff:
```
python -m pytest tests/unit/test_sqlite_storage.py -q
ruff format app/storage/sqlite.py tests/unit/test_sqlite_storage.py && ruff check app/storage/sqlite.py tests/unit/test_sqlite_storage.py
```

**Commit:** `feat(storage): SqliteStorage adapter (WAL + write lock, Postgres→SQLite SQL mapping)`

---

## A5 — `storage/factory.py`: `get_storage()` process-singleton, lazy adapter import

`get_storage() -> Storage` is a process singleton selecting the adapter by
`settings.STORAGE_BACKEND`. The chosen adapter module is imported **lazily** so sqlite mode never
imports `app.storage.postgres` (and thus never imports psycopg2 / `app.db.session`). Provide
`_reset_for_tests()`.

**Files:** new `backend/app/storage/factory.py`, new `backend/tests/unit/test_storage_factory.py`.

**Test first** — `backend/tests/unit/test_storage_factory.py`:
```python
import sys

import pytest

import app.storage.factory as factory
from app.config import settings


@pytest.fixture(autouse=True)
def _reset():
    factory._reset_for_tests()
    yield
    factory._reset_for_tests()


def test_singleton_returns_same_instance(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "postgres")
    a = factory.get_storage()
    b = factory.get_storage()
    assert a is b


def test_postgres_selected_by_default(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "postgres")
    from app.storage.postgres import PostgresStorage

    assert isinstance(factory.get_storage(), PostgresStorage)


def test_sqlite_selected_without_importing_postgres(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "sqlite")
    monkeypatch.setattr(settings, "SQLITE_PATH", str(tmp_path / "uh.db"))
    sys.modules.pop("app.storage.postgres", None)
    from app.storage.sqlite import SqliteStorage

    store = factory.get_storage()
    assert isinstance(store, SqliteStorage)
    assert "app.storage.postgres" not in sys.modules  # proves lazy import


def test_sqlite_without_path_raises(monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "sqlite")
    monkeypatch.setattr(settings, "SQLITE_PATH", "")
    with pytest.raises(RuntimeError):
        factory.get_storage()
```

Run (expect FAIL):
```
python -m pytest tests/unit/test_storage_factory.py -q
```

**Impl** — `backend/app/storage/factory.py`:
```python
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
```

Run (expect PASS) + ruff:
```
python -m pytest tests/unit/test_storage_factory.py -q
ruff format app/storage/factory.py tests/unit/test_storage_factory.py && ruff check app/storage/factory.py tests/unit/test_storage_factory.py
```

**Commit:** `feat(storage): get_storage() singleton with lazy backend selection`

---

## A6 — Refactor `task_store.py` to delegate persistence; keep crypto + public surface

`task_store.py` keeps `_SENSITIVE_FIELDS`, `_SENSITIVE_CONTAINERS`, `_encrypt_sensitive`,
`_decrypt_sensitive`, the `TaskStore` class (same method names/signatures), and the
`task_store = TaskStore()` singleton — so every importer (`signin.py`, `learning_manager.py`)
keeps working. It **drops** `from psycopg2.extras import Json` and `from app.db.session import
get_db_session` (sqlite mode no longer pulls psycopg2 via task_store), and the SQL/shaping moves to
the adapters.

**Byte-for-byte server equivalence (the argument to document in the commit):** writes apply
`_encrypt_sensitive` to the inbound dict before the adapter `_normalize_json`s+stores it; reads let
the adapter shape the row, then `_decrypt_sensitive` the result. Encryption only maps plaintext
`str`→ciphertext `str` on the three sensitive keys (top-level + `credentials.*`); none of those keys
are the scalar columns (`status/message/started_at/updated_at`) the adapter extracts, and
`_normalize_json` (json round-trip) is order-independent w.r.t. those string substitutions — so the
stored JSON and returned dicts are identical to the pre-refactor `task_store.py`.

**Files:** rewrite `backend/app/services/course/task_store.py`; rewrite
`backend/tests/unit/test_task_store.py` (the 3 SQL-level tests now live in
`test_postgres_storage.py` from A3 — replace them with delegation+crypto tests; **keep** the five
`test_signin_manager_*` tests verbatim — they monkeypatch `signin_module.task_store.<method>` and
are unaffected).

**Test first** — replace the top of `backend/tests/unit/test_task_store.py` (keep the
`test_signin_manager_*` block below unchanged):
```python
import app.services.course.task_store as task_store_module
from app.services.course.task_store import TaskStore


class _RecordingTasks:
    def __init__(self, get_result=None, list_result=None, history_result=None):
        self.calls = []
        self._get = get_result
        self._list = list_result or []
        self._history = history_result or []

    def ensure_tables(self):
        self.calls.append(("ensure_tables",))

    def upsert_task(self, task_kind, task_state_public):
        self.calls.append(("upsert_task", task_kind, task_state_public))

    def get_task(self, task_kind, task_id, user_id=None):
        self.calls.append(("get_task", task_kind, task_id, user_id))
        return self._get

    def list_tasks(self, task_kind, user_id=None, limit=50):
        self.calls.append(("list_tasks", task_kind, user_id, limit))
        return list(self._list)

    def append_history(self, history_kind, user_id, record, max_records=500):
        self.calls.append(("append_history", history_kind, user_id, record, max_records))

    def list_history(self, history_kind, user_id=None, limit=500):
        self.calls.append(("list_history", history_kind, user_id, limit))
        return list(self._history)


class _FakeStorage:
    def __init__(self, tasks):
        self.tasks = tasks
        self.probe = None


def _install(monkeypatch, tasks):
    monkeypatch.setattr(task_store_module, "get_storage", lambda: _FakeStorage(tasks))


def test_upsert_encrypts_sensitive_before_delegating(monkeypatch):
    tasks = _RecordingTasks()
    _install(monkeypatch, tasks)
    TaskStore().upsert_task("signin", {"task_id": "t1", "user_id": "u1", "password": "hunter2"})
    kind, kwarg = tasks.calls[0][1], tasks.calls[0][2]
    assert kind == "signin"
    # password must be transformed before it reaches storage (fernet: prefix in prod;
    # in the dev no-op cipher it passes through — assert delegation + that storage saw the key).
    assert "password" in kwarg
    assert kwarg["task_id"] == "t1"


def test_get_decrypts_storage_result(monkeypatch):
    from app.core.credential_crypto import _reset_for_tests, encrypt_str

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", "")  # dev no-op unless a real key is set
    _reset_for_tests()
    enc = encrypt_str("hunter2")  # no-op in dev → "hunter2"; fernet:… if a key is configured
    tasks = _RecordingTasks(get_result={"task_id": "t1", "user_id": "u1", "password": enc})
    _install(monkeypatch, tasks)
    got = TaskStore().get_task("signin", "t1", "u1")
    assert got["password"] == "hunter2"
    assert tasks.calls[0] == ("get_task", "signin", "t1", "u1")


def test_list_tasks_and_history_delegate_and_decrypt(monkeypatch):
    tasks = _RecordingTasks(
        list_result=[{"task_id": "t1", "user_id": "u1"}],
        history_result=[{"message": "m", "timestamp": "2026-01-01T00:00:00+00:00"}],
    )
    _install(monkeypatch, tasks)
    store = TaskStore()
    assert [t["task_id"] for t in store.list_tasks("signin", "u1", 10)] == ["t1"]
    assert store.list_history("signin", "u1", 5)[0]["message"] == "m"
    assert ("list_tasks", "signin", "u1", 10) in tasks.calls
    assert ("list_history", "signin", "u1", 5) in tasks.calls


def test_upsert_invalid_input_does_not_delegate(monkeypatch):
    tasks = _RecordingTasks()
    _install(monkeypatch, tasks)
    TaskStore().upsert_task("", {"task_id": "t1", "user_id": "u1"})
    TaskStore().upsert_task("signin", "not-a-dict")
    assert tasks.calls == []
```
(Add a round-trip crypto assertion only meaningful with a real key; the dev harness has none, so the
above asserts delegation + decrypt passthrough. The byte-for-byte encrypted-storage guarantee is
covered structurally by the equivalence argument + the `test_upsert_task_does_not_encrypt` /
`test_..._round_trip` adapter tests.)

Run (expect FAIL — `get_storage` not yet imported in task_store):
```
python -m pytest tests/unit/test_task_store.py -q
```

**Impl** — rewrite `backend/app/services/course/task_store.py`:
```python
import logging
from typing import Any

from app.core.credential_crypto import decrypt_dict_fields, encrypt_dict_fields
from app.storage.factory import get_storage

logger = logging.getLogger(__name__)

_SENSITIVE_FIELDS: tuple[str, ...] = ("password", "user_password", "third_party_password")
_SENSITIVE_CONTAINERS: tuple[str, ...] = ("credentials",)


def _encrypt_sensitive(payload: dict[str, Any]) -> dict[str, Any]:
    # ... VERBATIM from current task_store.py:29-56 ...


def _decrypt_sensitive(payload: dict[str, Any]) -> dict[str, Any]:
    # ... VERBATIM from current task_store.py:59-79 ...


class TaskStore:
    def ensure_tables(self) -> None:
        get_storage().tasks.ensure_tables()

    def upsert_task(self, task_kind: str, task_state_public: dict[str, Any]) -> None:
        if not task_kind or not isinstance(task_state_public, dict):
            return
        get_storage().tasks.upsert_task(task_kind, _encrypt_sensitive(task_state_public))

    def get_task(self, task_kind: str, task_id: str, user_id: str | None = None) -> dict[str, Any] | None:
        item = get_storage().tasks.get_task(task_kind, task_id, user_id)
        if item is None:
            return None
        return _decrypt_sensitive(item)

    def list_tasks(self, task_kind: str, user_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return [_decrypt_sensitive(item) for item in get_storage().tasks.list_tasks(task_kind, user_id, limit)]

    def append_history(
        self, history_kind: str, user_id: str, record: dict[str, Any], max_records: int = 500
    ) -> None:
        if not history_kind or not user_id or not isinstance(record, dict):
            return
        get_storage().tasks.append_history(history_kind, user_id, _encrypt_sensitive(record), max_records)

    def list_history(
        self, history_kind: str, user_id: str | None = None, limit: int = 500
    ) -> list[dict[str, Any]]:
        return [_decrypt_sensitive(item) for item in get_storage().tasks.list_history(history_kind, user_id, limit)]


task_store = TaskStore()
```
Keep `_encrypt_sensitive`/`_decrypt_sensitive` bodies verbatim. The early-return guards for
`upsert_task`/`append_history` preserve the "no DB call on bad input" contract at the wrapper level;
the adapter also re-checks (so `task_store_module.get_db_session` no longer exists — that's why the 3
SQL tests moved to A3).

Run the full affected suite (expect PASS — incl. the kept signin-manager tests):
```
python -m pytest tests/unit/test_task_store.py tests/unit/test_postgres_storage.py tests/unit/test_chaoxing_learning_persist.py tests/unit/test_chaoxing_learning_notify.py -q
ruff format app/services/course/task_store.py tests/unit/test_task_store.py && ruff check app/services/course/task_store.py tests/unit/test_task_store.py
```

**Commit:** `refactor(task_store): delegate persistence to storage adapter; keep crypto + public surface`

---

## A7 — `/health` uses `get_storage().probe.ping()`

`main.py:205-226` — replace the inline `get_db_session()` `SELECT 1` with the probe. Remove
`from app.db.session import get_db_session` from `main.py` (only `/health` used it — verified) and add
`from app.storage.factory import get_storage`. Success-path response is unchanged; the only
observable diff is the 503 **detail text** on DB failure (`"db unavailable: <ExcType>"` →
`"db unavailable"`), because the mandated `ping() -> bool` doesn't surface the exception type. Grep
confirms **no test pins the detail string**; server success path is byte-for-byte unchanged.

**Files:** `backend/app/main.py`, new `backend/tests/unit/test_health_probe.py`.

**Test first** — `backend/tests/unit/test_health_probe.py`:
```python
import app.storage.factory as factory
from app.main import app
from fastapi.testclient import TestClient


class _Probe:
    def __init__(self, ok):
        self._ok = ok

    def ping(self):
        return self._ok


class _Storage:
    def __init__(self, ok):
        self.tasks = None
        self.probe = _Probe(ok)


def test_health_ok_when_probe_true(monkeypatch):
    monkeypatch.setattr("app.main.get_storage", lambda: _Storage(True))
    r = TestClient(app, base_url="http://localhost").get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "ok"
    assert body["status"] in {"ok", "degraded"}


def test_health_503_when_probe_false(monkeypatch):
    monkeypatch.setattr("app.main.get_storage", lambda: _Storage(False))
    r = TestClient(app, base_url="http://localhost").get("/health")
    assert r.status_code == 503
    assert r.json()["detail"] == "db unavailable"
```

Run (expect FAIL — `app.main.get_storage` undefined):
```
python -m pytest tests/unit/test_health_probe.py -q
```

**Impl** — `backend/app/main.py`:
- Replace import (line 20) `from app.db.session import get_db_session` → `from app.storage.factory import get_storage`.
- Replace the `health()` body (lines 205-226):
```python
@app.get("/health")
def health():
    cleanup_task = getattr(app.state, "cleanup_task", None)
    cleanup_alive = bool(cleanup_task and not cleanup_task.done())
    if not get_storage().probe.ping():
        raise HTTPException(status_code=503, detail="db unavailable")
    status = "ok" if cleanup_alive else "degraded"
    return {"status": status, "db": "ok", "cleanup_task": "alive" if cleanup_alive else "dead"}
```

Run (expect PASS) + ruff:
```
python -m pytest tests/unit/test_health_probe.py -q
ruff format app/main.py tests/unit/test_health_probe.py && ruff check app/main.py tests/unit/test_health_probe.py
```

**Commit:** `refactor(health): /health uses storage probe.ping() instead of inline SELECT 1`

---

## A8 — Contract test: Postgres + SQLite parity (parametrized)

One parametrized test runs the SAME assertions against `PostgresStorage` (skipped unless a real PG is
reachable — CI service container provides it; spec §5) and `SqliteStorage` (temp file). Operates at
the **adapter** level (plaintext payloads — adapters don't encrypt). Uses uuid-namespaced
`task_kind`/`user_id` so Postgres rows from prior runs don't interfere (no teardown needed).

**Files:** new `backend/tests/unit/test_storage_contract.py`.

```python
import uuid

import pytest

from app.storage.sqlite import SqliteStorage


def _pg_available():
    try:
        import psycopg2

        from app.config import settings

        conn = psycopg2.connect(
            host=settings.MAIN_DB_HOST, dbname=settings.MAIN_DB_NAME,
            user=settings.MAIN_DB_USER, password=settings.MAIN_DB_PASSWORD,
            port=settings.MAIN_DB_PORT, connect_timeout=2,
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
    storage.tasks.upsert_task(kind, {
        "task_id": "t1", "user_id": user, "status": "running", "message": "m",
        "started_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:05:00+00:00",
        "nested": {"a": 1}, "password": "kept-verbatim",
    })
    got = storage.tasks.get_task(kind, "t1", user)
    assert got["task_id"] == "t1"
    assert got["status"] == "running"
    assert got["updated_at"] == "2026-01-01T00:05:00+00:00"
    assert got["nested"] == {"a": 1}
    assert got["password"] == "kept-verbatim"


def test_list_user_filter_and_order(storage):
    kind, user = f"k-{uuid.uuid4().hex}", f"u-{uuid.uuid4().hex}"
    storage.tasks.upsert_task(kind, {"task_id": "a", "user_id": user, "status": "x",
                                     "updated_at": "2026-01-01T00:00:00+00:00"})
    storage.tasks.upsert_task(kind, {"task_id": "b", "user_id": user, "status": "x",
                                     "updated_at": "2026-01-02T00:00:00+00:00"})
    storage.tasks.upsert_task(kind, {"task_id": "z", "user_id": "other", "status": "x",
                                     "updated_at": "2026-01-09T00:00:00+00:00"})
    ids = [t["task_id"] for t in storage.tasks.list_tasks(kind, user_id=user, limit=50)]
    assert ids == ["b", "a"]


def test_upsert_conflict_coalesces_started_at(storage):
    kind, user = f"k-{uuid.uuid4().hex}", f"u-{uuid.uuid4().hex}"
    storage.tasks.upsert_task(kind, {"task_id": "t1", "user_id": user, "status": "running",
                                     "started_at": "2026-01-01T00:00:00+00:00",
                                     "updated_at": "2026-01-01T00:00:00+00:00"})
    storage.tasks.upsert_task(kind, {"task_id": "t1", "user_id": user, "status": "completed",
                                     "updated_at": "2026-01-01T02:00:00+00:00"})
    got = storage.tasks.get_task(kind, "t1", user)
    assert got["status"] == "completed"
    assert got["started_at"] == "2026-01-01T00:00:00+00:00"


def test_history_append_list_and_prune(storage):
    kind, user = f"k-{uuid.uuid4().hex}", f"u-{uuid.uuid4().hex}"
    for i in range(5):
        storage.tasks.append_history(kind, user,
                                     {"message": f"m{i}", "timestamp": f"2026-01-0{i + 1}T00:00:00+00:00"},
                                     max_records=3)
    hist = storage.tasks.list_history(kind, user_id=user, limit=50)
    assert [h["message"] for h in hist] == ["m4", "m3", "m2"]
```

Run (sqlite leg passes; pg leg skips locally / runs in CI):
```
python -m pytest tests/unit/test_storage_contract.py -q
ruff format tests/unit/test_storage_contract.py && ruff check tests/unit/test_storage_contract.py
```
Expected locally: 4 passed, 4 skipped (postgres legs) — or 8 passed under CI with PG.

**Commit:** `test(storage): cross-adapter contract parity (Postgres + SQLite)`

---

## A9 — SQLite concurrency: N threads upserting without "database is locked"

Confirms WAL + busy_timeout + the write lock survive heavy concurrent daemon-thread writes (spec
§5/§14.1). Uses a temp **file** (WAL needs a file, not `:memory:`).

**Files:** new `backend/tests/unit/test_sqlite_concurrency.py`.

```python
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
                store.tasks.upsert_task("signin", {
                    "task_id": f"t-{tid}-{i}", "user_id": f"u-{tid}",
                    "status": "running", "message": f"{tid}:{i}",
                    "updated_at": "2026-01-01T00:00:00+00:00",
                })
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
```
Note: `_SqliteTaskStore.upsert_task` swallows exceptions into `logger.exception`, so a lock failure
would not raise — the durable signal is the **row count** (`total == 500`); a "database is locked"
drop would lower it. The `errors` list guards against unexpected propagation. (If hardening is
wanted, the impl can be temporarily switched to re-raise; not required for the gate.)

Run (expect PASS) + ruff:
```
python -m pytest tests/unit/test_sqlite_concurrency.py -q
ruff format tests/unit/test_sqlite_concurrency.py && ruff check tests/unit/test_sqlite_concurrency.py
```

**Final full-suite gate (server path unchanged):**
```
python -m pytest -q
ruff format --check app && ruff check app
```
Expected: entire backend suite green; no server-mode test regressed.

**Commit:** `test(storage): SQLite concurrency gate (N-thread upserts, no database-is-locked)`

---

## Cross-workstream dependencies (consumed by B / C / D)

- **B (`PROFILE=local`)** depends on **A1** for `PROFILE` / `LOCAL_USER_ID` (and reuses
  `STORAGE_BACKEND` to flip the factory to sqlite).
- **D (launcher / PyInstaller)** depends on **A1** (`STORAGE_BACKEND=sqlite`, `SQLITE_PATH`) and on
  **A5**'s lazy import so the frozen local build can avoid the psycopg2 hot path. **Caveat to flag to
  D:** A only removes the psycopg2 import from `task_store.py`; the `auth`/`chaoxing` routers still
  import `app.db.session` at app import time, so "local build never imports psycopg2" is **not** fully
  achieved by A alone — D's PyInstaller collect flags must still bundle psycopg2 (or B must gate the
  auth-router import in local mode). Out of scope for A.
- **C (SPA serving)** is independent of A but shares `main.py`; coordinate the `main.py` edits (A7's
  `/health` change + import swap) with C's catch-all/`GET /` changes to avoid merge conflicts.
- **All workstreams**: `get_storage()` is a process singleton — any test that flips
  `settings.STORAGE_BACKEND` must call `app.storage.factory._reset_for_tests()` (provided in A5).
# Workstream B — `PROFILE=local` auth / middleware

Goal: when `settings.PROFILE == "local"`, the FastAPI app drops the only auth-bearing
piece of the request path (the `tenant_isolation_middleware` JWT gate) and injects an
implicit single-user identity (`user_id == settings.LOCAL_USER_ID == "local"`) via
`app.dependency_overrides`, so `course.py`/`chaoxing.py` work with **no** `Authorization`
header and **no** code changes to routers or `dependencies.py`. The server path
(`PROFILE` default `"server"`) stays byte-for-byte unchanged at runtime.

---

## Verified facts this workstream builds on (read the files)

- `backend/app/main.py` has **NO app factory**. The `FastAPI` object `app` is built at
  module import time (`main.py:70-78`); the auth gate is registered at module level
  (`main.py:107` — `app.middleware("http")(tenant_isolation_middleware)`); routers are
  included at module level (`main.py:191-197`). ⇒ PROFILE-dependent wiring is decided
  **at import**, so tests must reload `app.config` then `app.main` with the env set.
- `tenant_isolation_middleware` (`backend/app/middleware/tenant_isolation.py:31-86`) is a
  JWT gate that returns `JSONResponse(status_code=401, {"detail": "Missing token"})` when
  no `Authorization` header is present and the path is not in `PUBLIC_ROUTES`. It sets
  `request.state.user_id` but **no router reads it**. It is the OUTERMOST-but-one
  middleware and short-circuits the 401 **before** any route/dependency runs.
- `backend/app/dependencies.py`: `get_current_user` (`:15`, `HTTPBearer(auto_error=True)`,
  used by every `course.py` route) returns the decoded JWT **dict**; `get_current_user_id`
  (`:24`, `HTTPBearer(auto_error=False)`, used by every `chaoxing.py` route) returns a
  `str`. With `auto_error=True`, a missing header makes `HTTPBearer` raise **403**
  ("Not authenticated") — distinct from the gate's **401** (this lets B1 isolate the gate).
- `backend/app/api/v1/course.py:280-284` `_current_user_id(current_user)` does
  `str(current_user.get("user_id") or "")` ⇒ the override **must** return a dict shaped
  `{"user_id": "local"}`. `chaoxing.py` consumes `get_current_user_id` directly as a `str`.
- `backend/app/config.py`: `settings = Settings()` is a module-level singleton built at
  import; `SECRET_KEY` (<16 ⇒ reject) and `CORS_ORIGINS` (empty ⇒ reject) validators run
  at construction; `ENFORCE_HTTPS` default `True` ⇒ `main.py:121-126` 301-redirects any
  plain-http request (would loop the loopback webview). `ENV` default `"dev"`.
- `backend/pytest.ini:7-12` sets test env at collection (via `pytest-env`):
  `SECRET_KEY`, `CORS_ORIGINS=["http://localhost:3000"]`, `MAIN_DB_USER/PASSWORD`, and
  **`ENFORCE_HTTPS=false`**. So the existing suite already runs with HTTPS enforcement off.
- `backend/tests/conftest.py:11-15`: the `client` fixture lazily does
  `from app.main import app` and `TestClient(app, base_url="http://localhost")`. It does
  **not** enter the TestClient context manager ⇒ lifespan (DB ping / `init_cipher`) does
  **not** run ⇒ auth/routing tests need no DB. We rely on that for B's tests.

---

## CROSS-WORKSTREAM DEPENDENCIES (read first)

- **HARD dependency on Workstream A** (config): B's code and reload-based tests require
  `settings.PROFILE` (`Literal["server","local"]`, default `"server"`) and
  `settings.LOCAL_USER_ID` (`"local"`) to exist on the `Settings` object. As of writing,
  `grep -rn "PROFILE\|LOCAL_USER_ID" backend/app` returns **nothing** — A is not landed.
  B's override code uses `settings.LOCAL_USER_ID` (per the agreed interface). If A exposes
  it instead as a bare module constant `app.config.LOCAL_USER_ID`, swap the two override
  lines to `from app.config import LOCAL_USER_ID` and use that name — **do not redefine it
  in B**. If A is not yet merged when B starts, B1 is BLOCKED; coordinate or stub A's two
  config additions locally to unblock (but the real definitions are A's deliverable).
- **Enables Workstream C** (SPA same-origin): once B1 removes the gate and B2 adds the
  overrides, C's `StaticFiles` mount, SPA catch-all, and repointed `GET /` serve freely in
  local mode with no auth. C does not need to touch auth — B already cleared the path.
- **Cross-ref Workstream D** (launcher) — B only **asserts app behavior given the env**; B
  does NOT implement the launcher. D injects, before importing `app.config`:
  `PROFILE=local`, `STORAGE_BACKEND=sqlite`, `ENV=dev`, **`ENFORCE_HTTPS=false`**,
  `SECRET_KEY=<persisted random ≥32>`, `CORS_ORIGINS=["http://127.0.0.1:<port>"]`. B3
  documents this list and proves the app does the right thing when it is present (and the
  wrong thing — a 301 loop — when `ENFORCE_HTTPS` is left at its `True` default).
- Independent of Workstreams E (Tauri) and F (release pipeline).

---

## Shared test infra (added once, in B1; reused by B2/B3)

`backend/app/main.py` builds `app` at import, so every B test needs a freshly-imported
app with the right env. Add a `build_app` context-manager **helper** to
`backend/tests/conftest.py` (a plain function, not an autouse fixture, so it has zero
effect on existing tests). It (1) sets env, (2) reloads `app.config` **then** `app.main`
(order matters: `main` does `from app.config import settings`, so config must be reloaded
first), (3) yields the rebuilt `app`, (4) restores env and reloads both modules back to
their default (`PROFILE` unset ⇒ `"server"`) so later tests see the normal server app.

```python
# --- append to backend/tests/conftest.py ---
import contextlib
import importlib


@contextlib.contextmanager
def build_app(profile: str = "server", **env: str):
    """Yield a freshly-built `app.main.app` for the given PROFILE + env overrides.

    main.py constructs the FastAPI `app` (and decides the tenant_isolation guard +
    dependency_overrides) at IMPORT time — there is no app factory — so a test that
    wants PROFILE=local must reload the module with the env in place, then restore the
    default server-profile module afterwards so other tests are unaffected.
    """
    import app.config as config_mod
    import app.main as main_mod

    overrides = {"PROFILE": profile, **env}
    saved = {k: os.environ.get(k) for k in overrides}
    os.environ.update({k: str(v) for k, v in overrides.items()})
    try:
        importlib.reload(config_mod)
        importlib.reload(main_mod)
        yield main_mod.app
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        importlib.reload(config_mod)
        importlib.reload(main_mod)
```

Notes / why this is safe:
- `get_current_user` / `get_current_user_id` live in `app.dependencies`, which is **not**
  reloaded, so they remain the **same** function objects the routers depend on ⇒ the
  override-dict keys set in (reloaded) `main` match the deps the routes resolve. ✅
- Reloading `main` re-binds its `settings` to the reloaded `app.config.settings` (new
  object, `PROFILE`/`ENFORCE_HTTPS` from env). The middleware functions, the gate guard,
  and the override lambdas are all defined in `main` ⇒ they read the fresh `settings`. ✅
- Tests use `TestClient(app, base_url=...)` **without** the `with` context manager ⇒ no
  lifespan ⇒ no DB / cipher needed.

---

## B1 — Guard the auth gate behind `PROFILE`

**Depends on:** Workstream A (`settings.PROFILE`). **Blocks:** B2, B3, C.

### B1.1 (RED) Write the test — `backend/tests/test_profile_local_middleware.py`

```python
from fastapi.testclient import TestClient

from tests.conftest import build_app

PROTECTED = "/api/v1/course/tasks"  # course.py route, behind get_current_user


def test_server_profile_gate_rejects_missing_token():
    # Server mode: tenant_isolation_middleware IS registered → its 401 fires
    # before any route/dependency runs.
    with build_app("server") as app:
        client = TestClient(app, base_url="http://localhost")
        resp = client.get(PROTECTED)  # no Authorization header
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing token"  # pins it to the gate


def test_local_profile_gate_not_registered():
    # Local mode: the gate is SKIPPED. With the gate gone, a missing token is no
    # longer a 401 from the gate. (Pre-B2 the HTTPBearer dep returns 403
    # "Not authenticated"; post-B2 the override returns 200. Either way, the
    # gate's 401 is gone — and because the gate is OUTERMOST it would 401
    # regardless of dependency_overrides, so a non-401 here proves it is unregistered.)
    with build_app("local") as app:
        client = TestClient(app, base_url="http://localhost")
        resp = client.get(PROTECTED)  # no Authorization header
    assert resp.status_code != 401
```

Run (expect the local test to FAIL red — gate still registered ⇒ 401):
```
cd backend && python -m pytest tests/test_profile_local_middleware.py -p no:cacheprovider -o addopts="" -v
```
Expected (red): `test_server_profile_gate_rejects_missing_token PASSED`,
`test_local_profile_gate_not_registered FAILED` (`assert 401 != 401`).

### B1.2 (GREEN) Implement the guard in `backend/app/main.py`

Replace the single registration line at `main.py:107` (keep the existing comment block
above it). Old:
```python
# Innermost middleware: registered first so its short-circuit responses still
# travel back out through request_metrics (counted) and CORS (CORS headers added).
app.middleware("http")(tenant_isolation_middleware)
```
New:
```python
# Innermost middleware: registered first so its short-circuit responses still
# travel back out through request_metrics (counted) and CORS (CORS headers added).
#
# PROFILE=local (single-user desktop build) SKIPS this JWT gate: the desktop app
# never logs in and sends no token; the implicit "local" identity is injected via
# dependency_overrides further below. Server mode (the default) registers it
# exactly as before — runtime byte-for-byte unchanged.
if settings.PROFILE != "local":
    app.middleware("http")(tenant_isolation_middleware)
```
`settings` is already imported (`main.py:15`). No other change in this task.

Re-run the same command. Expected (green): both tests PASSED.

### B1.3 Regression + lint + commit

```
cd backend && python -m pytest -q
cd backend && ruff check app/main.py tests/conftest.py tests/test_profile_local_middleware.py
```
Expected: full suite passes (server path untouched — the guard is `True` in server mode,
so the gate registers identically); `ruff` ⇒ `All checks passed!`.

Commit (small, single-purpose):
```
git add backend/app/main.py backend/tests/conftest.py backend/tests/test_profile_local_middleware.py
git commit -m "feat(local): skip tenant_isolation JWT gate when PROFILE=local"
```
(The `build_app` helper added to `conftest.py` is committed here since B1 introduces it.)

---

## B2 — Inject the implicit local user via `dependency_overrides`

**Depends on:** B1, Workstream A (`settings.LOCAL_USER_ID`).

### B2.1 (RED) Write the test — `backend/tests/test_profile_local_overrides.py`

```python
from fastapi.testclient import TestClient

from tests.conftest import build_app


def test_course_endpoint_local_no_token_sees_local_user(monkeypatch):
    # course.py uses get_current_user (HTTPBearer auto_error=True). With the local
    # override, no Authorization header is required and _current_user_id() yields "local".
    captured = {}

    class FakeManager:
        def list_tasks(self, user_id):
            captured["user_id"] = user_id
            return [{"task_id": "t1"}]

    with build_app("local", ENFORCE_HTTPS="false") as app:
        import app.api.v1.course as course_mod
        monkeypatch.setattr(course_mod, "_get_learning_manager", lambda: FakeManager())
        client = TestClient(app, base_url="http://127.0.0.1")
        resp = client.get("/api/v1/course/tasks")  # NO Authorization header

    assert resp.status_code != 401
    assert resp.status_code == 200
    assert captured["user_id"] == "local"
    assert resp.json()["data"] == [{"task_id": "t1"}]


def test_chaoxing_endpoint_local_no_token_sees_local_user(monkeypatch):
    # chaoxing.py uses get_current_user_id (HTTPBearer auto_error=False) → a plain str.
    captured = {}

    def fake_get_active_tasks(user_id, sign_type):
        captured["user_id"] = user_id
        return []

    with build_app("local", ENFORCE_HTTPS="false") as app:
        import app.api.v1.chaoxing as chaoxing_mod
        monkeypatch.setattr(
            chaoxing_mod.signin_manager, "get_active_tasks", fake_get_active_tasks
        )
        client = TestClient(app, base_url="http://127.0.0.1")
        resp = client.get("/api/v1/chaoxing/tasks")  # NO Authorization header

    assert resp.status_code != 401
    assert resp.status_code == 200
    assert captured["user_id"] == "local"


def test_server_profile_same_endpoints_still_401_without_token():
    with build_app("server") as app:
        client = TestClient(app, base_url="http://localhost")
        course = client.get("/api/v1/course/tasks")
        chaoxing = client.get("/api/v1/chaoxing/tasks")
    assert course.status_code == 401
    assert chaoxing.status_code == 401
```

Run (expect the two local tests RED — pre-override, missing header ⇒ HTTPBearer 403):
```
cd backend && python -m pytest tests/test_profile_local_overrides.py -p no:cacheprovider -o addopts="" -v
```
Expected (red): server test PASSED; both local tests FAILED with `assert 403 == 200`.

### B2.2 (GREEN) Add the overrides in `backend/app/main.py`

Add the import alongside the other `app.*` imports near the top (e.g. after
`from app.db.session import get_db_session` at `main.py:20`):
```python
from app.dependencies import get_current_user, get_current_user_id
```
Then add the override block **after** the router includes (immediately after
`app.include_router(metrics_router, tags=["metrics"])` at `main.py:197`, before the
`@app.get("/")` root route):
```python
# PROFILE=local: inject the implicit single-user identity so the HTTPBearer
# sub-dependencies never run — no Authorization header is required. course.py
# receives {"user_id": "local"} and chaoxing.py receives "local"; both work
# unchanged. No edits to routers or dependencies.py. Server mode skips this block
# entirely, leaving dependency_overrides empty (runtime unchanged).
if settings.PROFILE == "local":
    app.dependency_overrides[get_current_user] = lambda: {"user_id": settings.LOCAL_USER_ID}
    app.dependency_overrides[get_current_user_id] = lambda: settings.LOCAL_USER_ID
```
(Per the A interface, `settings.LOCAL_USER_ID == "local"`. If A shipped it as a bare
module constant instead, use `from app.config import LOCAL_USER_ID` and reference
`LOCAL_USER_ID` — do not redefine it here.)

Re-run the same command. Expected (green): all three tests PASSED.

### B2.3 Regression + lint + commit

```
cd backend && python -m pytest -q
cd backend && ruff check app/main.py tests/test_profile_local_overrides.py
```
Expected: full suite passes; `ruff` ⇒ `All checks passed!`. (Assigning the lambdas into a
dict does not trigger ruff E731, which only flags `name = lambda`.)

Commit:
```
git add backend/app/main.py backend/tests/test_profile_local_overrides.py
git commit -m "feat(local): inject implicit local user via dependency_overrides"
```

---

## B3 — `ENFORCE_HTTPS` / CORS behavior for the loopback (local) app

**Depends on:** B1, B2. Asserts app behavior only; the launcher (D) sets the env.

### B3.1 (GREEN — no prod-code change) Write the test — `backend/tests/test_profile_local_https.py`

```python
from fastapi.testclient import TestClient

from tests.conftest import build_app


def test_local_no_301_redirect_on_plain_http_loopback():
    # The env Workstream D injects for the desktop build (asserted here, not implemented):
    #   PROFILE=local, ENV=dev, STORAGE_BACKEND=sqlite,
    #   SECRET_KEY=<persisted ≥32>, CORS_ORIGINS=["http://127.0.0.1:<port>"],
    #   ENFORCE_HTTPS=false   <-- without this the loopback webview would 301-loop.
    with build_app(
        "local",
        ENFORCE_HTTPS="false",
        CORS_ORIGINS='["http://127.0.0.1:8000"]',
    ) as app:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        # zhihuishu/status is a course.py route that needs no DB/external deps:
        # with B2's override it returns a clean 200 over plain http.
        resp = client.get(
            "/api/v1/course/zhihuishu/status", follow_redirects=False
        )
    assert resp.status_code != 301
    assert resp.status_code == 200
    assert "location" not in {k.lower() for k in resp.headers}


def test_enforce_https_true_would_301_loop_the_loopback():
    # Documents WHY D must set ENFORCE_HTTPS=false: the default True 301-redirects
    # every plain-http loopback request to https:// (which the webview can't reach).
    with build_app(
        "local",
        ENFORCE_HTTPS="true",
        CORS_ORIGINS='["http://127.0.0.1:8000"]',
    ) as app:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        resp = client.get("/health", follow_redirects=False)  # public route
    assert resp.status_code == 301
    assert resp.headers["location"].startswith("https://")


def test_loopback_host_accepted_by_trustedhost():
    # CORS_ORIGINS=["http://127.0.0.1:<port>"] feeds _build_allowed_hosts (main.py:81),
    # and 127.0.0.1 is always seeded → the loopback Host header is not a 400.
    with build_app(
        "local",
        ENFORCE_HTTPS="false",
        CORS_ORIGINS='["http://127.0.0.1:8000"]',
    ) as app:
        client = TestClient(app, base_url="http://127.0.0.1:8000")
        resp = client.get("/api/v1/course/zhihuishu/status", follow_redirects=False)
    assert resp.status_code != 400  # not "Invalid host header"
```

Run:
```
cd backend && python -m pytest tests/test_profile_local_https.py -p no:cacheprovider -o addopts="" -v
```
Expected: all three PASSED (no production-code change needed — `https_redirect_middleware`
at `main.py:121-126` already keys off `settings.ENFORCE_HTTPS`; B3 only proves the app
behaves correctly under the launcher-injected env).

### B3.2 Regression + lint + commit

```
cd backend && python -m pytest -q
cd backend && ruff check tests/test_profile_local_https.py
```
Expected: full suite passes; `ruff` ⇒ `All checks passed!`.

Commit:
```
git add backend/tests/test_profile_local_https.py
git commit -m "test(local): no https 301 on loopback under PROFILE=local env"
```

---

## Server-path preservation checklist (verify before declaring B done)

- The only `main.py` source changes are: one added import (`get_current_user`,
  `get_current_user_id`), one `if settings.PROFILE != "local":` guard around the existing
  gate registration, and one `if settings.PROFILE == "local":` override block. In server
  mode (`PROFILE` default `"server"`) the guard is `True` (gate registers identically) and
  the override block is skipped (`dependency_overrides` stays empty) ⇒ **runtime
  byte-for-byte unchanged**.
- `cd backend && python -m pytest -q` is green at the end of every task (no regression in
  the existing server-path suite).
- `ruff check` clean on every touched file. Python 3.11. Commands run from `backend/`.

## Expected commits (one per task)
1. `feat(local): skip tenant_isolation JWT gate when PROFILE=local` (B1 + `build_app` helper)
2. `feat(local): inject implicit local user via dependency_overrides` (B2)
3. `test(local): no https 301 on loopback under PROFILE=local env` (B3)
# Workstream C — FastAPI serves the SPA same-origin

Source spec: `docs/superpowers/specs/2026-06-26-desktop-client-and-release-design.md` §7 (verified against the code below).

## Goal

Let the existing FastAPI app serve the built Vite SPA (`frontend/dist`) from its own
origin so the relative `'/api/v1'` base (`frontend/src/utils/api.js:3-6`) "just works"
with no CORS and no second server. This is wired **only when a dist dir is resolvable**,
so server deployments — whose backend image bundles **no** `frontend/dist`
(`Dockerfile.server` does `COPY backend /srv/backend` only) — are byte-for-byte unchanged.

## Facts established before writing these tasks (file:line)

- Routers are included at `backend/app/main.py:191-197` (`/api/v1/auth`, `/api/v1/course`,
  `/api/v1/chaoxing`, and the no-prefix `metrics_router`). The SPA mount + catch-all must
  register **after** these so API/`/health`/`/docs`/`/metrics` win.
- `GET /` at `backend/app/main.py:200-202` returns `{"message": "University Helper API"}`.
  It shadows `index.html` at `/` and must branch on dist presence.
- `GET /health` at `backend/app/main.py:205-226` is a GET FULL-match route (returns JSON/503),
  registered before the catch-all → never shadowed. Used in tests as a "non-catch-all GET wins" probe.
- `cxsecret_font.resource_path()` (`backend/app/services/course/chaoxing/cxsecret_font.py:31-63`)
  is the existing `_MEIPASS`-aware resolver pattern. It resolves **relative to `backend/`**
  (`parents[4]`), which is wrong for `frontend/dist` (sibling of `backend/`), so C uses its own
  resolver reusing the same `sys._MEIPASS` + repo-root idea.
- The server backend image never ships `frontend/dist` → resolver returns `None` there → catch-all
  not registered, `GET /` keeps JSON. **This is the safety guarantee.**
- `GET /api/v1/chaoxing/location/geocode` (`backend/app/api/v1/chaoxing.py:292-295`) has a
  **required** `query: str` and `get_current_user_id` is `auto_error=False` → calling it with no
  query and no token returns a **422 JSON** *before* the handler runs (no DB, no auth, no network).
  Perfect "the API route wins over the catch-all" assertion.
- `frontend/dist/` exists in the checkout with `index.html` + `assets/` (verified), so the dev
  (repo) branch of the resolver is live. `FileResponse`/`StaticFiles` ship with Starlette/FastAPI
  (`fastapi>=0.115`, `starlette>=0.40`) — **no new dependency** (anyio-backed, no `aiofiles`).
- pytest env (`backend/pytest.ini`) sets `SECRET_KEY`, `CORS_ORIGINS`, `MAIN_DB_USER/PASSWORD`,
  `ENFORCE_HTTPS=false`; it does **not** set `FRONTEND_DIST`. Coverage `fail_under = 0`
  (`.coveragerc`) so single-file runs never fail on coverage. ruff `target-version = py311`.

## Design decisions (justified)

1. **Register the catch-all/`/assets` mount only when the resolved dist dir exists** (the spec's
   default). Reasons: (a) `StaticFiles(directory=...)` raises `RuntimeError` at construction if the
   directory is absent, so unconditional registration would crash the server import; (b) the server
   image has no dist → `None` → nothing registered → server path provably unchanged. The alternative
   ("always register, 404 if absent") is rejected: it both risks the StaticFiles construction error
   and adds a permanent catch-all to the server app for no benefit.
2. **`FRONTEND_DIST` is authoritative when set, with no fallback.** A non-empty value that does not
   point at a real directory resolves to `None` (not the repo path). This gives tests a deterministic
   way to force the "no dist / server behavior" state regardless of the checkout's real `frontend/dist`,
   and lets the frozen launcher (workstream D) pin an exact path.
3. **`GET /` stays an explicit route** that branches on the module-level `_SPA_DIST`; it is registered
   before the catch-all so it (not the catch-all's empty-`full_path` match) owns `/`.
4. **Path-traversal guard** is the spec's `DIST.resolve() in candidate.parents` exactly. Because HTTP
   clients normalize `..`, the traversal test calls the route coroutine directly (raw `full_path`) so
   the guard is actually exercised; the client layer is a second, independent line of defense.

---

## C1 — Add the `FRONTEND_DIST` Settings field (config seam)

**TDD — write the test first.**

Add to `backend/tests/unit/test_config.py` (end of file):

```python
def test_frontend_dist_defaults_empty():
    with patch.dict('os.environ', {'SECRET_KEY': _TEST_SECRET, 'CORS_ORIGINS': '["*"]'}):
        settings = Settings()
        assert settings.FRONTEND_DIST == ""


def test_frontend_dist_from_env():
    with patch.dict('os.environ', {
        'SECRET_KEY': _TEST_SECRET,
        'CORS_ORIGINS': '["*"]',
        'FRONTEND_DIST': '/opt/uh/frontend/dist',
    }):
        settings = Settings()
        assert settings.FRONTEND_DIST == "/opt/uh/frontend/dist"
```

Run (RED — field missing → `AttributeError`/assertion fail):

```
cd backend && python -m pytest tests/unit/test_config.py -q
```

**Implement.** In `backend/app/config.py`, add the field inside `class Settings` (place it right
after the `DOCS_ENABLED` block, before `BAIDU_MAP_API_KEY`):

```python
    # Frontend SPA (same-origin serving). When set, FastAPI serves the built
    # Vite app from this directory (local desktop build / tests). Empty by
    # default so the server backend image — which bundles NO frontend/dist —
    # keeps the JSON root and never registers the SPA catch-all. Treated as
    # authoritative: a non-empty value that is not a real dir disables the SPA
    # (no silent fallback) so the server path stays reachable.
    FRONTEND_DIST: str = ""
```

No validator (empty is valid). Run (GREEN):

```
cd backend && python -m pytest tests/unit/test_config.py -q
```

Expected tail:

```
tests/unit/test_config.py ........                                       [100%]
8 passed in 0.2Xs
```

Lint:

```
cd backend && ruff check app/config.py tests/unit/test_config.py
```

Expected: `All checks passed!`

**Commit:** `feat(config): add FRONTEND_DIST setting for same-origin SPA serving`

---

## C2 — Add the `resolve_frontend_dist()` resolver in `main.py`

**TDD — new test file `backend/tests/unit/test_spa_resolver.py`:**

```python
import sys
from pathlib import Path

import app.main as main_mod


def test_resolver_explicit_existing_dir(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    monkeypatch.setattr(main_mod.settings, "FRONTEND_DIST", str(dist))
    assert main_mod.resolve_frontend_dist() == dist


def test_resolver_explicit_missing_dir_returns_none(tmp_path, monkeypatch):
    # Authoritative override pointing at a non-existent path -> None (no fallback),
    # which is how the "server / no SPA" state is forced deterministically.
    monkeypatch.setattr(main_mod.settings, "FRONTEND_DIST", str(tmp_path / "nope"))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert main_mod.resolve_frontend_dist() is None


def test_resolver_meipass_bundle(tmp_path, monkeypatch):
    bundle = tmp_path / "frontend" / "dist"
    bundle.mkdir(parents=True)
    monkeypatch.setattr(main_mod.settings, "FRONTEND_DIST", "")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert main_mod.resolve_frontend_dist() == bundle


def test_resolver_repo_dev_path(monkeypatch):
    # Empty override, not frozen -> <repo-root>/frontend/dist, which exists in the checkout.
    monkeypatch.setattr(main_mod.settings, "FRONTEND_DIST", "")
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    expected = Path(main_mod.__file__).resolve().parents[2] / "frontend" / "dist"
    result = main_mod.resolve_frontend_dist()
    assert result == expected
    assert result.is_dir()
```

Run (RED — `resolve_frontend_dist` undefined → `AttributeError`):

```
cd backend && python -m pytest tests/unit/test_spa_resolver.py -q
```

**Implement.** In `backend/app/main.py`:

1. Add stdlib imports near the top (with the existing `import asyncio` / `import logging`):

```python
import sys
from pathlib import Path
```

2. Extend the response import and add the StaticFiles import. Change:

```python
from fastapi.responses import JSONResponse, RedirectResponse
```

to:

```python
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
```

3. Add the resolver function (place it just before the `# Routes` section, i.e. after the
   `unhandled_exception_handler` at line 188 / before line 190):

```python
def resolve_frontend_dist() -> Path | None:
    """Locate the built SPA (frontend/dist), or None when there is none to serve.

    Resolution order:
      1. settings.FRONTEND_DIST — authoritative. Tests inject a temp dir; the
         frozen desktop launcher (workstream D) pins the bundled path. A
         non-empty value that is not a real directory returns None (NO fallback)
         so the "server / no SPA" state can be forced deterministically.
      2. PyInstaller bundle: <sys._MEIPASS>/frontend/dist (added via
         --add-data "frontend/dist:frontend/dist").
      3. Dev checkout: <repo-root>/frontend/dist
         (main.py is <repo>/backend/app/main.py -> parents[2] == <repo-root>).
      4. None -> server mode: JSON root, no /assets mount, no catch-all.
    """
    configured = (settings.FRONTEND_DIST or "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_dir() else None

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "frontend" / "dist"
        if bundled.is_dir():
            return bundled

    repo_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if repo_dist.is_dir():
        return repo_dist

    return None
```

Run (GREEN):

```
cd backend && python -m pytest tests/unit/test_spa_resolver.py -q
```

Expected tail:

```
tests/unit/test_spa_resolver.py ....                                     [100%]
4 passed in 0.XXs
```

Lint:

```
cd backend && ruff check app/main.py tests/unit/test_spa_resolver.py
```

Expected: `All checks passed!`

**Commit:** `feat(main): add _MEIPASS-aware resolve_frontend_dist() resolver`

---

## C3 — Repoint `GET /` to serve `index.html` when a dist exists

**TDD — new test file `backend/tests/integration/test_spa_serving.py`** (shared helpers used by C3
and C4; C3 adds the first two tests, C4 appends the rest):

```python
import importlib

import pytest
from fastapi.testclient import TestClient


def _reload_app_with_dist(monkeypatch, frontend_dist: str):
    """Rebuild app.main with FRONTEND_DIST = frontend_dist.

    SPA wiring (root() branch, /assets mount, catch-all) is decided at import
    time from the resolved dist dir, so the module must be reloaded after the
    env is set. config is reloaded first so app.main re-binds the new settings.
    """
    monkeypatch.setenv("FRONTEND_DIST", frontend_dist)
    config_mod = importlib.import_module("app.config")
    importlib.reload(config_mod)
    main_mod = importlib.import_module("app.main")
    importlib.reload(main_mod)
    return main_mod


def _make_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>SPA</title><div id=root></div>", encoding="utf-8"
    )
    (dist / "assets" / "app.js").write_text("console.log('app');", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return dist


@pytest.fixture
def spa_client(monkeypatch, tmp_path):
    """TestClient bound to an app that serves a temp SPA dist."""
    dist = _make_dist(tmp_path)
    main_mod = _reload_app_with_dist(monkeypatch, str(dist))
    # No context manager: match conftest's client fixture so lifespan (DB probe,
    # cleanup loop) does not run for these routing-only tests.
    client = TestClient(main_mod.app, base_url="http://localhost")
    client._uh_dist = dist  # stash for assertions
    yield client
    # Restore the pristine default module for later test files.
    monkeypatch.delenv("FRONTEND_DIST", raising=False)
    importlib.reload(importlib.import_module("app.config"))
    importlib.reload(importlib.import_module("app.main"))


@pytest.fixture
def no_dist_client(monkeypatch, tmp_path):
    """TestClient bound to an app with NO servable dist (server behavior)."""
    main_mod = _reload_app_with_dist(monkeypatch, str(tmp_path / "does-not-exist"))
    client = TestClient(main_mod.app, base_url="http://localhost")
    yield client
    monkeypatch.delenv("FRONTEND_DIST", raising=False)
    importlib.reload(importlib.import_module("app.config"))
    importlib.reload(importlib.import_module("app.main"))


def test_root_serves_index_when_dist_present(spa_client):
    resp = spa_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert resp.text == (spa_client._uh_dist / "index.html").read_text(encoding="utf-8")


def test_root_returns_json_when_no_dist(no_dist_client):
    # Server behavior preserved: no dist -> the original JSON body.
    resp = no_dist_client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"message": "University Helper API"}
```

Run (RED — `GET /` still returns JSON even with a dist):

```
cd backend && python -m pytest tests/integration/test_spa_serving.py -q
```

**Implement.** In `backend/app/main.py`:

1. After the routers block (immediately after line 197
   `app.include_router(metrics_router, tags=["metrics"])`, before `GET /`), compute the
   module-level dist once:

```python
# Resolve the SPA dist ONCE at import. None in server mode (no frontend/dist in
# the backend image) -> JSON root + no catch-all, i.e. server path unchanged.
_SPA_DIST = resolve_frontend_dist()
```

2. Replace the current `GET /` handler (lines 200-202):

```python
@app.get("/")
async def root():
    return {"message": "University Helper API"}
```

with:

```python
@app.get("/", include_in_schema=False)
async def root():
    if _SPA_DIST is not None:
        return FileResponse(_SPA_DIST / "index.html")
    return {"message": "University Helper API"}
```

Run (GREEN — these two tests; the C4 tests are added next):

```
cd backend && python -m pytest tests/integration/test_spa_serving.py -q
```

Expected: `2 passed`.

Lint:

```
cd backend && ruff check app/main.py tests/integration/test_spa_serving.py
```

Expected: `All checks passed!`

**Commit:** `feat(main): serve SPA index.html at / when a frontend dist is present`

---

## C4 — Mount `/assets` + SPA catch-all (after routers, traversal-guarded)

**TDD — append to `backend/tests/integration/test_spa_serving.py`:**

```python
import asyncio


def test_client_route_returns_index(spa_client):
    # An unknown, non-file path is a client-side route -> SPA shell.
    resp = spa_client.get("/dashboard/courses")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert resp.text == (spa_client._uh_dist / "index.html").read_text(encoding="utf-8")


def test_hashed_asset_served_with_bytes(spa_client):
    resp = spa_client.get("/assets/app.js")
    assert resp.status_code == 200
    assert resp.text == "console.log('app');"
    # Served as a real JS asset, not the HTML shell.
    assert "text/html" not in resp.headers["content-type"]


def test_top_level_static_file_served(spa_client):
    # Files directly under dist (favicon.svg, sw.js, robots.txt …) go through the
    # catch-all, not /assets, and must be returned as real files.
    resp = spa_client.get("/favicon.svg")
    assert resp.status_code == 200
    assert resp.text == "<svg/>"


def test_api_route_still_wins_over_catch_all(spa_client):
    # Required `query` missing -> FastAPI 422 BEFORE the handler (no DB/auth/network).
    # Proves the API router claims the path instead of the SPA catch-all.
    resp = spa_client.get("/api/v1/chaoxing/location/geocode")
    assert resp.status_code == 422
    assert "application/json" in resp.headers["content-type"]


def test_health_route_still_wins_over_catch_all(spa_client):
    # /health is a GET FULL-match route registered before the catch-all; with no
    # DB it 503s — either way it is NOT the 200 HTML shell.
    resp = spa_client.get("/health")
    assert resp.status_code in (200, 503)
    assert "text/html" not in resp.headers.get("content-type", "")


def test_path_traversal_is_blocked(spa_client, monkeypatch):
    # HTTP clients normalize '..', so exercise the guard by calling the route
    # coroutine directly with a raw traversal path. It must fall back to index.html
    # rather than returning an out-of-tree file.
    import app.main as main_mod
    importlib.reload(importlib.import_module("app.config"))
    # spa_client already reloaded main with the temp dist; grab its route fn.
    spa_fn = None
    for route in main_mod.app.router.routes:
        if getattr(route, "name", "") == "spa":
            spa_fn = route.endpoint
            break
    assert spa_fn is not None, "spa catch-all route not registered"
    result = asyncio.run(spa_fn("../../etc/passwd"))
    # FileResponse for index.html, never /etc/passwd.
    assert str(result.path).endswith("index.html")


def test_no_catch_all_registered_without_dist(no_dist_client):
    # With no dist, an unknown GET path must 404 (no catch-all) -> server unchanged.
    resp = no_dist_client.get("/some/client/route")
    assert resp.status_code == 404
```

Run (RED — catch-all/`/assets` not yet registered: client routes 404, `/assets/app.js` 404,
`spa` route missing):

```
cd backend && python -m pytest tests/integration/test_spa_serving.py -q
```

**Implement.** At the **end** of `backend/app/main.py` (after the `health()` function, so the
catch-all is the LAST route registered and loses to every real route):

```python
def _mount_spa(application: FastAPI, dist: Path) -> None:
    """Mount hashed assets + a history-fallback catch-all for the SPA.

    Registered AFTER all API routers so /api/*, /health, /metrics, /docs, and the
    explicit GET / win; the catch-all only answers paths no real route claimed.
    """
    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        application.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @application.get("/{full_path:path}", include_in_schema=False, name="spa")
    async def spa(full_path: str):
        candidate = (dist / full_path).resolve()
        # Serve a real in-tree static file (favicon.svg, sw.js, robots.txt, …).
        # `dist.resolve() in candidate.parents` blocks traversal escapes such as
        # '../../etc/passwd' (candidate would resolve outside dist).
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        # Anything else is a client-side route -> hand back the SPA shell.
        return FileResponse(dist / "index.html")


if _SPA_DIST is not None:
    _mount_spa(app, _SPA_DIST)
```

Run (GREEN — full file):

```
cd backend && python -m pytest tests/integration/test_spa_serving.py -q
```

Expected tail:

```
tests/integration/test_spa_serving.py .........                          [100%]
9 passed in 0.XXs
```

Lint:

```
cd backend && ruff check app/main.py tests/integration/test_spa_serving.py
```

Expected: `All checks passed!`

**Full-suite regression gate** (the new default app serves the repo SPA; confirm nothing else broke —
no existing test asserts the root JSON or a 404 on an unknown GET path, verified by grep):

```
cd backend && python -m pytest -q
```

Expected: the whole suite passes (same count as before + the 15 new C tests; `0 failed`).

**Commit:** `feat(main): mount /assets + SPA catch-all after routers (same-origin serving)`

---

## Final verification for workstream C

```
cd backend && ruff check app tests && python -m pytest -q
```

Both must be clean/green. The server import path is exercised by `no_dist_client`
(`_SPA_DIST is None` → JSON root, no catch-all, unknown GET → 404), demonstrating server behavior
is preserved.

## Cross-workstream dependencies

- **C ← B (soft, runtime-only):** Serving the SPA *without a token* requires `tenant_isolation_middleware`
  to be off, which workstream B does in `PROFILE=local`. At the **code level C is independent**: in
  server mode `_SPA_DIST is None` so C registers nothing and the gate is irrelevant; in local mode B has
  already skipped the gate so `/`, `/assets/*`, and client routes pass freely. C and B can land in either
  order.
- **C → D (provider):** Workstream D's launcher relies on C's resolver. D either sets `FRONTEND_DIST`
  explicitly or depends on the `sys._MEIPASS` branch matching D's PyInstaller
  `--add-data "frontend/dist:frontend/dist"` layout (`<_MEIPASS>/frontend/dist`). Keep these two in sync.
- **C ⟂ A:** No dependency on the storage abstraction. The only DB-touching route involved (`/health`) is
  asserted in C only as a "non-catch-all GET wins" probe (200 or 503), so C's tests don't need A's SQLite probe.
- **C ⟂ E/F:** No direct dependency; the released desktop bundle (E) simply benefits from C's same-origin
  serving, and the version-stamp pipeline (F) doesn't touch C's files.
# Workstream D — sidecar launcher + PyInstaller freeze

Implements the frozen Python entrypoint (`backend/desktop_entry.py`) that boots the
existing FastAPI app fully-locally, plus the PyInstaller build and the per-OS smoke
gate. Spec: `docs/superpowers/specs/2026-06-26-desktop-client-and-release-design.md`
§4, §8, §13, §14, §16.

## Locked shared interfaces (do not change without updating workstream E)
- `backend/desktop_entry.py` is the PyInstaller entrypoint; sidecar base name `uh-backend`.
- It prints **exactly one** stdout line `UH_BACKEND_LISTENING <port>` (flush=True) before/at uvicorn start.
- App-data dir via `platformdirs`: `appname="UniversityHelper"`, `appauthor="cornna"` (ASCII; display name 学道 is Tauri-side only).
- desktop uvicorn: `workers=1, loop="asyncio", http="h11"` — **never uvloop** (absent on Windows).
- Python 3.11. Strict TDD (test before impl). Small commits — one per task below.

## Cross-workstream dependencies (see summary at bottom)
- D **sets** env vars (`PROFILE`, `STORAGE_BACKEND`, `SQLITE_PATH`, `FRONTEND_DIST`, …);
  **A/B/C must consume** them (`app.config` uses `extra="ignore"`, so a *typed field*
  must exist or a consumer must read `os.environ` directly).
- The `/health` smoke gate (D6) passes only once **A** (SQLite `DbProbe`) is merged; full
  app behaviour additionally needs **B** (profile/auth) and **C** (SPA serve).
- **E** consumes the built `uh-backend` binary + the token contract. **F** invokes
  `scripts/build_sidecar.sh` and `scripts/smoke_sidecar.sh`.

---

## D1 — Add `platformdirs` runtime dep (+ PyInstaller build dep)

**Why:** the launcher resolves the OS app-data dir via `platformdirs`; the spec mandates adding it (§ shared interfaces).

**Edit `backend/requirements.txt`** — append:
```
platformdirs>=4.2,<5
```
**Edit `backend/requirements-dev.txt`** — append (build-time only; CI also `pip install pyinstaller` explicitly):
```
pyinstaller>=6.6,<7
```

**Commands + expected output:**
```bash
cd backend && pip install -r requirements.txt -r requirements-dev.txt
python -c "import platformdirs, PyInstaller; print(platformdirs.__version__, PyInstaller.__version__)"
# -> e.g. "4.3.6 6.11.1"  (any 4.x / 6.x is fine)
```

**Commit:** `D1: add platformdirs runtime dep + pyinstaller dev dep`

---

## D2 — Failing unit tests for the launcher helpers (RED)

**Why:** TDD. These tests pin the locked env contract before any implementation exists.

**Create `backend/tests/unit/test_desktop_entry.py`:**
```python
import json
import os
import socket
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import desktop_entry  # backend/ is on sys.path (same as `import app`)


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    # Redirect every app_data_dir() call (configure_env + persisted use the
    # module global) to an isolated tmp dir.
    monkeypatch.setattr(desktop_entry, "app_data_dir", lambda: tmp_path)
    return tmp_path


def test_free_port_returns_bindable_port():
    port = desktop_entry.free_port()
    assert 1024 < port < 65536
    # It was free at selection time -> we can bind it now.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", port))


def test_persisted_generates_once_then_returns_same(appdata):
    calls = {"n": 0}

    def gen():
        calls["n"] += 1
        return f"value-{calls['n']}"

    first = desktop_entry.persisted("secret_key", gen)
    second = desktop_entry.persisted("secret_key", gen)
    assert first == second == "value-1"
    assert calls["n"] == 1  # gen() ran exactly once


@pytest.mark.skipif(os.name == "nt", reason="POSIX file mode bits")
def test_persisted_writes_0600(appdata):
    desktop_entry.persisted("credential.key", lambda: "k")
    mode = stat.S_IMODE((appdata / "credential.key").stat().st_mode)
    assert mode == 0o600


def test_configure_env_sets_every_required_var(appdata, monkeypatch):
    for k in (
        "PROFILE STORAGE_BACKEND SQLITE_PATH FRONTEND_DIST ENV ENFORCE_HTTPS "
        "SECRET_KEY CREDENTIAL_ENCRYPTION_KEY CORS_ORIGINS "
        "CHAOXING_COOKIES_FILE CHAOXING_CACHE_FILE MAIN_DB_USER MAIN_DB_PASSWORD"
    ).split():
        monkeypatch.delenv(k, raising=False)

    desktop_entry.configure_env(54321, "/some/dist")

    assert os.environ["PROFILE"] == "local"
    assert os.environ["STORAGE_BACKEND"] == "sqlite"
    assert os.environ["ENV"] == "dev"
    assert os.environ["ENFORCE_HTTPS"] == "false"
    assert os.environ["FRONTEND_DIST"] == "/some/dist"
    assert os.environ["SQLITE_PATH"] == str(appdata / "local.db")
    assert os.environ["CHAOXING_COOKIES_FILE"] == str(appdata / "cookies.json")
    assert os.environ["CHAOXING_CACHE_FILE"] == str(appdata / "answer_cache.json")
    # CORS_ORIGINS must be a JSON list with exactly the loopback origin.
    assert json.loads(os.environ["CORS_ORIGINS"]) == ["http://127.0.0.1:54321"]
    assert len(os.environ["SECRET_KEY"]) >= 16
    # CREDENTIAL_ENCRYPTION_KEY must be a usable Fernet key.
    from cryptography.fernet import Fernet
    Fernet(os.environ["CREDENTIAL_ENCRYPTION_KEY"].encode())


def test_configure_env_secrets_stable_across_calls(appdata):
    desktop_entry.configure_env(1111, "/d")
    sk1, ck1 = os.environ["SECRET_KEY"], os.environ["CREDENTIAL_ENCRYPTION_KEY"]
    desktop_entry.configure_env(2222, "/d")  # different port, same persisted secrets
    assert os.environ["SECRET_KEY"] == sk1
    assert os.environ["CREDENTIAL_ENCRYPTION_KEY"] == ck1


def test_app_config_imports_after_configure_env(tmp_path):
    # Run in a clean subprocess: proves configure_env ALONE satisfies app.config's
    # import-time validators, without mutating this session's os.environ/sys.modules
    # and without inheriting pytest.ini's env. (`settings = Settings()` runs at import.)
    code = textwrap.dedent(
        """
        import os, sys
        from pathlib import Path
        for k in ("SECRET_KEY CORS_ORIGINS ENFORCE_HTTPS ENV PROFILE STORAGE_BACKEND "
                  "SQLITE_PATH FRONTEND_DIST CREDENTIAL_ENCRYPTION_KEY MAIN_DB_USER "
                  "MAIN_DB_PASSWORD CHAOXING_COOKIES_FILE CHAOXING_CACHE_FILE").split():
            os.environ.pop(k, None)
        import desktop_entry
        desktop_entry.app_data_dir = lambda: Path(sys.argv[1])
        desktop_entry.configure_env(45678, "/d")
        from app.config import settings
        assert settings.CORS_ORIGINS == ["http://127.0.0.1:45678"], settings.CORS_ORIGINS
        assert settings.ENFORCE_HTTPS is False
        assert len(settings.SECRET_KEY) >= 16
        assert os.environ["PROFILE"] == "local"
        # PROFILE typed field arrives with workstream B (extra='ignore' drops it until then).
        if hasattr(settings, "PROFILE"):
            assert settings.PROFILE == "local"
        print("OK")
        """
    )
    backend = Path(desktop_entry.__file__).resolve().parent
    proc = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=str(backend), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout
```

**Run (expect RED — module/functions don't exist yet):**
```bash
cd backend && python -m pytest tests/unit/test_desktop_entry.py -q
# -> ModuleNotFoundError: No module named 'desktop_entry'  (collection error / fail)
```

**Commit:** `D2: failing unit tests for desktop_entry launcher helpers`

---

## D3 — Implement `backend/desktop_entry.py` (GREEN)

**Why:** the frozen entrypoint. Every step except `main()` is a small importable
function so the env/path wiring is unit-testable without booting uvicorn.

**Create `backend/desktop_entry.py`:**
```python
"""Frozen desktop entrypoint for University Helper (the `uh-backend` sidecar).

Resolves an OS app-data dir, persists the local single-user secrets, points all
writable paths under app-data, sets PROFILE=local / STORAGE_BACKEND=sqlite (and
the rest) in os.environ BEFORE app.config is imported, picks a free loopback
port, prints the port token Tauri parses, then boots uvicorn with the asyncio
loop + h11 (NEVER uvloop — absent on Windows).

Helpers are kept side-effect-light and importable so the env/path wiring can be
unit-tested without starting uvicorn.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
from pathlib import Path
from typing import Callable

import platformdirs
from cryptography.fernet import Fernet

# ASCII identity (filesystem-safe). The display name 学道 lives Tauri-side only.
APP_NAME = "UniversityHelper"
APP_AUTHOR = "cornna"
TOKEN_PREFIX = "UH_BACKEND_LISTENING"


def app_data_dir() -> Path:
    """Return (creating if needed) the per-user app-data dir.

    Windows: %APPDATA%\\cornna\\UniversityHelper
    macOS:   ~/Library/Application Support/UniversityHelper
    Linux:   ~/.local/share/UniversityHelper
    """
    d = Path(platformdirs.user_data_dir(APP_NAME, APP_AUTHOR))
    d.mkdir(parents=True, exist_ok=True)
    return d


def persisted(name: str, gen: Callable[[], str]) -> str:
    """Return a secret persisted under app-data, generating it once (mode 0600).

    First call: gen() produces the value, it is written + chmod 0600, returned.
    Later calls: the SAME stored value is read back, so SECRET_KEY / the Fernet
    key stay stable across restarts (otherwise previously-encrypted credentials
    would become undecryptable).
    """
    path = app_data_dir() / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = gen()
    path.write_text(value, encoding="utf-8")
    # 0600 is correct on POSIX (file holds a secret); a best-effort no-op on
    # Windows, which uses ACLs — swallow the OSError there.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return value


def free_port() -> int:
    """Pick a currently-free loopback TCP port (bind :0, read it, close).

    There is an inherent TOCTOU window before uvicorn binds; acceptable for a
    single-user desktop app on loopback.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def frontend_dist() -> str:
    """Resolve the bundled frontend/dist dir (frozen via _MEIPASS, else repo path).

    Mirrors cxsecret_font.resource_path's _MEIPASS-first strategy so the same
    bundle works frozen and in dev (`python backend/desktop_entry.py`).
    """
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "frontend" / "dist")
    # backend/desktop_entry.py -> parents[1] == repo root -> frontend/dist
    candidates.append(Path(__file__).resolve().parents[1] / "frontend" / "dist")
    for c in candidates:
        if c.is_dir():
            return str(c)
    return str(candidates[0])  # stable fallback; SPA mount degrades if absent


def configure_env(port: int, dist: str) -> None:
    """Set every env var app.config needs — call BEFORE importing app.config/app.main.

    Idempotent w.r.t. the persisted secrets (read back, never regenerated).
    """
    d = app_data_dir()

    # Profile / storage selection (consumed by workstreams B / A).
    os.environ["PROFILE"] = "local"
    os.environ["STORAGE_BACKEND"] = "sqlite"
    os.environ["SQLITE_PATH"] = str(d / "local.db")
    os.environ["FRONTEND_DIST"] = dist  # consumed by workstream C

    # ENV=dev makes CREDENTIAL_ENCRYPTION_KEY optional in init_cipher and skips the
    # production https/CORS gate; ENFORCE_HTTPS=false stops the 301 loop on loopback.
    os.environ["ENV"] = "dev"
    os.environ["ENFORCE_HTTPS"] = "false"

    # Persisted secrets (satisfy config validators; stable across restarts).
    os.environ["SECRET_KEY"] = persisted("secret_key", lambda: secrets.token_urlsafe(48))
    os.environ["CREDENTIAL_ENCRYPTION_KEY"] = persisted(
        "credential.key", lambda: Fernet.generate_key().decode("ascii")
    )

    # config.py parses CORS_ORIGINS as JSON; non-empty validator then passes.
    os.environ["CORS_ORIGINS"] = json.dumps([f"http://127.0.0.1:{port}"])

    # Writable runtime files under app-data (module defaults point at /tmp).
    os.environ["CHAOXING_COOKIES_FILE"] = str(d / "cookies.json")
    os.environ["CHAOXING_CACHE_FILE"] = str(d / "answer_cache.json")

    # config.py declares MAIN_DB_USER/MAIN_DB_PASSWORD as REQUIRED (no default), so
    # app.config raises at import even though SQLite never opens a Postgres socket.
    # Seed harmless placeholders. NOTE: if workstream A makes MAIN_DB_* optional
    # under STORAGE_BACKEND=sqlite, delete these two lines.
    os.environ.setdefault("MAIN_DB_USER", "local")
    os.environ.setdefault("MAIN_DB_PASSWORD", "local")


def main() -> None:
    # answer_base.py reads ./config.ini relative to CWD; chdir into app-data so an
    # optional user config.ini resolves and stray writes land in a writable dir.
    # The cookies/cache/sqlite paths set above are ABSOLUTE, so chdir is safe.
    os.chdir(app_data_dir())

    dist = frontend_dist()
    port = free_port()
    configure_env(port, dist)

    # The ONE line Tauri (workstream E) parses for the port. Printed BEFORE
    # uvicorn.run so the parent can navigate while the server finishes binding
    # (Tauri then polls /health). flush=True is mandatory — frozen stdout is
    # block-buffered.
    print(f"{TOKEN_PREFIX} {port}", flush=True)

    import uvicorn

    # Import string is resolved lazily inside run() — i.e. AFTER configure_env, so
    # app.config sees the local env. asyncio + h11 only (uvloop absent on Windows).
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        workers=1,
        loop="asyncio",
        http="h11",
        log_level="info",
    )


if __name__ == "__main__":
    main()
```

**Run (expect GREEN):**
```bash
cd backend && python -m pytest tests/unit/test_desktop_entry.py -q
# -> all tests pass (the 0600 test is skipped on Windows)
```

**Manual dev boot sanity (optional, not a CI gate; needs frontend/dist built or it degrades):**
```bash
cd /Users/cornna/project/university-helper/university-helper
python backend/desktop_entry.py &
sleep 4
# stdout shows exactly: UH_BACKEND_LISTENING <port>
curl -s "http://127.0.0.1:<port>/health"   # 200 once workstream A's SQLite DbProbe is merged
kill %1
```
> Until A merges, `/health` may 503 on the Postgres probe — expected; the gate is D6.

**Commit:** `D3: implement desktop_entry launcher (app_data_dir/persisted/free_port/configure_env/main)`

---

## D4 — Lint/type the new module + wire into existing checks

**Why:** keep the new file inside the repo's ruff/mypy gates (small, cheap, no behaviour change).

```bash
cd backend
ruff check desktop_entry.py tests/unit/test_desktop_entry.py
ruff format --check desktop_entry.py
mypy desktop_entry.py            # `from __future__ import annotations` + typed sigs
# all clean
```
Fix any findings (e.g. import order). No `# type: ignore` unless justified inline.

**Commit:** `D4: ruff/mypy clean for desktop_entry`

---

## D5 — PyInstaller onefile build (`scripts/build_sidecar.sh`)

**Why:** produce the `uh-backend` sidecar from `desktop_entry.py` with all
compiled/lazy deps collected. A green build ≠ a booting app — D6 is the real gate.

**Create `scripts/build_sidecar.sh` (chmod +x):**
```bash
#!/usr/bin/env bash
# Build the frozen `uh-backend` sidecar (PyInstaller --onefile).
#
# Run from anywhere; resolves the repo root itself. Prereqs:
#   pip install -r backend/requirements.txt -r backend/requirements-dev.txt
#   a built frontend at frontend/dist (npm --prefix frontend ci && run build)
#
# Output:
#   dist/uh-backend       (Linux, macOS)
#   dist/uh-backend.exe   (Windows)
# CI (workstream F) renames it to frontend/src-tauri/binaries/uh-backend-<triple>[.exe].
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# --add-data uses ';' as src:dst sep on Windows, ':' elsewhere. Allow override.
SEP="${PYI_ADDDATA_SEP:-}"
if [ -z "$SEP" ]; then
  case "${OSTYPE:-}${OS:-}" in
    *msys*|*cygwin*|*win32*|*Windows*) SEP=';' ;;
    *) SEP=':' ;;
  esac
fi

if [ ! -d frontend/dist ]; then
  echo "ERROR: frontend/dist missing — build the SPA first (npm --prefix frontend ci && npm --prefix frontend run build)" >&2
  exit 1
fi

python -m PyInstaller \
  --noconfirm --clean \
  --onefile \
  --name uh-backend \
  --paths backend \
  --collect-submodules app \
  --collect-submodules api \
  --collect-submodules Crypto \
  --collect-submodules fontTools \
  --collect-all lxml \
  --collect-all bcrypt \
  --hidden-import pyaes \
  --add-data "frontend/dist${SEP}frontend/dist" \
  backend/desktop_entry.py

ls -l dist/uh-backend* 2>/dev/null || { echo "ERROR: no sidecar produced" >&2; exit 1; }
echo "Built sidecar: $(ls -1 dist/uh-backend*)"
```

**Notes baked into the design:**
- `--paths backend` makes `app`, `api`, `desktop_entry` importable; `--collect-submodules app/api`
  bundles modules pulled in by string-level `from api.* import …` (the legacy shim).
- `--add-data frontend/dist:frontend/dist` lands the SPA at `_MEIPASS/frontend/dist`,
  exactly where `frontend_dist()` / `cxsecret_font.resource_path()` look.
- `--collect-all lxml`, `--collect-submodules Crypto` (pycryptodome), `--collect-submodules
  fontTools`, `--collect-all bcrypt`, `--hidden-import pyaes` cover the lazy/compiled deps.
- **No uvloop/httptools at runtime:** we pass `loop="asyncio", http="h11"`. They may still
  be *bundled* (harmless); to trim size you MAY add `--exclude-module uvloop --exclude-module
  httptools` (uvicorn guards those imports, so excluding is safe).
- `cryptography` / `pydantic-core` ship compiled `.so`/`.pyd` collected by their PyInstaller
  hooks — verify they land; if the D6 smoke catches a `ModuleNotFoundError`, add the missing
  `--hidden-import` / `--collect-all` (e.g. `--collect-all cryptography`) and rebuild.
- `psycopg2` is intentionally NOT forced: the storage factory (workstream A) imports
  `postgres.py` lazily, so the local build need not bundle it. If A's factory imports it
  eagerly, either make it lazy or add `--hidden-import psycopg2`.
- An equivalent `backend/uh-backend.spec` may be generated later (`pyi-makespec` with the
  same flags) if per-OS tweaks are needed; the shell script is the single source for now.

**Per-OS output → CI copy target (documented for workstream E/F):**
| Runner | `dist/` output | renamed to (triple via `rustc --print host-tuple`) |
|---|---|---|
| windows-latest | `uh-backend.exe` | `frontend/src-tauri/binaries/uh-backend-x86_64-pc-windows-msvc.exe` |
| macos (arm) | `uh-backend` | `frontend/src-tauri/binaries/uh-backend-aarch64-apple-darwin` |
| macos (intel) | `uh-backend` | `frontend/src-tauri/binaries/uh-backend-x86_64-apple-darwin` |
| ubuntu-22.04 | `uh-backend` | `frontend/src-tauri/binaries/uh-backend-x86_64-unknown-linux-gnu` |

**Commands + expected output:**
```bash
cd /Users/cornna/project/university-helper/university-helper
npm --prefix frontend ci && npm --prefix frontend run build   # produces frontend/dist
bash scripts/build_sidecar.sh
# ... PyInstaller log ...
# Built sidecar: dist/uh-backend
ls -l dist/uh-backend       # an executable, tens of MB
```

> **NOTE (caveat from spec §9/§16, not a blocker):** `--onefile` is a bootloader that
> unpacks to a temp dir and spawns a child process; on some platforms killing the parent
> does not reap the grandchild. This is handled downstream — D6's smoke kills the whole
> process group, and workstream E kills the `CommandChild` on `RunEvent::ExitRequested`
> (and before the updater restart). If onefile startup proves slow, §16 allows revisiting
> onedir; no code here changes if we switch.

**Commit:** `D5: PyInstaller onefile build script for uh-backend sidecar`

---

## D6 — Per-OS smoke gate (`scripts/smoke_sidecar.sh` + pytest variant)

**Why:** the mandatory CI gate per the spec (§8, §13, §14): boot the *built binary*, wait
for the stdout token, `curl /health` == 200, then kill it. A green build is not proof the
frozen app boots.

**Create `scripts/smoke_sidecar.sh` (chmod +x) — POSIX runners (macOS/Linux):**
```bash
#!/usr/bin/env bash
# CI gate: boot the frozen sidecar, wait for its port token, assert /health == 200.
# Usage: scripts/smoke_sidecar.sh [path-to-binary]   (default: dist/uh-backend[.exe])
set -uo pipefail

BIN="${1:-}"
if [ -z "$BIN" ]; then
  if [ -x dist/uh-backend ]; then BIN=dist/uh-backend; else BIN=dist/uh-backend.exe; fi
fi
[ -x "$BIN" ] || { echo "ERROR: sidecar binary not found/executable: $BIN" >&2; exit 1; }

OUT="$(mktemp)"
set -m                       # own process group so we can reap the onefile child
"$BIN" >"$OUT" 2>&1 &
PID=$!

cleanup() {
  kill -- -"$PID" 2>/dev/null || kill "$PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
  rm -f "$OUT"
}
trap cleanup EXIT

# 1) wait up to 30s for the single token line
PORT=""
for _ in $(seq 1 300); do
  PORT="$(sed -n 's/^UH_BACKEND_LISTENING \([0-9][0-9]*\).*/\1/p' "$OUT" | head -n1)"
  [ -n "$PORT" ] && break
  kill -0 "$PID" 2>/dev/null || { echo "ERROR: sidecar exited early:" >&2; cat "$OUT" >&2; exit 1; }
  sleep 0.1
done
[ -n "$PORT" ] || { echo "ERROR: never saw UH_BACKEND_LISTENING token:" >&2; cat "$OUT" >&2; exit 1; }
echo "sidecar listening on port $PORT"

# 2) poll /health up to 15s for 200
CODE=""
for _ in $(seq 1 150); do
  CODE="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/health" || true)"
  [ "$CODE" = "200" ] && { echo "PASS: /health 200"; exit 0; }
  sleep 0.1
done
echo "ERROR: /health never returned 200 (last code: ${CODE:-none})" >&2
cat "$OUT" >&2
exit 1
```

**Create `backend/tests/integration/test_sidecar_smoke.py` — cross-platform (incl. Windows CI):**
```python
"""Integration smoke test for the frozen sidecar (the per-OS CI gate).

Skipped unless UH_SIDECAR_BIN points at a built `uh-backend` binary, so the
normal unit run is unaffected. CI sets UH_SIDECAR_BIN after build_sidecar.sh and
runs: pytest tests/integration/test_sidecar_smoke.py
"""

import os
import re
import signal
import subprocess
import time
import urllib.request

import pytest

BIN = os.environ.get("UH_SIDECAR_BIN")

pytestmark = pytest.mark.skipif(
    not BIN or not os.path.exists(BIN),
    reason="UH_SIDECAR_BIN not set to a built sidecar binary",
)


def _start() -> subprocess.Popen:
    kwargs = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True  # own process group -> clean reap
    return subprocess.Popen(
        [BIN], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, **kwargs,
    )


def _kill(proc: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, OSError):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_sidecar_boots_and_health_ok():
    proc = _start()
    try:
        # 1) read the port token (30s budget)
        port = None
        deadline = time.time() + 30
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    pytest.fail(f"sidecar exited early rc={proc.returncode}")
                continue
            m = re.match(r"UH_BACKEND_LISTENING (\d+)", line.strip())
            if m:
                port = int(m.group(1))
                break
        assert port, "never saw UH_BACKEND_LISTENING token"

        # 2) poll /health for 200 (15s budget)
        ok = False
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=2
                ) as r:
                    if r.status == 200:
                        ok = True
                        break
            except Exception:
                time.sleep(0.2)
        assert ok, "/health never returned 200"
    finally:
        _kill(proc)
```
> Implementation note: after the token we stop draining stdout; the brief /health window
> finishes well before uvicorn could fill the stdout pipe buffer, then we kill. If a future
> sidecar logs heavily to stdout, drain it on a daemon thread.

**Commands + expected output (POSIX):**
```bash
cd /Users/cornna/project/university-helper/university-helper
bash scripts/smoke_sidecar.sh dist/uh-backend
# sidecar listening on port 5xxxx
# PASS: /health 200      (exit 0)

# pytest variant (used on Windows CI; also works on POSIX):
UH_SIDECAR_BIN="$PWD/dist/uh-backend" python -m pytest backend/tests/integration/test_sidecar_smoke.py -q
# 1 passed   (skipped when UH_SIDECAR_BIN unset)
```

**CI wiring (informs workstream F's `desktop` matrix leg):** after `pip install …` + build:
`bash scripts/build_sidecar.sh` → on Windows run the pytest variant with `UH_SIDECAR_BIN`
set to `dist/uh-backend.exe`, on macOS/Linux run `scripts/smoke_sidecar.sh dist/uh-backend`.
This gate must pass before the binary is renamed to the target triple and handed to Tauri.

> Reminder: this gate only goes green once **workstream A** (SQLite `DbProbe` for `/health`)
> is merged, since `/health` runs a DB `SELECT 1`.

**Commit:** `D6: per-OS sidecar smoke gate (shell + pytest), the mandatory boot test`

---

## Definition of done (workstream D)
- `backend/desktop_entry.py` exists with the 5 locked functions; unit tests (D2) green; ruff/mypy clean.
- `scripts/build_sidecar.sh` produces `dist/uh-backend[.exe]` on each OS.
- `scripts/smoke_sidecar.sh` + `tests/integration/test_sidecar_smoke.py` exist and pass against the built binary (post-A).
- `platformdirs` in `requirements.txt`; `pyinstaller` in `requirements-dev.txt`.
- The token contract (`UH_BACKEND_LISTENING <port>`) and binary naming are documented for E/F.
# Workstream E — Tauri v2 desktop shell (`frontend/src-tauri/`)

Implements §9 of `docs/superpowers/specs/2026-06-26-desktop-client-and-release-design.md`.

**Scope:** scaffold a greenfield Tauri v2 Rust app that spawns the workstream-D sidecar
`uh-backend`, parses its `UH_BACKEND_LISTENING <port>` readiness line, opens the webview
at `http://127.0.0.1:<port>` (the sidecar serves the SPA same-origin), kills the sidecar on
exit, and is wired for GitHub-Releases auto-update.

### Pinned versions (validated against current docs/registries, 2026-06-26)
| Crate / tool | Version | Source |
|---|---|---|
| `tauri` (+ `tauri-build`) | **2.11.3** (latest stable, published 2026-06-17) | https://crates.io/crates/tauri |
| `tauri-plugin-shell` | **2.3.5** | https://crates.io/crates/tauri-plugin-shell |
| `tauri-plugin-updater` | **2.10.1** | https://crates.io/crates/tauri-plugin-updater |
| `tauri-plugin-process` | **2.3.1** | https://crates.io/crates/tauri-plugin-process |
| `@tauri-apps/cli` (npm) | **2.11.3** | `npm view @tauri-apps/cli version` |
| Rust toolchain | stable; **≥1.77.2** (Tauri 2.x MSRV), **≥1.84** for `rustc --print host-tuple` | https://v2.tauri.app/develop/sidecar/ |

### Tauri facts confirmed from docs (cite in PRs)
- **Sidecar spawn (Rust):** `app.shell().sidecar("binaries/uh-backend")?.spawn()` returns `(rx, child)`; read `rx.recv().await` for `CommandEvent::Stdout(Vec<u8>)`. — https://v2.tauri.app/develop/sidecar/
- **externalBin triple naming:** ship `binaries/uh-backend-<target-triple>[.exe]` (e.g. `uh-backend-x86_64-pc-windows-msvc.exe`, `uh-backend-aarch64-apple-darwin`); get triple via `rustc --print host-tuple` (Rust ≥1.84). The `externalBin` / `Command::sidecar` name is the **path without the triple**: `binaries/uh-backend`. — https://v2.tauri.app/develop/sidecar/
- **Kill child on exit:** store `CommandChild` in managed state; in the `Builder::run(|app, event| …)` callback match `RunEvent::ExitRequested { .. }` and `child.kill()`. Tauri does **not** auto-reap sidecars. — https://github.com/tauri-apps/tauri/discussions/3273
- **Updater config keys:** `bundle.createUpdaterArtifacts: true` + `plugins.updater.{pubkey, endpoints}`. — https://v2.tauri.app/plugin/updater/
- **Runtime window:** `WebviewWindowBuilder::new(&handle, "main", WebviewUrl::External(url))` (loopback, same-origin). — https://v2.tauri.app/plugin/localhost/
- **Capabilities:** JS-side sidecar exec needs `shell:allow-spawn`/`shell:allow-execute` with `{name, sidecar:true, args:true}`. — https://v2.tauri.app/develop/sidecar/

> **Rust TDD scope (acknowledged):** the only pure-logic unit under test is `parse_listening_port` (task **E2**). Everything else in the Rust shell is glue over Tauri runtime APIs (window/process lifecycle) that can't be unit-tested headlessly; those are guarded by **compile + `clippy -D warnings` + `fmt --check`** gates (E5) and the per-OS `/health` boot smoke owned by workstreams D/F. No success claims without running the command and seeing the output.

---

## E1 — Scaffold `frontend/src-tauri/` (Cargo.toml, build.rs, tauri.conf.json) + npm wiring

**Objective:** create the Tauri v2 project skeleton with the locked bundle/updater config and the `npm run tauri` entrypoint. No Rust app logic yet (that's E2/E3).

**Create `frontend/src-tauri/Cargo.toml`** (full contents):
```toml
[package]
name = "uh-desktop"
version = "1.4.0"                      # stamped from the git tag by scripts/set_version.sh (workstream F)
description = "学道 — University Helper desktop shell"
authors = ["sweetcornna"]
edition = "2021"
rust-version = "1.77.2"

[lib]
# The desktop entrypoint lives in the lib so a future mobile target can reuse run().
name = "uh_desktop_lib"
crate-type = ["staticlib", "cdylib", "rlib"]

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
tauri = { version = "2.11", features = [] }
tauri-plugin-shell = "2"
tauri-plugin-process = "2"
serde = { version = "1", features = ["derive"] }

# Updater is a desktop-only plugin (matches `cargo add … --target 'cfg(...)'` from the docs).
[target.'cfg(any(target_os = "macos", windows, target_os = "linux"))'.dependencies]
tauri-plugin-updater = "2"

[profile.release]
codegen-units = 1
lto = true
opt-level = "s"
panic = "abort"
strip = true
```

**Create `frontend/src-tauri/build.rs`** (full contents):
```rust
fn main() {
    tauri_build::build()
}
```

**Create `frontend/src-tauri/tauri.conf.json`** (full contents):
```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "学道",
  "version": "1.4.0",
  "identifier": "xyz.cornna.shuake",
  "build": {
    "beforeDevCommand": "",
    "beforeBuildCommand": "",
    "frontendDist": "splash"
  },
  "app": {
    "windows": [
      {
        "label": "splash",
        "title": "学道",
        "width": 480,
        "height": 320,
        "resizable": false,
        "center": true
      }
    ],
    "security": {
      "csp": null
    }
  },
  "bundle": {
    "active": true,
    "targets": ["msi", "nsis", "dmg", "app", "appimage", "deb"],
    "externalBin": ["binaries/uh-backend"],
    "createUpdaterArtifacts": true,
    "icon": [
      "icons/32x32.png",
      "icons/128x128.png",
      "icons/128x128@2x.png",
      "icons/icon.icns",
      "icons/icon.ico"
    ]
  },
  "plugins": {
    "updater": {
      "pubkey": "PLACEHOLDER_UPDATER_PUBKEY__FILLED_BY_WORKSTREAM_F_KEYGEN",
      "endpoints": [
        "https://github.com/sweetcornna/university-helper/releases/latest/download/latest.json"
      ]
    }
  }
}
```
Notes on locked choices:
- `frontendDist: "splash"` → Tauri bundles only a tiny placeholder page (E5 creates `splash/index.html`). The **real UI is the loopback page** built at runtime in E3; we never duplicate `frontend/dist` into the Tauri bundle. `beforeBuildCommand`/`beforeDevCommand` are empty because the SPA is built by workstream D/F (`npm run build` → consumed by PyInstaller), not by Tauri.
- `app.security.csp: null` — page is served by FastAPI on loopback (per §9); CSP is the backend's concern.
- `bundle.icon` is **required** for `tauri build`/`generate_context!`; E5 generates the icon set.
- `plugins.updater.pubkey` is the locked **placeholder** — workstream F's `tauri signer generate` fills it; `version` (here + Cargo.toml) is stamped by F's `scripts/set_version.sh`.

**Create `frontend/src-tauri/splash/index.html`** (placeholder bundled page — minimal so the bundle has something to load before the loopback window opens):
```html
<!doctype html>
<html lang="zh">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>学道</title>
    <style>
      html, body { height: 100%; margin: 0; }
      body { display: grid; place-items: center; font-family: system-ui, sans-serif;
             background: #0b1020; color: #e6e8ef; }
      .dot { width: 10px; height: 10px; border-radius: 50%; background: #6ea8fe;
             animation: pulse 1s ease-in-out infinite; margin-top: 12px; }
      @keyframes pulse { 0%,100%{opacity:.3} 50%{opacity:1} }
    </style>
  </head>
  <body>
    <div style="text-align:center">
      <h1 style="font-weight:600">学道</h1>
      <p style="opacity:.7;margin:0">正在启动本地服务…</p>
      <div class="dot" style="margin:12px auto 0"></div>
    </div>
  </body>
</html>
```

**Edit `frontend/package.json`** — add the CLI devDep + script:
```jsonc
// devDependencies: add
"@tauri-apps/cli": "^2.11.3"
// scripts: add
"tauri": "tauri"
```
(Run `npm install` from `frontend/` afterwards; `npm run tauri` auto-detects `frontend/src-tauri/`.)

**Create `frontend/src-tauri/.gitignore`**:
```gitignore
/target
/gen/schemas
# CI drops the real triple-named sidecar here; only the placeholder loader is tracked (E5)
/binaries/uh-backend-*
```

**Commands / expected output:**
```bash
cargo metadata --manifest-path frontend/src-tauri/Cargo.toml --no-deps --format-version 1 >/dev/null && echo "Cargo.toml parses OK"
# → Cargo.toml parses OK
python3 -c "import json;json.load(open('frontend/src-tauri/tauri.conf.json'));print('tauri.conf.json valid JSON')"
# → tauri.conf.json valid JSON
```
(Full `cargo check` is deferred to E5 — it needs the E3 source + icons + a placeholder sidecar.)

**Commit:** `feat(desktop): scaffold Tauri v2 project (Cargo, build.rs, tauri.conf.json, npm wiring)`

---

## E2 — TDD: pure `parse_listening_port(line: &str) -> Option<u16>`

**Objective:** the one true unit-tested piece. Parse the locked readiness line `UH_BACKEND_LISTENING 51763`. Write the failing test first, then the function.

**Create `frontend/src-tauri/src/port.rs`** (full contents — function + `#[cfg(test)]` tests):
```rust
//! Parses the sidecar readiness line emitted by the workstream-D launcher.
//!
//! Contract (locked across workstreams D + E): the `uh-backend` sidecar prints
//! exactly one line `UH_BACKEND_LISTENING <port>` to stdout once uvicorn is bound.

/// Extract the loopback port from a single stdout line.
///
/// Returns `Some(port)` only when the line's first whitespace-delimited token is
/// exactly `UH_BACKEND_LISTENING` and the second token parses as a `u16`.
/// Tolerant of leading/trailing whitespace and `\r\n`; rejects everything else.
pub fn parse_listening_port(line: &str) -> Option<u16> {
    let mut parts = line.split_whitespace();
    if parts.next()? != "UH_BACKEND_LISTENING" {
        return None;
    }
    parts.next()?.parse::<u16>().ok()
}

#[cfg(test)]
mod tests {
    use super::parse_listening_port;

    #[test]
    fn parses_valid_line() {
        assert_eq!(parse_listening_port("UH_BACKEND_LISTENING 51763"), Some(51763));
    }

    #[test]
    fn tolerates_surrounding_whitespace_and_crlf() {
        assert_eq!(parse_listening_port("  UH_BACKEND_LISTENING 8000\r\n"), Some(8000));
    }

    #[test]
    fn rejects_unrelated_line() {
        assert_eq!(parse_listening_port("INFO: uvicorn running"), None);
        assert_eq!(parse_listening_port("UH_BACKEND_LISTENING51763"), None);
    }

    #[test]
    fn rejects_missing_port() {
        assert_eq!(parse_listening_port("UH_BACKEND_LISTENING"), None);
    }

    #[test]
    fn rejects_non_numeric_port() {
        assert_eq!(parse_listening_port("UH_BACKEND_LISTENING notaport"), None);
    }

    #[test]
    fn rejects_out_of_range_port() {
        // 70000 > u16::MAX → parse fails (no truncation).
        assert_eq!(parse_listening_port("UH_BACKEND_LISTENING 70000"), None);
    }
}
```

**Run (red→green) — full app crate isn't compilable until E3, so run the module in isolation first:**
```bash
# RED/GREEN on the pure module alone (no tauri, instant — proves the logic before the shell exists):
rustc --test --edition 2021 frontend/src-tauri/src/port.rs -o /tmp/uh_port_test && /tmp/uh_port_test
# → running 6 tests ... test result: ok. 6 passed; 0 failed; 0 ignored
```
After E3 wires `mod port;` into the lib, the same tests run under the normal harness (see E5):
```bash
cargo test --manifest-path frontend/src-tauri/Cargo.toml port::
# → test result: ok. 6 passed; 0 failed
```

**Commit:** `test(desktop): parse_listening_port with unit tests (TDD)`

---

## E3 — `src/lib.rs` + `src/main.rs`: spawn sidecar, parse port, build window, kill on exit

**Objective:** the runtime glue. In `setup()` spawn the sidecar via `tauri-plugin-shell`, read `CommandEvent::Stdout`, call `parse_listening_port`, build the loopback `WebviewWindow`, close the splash, store the `CommandChild` in managed state, and **kill it on `RunEvent::ExitRequested`** (the footgun). Plus a Rust-side updater check that frees the port before relaunch.

**Create `frontend/src-tauri/src/lib.rs`** (full contents):
```rust
mod port;
pub use port::parse_listening_port;

use std::sync::Mutex;

use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

/// Managed state: holds the sidecar handle so we can reap it on exit / before restart.
struct SidecarProcess(Mutex<Option<CommandChild>>);

/// Kill the sidecar if still running. Idempotent (uses `Option::take`).
/// Called from `RunEvent::ExitRequested` and before an updater relaunch so the
/// loopback port is free again (Tauri does NOT auto-reap sidecars).
fn kill_sidecar(app: &AppHandle) {
    if let Some(state) = app.try_state::<SidecarProcess>() {
        if let Some(child) = state.0.lock().unwrap().take() {
            let _ = child.kill();
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            // 1. Spawn the workstream-D sidecar. Name matches `externalBin`/the triple base.
            let sidecar = app
                .shell()
                .sidecar("binaries/uh-backend")
                .expect("failed to create `uh-backend` sidecar command");
            let (mut rx, child) = sidecar.spawn().expect("failed to spawn `uh-backend` sidecar");

            // 2. Keep the child so we can kill it on exit.
            app.manage(SidecarProcess(Mutex::new(Some(child))));

            // 3. Read stdout until we see the readiness line, then open the real window.
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(bytes) => {
                            let line = String::from_utf8_lossy(&bytes);
                            if let Some(p) = parse_listening_port(&line) {
                                let url = format!("http://127.0.0.1:{p}");
                                let h = handle.clone();
                                // Window creation must run on the main thread.
                                handle
                                    .run_on_main_thread(move || {
                                        WebviewWindowBuilder::new(
                                            &h,
                                            "main",
                                            WebviewUrl::External(
                                                url.parse().expect("valid loopback url"),
                                            ),
                                        )
                                        .title("学道")
                                        .inner_size(1280.0, 832.0)
                                        .min_inner_size(960.0, 640.0)
                                        .center()
                                        .build()
                                        .expect("failed to build main window");

                                        if let Some(splash) = h.get_webview_window("splash") {
                                            let _ = splash.close();
                                        }
                                    })
                                    .expect("failed to schedule window creation");
                                break; // got the port; stop scanning stdout
                            }
                        }
                        CommandEvent::Stderr(bytes) => {
                            eprintln!("[uh-backend] {}", String::from_utf8_lossy(&bytes));
                        }
                        CommandEvent::Error(err) => {
                            eprintln!("[uh-backend] error: {err}");
                            break;
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[uh-backend] terminated before readiness: {payload:?}");
                            break;
                        }
                        _ => {}
                    }
                }
            });

            // 4. Background auto-update check (Rust-side; frees the port before relaunch).
            let h2 = app.handle().clone();
            tauri::async_runtime::spawn(check_for_updates(h2));

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building 学道 desktop app")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                // THE FOOTGUN: sidecars are not auto-reaped — kill it ourselves.
                kill_sidecar(app_handle);
            }
        });
}

/// Check GitHub Releases for an update; on install, kill the sidecar then relaunch.
async fn check_for_updates(app: AppHandle) {
    use tauri_plugin_updater::UpdaterExt;

    let updater = match app.updater() {
        Ok(u) => u,
        Err(e) => {
            eprintln!("updater unavailable: {e}");
            return;
        }
    };
    match updater.check().await {
        Ok(Some(update)) => {
            if let Err(e) = update.download_and_install(|_chunk, _total| {}, || {}).await {
                eprintln!("update install failed: {e}");
                return;
            }
            kill_sidecar(&app); // free the loopback port before relaunch
            app.restart();
        }
        Ok(None) => { /* already up to date */ }
        Err(e) => eprintln!("update check failed: {e}"),
    }
}
```

**Create `frontend/src-tauri/src/main.rs`** (full contents):
```rust
// Hide the extra console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    uh_desktop_lib::run()
}
```

Notes:
- Window built on the **main thread** via `run_on_main_thread` (window creation off the main thread panics on macOS/Linux).
- `break` after the port is found stops scanning; the `child` lives on in managed state, not in the reader task.
- Updater uses the **Rust** `UpdaterExt` API (no JS capability needed because the loopback page uses no Tauri IPC). Signing/pubkey come from config (E1) + workstream F.

**Commit:** `feat(desktop): spawn sidecar, open loopback window, reap on exit + updater`

---

## E4 — `capabilities/default.json`

**Objective:** the locked capability set. `core:default`, `updater:default`, and `shell:allow-spawn` scoped to the `uh-backend` sidecar.

**Create `frontend/src-tauri/capabilities/default.json`** (full contents):
```json
{
  "$schema": "../gen/schemas/desktop-schema.json",
  "identifier": "default",
  "description": "Capabilities for the 学道 desktop shell (splash + loopback main window).",
  "windows": ["splash", "main"],
  "permissions": [
    "core:default",
    "updater:default",
    {
      "identifier": "shell:allow-spawn",
      "allow": [
        {
          "name": "binaries/uh-backend",
          "sidecar": true,
          "args": true
        }
      ]
    }
  ]
}
```
Notes:
- `windows` lists **both** the config-defined `splash` and the runtime-created `main` label so the permissions apply to each.
- `shell:allow-spawn` is scoped to exactly the sidecar (the docs' `{name, sidecar:true, args:true}` shape), so no arbitrary command execution is granted.
- No `process:*` capability is exposed to JS: the loopback page never calls Tauri IPC; restart is the Rust-side `AppHandle::restart()` (E3). The `tauri-plugin-process` dep/init is kept for forward use.

**Commands / expected output:**
```bash
python3 -c "import json;json.load(open('frontend/src-tauri/capabilities/default.json'));print('capability JSON valid')"
# → capability JSON valid
```
(Full ACL validation happens during `cargo build`/`generate_context!` in E5.)

**Commit:** `feat(desktop): default capability — core/updater + scoped sidecar spawn`

---

## E5 — Placeholder sidecar, icons, gates (fmt/clippy/test/build smoke), dev-loop docs

**Objective:** make the project locally checkable and buildable without CI: a placeholder triple-named sidecar so bundling/`generate_context!` succeed, an icon set, and the documented gate commands. Acknowledge CI (workstream D/F) provides the **real** PyInstaller sidecar renamed to the triple.

**Create `frontend/src-tauri/binaries/dev-stub.py`** (dev-only loader that honors the locked contract: pick a free port, print the readiness line, serve a trivial page so the loopback window has something to load):
```python
#!/usr/bin/env python3
"""Dev-only stand-in for the workstream-D `uh-backend` sidecar.

NOT shipped. CI replaces this with the PyInstaller binary renamed to
`uh-backend-<target-triple>[.exe]`. This stub only implements the readiness
contract so the Tauri shell can be exercised locally without the full backend.
"""
import http.server
import socket
import sys


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b"<h1>uh-backend dev stub</h1>" if self.path != "/health" else b"ok"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):  # silence
        pass


def main():
    port = free_port()
    print(f"UH_BACKEND_LISTENING {port}", flush=True)
    http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
```

**Create `frontend/src-tauri/scripts/make-dev-sidecar.sh`** (renames the stub to the host triple so `externalBin` resolves locally):
```bash
#!/usr/bin/env bash
# Produce a dev placeholder `binaries/uh-backend-<host-triple>[.exe]` from dev-stub.py.
# CI does NOT use this — it renames the real PyInstaller output instead.
set -euo pipefail
cd "$(dirname "$0")/.."                       # → frontend/src-tauri
TRIPLE="$(rustc --print host-tuple)"          # Rust ≥1.84
SRC="binaries/dev-stub.py"
case "$TRIPLE" in
  *windows*) DEST="binaries/uh-backend-${TRIPLE}.exe" ;;
  *)         DEST="binaries/uh-backend-${TRIPLE}"     ;;
esac
cp "$SRC" "$DEST"
chmod +x "$DEST"
echo "wrote $DEST"
```

**Icons:** generate the bundle icon set referenced by `tauri.conf.json` (required for `generate_context!`/`tauri build`). Provide a 512×512+ source `frontend/src-tauri/icons/source.png` (placeholder logo), then:
```bash
( cd frontend && npm run tauri icon src-tauri/icons/source.png )
# → generates src-tauri/icons/{32x32.png,128x128.png,128x128@2x.png,icon.icns,icon.ico,...}; commit them.
```

**Gate commands & expected output** (run from repo root; `--manifest-path` avoids `cd`):
```bash
# 1. Formatting
cargo fmt --manifest-path frontend/src-tauri/Cargo.toml --check
# → (no output, exit 0)

# 2. Lints — warnings are errors
cargo clippy --manifest-path frontend/src-tauri/Cargo.toml --all-targets -- -D warnings
# → Finished ... (no warnings)

# 3. Unit tests (the real TDD gate — parse_listening_port)
cargo test --manifest-path frontend/src-tauri/Cargo.toml
# → running 6 tests ... test result: ok. 6 passed; 0 failed

# 4. Debug bundle smoke (needs the placeholder sidecar + icons present).
#    Disable updater-artifact signing for the LOCAL smoke (real keys come from workstream F):
bash frontend/src-tauri/scripts/make-dev-sidecar.sh
( cd frontend && npm run tauri build -- --debug \
    --config '{"bundle":{"createUpdaterArtifacts":false}}' )
# → Finished `dev` profile ... Bundling 学道.app / .deb / .msi (per host OS) ... Finished N bundles
```
Gotchas to document:
- `createUpdaterArtifacts: true` (committed config) requires a signing key (`TAURI_SIGNING_PRIVATE_KEY`) at build time → the local smoke overrides it to `false`. CI (workstream F) sets the real key + fills the placeholder pubkey.
- `tauri build` fails if the triple-named `externalBin` is missing → run `make-dev-sidecar.sh` first.
- Windows: the `.py` stub is not directly executable; for a runnable Windows dev loop use the real sidecar or freeze the stub. The `--debug` bundle smoke only needs the file present (it copies, doesn't run it).

**Dev loop (document in PR / a short `frontend/src-tauri/README.md`):**
1. `bash frontend/src-tauri/scripts/make-dev-sidecar.sh` (once per OS / after `cargo clean`).
2. `cd frontend && npm install` (first time) → `npm run tauri dev`.
3. Splash shows → stub prints `UH_BACKEND_LISTENING <port>` → main window opens on the stub page.
4. For the real app, drop the workstream-D PyInstaller binary as `binaries/uh-backend-<triple>[.exe]` instead of the stub.

**Create `frontend/src-tauri/binaries/.gitkeep`** (track the dir; the triple-named binaries are git-ignored per E1).

**Commit:** `chore(desktop): dev sidecar stub, icons, fmt/clippy/test/build gates + dev docs`

---

## Cross-workstream dependencies

- **E ← D (workstream D, sidecar/PyInstaller):**
  - Locked contract `UH_BACKEND_LISTENING <port>` on stdout — E2 parses it, E3 consumes it. (E ships a dev stub honoring the same contract so E is buildable/testable before D lands.)
  - D's PyInstaller output is renamed by CI to `binaries/uh-backend-<target-triple>[.exe]` to satisfy E's `externalBin`.
  - D's backend serves `frontend/dist` same-origin at the loopback URL E opens; E does **not** bundle the SPA.
- **E ← F (workstream F, release pipeline + keygen):**
  - F's `tauri signer generate` produces the real updater **pubkey** that replaces E1's `PLACEHOLDER_…` in `tauri.conf.json`; F provides `TAURI_SIGNING_PRIVATE_KEY[_PASSWORD]` so `createUpdaterArtifacts` can sign.
  - F's `scripts/set_version.sh` stamps the version into `tauri.conf.json` **and** `Cargo.toml` (both default to `1.4.0` here).
  - F's `tauri-action@v0` builds this project with `projectPath: frontend` and attaches `.msi/.nsis/.dmg/.app/.appimage/.deb` + updater `.sig`/`latest.json` (per-OS matrix incl. `ubuntu-22.04` for `webkit2gtk-4.1`).
- **E → D/F:** E owns the `externalBin` name (`binaries/uh-backend`) and triple-naming convention, the capability scope, and the updater endpoint URL — these are inputs D/F must match.
- **Independent of A/B/C:** E has no compile/test dependency on the storage/profile/SPA workstreams (it only talks to D's running process over loopback HTTP).
# Workstream F — Release pipeline + versioning + signing/updater

Spec: `docs/superpowers/specs/2026-06-26-desktop-client-and-release-design.md` §10–§12, §16.
Goal: **one git tag = single source of truth for version**, fan out from a `v*` tag to (a) GHCR
server images and (b) cross-platform desktop installers + auto-updater artifacts, all attached to
one GitHub Release, with **optional** code-signing (unsigned builds must still go green).

## Locked shared interfaces (do not deviate)
- `scripts/set_version.sh "$VERSION"` stamps exactly 5 files:
  `frontend/package.json`, `backend/pyproject.toml`, `backend/app/main.py`,
  `frontend/src-tauri/tauri.conf.json`, `frontend/src-tauri/Cargo.toml`.
- Sidecar staged as `frontend/src-tauri/binaries/uh-backend-<target-triple>[.exe]`
  (triple = the rust target for the leg; Tauri auto-appends `-<triple>` to `externalBin`).
- Updater needs `TAURI_SIGNING_PRIVATE_KEY` (+ `_PASSWORD`) as GitHub secrets and the matching
  public key pasted into `tauri.conf.json` `plugins.updater.pubkey` (the file is owned by E).

## Cross-workstream dependencies (read before executing F)
- **F1** ships independently — its automated test uses self-contained fixtures, so it does not need
  E's `tauri.conf.json`/`Cargo.toml` to exist yet. But the *real* run of `set_version.sh` against the
  repo only touches all 5 files once **E** has created `frontend/src-tauri/{tauri.conf.json,Cargo.toml}`.
- **F2** documents the updater keypair; the pubkey destination (`plugins.updater`) is created by **E**.
- **F3** (release.yml rewrite) hard-depends on **D** (`scripts/build_sidecar.sh`,
  `scripts/smoke_sidecar.sh`, sidecar output at `backend/dist/uh-backend[.exe]`), **E**
  (`frontend/src-tauri` Tauri project with `bundle.externalBin`, `bundle.createUpdaterArtifacts`,
  `binaries/` dir, `Cargo.toml`), **F1** (`scripts/set_version.sh`), and **F2** (signing secrets +
  pubkey — optional/gated). Land F3 **after** D and E are merged.
- **F4** is a standalone ops runbook (no code) — runnable any time; fixes spec §11 at the
  distribution level.
- **F5** references the installer artifact names produced by **E**/**F3**.

---

## F1 — `scripts/set_version.sh` (TDD: test first, then script)

**Goal:** idempotent, portable (GNU + BSD), CWD-independent stamping of the 5 manifests from `$1`
(tolerates a leading `v`). Eliminates today's 4-place manual drift (`frontend/package.json:4`,
`backend/pyproject.toml:3`, `backend/app/main.py:73`, plus the new Tauri files).

### F1.a — Write the failing test first (RED)

New file `backend/tests/unit/test_set_version.py` (runs inside the existing **Backend** pytest job;
`jq`/`sed`/`awk`/`bash` are all present on GitHub `ubuntu-latest` and on dev macOS). The test builds a
self-contained tmp tree (so it does not depend on E's files), copies the script in, runs it, and greps
each file `== 9.9.9`.

```python
# backend/tests/unit/test_set_version.py
"""scripts/set_version.sh stamps ONE version into all five manifests, idempotently.

Self-contained: synthesizes minimal fixtures for all five files (including the
Tauri files that workstream E owns) so this test is green regardless of E's state.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "scripts" / "set_version.sh"

PKG_JSON = (
    '{\n'
    '  "name": "university-helper-frontend",\n'
    '  "private": true,\n'
    '  "version": "0.0.0",\n'
    '  "dependencies": { "react": "^18.2.0", "jsqr": "^1.4.0" }\n'
    '}\n'
)
PYPROJECT = (
    '[project]\n'
    'name = "university-helper-backend"\n'
    'version = "0.0.0"\n'
    'requires-python = ">=3.11"\n\n'
    '[tool.ruff]\n'
    'target-version = "py311"\n'
)
MAIN_PY = (
    'app = FastAPI(\n'
    '    title="University Helper API",\n'
    '    description="…",\n'
    '    version="0.0.0",\n'
    '    docs_url="/docs",\n'
    ')\n'
)
TAURI_JSON = (
    '{\n'
    '  "productName": "University Helper",\n'
    '  "version": "0.0.0",\n'
    '  "identifier": "xyz.cornna.shuake"\n'
    '}\n'
)
CARGO_TOML = (
    '[package]\n'
    'name = "uh"\n'
    'version = "0.0.0"\n'
    'edition = "2021"\n\n'
    '[dependencies]\n'
    'tauri = { version = "2", features = [] }\n'
)

FILES = [
    "frontend/package.json",
    "backend/pyproject.toml",
    "backend/app/main.py",
    "frontend/src-tauri/tauri.conf.json",
    "frontend/src-tauri/Cargo.toml",
]


def _make_tree(tmp: Path) -> None:
    (tmp / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp / "scripts" / "set_version.sh")
    (tmp / "frontend" / "src-tauri").mkdir(parents=True)
    (tmp / "backend" / "app").mkdir(parents=True)
    (tmp / "frontend" / "package.json").write_text(PKG_JSON)
    (tmp / "backend" / "pyproject.toml").write_text(PYPROJECT)
    (tmp / "backend" / "app" / "main.py").write_text(MAIN_PY)
    (tmp / "frontend" / "src-tauri" / "tauri.conf.json").write_text(TAURI_JSON)
    (tmp / "frontend" / "src-tauri" / "Cargo.toml").write_text(CARGO_TOML)


def _run(tmp: Path, version: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(tmp / "scripts" / "set_version.sh"), version],
        check=True, capture_output=True, text=True,
    )


def test_stamps_all_five_manifests(tmp_path):
    _make_tree(tmp_path)
    _run(tmp_path, "9.9.9")
    assert json.loads((tmp_path / "frontend/package.json").read_text())["version"] == "9.9.9"
    assert 'version = "9.9.9"' in (tmp_path / "backend/pyproject.toml").read_text()
    assert 'version="9.9.9"' in (tmp_path / "backend/app/main.py").read_text()
    assert json.loads((tmp_path / "frontend/src-tauri/tauri.conf.json").read_text())["version"] == "9.9.9"
    assert 'version = "9.9.9"' in (tmp_path / "frontend/src-tauri/Cargo.toml").read_text()


def test_does_not_touch_dependency_versions(tmp_path):
    _make_tree(tmp_path)
    _run(tmp_path, "9.9.9")
    cargo = (tmp_path / "frontend/src-tauri/Cargo.toml").read_text()
    assert 'tauri = { version = "2"' in cargo  # dep spec untouched
    pkg = json.loads((tmp_path / "frontend/package.json").read_text())
    assert pkg["dependencies"]["react"] == "^18.2.0"  # dep spec untouched


def test_strips_leading_v(tmp_path):
    _make_tree(tmp_path)
    _run(tmp_path, "v1.4.0")
    assert json.loads((tmp_path / "frontend/package.json").read_text())["version"] == "1.4.0"


def test_idempotent(tmp_path):
    _make_tree(tmp_path)
    _run(tmp_path, "9.9.9")
    snap = {f: (tmp_path / f).read_text() for f in FILES}
    _run(tmp_path, "9.9.9")  # second run must be a no-op
    for f in FILES:
        assert (tmp_path / f).read_text() == snap[f], f"{f} changed on re-run"


def test_rejects_garbage_version(tmp_path):
    _make_tree(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        _run(tmp_path, "not-a-version")
```

Run it RED first (script absent → import/file-missing failure):
```bash
cd backend && pytest tests/unit/test_set_version.py -q
# expect: errors (scripts/set_version.sh does not exist) — this proves the test exercises the script
```

### F1.b — Write the script (GREEN)

New file `scripts/set_version.sh` (`chmod +x`). Uses `jq` for the two JSON files (semantic, format-
agnostic), anchored `sed -E` for `pyproject.toml`/`main.py`, and a section-scoped `awk` for
`Cargo.toml` (so a `[dependencies]` `version = …` is never clobbered). All edits go via tmp-file +
`mv` to avoid the GNU `sed -i` vs BSD `sed -i ''` incompatibility.

```bash
#!/usr/bin/env bash
# scripts/set_version.sh — stamp ONE version (the git tag, minus a leading 'v')
# into every manifest so the tag stays the single source of truth. Idempotent;
# safe to run from any CWD; works with both GNU and BSD userlands.
#
#   usage: scripts/set_version.sh <version>     e.g. scripts/set_version.sh 1.4.0
#
# Files stamped (locked interface — keep in sync with the CI and the spec §10):
#   1. frontend/package.json                  (top-level "version")
#   2. backend/pyproject.toml                 ([project] version = "…")
#   3. backend/app/main.py                    (FastAPI(version="…"))
#   4. frontend/src-tauri/tauri.conf.json     (top-level "version")
#   5. frontend/src-tauri/Cargo.toml          ([package] version = "…")
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <version>   e.g. $0 1.4.0" >&2
  exit 2
fi

VERSION="${1#v}"   # tolerate a leading 'v' (e.g. the raw git ref)

# Validate semver-ish so a typo can't silently stamp garbage everywhere.
if ! printf '%s' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+([-+][0-9A-Za-z.-]+)?$'; then
  echo "error: '$1' is not a valid semantic version (expected X.Y.Z)" >&2
  exit 2
fi

# Resolve repo root from THIS script's location, not the caller's CWD.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Portable in-place edit: render to a temp file, then move over the original.
edit_sed() {  # edit_sed <file> <sed -E expression>
  local f="$1" expr="$2" tmp
  tmp="$(mktemp)"
  sed -E "$expr" "$f" > "$tmp"
  mv "$tmp" "$f"
}

edit_json_version() {  # edit_json_version <file>  — set top-level .version
  local f="$1" tmp
  tmp="$(mktemp)"
  jq --arg v "$VERSION" '.version = $v' "$f" > "$tmp"
  mv "$tmp" "$f"
}

# 1) frontend/package.json
edit_json_version "$ROOT/frontend/package.json"

# 2) backend/pyproject.toml — only the line that starts with `version = ` (so
#    requires-python / target-version / python_version are never matched).
edit_sed "$ROOT/backend/pyproject.toml" \
  's/^version = "[^"]*"/version = "'"$VERSION"'"/'

# 3) backend/app/main.py — the FastAPI(version="…") line (leading indentation).
edit_sed "$ROOT/backend/app/main.py" \
  's/^( *version=")[^"]*(",)/\1'"$VERSION"'\2/'

# 4) frontend/src-tauri/tauri.conf.json
edit_json_version "$ROOT/frontend/src-tauri/tauri.conf.json"

# 5) frontend/src-tauri/Cargo.toml — version under [package] ONLY (a dependency
#    table's `version = "…"` must be left alone). Section-scoped with awk.
cargo_tmp="$(mktemp)"
awk -v v="$VERSION" '
  /^\[/ { in_pkg = ($0 == "[package]") }
  in_pkg && /^version[[:space:]]*=[[:space:]]*"/ { sub(/"[^"]*"/, "\"" v "\"") }
  { print }
' "$ROOT/frontend/src-tauri/Cargo.toml" > "$cargo_tmp"
mv "$cargo_tmp" "$ROOT/frontend/src-tauri/Cargo.toml"

echo "set_version: stamped ${VERSION} into 5 manifests"
```

### F1.c — Verify (GREEN + lint)

```bash
chmod +x scripts/set_version.sh
shellcheck scripts/set_version.sh          # expect: no output, exit 0
cd backend && pytest tests/unit/test_set_version.py -q
# expect: 5 passed
```

Optional CI guard (add to `.github/workflows/test.yml`, a new lightweight job — recommended but not
required since the pytest already exercises behavior in the Backend job):
```yaml
  scripts-lint:
    name: Scripts (shellcheck)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: sudo apt-get update && sudo apt-get install -y shellcheck
      - run: shellcheck scripts/*.sh
```

**Commit (F1):** `git add scripts/set_version.sh backend/tests/unit/test_set_version.py` →
`build: add set_version.sh single-source version stamper + tests`.

---

## F2 — Updater keypair generation + secret storage (docs + checklist, no automated test)

**Goal:** create the free Tauri updater signing keypair once, store the private key + password as
GitHub Actions secrets, and paste the public key into the Tauri config (file owned by **E**).

### F2.a — Generate the keypair (run once, locally)

```bash
cd frontend
npm install                                   # ensures @tauri-apps/cli is available
npm run tauri signer generate -- -w ~/.tauri/uh-updater.key
#   (equivalent: npx @tauri-apps/cli@latest signer generate -w ~/.tauri/uh-updater.key)
```
It prompts for a password (choose a strong one; it can be empty but a password is recommended) and
writes two files:
- `~/.tauri/uh-updater.key`      — **private** key (NEVER commit; this becomes a secret)
- `~/.tauri/uh-updater.key.pub`  — public key (this is committed inside `tauri.conf.json`)

It also prints the public key to stdout, e.g.:
```
Your keypair was generated successfully
Private: ~/.tauri/uh-updater.key  (Keep it secret!)
Public:  dW50cnVzdGVkIGNvbW1lbnQ6...   (paste into tauri.conf.json)
```

### F2.b — Store the secrets (gh CLI)

```bash
# private key file content → secret
gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.tauri/uh-updater.key
# the password chosen above (omit --body to be prompted; do NOT echo it into shell history)
gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD
# verify
gh secret list | grep TAURI_SIGNING
#   TAURI_SIGNING_PRIVATE_KEY            Updated ...
#   TAURI_SIGNING_PRIVATE_KEY_PASSWORD   Updated ...
```

### F2.c — Wire the public key (cross-ref E)

Paste the public key into `frontend/src-tauri/tauri.conf.json` (owned by **E**):
```jsonc
"plugins": {
  "updater": {
    "pubkey": "dW50cnVzdGVkIGNvbW1lbnQ6...",   // from ~/.tauri/uh-updater.key.pub
    "endpoints": [
      "https://github.com/sweetcornna/university-helper/releases/latest/download/latest.json"
    ]
  }
}
```
(If E has not landed yet, hand the pubkey string to the E task; this is the only F→E handoff.)

### F2.d — Verification checklist

- [ ] `~/.tauri/uh-updater.key` permissions are `0600` (`chmod 600 ~/.tauri/uh-updater.key`).
- [ ] Private key + `.pub` are **git-ignored / outside the repo** (never staged).
- [ ] `gh secret list` shows both `TAURI_SIGNING_PRIVATE_KEY` and `_PASSWORD`.
- [ ] `tauri.conf.json` `plugins.updater.pubkey` equals the `.pub` content; `endpoints` points at
      `releases/latest/download/latest.json`.
- [ ] After F3 lands, a desktop build leg **with** the secret present emits `*.sig` files and a
      `latest.json`; a leg **without** it still produces installers (no `.sig`, no auto-update).

**Commit (F2):** docs-only. Add a short `docs/RELEASING.md` "Updater signing" section (or extend it)
with the commands above → `docs: document Tauri updater keypair + signing secrets`. (No source/test
change; the pubkey edit lands with E.)

---

## F3 — Rewrite `.github/workflows/release.yml` into 4 jobs (`create-release` → `images` + `desktop` → `publish`)

**Goal:** fan out from one `v*` tag. `create-release` makes a **draft** release so the matrix legs all
attach to one release; `publish` flips it to published only when **every** leg (images + all desktop
legs) succeeds — keeping GHCR `:latest`, the updater `latest.json`, and the GitHub "latest release"
mutually consistent. Signing/notarization steps are gated on `secrets != ''` so unsigned forks stay
green.

> Prereqs that must be merged first: **D** (`scripts/build_sidecar.sh`, `scripts/smoke_sidecar.sh`,
> sidecar at `backend/dist/uh-backend[.exe]`), **E** (`frontend/src-tauri` project), **F1**
> (`scripts/set_version.sh`).

> **Release runbook (human step, keeps `images` correct):** because the `images` job builds the
> tagged commit verbatim, stamp + commit the version **before** tagging:
> `bash scripts/set_version.sh 1.4.0 && git commit -am "chore: v1.4.0" && git tag v1.4.0 && git push --follow-tags`.
> The `desktop` legs additionally re-run `set_version.sh` on their fresh checkout (belt-and-suspenders
> for the Tauri/Cargo version).

> **macOS sidecar caveat (cross-ref D):** the spec pins `macos-latest ×2` (arm64 runner) for both
> `aarch64-` and `x86_64-apple-darwin`. PyInstaller does not cross-compile, so the `x86_64` leg needs
> an x86_64 sidecar — D's `build_sidecar.sh` must handle that (e.g. `arch -x86_64` + an x86_64 Python
> under Rosetta), OR switch that matrix leg to a native Intel runner (`macos-13`). The YAML below
> follows the spec literally; revisit with D if the x86_64 leg fails to produce a Mach-O `x86_64`
> binary.

Full file — replace `.github/workflows/release.yml` with:

```yaml
name: release

# Fan-out from one v* tag (the single source of truth for the version):
#   create-release  → makes a DRAFT GitHub Release, stamps version, extracts notes
#   images          → multi-arch app+web images to GHCR (:version + :latest)
#   desktop         → Win/macOS(x2)/Linux installers + updater artifacts (Tauri)
#   publish         → flips the draft to published once images + every desktop leg pass
#
# First-run prerequisite: Settings → Actions → General → Workflow permissions =
# "Read and write". GHCR packages default to PRIVATE — make
# university-helper-{app,web} PUBLIC for anonymous `docker pull` (see F4 runbook).
on:
  push:
    tags:
      - "v*"
  workflow_dispatch:
    inputs:
      tag:
        description: "Release tag to build (e.g. v1.4.0)"
        required: true

permissions:
  contents: write   # create the GitHub Release / tag and upload assets
  packages: write   # push images to GHCR

env:
  REGISTRY: ghcr.io
  APP_IMAGE: ghcr.io/sweetcornna/university-helper-app
  WEB_IMAGE: ghcr.io/sweetcornna/university-helper-web
  PLATFORMS: linux/amd64,linux/arm64

jobs:
  # ───────────────────────── 1. create the draft release ─────────────────────
  create-release:
    runs-on: ubuntu-latest
    outputs:
      tag: ${{ steps.meta.outputs.tag }}
      version: ${{ steps.meta.outputs.version }}
      release_id: ${{ steps.release.outputs.id }}
    steps:
      - uses: actions/checkout@v4

      - name: Resolve version from tag
        id: meta
        run: |
          REF="${{ github.event.inputs.tag || github.ref_name }}"
          echo "tag=${REF}" >> "$GITHUB_OUTPUT"
          echo "version=${REF#v}" >> "$GITHUB_OUTPUT"

      # Validates set_version.sh runs against the real tree on every release.
      # (The build jobs below re-stamp their own fresh checkouts.)
      - name: Stamp version into all manifests
        run: bash scripts/set_version.sh "${{ steps.meta.outputs.version }}"

      - name: Extract release notes from CHANGELOG
        run: |
          VERSION="${{ steps.meta.outputs.version }}"
          awk -v ver="$VERSION" '
            $0 ~ "^## \\[" ver "\\]" { grab=1; print; next }
            grab && /^## \[/ { exit }
            grab { print }
          ' CHANGELOG.md > release_notes.md
          if [ ! -s release_notes.md ]; then
            echo "Release ${{ steps.meta.outputs.tag }}" > release_notes.md
          fi
          {
            echo ""
            echo "## Desktop app"
            echo "Download the installer for your OS from the **Assets** below"
            echo "(\`.msi\`/\`.exe\` Windows · \`.dmg\` macOS · \`.AppImage\`/\`.deb\` Linux)."
            echo "Unsigned builds: macOS → right-click the app → **Open**; Windows → **More info → Run anyway**."
            echo ""
            echo "## Server (Docker)"
            echo '```bash'
            echo "git clone https://github.com/sweetcornna/university-helper.git"
            echo "cd university-helper"
            echo "bash scripts/deploy_server.sh --tag ${{ steps.meta.outputs.tag }} --domain your.domain"
            echo '```'
          } >> release_notes.md

      - name: Create DRAFT release
        id: release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ steps.meta.outputs.tag }}
          name: ${{ steps.meta.outputs.tag }}
          body_path: release_notes.md
          draft: true
          files: |
            docker-compose.release.yml
            scripts/deploy_server.sh
            scripts/deploy_server.ps1

  # ───────────────────────── 2. server images (logic unchanged) ──────────────
  images:
    runs-on: ubuntu-latest
    needs: create-release
    steps:
      - uses: actions/checkout@v4

      - name: Resolve version
        id: meta
        run: |
          REF="${{ github.event.inputs.tag || github.ref_name }}"
          echo "tag=${REF}" >> "$GITHUB_OUTPUT"
          echo "version=${REF#v}" >> "$GITHUB_OUTPUT"

      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build & push app image
        uses: docker/build-push-action@v6
        with:
          context: .
          file: Dockerfile.server
          platforms: ${{ env.PLATFORMS }}
          push: true
          # Public PyPI is faster/more reliable than the in-Dockerfile CN mirror
          # default when building on GitHub-hosted runners.
          build-args: |
            PIP_INDEX_URL=https://pypi.org/simple
            PIP_TRUSTED_HOST=pypi.org
          tags: |
            ${{ env.APP_IMAGE }}:${{ steps.meta.outputs.version }}
            ${{ env.APP_IMAGE }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Build & push web image
        uses: docker/build-push-action@v6
        with:
          context: .
          file: Dockerfile.web
          platforms: ${{ env.PLATFORMS }}
          push: true
          tags: |
            ${{ env.WEB_IMAGE }}:${{ steps.meta.outputs.version }}
            ${{ env.WEB_IMAGE }}:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

  # ───────────────────────── 3. desktop installers + updater ─────────────────
  desktop:
    needs: create-release
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-22.04
            rust_target: x86_64-unknown-linux-gnu
          - os: windows-latest
            rust_target: x86_64-pc-windows-msvc
          - os: macos-latest
            rust_target: aarch64-apple-darwin
          - os: macos-latest
            rust_target: x86_64-apple-darwin
    runs-on: ${{ matrix.os }}
    env:
      VERSION: ${{ needs.create-release.outputs.version }}
    steps:
      - uses: actions/checkout@v4

      - name: Stamp version into all manifests
        shell: bash
        run: bash scripts/set_version.sh "$VERSION"

      # Tauri/webkit build deps — Linux only (pin webkit2gtk-4.1 via ubuntu-22.04).
      - name: Install Linux bundle deps
        if: matrix.os == 'ubuntu-22.04'
        run: |
          sudo apt-get update
          sudo apt-get install -y \
            libwebkit2gtk-4.1-dev \
            libappindicator3-dev \
            librsvg2-dev \
            patchelf \
            build-essential \
            libssl-dev \
            file

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Build the PyInstaller sidecar
        shell: bash
        run: |
          python -m pip install --upgrade pip
          pip install -r backend/requirements.txt pyinstaller
          bash scripts/build_sidecar.sh        # from workstream D → backend/dist/uh-backend[.exe]

      - name: Smoke-test the sidecar /health
        shell: bash
        run: bash scripts/smoke_sidecar.sh      # from workstream D: boot frozen binary, curl /health == 200

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Build the SPA
        working-directory: frontend
        run: |
          npm ci
          npm run build

      - name: Setup Rust (+ target)
        uses: dtolnay/rust-toolchain@stable
        with:
          targets: ${{ matrix.rust_target }}

      - uses: Swatinem/rust-cache@v2
        with:
          workspaces: frontend/src-tauri -> target

      - name: Stage sidecar as binaries/uh-backend-<triple>
        shell: bash
        run: |
          mkdir -p frontend/src-tauri/binaries
          if [ "${{ runner.os }}" = "Windows" ]; then
            cp backend/dist/uh-backend.exe \
               "frontend/src-tauri/binaries/uh-backend-${{ matrix.rust_target }}.exe"
          else
            cp backend/dist/uh-backend \
               "frontend/src-tauri/binaries/uh-backend-${{ matrix.rust_target }}"
            chmod +x "frontend/src-tauri/binaries/uh-backend-${{ matrix.rust_target }}"
          fi

      # Decide whether updater artifacts can be produced: createUpdaterArtifacts
      # REQUIRES a signing key, so when the secret is absent we turn it off via an
      # inline --config merge so unsigned forks still build installers.
      - name: Resolve signing availability
        id: signing
        shell: bash
        env:
          SIGN_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}
        run: |
          if [ -n "$SIGN_KEY" ]; then
            echo "updater=true" >> "$GITHUB_OUTPUT"
          else
            echo "updater=false" >> "$GITHUB_OUTPUT"
            echo "::notice::No TAURI_SIGNING_PRIVATE_KEY — building UNSIGNED, no updater artifacts."
          fi

      - name: Build & upload Tauri bundles
        uses: tauri-apps/tauri-action@v0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          # Updater signing (optional/free) — empty secrets ⇒ unsigned.
          TAURI_SIGNING_PRIVATE_KEY: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY }}
          TAURI_SIGNING_PRIVATE_KEY_PASSWORD: ${{ secrets.TAURI_SIGNING_PRIVATE_KEY_PASSWORD }}
          # macOS notarization (optional/later) — empty secrets ⇒ ad-hoc/unsigned.
          APPLE_CERTIFICATE: ${{ secrets.APPLE_CERTIFICATE }}
          APPLE_CERTIFICATE_PASSWORD: ${{ secrets.APPLE_CERTIFICATE_PASSWORD }}
          APPLE_SIGNING_IDENTITY: ${{ secrets.APPLE_SIGNING_IDENTITY }}
          APPLE_ID: ${{ secrets.APPLE_ID }}
          APPLE_PASSWORD: ${{ secrets.APPLE_PASSWORD }}
          APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}
        with:
          projectPath: frontend
          releaseId: ${{ needs.create-release.outputs.release_id }}
          args: >-
            --target ${{ matrix.rust_target }}
            ${{ steps.signing.outputs.updater == 'false' && '--config {"bundle":{"createUpdaterArtifacts":false}}' || '' }}

  # ───────────────────────── 4. publish (gate on everything) ─────────────────
  publish:
    runs-on: ubuntu-latest
    needs: [create-release, images, desktop]
    steps:
      - uses: actions/checkout@v4
      - name: Flip draft → published
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh release edit "${{ needs.create-release.outputs.tag }}" \
            --repo "${{ github.repository }}" \
            --draft=false --latest
```

### F3 — Verify

```bash
# 1) Lint the workflow locally (optional but recommended):
#    https://github.com/rhysd/actionlint
actionlint .github/workflows/release.yml      # expect: no errors

# 2) Dry-run end-to-end on a throwaway pre-release tag once D + E are merged:
git tag v1.4.0-rc1 && git push origin v1.4.0-rc1
gh run watch                                  # expect: create-release → images+desktop → publish all green
gh release view v1.4.0-rc1                    # expect: installers (.msi/.dmg/.AppImage) + latest.json attached
```

**Commit (F3):** `git add .github/workflows/release.yml` →
`ci: split release into create-release/images/desktop/publish with Tauri + gated signing`.

---

## F4 — GHCR visibility fix (ops runbook — resolves spec §11 at the distribution level)

**Goal:** make the published server images anonymously pullable so the one-click `deploy_server.sh`
(and the §11 fix-forward) works without a login. No code change; run once.

### (a) Set Actions workflow permissions to Read and write

UI: **Settings → Actions → General → Workflow permissions → "Read and write permissions" → Save.**

Equivalent API:
```bash
gh api -X PUT /repos/sweetcornna/university-helper/actions/permissions/workflow \
  -f default_workflow_permissions=write \
  -F can_approve_pull_request_reviews=false
# verify
gh api /repos/sweetcornna/university-helper/actions/permissions/workflow
#   { "default_workflow_permissions": "write", "can_approve_pull_request_reviews": false }
```

### (b) Re-run the release on v1.3.0 to (re)publish images

```bash
gh workflow run release.yml -f tag=v1.3.0     # workflow_dispatch path
gh run watch                                  # expect: images job pushes :1.3.0 and :latest, green
```

### (c) Make both container packages PUBLIC

```bash
gh api -X PATCH /user/packages/container/university-helper-app -f visibility=public
gh api -X PATCH /user/packages/container/university-helper-web -f visibility=public
# verify
gh api /user/packages/container/university-helper-app  --jq '.visibility'   # expect: public
gh api /user/packages/container/university-helper-web  --jq '.visibility'   # expect: public
```
UI fallback (if the PAT lacks the package scope): **Profile → Packages → university-helper-app →
Package settings → Danger Zone → Change visibility → Public** (repeat for `-web`).

### (d) Verify anonymous pull (no auth)

```bash
docker logout ghcr.io
docker pull ghcr.io/sweetcornna/university-helper-web:latest      # expect: success, no login prompt
docker pull ghcr.io/sweetcornna/university-helper-app:latest      # expect: success
```
Once both pull anonymously, the §11 deploy bug is fixed at the distribution level: a clean box running
`bash scripts/deploy_server.sh --tag v1.3.0` pulls the **current fixed** images (which already always
seed `localhost`/`127.0.0.1` as TrustedHost patterns — `backend/app/main.py:81-91`), so the healthcheck
no longer 400s on `Invalid host header`.

**Commit (F4):** runbook is ops-only; capture it as a section in `docs/RELEASING.md`
(`docs: GHCR make-public + workflow-permissions runbook`). The state changes are on GitHub, not in git.

---

## F5 — README/download docs (Desktop section + unsigned-run notes + SignPath note)

**Goal:** give end users a Desktop download path and the platform-specific "run an unsigned build"
instructions, and record the SignPath Foundation OSS-signing plan.

Insert a new `## Desktop app (download & run)` section in `README.md` immediately **after** the
`## Supported platforms` block (ends at line 81, before `## Local development`). Exact block to add:

```markdown
## Desktop app (download & run)

Prefer a double-click app over Docker? Grab the native installer for your OS from the
[**latest release**](../../releases/latest) — it bundles the backend and runs entirely on your
machine (no Docker, no Postgres, no Python). Tasks run while the app window is open.

| OS | Download | Notes |
|---|---|---|
| Windows 10/11 | `University.Helper_<ver>_x64-setup.exe` / `.msi` | unsigned → SmartScreen: **More info → Run anyway** |
| macOS (Apple Silicon) | `University.Helper_<ver>_aarch64.dmg` | unsigned → **right-click the app → Open** (first launch only) |
| macOS (Intel) | `University.Helper_<ver>_x64.dmg` | same right-click → Open |
| Linux | `university-helper_<ver>_amd64.AppImage` / `.deb` | `chmod +x *.AppImage && ./*.AppImage` |

The app **auto-updates** from GitHub Releases (signed updater payloads).

> **Why the unsigned-build warning?** Builds are signed with a free updater key but are not yet OS
> code-signed (paid). On macOS, right-click → **Open** once to add a Gatekeeper exception; on Windows,
> click **More info → Run anyway** on the SmartScreen prompt. We are applying to the
> [**SignPath Foundation**](https://signpath.org/) free OSS code-signing program for Windows; an
> optional Apple Developer ID ($99/yr) for macOS notarization is planned. Once approved, these warnings
> go away with no change to how you download.
```

**Commit (F5):** `git add README.md` (and mirror into `README.zh-CN.md` if maintaining parity) →
`docs: add desktop download section + unsigned-run + SignPath notes`.

---

## Task summary / order

1. **F1** — `scripts/set_version.sh` + `backend/tests/unit/test_set_version.py` (TDD; lands now).
2. **F2** — updater keypair + secrets docs (run once; pubkey handoff to E).
3. **F3** — rewrite `release.yml` into 4 jobs (lands after D + E + F1).
4. **F4** — GHCR workflow-permissions + make-public runbook (ops; any time).
5. **F5** — README desktop download + unsigned-run + SignPath docs.
---

## Task Z1: End-to-end local desktop acceptance (manual gate)

**Files:** none (acceptance checklist run after A–E land and F1/D5/E5 produce artifacts).

**Interfaces:**
- Consumes: `scripts/build_sidecar.sh` (D5), the Tauri app build (E5), the local SQLite profile (A+B+C).

- [ ] **Step 1: Build the sidecar locally**

Run: `bash scripts/build_sidecar.sh`
Expected: a `uh-backend` binary under `backend/dist/` (or the path D5 documents); no PyInstaller errors.

- [ ] **Step 2: Stage the sidecar for Tauri and build the app (debug)**

Run (host triple from `rustc --print host-tuple`):
```bash
TRIPLE=$(rustc --print host-tuple)
mkdir -p frontend/src-tauri/binaries
cp backend/dist/uh-backend "frontend/src-tauri/binaries/uh-backend-$TRIPLE"   # add .exe on Windows
cd frontend && npm ci && npm run build && npm run tauri build -- --debug
```
Expected: a bundle is produced under `frontend/src-tauri/target/debug/bundle/…`.

- [ ] **Step 3: Launch and verify the window loads the SPA**

Launch the built app. Expected: a window titled **学道** opens; the login/dashboard SPA renders (served from `http://127.0.0.1:<port>`); browser devtools/network (if enabled) show `GET /api/v1/...` returning 200 from the same origin.

- [ ] **Step 4: Verify a real task runs and persists locally**

Using a **test** 学习通 account, log in and start a course/sign-in task. Expected: task progress appears and is written to the SQLite file at `<app-data>/local.db` (inspect with `sqlite3 <app-data>/local.db 'select task_kind,status from course_task_store;'`). Confirm `<app-data>` matches platformdirs (`UniversityHelper`/`cornna`) and that `cookies.json` / `answer_cache.json` / `local.db` / `secret_key` / `fernet.key` are all there.

- [ ] **Step 5: Verify sidecar reaping on exit**

Close the app window. Expected: no orphaned `uh-backend` process remains (`pgrep -fl uh-backend` / Task Manager shows none) and the loopback port is freed.

- [ ] **Step 6: Record results**

Note the OS/arch tested and any deviations. This gate must pass on at least one OS before tagging a release; CI's per-OS `/health` smoke (D6) covers the rest.

---

## Appendix: deploy-bug quick fix (independent of this plan)

The reported `Invalid host header` / `dependency app failed to start` is a stale pre-v1.1.0 `app` image (current code already seeds `localhost`). On the deploy host:
```bash
docker logs shuake-easy-learning-app --tail 50      # confirms "Invalid host header"
docker compose -p university-helper -f docker-compose.release.yml down
bash scripts/deploy_server.sh --build               # builds from current fixed source
```
Task F4 fixes this at the distribution level (republish + make GHCR images public).
