"""Regression tests for Chaoxing learning worker-count validation."""

from types import SimpleNamespace

import pytest

from app.services.course.chaoxing import learning
from app.services.course.chaoxing.learning import ChapterResult, ChapterTask, JobProcessor


class _OverflowingJobs:
    def __index__(self):
        raise OverflowError("worker count overflow")


def _args(**overrides):
    values = {
        "use_cookies": False,
        "username": None,
        "password": None,
        "list": None,
        "speed": 1.0,
        "jobs": 1,
        "notopen_action": "retry",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("jobs", [0, -1, "0", "-1"])
def test_job_processor_rejects_nonpositive_jobs_before_starting_threads(jobs):
    task = ChapterTask(index=0, point={"title": "chapter", "has_finished": False})
    processor = JobProcessor(
        chaoxing=object(),
        course={"title": "course"},
        tasks=[task],
        config={"speed": 1.0, "jobs": jobs, "notopen_action": "retry"},
    )

    with pytest.raises(ValueError, match="jobs"):
        processor.run()

    assert processor.threads == []
    assert processor.task_queue.unfinished_tasks == 0


@pytest.mark.parametrize(
    "jobs",
    [1.0, 1.5, -1.5, float("nan"), float("inf"), float("-inf"), _OverflowingJobs()],
)
def test_job_processor_rejects_float_jobs_before_starting_threads(jobs):
    processor = JobProcessor(
        chaoxing=object(),
        course={"title": "course"},
        tasks=[ChapterTask(index=0, point={"title": "chapter", "has_finished": False})],
        config={"speed": 1.0, "jobs": jobs, "notopen_action": "retry"},
    )

    with pytest.raises(ValueError, match="jobs"):
        processor.run()

    assert processor.threads == []
    assert processor.task_queue.unfinished_tasks == 0


@pytest.mark.parametrize("jobs", [1, "1"])
def test_job_processor_accepts_one_worker(monkeypatch, jobs):
    monkeypatch.setattr(learning, "process_chapter", lambda *_args, **_kwargs: ChapterResult.SUCCESS)
    task = ChapterTask(index=0, point={"title": "chapter", "has_finished": False})
    processor = JobProcessor(
        chaoxing=object(),
        course={"title": "course"},
        tasks=[task],
        config={"speed": 1.0, "jobs": jobs, "notopen_action": "retry"},
    )

    processor.run()

    assert task.result == ChapterResult.SUCCESS
    assert processor.threads
    assert all(not thread.is_alive() for thread in processor.threads)


@pytest.mark.parametrize("jobs", [0, -1])
def test_cli_rejects_nonpositive_jobs(monkeypatch, jobs):
    monkeypatch.setattr(learning.sys, "argv", ["learning.py", "--jobs", str(jobs)])

    with pytest.raises(SystemExit) as exc_info:
        learning.parse_args()

    assert exc_info.value.code == 2


@pytest.mark.parametrize("jobs", [0, -1])
def test_file_config_rejects_nonpositive_jobs(tmp_path, jobs):
    config_path = tmp_path / "config.ini"
    config_path.write_text(f"[common]\njobs = {jobs}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="jobs"):
        learning.load_config_from_file(config_path)


def test_file_config_accepts_one_worker(tmp_path):
    config_path = tmp_path / "config.ini"
    config_path.write_text("[common]\njobs = 1\n", encoding="utf-8")

    common_config, _, _ = learning.load_config_from_file(config_path)

    assert common_config["jobs"] == 1


@pytest.mark.parametrize(
    "jobs",
    [0, -1, 1.0, 1.5, -1.5, float("nan"), float("inf"), float("-inf"), _OverflowingJobs()],
)
def test_build_config_rejects_invalid_jobs(jobs):
    with pytest.raises(ValueError, match="jobs"):
        learning.build_config_from_args(_args(jobs=jobs))


@pytest.mark.parametrize("jobs", [1, "1"])
def test_build_config_accepts_one_worker(jobs):
    common_config, _, _ = learning.build_config_from_args(_args(jobs=jobs))

    assert common_config["jobs"] == 1
