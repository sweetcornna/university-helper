"""Popup protocol from luoyily/zhihuishu-tool zhs_api.py:525-575.

The tests run our real service/adapter and replace only HTTP. No platform writes
or upstream scripts are executed.
"""

import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.course.zhihuishu.adapter import ZhihuishuAdapter
from app.services.course.zhihuishu.crypto import VIDEO_KEY, Cipher
from app.services.course.zhihuishu.learning import ZhihuishuLearning

POINTER_URL = "https://studyservice-api.zhihuishu.com/gateway/t/v1/popupAnswer/loadVideoPointerInfo"
EXAM_URL = "https://studyservice-api.zhihuishu.com/gateway/t/v1/popupAnswer/lessonPopupExam"
SUBMIT_URL = "https://studyservice-api.zhihuishu.com/gateway/t/v1/popupAnswer/saveLessonPopupExamSaveAnswer"


def _response(payload, status_code=200):
    return SimpleNamespace(status_code=status_code, json=lambda: payload)


def _video(**updates):
    video = {
        "id": "11",
        "title": "Lesson",
        "video_id": 11,
        "video_sec": 10,
        "small_lesson_id": 0,
        "lesson_id": 22,
        "chapter_id": 33,
        "recruit_id": 44,
        "course_id": 55,
        "study_total_time": 0,
        "watch_state": 0,
    }
    video.update(updates)
    return video


def _exam(question_id, correct=("101", "103")):
    return {
        "lessonTestQuestionUseInterfaceDtos": [
            {
                "testQuestion": {
                    "id": int(question_id),
                    "questionOptions": [
                        {"id": 101, "result": "1" if "101" in correct else "0"},
                        {"id": 102, "result": "1" if "102" in correct else "0"},
                        {"id": 103, "result": "1" if "103" in correct else "0"},
                    ],
                }
            }
        ]
    }


class PopupHTTP:
    def __init__(self, points=None):
        self.points = (
            points
            if points is not None
            else [
                {"timeSec": 3, "questionIds": "201,202"},
                {"timeSec": 7, "questionIds": "203"},
            ]
        )
        self.calls = []
        self.submission = {"code": 0, "data": True}
        self.exam_override = None
        self.position = 0
        self.study_total = 0

    def post(self, url, data=None, headers=None, proxies=None, timeout=None):
        payload = json.loads(Cipher(VIDEO_KEY).decrypt(data["secretStr"]))
        self.calls.append((url, payload))
        if "prelearningNote" in url:
            return _response(
                {
                    "code": 0,
                    "data": {
                        "studiedLessonDto": {
                            "id": 99,
                            "learnTimeSec": self.position,
                            "studyTotalTime": self.study_total,
                        }
                    },
                }
            )
        if url == POINTER_URL:
            return _response({"code": 0, "data": {"questionPoint": self.points}})
        if url == EXAM_URL:
            return _response({"code": 0, "data": self.exam_override or _exam(payload["questionIds"])})
        if url == SUBMIT_URL:
            return _response(self.submission)
        if "saveDatabaseIntervalTimeV2" in url:
            return _response({"code": 0})
        raise AssertionError(f"Unexpected URL {url}")


def _learning(monkeypatch, http=None):
    monkeypatch.setattr("app.services.course.zhihuishu.learning.time.sleep", lambda *_: None)
    learning = ZhihuishuLearning({}, uuid="user")
    http = http or PopupHTTP()
    learning.session.post = http.post
    return learning, http


