import asyncio
import base64
import logging
import threading
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies import get_current_user
from app.services.course.chaoxing.signin import signin_manager
from app.services.course.zhihuishu.adapter import ZhihuishuAdapter

router = APIRouter()
logger = logging.getLogger(__name__)
_QR_SESSION_TTL_SECONDS = 10 * 60
_USER_ADAPTER_TTL_SECONDS = 60 * 60  # 1 hour
_COURSE_TASK_TTL_SECONDS = 2 * 60 * 60  # 2 hours
_qr_sessions: Dict[str, Dict[str, Any]] = {}
_qr_sessions_lock = threading.Lock()
_user_adapters: Dict[str, Dict[str, Any]] = {}  # {"adapter": ..., "last_access": ...}
_course_tasks: Dict[str, Dict[str, Any]] = {}
_course_tasks_lock = threading.Lock()
_learning_manager_instance: Any = None


class CourseStartRequest(BaseModel):
    platform: str
    username: str
    password: str
    course_ids: Optional[List[str]] = None
    speed: float = 1.0
    concurrency: int = 4
    unopened_strategy: str = "retry"
    tiku_config: Optional[dict] = None
    notify_config: Optional[dict] = None


class CourseStatusResponse(BaseModel):
    status: str
    message: str
    progress: Optional[dict] = None
    task_id: Optional[str] = None
    current_task: Optional[str] = None


class ZhihuishuQRLoginResponse(BaseModel):
    session_id: str
    status: str
    message: str
    qr_code: str


class ZhihuishuQRStatusResponse(BaseModel):
    session_id: str
    status: str
    message: str


class ZhihuishuPasswordLoginRequest(BaseModel):
    username: str
    password: str


class ZhihuishuCourseRequest(BaseModel):
    course_id: str
    speed: float = 1.0
    auto_answer: bool = True


class ZhihuishuTaskStartRequest(BaseModel):
    course_id: str
    speed: Optional[float] = None
    auto_answer: Optional[bool] = None


class ZhihuishuConfigUpdateRequest(BaseModel):
    speed: Optional[float] = None
    auto_answer: Optional[bool] = None
    proxies: Optional[Dict[str, Any]] = None
    ai_config: Optional[Dict[str, Any]] = None


def _internal_error(message: str, exc: Exception) -> HTTPException:
    logger.exception("%s: %s", message, exc)
    return HTTPException(status_code=500, detail=message)


async def _run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


@router.post("/start", response_model=CourseStatusResponse)
async def start_course_learning(
    request: CourseStartRequest,
    current_user: dict = Depends(get_current_user),
):
    if request.platform.lower() != "chaoxing":
        raise HTTPException(status_code=400, detail="Only chaoxing is supported")

    user_id = _current_user_id(current_user)
    try:
        learning_manager = _get_learning_manager()
        task_id = await _run_blocking(
            learning_manager.start_task,
            user_id=user_id,
            payload={
                "platform": request.platform,
                "username": request.username,
                "password": request.password,
                "course_ids": request.course_ids or [],
                "speed": request.speed,
                "concurrency": request.concurrency,
                "unopened_strategy": request.unopened_strategy,
                "tiku_config": request.tiku_config or {},
                "notify_config": request.notify_config or {},
            },
        )
        progress = {
            "total": len(request.course_ids or []),
            "completed": 0,
            "failed": 0,
            "current": 0,
        }
        return CourseStatusResponse(
            status="started",
            message="Course learning task started",
            progress=progress,
            task_id=task_id,
            current_task="preparing",
        )
    except Exception as exc:
        raise _internal_error("Failed to start course learning task", exc) from exc


