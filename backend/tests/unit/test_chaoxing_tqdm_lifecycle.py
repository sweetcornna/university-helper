"""Regression tests for process_course's temporary tqdm customizations."""

import pytest

from app.services.course.chaoxing import learning


def _course():
    return {"title": "course", "courseId": "course-id", "clazzId": "class-id", "cpi": "cpi"}


class _Chaoxing:
    def get_course_point(self, course_id, clazz_id, cpi):
        assert (course_id, clazz_id, cpi) == ("course-id", "class-id", "cpi")
        return {"points": [{"title": "point"}]}


class _SuccessfulProcessor:
    def __init__(self, *args):
        self.args = args

    def run(self):
        return None


@pytest.fixture
def original_tqdm_state():
    format_sizeof = learning.tqdm.format_sizeof
    lock = learning.tqdm.get_lock()
    try:
        yield format_sizeof, lock
    finally:
        learning.tqdm.format_sizeof = format_sizeof
        learning.tqdm.set_lock(lock)


def _assert_tqdm_state(format_sizeof, lock):
    assert learning.tqdm.format_sizeof is format_sizeof
    assert learning.tqdm.get_lock() is lock


def test_process_course_restores_tqdm_state_after_success(monkeypatch, original_tqdm_state):
    old_format_sizeof, old_lock = original_tqdm_state
    monkeypatch.setattr(learning, "JobProcessor", _SuccessfulProcessor)

    learning.process_course(_Chaoxing(), _course(), {"speed": 1.0, "jobs": 1, "notopen_action": "retry"})

    _assert_tqdm_state(old_format_sizeof, old_lock)


def test_process_course_restores_tqdm_state_and_propagates_base_exception(monkeypatch, original_tqdm_state):
    old_format_sizeof, old_lock = original_tqdm_state
    failure = KeyboardInterrupt("sentinel failure")

    class FailingProcessor:
        def __init__(self, *args):
            self.args = args

        def run(self):
            raise failure

    monkeypatch.setattr(learning, "JobProcessor", FailingProcessor)

    with pytest.raises(KeyboardInterrupt) as exc_info:
        learning.process_course(_Chaoxing(), _course(), {"speed": 1.0, "jobs": 1, "notopen_action": "retry"})

    assert exc_info.value is failure
    assert str(exc_info.value) == "sentinel failure"
    _assert_tqdm_state(old_format_sizeof, old_lock)
