"""Per-course "study up to chapter X" limits in the Chaoxing learning worker."""

import threading

import pytest

import app.services.course.chaoxing.learning_manager as lm
from app.services.course.chaoxing.learning_manager import ChaoxingLearningManager

COURSE_A = {"courseId": "100", "clazzId": "200", "cpi": "300", "title": "Course A"}
COURSE_B = {"courseId": "101", "clazzId": "201", "cpi": "301", "title": "Course B"}
POINTS = [
    {"id": "p1", "title": "1.1 Intro", "has_finished": True},
    {"id": "p2", "title": "1.2 Basics", "has_finished": False},
    {"id": "p3", "title": "2.1 Advanced", "has_finished": False},
    {"id": "p4", "title": "2.2 Final", "has_finished": False},
]


class FakeChaoxing:
    def login(self, login_with_cookies=False):
        del login_with_cookies
        return {"status": True}

    def get_course_list(self):
        return [dict(COURSE_A), dict(COURSE_B)]

    def get_course_point(self, course_id, clazz_id, cpi):
        del course_id, clazz_id, cpi
        return {"hasLocked": False, "points": [dict(point) for point in POINTS]}


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setattr(lm.task_store, "upsert_task", lambda *args, **kwargs: True)
    monkeypatch.setattr(lm, "init_chaoxing", lambda common, tiku: FakeChaoxing())

    processed: dict[str, list[str]] = {}

    class RecordingProcessor:
        def __init__(self, chaoxing, course, tasks, config):
            del chaoxing, config
            processed[course["courseId"]] = [task.point["id"] for task in tasks]
            self.failed_tasks = []

        def run(self):
            return None

    monkeypatch.setattr(lm, "JobProcessor", RecordingProcessor)

    manager = ChaoxingLearningManager.__new__(ChaoxingLearningManager)
    manager._lock = threading.Lock()
    manager._loaded_task_users = set()
    pause_event = threading.Event()
    pause_event.set()
    manager._tasks = {
        "t1": {
            "task_id": "t1",
            "user_id": "u1",
            "platform": "chaoxing",
            "status": "pending",
            "message": "",
            "current_task": "",
            "progress": manager._default_progress(),
            "logs": [],
            "_log_cursor": 0,
            "_pause_event": pause_event,
            "_stop_event": threading.Event(),
        }
    }

    def run(**payload):
        manager._run_task_worker("t1", "u1", {"username": "demo", "password": "secret", **payload})
        return manager._tasks["t1"], processed

    return run


def _log_messages(task):
    return [entry["message"] for entry in task["logs"]]


def test_limit_stops_the_course_at_the_chosen_chapter(worker):
    task, processed = worker(
        course_ids=["100_200_300", "101_201_301"],
        chapter_limits={"100_200_300": "p2"},
    )

    assert processed == {"100": ["p1", "p2"], "101": ["p1", "p2", "p3", "p4"]}
    assert task["progress"]["total_chapters"] == 6
    assert task["status"] == "completed"
    assert any('up to "1.2 Basics" (2/4 chapters)' in message for message in _log_messages(task))


def test_courses_without_a_limit_study_every_chapter(worker):
    task, processed = worker(course_ids=["100_200_300"])

    assert processed == {"100": ["p1", "p2", "p3", "p4"]}
    assert task["progress"]["total_chapters"] == 4


def test_limit_that_no_longer_exists_skips_the_course_instead_of_studying_all(worker):
    task, processed = worker(
        course_ids=["100_200_300", "101_201_301"],
        chapter_limits={"100_200_300": "gone", "101_201_301": "p3"},
    )

    assert processed == {"101": ["p1", "p2", "p3"]}
    assert task["status"] == "failed"
    assert task["progress"]["failed"] == 1
    assert any("no longer exists in Course A" in message for message in _log_messages(task))


def test_limit_selector_must_match_the_class_it_names(worker):
    _, processed = worker(
        course_ids=["100_200_300"],
        chapter_limits={"100_999": "p1"},
    )

    assert processed == {"100": ["p1", "p2", "p3", "p4"]}


def test_limit_keyed_by_course_id_only_applies_to_that_course(worker):
    _, processed = worker(
        course_ids=["100", "101"],
        chapter_limits={"101": "p1"},
    )

    assert processed == {"100": ["p1", "p2", "p3", "p4"], "101": ["p1"]}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, {}),
        (["100_200_300"], {}),
        ({" 100_200_300 ": " p2 ", "": "p1", "101": "", "102": None}, {"100_200_300": "p2"}),
    ],
)
def test_normalize_chapter_limits_drops_unusable_entries(raw, expected):
    assert lm._normalize_chapter_limits(raw) == expected


def test_most_specific_limit_wins_when_selectors_overlap(worker):
    _, processed = worker(
        course_ids=["100_200_300"],
        chapter_limits={"100": "p1", "100_200_300": "p3"},
    )

    assert processed == {"100": ["p1", "p2", "p3"]}


def test_given_up_chapters_are_explained_in_logs_and_task_failures(monkeypatch, worker):
    from app.services.course.chaoxing.learning import ChapterResult

    class FailingProcessor:
        def __init__(self, chaoxing, course, tasks, config):
            del chaoxing
            self.course = course
            self.tasks = tasks
            self.config = config
            self.failed_tasks = []

        def run(self):
            crashed, locked = self.tasks[1], self.tasks[2]
            crashed.result, crashed.tries = ChapterResult.ERROR, 1
            crashed.error = "ValueError: Invalid Chaoxing task card mArg object"
            self.config["chapter_failure_callback"](self.course, crashed, final=False, max_tries=5)
            crashed.tries = 5
            self.config["chapter_failure_callback"](self.course, crashed, final=True, max_tries=5)
            locked.result, locked.tries = ChapterResult.NOT_OPEN, 5
            self.config["chapter_failure_callback"](self.course, locked, final=True, max_tries=5)
            self.failed_tasks = [crashed, locked]

    monkeypatch.setattr(lm, "JobProcessor", FailingProcessor)

    task, _ = worker(course_ids=["100_200_300"])

    assert task["status"] == "failed"
    failures = task["failures"]
    assert [(f["course"], f["chapter"]) for f in failures] == [("Course A", "1.2 Basics"), ("Course A", "2.1 Advanced")]
    assert "Invalid Chaoxing task card mArg object" in failures[0]["reason"]
    assert failures[0]["hint"]
    assert "没开放" in failures[1]["reason"] and "跳过" in failures[1]["hint"]
    messages = _log_messages(task)
    assert any("1.2 Basics" in m and "正在自动重试" in m for m in messages)
    assert sum("已跳过" in m for m in messages) == 2
