import pytest

from app.api.v1 import course as course_api


@pytest.fixture
def isolated_course_tasks(monkeypatch):
    monkeypatch.setattr(course_api, "_qr_sessions", {})
    monkeypatch.setattr(course_api, "_user_adapters", {})
    tasks = {}
    monkeypatch.setattr(course_api, "_course_tasks", tasks)
    return tasks


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "error", None])
def test_cleanup_removes_expired_terminal_tasks(isolated_course_tasks, monkeypatch, status):
    now = 1_000.0
    monkeypatch.setattr(course_api.time, "time", lambda: now)
    isolated_course_tasks["expired"] = {
        "status": status,
        "updated_at": now - course_api._COURSE_TASK_TTL_SECONDS - 1,
    }

    course_api.cleanup_expired_entries()

    assert "expired" not in isolated_course_tasks


def test_cleanup_preserves_running_task(isolated_course_tasks, monkeypatch):
    now = 1_000.0
    monkeypatch.setattr(course_api.time, "time", lambda: now)
    isolated_course_tasks["running"] = {
        "status": "running",
        "updated_at": now - course_api._COURSE_TASK_TTL_SECONDS - 1,
    }

    course_api.cleanup_expired_entries()

    assert "running" in isolated_course_tasks


def test_cleanup_preserves_recent_error_task(isolated_course_tasks, monkeypatch):
    now = 1_000.0
    monkeypatch.setattr(course_api.time, "time", lambda: now)
    isolated_course_tasks["new-error"] = {"status": "error", "updated_at": now}

    course_api.cleanup_expired_entries()

    assert "new-error" in isolated_course_tasks
