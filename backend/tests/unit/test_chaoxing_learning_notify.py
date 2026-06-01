"""Tests for completion-notification wiring in the learning manager.

notify_config must actually be sent through the notification provider path
(not merely logged), with an SSRF guard mirroring the /notify/test endpoint.
"""
import threading
from unittest import mock

import app.services.course.chaoxing.learning_manager as lm
from app.services.course.chaoxing.learning_manager import ChaoxingLearningManager


def _bare_manager() -> ChaoxingLearningManager:
    m = ChaoxingLearningManager.__new__(ChaoxingLearningManager)
    m._lock = threading.Lock()
    m._tasks = {
        "t1": {
            "task_id": "t1",
            "user_id": "u1",
            "status": "completed",
            "progress": m._default_progress(),
            "logs": [],
            "_log_cursor": 0,
        }
    }
    m._loaded_task_users = set()
    return m


def test_completion_notification_is_sent(monkeypatch):
    m = _bare_manager()
    monkeypatch.setattr(lm.task_store, "upsert_task", lambda *a, **k: None)
    # The SSRF validator does a real DNS lookup (covered by its own tests); here
    # we only exercise the send wiring, so accept the URL.
    monkeypatch.setattr(lm, "validate_notification_url", lambda url: True)

    notifier = mock.Mock()
    factory = mock.Mock()
    factory.create_service.return_value = notifier
    monkeypatch.setattr(lm, "NotificationFactory", factory)

    m._send_completion_notification(
        "t1",
        {"service": "ServerChan", "url": "https://sctapi.example.com/abc.send"},
        "Task completed",
    )

    factory.create_service.assert_called_once()
    config = factory.create_service.call_args.args[0]
    assert config["provider"] == "ServerChan"
    assert config["url"] == "https://sctapi.example.com/abc.send"
    notifier.send.assert_called_once()
    assert "Task completed" in notifier.send.call_args.args[0]


def test_completion_notification_blocks_internal_url(monkeypatch):
    m = _bare_manager()
    monkeypatch.setattr(lm.task_store, "upsert_task", lambda *a, **k: None)

    factory = mock.Mock()
    monkeypatch.setattr(lm, "NotificationFactory", factory)

    m._send_completion_notification(
        "t1",
        {"service": "Bark", "url": "http://127.0.0.1:8000/internal"},
        "Task completed",
    )

    # SSRF guard must prevent any provider construction / send.
    factory.create_service.assert_not_called()


def test_completion_notification_noop_without_config(monkeypatch):
    m = _bare_manager()
    monkeypatch.setattr(lm.task_store, "upsert_task", lambda *a, **k: None)
    factory = mock.Mock()
    monkeypatch.setattr(lm, "NotificationFactory", factory)

    m._send_completion_notification("t1", {}, "Task completed")
    m._send_completion_notification("t1", {"service": "Bark"}, "Task completed")

    factory.create_service.assert_not_called()


def test_completion_notification_send_failure_is_swallowed(monkeypatch):
    m = _bare_manager()
    monkeypatch.setattr(lm.task_store, "upsert_task", lambda *a, **k: None)
    monkeypatch.setattr(lm, "validate_notification_url", lambda url: True)

    notifier = mock.Mock()
    notifier.send.side_effect = RuntimeError("boom")
    factory = mock.Mock()
    factory.create_service.return_value = notifier
    monkeypatch.setattr(lm, "NotificationFactory", factory)

    # Must not raise even when the provider send blows up.
    m._send_completion_notification(
        "t1",
        {"service": "Qmsg", "url": "https://qmsg.example.com/send"},
        "Task completed",
    )
