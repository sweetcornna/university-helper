"""Zhihuishu "study up to chapter X" (end_chapter_id) support."""

import threading
import time

import pytest

from app.services.course.zhihuishu.adapter import (
    CHAPTER_NOT_FOUND_DETAIL,
    ZhihuishuAdapter,
    ZhihuishuChapterNotFoundError,
)


def _course_data():
    def lesson(video_id, sec=5):
        return {"id": f"L{video_id}", "name": f"Lesson {video_id}", "videoId": video_id, "videoSec": sec}

    return {
        "courseId": "cc",
        "recruitId": "rr",
        "videoChapterDtos": [
            {"id": "ch1", "name": "第一章 绪论", "videoLessons": [lesson("v1"), lesson("v2")]},
            {"id": "ch2", "name": "第二章 基础", "videoLessons": [lesson("v3")]},
            {"id": "ch3", "name": "第三章 进阶", "videoLessons": [lesson("v4"), lesson("v5")]},
        ],
    }


class FakeLearning:
    def __init__(self, data):
        self._data = data
        self.watched = []
        self.video_list_calls = 0
        self.lock = threading.Lock()

    def get_video_list(self, rac_id):
        del rac_id
        with self.lock:
            self.video_list_calls += 1
        return self._data

    def watch_video(self, video, speed=1.0, is_cancelled=None, is_paused=None):
        del speed, is_cancelled, is_paused
        with self.lock:
            self.watched.append(video["video_id"])
        return True


def _adapter():
    adapter = ZhihuishuAdapter(ai_config={"enabled": False})
    adapter.learning = FakeLearning(_course_data())
    return adapter


def _wait_for_terminal(adapter, course_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        progress = adapter.get_progress(course_id)
        if progress["status"] in {"completed", "cancelled", "error"}:
            return progress
        time.sleep(0.02)
    raise AssertionError("task did not finish")


def test_flattened_videos_carry_their_chapter_title():
    videos = ZhihuishuAdapter._flatten_videos(_course_data(), rac_id="rac")

    assert [(v["chapter_id"], v["chapter_title"]) for v in videos] == [
        ("ch1", "第一章 绪论"),
        ("ch1", "第一章 绪论"),
        ("ch2", "第二章 基础"),
        ("ch3", "第三章 进阶"),
        ("ch3", "第三章 进阶"),
    ]


def test_end_chapter_stops_after_its_last_video():
    adapter = _adapter()

    result = adapter.start_course("c-1", auto_answer=False, end_chapter_id="ch2")
    progress = _wait_for_terminal(adapter, "c-1")

    assert adapter.learning.watched == ["v1", "v2", "v3"]
    assert progress["status"] == "completed"
    assert progress["total"] == 3
    assert adapter.get_task(result["task_id"])["end_chapter_id"] == "ch2"


def test_without_end_chapter_the_whole_course_is_studied():
    adapter = _adapter()

    adapter.start_course("c-1", auto_answer=False)
    _wait_for_terminal(adapter, "c-1")

    assert adapter.learning.watched == ["v1", "v2", "v3", "v4", "v5"]


def test_unknown_end_chapter_is_rejected_without_starting_a_task():
    adapter = _adapter()

    with pytest.raises(ZhihuishuChapterNotFoundError) as exc_info:
        adapter.start_course("c-1", auto_answer=False, end_chapter_id="gone")

    assert exc_info.value.detail == CHAPTER_NOT_FOUND_DETAIL
    assert adapter._tasks == {}
    assert adapter.learning.watched == []


def test_ai_course_task_forwards_the_end_chapter():
    adapter = _adapter()

    adapter.start_ai_course_task("c-1", end_chapter_id="ch1")
    _wait_for_terminal(adapter, "c-1")

    assert adapter.learning.watched == ["v1", "v2"]


def test_video_list_after_a_partial_task_shows_the_whole_course_again():
    adapter = _adapter()
    adapter.start_course("c-1", auto_answer=False, end_chapter_id="ch1")
    _wait_for_terminal(adapter, "c-1")

    videos = adapter.get_videos("c-1")

    assert [v["video_id"] for v in videos] == ["v1", "v2", "v3", "v4", "v5"]
    # A later task can therefore pick a later chapter.
    adapter.start_course("c-1", auto_answer=False, end_chapter_id="ch3")
    progress = _wait_for_terminal(adapter, "c-1")
    assert progress["total"] == 5


def test_video_list_during_a_running_task_is_the_task_list():
    adapter = _adapter()
    gate = threading.Event()
    original_watch = adapter.learning.watch_video

    def blocking_watch(video, **kwargs):
        gate.wait(timeout=5)
        return original_watch(video, **kwargs)

    adapter.learning.watch_video = blocking_watch
    adapter.start_course("c-1", auto_answer=False, end_chapter_id="ch1")
    try:
        calls_before = adapter.learning.video_list_calls
        videos = adapter.get_videos("c-1")
        assert [v["video_id"] for v in videos] == ["v1", "v2"]
        assert adapter.learning.video_list_calls == calls_before
    finally:
        gate.set()
    _wait_for_terminal(adapter, "c-1")


def test_watched_videos_are_listed_as_completed():
    adapter = _adapter()

    def query_study_info(lesson_ids, video_ids, recruit_id):
        del lesson_ids, video_ids, recruit_id
        return {"lesson": {"Lv1": {"watchState": 1, "studyTotalTime": 5}}}

    adapter.learning.query_study_info = query_study_info

    statuses = {v["video_id"]: v["status"] for v in adapter.get_videos("c-1")}

    assert statuses["v1"] == "completed"
    assert statuses["v2"] == "pending"


def test_unreadable_watch_state_does_not_break_the_video_list():
    adapter = _adapter()

    def query_study_info(lesson_ids, video_ids, recruit_id):
        del lesson_ids, video_ids, recruit_id
        return {"lesson": {"Lv1": {"watchState": "done"}}}

    adapter.learning.query_study_info = query_study_info

    videos = adapter.get_videos("c-1")

    assert len(videos) == 5
    assert videos[0]["status"] == "pending"


def test_rejected_ai_start_leaves_ai_answering_as_it_was():
    adapter = _adapter()
    assert adapter.ai_config.get("enabled") is False

    with pytest.raises(ZhihuishuChapterNotFoundError):
        adapter.start_ai_course_task("c-1", end_chapter_id="gone")

    assert adapter.ai_config["enabled"] is False
    assert adapter.get_config()["ai_config"]["enabled"] is False
