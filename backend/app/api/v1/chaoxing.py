import asyncio
import base64
import binascii
import json
import logging
from typing import Annotated, Any

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, StringConstraints, ValidationError, field_validator
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.dependencies import get_current_user_id
from app.services.course.chaoxing.signin import QR_SESSION_NOT_FOUND, signin_manager
from app.services.course.chaoxing.task_admission import TaskAdmissionError

logger = logging.getLogger(__name__)

router = APIRouter()
PHOTON_BASE_URL = "https://photon.komoot.io"
PHOTON_HEADERS = {"User-Agent": "UniversityHelper/1.0"}
SUPPORTED_SIGN_TYPES = {
    "all",
    "normal",
    "photo",
    "location",
    "qrcode",
    "gesture",
    "code",
}
SIGN_TYPE_ALIASES = {
    "qr": "qrcode",
    "qr_code": "qrcode",
    "qr-code": "qrcode",
    "gesture_sign": "gesture",
    "signcode": "code",
    "passcode": "code",
}
MAX_PHOTO_BYTES = 5 * 1024 * 1024
PHOTO_READ_CHUNK_BYTES = 64 * 1024
ALLOWED_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
NonBlankShortString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
OptionalShortString = Annotated[str, StringConstraints(strip_whitespace=True, max_length=256)] | None
OptionalLongString = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1024)] | None
SelectorList = Annotated[list[NonBlankShortString], Field(max_length=100)]


def _decode_photo_base64(value: str) -> bytes:
    payload = value.strip()
    if payload.startswith("data:"):
        if "," not in payload:
            raise ValueError("photo_base64 data URL is invalid")
        metadata, payload = payload.split(",", 1)
        media_type = metadata[5:].split(";", 1)[0].lower()
        if media_type not in ALLOWED_IMAGE_TYPES:
            raise ValueError("photo_base64 uses an unsupported image type")
    if len(payload) > ((MAX_PHOTO_BYTES + 2) // 3) * 4 + 8:
        raise ValueError("photo exceeds the 5 MB limit")
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("photo_base64 must be valid base64") from exc
    if len(decoded) > MAX_PHOTO_BYTES:
        raise ValueError("photo exceeds the 5 MB limit")
    return decoded


class _ChaoxingCredentials(BaseModel):
    username: NonBlankShortString
    password: Annotated[str, StringConstraints(min_length=1, max_length=512)]


class _ChaoxingPhotoPayload(_ChaoxingCredentials):
    # The sign-in and task routes may omit the password: the server then reuses
    # the stored session bound to `username` (see
    # ChaoxingSigninManager._resolve_client). The username stays required — it
    # is what binds a reused cookie jar to an account, and adopting a jar
    # without it could silently act as a different Chaoxing account.
    # ChaoxingLoginRequest keeps min_length=1: it IS the password path.
    password: Annotated[str, StringConstraints(max_length=512)] = ""
    photo_base64: str | None = None
    photo: str | None = None

    @field_validator("photo_base64", "photo")
    @classmethod
    def validate_photo(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        _decode_photo_base64(value)
        return value


class ChaoxingLoginRequest(_ChaoxingCredentials):
    use_cookies: bool = False


class ChaoxingSignRequest(_ChaoxingPhotoPayload):
    sign_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)] = "all"
    course_id: OptionalShortString = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    address: OptionalLongString = None
    qr_code: OptionalLongString = None
    qrcode: Any | None = None
    location: Any | None = None
    sign_code: OptionalShortString = None
    gesture: OptionalShortString = None
    code: OptionalShortString = None
    object_id: OptionalShortString = None
    altitude: float | None = Field(default=None, ge=-1000, le=10000)


class ChaoxingClassSignRequest(ChaoxingSignRequest):
    class_id: NonBlankShortString
    active_id: OptionalShortString = None


