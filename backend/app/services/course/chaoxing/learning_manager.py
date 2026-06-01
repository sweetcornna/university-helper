import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4
import logging

from app.services.notification import NotificationFactory
from app.services.notification.providers import validate_notification_url

from ..task_store import task_store
from .learning import ChapterTask, JobProcessor, init_chaoxing
from .payload_mapper import normalize_tiku_config

logger = logging.getLogger(__name__)
LEARNING_TASK_KIND = "chaoxing_learning"
INTERRUPTED_STATUSES = {"running", "pending", "paused", "cancelling"}
RESTART_INTERRUPTED_MESSAGE = "Task interrupted due to service restart"
UNEXPECTED_WORKER_ERROR_PREFIX = "Unexpected task failure"
USER_TASK_LOAD_LIMIT = 2000
# Minimum seconds between throttled (high-frequency progress) main-DB upserts of
# a single task's payload. Video progress callbacks fire ~1/sec per task and
# each upsert re-serializes the whole growing logs+progress payload as JSONB, so
# coalesce them. Status changes / logs / terminal writes bypass this throttle
# (force=True) so final state is never lost. (F31)
PROGRESS_PERSIST_INTERVAL = 5.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _parse_course_selector(raw: str) -> Tuple[str, Optional[str], Optional[str]]:
    text = str(raw or "").strip()
    if not text:
        return "", None, None
    parts = [part for part in text.split("_") if part]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], parts[1], None
    return parts[0], None, None


def _course_label(course: Dict[str, Any]) -> str:
    return (
        str(course.get("title") or "").strip()
        or str(course.get("courseName") or "").strip()
        or f"{course.get('courseId', 'course')}"
    )


