"""Sign-in must not demand a password when a bound session already exists.

The reported bug: log in on 泛雅, switch to 签到, and the page asks for the
password again. Two independent causes, both covered here:

* every sign-in route required ``password`` at the schema layer, so the
  passwordless path could never be reached; and
* ``sign_once`` / ``sign_class_once`` / ``_run_task_worker`` called
  ``self.login(...)`` unconditionally, doing a full password login per action.

``_resolve_client`` is the single place that decides between "re-authenticate"
and "reuse the stored session". The account binding it enforces is the security
property that matters: a jar for account A must never authenticate an action
requested for account B.
"""

import json
import types

import pytest
import requests

import app.services.course.chaoxing.cookies as cookies_mod
import app.services.course.chaoxing.signin as signin_mod
import app.services.course.task_store as task_store_mod
from app.services.course.chaoxing.cookies import save_session
from app.services.course.chaoxing.signin import ChaoxingSigninManager

SESSION_LOST_HINT = "重新输入密码"


class FakeTaskBackend:
    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}

    def ensure_tables(self) -> None:
        pass

    def upsert_task(self, task_kind, payload):
        self.rows[(task_kind, str(payload.get("task_id")))] = json.loads(json.dumps(payload, default=str))

    def get_task(self, task_kind, task_id, user_id=None):
        row = self.rows.get((task_kind, str(task_id)))
        return dict(row) if row else None

    def list_tasks(self, task_kind, user_id=None, limit=50):
        return []

    def append_history(self, history_kind, user_id, record, max_records=500):
        pass

    def list_history(self, history_kind, user_id=None, limit=500):
        return []


@pytest.fixture
def store(monkeypatch, tmp_path):
    backend = FakeTaskBackend()
    monkeypatch.setattr(task_store_mod, "get_storage", lambda: types.SimpleNamespace(tasks=backend))
    monkeypatch.setattr(cookies_mod, "COOKIES_DIR", tmp_path)
    monkeypatch.setattr(cookies_mod, "COOKIES_FILE", tmp_path / "cookies.json")
    return backend


class FakeSigninClient:
    """Offline stand-in for ChaoxingSigninClient."""

    def __init__(self):
        self.session = requests.Session()
        self.username = ""
        self.account_name = ""
        self.logins: list[tuple[str, str]] = []
        self.tasks = [{"courseName": "人工智能概论", "type": "normal"}]

    def login(self, username, password):
        self.logins.append((username, password))
        self.username = username
        self.session.cookies.set("_uid", "999")
        return {"status": True, "message": "ok", "data": {}}

    def get_active_tasks(self, **kwargs):
        return list(self.tasks)

    def sign_task(self, task, **kwargs):
        return {"status": True, "message": "签到成功", "data": {}}


@pytest.fixture
def manager(store, monkeypatch):
    monkeypatch.setattr(signin_mod, "validate_session_cookies", lambda cookies: True)
    monkeypatch.setattr(signin_mod, "ChaoxingSigninClient", FakeSigninClient)
    return ChaoxingSigninManager()


def _cache_client(manager, user_id, username):
    """Put a client in the in-memory cache, as a prior login would."""
    client = FakeSigninClient()
    client.username = username
    manager._clients[user_id] = client
    return client


# ---------------------------------------------------------------------------
# _resolve_client
# ---------------------------------------------------------------------------


def test_password_takes_priority_and_reauthenticates(manager):
    client, error = manager._resolve_client("u1", "student01", "pw")

    assert error == {}
    assert client.logins == [("student01", "pw")]


def test_absent_password_reuses_the_bound_session_without_a_login(manager):
    _cache_client(manager, "u1", "student01")
    save_session("u1", "student01", {"_uid": "999"})

    client, error = manager._resolve_client("u1", "student01", "")

    assert error == {}
    assert client.logins == [], "a stored session must not trigger a password login"


def test_absent_password_without_a_session_asks_for_the_password(manager):
    client, error = manager._resolve_client("u1", "student01", "")

    assert client is None
    assert SESSION_LOST_HINT in error["message"]


def test_absent_password_refuses_a_session_bound_to_another_account(manager):
    """Regression: this is the account-binding guarantee, not a nicety."""
    _cache_client(manager, "u1", "accountA")
    save_session("u1", "accountA", {"_uid": "AAA"})

    client, error = manager._resolve_client("u1", "accountB", "")

    assert client is None
    assert SESSION_LOST_HINT in error["message"]


