"""Unit tests for ZhihuishuAdapter._run_task_loop and the ZhihuishuLearning
request protocol.

The adapter tests mock the Zhihuishu HTTP layer (ZhihuishuLearning / ZhihuishuAnswer)
so they assert the worker loop actually CALLS watch_video / answer_question and
reflects the mocked platform responses in progress -- instead of running a fake
timer that fabricates a 'completed' status.

The protocol tests pin the corrected request shapes against the live API
(queryShareCourseInfo pagination payload, videolist endpoint + VIDEO_KEY signing)
without needing real credentials.

NOTE: End-to-end verification against the live Zhihuishu platform requires real
credentials, which are not available in this environment.
"""

import json
import threading
import time

import pytest

import app.services.course.zhihuishu.adapter as adapter_module
from app.services.course.zhihuishu.adapter import ZhihuishuAdapter
from app.services.course.zhihuishu.crypto import HOME_KEY, VIDEO_KEY, Cipher
from app.services.course.zhihuishu.learning import ZhihuishuLearning


def _chapters(*videos, course_id="cc-1", recruit_id="r-1"):
    """Build a realistic videolist ``data`` dict.

    Each entry is ``(video_id, name, sec)`` or ``(video_id, name, sec, questions)``;
    rendered as a single-video lesson (``videoId`` on the lesson, no
    ``videoSmallLessons``) under one chapter.
    """
    lessons = []
    for v in videos:
        vid, name, sec = v[0], v[1], v[2]
        lesson = {"id": f"L{vid}", "name": name, "videoId": vid, "videoSec": sec}
        if len(v) > 3 and v[3]:
            lesson["questionList"] = v[3]
        lessons.append(lesson)
    return {
        "courseId": course_id,
        "recruitId": recruit_id,
        "videoChapterDtos": [{"id": "ch1", "name": "Chapter 1", "videoLessons": lessons}],
    }


class FakeLearning:
    """Stand-in for ZhihuishuLearning that records watch_video calls."""

    def __init__(self, data, watch_results=None):
        self._data = data
        # watch_results: optional mapping video_id -> bool (default True)
        self._watch_results = watch_results or {}
        self.watch_calls = []
        self.lock = threading.Lock()

    def get_video_list(self, rac_id):
        return self._data

    def watch_video(self, video, speed=1.0, is_cancelled=None, is_paused=None):
        # Signature mirrors the real ZhihuishuLearning.watch_video: the adapter now
        # forwards the full video-context dict + speed + pause/cancel checkers.
        with self.lock:
            self.watch_calls.append(
                {
                    "video_id": video.get("video_id"),
                    "duration": video.get("video_sec") if video.get("video_sec") is not None else video.get("duration"),
                    "speed": speed,
                    "is_cancelled": is_cancelled,
                    "is_paused": is_paused,
                }
            )
        return self._watch_results.get(str(video.get("video_id")), True)


class FakeAnswer:
    """Stand-in for ZhihuishuAnswer that records answer_question calls."""

    def __init__(self, ai_enabled=True):
        self.ai_enabled = ai_enabled
        self.use_zhidao_ai = True
        self.stream = True
        self.answer_calls = []
        self.lock = threading.Lock()

    def answer_question(self, question):
        with self.lock:
            self.answer_calls.append(question)
        return "A"


def _make_adapter(data, watch_results=None, ai_enabled=True):
    adapter = ZhihuishuAdapter(ai_config={"enabled": ai_enabled})
    adapter.learning = FakeLearning(data, watch_results=watch_results)
    adapter.answer = FakeAnswer(ai_enabled=ai_enabled)
    return adapter


def _wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _wait_for_terminal(adapter, course_id, timeout=5.0):
    def done():
        progress = adapter.get_progress(course_id)
        return progress.get("status") in {"completed", "cancelled", "error", "idle"}

    assert _wait_until(done, timeout=timeout), "task did not reach terminal state"
    return adapter.get_progress(course_id)


def test_loop_calls_watch_video_for_every_video():
    adapter = _make_adapter(_chapters(("v1", "Intro", 10), ("v2", "Body", 20)), ai_enabled=False)

    result = adapter.start_course("c-1", speed=1.0, auto_answer=False)
    assert result["task_id"]

    progress = _wait_for_terminal(adapter, "c-1")

    # The loop must have actually driven the platform watch_video API per video.
    watched_ids = [c["video_id"] for c in adapter.learning.watch_calls]
    assert watched_ids == ["v1", "v2"], watched_ids
    # Durations must come from the real video metadata, not a fake timer.
    durations = {c["video_id"]: c["duration"] for c in adapter.learning.watch_calls}
    assert durations == {"v1": 10, "v2": 20}

    assert progress["status"] == "completed"
    assert progress["completed"] == 2
    assert progress["total"] == 2
    assert progress["percentage"] == 100.0


