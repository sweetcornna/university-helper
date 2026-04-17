import asyncio
import base64
import json
import logging
from typing import Any, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.config import settings
from app.dependencies import get_current_user
from app.services.course.chaoxing.signin import signin_manager

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


class ChaoxingLoginRequest(BaseModel):
    username: str
    password: str
    use_cookies: bool = False


class ChaoxingSignRequest(BaseModel):
    username: str
    password: str
    sign_type: str = "all"
    course_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    qr_code: Optional[str] = None
    qrcode: Optional[Any] = None
    location: Optional[Any] = None
    sign_code: Optional[str] = None
    gesture: Optional[str] = None
    code: Optional[str] = None
    object_id: Optional[str] = None
    photo_base64: Optional[str] = None
    photo: Optional[str] = None
    altitude: Optional[float] = None


class ChaoxingStartRequest(BaseModel):
    username: str
    password: str
    course_list: List[str] = Field(default_factory=list)
    speed: float = 1.0
    jobs: int = 1
    sign_type: str = "all"
    notopen_action: Optional[str] = None
    tiku_config: Dict[str, Any] = Field(default_factory=dict)
    notification_config: Dict[str, Any] = Field(default_factory=dict)
    ocr_config: Dict[str, Any] = Field(default_factory=dict)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    qr_code: Optional[str] = None
    qrcode: Optional[Any] = None
    location: Optional[Any] = None
    sign_code: Optional[str] = None
    gesture: Optional[str] = None
    code: Optional[str] = None
    object_id: Optional[str] = None
    photo_base64: Optional[str] = None
    photo: Optional[str] = None
    altitude: Optional[float] = None


def _request_photon_json(path: str, params: Dict[str, Any]) -> Any:
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


def _photon_feature_to_address(props: Dict[str, Any]) -> str:
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


def _parse_object(value: Any) -> Optional[Dict[str, Any]]:
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


def _normalize_sign_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload or {})

    if normalized.get("course_id") is None and normalized.get("courseId") is not None:
        normalized["course_id"] = normalized.get("courseId")
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


async def _parse_request_payload(raw_request: Request) -> Dict[str, Any]:
    content_type = (raw_request.headers.get("content-type") or "").lower()
    if (
        "multipart/form-data" in content_type
        or "application/x-www-form-urlencoded" in content_type
    ):
        form = await raw_request.form()
        payload: Dict[str, Any] = {}
        ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        for key, value in form.multi_items():
            if isinstance(value, (UploadFile, StarletteUploadFile)):
                if key == "photo":
                    if value.content_type not in ALLOWED_IMAGE_TYPES:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Unsupported file type: {value.content_type}. Allowed: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}",
                        )
                    file_bytes = await value.read()
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


def _validate_payload(model_cls: Any, payload: Dict[str, Any]) -> BaseModel:
    try:
        return model_cls.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


async def _run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


@router.get("/location/geocode")
async def chaoxing_location_geocode(query: str):
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
async def chaoxing_location_search(query: str):
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
async def chaoxing_location_reverse_geocode(lat: float, lng: float):

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
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

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


@router.get("/courses")
async def chaoxing_courses(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    courses = await _run_blocking(signin_manager.get_courses, user_id)
    return {
        "status": True,
        "message": "ok",
        "data": courses,
        "courses": courses,
    }


@router.get("/tasks")
async def chaoxing_tasks(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    tasks = await _run_blocking(
        signin_manager.get_active_tasks, user_id=user_id, sign_type="all"
    )
    return {"status": True, "message": "ok", "data": tasks}


@router.get("/task-list")
async def chaoxing_task_list(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    tasks = await _run_blocking(signin_manager.list_tasks, user_id=user_id)
    return {"status": True, "message": "ok", "data": tasks}


@router.get("/history")
async def chaoxing_history(current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    history = await _run_blocking(signin_manager.get_history, user_id)
    return {"status": True, "message": "ok", "data": history}


@router.post("/sign")
async def chaoxing_sign(
    raw_request: Request,
    current_user: dict = Depends(get_current_user),
):
    payload = _normalize_sign_payload(await _parse_request_payload(raw_request))
    request = _validate_payload(ChaoxingSignRequest, payload)
    _ensure_supported_sign_type(request.sign_type)
    user_id = str(current_user.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

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


@router.post("/start")
async def chaoxing_start(
    raw_request: Request,
    current_user: dict = Depends(get_current_user),
):
    payload = _normalize_sign_payload(await _parse_request_payload(raw_request))
    request = _validate_payload(ChaoxingStartRequest, payload)
    _ensure_supported_sign_type(request.sign_type)
    user_id = str(current_user.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    task_id = await _run_blocking(
        signin_manager.start_task, user_id=user_id, payload=request.model_dump()
    )
    return {
        "status": True,
        "message": "Task started",
        "data": {"task_id": task_id},
    }


@router.get("/task/{task_id}")
async def chaoxing_task(task_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    task = await _run_blocking(
        signin_manager.get_task, user_id=user_id, task_id=task_id
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": True, "message": "ok", "data": task}


@router.get("/logs/{task_id}")
async def chaoxing_logs(task_id: str, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    logs = await _run_blocking(
        signin_manager.get_task_logs, user_id=user_id, task_id=task_id
    )
    if logs is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": True, "message": "ok", "data": logs}
