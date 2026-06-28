"""Zhihuishu adapter with minimal task orchestration for API polling."""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from .answer import ZhihuishuAnswer
from .auth import ZhihuishuAuth
from .learning import ZhihuishuLearning

logger = logging.getLogger(__name__)
UNEXPECTED_TASK_ERROR_PREFIX = "Unexpected task failure"
THREAD_START_FAILURE_MESSAGE = (
    "Server cannot start a new background thread. Stop existing tasks and retry, "
    "or restart the service if the problem persists."
)


class ZhihuishuAdapter:
    """Zhihuishu adapter with login/course/video/progress controls."""

    def __init__(self, ai_config: dict | None = None, proxies: dict | None = None):
        self.proxies = proxies or {}
        self.ai_config = ai_config or {"enabled": False}
        self._config: dict[str, Any] = {
            "speed": 1.0,
            "auto_answer": True,
            "ai_config": dict(self.ai_config),
            "proxies": dict(self.proxies),
        }
        self.auth = ZhihuishuAuth(proxies=self.proxies)
        self.learning: ZhihuishuLearning | None = None
        self.answer: ZhihuishuAnswer | None = None
        self._task_lock = threading.Lock()
        self._task_state: dict[str, Any] | None = None
        self._tasks: dict[str, dict[str, Any]] = {}

    def login_with_qr(self, qr_callback: Callable[[bytes], None]) -> dict:
        cookies = self.auth.qr_login(qr_callback)
        self._init_services(cookies)
        return {"success": True, "cookies": cookies}

    def login_with_password(self, username: str, password: str) -> dict:
        cookies = self.auth.password_login(username, password)
        self._init_services(cookies)
        return {"success": True, "cookies": cookies}

    def _init_services(self, cookies: dict):
        # uuid（从 CASLOGC cookie 解出）是进度上报 ev 的必需字段，透传给 learning。
        self.learning = ZhihuishuLearning(cookies, self.proxies, uuid=self.auth.uuid)
        self.answer = ZhihuishuAnswer(cookies, self.ai_config, self.proxies)

    @staticmethod
    def _task_payload(task: dict[str, Any], include_videos: bool = False) -> dict[str, Any]:
        payload = {
            "task_id": task.get("task_id"),
            "task_type": task.get("task_type", "course"),
            "course_id": task.get("course_id"),
            "status": task.get("status"),
            "message": task.get("message"),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "total": task.get("total", 0),
            "completed": task.get("completed", 0),
            "failed": task.get("failed", 0),
            "percentage": task.get("percentage", 0.0),
            "current_video": task.get("current_video"),
            "paused": bool(task.get("paused")),
            "cancelled": bool(task.get("cancelled")),
            "speed": task.get("speed", 1.0),
            "auto_answer": bool(task.get("auto_answer", True)),
        }
        if include_videos:
            payload["videos"] = list(task.get("videos", []))
        return payload

    def get_courses(self) -> list[dict]:
        if not self.learning:
            raise Exception("Not logged in")
        return self.learning.get_course_list()

    def get_grouped_courses(self) -> list[dict[str, Any]]:
        courses = self.get_courses()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for course in courses:
            group_key = str(
                course.get("semesterName") or course.get("termName") or course.get("courseTypeName") or "default"
            )
            grouped.setdefault(group_key, []).append(course)

        return [{"group": name, "count": len(items), "courses": items} for name, items in grouped.items()]

    def get_course_detail(self, course_id: str) -> dict[str, Any]:
        target = str(course_id)
        for course in self.get_courses():
            current_id = str(course.get("courseId") or course.get("id") or "")
            if current_id == target:
                return course
        raise Exception("Course not found")

    def _resolve_rac_id(self, course_id: str) -> str:
        """把前端选中的 courseId 映射为视频接口所需的 recruitAndCourseId（= 课程 secret）。

        映射失败（取不到列表/课程不在列表里）时回退用 course_id 本身，保证不致命。
        """
        try:
            course = self.get_course_detail(course_id)
        except Exception:
            return str(course_id)
        return str(course.get("recruitAndCourseId") or course.get("secret") or course_id)

    def get_videos(self, course_id: str) -> list[dict]:
        if not self.learning:
            raise Exception("Not logged in")

        with self._task_lock:
            if self._task_state and self._task_state.get("course_id") == course_id:
                return list(self._task_state.get("videos", []))

        rac_id = self._resolve_rac_id(course_id)
        data = self.learning.get_video_list(rac_id)
        videos = self._flatten_videos(data, rac_id)
        self._annotate_watch_state(videos, data)
        return videos

    def _annotate_watch_state(self, videos: list[dict], data: Any) -> None:
        """给每个视频补上 study_total_time / watch_state，供 watch_video 续播与跳过已完成。

        失败（接口异常 / mock 无该方法）时静默忽略：watch_video 会按未学（从 0 开始）处理。
        """
        if not videos:
            return
        recruit_id = data.get("recruitId") if isinstance(data, dict) else None
        lesson_ids = sorted({v["lesson_id"] for v in videos if v.get("lesson_id")}, key=str)
        video_ids = sorted({v["small_lesson_id"] for v in videos if v.get("small_lesson_id")}, key=str)
        try:
            info = self.learning.query_study_info(lesson_ids, video_ids, recruit_id)
        except Exception:  # noqa: BLE001 - 状态拉取失败不致命
            return
        lv = info.get("lv") or {}
        lesson = info.get("lesson") or {}
        for v in videos:
            state = lv.get(str(v.get("small_lesson_id"))) or lesson.get(str(v.get("lesson_id"))) or {}
            v["study_total_time"] = state.get("studyTotalTime") or 0
            v["watch_state"] = state.get("watchState") or 0

    def start_course(self, course_id: str, speed: float = 1.0, auto_answer: bool = True) -> dict:
        if not self.learning:
            raise Exception("Not logged in")

        videos = self.get_videos(course_id)
        task_id = uuid4().hex
        total = len(videos)
        now = time.time()
        task_state: dict[str, Any] = {
            "task_id": task_id,
            "course_id": course_id,
            "status": "completed" if total == 0 else "running",
            "message": "Task started" if total > 0 else "No videos found",
            "created_at": now,
            "updated_at": now,
            "videos": videos,
            "total": total,
            "completed": 0,
            "failed": 0,
            "percentage": 0.0,
            "current_video": None,
            "estimated_time": None,
            "paused": False,
            "cancelled": False,
            "speed": speed if speed > 0 else 1.0,
            "auto_answer": bool(auto_answer),
            "task_type": "course",
        }

        with self._task_lock:
            self._task_state = task_state
            self._tasks[task_id] = task_state
            self._config["speed"] = float(task_state["speed"])
            self._config["auto_answer"] = bool(task_state["auto_answer"])

        if total > 0:
            try:
                threading.Thread(target=self._run_task_loop_guarded, args=(task_id,), daemon=True).start()
            except RuntimeError as exc:
                self._mark_task_error(task_id, THREAD_START_FAILURE_MESSAGE)
                raise RuntimeError(THREAD_START_FAILURE_MESSAGE) from exc

        return {
            "task_id": task_id,
            "status": task_state["status"],
            "progress": self.get_progress(course_id),
        }

    def get_progress(self, course_id: str) -> dict[str, Any]:
        with self._task_lock:
            task = dict(self._task_state) if self._task_state else None

        if not task or task.get("course_id") != course_id:
            return {
                "status": "idle",
                "message": "No running task",
                "course_id": course_id,
                "total": 0,
                "completed": 0,
                "failed": 0,
                "percentage": 0.0,
                "current_video": None,
                "estimated_time": None,
                "paused": False,
            }

        total = int(task.get("total") or 0)
        completed = int(task.get("completed") or 0)
        speed = float(task.get("speed") or 1.0)
        remaining = max(total - completed, 0)
        eta_seconds = int((remaining * 6) / max(speed, 0.1))

        return {
            "task_id": task.get("task_id"),
            "course_id": task.get("course_id"),
            "status": task.get("status", "running"),
            "message": task.get("message", "ok"),
            "total": total,
            "completed": completed,
            "failed": int(task.get("failed") or 0),
            "percentage": float(task.get("percentage") or 0.0),
            "current_video": task.get("current_video"),
            "estimated_time": f"{eta_seconds}s" if task.get("status") == "running" else None,
            "paused": bool(task.get("paused")),
        }

    def pause_task(self) -> dict[str, Any]:
        with self._task_lock:
            if not self._task_state:
                return {"status": "idle", "message": "No running task"}
            if self._task_state.get("status") in {"completed", "cancelled"}:
                return {"status": self._task_state["status"], "message": "Task already finished"}
            self._task_state["paused"] = True
            self._task_state["status"] = "paused"
            self._task_state["message"] = "Task paused"
            self._task_state["updated_at"] = time.time()
            return {"status": "paused", "message": "Task paused"}

    def resume_task(self) -> dict[str, Any]:
        with self._task_lock:
            if not self._task_state:
                return {"status": "idle", "message": "No running task"}
            if self._task_state.get("status") == "cancelled":
                return {"status": "cancelled", "message": "Task already cancelled"}
            if self._task_state.get("status") == "completed":
                return {"status": "completed", "message": "Task already completed"}
            self._task_state["paused"] = False
            self._task_state["status"] = "running"
            self._task_state["message"] = "Task resumed"
            self._task_state["updated_at"] = time.time()
            return {"status": "running", "message": "Task resumed"}

    def cancel_task(self) -> dict[str, Any]:
        with self._task_lock:
            if not self._task_state:
                return {"status": "idle", "message": "No running task"}
            self._task_state["cancelled"] = True
            self._task_state["paused"] = False
            self._task_state["status"] = "cancelled"
            self._task_state["message"] = "Task cancelled"
            self._task_state["updated_at"] = time.time()
            return {"status": "cancelled", "message": "Task cancelled"}

    def list_tasks(self, task_type: str | None = None, course_id: str | None = None) -> list[dict[str, Any]]:
        with self._task_lock:
            tasks = [self._task_payload(task) for task in self._tasks.values()]

        if task_type:
            tasks = [task for task in tasks if str(task.get("task_type")) == str(task_type)]
        if course_id:
            tasks = [task for task in tasks if str(task.get("course_id")) == str(course_id)]

        return sorted(tasks, key=lambda item: item.get("updated_at") or 0, reverse=True)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return self._task_payload(task, include_videos=True)

    def cancel_task_by_id(self, task_id: str) -> dict[str, Any]:
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return {"status": "idle", "message": "Task not found"}

            task["cancelled"] = True
            task["paused"] = False
            task["status"] = "cancelled"
            task["message"] = "Task cancelled"
            task["updated_at"] = time.time()
            if self._task_state and self._task_state.get("task_id") == task_id:
                self._task_state = task
            return {"status": "cancelled", "message": "Task cancelled", "task_id": task_id}

    def start_course_task(
        self,
        course_id: str,
        speed: float = 1.0,
        auto_answer: bool = True,
        task_type: str = "course",
    ) -> dict[str, Any]:
        result = self.start_course(course_id, speed=speed, auto_answer=auto_answer)
        task_id = str(result.get("task_id") or "")
        if task_id:
            with self._task_lock:
                task = self._tasks.get(task_id)
                if task:
                    task["task_type"] = task_type
                    task["auto_answer"] = bool(auto_answer)
                    task["updated_at"] = time.time()
        return result

    def start_ai_course_task(self, course_id: str, speed: float = 1.0) -> dict[str, Any]:
        with self._task_lock:
            self.ai_config["enabled"] = True
            self._config["ai_config"] = dict(self.ai_config)
            if self.answer is not None:
                self.answer.ai_enabled = True
        return self.start_course_task(course_id, speed=speed, auto_answer=True, task_type="ai-course")

    def get_status(self) -> dict[str, Any]:
        with self._task_lock:
            current_task = dict(self._task_state) if self._task_state else None
            logged_in = self.learning is not None

        payload: dict[str, Any] = {
            "logged_in": logged_in,
            "status": "online" if logged_in else "offline",
            "has_task": bool(current_task),
            "current_task": self._task_payload(current_task) if current_task else None,
        }
        if current_task:
            payload["progress"] = self.get_progress(str(current_task.get("course_id") or ""))
        return payload

    def logout(self) -> dict[str, Any]:
        with self._task_lock:
            if self._task_state:
                self._task_state["cancelled"] = True
                self._task_state["paused"] = False
                self._task_state["status"] = "cancelled"
                self._task_state["message"] = "Task cancelled by logout"
                self._task_state["updated_at"] = time.time()
                self._tasks[self._task_state["task_id"]] = self._task_state
            self.learning = None
            self.answer = None
        return {"status": "success", "message": "Logout successful"}

    def get_config(self) -> dict[str, Any]:
        with self._task_lock:
            config = dict(self._config)
            config["ai_config"] = dict(self.ai_config)
            config["proxies"] = dict(self.proxies)
            return config

    def update_config(self, update_data: dict[str, Any]) -> dict[str, Any]:
        with self._task_lock:
            if "speed" in update_data and update_data.get("speed") is not None:
                speed = float(update_data["speed"])
                self._config["speed"] = speed if speed > 0 else 1.0
            if "auto_answer" in update_data and update_data.get("auto_answer") is not None:
                self._config["auto_answer"] = bool(update_data["auto_answer"])
            if "proxies" in update_data and isinstance(update_data.get("proxies"), dict):
                self.proxies = dict(update_data["proxies"])
                self._config["proxies"] = dict(self.proxies)

            ai_payload = update_data.get("ai_config")
            if ai_payload is None and isinstance(update_data.get("ai"), dict):
                ai_payload = update_data.get("ai")
            if isinstance(ai_payload, dict):
                self.ai_config.update(ai_payload)
            self._config["ai_config"] = dict(self.ai_config)

            if self.answer is not None:
                self.answer.ai_enabled = bool(self.ai_config.get("enabled", False))
                self.answer.use_zhidao_ai = bool(self.ai_config.get("use_zhidao_ai", True))
                self.answer.stream = bool(self.ai_config.get("use_stream", True))

            config = dict(self._config)
            config["ai_config"] = dict(self.ai_config)
            config["proxies"] = dict(self.proxies)
            return config

    def answer_question(self, question: dict) -> str | None:
        if not self.answer:
            raise Exception("Not logged in")
        return self.answer.answer_question(question)

    @staticmethod
    def _extract_questions(item: dict[str, Any]) -> list[dict[str, Any]]:
        """Pull any embedded quiz questions attached to a video DTO.

        Zhihuishu video DTOs may carry per-video questions under one of a few
        keys depending on the endpoint/version. We collect whatever is present
        so the task loop can drive answer.answer_question for them.
        """
        for key in ("questionList", "questions", "quizList", "workList"):
            value = item.get(key)
            if isinstance(value, list) and value:
                return [q for q in value if isinstance(q, dict)]
        return []

    @staticmethod
    def _flatten_videos(data: Any, rac_id: str | None = None) -> list[dict]:
        """把 videolist 的 ``data`` 拍平成任务用的视频列表，并携带上报所需上下文。

        真实结构是 ``videoChapterDtos[].videoLessons[].videoSmallLessons[]``；单视频小节
        （lesson 自带 ``videoId``、无 ``videoSmallLessons``）按一个 small lesson（id=0）处理。
        同时兼容旧/测试结构（章节直接挂 ``videoLearningDtos``/``videoDtos``）。
        """
        if isinstance(data, dict):
            chapters = data.get("videoChapterDtos") or []
            course_id = data.get("courseId")
            recruit_id = data.get("recruitId")
        else:
            chapters = data or []
            course_id = None
            recruit_id = None

        videos: list[dict[str, Any]] = []
        index = 1
        for chapter in chapters:
            chapter_id = chapter.get("id") or chapter.get("chapterId")
            lessons = chapter.get("videoLessons") or chapter.get("videoLearningDtos") or chapter.get("videoDtos") or []
            for lesson in lessons:
                lesson_id = lesson.get("id") or lesson.get("lessonId")
                smalls = lesson.get("videoSmallLessons") or [lesson]
                for small in smalls:
                    is_single = small is lesson
                    video_id = small.get("videoId") or small.get("id")
                    title = (
                        small.get("name")
                        or small.get("videoName")
                        or lesson.get("name")
                        or lesson.get("videoName")
                        or lesson.get("lessonVideoName")
                        or f"Video {index}"
                    )
                    video_sec = small.get("videoSec") or small.get("duration") or 0
                    questions = ZhihuishuAdapter._extract_questions(small)
                    if not questions and not is_single:
                        questions = ZhihuishuAdapter._extract_questions(lesson)
                    videos.append(
                        {
                            "id": str(video_id or index),
                            "title": title,
                            "duration": video_sec,
                            "status": "pending",
                            "progress": 0,
                            "questions": questions,
                            # --- 进度上报上下文 ---
                            "recruit_and_course_id": rac_id,
                            "recruit_id": recruit_id,
                            "course_id": course_id,
                            "chapter_id": chapter_id,
                            "lesson_id": lesson_id,
                            "small_lesson_id": 0 if is_single else small.get("id"),
                            "video_id": video_id,
                            "video_sec": video_sec,
                        }
                    )
                    index += 1
        return videos

    def _is_task_cancelled(self, task_id: str) -> bool:
        """Thread-safe check used by watch_video to abort mid-playback."""
        with self._task_lock:
            task = self._task_state
            return bool(task and task.get("task_id") == task_id and task.get("cancelled"))

    def _is_task_paused(self, task_id: str) -> bool:
        """Thread-safe check used by watch_video to pause mid-playback."""
        with self._task_lock:
            task = self._task_state
            return bool(task and task.get("task_id") == task_id and task.get("paused"))

    def _mark_task_error(self, task_id: str, message: str) -> None:
        with self._task_lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["status"] = "error"
            task["message"] = message
            task["updated_at"] = time.time()
            if self._task_state and self._task_state.get("task_id") == task_id:
                self._task_state = task

    def _run_task_loop_guarded(self, task_id: str) -> None:
        try:
            self._run_task_loop(task_id)
        except Exception as exc:  # pragma: no cover - defensive safety net
            logger.exception("Zhihuishu task crashed: task_id=%s", task_id)
            self._mark_task_error(task_id, f"{UNEXPECTED_TASK_ERROR_PREFIX}: {exc}")

    def _recompute_percentage(self, task: dict[str, Any]) -> None:
        """Set task percentage from real completed-video counts (caller holds lock)."""
        total = int(task.get("total") or 0)
        completed = int(task.get("completed") or 0)
        task["percentage"] = round((completed / total) * 100, 2) if total > 0 else 0.0

    def _run_task_loop(self, task_id: str) -> None:
        """Drive the real Zhihuishu study flow for a started course task.

        For each video the loop calls ``self.learning.watch_video`` (which reports
        watch points to the Zhihuishu study API) and, when auto-answer is enabled,
        ``self.answer.answer_question`` for any quiz questions embedded in the
        video DTO. Progress (completed/failed/percentage/current_video) is derived
        from the real platform responses rather than a fabricated timer. Pause,
        resume, cancel, task-replacement and error handling are preserved.

        End-to-end verification requires live Zhihuishu credentials (unavailable
        here); unit tests in tests/unit/test_zhihuishu_adapter.py mock the HTTP
        layer and assert watch_video/answer_question are actually invoked.
        """
        current_index = 0

        while True:
            # --- Phase 1: under lock, decide what to do next & pick the video ---
            with self._task_lock:
                if not self._task_state or self._task_state.get("task_id") != task_id:
                    return
                task = self._task_state
                videos = task.get("videos", [])

                if task.get("cancelled"):
                    task["status"] = "cancelled"
                    task["message"] = "Task cancelled"
                    task["updated_at"] = time.time()
                    return

                if current_index >= len(videos):
                    task["status"] = "completed"
                    task["message"] = "Task completed"
                    task["current_video"] = None
                    self._recompute_percentage(task)
                    task["updated_at"] = time.time()
                    return

                if task.get("paused"):
                    task["status"] = "paused"
                    task["updated_at"] = time.time()
                    time.sleep(0.3)
                    continue

                current_video = videos[current_index]
                current_video["status"] = "learning"
                current_video["progress"] = 0
                task["current_video"] = current_video.get("title")
                task["status"] = "running"
                task["message"] = "Task is running"
                auto_answer = bool(task.get("auto_answer", True))
                video_id = current_video.get("id")
                questions = list(current_video.get("questions") or [])
                speed = float(task.get("speed") or 1.0)

            # --- Phase 2: blocking platform call OUTSIDE the lock ---
            watch_ok = False
            watch_error: str | None = None
            try:
                if self.learning is None:
                    raise Exception("Not logged in")
                # Pass the full video context dict (recruit/chapter/lesson/video ids +
                # videoSec) so watch_video can sign the real saveDatabaseIntervalTimeV2
                # report, plus speed + pause/cancel checkers for倍速 and mid-playback control.
                watch_ok = bool(
                    self.learning.watch_video(
                        current_video,
                        speed=speed,
                        is_cancelled=lambda: self._is_task_cancelled(task_id),
                        is_paused=lambda: self._is_task_paused(task_id),
                    )
                )
            except Exception as exc:  # noqa: BLE001 - surface as failed video, keep going
                logger.warning(
                    "Zhihuishu watch_video failed: task_id=%s video_id=%s err=%s",
                    task_id,
                    video_id,
                    exc,
                )
                watch_error = str(exc)

            # If the task was cancelled/replaced while watching, stop now.
            with self._task_lock:
                if not self._task_state or self._task_state.get("task_id") != task_id:
                    return
                task = self._task_state
                if task.get("cancelled"):
                    task["status"] = "cancelled"
                    task["message"] = "Task cancelled"
                    task["updated_at"] = time.time()
                    return

            # --- Phase 3: answer embedded questions (outside lock; real HTTP) ---
            if watch_ok and auto_answer and questions and self.answer is not None:
                for question in questions:
                    with self._task_lock:
                        if not self._task_state or self._task_state.get("task_id") != task_id:
                            return
                        if self._task_state.get("cancelled"):
                            break
                    try:
                        computed = self.answer.answer_question(question)
                        # NOTE (audit F-answer): answer_question only COMPUTES an
                        # answer via AI; submitting it to Zhihuishu's QA/exam save
                        # endpoint is NOT yet implemented (endpoint + signing must be
                        # reverse-engineered live). Log the computed result so it is
                        # not silently discarded and the limitation is observable.
                        if computed:
                            logger.info(
                                "Zhihuishu answer computed but NOT submitted " "(submission unimplemented): task_id=%s",
                                task_id,
                            )
                    except Exception as exc:  # noqa: BLE001 - log, do not abort the course
                        logger.warning(
                            "Zhihuishu answer_question failed: task_id=%s err=%s",
                            task_id,
                            exc,
                        )

            # --- Phase 4: record the real result for this video ---
            with self._task_lock:
                if not self._task_state or self._task_state.get("task_id") != task_id:
                    return
                task = self._task_state
                if task.get("cancelled"):
                    task["status"] = "cancelled"
                    task["message"] = "Task cancelled"
                    task["updated_at"] = time.time()
                    return

                task_videos = task.get("videos", [])
                if current_index < len(task_videos):
                    if watch_ok:
                        task_videos[current_index]["status"] = "completed"
                        task_videos[current_index]["progress"] = 100
                    else:
                        task_videos[current_index]["status"] = "failed"
                        if watch_error:
                            task_videos[current_index]["error"] = watch_error

                if watch_ok:
                    task["completed"] = int(task.get("completed") or 0) + 1
                else:
                    task["failed"] = int(task.get("failed") or 0) + 1
                self._recompute_percentage(task)
                task["updated_at"] = time.time()

            current_index += 1
