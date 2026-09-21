"""A stored Chaoxing session must let a task start without the password.

Persisting the login is pointless if the worker still demands a password before
it ever reaches the cookie path: `_run_task_worker` used to reject an empty
password outright, which made `common_config["use_cookies"] = True` unreachable
and forced the user to retype their Chaoxing password on every single task.

The username stays mandatory — it is what binds a reused cookie jar to an
account (see cookies.load_session), so dropping it would let a task adopt a
session belonging to a different Chaoxing account.
"""

import threading

import app.services.course.chaoxing.learning_manager as lm
from app.services.course.chaoxing.learning_manager import ChaoxingLearningManager


def _manager_with_task(task_id: str = "t1") -> ChaoxingLearningManager:
    m = ChaoxingLearningManager.__new__(ChaoxingLearningManager)
    m._lock = threading.Lock()
    m._tasks = {
        task_id: {
            "task_id": task_id,
            "user_id": "u1",
            "status": "running",
            "progress": m._default_progress(),
            "logs": [],
            "_log_cursor": 0,
        }
    }
    m._loaded_task_users = set()
    return m


def _stop_after_credential_check(monkeypatch, failures: list):
    """Let the worker run only as far as the credential gate."""
    monkeypatch.setattr(lm.task_store, "upsert_task", lambda *a, **k: None)
    monkeypatch.setattr(
        ChaoxingLearningManager,
        "_fail_task",
        lambda self, task_id, message: failures.append(message),
    )

    # Past the gate the worker builds a real client; stop it there so the test
    # stays offline. The raised error is reported through a different path.
    def _boom(*args, **kwargs):
        raise RuntimeError("reached-client-init")

    monkeypatch.setattr(lm, "init_chaoxing", _boom)


def test_empty_password_is_accepted_when_a_bound_session_exists(monkeypatch):
    failures: list = []
    _stop_after_credential_check(monkeypatch, failures)

    seen: dict = {}

    def _load_session(user_id, expected_username=None):
        seen["user_id"] = user_id
        seen["expected_username"] = expected_username
        return {"username": expected_username, "cookies": {"_uid": "1"}}

    monkeypatch.setattr(lm, "load_session", _load_session)

    m = _manager_with_task()
    m._run_task_worker("t1", "u1", {"username": "student01", "password": "", "course_ids": ["c1"]})

    assert failures != ["Missing username or password"], "a stored session must not be ignored"
    assert not any("重新输入密码" in f for f in failures), failures
    # The lookup must be scoped to both the platform user and the Chaoxing
    # account, otherwise it could adopt another account's jar.
    assert seen == {"user_id": "u1", "expected_username": "student01"}


def test_empty_password_without_a_stored_session_fails_with_guidance(monkeypatch):
    failures: list = []
    _stop_after_credential_check(monkeypatch, failures)
    monkeypatch.setattr(lm, "load_session", lambda user_id, expected_username=None: None)

    m = _manager_with_task()
    m._run_task_worker("t1", "u1", {"username": "student01", "password": "", "course_ids": ["c1"]})

    assert len(failures) == 1
    assert "重新输入密码" in failures[0]


def test_missing_username_still_fails_even_with_a_stored_session(monkeypatch):
    """Without a username there is nothing to bind the jar to."""
    failures: list = []
    _stop_after_credential_check(monkeypatch, failures)
    monkeypatch.setattr(
        lm,
        "load_session",
        lambda user_id, expected_username=None: {"username": "someone", "cookies": {"_uid": "1"}},
    )

    m = _manager_with_task()
    m._run_task_worker("t1", "u1", {"username": "", "password": "", "course_ids": ["c1"]})

    assert failures == ["Missing username or password"]
