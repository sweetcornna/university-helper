import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.services.notification import NotificationFactory
from app.services.notification.providers import validate_notification_url

from ..task_store import task_store
from .endpoint_security import validate_tiku_config
from .learning import ChapterTask, JobProcessor, init_chaoxing
from .payload_mapper import normalize_tiku_config
from .task_admission import (
    MAX_ACTIVE_TASKS,
    TaskAlreadyActiveError,
    TaskCapacityError,
    cleanup_task_records,
    count_active_tasks,
    is_active_status,
    sort_task_records,
)

logger = logging.getLogger(__name__)
LEARNING_TASK_KIND = "chaoxing_learning"
INTERRUPTED_STATUSES = {"running", "pending", "paused", "cancelling", "stopping"}
_NOTIFICATION_SERVICE_LABELS = frozenset({"ServerChan", "Qmsg", "Bark", "Telegram"})
RESTART_INTERRUPTED_MESSAGE = "Task interrupted due to service restart"
UNEXPECTED_WORKER_ERROR_PREFIX = "Unexpected task failure"
USER_TASK_LOAD_LIMIT = 2000
THREAD_START_FAILURE_MESSAGE = (
    "Server cannot start a new background thread. Stop existing tasks and retry, "
    "or restart the service if the problem persists."
)
TASK_PERSIST_FAILURE_MESSAGE = "Failed to persist learning task state"
# Minimum seconds between throttled (high-frequency progress) main-DB upserts of
# a single task's payload. Video progress callbacks fire ~1/sec per task and
# each upsert re-serializes the whole growing logs+progress payload as JSONB, so
# coalesce them. Status changes / logs / terminal writes bypass this throttle
# (force=True) so final state is never lost. (F31)
PROGRESS_PERSIST_INTERVAL = 5.0


