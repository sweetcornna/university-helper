"""Regression tests for JobProcessor retry-queue accounting (F05).

A chapter that ERRORs (transient) or returns NOT_OPEN with notopen_action=retry
gets re-queued. The unfinished_tasks accounting must stay balanced so that
JobProcessor.run() actually terminates once retried chapters succeed/exhaust.
"""

import threading
from types import SimpleNamespace

from app.services.course.chaoxing import learning
from app.services.course.chaoxing.client import StudyResult
from app.services.course.chaoxing.learning import (
    ChapterResult,
    ChapterTask,
    JobProcessor,
    process_chapter,
)


def _run_with_timeout(processor: JobProcessor, timeout: float = 10.0) -> bool:
    """Run processor.run() in a thread; return True if it finished in time."""
    finished = threading.Event()

    def _target():
        processor.run()
        finished.set()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    return finished.wait(timeout)


def _base_config(**overrides):
    config = {"speed": 1.0, "jobs": 1, "notopen_action": "retry"}
    config.update(overrides)
    return config


def test_run_terminates_after_error_then_success(monkeypatch):
    """A chapter that ERRORs once then SUCCEEDs must let run() return."""
    call_counts: dict[str, int] = {}

    def fake_process_chapter(chaoxing, course, point, speed, config=None):
        title = point["title"]
        call_counts[title] = call_counts.get(title, 0) + 1
        # First chapter errors once, then succeeds on the retry.
        if title == "chapter-error-once" and call_counts[title] == 1:
            return ChapterResult.ERROR
        return ChapterResult.SUCCESS

    monkeypatch.setattr(learning, "process_chapter", fake_process_chapter)

    tasks = [
        ChapterTask(point={"title": "chapter-ok", "has_finished": False}, index=0),
        ChapterTask(point={"title": "chapter-error-once", "has_finished": False}, index=1),
    ]
    processor = JobProcessor(chaoxing=object(), course={"title": "c"}, tasks=tasks, config=_base_config())

    assert _run_with_timeout(
        processor, timeout=10.0
    ), "JobProcessor.run() hung after a chapter retried (unfinished_tasks leak)"
    # The retried chapter must eventually have been processed twice and succeeded.
    assert call_counts["chapter-error-once"] == 2
    assert not processor.failed_tasks


def test_run_terminates_after_not_open_then_open(monkeypatch):
    """A NOT_OPEN chapter (notopen_action=retry) that later opens must let run() return."""
    call_counts: dict[str, int] = {}

    def fake_process_chapter(chaoxing, course, point, speed, config=None):
        title = point["title"]
        call_counts[title] = call_counts.get(title, 0) + 1
        if title == "chapter-notopen" and call_counts[title] < 3:
            return ChapterResult.NOT_OPEN
        return ChapterResult.SUCCESS

    monkeypatch.setattr(learning, "process_chapter", fake_process_chapter)

    tasks = [
        ChapterTask(point={"title": "chapter-notopen", "has_finished": False}, index=0),
    ]
    processor = JobProcessor(chaoxing=object(), course={"title": "c"}, tasks=tasks, config=_base_config())

    assert _run_with_timeout(processor, timeout=10.0), "JobProcessor.run() hung after a NOT_OPEN chapter retried"
    assert call_counts["chapter-notopen"] == 3


def test_run_terminates_on_stop_while_retrying(monkeypatch):
    """Requesting stop while a chapter is looping in the retry pipeline must let run() return."""
    stop_flag = {"stop": False}

    def fake_process_chapter(chaoxing, course, point, speed, config=None):
        # Always error so the task keeps cycling through the retry pipeline,
        # then ask the controller to stop after the first pass.
        stop_flag["stop"] = True
        return ChapterResult.ERROR

    monkeypatch.setattr(learning, "process_chapter", fake_process_chapter)

    tasks = [
        ChapterTask(point={"title": "looping", "has_finished": False}, index=0),
    ]
    config = _base_config(should_stop=lambda: stop_flag["stop"])
    processor = JobProcessor(chaoxing=object(), course={"title": "c"}, tasks=tasks, config=config)

    assert _run_with_timeout(processor, timeout=10.0), "JobProcessor.run() hung after stop requested mid-retry"


def test_run_terminates_when_error_exhausts_retries(monkeypatch):
    """A chapter that always ERRORs must exhaust retries and let run() return."""

    def fake_process_chapter(chaoxing, course, point, speed, config=None):
        return ChapterResult.ERROR

    monkeypatch.setattr(learning, "process_chapter", fake_process_chapter)

    tasks = [
        ChapterTask(point={"title": "always-error", "has_finished": False}, index=0),
    ]
    processor = JobProcessor(chaoxing=object(), course={"title": "c"}, tasks=tasks, config=_base_config())

    assert _run_with_timeout(processor, timeout=15.0), "JobProcessor.run() hung when a chapter exhausted its retries"
    assert len(processor.failed_tasks) == 1


def test_run_processes_chapters_inline_when_worker_thread_cannot_start(monkeypatch):
    """Production thread exhaustion should degrade to inline chapter processing."""
    processed: list[str] = []

    def fake_process_chapter(chaoxing, course, point, speed, config=None):
        del chaoxing, course, speed, config
        processed.append(point["title"])
        return ChapterResult.SUCCESS

    class FailingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(learning, "process_chapter", fake_process_chapter)
    monkeypatch.setattr(learning.threading, "Thread", FailingThread)

    tasks = [
        ChapterTask(point={"title": "chapter-1", "has_finished": False}, index=0),
        ChapterTask(point={"title": "chapter-2", "has_finished": False}, index=1),
    ]
    processor = JobProcessor(chaoxing=object(), course={"title": "c"}, tasks=tasks, config=_base_config(jobs=4))

    processor.run()

    assert processed == ["chapter-1", "chapter-2"]
    assert not processor.failed_tasks


def test_process_chapter_runs_jobs_inline_when_executor_cannot_start(monkeypatch):
    """Chapter task points should still run when ThreadPoolExecutor cannot create workers."""
    processed_jobs: list[str] = []

    class FailingExecutor:
        def __init__(self, *args, **kwargs):
            pass

        def submit(self, *args, **kwargs):
            raise RuntimeError("can't start new thread")

        def shutdown(self, *args, **kwargs):
            pass

    def fake_process_job(chaoxing, course, job, job_info, speed, progress_callback=None, should_stop_callback=None):
        del chaoxing, course, job_info, speed, progress_callback, should_stop_callback
        processed_jobs.append(job["jobid"])
        return StudyResult.SUCCESS

    chaoxing = SimpleNamespace(
        rate_limiter=SimpleNamespace(limit_rate=lambda **kwargs: None),
        get_job_list=lambda course, point: (
            [
                {"jobid": "job-1", "type": "document"},
                {"jobid": "job-2", "type": "read"},
            ],
            {"knowledgeid": "k1"},
        ),
    )

    monkeypatch.setattr(learning, "ThreadPoolExecutor", FailingExecutor)
    monkeypatch.setattr(learning, "process_job", fake_process_job)

    result = process_chapter(
        chaoxing,
        course={"title": "course"},
        point={"title": "chapter", "has_finished": False},
        speed=1.0,
        config={},
    )

    assert result == ChapterResult.SUCCESS
    assert processed_jobs == ["job-1", "job-2"]
