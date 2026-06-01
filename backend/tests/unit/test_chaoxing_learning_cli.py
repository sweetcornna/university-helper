"""Regression tests for the standalone CLI main() (F25).

main() must not reference an undefined name 'Notification' (NameError on every
run) and should wire notifications through the imported NotificationFactory.
"""
from unittest import mock

import app.services.course.chaoxing.learning as learning


def test_main_does_not_raise_nameerror_for_notification(monkeypatch):
    """main() must build the notifier via the imported factory, not undefined Notification()."""
    sent: list[str] = []

    class _FakeNotifier:
        def send(self, message):
            sent.append(message)

    fake_chaoxing = mock.Mock()
    fake_chaoxing.login.return_value = {"status": True, "msg": "ok"}
    fake_chaoxing.get_course_list.return_value = []

    monkeypatch.setattr(
        learning,
        "init_config",
        lambda: ({"speed": 1.0, "use_cookies": False}, {}, {"provider": "X"}),
    )
    monkeypatch.setattr(learning, "init_chaoxing", lambda common, tiku: fake_chaoxing)
    monkeypatch.setattr(learning, "filter_courses", lambda all_course, course_list: [])

    factory_mock = mock.Mock()
    factory_mock.create_service.return_value = _FakeNotifier()
    monkeypatch.setattr(learning, "NotificationFactory", factory_mock)

    # Must not raise NameError: name 'Notification' is not defined.
    learning.main()

    # The notifier was constructed via the imported factory (with the real
    # notification config) and used to report completion.
    assert factory_mock.create_service.called
    assert factory_mock.create_service.call_args_list[-1].args[0] == {"provider": "X"}
    assert any("所有课程学习任务已完成" in msg for msg in sent)


def test_main_notifier_used_in_error_path(monkeypatch):
    """An error after setup must be reportable via the notifier without UnboundLocalError."""
    sent: list[str] = []

    class _FakeNotifier:
        def send(self, message):
            sent.append(message)

    fake_chaoxing = mock.Mock()
    fake_chaoxing.login.return_value = {"status": False, "msg": "bad creds"}

    monkeypatch.setattr(
        learning,
        "init_config",
        lambda: ({"speed": 1.0, "use_cookies": False}, {}, {}),
    )
    monkeypatch.setattr(learning, "init_chaoxing", lambda common, tiku: fake_chaoxing)

    factory_mock = mock.Mock()
    factory_mock.create_service.return_value = _FakeNotifier()
    monkeypatch.setattr(learning, "NotificationFactory", factory_mock)

    # LoginError is raised then re-raised; the error notification path must run.
    try:
        learning.main()
    except Exception:
        pass

    assert any("出现错误" in msg for msg in sent)