def test_start_course_marks_task_error_when_worker_thread_cannot_start(monkeypatch):
    adapter = _make_adapter(_chapters(("v1", "Intro", 10)), ai_enabled=False)

    class FailingThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(adapter_module.threading, "Thread", FailingThread)

    with pytest.raises(RuntimeError, match="cannot start a new background thread"):
        adapter.start_course("c-thread", speed=1.0, auto_answer=False)

    progress = adapter.get_progress("c-thread")
    assert progress["status"] == "error"
    assert "cannot start a new background thread" in progress["message"]


def test_progress_reflects_failed_watch_response():
    """A False watch_video response must be reflected as a failed video, not faked success."""
    adapter = _make_adapter(
        _chapters(("v1", "Ok", 5), ("v2", "Fails", 5)), watch_results={"v2": False}, ai_enabled=False
    )

    adapter.start_course("c-2", speed=1.0, auto_answer=False)
    progress = _wait_for_terminal(adapter, "c-2")

    assert {c["video_id"] for c in adapter.learning.watch_calls} == {"v1", "v2"}
    assert progress["completed"] == 1
    assert progress["failed"] == 1
    # Percentage reflects only genuinely completed videos.
    assert progress["percentage"] == 50.0


def test_loop_answers_questions_when_auto_answer_enabled():
    q1 = {"title": "Q1", "choices": [{"name": "A", "content": "x"}]}
    q2 = {"title": "Q2", "choices": [{"name": "B", "content": "y"}]}
    adapter = _make_adapter(_chapters(("v1", "Has quiz", 5, [q1, q2])), ai_enabled=True)

    adapter.start_course("c-3", speed=1.0, auto_answer=True)
    progress = _wait_for_terminal(adapter, "c-3")

    assert progress["status"] == "completed"
    # answer_question must have been invoked for each embedded question.
    answered_titles = [q.get("title") for q in adapter.answer.answer_calls]
    assert answered_titles == ["Q1", "Q2"], answered_titles


def test_loop_skips_answering_when_auto_answer_disabled():
    q1 = {"title": "Q1", "choices": []}
    adapter = _make_adapter(_chapters(("v1", "Has quiz", 5, [q1])), ai_enabled=True)

    adapter.start_course("c-4", speed=1.0, auto_answer=False)
    _wait_for_terminal(adapter, "c-4")

    assert adapter.answer.answer_calls == []


def test_cancel_stops_loop_before_remaining_videos():
    # Make watch_video block so we can cancel mid-flight deterministically.
    started = threading.Event()
    release = threading.Event()

    adapter = _make_adapter(_chapters(("v1", "A", 5), ("v2", "B", 5)), ai_enabled=False)

    real_watch = adapter.learning.watch_video

    def blocking_watch(video, speed=1.0, is_cancelled=None, is_paused=None):
        if video.get("video_id") == "v1":
            started.set()
            release.wait(timeout=5)
        return real_watch(video, speed=speed, is_cancelled=is_cancelled, is_paused=is_paused)

    adapter.learning.watch_video = blocking_watch

    adapter.start_course("c-5", speed=1.0, auto_answer=False)
    assert started.wait(timeout=5)

    adapter.cancel_task()
    release.set()

    progress = _wait_for_terminal(adapter, "c-5")
    assert progress["status"] == "cancelled"
    # v2 must never be watched because the task was cancelled after v1.
    watched_ids = [c["video_id"] for c in adapter.learning.watch_calls]
    assert "v2" not in watched_ids


def test_watch_video_receives_speed_and_control_callbacks():
    """The adapter must forward speed and working pause/cancel checkers (F-speed/F-pause-cancel)."""
    adapter = _make_adapter(_chapters(("v1", "A", 5)), ai_enabled=False)

    adapter.start_course("c-speed", speed=1.75, auto_answer=False)
    _wait_for_terminal(adapter, "c-speed")

    assert adapter.learning.watch_calls, "watch_video was never called"
    call = adapter.learning.watch_calls[0]
    assert call["speed"] == 1.75
    assert callable(call["is_cancelled"]) and callable(call["is_paused"])
    # The forwarded checkers must reflect live task state, not be no-ops.
    assert call["is_cancelled"]() is False
    assert call["is_paused"]() is False


def test_zero_duration_video_not_faked_complete():
    """A 0/None-duration video must NOT be counted as completed (F-zero-duration).

    Uses the REAL ZhihuishuLearning.watch_video (no watch_video override) to
    exercise the duration guard; get_video_list / get_course_list are stubbed so
    no network call happens.
    """
    data = _chapters(("v0", "NoDur", 0))
    adapter = ZhihuishuAdapter(ai_config={"enabled": False})
    real_learning = ZhihuishuLearning(cookies={}, proxies={})
    real_learning.get_course_list = lambda: []  # avoid network in _resolve_rac_id
    real_learning.get_video_list = lambda rac_id: data
    real_learning.query_study_info = lambda *a, **k: {}  # avoid network in _annotate_watch_state
    adapter.learning = real_learning

    adapter.start_course("c-zero", speed=1.0, auto_answer=False)
    progress = _wait_for_terminal(adapter, "c-zero")

    # Zero-duration video is surfaced as failed, never as fake-completed 100%.
    assert progress["completed"] == 0
    assert progress["failed"] == 1
    assert progress["percentage"] == 0.0


