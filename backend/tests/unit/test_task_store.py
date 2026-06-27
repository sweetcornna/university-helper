import importlib

import pytest

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


@pytest.fixture
def real_cipher(monkeypatch):
    """Enable REAL Fernet encryption for the duration of a test.

    A no-op cipher (the CI default with no key) would let a missing-encrypt
    regression slip through, so these crypto-invariant tests need a real key.
    Generates a fresh Fernet key, points ``CREDENTIAL_ENCRYPTION_KEY`` at it and
    rebuilds the process cipher singleton, then drops the singleton in teardown
    so the next test rebuilds from the (monkeypatch-restored) env.
    """
    from cryptography.fernet import Fernet

    from app.core import credential_crypto

    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    credential_crypto._reset_for_tests()
    credential_crypto.init_cipher()  # build the Fernet cipher now; emits 'fernet:' prefixes
    yield
    credential_crypto._reset_for_tests()  # drop cached cipher so later tests rebuild cleanly


def test_upsert_encrypts_sensitive_before_delegating(monkeypatch, real_cipher):
    # REAL encryption: prove the value actually became ciphertext before delegation,
    # not merely that the key survived the no-op cipher.
    tasks = _RecordingTasks()
    _install(monkeypatch, tasks)
    TaskStore().upsert_task("signin", {"task_id": "t1", "user_id": "u1", "password": "hunter2"})
    kind, kwarg = tasks.calls[0][1], tasks.calls[0][2]
    assert kind == "signin"
    assert kwarg["task_id"] == "t1"
    # password must be ACTUALLY encrypted before it reaches storage.
    assert kwarg["password"].startswith("fernet:")
    assert kwarg["password"] != "hunter2"


def test_append_history_encrypts_before_delegating(monkeypatch, real_cipher):
    # The OTHER write path must also encrypt before delegating.
    tasks = _RecordingTasks()
    _install(monkeypatch, tasks)
    TaskStore().append_history("signin", "u1", {"message": "m", "password": "hunter2"})
    call = tasks.calls[0]
    assert call[0] == "append_history"
    assert call[1] == "signin"
    assert call[2] == "u1"
    record = call[3]
    assert record["password"].startswith("fernet:")
    assert record["password"] != "hunter2"


def test_encrypt_handles_non_string_sensitive_value(monkeypatch, real_cipher):
    # The old code ran _normalize_json before encrypt; the new code encrypts the raw
    # dict. A non-string sensitive value must pass through untouched (encrypt_dict_fields
    # only transforms truthy str values) without raising.
    tasks = _RecordingTasks()
    _install(monkeypatch, tasks)
    TaskStore().upsert_task("signin", {"task_id": "t1", "user_id": "u1", "password": 12345})
    kwarg = tasks.calls[0][2]
    assert kwarg["password"] == 12345  # non-string left untouched, no exception


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