class ChaoxingLearningManager:
    """Background task manager for Chaoxing course-learning jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._loaded_task_users: set[str] = set()
        self._restore_tasks_from_store()

    def start_task(self, user_id: str, payload: Dict[str, Any]) -> str:
        task_id = uuid4().hex
        pause_event = threading.Event()
        pause_event.set()
        stop_event = threading.Event()
        now = _utc_now_iso()

        task_state: Dict[str, Any] = {
            "task_id": task_id,
            "user_id": user_id,
            "platform": "chaoxing",
            "status": "pending",
            "message": "Task created",
            "current_task": "preparing",
            "progress": {
                "total": 0,
                "completed": 0,
                "failed": 0,
                "current": 0,
                "total_chapters": 0,
                "completed_chapters": 0,
                "current_course": "",
                "current_chapter": "",
                "video_progress": None,
            },
            "created_at": now,
            "started_at": now,
            "updated_at": now,
            "logs": [],
            "_log_cursor": 0,
            "_pause_event": pause_event,
            "_stop_event": stop_event,
        }

        with self._lock:
            self._tasks[task_id] = task_state
        self._persist_task_state(self._task_public_payload(task_state))

        threading.Thread(
            target=self._run_task_worker_guarded,
            args=(task_id, user_id, dict(payload or {})),
            daemon=True,
        ).start()
        return task_id

    def get_task(self, user_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        normalized_user_id = str(user_id or "").strip()
        normalized_task_id = str(task_id or "").strip()
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if task and str(task.get("user_id")) == normalized_user_id:
                return {k: v for k, v in task.items() if not k.startswith("_")}

        self._load_task_from_store(normalized_user_id, normalized_task_id)
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if not task or str(task.get("user_id")) != normalized_user_id:
                return None
            return {k: v for k, v in task.items() if not k.startswith("_")}

    def list_tasks(self, user_id: str) -> List[Dict[str, Any]]:
        self._ensure_tasks_loaded_for_user(user_id)
        with self._lock:
            tasks: List[Dict[str, Any]] = []
            for task in self._tasks.values():
                if str(task.get("user_id")) != str(user_id):
                    continue
                public_task = self._task_public_payload(task)
                public_task.pop("user_id", None)
                started_at = (
                    public_task.get("started_at")
                    or public_task.get("start_time")
                    or public_task.get("created_at")
                )
                if started_at:
                    public_task["started_at"] = started_at
                if not public_task.get("updated_at") and started_at:
                    public_task["updated_at"] = started_at
                tasks.append(public_task)
        return sorted(
            tasks,
            key=lambda item: str(
                item.get("updated_at")
                or item.get("start_time")
                or item.get("started_at")
                or ""
            ),
            reverse=True,
        )

    def get_task_logs(self, user_id: str, task_id: str, cursor: Optional[int] = None) -> Optional[Dict[str, Any]]:
        normalized_user_id = str(user_id or "").strip()
        normalized_task_id = str(task_id or "").strip()
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if task and str(task.get("user_id")) == normalized_user_id:
                start = int(cursor) if cursor is not None else int(task.get("_log_cursor", 0))
                logs = list(task.get("logs", [])[start:])
                next_cursor = len(task.get("logs", []))
                if cursor is None:
                    task["_log_cursor"] = next_cursor
                return {"logs": logs, "cursor": next_cursor}

        self._load_task_from_store(normalized_user_id, normalized_task_id)
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if not task or str(task.get("user_id")) != normalized_user_id:
                return None
            start = int(cursor) if cursor is not None else int(task.get("_log_cursor", 0))
            logs = list(task.get("logs", [])[start:])
            next_cursor = len(task.get("logs", []))
            if cursor is None:
                task["_log_cursor"] = next_cursor
            return {"logs": logs, "cursor": next_cursor}

    def pause_task(self, user_id: str, task_id: str) -> Dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_task_id = str(task_id or "").strip()
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if task and str(task.get("user_id")) == normalized_user_id:
                pass
            else:
                task = None
        if task is None:
            self._load_task_from_store(normalized_user_id, normalized_task_id)
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if not task or str(task.get("user_id")) != normalized_user_id:
                return {"status": "error", "message": "Task not found"}
            if task.get("status") in {"completed", "failed", "error", "cancelled"}:
                return {"status": task.get("status", "completed"), "message": "Task already finished"}
            pause_event: threading.Event = task["_pause_event"]
            pause_event.clear()
            task["status"] = "paused"
            task["message"] = "Task paused"
            task["updated_at"] = _utc_now_iso()
        self._append_task_log(task_id, "Task paused", "warning")
        return {"status": "paused", "message": "Task paused"}

    def resume_task(self, user_id: str, task_id: str) -> Dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_task_id = str(task_id or "").strip()
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if task and str(task.get("user_id")) == normalized_user_id:
                pass
            else:
                task = None
        if task is None:
            self._load_task_from_store(normalized_user_id, normalized_task_id)
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if not task or str(task.get("user_id")) != normalized_user_id:
                return {"status": "error", "message": "Task not found"}
            if task.get("status") in {"completed", "failed", "error", "cancelled"}:
                return {"status": task.get("status", "completed"), "message": "Task already finished"}
            pause_event: threading.Event = task["_pause_event"]
            pause_event.set()
            task["status"] = "running"
            task["message"] = "Task resumed"
            task["updated_at"] = _utc_now_iso()
        self._append_task_log(task_id, "Task resumed", "info")
        return {"status": "running", "message": "Task resumed"}

    def stop_task(self, user_id: str, task_id: str) -> Dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_task_id = str(task_id or "").strip()
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if task and str(task.get("user_id")) == normalized_user_id:
                pass
            else:
                task = None
        if task is None:
            self._load_task_from_store(normalized_user_id, normalized_task_id)
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if not task or str(task.get("user_id")) != normalized_user_id:
                return {"status": "error", "message": "Task not found"}
            stop_event: threading.Event = task["_stop_event"]
            pause_event: threading.Event = task["_pause_event"]
            stop_event.set()
            pause_event.set()
            if task.get("status") not in {"completed", "failed", "error", "cancelled"}:
                task["status"] = "cancelling"
                task["message"] = "Task cancellation requested"
            task["updated_at"] = _utc_now_iso()
        self._append_task_log(task_id, "Task cancellation requested", "warning")
        return {"status": "cancelling", "message": "Task cancellation requested"}

    def _run_task_worker(self, task_id: str, user_id: str, payload: Dict[str, Any]) -> None:
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "").strip()
        if not username or not password:
            self._fail_task(task_id, "Missing username or password")
            return

        course_list = payload.get("course_ids") or payload.get("course_list") or []
        if not isinstance(course_list, list):
            course_list = []

        common_config = {
            "username": username,
            "password": password,
            "course_list": [str(item) for item in course_list if str(item).strip()],
            "speed": _as_float(payload.get("speed"), default=1.5, minimum=1.0, maximum=2.0),
            "jobs": _as_int(
                payload.get("concurrency", payload.get("jobs")),
                default=4,
                minimum=1,
                maximum=16,
            ),
            "notopen_action": str(
                payload.get("unopened_strategy") or payload.get("notopen_action") or "retry"
            ).strip().lower(),
            "use_cookies": False,
        }
        if common_config["notopen_action"] not in {"retry", "ask", "continue"}:
            common_config["notopen_action"] = "retry"

        tiku_config = normalize_tiku_config(payload.get("tiku_config"))
        notify_config = payload.get("notify_config")
        if not isinstance(notify_config, dict):
            notify_config = {}

        stop_event, pause_event = self._control_events(task_id)
        if stop_event is None or pause_event is None:
            return

        self._update_task(
            task_id,
            status="running",
            message="Logging in to Chaoxing",
            current_task="login",
        )
        self._append_task_log(task_id, "Starting login...", "info")

        try:
            chaoxing = init_chaoxing(common_config, tiku_config)
        except Exception as exc:
            self._fail_task(task_id, f"Initialize chaoxing client failed: {exc}")
            return

        try:
            login_state = chaoxing.login(login_with_cookies=False)
        except Exception as exc:
            self._fail_task(task_id, f"Login request failed: {exc}")
            return

        if not login_state.get("status"):
            self._fail_task(task_id, login_state.get("msg") or login_state.get("message") or "Login failed")
            return

        self._append_task_log(task_id, "Login successful", "success")

        try:
            all_courses = chaoxing.get_course_list()
        except Exception as exc:
            self._fail_task(task_id, f"Fetch course list failed: {exc}")
            return

        selected_courses = self._select_courses(all_courses, common_config["course_list"])
        if not selected_courses:
            self._fail_task(task_id, "No available courses after filtering")
            return

        self._update_progress(
            task_id,
            total=len(selected_courses),
            completed=0,
            failed=0,
            current=0,
            total_chapters=0,
            completed_chapters=0,
            current_course="",
            current_chapter="",
            video_progress=None,
        )
        self._append_task_log(
            task_id,
            f"Selected {len(selected_courses)} courses, speed {common_config['speed']}x, jobs {common_config['jobs']}",
            "info",
        )

        completed_courses = 0
        failed_courses = 0

        for index, course in enumerate(selected_courses, start=1):
            if stop_event.is_set():
                self._cancel_task(task_id, "Task cancelled by user")
                return

            if not self._wait_for_resume(task_id, pause_event, stop_event):
                self._cancel_task(task_id, "Task cancelled by user")
                return

            course_name = _course_label(course)
            self._update_task(
                task_id,
                status="running",
                message=f"Learning course {index}/{len(selected_courses)}",
                current_task=f"course:{course_name}",
            )
            self._update_progress(
                task_id,
                current=index,
                current_course=course_name,
                current_chapter="",
                video_progress=None,
            )
            self._append_task_log(task_id, f"Start course: {course_name}", "info")

            try:
                points_payload = chaoxing.get_course_point(
                    course["courseId"], course["clazzId"], course["cpi"]
                )
                points = list(points_payload.get("points") or [])
            except Exception as exc:
                failed_courses += 1
                self._append_task_log(task_id, f"Fetch chapters failed for {course_name}: {exc}", "error")
                self._update_progress(task_id, failed=failed_courses, current=index)
                continue

            if points:
                self._increase_progress(task_id, "total_chapters", len(points))

            callback_lock = threading.Lock()
            last_video_tick = {"ts": 0.0}

            def chapter_start_callback(_: Dict[str, Any], point: Dict[str, Any]) -> None:
                if stop_event.is_set():
                    return
                if not pause_event.is_set():
                    self._wait_for_resume(task_id, pause_event, stop_event)
                self._update_progress(
                    task_id,
                    current_course=course_name,
                    current_chapter=str(point.get("title") or ""),
                )
                self._update_task(
                    task_id,
                    current_task=f"chapter:{point.get('title', '')}",
                )

            def chapter_done_callback(_: Dict[str, Any], point: Dict[str, Any]) -> None:
                del point
                self._increase_progress(task_id, "completed_chapters", 1)

            def video_progress_callback(
                _: Dict[str, Any],
                job: Dict[str, Any],
                play_time: float,
                duration: float,
            ) -> None:
                if stop_event.is_set():
                    return
                if not pause_event.is_set():
                    self._wait_for_resume(task_id, pause_event, stop_event)
                now = time.time()
                with callback_lock:
                    if now - last_video_tick["ts"] < 0.8:
                        return
                    last_video_tick["ts"] = now
                self._update_progress(
                    task_id,
                    video_progress={
                        "name": str(job.get("name") or ""),
                        "current": round(float(play_time), 1),
                        "duration": round(float(duration), 1),
                    },
                )

            chapter_tasks = [ChapterTask(point=point, index=i) for i, point in enumerate(points)]
            run_config = dict(common_config)
            run_config["chapter_start_callback"] = chapter_start_callback
            run_config["chapter_done_callback"] = chapter_done_callback
            run_config["video_progress_callback"] = video_progress_callback
            run_config["should_stop"] = stop_event.is_set

            try:
                processor = JobProcessor(chaoxing, course, chapter_tasks, run_config)
                processor.run()
                if stop_event.is_set():
                    self._cancel_task(task_id, "Task cancelled by user")
                    return
                if processor.failed_tasks:
                    failed_courses += 1
                    self._append_task_log(
                        task_id,
                        f"Course finished with {len(processor.failed_tasks)} failed chapters: {course_name}",
                        "warning",
                    )
                else:
                    completed_courses += 1
                    self._append_task_log(task_id, f"Course completed: {course_name}", "success")
            except Exception as exc:
                failed_courses += 1
                self._append_task_log(task_id, f"Course execution failed {course_name}: {exc}", "error")

            self._update_progress(
                task_id,
                completed=completed_courses,
                failed=failed_courses,
                current=index,
                current_course=course_name,
            )

        if stop_event.is_set():
            self._cancel_task(task_id, "Task cancelled by user")
            return

        if failed_courses > 0:
            summary = f"Task finished with failures ({failed_courses} failed courses)"
            self._update_task(
                task_id,
                status="failed",
                message=summary,
                current_task="finished",
            )
            self._append_task_log(task_id, "Task finished with failures", "warning")
        else:
            summary = "Task completed"
            self._update_task(
                task_id,
                status="completed",
                message=summary,
                current_task="finished",
            )
            self._append_task_log(task_id, "Task completed", "success")

        self._send_completion_notification(task_id, notify_config, summary)

    def _send_completion_notification(
        self,
        task_id: str,
        notify_config: Dict[str, Any],
        summary: str,
    ) -> None:
        """Deliver a completion notification via the configured provider.

        The web `notify_config` carries `service` (provider name, e.g. ServerChan
        /Qmsg/Bark/Telegram) and `url`, matching what app.services.notification
        providers expect as {"provider": ..., "url": ...}. Best-effort: any
        failure is logged into the task log and never propagated.
        """
        if not isinstance(notify_config, dict):
            return
        service = str(notify_config.get("service") or "").strip()
        url = str(notify_config.get("url") or "").strip()
        if not service or not url:
            return

        # SSRF guard: refuse to POST to internal/loopback/metadata hosts, mirroring
        # the /notify/test endpoint guard.
        if not validate_notification_url(url):
            self._append_task_log(
                task_id,
                "Notification skipped: URL must be a public http(s) address",
                "warning",
            )
            return

        provider_config: Dict[str, Any] = {"provider": service, "url": url}
        tg_chat_id = notify_config.get("tg_chat_id")
        if tg_chat_id:
            provider_config["tg_chat_id"] = str(tg_chat_id)

        try:
            notifier = NotificationFactory.create_service(provider_config)
            notifier.send(f"chaoxing : {summary}")
            self._append_task_log(task_id, f"Notification sent via {service}", "info")
        except Exception as exc:  # pragma: no cover - best-effort, never fatal
            logger.warning("send learning notification failed: %s", exc)
            self._append_task_log(task_id, f"Notification failed: {exc}", "warning")

    def _run_task_worker_guarded(self, task_id: str, user_id: str, payload: Dict[str, Any]) -> None:
        try:
            self._run_task_worker(task_id, user_id, payload)
        except Exception as exc:  # pragma: no cover - defensive safety net
            logger.exception("Chaoxing learning task crashed: task_id=%s user_id=%s", task_id, user_id)
            message = f"{UNEXPECTED_WORKER_ERROR_PREFIX}: {exc}"
            self._fail_task(task_id, message)

    def _select_courses(self, all_courses: List[Dict[str, Any]], selectors: List[str]) -> List[Dict[str, Any]]:
        if not selectors:
            return list(all_courses)

        parsed = [_parse_course_selector(item) for item in selectors]
        selected: List[Dict[str, Any]] = []
        seen: set[str] = set()

        for course in all_courses:
            course_id = str(course.get("courseId") or "")
            clazz_id = str(course.get("clazzId") or "")
            cpi = str(course.get("cpi") or "")
            for target_course, target_clazz, target_cpi in parsed:
                if target_course and course_id != target_course:
                    continue
                if target_clazz and clazz_id != target_clazz:
                    continue
                if target_cpi and cpi != target_cpi:
                    continue
                identity = f"{course_id}_{clazz_id}_{cpi}"
                if identity not in seen:
                    seen.add(identity)
                    selected.append(course)
                break

        return selected

    def _control_events(self, task_id: str) -> Tuple[Optional[threading.Event], Optional[threading.Event]]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None, None
            return task.get("_stop_event"), task.get("_pause_event")

    def _wait_for_resume(
        self,
        task_id: str,
        pause_event: threading.Event,
        stop_event: threading.Event,
    ) -> bool:
        while not stop_event.is_set() and not pause_event.is_set():
            self._update_task(task_id, status="paused", message="Task paused", current_task="paused")
            time.sleep(0.25)
        return not stop_event.is_set()

    def _cancel_task(self, task_id: str, message: str) -> None:
        self._update_task(task_id, status="cancelled", message=message, current_task="cancelled")
        self._append_task_log(task_id, message, "warning")

    def _fail_task(self, task_id: str, message: str) -> None:
        self._update_task(task_id, status="failed", message=message, current_task="failed")
        self._append_task_log(task_id, message, "error")

    def _append_task_log(self, task_id: str, message: str, level: str = "info") -> None:
        snapshot: Optional[Dict[str, Any]] = None
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["logs"].append(
                {
                    "timestamp": _utc_now_iso(),
                    "message": str(message),
                    "level": level,
                }
            )
            if len(task["logs"]) > 1000:
                del task["logs"][:-1000]
            task["updated_at"] = _utc_now_iso()
            snapshot = self._task_public_payload(task)
        if snapshot:
            self._persist_task_state(snapshot)

    def _update_task(self, task_id: str, **changes: Any) -> None:
        snapshot: Optional[Dict[str, Any]] = None
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            # Skip the (forced) main-DB upsert when nothing actually changed.
            # _wait_for_resume calls this every 0.25s while paused with the same
            # status/message; without this guard each tick would re-serialize and
            # upsert the full payload pointlessly. (F31)
            if all(task.get(key) == value for key, value in changes.items()):
                return
            task.update(changes)
            task["updated_at"] = _utc_now_iso()
            snapshot = self._task_public_payload(task)
        if snapshot:
            self._persist_task_state(snapshot)

    def _update_progress(self, task_id: str, **updates: Any) -> None:
        snapshot: Optional[Dict[str, Any]] = None
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            progress = dict(task.get("progress") or {})
            progress.update(updates)
            task["progress"] = progress
            task["updated_at"] = _utc_now_iso()
            snapshot = self._task_public_payload(task)
        if snapshot:
            # High-frequency (video) progress: throttle main-DB writes. The next
            # forced write (status change / terminal) carries the latest
            # progress, so the final state is never lost. (F31)
            self._persist_task_state(snapshot, task_id=task_id, force=False)

    def _increase_progress(self, task_id: str, key: str, delta: int = 1) -> None:
        snapshot: Optional[Dict[str, Any]] = None
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            progress = dict(task.get("progress") or {})
            progress[key] = int(progress.get(key) or 0) + int(delta)
            task["progress"] = progress
            task["updated_at"] = _utc_now_iso()
            snapshot = self._task_public_payload(task)
        if snapshot:
            self._persist_task_state(snapshot, task_id=task_id, force=False)

    @staticmethod
    def _task_public_payload(task: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in task.items() if not str(k).startswith("_")}

    @staticmethod
    def _default_progress() -> Dict[str, Any]:
        return {
            "total": 0,
            "completed": 0,
            "failed": 0,
            "current": 0,
            "total_chapters": 0,
            "completed_chapters": 0,
            "current_course": "",
            "current_chapter": "",
            "video_progress": None,
        }

    def _should_persist_now(self, task_id: Optional[str], force: bool) -> bool:
        """Throttle high-frequency (force=False) progress persistence.

        Returns True if the caller should write to the store now. For throttled
        callers we only allow a write once every PROGRESS_PERSIST_INTERVAL
        seconds per task; intermediate ticks are dropped because the next forced
        write (status change / terminal) carries the latest progress anyway.
        """
        if force or not task_id:
            return True
        now = time.monotonic()
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return True
            last = float(task.get("_last_progress_persist_ts") or 0.0)
            if now - last < PROGRESS_PERSIST_INTERVAL:
                return False
            task["_last_progress_persist_ts"] = now
        return True

    def _persist_task_state(
        self,
        task_state_public: Dict[str, Any],
        task_id: Optional[str] = None,
        force: bool = True,
    ) -> None:
        if not self._should_persist_now(task_id, force):
            return
        try:
            task_store.upsert_task(LEARNING_TASK_KIND, task_state_public)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("persist learning task failed: %s", exc)

    def _ensure_tasks_loaded_for_user(self, user_id: str) -> None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return
        with self._lock:
            if normalized_user_id in self._loaded_task_users:
                return
        self._load_tasks_from_store_for_user(normalized_user_id)

    def _load_task_from_store(self, user_id: str, task_id: str) -> None:
        normalized_user_id = str(user_id or "").strip()
        normalized_task_id = str(task_id or "").strip()
        if not normalized_user_id or not normalized_task_id:
            return
        try:
            stored_task = task_store.get_task(
                task_kind=LEARNING_TASK_KIND,
                task_id=normalized_task_id,
                user_id=normalized_user_id,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("load learning task failed: user=%s task=%s err=%s", normalized_user_id, normalized_task_id, exc)
            stored_task = None
        if stored_task:
            self._merge_task_from_store(stored_task)

    def _load_tasks_from_store_for_user(self, user_id: str) -> None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return
        try:
            stored_tasks = task_store.list_tasks(
                task_kind=LEARNING_TASK_KIND,
                user_id=normalized_user_id,
                limit=USER_TASK_LOAD_LIMIT,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("load learning tasks failed: user=%s err=%s", normalized_user_id, exc)
            stored_tasks = []

        for item in stored_tasks:
            self._merge_task_from_store(item)

        with self._lock:
            self._loaded_task_users.add(normalized_user_id)

    def _merge_task_from_store(self, item: Dict[str, Any], now: Optional[str] = None) -> bool:
        task_id = str(item.get("task_id") or "").strip()
        user_id = str(item.get("user_id") or "").strip()
        if not task_id or not user_id:
            return False

        with self._lock:
            if task_id in self._tasks:
                return False

        current_time = now or _utc_now_iso()
        task: Dict[str, Any] = dict(item)
        progress = self._default_progress()
        raw_progress = task.get("progress")
        if isinstance(raw_progress, dict):
            progress.update(raw_progress)
        task["progress"] = progress
        task.setdefault("platform", "chaoxing")
        task.setdefault("created_at", task.get("started_at") or current_time)
        task.setdefault("started_at", task.get("created_at") or current_time)
        task.setdefault("updated_at", task.get("started_at") or current_time)

        logs = task.get("logs")
        if not isinstance(logs, list):
            logs = []
        task["logs"] = logs

        interrupted = str(task.get("status") or "").lower() in INTERRUPTED_STATUSES
        if interrupted:
            task["status"] = "failed"
            task["message"] = RESTART_INTERRUPTED_MESSAGE
            task["current_task"] = "failed"
            task["updated_at"] = current_time
            task["logs"].append(
                {
                    "timestamp": current_time,
                    "message": RESTART_INTERRUPTED_MESSAGE,
                    "level": "warning",
                }
            )
            if len(task["logs"]) > 1000:
                del task["logs"][:-1000]

        pause_event = threading.Event()
        pause_event.set()
        task["_pause_event"] = pause_event
        task["_stop_event"] = threading.Event()
        task["_log_cursor"] = 0

        with self._lock:
            self._tasks[task_id] = task

        if interrupted:
            self._persist_task_state(self._task_public_payload(task))
        return True

    def _restore_tasks_from_store(self) -> None:
        try:
            stored_tasks = task_store.list_tasks(task_kind=LEARNING_TASK_KIND, user_id=None, limit=300)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("restore learning tasks failed: %s", exc)
            stored_tasks = []

        now = _utc_now_iso()
        for item in stored_tasks:
            self._merge_task_from_store(item, now=now)


learning_manager = ChaoxingLearningManager()