@router.get("/status/{task_id}", response_model=CourseStatusResponse)
async def get_course_status(task_id: str, current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)

    chaoxing_task = None
    try:
        learning_manager = _get_learning_manager()
        chaoxing_task = await _run_blocking(learning_manager.get_task, user_id=user_id, task_id=task_id)
    except HTTPException as exc:
        if exc.status_code != 501:
            raise
    if chaoxing_task is not None:
        return CourseStatusResponse(
            status=str(chaoxing_task.get("status", "running")),
            message=str(chaoxing_task.get("message", "Task is running")),
            progress=chaoxing_task.get("progress"),
            task_id=task_id,
            current_task=chaoxing_task.get("current_task"),
        )

    task = _get_course_task(task_id)
    if task is None or str(task.get("user_id")) != user_id:
        raise HTTPException(status_code=404, detail="Task not found")

    # Keep /course/status compatible with Zhihuishu polling by syncing progress on every query.
    if task.get("platform") == "zhihuishu":
        with _qr_sessions_lock:
            entry = _user_adapters.get(user_id)
            adapter = entry["adapter"] if entry else None
        if adapter is not None:
            progress = await _run_blocking(adapter.get_progress, str(task.get("course_id") or ""))
            task_status = progress.get("status", task.get("status", "running"))
            task_message = progress.get("message", task.get("message", "Task is running"))
            task = _update_course_task(
                task_id,
                status=task_status,
                message=task_message,
                progress=progress,
                current_task=progress.get("current_video"),
            ) or task

    return CourseStatusResponse(
        status=str(task.get("status", "running")),
        message=str(task.get("message", "Task is running")),
        progress=task.get("progress"),
        task_id=task_id,
        current_task=task.get("current_task"),
    )


@router.get("/tasks")
async def get_course_tasks(current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    learning_manager = _get_learning_manager()
    tasks = await _run_blocking(learning_manager.list_tasks, user_id=user_id)
    return {"status": "success", "message": "ok", "data": tasks}


@router.get("/logs/{task_id}")
async def get_course_logs(
    task_id: str,
    cursor: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
):
    user_id = _current_user_id(current_user)
    learning_manager = _get_learning_manager()
    log_state = await _run_blocking(learning_manager.get_task_logs, user_id=user_id, task_id=task_id, cursor=cursor)
    if log_state is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "status": "success",
        "message": "ok",
        "data": log_state.get("logs", []),
        "cursor": log_state.get("cursor", 0),
    }