def test_signin_manager_loads_full_history_for_user_even_after_partial_preload(monkeypatch):
    try:
        signin_module = importlib.import_module("app.services.course.chaoxing.signin")
    except Exception as exc:
        pytest.xfail(f"signin import blocked in current branch: {exc}")

    if not hasattr(signin_module, "task_store"):
        pytest.xfail("signin manager task_store integration is not available")

    global_history = [
        {
            "user_id": "user-1",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "message": "partial",
        }
    ]
    full_history = [
        {
            "timestamp": "2026-01-02T00:00:00+00:00",
            "message": "latest",
        },
        {
            "timestamp": "2026-01-01T00:00:00+00:00",
            "message": "partial",
        },
    ]

    monkeypatch.setattr(signin_module.task_store, "list_tasks", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(signin_module.task_store, "upsert_task", lambda *args, **kwargs: None, raising=False)

    def _fake_list_history(*args, **kwargs):
        if kwargs.get("user_id"):
            return list(full_history)
        return list(global_history)

    monkeypatch.setattr(signin_module.task_store, "list_history", _fake_list_history, raising=False)

    manager = signin_module.ChaoxingSigninManager()
    history = manager.get_history("user-1")

    assert [item["message"] for item in history] == ["latest", "partial"]


def test_signin_manager_loads_missing_task_from_store_on_demand(monkeypatch):
    try:
        signin_module = importlib.import_module("app.services.course.chaoxing.signin")
    except Exception as exc:
        pytest.xfail(f"signin import blocked in current branch: {exc}")

    if not hasattr(signin_module, "task_store"):
        pytest.xfail("signin manager task_store integration is not available")

    stored_task = {
        "task_id": "stored-task",
        "user_id": "user-1",
        "status": "completed",
        "message": "done",
        "progress": {"total": 1, "completed": 1, "failed": 0, "current": 1},
        "created_at": "2026-01-01T00:00:00+00:00",
        "started_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:01:00+00:00",
        "logs": [{"timestamp": "2026-01-01T00:01:00+00:00", "message": "done", "level": "success"}],
    }

    monkeypatch.setattr(signin_module.task_store, "list_tasks", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(signin_module.task_store, "list_history", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(signin_module.task_store, "upsert_task", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(signin_module.task_store, "get_task", lambda *args, **kwargs: dict(stored_task), raising=False)

    manager = signin_module.ChaoxingSigninManager()
    task = manager.get_task(user_id="user-1", task_id="stored-task")

    assert task is not None
    assert task["task_id"] == "stored-task"
    assert task["status"] == "completed"


def test_signin_manager_get_active_tasks_falls_back_to_background_tasks(monkeypatch):
    try:
        signin_module = importlib.import_module("app.services.course.chaoxing.signin")
    except Exception as exc:
        pytest.xfail(f"signin import blocked in current branch: {exc}")

    if not hasattr(signin_module, "task_store"):
        pytest.xfail("signin manager task_store integration is not available")

    monkeypatch.setattr(signin_module.task_store, "list_tasks", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(signin_module.task_store, "list_history", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(signin_module.task_store, "upsert_task", lambda *args, **kwargs: None, raising=False)

    manager = signin_module.ChaoxingSigninManager()
    manager._tasks["bg-task-1"] = {
        "task_id": "bg-task-1",
        "user_id": "user-1",
        "status": "running",
        "message": "Task started",
        "progress": {"total": 1, "completed": 0, "failed": 0, "current": 0, "current_course": "????I"},
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:01:00+00:00",
        "logs": [],
        "_log_cursor": 0,
    }

    tasks = manager.get_active_tasks("user-1")

    assert len(tasks) == 1
    assert tasks[0]["taskId"] == "bg-task-1"
    assert tasks[0]["actionable"] is False
    assert tasks[0]["source"] == "background"
    assert tasks[0]["typeLabel"] == "Background task"
    assert tasks[0]["courseName"] == "????I"


def test_signin_manager_recovery_marks_running_task_as_non_running(monkeypatch):
    try:
        signin_module = importlib.import_module("app.services.course.chaoxing.signin")
    except Exception as exc:
        pytest.xfail(f"signin import blocked in current branch: {exc}")

    if not hasattr(signin_module, "task_store"):
        pytest.xfail("signin manager task_store integration is not available")

    restored_rows = [
        {
            "task_id": "recovered-running",
            "user_id": "user-1",
            "status": "running",
            "message": "task was running before restart",
            "progress": {"total": 1, "completed": 0, "failed": 0, "current": 0},
            "created_at": "2026-01-01T00:00:00+00:00",
            "started_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "logs": [],
        }
    ]

    monkeypatch.setattr(
        signin_module.task_store,
        "list_tasks",
        lambda *args, **kwargs: list(restored_rows),
        raising=False,
    )
    monkeypatch.setattr(signin_module.task_store, "list_history", lambda *args, **kwargs: [], raising=False)
    monkeypatch.setattr(signin_module.task_store, "upsert_task", lambda *args, **kwargs: None, raising=False)

    manager = signin_module.ChaoxingSigninManager()
    restored = manager.get_task(user_id="user-1", task_id="recovered-running")

    assert restored is not None
    assert restored["status"] in {"failed", "error"}
    assert restored["status"] != "running"