def test_cached_client_for_another_account_is_refused(manager):
    """The in-memory cache is keyed by platform user, so identity is rechecked."""
    save_session("u1", "accountB", {"_uid": "BBB"})
    _cache_client(manager, "u1", "accountA")

    client, error = manager._resolve_client("u1", "accountB", "")

    assert client is None
    assert SESSION_LOST_HINT in error["message"]


def test_missing_username_is_refused_even_with_a_stored_session(manager):
    """Nothing to bind the jar to, so it must never be adopted."""
    _cache_client(manager, "u1", "student01")
    save_session("u1", "student01", {"_uid": "999"})

    client, error = manager._resolve_client("u1", "", "")

    assert client is None
    assert error["status"] is False


def test_a_failed_password_login_is_reported_unchanged(manager, monkeypatch):
    class FailingClient(FakeSigninClient):
        def login(self, username, password):
            self.logins.append((username, password))
            return {"status": False, "message": "密码错误"}

    monkeypatch.setattr(signin_mod, "ChaoxingSigninClient", FailingClient)

    client, error = manager._resolve_client("u1", "student01", "wrong")

    assert client is None
    assert error["message"] == "密码错误"


# ---------------------------------------------------------------------------
# The actions that used to force a password
# ---------------------------------------------------------------------------


def test_sign_once_succeeds_without_a_password(manager):
    save_session("u1", "student01", {"_uid": "999"})

    result = manager.sign_once("u1", "student01", "", sign_type="normal")

    assert result["status"] is True
    assert result["message"] == "签到成功"


def test_sign_once_still_works_with_a_password(manager):
    result = manager.sign_once("u1", "student01", "pw", sign_type="normal")

    assert result["status"] is True
    assert manager._clients["u1"].logins == [("student01", "pw")]


def test_sign_once_without_a_password_or_session_fails_with_guidance(manager):
    result = manager.sign_once("u1", "student01", "", sign_type="normal")

    assert result["status"] is False
    assert SESSION_LOST_HINT in result["message"]
    assert manager._clients == {}


def test_sign_class_once_succeeds_without_a_password(manager):
    save_session("u1", "student01", {"_uid": "999"})

    result = manager.sign_class_once("u1", "student01", "", class_id="c1", sign_type="normal")

    assert result["status"] is True


def test_sign_class_once_still_requires_a_class_id(manager):
    save_session("u1", "student01", {"_uid": "999"})

    result = manager.sign_class_once("u1", "student01", "", class_id="")

    assert result["status"] is False


def test_task_worker_runs_without_a_password(manager, monkeypatch):
    """The background sign-in task must take the same passwordless path."""
    save_session("u1", "student01", {"_uid": "999"})
    monkeypatch.setattr(signin_mod, "task_store", types.SimpleNamespace(upsert_task=lambda *a, **k: None))

    from uuid import uuid4

    task_id = uuid4().hex
    manager._tasks[task_id] = {
        "task_id": task_id,
        "user_id": "u1",
        "status": "running",
        "message": "",
        "progress": {"total": 0, "completed": 0, "failed": 0, "current": 0},
        "logs": [],
        "_log_cursor": 0,
    }

    manager._run_task_worker(task_id, "u1", {"username": "student01", "password": "", "sign_type": "normal"})

    task = manager._tasks[task_id]
    assert task["status"] == "completed", task.get("message")
    assert not any(SESSION_LOST_HINT in str(log.get("message")) for log in task["logs"])


def test_task_worker_without_a_session_fails_with_guidance(manager, monkeypatch):
    monkeypatch.setattr(signin_mod, "task_store", types.SimpleNamespace(upsert_task=lambda *a, **k: None))

    from uuid import uuid4

    task_id = uuid4().hex
    manager._tasks[task_id] = {
        "task_id": task_id,
        "user_id": "u1",
        "status": "running",
        "message": "",
        "progress": {"total": 0, "completed": 0, "failed": 0, "current": 0},
        "logs": [],
        "_log_cursor": 0,
    }

    manager._run_task_worker(task_id, "u1", {"username": "student01", "password": "", "sign_type": "normal"})

    task = manager._tasks[task_id]
    assert task["status"] == "error"
    assert SESSION_LOST_HINT in task["message"]