class ChaoxingStartRequest(_ChaoxingPhotoPayload):
    course_list: SelectorList = Field(default_factory=list)
    speed: float = Field(default=1.0, gt=0, le=4)
    jobs: int = Field(default=1, ge=1, le=16)
    sign_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)] = "all"
    notopen_action: OptionalShortString = None
    tiku_config: dict[str, Any] = Field(default_factory=dict)
    notification_config: dict[str, Any] = Field(default_factory=dict)
    ocr_config: dict[str, Any] = Field(default_factory=dict)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    address: OptionalLongString = None
    qr_code: OptionalLongString = None
    qrcode: Any | None = None
    location: Any | None = None
    sign_code: OptionalShortString = None
    gesture: OptionalShortString = None
    code: OptionalShortString = None
    object_id: OptionalShortString = None
    altitude: float | None = Field(default=None, ge=-1000, le=10000)


class ChaoxingClassStartRequest(ChaoxingStartRequest):
    class_id: OptionalShortString = None
    class_list: SelectorList = Field(default_factory=list)
    active_id: OptionalShortString = None
    subject_type: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)] = "class"


def _request_photon_json(path: str, params: dict[str, Any]) -> Any:
    url = f"{PHOTON_BASE_URL}{path}"
    try:
        response = requests.get(url, params=params, headers=PHOTON_HEADERS, timeout=12)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("Geocoding service request failed: %s", exc)
        raise HTTPException(
            status_code=502, detail="Geocoding service temporarily unavailable"
        ) from exc

    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502, detail="Invalid geocoding service response"
        ) from exc


def _photon_feature_to_address(props: dict[str, Any]) -> str:
    parts = []
    for key in ("country", "state", "city", "district", "street", "name"):
        val = (props.get(key) or "").strip()
        if val and val not in parts:
            parts.append(val)
    return " ".join(parts) if parts else ""


def _parse_form_value(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    if text[0] in {"[", "{"}:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def _normalize_sign_type(value: Any) -> str:
    raw = str(value or "all").strip().lower()
    return SIGN_TYPE_ALIASES.get(raw, raw)


def _parse_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            try:
                loaded = json.loads(text)
            except json.JSONDecodeError:
                return None
            if isinstance(loaded, dict):
                return loaded
    return None


def _normalize_sign_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})

    if normalized.get("course_id") is None and normalized.get("courseId") is not None:
        normalized["course_id"] = normalized.get("courseId")
    if normalized.get("class_id") is None:
        for key in ("classId", "clazzId", "clazz_id"):
            if normalized.get(key) is not None:
                normalized["class_id"] = normalized.get(key)
                break
    if normalized.get("active_id") is None and normalized.get("activeId") is not None:
        normalized["active_id"] = normalized.get("activeId")
    if normalized.get("course_list") is None and normalized.get("courseList") is not None:
        normalized["course_list"] = normalized.get("courseList")
    if normalized.get("class_list") is None:
        for key in ("classList", "clazzList"):
            if normalized.get(key) is not None:
                normalized["class_list"] = normalized.get(key)
                break
    if normalized.get("object_id") is None and normalized.get("objectId") is not None:
        normalized["object_id"] = normalized.get("objectId")
    if normalized.get("latitude") is None and normalized.get("lat") is not None:
        normalized["latitude"] = normalized.get("lat")
    if normalized.get("longitude") is None and normalized.get("lng") is not None:
        normalized["longitude"] = normalized.get("lng")

    if "sign_type" not in normalized and normalized.get("type") is not None:
        normalized["sign_type"] = normalized.get("type")
    normalized["sign_type"] = _normalize_sign_type(normalized.get("sign_type"))

    qrcode = _parse_object(normalized.get("qrcode"))
    if qrcode:
        if not normalized.get("qr_code"):
            normalized["qr_code"] = (
                qrcode.get("qr_code")
                or qrcode.get("url")
                or qrcode.get("code")
                or qrcode.get("enc")
            )
        if normalized.get("latitude") is None:
            normalized["latitude"] = qrcode.get("latitude") or qrcode.get("lat")
        if normalized.get("longitude") is None:
            normalized["longitude"] = qrcode.get("longitude") or qrcode.get("lng")
        if not normalized.get("address"):
            normalized["address"] = qrcode.get("address")
        if normalized.get("altitude") is None:
            normalized["altitude"] = qrcode.get("altitude")
    elif not normalized.get("qr_code") and isinstance(normalized.get("qrcode"), str):
        normalized["qr_code"] = normalized.get("qrcode")

    location = _parse_object(normalized.get("location"))
    if location:
        if normalized.get("latitude") is None:
            normalized["latitude"] = location.get("latitude") or location.get("lat")
        if normalized.get("longitude") is None:
            normalized["longitude"] = location.get("longitude") or location.get("lng")
        if not normalized.get("address"):
            normalized["address"] = location.get("address") or location.get("name")
        if normalized.get("altitude") is None:
            normalized["altitude"] = location.get("altitude")

    sign_code = None
    for key in ("sign_code", "signCode", "gesture_code", "gesture", "code", "passcode"):
        value = normalized.get(key)
        if value is not None and str(value).strip():
            sign_code = str(value).strip()
            break
    if sign_code:
        normalized["sign_code"] = sign_code
        normalized.setdefault("gesture", sign_code)
        normalized.setdefault("code", sign_code)

    return normalized


