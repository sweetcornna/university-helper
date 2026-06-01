"""Unit tests for ZhihuishuAdapter._run_task_loop driving the real study flow.

These tests mock the Zhihuishu HTTP layer (ZhihuishuLearning / ZhihuishuAnswer)
so they assert that the worker loop actually CALLS watch_video / answer_question
and reflects the mocked platform responses in progress -- instead of running a
fake timer that fabricates a 'completed' status.

NOTE: End-to-end verification against the live Zhihuishu platform requires real
credentials, which are not available in this environment. These unit tests pin
the behavioural contract (real method invocation + progress derived from real
responses) at the seam between the adapter and the HTTP services.
"""

import threading
import time

import pytest

from app.services.course.zhihuishu.adapter import ZhihuishuAdapter


class FakeLearning:
    """Stand-in for ZhihuishuLearning that records watch_video calls."""

    def __init__(self, chapters, watch_results=None):
        self._chapters = chapters
        # watch_results: optional mapping video_id -> bool (default True)
        self._watch_results = watch_results or {}
        self.watch_calls = []
        self.lock = threading.Lock()

    def get_video_list(self, course_id):
        return self._chapters

    def watch_video(self, course_id, video_id, duration):
        with self.lock:
            self.watch_calls.append(
                {"course_id": course_id, "video_id": video_id, "duration": duration}
            )
        return self._watch_results.get(str(video_id), True)


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


def _make_adapter(chapters, watch_results=None, ai_enabled=True):
    adapter = ZhihuishuAdapter(ai_config={"enabled": ai_enabled})
    adapter.learning = FakeLearning(chapters, watch_results=watch_results)
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
    chapters = [
        {
            "videoLearningDtos": [
                {"videoId": "v1", "videoName": "Intro", "videoSec": 10},
                {"videoId": "v2", "videoName": "Body", "videoSec": 20},
            ]
        }
    ]
    adapter = _make_adapter(chapters, ai_enabled=False)

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


def test_progress_reflects_failed_watch_response():
    """A False watch_video response must be reflected as a failed video, not faked success."""
    chapters = [
        {
            "videoLearningDtos": [
                {"videoId": "v1", "videoName": "Ok", "videoSec": 5},
                {"videoId": "v2", "videoName": "Fails", "videoSec": 5},
            ]
        }
    ]
    adapter = _make_adapter(chapters, watch_results={"v2": False}, ai_enabled=False)

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
    chapters = [
        {
            "videoLearningDtos": [
                {
                    "videoId": "v1",
                    "videoName": "Has quiz",
                    "videoSec": 5,
                    "questionList": [q1, q2],
                }
            ]
        }
    ]
    adapter = _make_adapter(chapters, ai_enabled=True)

    adapter.start_course("c-3", speed=1.0, auto_answer=True)
    progress = _wait_for_terminal(adapter, "c-3")

    assert progress["status"] == "completed"
    # answer_question must have been invoked for each embedded question.
    answered_titles = [q.get("title") for q in adapter.answer.answer_calls]
    assert answered_titles == ["Q1", "Q2"], answered_titles


def test_loop_skips_answering_when_auto_answer_disabled():
    q1 = {"title": "Q1", "choices": []}
    chapters = [
        {
            "videoLearningDtos": [
                {
                    "videoId": "v1",
                    "videoName": "Has quiz",
                    "videoSec": 5,
                    "questionList": [q1],
                }
            ]
        }
    ]
    adapter = _make_adapter(chapters, ai_enabled=True)

    adapter.start_course("c-4", speed=1.0, auto_answer=False)
    _wait_for_terminal(adapter, "c-4")

    assert adapter.answer.answer_calls == []


def test_cancel_stops_loop_before_remaining_videos():
    # Make watch_video block so we can cancel mid-flight deterministically.
    started = threading.Event()
    release = threading.Event()

    chapters = [
        {
            "videoLearningDtos": [
                {"videoId": "v1", "videoName": "A", "videoSec": 5},
                {"videoId": "v2", "videoName": "B", "videoSec": 5},
            ]
        }
    ]
    adapter = _make_adapter(chapters, ai_enabled=False)

    real_watch = adapter.learning.watch_video

    def blocking_watch(course_id, video_id, duration):
        if video_id == "v1":
            started.set()
            release.wait(timeout=5)
        return real_watch(course_id, video_id, duration)

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