def test_popup_endpoint_payloads_use_video_signing_and_optional_small_lesson(monkeypatch):
    learning, http = _learning(monkeypatch)
    video = _video(small_lesson_id=77)

    points = learning.load_video_pointer_info(video)
    questions = learning.get_popup_exam(video, "201")
    learning.submit_popup_exam(video, "201", "101,103")

    assert points[0]["timeSec"] == 3
    assert questions[0]["testQuestion"]["id"] == 201
    assert [(url, {k: v for k, v in data.items() if k != "dateFormate"}) for url, data in http.calls] == [
        (POINTER_URL, {"lessonId": 22, "recruitId": 44, "courseId": 55, "lessonVideoId": 77}),
        (EXAM_URL, {"lessonId": 22, "questionIds": "201", "lessonVideoId": 77}),
        (
            SUBMIT_URL,
            {
                "courseId": 55,
                "recruitId": 44,
                "testQuestionId": 201,
                "lessonId": 22,
                "lessonVideoId": 77,
                "answer": "101,103",
                "isCurrent": "1",
                "testType": 0,
            },
        ),
    ]


def test_auto_answer_submits_every_question_at_its_checkpoint_before_progress(monkeypatch):
    learning, http = _learning(monkeypatch)
    video = _video()

    assert learning.watch_video(video, speed=2, auto_answer=True) is True

    flow = [(url.rsplit("/", 1)[-1], data.get("testQuestionId")) for url, data in http.calls]
    assert flow == [
        ("prelearningNote", None),
        ("loadVideoPointerInfo", None),
        ("lessonPopupExam", None),
        ("saveLessonPopupExamSaveAnswer", 201),
        ("lessonPopupExam", None),
        ("saveLessonPopupExamSaveAnswer", 202),
        ("saveDatabaseIntervalTimeV2", None),
        ("lessonPopupExam", None),
        ("saveLessonPopupExamSaveAnswer", 203),
        ("saveDatabaseIntervalTimeV2", None),
        ("saveDatabaseIntervalTimeV2", None),
    ]
    assert all("lessonVideoId" not in data for url, data in http.calls if "/popupAnswer/" in url)
    assert video["answered_popup_questions"] == ["201", "202", "203"]
    assert video["study_total_time"] == 10


def test_auto_answer_disabled_never_fetches_or_submits_popups(monkeypatch):
    learning, http = _learning(monkeypatch)

    assert learning.watch_video(_video(), speed=2, auto_answer=False) is True

    assert not any("/popupAnswer/" in url for url, _ in http.calls)


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"code": -1, "data": True}, 200),
        ({"code": 0, "data": False}, 200),
        ({"code": 0, "data": True}, 503),
        ({"data": True}, 200),
        ([], 200),
        ({"code": False, "data": True}, 200),
    ],
)
def test_rejected_or_unacknowledged_popup_submission_fails(payload, status):
    learning = ZhihuishuLearning({})
    learning.session.post = Mock(return_value=_response(payload, status))

    with pytest.raises(ValueError, match="popup"):
        learning.submit_popup_exam(_video(), "201", "101")


def test_missing_correct_option_flags_fails_before_submission(monkeypatch):
    learning, http = _learning(monkeypatch)
    http.exam_override = {
        "lessonTestQuestionUseInterfaceDtos": [
            {
                "testQuestion": {
                    "id": 201,
                    "questionOptions": [{"id": 101}, {"id": 102}],
                }
            }
        ]
    }

    with pytest.raises(Exception, match="correct option"):
        learning.watch_video(_video(), speed=2, auto_answer=True)

    assert not any(url == SUBMIT_URL for url, _ in http.calls)
    assert not any("saveDatabase" in url for url, _ in http.calls)


def test_popup_failure_is_visible_in_adapter_task_and_never_counted_completed(monkeypatch):
    learning, http = _learning(monkeypatch)
    http.submission = {"code": -1, "msg": "rejected"}
    adapter = ZhihuishuAdapter()
    adapter.learning = learning
    adapter.get_videos = lambda _: [_video()]
    finished = threading.Event()
    original = adapter._run_task_loop_guarded

    def worker(task_id):
        try:
            original(task_id)
        finally:
            finished.set()

    monkeypatch.setattr(adapter, "_run_task_loop_guarded", worker)

    result = adapter.start_course("course", speed=2, auto_answer=True)
    assert finished.wait(5)

    progress = adapter.get_progress("course")
    assert progress["status"] == "error"
    assert progress["failed"] == 1
    assert progress["completed"] == 0
    assert progress["percentage"] == 0
    assert "popup" in progress["message"].lower()
    assert "popup" in adapter.get_task(result["task_id"])["videos"][0]["error"].lower()
    assert not any("saveDatabase" in url for url, _ in http.calls)