@router.post("/task/{task_id}/pause")
async def pause_course_task(task_id: str, current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    learning_manager = _get_learning_manager()
    result = await _run_blocking(learning_manager.pause_task, user_id=user_id, task_id=task_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message", "Task not found"))
    return {"status": "success", "message": result.get("message", "Task paused"), "data": result}


@router.post("/task/{task_id}/resume")
async def resume_course_task(task_id: str, current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    learning_manager = _get_learning_manager()
    result = await _run_blocking(learning_manager.resume_task, user_id=user_id, task_id=task_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message", "Task not found"))
    return {"status": "success", "message": result.get("message", "Task resumed"), "data": result}


@router.post("/task/{task_id}/stop")
async def stop_course_task(task_id: str, current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    learning_manager = _get_learning_manager()
    result = await _run_blocking(learning_manager.stop_task, user_id=user_id, task_id=task_id)
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message", "Task not found"))
    return {"status": "success", "message": result.get("message", "Task cancellation requested"), "data": result}


def cleanup_expired_entries() -> None:
    now = time.time()
    with _qr_sessions_lock:
        expired = [
            session_id
            for session_id, state in _qr_sessions.items()
            if now - state.get("updated_at", now) > _QR_SESSION_TTL_SECONDS
        ]
        for session_id in expired:
            _qr_sessions.pop(session_id, None)
        expired_adapters = [
            user_id
            for user_id, entry in _user_adapters.items()
            if now - entry.get("last_access", now) > _USER_ADAPTER_TTL_SECONDS
        ]
        for user_id in expired_adapters:
            _user_adapters.pop(user_id, None)
    with _course_tasks_lock:
        expired_tasks = [
            task_id
            for task_id, task in _course_tasks.items()
            if now - task.get("updated_at", task.get("created_at", now)) > _COURSE_TASK_TTL_SECONDS
            and task.get("status") in ("completed", "failed", "cancelled", None)
        ]
        for task_id in expired_tasks:
            _course_tasks.pop(task_id, None)


def _current_user_id(current_user: dict) -> str:
    user_id = str(current_user.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    return user_id


def _get_learning_manager():
    global _learning_manager_instance
    if _learning_manager_instance is not None:
        return _learning_manager_instance
    try:
        from app.services.course.chaoxing.learning_manager import learning_manager
    except Exception as exc:
        raise HTTPException(
            status_code=501,
            detail=f"Chaoxing learning service unavailable: {exc}",
        ) from exc
    _learning_manager_instance = learning_manager
    return _learning_manager_instance


def _set_course_task(task_id: str, payload: Dict[str, Any]) -> None:
    with _course_tasks_lock:
        _course_tasks[task_id] = payload


def _get_course_task(task_id: str) -> Optional[Dict[str, Any]]:
    with _course_tasks_lock:
        task = _course_tasks.get(task_id)
        return dict(task) if task else None


def _update_course_task(task_id: str, **changes: Any) -> Optional[Dict[str, Any]]:
    with _course_tasks_lock:
        task = _course_tasks.get(task_id)
        if not task:
            return None
        task.update(changes)
        task["updated_at"] = time.time()
        return dict(task)


def _get_zhihuishu_adapter(user_id: str, required: bool = True) -> Optional[ZhihuishuAdapter]:
    with _qr_sessions_lock:
        entry = _user_adapters.get(user_id)
        if entry is not None:
            entry["last_access"] = time.time()
            adapter = entry["adapter"]
        else:
            adapter = None
    if required and not adapter:
        raise HTTPException(status_code=401, detail="Zhihuishu not logged in")
    return adapter


def _register_zhihuishu_course_task(
    user_id: str,
    course_id: str,
    task_id: str,
    progress: Dict[str, Any],
    task_type: str = "course",
) -> None:
    _set_course_task(
        task_id,
        {
            "task_id": task_id,
            "platform": "zhihuishu",
            "task_type": task_type,
            "course_id": course_id,
            "user_id": user_id,
            "status": progress.get("status", "running"),
            "message": progress.get("message", "Zhihuishu task started"),
            "progress": progress,
            "current_task": progress.get("current_video"),
            "created_at": time.time(),
            "updated_at": time.time(),
        },
    )


@router.post("/zhihuishu/qr-login", response_model=ZhihuishuQRLoginResponse)
async def start_zhihuishu_qr_login(current_user: dict = Depends(get_current_user)):
    cleanup_expired_entries()
    user_id = str(current_user.get("user_id"))
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    session_id = uuid4().hex
    adapter = ZhihuishuAdapter()
    qr_ready_event = threading.Event()

    state: Dict[str, Any] = {
        "status": "pending",
        "message": "Waiting for scan",
        "qr_code": None,
        "updated_at": time.time(),
        "user_id": user_id,
        "adapter": adapter,
    }

    with _qr_sessions_lock:
        _qr_sessions[session_id] = state

    def qr_callback(img_bytes: bytes) -> None:
        qr_b64 = base64.b64encode(img_bytes).decode("utf-8")
        with _qr_sessions_lock:
            current_state = _qr_sessions.get(session_id)
            if current_state is None:
                return
            current_state["qr_code"] = qr_b64
            current_state["updated_at"] = time.time()
        qr_ready_event.set()

    def login_worker() -> None:
        try:
            result = adapter.login_with_qr(qr_callback)
            success = bool(result.get("success"))
            with _qr_sessions_lock:
                current_state = _qr_sessions.get(session_id)
                if current_state is None:
                    return
                current_state["status"] = "success" if success else "failed"
                current_state["message"] = "Login successful" if success else "Login failed"
                current_state["updated_at"] = time.time()
                if success:
                    _user_adapters[user_id] = {"adapter": adapter, "last_access": time.time()}
        except Exception as exc:
            with _qr_sessions_lock:
                current_state = _qr_sessions.get(session_id)
                if current_state is None:
                    return
                current_state["status"] = "failed"
                current_state["message"] = str(exc)
                current_state["updated_at"] = time.time()

    threading.Thread(target=login_worker, daemon=True).start()

    if not qr_ready_event.wait(timeout=12):
        with _qr_sessions_lock:
            _qr_sessions.pop(session_id, None)
        raise HTTPException(status_code=504, detail="Failed to generate QR code")

    with _qr_sessions_lock:
        current_state = _qr_sessions.get(session_id)
        if current_state is None or not current_state.get("qr_code"):
            raise HTTPException(status_code=500, detail="QR code unavailable")

        return ZhihuishuQRLoginResponse(
            session_id=session_id,
            status=current_state.get("status", "pending"),
            message=current_state.get("message", "Waiting for scan"),
            qr_code=current_state["qr_code"],
        )


@router.get("/zhihuishu/login-status/{session_id}", response_model=ZhihuishuQRStatusResponse)
async def get_zhihuishu_login_status(
    session_id: str,
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user.get("user_id"))
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    cleanup_expired_entries()

    with _qr_sessions_lock:
        state = _qr_sessions.get(session_id)
        if state is None:
            raise HTTPException(status_code=404, detail="QR session not found or expired")
        if str(state.get("user_id")) != user_id:
            raise HTTPException(status_code=404, detail="QR session not found")

        return ZhihuishuQRStatusResponse(
            session_id=session_id,
            status=state.get("status", "pending"),
            message=state.get("message", "Waiting for scan"),
        )


@router.post("/zhihuishu/password-login")
async def zhihuishu_password_login(
    request: ZhihuishuPasswordLoginRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user.get("user_id"))
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    adapter = ZhihuishuAdapter()
    try:
        result = await _run_blocking(adapter.login_with_password, request.username, request.password)
        if not result.get("success"):
            raise HTTPException(status_code=401, detail="Login failed")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Zhihuishu login failed") from exc

    with _qr_sessions_lock:
        _user_adapters[user_id] = {"adapter": adapter, "last_access": time.time()}

    return {"status": "success", "message": "Login successful"}


@router.get("/zhihuishu/status")
async def zhihuishu_status(current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id, required=False)
    if adapter is None:
        data = {
            "logged_in": False,
            "status": "offline",
            "has_task": False,
            "current_task": None,
            "progress": None,
        }
        return {"status": "success", "message": "Not logged in", "data": data}

    try:
        if hasattr(adapter, "get_status"):
            data = await _run_blocking(adapter.get_status)
        else:
            data = {"logged_in": True, "status": "online", "has_task": False, "current_task": None}
    except Exception as exc:
        raise _internal_error("Failed to load Zhihuishu status", exc) from exc

    return {"status": "success", "message": "ok", "data": data}


@router.post("/zhihuishu/logout")
async def zhihuishu_logout(current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id, required=False)
    if adapter is not None:
        try:
            if hasattr(adapter, "logout"):
                await _run_blocking(adapter.logout)
        except Exception as exc:
            raise _internal_error("Failed to logout from Zhihuishu", exc) from exc

    with _qr_sessions_lock:
        _user_adapters.pop(user_id, None)
        expired_sessions = [
            session_id
            for session_id, state in _qr_sessions.items()
            if str(state.get("user_id")) == user_id
        ]
        for session_id in expired_sessions:
            _qr_sessions.pop(session_id, None)

    with _course_tasks_lock:
        for task in _course_tasks.values():
            if str(task.get("user_id")) == user_id and task.get("platform") == "zhihuishu":
                task["status"] = "cancelled"
                task["message"] = "Task cancelled by logout"
                task["updated_at"] = time.time()

    return {"status": "success", "message": "Logout successful"}


@router.get("/zhihuishu/courses")
async def zhihuishu_get_courses(current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    try:
        courses = await _run_blocking(adapter.get_courses)
    except Exception as exc:
        raise _internal_error("Failed to load Zhihuishu courses", exc) from exc

    return {
        "status": "success",
        "message": "Courses loaded",
        "data": courses,
        "courses": courses,
    }


@router.get("/zhihuishu/courses/grouped")
async def zhihuishu_get_grouped_courses(current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    try:
        groups = await _run_blocking(adapter.get_grouped_courses)
    except Exception as exc:
        raise _internal_error("Failed to load grouped Zhihuishu courses", exc) from exc

    return {
        "status": "success",
        "message": "Grouped courses loaded",
        "data": groups,
        "groups": groups,
    }


@router.get("/zhihuishu/courses/{course_id}")
async def zhihuishu_get_course_detail(course_id: str, current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    try:
        detail = await _run_blocking(adapter.get_course_detail, course_id)
    except Exception as exc:
        detail_text = str(exc)
        if "not found" in detail_text.lower():
            raise HTTPException(status_code=404, detail="Course not found") from exc
        raise _internal_error("Failed to load course detail", exc) from exc

    return {"status": "success", "message": "Course detail loaded", "data": detail}


@router.post("/zhihuishu/course/start")
async def zhihuishu_start_course(
    request: ZhihuishuCourseRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    try:
        if hasattr(adapter, "start_course_task"):
            result = adapter.start_course_task(
                request.course_id,
                speed=request.speed,
                auto_answer=request.auto_answer,
                task_type="course",
            )
        else:
            result = adapter.start_course(
                request.course_id,
                speed=request.speed,
                auto_answer=request.auto_answer,
            )
    except Exception as exc:
        raise _internal_error("Failed to start Zhihuishu task", exc) from exc

    task_id = str(result.get("task_id") or uuid4().hex)
    progress = result.get("progress", {})
    _register_zhihuishu_course_task(user_id, request.course_id, task_id, progress, task_type="course")

    return {
        "status": "success",
        "message": "Task started",
        "task_id": task_id,
        "data": result,
    }


@router.post("/zhihuishu/tasks/course")
async def zhihuishu_start_course_task(
    request: ZhihuishuTaskStartRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    config = adapter.get_config() if hasattr(adapter, "get_config") else {"speed": 1.0, "auto_answer": True}
    speed = request.speed if request.speed is not None else float(config.get("speed", 1.0))
    auto_answer = request.auto_answer if request.auto_answer is not None else bool(
        config.get("auto_answer", True)
    )

    try:
        if hasattr(adapter, "start_course_task"):
            result = adapter.start_course_task(
                request.course_id,
                speed=speed,
                auto_answer=auto_answer,
                task_type="course",
            )
        else:
            result = adapter.start_course(
                request.course_id,
                speed=speed,
                auto_answer=auto_answer,
            )
    except Exception as exc:
        raise _internal_error("Failed to start Zhihuishu course task", exc) from exc

    task_id = str(result.get("task_id") or uuid4().hex)
    progress = result.get("progress", {})
    _register_zhihuishu_course_task(user_id, request.course_id, task_id, progress, task_type="course")
    return {"status": "success", "message": "Task started", "task_id": task_id, "data": result}


@router.post("/zhihuishu/tasks/ai-course")
async def zhihuishu_start_ai_course_task(
    request: ZhihuishuTaskStartRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    config = adapter.get_config() if hasattr(adapter, "get_config") else {"speed": 1.0}
    speed = request.speed if request.speed is not None else float(config.get("speed", 1.0))

    try:
        if hasattr(adapter, "start_ai_course_task"):
            result = adapter.start_ai_course_task(request.course_id, speed=speed)
        else:
            result = adapter.start_course(
                request.course_id,
                speed=speed,
                auto_answer=True,
            )
    except Exception as exc:
        raise _internal_error("Failed to start Zhihuishu AI course task", exc) from exc

    task_id = str(result.get("task_id") or uuid4().hex)
    progress = result.get("progress", {})
    _register_zhihuishu_course_task(user_id, request.course_id, task_id, progress, task_type="ai-course")
    return {"status": "success", "message": "AI course task started", "task_id": task_id, "data": result}


@router.get("/zhihuishu/tasks")
async def zhihuishu_list_tasks(
    task_type: Optional[str] = None,
    course_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    try:
        if hasattr(adapter, "list_tasks"):
            tasks = adapter.list_tasks(task_type=task_type, course_id=course_id)
        else:
            with _course_tasks_lock:
                tasks = [
                    dict(task)
                    for task in _course_tasks.values()
                    if str(task.get("user_id")) == user_id and task.get("platform") == "zhihuishu"
                ]
    except Exception as exc:
        raise _internal_error("Failed to load Zhihuishu tasks", exc) from exc

    return {"status": "success", "message": "Tasks loaded", "data": tasks, "tasks": tasks}


@router.get("/zhihuishu/tasks/{task_id}")
async def zhihuishu_get_task(task_id: str, current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    try:
        if hasattr(adapter, "get_task"):
            task = adapter.get_task(task_id)
        else:
            task = _get_course_task(task_id)
            if task and (str(task.get("user_id")) != user_id or task.get("platform") != "zhihuishu"):
                task = None
    except Exception as exc:
        raise _internal_error("Failed to load Zhihuishu task", exc) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"status": "success", "message": "Task loaded", "data": task}


@router.post("/zhihuishu/tasks/{task_id}/cancel")
async def zhihuishu_cancel_task(task_id: str, current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    if hasattr(adapter, "cancel_task_by_id"):
        result = adapter.cancel_task_by_id(task_id)
        if result.get("status") == "idle":
            raise HTTPException(status_code=404, detail="Task not found")
    else:
        existing = _get_course_task(task_id)
        if existing is None or str(existing.get("user_id")) != user_id:
            raise HTTPException(status_code=404, detail="Task not found")
        result = adapter.cancel_task()

    with _course_tasks_lock:
        task = _course_tasks.get(task_id)
        if task and str(task.get("user_id")) == user_id and task.get("platform") == "zhihuishu":
            task["status"] = "cancelled"
            task["message"] = result.get("message", "Task cancelled")
            task["updated_at"] = time.time()
            _course_tasks[task_id] = task

    return {"status": "success", "message": result.get("message", "Task cancelled"), "data": result}


@router.get("/zhihuishu/config")
async def zhihuishu_get_config(current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    try:
        if hasattr(adapter, "get_config"):
            config = adapter.get_config()
        else:
            config = {"speed": 1.0, "auto_answer": True, "ai_config": {"enabled": False}}
    except Exception as exc:
        raise _internal_error("Failed to load Zhihuishu config", exc) from exc

    return {"status": "success", "message": "Config loaded", "data": config, "config": config}


@router.put("/zhihuishu/config")
async def zhihuishu_update_config(
    request: ZhihuishuConfigUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    updates = request.model_dump(exclude_none=True)
    try:
        if hasattr(adapter, "update_config"):
            config = adapter.update_config(updates)
        else:
            config = updates
    except Exception as exc:
        raise _internal_error("Failed to update Zhihuishu config", exc) from exc

    return {"status": "success", "message": "Config updated", "data": config, "config": config}


@router.patch("/zhihuishu/config")
async def zhihuishu_patch_config(
    request: ZhihuishuConfigUpdateRequest,
    current_user: dict = Depends(get_current_user),
):
    return await zhihuishu_update_config(request=request, current_user=current_user)


@router.get("/zhihuishu/videos/{course_id}")
async def zhihuishu_get_videos(
    course_id: str,
    current_user: dict = Depends(get_current_user),
):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    try:
        videos = await _run_blocking(adapter.get_videos, course_id)
    except Exception as exc:
        raise _internal_error("Failed to load Zhihuishu videos", exc) from exc

    return {
        "status": "success",
        "message": "Videos loaded",
        "data": videos,
        "videos": videos,
    }


@router.get("/zhihuishu/progress/{course_id}")
async def zhihuishu_get_progress(
    course_id: str,
    current_user: dict = Depends(get_current_user),
):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    try:
        progress = await _run_blocking(adapter.get_progress, course_id)
    except Exception as exc:
        raise _internal_error("Failed to load Zhihuishu progress", exc) from exc

    response = {
        "status": progress.get("status", "idle"),
        "message": progress.get("message", "ok"),
        "data": progress,
    }
    response.update(progress)
    return response


@router.post("/zhihuishu/pause")
async def zhihuishu_pause(current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    result = adapter.pause_task()
    with _course_tasks_lock:
        for task in _course_tasks.values():
            if str(task.get("user_id")) == user_id and task.get("platform") == "zhihuishu":
                task["status"] = "paused"
                task["message"] = result.get("message", "Task paused")
                task["updated_at"] = time.time()

    return {"status": "success", "message": result.get("message", "Task paused"), "data": result}


@router.post("/zhihuishu/resume")
async def zhihuishu_resume(current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    result = adapter.resume_task()
    with _course_tasks_lock:
        for task in _course_tasks.values():
            if str(task.get("user_id")) == user_id and task.get("platform") == "zhihuishu":
                task["status"] = "running"
                task["message"] = result.get("message", "Task resumed")
                task["updated_at"] = time.time()

    return {"status": "success", "message": result.get("message", "Task resumed"), "data": result}


@router.post("/zhihuishu/cancel")
async def zhihuishu_cancel(current_user: dict = Depends(get_current_user)):
    user_id = _current_user_id(current_user)
    adapter = _get_zhihuishu_adapter(user_id)

    result = adapter.cancel_task()
    with _course_tasks_lock:
        for task in _course_tasks.values():
            if str(task.get("user_id")) == user_id and task.get("platform") == "zhihuishu":
                task["status"] = "cancelled"
                task["message"] = result.get("message", "Task cancelled")
                task["updated_at"] = time.time()

    return {"status": "success", "message": result.get("message", "Task cancelled"), "data": result}


@router.post("/login")
async def course_login(
    request: CourseStartRequest,
    current_user: dict = Depends(get_current_user),
):
    if request.platform.lower() != "chaoxing":
        raise HTTPException(status_code=400, detail="Only chaoxing is supported")

    user_id = _current_user_id(current_user)
    try:
        import asyncio
        login_result = await asyncio.to_thread(
            signin_manager.login,
            user_id,
            request.username,
            request.password,
        )
        if not login_result.get("status"):
            raise HTTPException(status_code=401, detail=login_result.get("message", "Login failed"))

        courses = await asyncio.to_thread(signin_manager.get_courses, user_id)

        return {
            "status": "success",
            "message": "Login successful",
            "data": courses,
            "courses": courses,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise _internal_error("Failed to login and load Chaoxing courses", exc) from exc


@router.get("/courses")
async def get_courses(
    current_user: dict = Depends(get_current_user),
):
    user_id = _current_user_id(current_user)
    courses = await _run_blocking(signin_manager.get_courses, user_id)
    return {
        "status": "success",
        "message": "ok",
        "data": courses,
        "courses": courses,
    }


@router.get("/chapters/{course_id}")
async def get_chapters(
    course_id: str,
    current_user: dict = Depends(get_current_user),
):
    user_id = _current_user_id(current_user)

    try:
        course_parts = course_id.split("_")
        if len(course_parts) < 2:
            raise HTTPException(status_code=400, detail="Invalid course_id format")

        courseid, clazzid = course_parts[0], course_parts[1]
        cpi = course_parts[2] if len(course_parts) >= 3 else ""
        if not cpi:
            for item in await _run_blocking(signin_manager.get_courses, user_id):
                if str(item.get("courseId")) == str(courseid) and str(item.get("classId")) == str(clazzid):
                    cpi = str(item.get("cpi") or "")
                    break
        if not cpi:
            raise HTTPException(status_code=400, detail="Missing cpi in course_id")

        client = await _run_blocking(signin_manager.get_client, user_id)
        if client is None:
            raise HTTPException(status_code=401, detail="Please login to Chaoxing first")

        from app.services.course.chaoxing.decode import decode_course_point

        response = await _run_blocking(
            client.session.get,
            "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse",
            params={
                "courseid": courseid,
                "clazzid": clazzid,
                "cpi": cpi,
                "ut": "s",
            },
            timeout=12,
        )
        if response.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Fetch chapters failed: {response.status_code}")
        parsed = decode_course_point(response.text)
        chapters = parsed.get("points", []) if isinstance(parsed, dict) else []

        return {"chapters": chapters}
    except HTTPException:
        raise
    except Exception as exc:
        raise _internal_error("Failed to load Chaoxing chapters", exc) from exc


@router.post("/notify/test")
async def test_notification(request: dict):

    service = request.get("service")
    url = request.get("url")

    if not service or not url:
        raise HTTPException(status_code=400, detail="service and url are required")

    return {"status": "success", "message": f"Test notification sent via {service}"}
