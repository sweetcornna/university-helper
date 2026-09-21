"""Regression tests for JobProcessor's per-run thread lifecycle."""

import threading

import pytest

from app.services.course.chaoxing import learning
from app.services.course.chaoxing.learning import ChapterResult, ChapterTask, JobProcessor


def _config(**overrides):
    config = {"speed": 1.0, "jobs": 2, "notopen_action": "retry"}
    config.update(overrides)
    return config


def _processor(tasks=None, **config_overrides):
    if tasks is None:
        tasks = []
    return JobProcessor(object(), {"title": "course"}, tasks, _config(**config_overrides))


def _assert_run_threads_stopped(processor):
    assert processor.threads
    assert all(not thread.is_alive() for thread in processor.threads)
    assert processor.task_queue.unfinished_tasks == 0
    assert processor.retry_queue.unfinished_tasks == 0
    assert processor._pending_retries == 0


def test_empty_run_stops_workers_and_retry_thread():
    processor = _processor()

    processor.run()

    _assert_run_threads_stopped(processor)


def test_success_and_retry_runs_leave_no_threads(monkeypatch):
    calls = {"retry": 0}

    def process_chapter(_chaoxing, _course, point, _speed, _config=None):
        del _chaoxing, _course, _speed, _config
        if point["title"] == "retry" and calls["retry"] == 0:
            calls["retry"] += 1
            return ChapterResult.ERROR
        if point["title"] == "retry":
            calls["retry"] += 1
        return ChapterResult.SUCCESS

    monkeypatch.setattr(learning, "process_chapter", process_chapter)
    processor = _processor(
        [
            ChapterTask(index=0, point={"title": "success", "has_finished": False}),
            ChapterTask(index=1, point={"title": "retry", "has_finished": False}),
        ],
        jobs=2,
    )

    processor.run()

    assert calls["retry"] == 2
    assert not processor.failed_tasks
    _assert_run_threads_stopped(processor)


def test_consecutive_empty_runs_do_not_accumulate_threads():
    processor = _processor()

    for _ in range(8):
        processor.run()
        _assert_run_threads_stopped(processor)


def test_worker_exception_is_observed_and_threads_are_joined(monkeypatch):
    processor = _processor()

    def fail_worker(_stop_event):
        raise RuntimeError("worker failed")

    monkeypatch.setattr(processor, "worker_thread", fail_worker)

    with pytest.raises(RuntimeError, match="worker failed"):
        processor.run()

    _assert_run_threads_stopped(processor)


def test_retry_exception_is_observed_and_threads_are_joined(monkeypatch):
    processor = _processor()

    def fail_retry(_stop_event):
        raise RuntimeError("retry worker failed")

    monkeypatch.setattr(processor, "retry_thread", fail_retry)

    with pytest.raises(RuntimeError, match="retry worker failed"):
        processor.run()

    _assert_run_threads_stopped(processor)


def test_controller_error_survives_cleanup_error_and_polls_inflight_worker(monkeypatch):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    errors = []
    drain_calls = 0
    join_polls = 0

    def process_chapter(_chaoxing, _course, _point, _speed, _config=None):
        started.set()
        release.wait()
        return ChapterResult.SUCCESS

    def fail_controller(_stop_event):
        assert started.wait(timeout=1)
        raise ValueError("controller failed")

    def run_processor():
        try:
            processor.run()
        except BaseException as exc:  # pragma: no cover - assertion below reports it
            errors.append(exc)
        finally:
            finished.set()

    monkeypatch.setattr(learning, "process_chapter", process_chapter)
    processor = _processor(
        [ChapterTask(index=0, point={"title": "in-flight", "has_finished": False})],
        jobs=1,
    )
    processor._JOIN_POLL_INTERVAL = 0.02
    original_drain = processor._drain_pending_tasks
    original_join = threading.Thread.join

    def flaky_drain():
        nonlocal drain_calls
        drain_calls += 1
        if drain_calls == 1:
            raise RuntimeError("first drain failed")
        original_drain()

    def counted_join(thread, timeout=None):
        nonlocal join_polls
        if thread in processor.threads:
            join_polls += 1
            if join_polls == 1:
                raise RuntimeError("first join failed")
            if join_polls == 3:
                release.set()
        return original_join(thread, timeout=timeout)

    monkeypatch.setattr(processor, "_promote_retry_once", fail_controller)
    monkeypatch.setattr(processor, "_drain_pending_tasks", flaky_drain)
    monkeypatch.setattr(threading.Thread, "join", counted_join)
    run_thread = threading.Thread(target=run_processor, daemon=True)
    run_thread.start()

    assert started.wait(timeout=1)
    assert not finished.wait(timeout=0.01)
    assert finished.wait(timeout=2)
    run_thread.join(timeout=1)

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert str(errors[0]) == "controller failed"
    assert drain_calls == 2
    assert join_polls >= 3
    _assert_run_threads_stopped(processor)


def test_cleanup_propagates_first_error_after_best_effort_shutdown(monkeypatch):
    processor = _processor()
    drain_calls = 0

    def fail_drain_twice():
        nonlocal drain_calls
        drain_calls += 1
        if drain_calls == 1:
            raise RuntimeError("first cleanup failed")
        raise ValueError("final cleanup failed")

    monkeypatch.setattr(processor, "_drain_pending_tasks", fail_drain_twice)

    with pytest.raises(RuntimeError, match="first cleanup failed"):
        processor.run()

    assert drain_calls == 2
    _assert_run_threads_stopped(processor)


def test_retry_stop_callback_can_reenter_drain_without_deadlock(monkeypatch):
    processor = _processor()
    task = ChapterTask(index=0, point={"title": "retry", "has_finished": False})
    processor.retry_queue.put(task)
    processor._pending_retries = 1
    callback_calls = 0
    reentered = threading.Event()

    def reentrant_should_stop(_config):
        nonlocal callback_calls
        callback_calls += 1
        if callback_calls == 1:
            return False
        processor._drain_pending_tasks()
        reentered.set()
        return True

    monkeypatch.setattr(learning, "should_stop", reentrant_should_stop)
    retry_worker = threading.Thread(target=processor.retry_thread, args=(threading.Event(),), daemon=True)
    processor.threads = [retry_worker]
    retry_worker.start()

    assert reentered.wait(timeout=1)
    retry_worker.join(timeout=1)

    assert not retry_worker.is_alive()
    assert callback_calls == 2
    _assert_run_threads_stopped(processor)


def test_base_exception_balances_task_done_and_allows_second_run(monkeypatch):
    class FatalChapterError(BaseException):
        pass

    calls = 0

    def process_chapter(_chaoxing, _course, _point, _speed, _config=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FatalChapterError("chapter aborted")
        return ChapterResult.SUCCESS

    monkeypatch.setattr(learning, "process_chapter", process_chapter)
    processor = _processor(
        [ChapterTask(index=0, point={"title": "fatal-once", "has_finished": False})],
        jobs=1,
    )

    with pytest.raises(FatalChapterError, match="chapter aborted"):
        processor.run()

    _assert_run_threads_stopped(processor)
    assert processor.task_queue.unfinished_tasks == 0

    processor.run()

    assert calls == 2
    _assert_run_threads_stopped(processor)