class _TaskPersistSequencer:
    """Run one task's reserved snapshots in mutation order.

    Snapshot revisions are reserved while the manager lock still protects the
    corresponding state mutation. Store I/O happens after that lock is released,
    so unrelated tasks remain independent while concurrent callers for the same
    task cannot overtake one another.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._last_reserved_revision = 0
        self._last_finished_revision = 0

    def reserve(self) -> int:
        with self._condition:
            self._last_reserved_revision += 1
            return self._last_reserved_revision

    def run(self, revision: int, writer: Callable[[], None]) -> None:
        with self._condition:
            self._condition.wait_for(lambda: revision == self._last_finished_revision + 1)
        try:
            writer()
        finally:
            # A failed write must release the next revision. Persistence is
            # best-effort, and later snapshots still need a chance to recover.
            with self._condition:
                self._last_finished_revision = revision
                self._condition.notify_all()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


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


def _parse_course_selector(raw: str) -> tuple[str, str | None, str | None]:
    text = str(raw or "").strip()
    if not text:
        return "", None, None
    parts = [part for part in text.split("_") if part]
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], parts[1], None
    return parts[0], None, None


def _course_label(course: dict[str, Any]) -> str:
    return (
        str(course.get("title") or "").strip()
        or str(course.get("courseName") or "").strip()
        or f"{course.get('courseId', 'course')}"
    )


class ChaoxingLearningManager:
    """Background task manager for Chaoxing course-learning jobs."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._loaded_task_users: set[str] = set()
        self._restore_tasks_from_store()

    def start_task(self, user_id: str, payload: dict[str, Any]) -> str:
        # Validate user-controlled answer-provider destinations before creating
        # persistent state or a worker thread.  The API maps the safe,
        # detail-free exception to a 4xx response; direct callers get the same
        # fail-closed behavior.
        validate_tiku_config((payload or {}).get("tiku_config"))

        normalized_user_id = str(user_id or "").strip()
        with self._lock:
            cleanup_task_records(self._tasks)
            if any(
                str(task.get("user_id") or "").strip() == normalized_user_id and is_active_status(task.get("status"))
                for task in self._tasks.values()
            ):
                raise TaskAlreadyActiveError()
            if count_active_tasks(self._tasks) >= MAX_ACTIVE_TASKS:
                raise TaskCapacityError()

            task_id = uuid4().hex
            pause_event = threading.Event()
            pause_event.set()
            stop_event = threading.Event()
            now = _utc_now_iso()
            task_state: dict[str, Any] = {
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
            self._tasks[task_id] = task_state
            cleanup_task_records(self._tasks)
            persist_request = self._prepare_persist_locked(task_state)
        if persist_request:
            try:
                persisted = self._persist_task_state(*persist_request)
                if persisted is not True:
                    raise RuntimeError(TASK_PERSIST_FAILURE_MESSAGE)
            except Exception:
                self._record_admission_persist_failure(task_id)
                raise

        try:
            threading.Thread(
                target=self._run_task_worker_guarded,
                args=(task_id, user_id, dict(payload or {})),
                daemon=True,
            ).start()
        except Exception as exc:
            self._fail_task(task_id, THREAD_START_FAILURE_MESSAGE)
            raise RuntimeError(THREAD_START_FAILURE_MESSAGE) from exc
        return task_id

    def get_task(self, user_id: str, task_id: str) -> dict[str, Any] | None:
        normalized_user_id = str(user_id or "").strip()
        normalized_task_id = str(task_id or "").strip()
        with self._lock:
            cleanup_task_records(self._tasks)
            task = self._tasks.get(normalized_task_id)
            if task and str(task.get("user_id")) == normalized_user_id:
                return {k: v for k, v in task.items() if not k.startswith("_")}

        self._load_task_from_store(normalized_user_id, normalized_task_id)
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if not task or str(task.get("user_id")) != normalized_user_id:
                return None
            return {k: v for k, v in task.items() if not k.startswith("_")}

    def list_tasks(self, user_id: str) -> list[dict[str, Any]]:
        self._ensure_tasks_loaded_for_user(user_id)
        with self._lock:
            cleanup_task_records(self._tasks)
            tasks: list[dict[str, Any]] = []
            for task in self._tasks.values():
                if str(task.get("user_id")) != str(user_id):
                    continue
                public_task = self._task_public_payload(task)
                public_task.pop("user_id", None)
                started_at = (
                    public_task.get("started_at") or public_task.get("start_time") or public_task.get("created_at")
                )
                if started_at:
                    public_task["started_at"] = started_at
                if not public_task.get("updated_at") and started_at:
                    public_task["updated_at"] = started_at
                tasks.append(public_task)
        return sort_task_records(tasks)

    def get_task_logs(self, user_id: str, task_id: str, cursor: int | None = None) -> dict[str, Any] | None:
        normalized_user_id = str(user_id or "").strip()
        normalized_task_id = str(task_id or "").strip()
        with self._lock:
            cleanup_task_records(self._tasks)
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
            cleanup_task_records(self._tasks)
            task = self._tasks.get(normalized_task_id)
            if not task or str(task.get("user_id")) != normalized_user_id:
                return None
            start = int(cursor) if cursor is not None else int(task.get("_log_cursor", 0))
            logs = list(task.get("logs", [])[start:])
            next_cursor = len(task.get("logs", []))
            if cursor is None:
                task["_log_cursor"] = next_cursor
            return {"logs": logs, "cursor": next_cursor}

    def pause_task(self, user_id: str, task_id: str) -> dict[str, Any]:
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

    def resume_task(self, user_id: str, task_id: str) -> dict[str, Any]:
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

    def stop_task(self, user_id: str, task_id: str) -> dict[str, Any]:
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

    def _run_task_worker(self, task_id: str, user_id: str, payload: dict[str, Any]) -> None:
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
            "notopen_action": str(payload.get("unopened_strategy") or payload.get("notopen_action") or "retry")
            .strip()
            .lower(),
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
                points_payload = chaoxing.get_course_point(course["courseId"], course["clazzId"], course["cpi"])
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

            def chapter_start_callback(_: dict[str, Any], point: dict[str, Any]) -> None:
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

            def chapter_done_callback(_: dict[str, Any], point: dict[str, Any]) -> None:
                del point
                self._increase_progress(task_id, "completed_chapters", 1)

            def video_progress_callback(
                _: dict[str, Any],
                job: dict[str, Any],
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
        notify_config: dict[str, Any],
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
        raw_service = notify_config.get("service")
        service = raw_service.strip() if isinstance(raw_service, str) else ""
        raw_url = notify_config.get("url")
        url = raw_url.strip() if isinstance(raw_url, str) else ""
        if not service or not url:
            return
        if service not in _NOTIFICATION_SERVICE_LABELS:
            self._append_task_log(task_id, "Notification skipped: unsupported service", "warning")
            return

        # SSRF guard: refuse to POST to internal/loopback/metadata hosts, mirroring
        # the /notify/test endpoint guard.
        try:
            url_allowed = validate_notification_url(url)
        except Exception as exc:
            logger.warning("notification URL validation failed: %s", type(exc).__name__)
            self._append_task_log(task_id, "Notification skipped: URL validation failed", "warning")
            return
        if not url_allowed:
            self._append_task_log(
                task_id,
                "Notification skipped: URL must be a public http(s) address",
                "warning",
            )
            return

        provider_config: dict[str, Any] = {"provider": service, "url": url}
        tg_chat_id = notify_config.get("tg_chat_id")
        if tg_chat_id:
            provider_config["tg_chat_id"] = str(tg_chat_id)

        try:
            notifier = NotificationFactory.create_service(provider_config)
            notifier.send(f"chaoxing : {summary}")
            self._append_task_log(task_id, f"Notification sent via {service}", "info")
        except Exception as exc:  # pragma: no cover - best-effort, never fatal
            failure_type = type(exc).__name__
            logger.warning("send learning notification failed: %s", failure_type)
            self._append_task_log(task_id, f"Notification failed ({failure_type})", "warning")

    def _run_task_worker_guarded(self, task_id: str, user_id: str, payload: dict[str, Any]) -> None:
        try:
            self._run_task_worker(task_id, user_id, payload)
        except Exception as exc:  # pragma: no cover - defensive safety net
            logger.exception("Chaoxing learning task crashed: task_id=%s user_id=%s", task_id, user_id)
            message = f"{UNEXPECTED_WORKER_ERROR_PREFIX}: {exc}"
            self._fail_task(task_id, message)

    def _select_courses(self, all_courses: list[dict[str, Any]], selectors: list[str]) -> list[dict[str, Any]]:
        if not selectors:
            return list(all_courses)

        parsed = [_parse_course_selector(item) for item in selectors]
        selected: list[dict[str, Any]] = []
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

    def _control_events(self, task_id: str) -> tuple[threading.Event | None, threading.Event | None]:
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

    def _record_admission_persist_failure(self, task_id: str) -> None:
        """Keep an unstarted task terminal and best-effort overwrite any active row."""
        persist_request: tuple[dict[str, Any], _TaskPersistSequencer, int] | None = None
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            now = _utc_now_iso()
            task.update(
                status="failed",
                message=TASK_PERSIST_FAILURE_MESSAGE,
                current_task="failed",
                updated_at=now,
            )
            task["logs"].append(
                {
                    "timestamp": now,
                    "message": TASK_PERSIST_FAILURE_MESSAGE,
                    "level": "error",
                }
            )
            if len(task["logs"]) > 1000:
                del task["logs"][:-1000]
            persist_request = self._prepare_persist_locked(task)
        if not persist_request:
            return
        try:
            if self._persist_task_state(*persist_request) is not True:
                logger.warning("failed to compensate learning task admission: task_id=%s", task_id)
        except Exception:  # pragma: no cover - defensive for patched/custom stores
            logger.warning("failed to compensate learning task admission: task_id=%s", task_id, exc_info=True)

    def _append_task_log(self, task_id: str, message: str, level: str = "info") -> None:
        persist_request: tuple[dict[str, Any], _TaskPersistSequencer, int] | None = None
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
            persist_request = self._prepare_persist_locked(task)
        if persist_request:
            self._persist_task_state(*persist_request)

    def _update_task(self, task_id: str, **changes: Any) -> None:
        persist_request: tuple[dict[str, Any], _TaskPersistSequencer, int] | None = None
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
            persist_request = self._prepare_persist_locked(task)
        if persist_request:
            self._persist_task_state(*persist_request)

    def _update_progress(self, task_id: str, **updates: Any) -> None:
        persist_request: tuple[dict[str, Any], _TaskPersistSequencer, int] | None = None
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            progress = dict(task.get("progress") or {})
            progress.update(updates)
            task["progress"] = progress
            task["updated_at"] = _utc_now_iso()
            # High-frequency (video) progress: throttle main-DB writes. The next
            # forced write (status change / terminal) carries the latest
            # progress, so the final state is never lost. (F31)
            persist_request = self._prepare_persist_locked(task, force=False)
        if persist_request:
            self._persist_task_state(*persist_request)

    def _increase_progress(self, task_id: str, key: str, delta: int = 1) -> None:
        persist_request: tuple[dict[str, Any], _TaskPersistSequencer, int] | None = None
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            progress = dict(task.get("progress") or {})
            progress[key] = int(progress.get(key) or 0) + int(delta)
            task["progress"] = progress
            task["updated_at"] = _utc_now_iso()
            persist_request = self._prepare_persist_locked(task, force=False)
        if persist_request:
            self._persist_task_state(*persist_request)

    @staticmethod
    def _task_public_payload(task: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in task.items() if not str(k).startswith("_")}

    @staticmethod
    def _default_progress() -> dict[str, Any]:
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

    def _prepare_persist_locked(
        self,
        task: dict[str, Any],
        *,
        force: bool = True,
    ) -> tuple[dict[str, Any], _TaskPersistSequencer, int] | None:
        """Capture and order a snapshot while ``self._lock`` is held."""
        if not force:
            now = time.monotonic()
            last = float(task.get("_last_progress_persist_ts") or 0.0)
            if now - last < PROGRESS_PERSIST_INTERVAL:
                return None
            task["_last_progress_persist_ts"] = now

        snapshot = self._task_public_payload(task)
        sequencer = task.get("_persist_sequencer")
        if not isinstance(sequencer, _TaskPersistSequencer):
            sequencer = _TaskPersistSequencer()
            task["_persist_sequencer"] = sequencer
        revision = sequencer.reserve()
        return snapshot, sequencer, revision

    def _persist_task_state(
        self,
        task_state_public: dict[str, Any],
        sequencer: _TaskPersistSequencer | None = None,
        revision: int | None = None,
    ) -> bool:
        persisted = True

        def write() -> None:
            nonlocal persisted
            try:
                result = task_store.upsert_task(LEARNING_TASK_KIND, task_state_public)
                persisted = result is True
            except Exception as exc:  # pragma: no cover - defensive fallback
                persisted = False
                logger.warning("persist learning task failed: %s", exc)

        if sequencer is None or revision is None:
            # Keep direct private callers compatible; manager-generated snapshots
            # always carry a reservation and therefore use the ordered path.
            write()
            return persisted
        sequencer.run(revision, write)
        return persisted

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
            logger.warning(
                "load learning task failed: user=%s task=%s err=%s", normalized_user_id, normalized_task_id, exc
            )
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
            cleanup_task_records(self._tasks)
            self._loaded_task_users.add(normalized_user_id)

    def _merge_task_from_store(self, item: dict[str, Any], now: str | None = None) -> bool:
        task_id = str(item.get("task_id") or "").strip()
        user_id = str(item.get("user_id") or "").strip()
        if not task_id or not user_id:
            return False

        with self._lock:
            if task_id in self._tasks:
                return False

        current_time = now or _utc_now_iso()
        task: dict[str, Any] = dict(item)
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
            if task_id in self._tasks:
                return False
            self._tasks[task_id] = task

        if interrupted:
            with self._lock:
                persist_request = self._prepare_persist_locked(task)
            if persist_request:
                self._persist_task_state(*persist_request)
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
        with self._lock:
            cleanup_task_records(self._tasks)


learning_manager = ChaoxingLearningManager()