def test_cancel_during_question_fetch_prevents_answer_and_progress_submission(monkeypatch):
    learning, http = _learning(monkeypatch)
    cancelled = threading.Event()
    original = http.post

    def post(url, **kwargs):
        response = original(url, **kwargs)
        if url == EXAM_URL:
            cancelled.set()
        return response

    learning.session.post = post

    assert learning.watch_video(_video(), speed=2, auto_answer=True, is_cancelled=cancelled.is_set) is False

    assert not any(url == SUBMIT_URL or "saveDatabase" in url for url, _ in http.calls)


def test_pause_after_question_fetch_defers_submission_until_resumed(monkeypatch):
    learning, http = _learning(monkeypatch)
    paused = threading.Event()
    reached_pause = threading.Event()
    resume = threading.Event()
    original = http.post

    def post(url, **kwargs):
        response = original(url, **kwargs)
        if url == EXAM_URL and not reached_pause.is_set():
            paused.set()
            reached_pause.set()
        return response

    def sleep(_):
        if paused.is_set():
            assert resume.wait(5)
            paused.clear()

    learning.session.post = post
    monkeypatch.setattr("app.services.course.zhihuishu.learning.time.sleep", sleep)
    results = []
    errors = []

    def run():
        try:
            results.append(learning.watch_video(_video(), speed=2, auto_answer=True, is_paused=paused.is_set))
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert reached_pause.wait(5)
        assert not any(url == SUBMIT_URL or "saveDatabase" in url for url, _ in http.calls)
    finally:
        resume.set()
        worker.join(5)

    assert not worker.is_alive()
    assert not errors
    assert results == [True]
    assert any(url == SUBMIT_URL for url, _ in http.calls)


def test_cancel_after_last_popup_acknowledgement_stops_progress_write(monkeypatch):
    learning, http = _learning(monkeypatch)
    http.position = 10
    http.points = [{"timeSec": 10, "questionIds": "201"}]
    cancelled = threading.Event()
    original = http.post

    def post(url, **kwargs):
        response = original(url, **kwargs)
        if url == SUBMIT_URL:
            cancelled.set()
        return response

    learning.session.post = post

    assert learning.watch_video(_video(), speed=2, auto_answer=True, is_cancelled=cancelled.is_set) is False

    assert not any("saveDatabase" in url for url, _ in http.calls)


def test_resuming_does_not_reanswer_checkpoints_before_the_playback_position(monkeypatch):
    learning, http = _learning(monkeypatch)
    http.position = 5
    http.study_total = 50

    assert learning.watch_video(_video(), speed=2, auto_answer=True) is True

    assert [data["testQuestionId"] for url, data in http.calls if url == SUBMIT_URL] == [203]


@pytest.mark.parametrize(
    "points",
    [
        [{"questionIds": "201"}],
        [{"timeSec": "NaN", "questionIds": "201"}],
        [{"timeSec": -1, "questionIds": "201"}],
        [{"timeSec": 3}],
        [{"timeSec": 3, "questionIds": "invalid"}],
        {},
        [{"timeSec": 11, "questionIds": "201"}],
    ],
)
def test_malformed_popup_points_fail_instead_of_silently_skipping(monkeypatch, points):
    learning, http = _learning(monkeypatch, PopupHTTP(points))

    with pytest.raises(Exception, match="popup"):
        learning.watch_video(_video(), speed=2, auto_answer=True)

    assert not any(url == SUBMIT_URL or "saveDatabase" in url for url, _ in http.calls)