def _ensure_supported_sign_type(sign_type: str) -> None:
    if sign_type not in SUPPORTED_SIGN_TYPES:
        valid = ", ".join(sorted(SUPPORTED_SIGN_TYPES))
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported sign_type: {sign_type}. Valid: {valid}",
        )


async def _read_limited_upload(upload: UploadFile | StarletteUploadFile) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(PHOTO_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_PHOTO_BYTES:
            raise HTTPException(status_code=413, detail="Photo exceeds the 5 MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


async def _parse_request_payload(raw_request: Request) -> dict[str, Any]:
    content_type = (raw_request.headers.get("content-type") or "").lower()
    if (
        "multipart/form-data" in content_type
        or "application/x-www-form-urlencoded" in content_type
    ):
        form = await raw_request.form(max_files=1, max_fields=100)
        payload: dict[str, Any] = {}
        for key, value in form.multi_items():
            if isinstance(value, (UploadFile, StarletteUploadFile)):
                if key == "photo":
                    media_type = (value.content_type or "").lower()
                    if media_type not in ALLOWED_IMAGE_TYPES:
                        raise HTTPException(
                            status_code=415,
                            detail=(
                                f"Unsupported file type: {media_type or 'unknown'}. "
                                f"Allowed: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}"
                            ),
                        )
                    file_bytes = await _read_limited_upload(value)
                    if file_bytes:
                        payload["photo_base64"] = base64.b64encode(file_bytes).decode(
                            "utf-8"
                        )
                continue
            payload[key] = _parse_form_value(str(value))
        return payload

    try:
        body = await raw_request.json()
    except json.JSONDecodeError:
        return {}
    return body if isinstance(body, dict) else {}


def _validate_payload(model_cls: Any, payload: dict[str, Any]) -> BaseModel:
    try:
        return model_cls.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


async def _run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


@router.get("/location/geocode")
async def chaoxing_location_geocode(
    query: str,
    user_id: str = Depends(get_current_user_id),
):
    keyword = query.strip()
    if not keyword:
        raise HTTPException(status_code=422, detail="query is required")

    data = await _run_blocking(
        _request_photon_json,
        "/api/",
        {"q": keyword, "limit": 1, "lang": "default"},
    )
    features = data.get("features") or []
    if not features:
        raise HTTPException(status_code=404, detail="未找到可用坐标")

    hit = features[0]
    coords = hit.get("geometry", {}).get("coordinates", [])
    props = hit.get("properties", {})
    if len(coords) < 2:
        raise HTTPException(status_code=404, detail="未找到可用坐标")

    return {
        "status": True,
        "message": "ok",
        "data": {
            "result": {
                "formatted_address": _photon_feature_to_address(props),
                "location": {"lat": coords[1], "lng": coords[0]},
            }
        },
    }


@router.get("/location/search")
async def chaoxing_location_search(
    query: str,
    user_id: str = Depends(get_current_user_id),
):
    keyword = query.strip()
    if not keyword:
        raise HTTPException(status_code=422, detail="query is required")

    data = await _run_blocking(
        _request_photon_json,
        "/api/",
        {"q": keyword, "limit": 10, "lang": "default"},
    )
    features = data.get("features") or []

    normalized = []
    for index, item in enumerate(features):
        coords = item.get("geometry", {}).get("coordinates", [])
        if len(coords) < 2:
            continue
        props = item.get("properties", {})
        try:
            lat = float(coords[1])
            lon = float(coords[0])
        except (TypeError, ValueError):
            continue
        normalized.append({
            "id": str(props.get("osm_id") or f"candidate-{index}"),
            "name": str(props.get("name") or "").strip(),
            "address": _photon_feature_to_address(props),
            "latitude": lat,
            "longitude": lon,
        })

    return {
        "status": True,
        "message": "ok",
        "data": {"results": normalized},
    }


@router.get("/location/reverse-geocode")
async def chaoxing_location_reverse_geocode(
    lat: float,
    lng: float,
    user_id: str = Depends(get_current_user_id),
):

    data = await _run_blocking(
        _request_photon_json,
        "/reverse",
        {"lat": lat, "lon": lng, "lang": "default"},
    )
    address = ""
    features = data.get("features") or [] if isinstance(data, dict) else []
    if features:
        props = features[0].get("properties", {})
        address = _photon_feature_to_address(props)
    return {
        "status": True,
        "message": "ok",
        "data": {"address": address, "latitude": lat, "longitude": lng},
    }


@router.post("/login")
async def chaoxing_login(
    request: ChaoxingLoginRequest,
    user_id: str = Depends(get_current_user_id),
):
    result = await _run_blocking(
        signin_manager.login,
        user_id=user_id,
        username=request.username,
        password=request.password,
    )
    if result.get("status"):
        return {
            "status": True,
            "message": result.get("message", "ok"),
            "data": result.get("data", {}),
        }
    return {
        "status": False,
        "message": result.get("message", "Login failed"),
        "data": {},
    }


@router.get("/session")
async def chaoxing_session(user_id: str = Depends(get_current_user_id)):
    """Report whether a stored Chaoxing session is usable. Never returns cookies."""
    state = await _run_blocking(signin_manager.get_session_state, user_id)
    return {
        "active": bool(state.get("active")),
        "username": state.get("username"),
        "expires_at": state.get("expires_at"),
    }


@router.delete("/session")
async def chaoxing_drop_session(user_id: str = Depends(get_current_user_id)):
    await _run_blocking(signin_manager.drop_session, user_id)
    return {"status": "success"}


def _qr_response(result: dict[str, Any]) -> dict[str, Any]:
    """Shape a manager QR result for the SPA.

    An unknown session id and one belonging to another user are both reported
    404 by the manager, so this cannot distinguish — and does not leak — which.
    """
    qr_status = str(result.get("qr_status") or "failed")
    if qr_status == QR_SESSION_NOT_FOUND:
        raise HTTPException(status_code=404, detail="二维码登录会话不存在或已过期")
    return {
        "session_id": result.get("session_id") or "",
        "status": qr_status,
        "message": result.get("message") or "",
        "qr_code": result.get("qr_code"),
        "qr_content_type": result.get("qr_content_type") or "",
        "username": result.get("username"),
    }


@router.post("/qr-login")
async def chaoxing_qr_login(user_id: str = Depends(get_current_user_id)):
    """Start a 学习通 QR-code login and return the first image.

    The image comes back as base64 PNG in ``qr_code``; the SPA renders it as a
    data URI and then polls the status route below.
    """
    result = await _run_blocking(signin_manager.start_qr_login, user_id)
    if result.get("qr_status") == "failed" and not result.get("session_id"):
        # Nothing was created, so there is no session id to poll: this is
        # upstream refusing to hand out a QR, not a client error.
        raise HTTPException(status_code=502, detail=result.get("message") or "无法生成二维码")
    return _qr_response(result)


@router.get("/qr-login/{session_id}")
async def chaoxing_qr_login_status(session_id: str, user_id: str = Depends(get_current_user_id)):
    """Poll one QR login.

    ``status`` is one of ``pending`` / ``scanned`` / ``success`` / ``failed``.
    A refreshed ``qr_code`` rides along when the previous code expired, so the
    browser can keep showing a scannable image without a new round trip.
    """
    result = await _run_blocking(signin_manager.poll_qr_login, user_id, session_id)
    return _qr_response(result)


@router.delete("/qr-login/{session_id}")
async def chaoxing_qr_login_cancel(session_id: str, user_id: str = Depends(get_current_user_id)):
    dropped = await _run_blocking(signin_manager.cancel_qr_login, user_id, session_id)
    if not dropped:
        raise HTTPException(status_code=404, detail="二维码登录会话不存在或已过期")
    return {"status": "success"}


@router.get("/courses")
async def chaoxing_courses(user_id: str = Depends(get_current_user_id)):
    courses = await _run_blocking(signin_manager.get_courses, user_id)
    return {
        "status": True,
        "message": "ok",
        "data": courses,
        "courses": courses,
    }


@router.get("/courses/grouped")
async def chaoxing_grouped_courses(user_id: str = Depends(get_current_user_id)):
    groups = await _run_blocking(signin_manager.get_grouped_courses, user_id)
    return {
        "status": "success",
        "message": "Grouped courses loaded",
        "data": groups,
        "groups": groups,
    }


@router.get("/classes")
async def chaoxing_classes(user_id: str = Depends(get_current_user_id)):
    classes = await _run_blocking(signin_manager.get_classes, user_id)
    return {
        "status": True,
        "message": "ok",
        "data": classes,
        "classes": classes,
    }


@router.get("/classes/{class_id}/activities")
async def chaoxing_class_activities(
    class_id: str,
    course_id: str | None = None,
    include_details: bool = True,
    user_id: str = Depends(get_current_user_id),
):
    activities = await _run_blocking(
        signin_manager.get_class_activities,
        user_id=user_id,
        class_id=class_id,
        course_id=course_id,
        include_details=include_details,
    )
    return {
        "status": True,
        "message": "ok",
        "data": activities,
        "activities": activities,
    }


@router.get("/remote-endpoints")
async def chaoxing_remote_endpoints(
    course_id: str | None = None,
    class_id: str | None = None,
    active_id: str | None = None,
    user_id: str = Depends(get_current_user_id),
):
    endpoints = await _run_blocking(
        signin_manager.get_remote_endpoints,
        user_id=user_id,
        course_id=course_id,
        class_id=class_id,
        active_id=active_id,
    )
    return {
        "status": True,
        "message": "ok",
        "data": endpoints,
        "remoteEndpoints": endpoints,
    }


@router.get("/tasks")
async def chaoxing_tasks(user_id: str = Depends(get_current_user_id)):
    tasks = await _run_blocking(
        signin_manager.get_active_tasks, user_id=user_id, sign_type="all"
    )
    return {"status": True, "message": "ok", "data": tasks}


@router.get("/task-list")
async def chaoxing_task_list(user_id: str = Depends(get_current_user_id)):
    tasks = await _run_blocking(signin_manager.list_tasks, user_id=user_id)
    return {"status": True, "message": "ok", "data": tasks}


@router.get("/history")
async def chaoxing_history(user_id: str = Depends(get_current_user_id)):
    history = await _run_blocking(signin_manager.get_history, user_id)
    return {"status": True, "message": "ok", "data": history}


@router.post("/sign")
async def chaoxing_sign(
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    payload = _normalize_sign_payload(await _parse_request_payload(raw_request))
    request = _validate_payload(ChaoxingSignRequest, payload)
    _ensure_supported_sign_type(request.sign_type)

    result = await _run_blocking(
        signin_manager.sign_once,
        user_id=user_id,
        username=request.username,
        password=request.password,
        sign_type=request.sign_type,
        course_id=request.course_id,
        options=request.model_dump(),
    )
    return {
        "status": bool(result.get("status")),
        "message": result.get("message", ""),
        "data": result.get("data", {}),
    }


@router.post("/class-sign")
async def chaoxing_class_sign(
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    payload = _normalize_sign_payload(await _parse_request_payload(raw_request))
    request = _validate_payload(ChaoxingClassSignRequest, payload)
    _ensure_supported_sign_type(request.sign_type)

    result = await _run_blocking(
        signin_manager.sign_class_once,
        user_id=user_id,
        username=request.username,
        password=request.password,
        class_id=request.class_id,
        sign_type=request.sign_type,
        active_id=request.active_id,
        course_id=request.course_id,
        options=request.model_dump(),
    )
    return {
        "status": bool(result.get("status")),
        "message": result.get("message", ""),
        "data": result.get("data", {}),
    }


@router.post("/classes/{class_id}/sign")
async def chaoxing_class_sign_by_path(
    class_id: str,
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    payload = _normalize_sign_payload(await _parse_request_payload(raw_request))
    payload["class_id"] = payload.get("class_id") or class_id
    request = _validate_payload(ChaoxingClassSignRequest, payload)
    _ensure_supported_sign_type(request.sign_type)

    result = await _run_blocking(
        signin_manager.sign_class_once,
        user_id=user_id,
        username=request.username,
        password=request.password,
        class_id=request.class_id,
        sign_type=request.sign_type,
        active_id=request.active_id,
        course_id=request.course_id,
        options=request.model_dump(),
    )
    return {
        "status": bool(result.get("status")),
        "message": result.get("message", ""),
        "data": result.get("data", {}),
    }


@router.post("/start")
async def chaoxing_start(
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    payload = _normalize_sign_payload(await _parse_request_payload(raw_request))
    request = _validate_payload(ChaoxingStartRequest, payload)
    _ensure_supported_sign_type(request.sign_type)

    try:
        task_id = await _run_blocking(signin_manager.start_task, user_id=user_id, payload=request.model_dump())
    except TaskAdmissionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {
        "status": True,
        "message": "Task started",
        "data": {"task_id": task_id},
    }


@router.post("/class-start")
async def chaoxing_class_start(
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    payload = _normalize_sign_payload(await _parse_request_payload(raw_request))
    request = _validate_payload(ChaoxingClassStartRequest, payload)
    _ensure_supported_sign_type(request.sign_type)

    try:
        task_id = await _run_blocking(
            signin_manager.start_class_task,
            user_id=user_id,
            payload=request.model_dump(),
        )
    except TaskAdmissionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {
        "status": True,
        "message": "Class task started",
        "data": {"task_id": task_id},
    }


@router.post("/classes/{class_id}/start")
async def chaoxing_class_start_by_path(
    class_id: str,
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    payload = _normalize_sign_payload(await _parse_request_payload(raw_request))
    payload["class_id"] = payload.get("class_id") or class_id
    request = _validate_payload(ChaoxingClassStartRequest, payload)
    _ensure_supported_sign_type(request.sign_type)

    try:
        task_id = await _run_blocking(
            signin_manager.start_class_task,
            user_id=user_id,
            payload=request.model_dump(),
        )
    except TaskAdmissionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {
        "status": True,
        "message": "Class task started",
        "data": {"task_id": task_id},
    }


@router.get("/task/{task_id}")
async def chaoxing_task(task_id: str, user_id: str = Depends(get_current_user_id)):
    task = await _run_blocking(
        signin_manager.get_task, user_id=user_id, task_id=task_id
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": True, "message": "ok", "data": task}


@router.get("/logs/{task_id}")
async def chaoxing_logs(
    task_id: str,
    cursor: int | None = None,
    user_id: str = Depends(get_current_user_id),
):
    log_state = await _run_blocking(
        signin_manager.get_task_logs, user_id=user_id, task_id=task_id, cursor=cursor
    )
    if log_state is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "status": True,
        "message": "ok",
        "data": log_state.get("logs", []),
        "cursor": log_state.get("cursor", 0),
    }