# --------------------------------------------------------------------------- #
# Request-protocol tests (the actual "课程无法加载" fix)
# --------------------------------------------------------------------------- #


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_get_course_list_signs_pagination_payload_for_both_statuses():
    """Course list must POST a HOME_KEY-signed {status,pageNo,pageSize} secretStr for
    BOTH status 0 (进行中) and 1 (已完成) — the old code sent only {dateFormate} for
    status 0, so a finished course never loaded (the real "课程无法加载" cause)."""
    learning = ZhihuishuLearning(cookies={}, proxies={})
    calls = []

    def fake_post(url, data=None, headers=None, proxies=None, timeout=None):
        calls.append({"url": url, "data": data, "headers": headers})
        return _Resp(
            {
                "code": 200,
                "result": {
                    "totalCount": 1,
                    "courseOpenDtos": [{"courseId": "c1", "courseName": "A", "secret": "sec1"}],
                },
            }
        )

    learning.session.post = fake_post
    courses = learning.get_course_list()

    statuses = set()
    for c in calls:
        assert "queryShareCourseInfo" in c["url"]
        obj = json.loads(Cipher(HOME_KEY).decrypt(c["data"]["secretStr"]))
        assert obj["pageNo"] == 1 and obj["pageSize"] == 5
        assert "dateFormate" in obj  # signing layer injects the timestamp into the plaintext
        assert c["data"]["dateFormate"]  # ...and as a sibling top-level form field
        assert c["headers"]["Origin"] == "https://onlineweb.zhihuishu.com"
        statuses.add(obj["status"])
    # Both 进行中 and 已完成 must be queried.
    assert statuses == {0, 1}
    # Same course returned under both statuses is de-duplicated by courseId.
    assert len(courses) == 1
    # secret is normalized to recruitAndCourseId for downstream video calls.
    assert courses[0]["recruitAndCourseId"] == "sec1"


