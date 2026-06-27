# A6 Report — Refactor `task_store.py` to delegate persistence

## What changed

### `backend/app/services/course/task_store.py` (full rewrite)
- Removed: `from psycopg2.extras import Json`, `from app.db.session import get_db_session`, all raw SQL, `_normalize_json`, `_parse_datetime`, `_datetime_to_iso`, `threading.Lock`, `_initialized` flag, `__init__`.
- Added: `from app.storage.factory import get_storage`.
- Kept verbatim: `_SENSITIVE_FIELDS`, `_SENSITIVE_CONTAINERS`, `_encrypt_sensitive`, `_decrypt_sensitive`, `task_store = TaskStore()` singleton.
- Every `TaskStore` method now delegates to `get_storage().tasks.<method>` with crypto applied at the boundary:
  - **writes** (`upsert_task`, `append_history`): `_encrypt_sensitive(payload)` before delegation; early-return guards on empty/invalid input remain.
  - **reads** (`get_task`, `list_tasks`, `list_history`): `_decrypt_sensitive(item)` applied to each result from the adapter.
  - `ensure_tables`: delegates directly.

### `backend/tests/unit/test_task_store.py` (partial rewrite — top section only)
- **Removed** 3 SQL-level tests (`test_task_store_list_tasks_*`, `test_task_store_get_task_*`, `test_task_store_upsert_task_*`) that monkeypatched `task_store_module.get_db_session`. Those SQL behaviors are now covered by `tests/unit/test_postgres_storage.py` (A3).
- **Added** 4 delegation+crypto tests as specified in the brief:
  1. `test_upsert_encrypts_sensitive_before_delegating` — verifies delegation and that sensitive key reaches storage
  2. `test_get_decrypts_storage_result` — verifies decrypt passthrough on read
  3. `test_list_tasks_and_history_delegate_and_decrypt` — verifies both list methods delegate with correct args
  4. `test_upsert_invalid_input_does_not_delegate` — verifies early-return guards at task_store level
- **Kept verbatim** 4 `test_signin_manager_*` tests (they monkeypatch `signin_module.task_store.<method>` and are unaffected by the refactor).

## Crypto + delegation wiring

```
caller → TaskStore.upsert_task(kind, state)
       → _encrypt_sensitive(state)           ← plaintext→ciphertext here
       → get_storage().tasks.upsert_task(kind, encrypted_state)
                                              ← adapter normalizes JSON, stores ciphertext

get_storage().tasks.get_task(kind, id, uid)  ← adapter returns ciphertext in payload
       → _decrypt_sensitive(item)            ← ciphertext→plaintext here
       → caller receives plaintext dict
```

The `_normalize_json` step (json round-trip) moves into the adapter; since sensitive values are strings, encryption is idempotent with respect to the json round-trip, preserving byte-for-byte stored equivalence.

## Test results

| Suite | RED (before impl) | GREEN (after impl) |
|---|---|---|
| `tests/unit/test_task_store.py` | 4 FAIL / 4 PASS | 8/8 PASS |
| Affected suite (task_store + postgres_storage + learning_persist + notify) | — | 24/24 PASS |
| Full suite `python -m pytest -q` | — | 304 passed, 4 failed (pre-existing perf), 2 errors (pre-existing integration) |

## Tests changed and why

The 3 SQL-level tests were removed because they monkeypatched `task_store_module.get_db_session` — a symbol that no longer exists in the refactored task_store. Their SQL behavior is fully covered by `test_postgres_storage.py` (A3 deliverable). The signin manager tests were kept byte-for-byte unchanged.

## Concerns

None. The public API surface is identical; all callers (signin.py, learning_manager.py, course.py) are unaffected. The crypto contract is preserved: task_store owns encrypt-on-write and decrypt-on-read; the storage adapters are crypto-free.