def test_query_study_info_signs_with_video_key():
    """Watch-state lookup must POST a VIDEO_KEY-signed secretStr to queryStuyInfo."""
    learning = ZhihuishuLearning(cookies={}, proxies={}, uuid="u")
    captured = {}

    def fake_post(url, data=None, headers=None, proxies=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        return _Resp({"code": 0, "data": {"lv": {"5": {"studyTotalTime": 100, "watchState": 1}}, "lesson": {}}})

    learning.session.post = fake_post
    info = learning.query_study_info(["L1"], ["5"], "R")

    assert "queryStuyInfo" in captured["url"]
    obj = json.loads(Cipher(VIDEO_KEY).decrypt(captured["data"]["secretStr"]))
    assert obj["recruitId"] == "R" and obj["lessonIds"] == ["L1"] and obj["lessonVideoIds"] == ["5"]
    assert info["lv"]["5"]["watchState"] == 1


def test_watch_video_skips_completed_video_without_network():
    """watchState==1 videos are skipped (counted done) with zero HTTP."""
    learning = ZhihuishuLearning(cookies={}, proxies={})

    def boom(*a, **k):
        raise AssertionError("no HTTP should happen for an already-completed video")

    learning.session.post = boom
    learning.session.get = boom
    video = {
        "video_id": "v", "video_sec": 100, "watch_state": 1, "study_total_time": 100,
        "small_lesson_id": 0, "lesson_id": "L", "chapter_id": "C", "recruit_id": "R", "course_id": "CC",
    }
    assert learning.watch_video(video) is True


def test_watch_video_resumes_from_study_total_time(monkeypatch):
    """Reports must resume from the server's studyTotalTime, never restart at 0
    (else the first report is < recorded time → code -8)."""
    import app.services.course.zhihuishu.learning as learning_mod

    monkeypatch.setattr(learning_mod.time, "sleep", lambda *_: None)
    learning = ZhihuishuLearning(cookies={}, proxies={}, uuid="u")
    learning._learning_token_id = lambda video: "tok"
    reports = []

    def fake_save(video, played, last_submit, watch_point, token_id):
        reports.append({"played": played, "last_submit": last_submit, "token": token_id})
        return 0

    learning._save_progress = fake_save
    video = {
        "video_id": "v", "video_sec": 10, "study_total_time": 4, "watch_state": 0,
        "small_lesson_id": 0, "lesson_id": "L", "chapter_id": "C", "recruit_id": "R", "course_id": "CC",
    }
    assert learning.watch_video(video, speed=2.0) is True
    assert reports, "should have reported at least once"
    assert reports[0]["last_submit"] >= 4  # resumed from prior progress, not 0
    assert all(r["token"] == "tok" for r in reports)


def test_watch_video_treats_code_minus8_as_already_complete(monkeypatch):
    """A -8 ('学习总时长下降了') means the server is already ahead → treat as done, not failed."""
    import app.services.course.zhihuishu.learning as learning_mod

    monkeypatch.setattr(learning_mod.time, "sleep", lambda *_: None)
    learning = ZhihuishuLearning(cookies={}, proxies={}, uuid="u")
    learning._learning_token_id = lambda video: "tok"
    learning._save_progress = lambda *a, **k: -8
    video = {
        "video_id": "v", "video_sec": 10, "study_total_time": 0, "watch_state": 0,
        "small_lesson_id": 0, "lesson_id": "L", "chapter_id": "C", "recruit_id": "R", "course_id": "CC",
    }
    assert learning.watch_video(video, speed=2.0) is True


def test_annotate_watch_state_maps_study_info():
    """Adapter must map lv (by small-lesson id) and lesson (by lesson id) onto videos."""

    class _L:
        def query_study_info(self, lesson_ids, video_ids, recruit_id):
            return {
                "lv": {"sm": {"studyTotalTime": 50, "watchState": 0}},
                "lesson": {"L1": {"studyTotalTime": 99, "watchState": 1}},
            }

    adapter = ZhihuishuAdapter(ai_config={"enabled": False})
    adapter.learning = _L()
    videos = [
        {"small_lesson_id": "sm", "lesson_id": "Lx"},  # matched via lv
        {"small_lesson_id": 0, "lesson_id": "L1"},  # single-video lesson, matched via lesson
    ]
    adapter._annotate_watch_state(videos, {"recruitId": "R"})
    assert videos[0]["study_total_time"] == 50 and videos[0]["watch_state"] == 0
    assert videos[1]["study_total_time"] == 99 and videos[1]["watch_state"] == 1


def test_get_video_list_uses_videolist_endpoint_and_video_key():
    """Chapter list must gologin then POST a VIDEO_KEY-signed secretStr to
    .../learning/videolist and read data.videoChapterDtos."""
    learning = ZhihuishuLearning(cookies={}, proxies={}, uuid="u1")
    calls = []

    def fake_get(url, params=None, proxies=None, timeout=None):
        calls.append(("GET", url))
        return _Resp({})

    def fake_post(url, data=None, headers=None, proxies=None, timeout=None):
        calls.append(("POST", url, data))
        return _Resp({"data": {"courseId": "cc", "recruitId": "rr", "videoChapterDtos": []}})

    learning.session.get = fake_get
    learning.session.post = fake_post

    data = learning.get_video_list("rac1")

    # gologin (cross-site) must happen first
    assert calls[0][0] == "GET" and "gologin" in calls[0][1]
    post = next(c for c in calls if c[0] == "POST")
    assert "videolist" in post[1]
    obj = json.loads(Cipher(VIDEO_KEY).decrypt(post[2]["secretStr"]))
    assert obj["recruitAndCourseId"] == "rac1"
    assert data["courseId"] == "cc"


def test_flatten_videos_parses_nested_small_lessons():
    """videoChapterDtos[].videoLessons[].videoSmallLessons[] must flatten with full context."""
    data = {
        "courseId": "cc",
        "recruitId": "rr",
        "videoChapterDtos": [
            {
                "id": "chap",
                "videoLessons": [
                    {
                        "id": "lesson",
                        "name": "L",
                        "videoSmallLessons": [
                            {"id": "small", "videoId": "vid", "videoSec": 42, "name": "small-v"},
                        ],
                    }
                ],
            }
        ],
    }
    videos = ZhihuishuAdapter._flatten_videos(data, rac_id="rac1")
    assert len(videos) == 1
    v = videos[0]
    assert v["video_id"] == "vid"
    assert v["video_sec"] == 42
    assert v["chapter_id"] == "chap"
    assert v["lesson_id"] == "lesson"
    assert v["small_lesson_id"] == "small"
    assert v["recruit_id"] == "rr"
    assert v["course_id"] == "cc"
    assert v["recruit_and_course_id"] == "rac1"


def test_flatten_videos_single_video_lesson_gets_zero_small_lesson_id():
    data = _chapters(("v1", "Solo", 7))
    videos = ZhihuishuAdapter._flatten_videos(data, rac_id="rac1")
    assert len(videos) == 1
    assert videos[0]["small_lesson_id"] == 0
    assert videos[0]["lesson_id"] == "Lv1"
    assert videos[0]["video_id"] == "v1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
