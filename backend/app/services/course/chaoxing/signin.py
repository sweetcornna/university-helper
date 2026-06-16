import base64
import binascii
import html
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse
from uuid import uuid4

import requests
from bs4 import BeautifulSoup

from ..task_store import task_store

try:
    from Crypto.Cipher import AES, DES
    from Crypto.Util.Padding import pad
except Exception:  # pragma: no cover - crypto lib fallback
    AES = None
    DES = None

    def pad(raw: bytes, block_size: int) -> bytes:
        padding = block_size - (len(raw) % block_size)
        return raw + bytes([padding] * padding)


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

LOGIN_URL = "https://passport2.chaoxing.com/fanyalogin"
COURSE_LIST_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"
INTERACTION_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"
COURSE_LIST_REFERER = (
    "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/interaction"
    "?moocDomain=https://mooc1-1.chaoxing.com/mooc-ans"
)
ACTIVE_LIST_URL = "https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist"
PPT_ACTIVE_INFO_URL = "https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo"
PRE_SIGN_URL = "https://mobilelearn.chaoxing.com/newsign/preSign"
PPT_SIGN_URL = "https://mobilelearn.chaoxing.com/pptSign/stuSignajax"
PAN_TOKEN_URL = "https://pan-yz.chaoxing.com/api/token/uservalid"
PAN_UPLOAD_URL = "https://pan-yz.chaoxing.com/upload"

logger = logging.getLogger(__name__)
SIGNIN_TASK_KIND = "chaoxing_signin"
SIGNIN_HISTORY_KIND = "chaoxing_signin_history"
INTERRUPTED_TASK_STATUSES = {"running", "pending", "paused", "cancelling"}
RESTART_INTERRUPTED_MESSAGE = "Task interrupted due to service restart"
UNEXPECTED_WORKER_ERROR_PREFIX = "Unexpected task failure"
USER_TASK_LOAD_LIMIT = 2000
BACKGROUND_TASK_ACTIVE_STATUSES = {"running", "pending", "paused", "cancelling"}
TASK_FEED_FALLBACK_LIMIT = 3

# Character windows used by the fallback parsers in _parse_courses to bound
# how far apart related tokens (course id / class id / cpi / name) may appear
# within the raw HTML+JS response before they are treated as unrelated.
_PARSE_SNIPPET_BEFORE = 320
_PARSE_SNIPPET_AFTER = 980
_FALLBACK_ID_PAIR_GAP = 240
_FALLBACK_JSON_IDS_GAP = 120
_FALLBACK_JSON_NAME_GAP_IDS = 180
_FALLBACK_JSON_NAME_GAP_NAME = 220
_FALLBACK_HIDDEN_INPUT_BEFORE = 360
_FALLBACK_HIDDEN_INPUT_AFTER = 1400


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_enc(qr_code: str) -> str:
    raw = (qr_code or "").strip()
    if not raw:
        return ""
    if "enc=" not in raw:
        return raw
    parsed = urlparse(raw)
    values = parse_qs(parsed.query).get("enc")
    if values:
        return values[0]
    start = raw.find("enc=") + 4
    end = raw.find("&", start)
    return raw[start:] if end == -1 else raw[start:end]


def _parse_course_filter(course_filter: str) -> tuple[Optional[str], Optional[str]]:
    if not course_filter:
        return None, None
    raw = str(course_filter or "").strip()
    if ":" in raw:
        values = raw.split(":")
        if len(values) >= 2 and values[0] and values[1]:
            return values[0], values[1]
        return values[0] if values else None, None
    values = raw.split("_")
    if len(values) >= 2 and values[0] and values[1]:
        return values[0], values[1]
    return values[0], None


def _as_filter_set(values: Optional[Any]) -> set[str]:
    if values is None:
        return set()
    source = values if isinstance(values, list) else [values]
    return {str(item or "").strip() for item in source if str(item or "").strip()}


def _course_selector(course: Dict[str, Any]) -> str:
    course_id = str(course.get("courseId") or course.get("rawCourseId") or "").strip()
    class_id = str(course.get("classId") or course.get("clazzId") or "").strip()
    cpi = str(course.get("cpi") or "").strip()
    if course_id and class_id:
        return f"{course_id}_{class_id}_{cpi}" if cpi else f"{course_id}_{class_id}"
    return course_id or class_id


def _remote_request_url(base_url: str, params: Dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value not in (None, "")}
    query = urlencode(clean_params)
    return f"{base_url}?{query}" if query else base_url


def build_remote_sign_endpoints(
    course_id: str = "",
    class_id: str = "",
    active_id: str = "",
    uid: str = "",
    fid: str = "",
) -> Dict[str, Any]:
    course_id = str(course_id or "").strip()
    class_id = str(class_id or "").strip()
    active_id = str(active_id or "").strip()
    uid = str(uid or "").strip()
    fid = str(fid or "").strip()

    activity_params = {
        "fid": fid or 0,
        "courseId": course_id,
        "classId": class_id,
        "_": int(time.time() * 1000),
    }
    pre_sign_params = {
        "courseId": course_id,
        "classId": class_id,
        "activePrimaryId": active_id,
        "general": 1,
        "sys": 1,
        "ls": 1,
        "appType": 15,
        "tid": "",
        "uid": uid,
        "ut": "s",
    }
    submit_params = {
        "activeId": active_id,
        "uid": uid,
        "clientip": "",
        "latitude": -1,
        "longitude": -1,
        "appType": 15,
        "fid": fid,
    }

    def endpoint(name: str, base_url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": name,
            "method": "GET",
            "baseUrl": base_url,
            "params": params,
            "url": _remote_request_url(base_url, params),
            "credentials": "include",
            "requiresChaoxingLogin": True,
        }

    return {
        "source": "chaoxing",
        "directBrowserRequest": True,
        "browserRequestMode": "remote-direct",
        "subjectType": "class" if class_id else "course",
        "courseId": course_id,
        "classId": class_id,
        "activeId": active_id,
        "endpoints": {
            "activities": endpoint("班级/课程活动列表", ACTIVE_LIST_URL, activity_params),
            "activeDetail": endpoint("活动详情", PPT_ACTIVE_INFO_URL, {"activeId": active_id}),
            "preSign": endpoint("签到预处理", PRE_SIGN_URL, pre_sign_params),
            "submitSign": endpoint("提交签到", PPT_SIGN_URL, submit_params),
            "photoToken": endpoint("拍照上传令牌", PAN_TOKEN_URL, {}),
        },
        "uploadEndpoints": {
            "photoUpload": {
                "name": "拍照图片上传",
                "method": "POST",
                "baseUrl": PAN_UPLOAD_URL,
                "params": {"_from": "mobilelearn"},
                "url": _remote_request_url(PAN_UPLOAD_URL, {"_from": "mobilelearn"}),
                "credentials": "include",
                "requiresChaoxingLogin": True,
            }
        },
    }


class ChaoxingSigninClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.username = ""
        self.account_name = ""

    @property
    def uid(self) -> str:
        return (
            self.session.cookies.get("_uid")
            or self.session.cookies.get("UID")
            or ""
        )

    @property
    def fid(self) -> str:
        return self.session.cookies.get("fid") or "-1"

    def _encrypt_des(self, raw_text: str) -> str:
        if DES is None:
            return raw_text
        key = "u2oh6Vu^HWe40fj".encode("utf-8")[:8]
        cipher = DES.new(key, DES.MODE_ECB)
        encrypted = cipher.encrypt(pad(raw_text.encode("utf-8"), DES.block_size))
        return binascii.hexlify(encrypted).decode("utf-8")

    def _encrypt_aes(self, raw_text: str) -> str:
        if AES is None:
            return raw_text
        key = "u2oh6Vu^HWe4_AES".encode("utf-8")
        cipher = AES.new(key, AES.MODE_CBC, iv=key)
        encrypted = cipher.encrypt(pad(raw_text.encode("utf-8"), AES.block_size))
        return base64.b64encode(encrypted).decode("utf-8")

    @staticmethod
    def _safe_json(resp: requests.Response) -> Dict[str, Any]:
        try:
            return resp.json()
        except Exception:
            return {}

    def login(self, username: str, password: str) -> Dict[str, Any]:
        self.username = username

        login_attempts = [
            {
                "uname": username,
                "password": self._encrypt_des(password),
                "fid": "-1",
                "t": "true",
                "refer": "https%3A%2F%2Fi.chaoxing.com",
                "forbidotherlogin": "0",
                "validate": "",
            },
            {
                "uname": self._encrypt_aes(username),
                "password": self._encrypt_aes(password),
                "fid": "-1",
                "t": "true",
                "refer": "https%3A%2F%2Fi.chaoxing.com",
                "forbidotherlogin": "0",
                "validate": "",
                "doubleFactorLogin": "0",
                "independentId": "0",
            },
        ]

        last_message = "Login failed"
        for payload in login_attempts:
            try:
                resp = self.session.post(
                    LOGIN_URL,
                    headers={"X-Requested-With": "XMLHttpRequest"},
                    data=payload,
                    timeout=15,
                )
            except requests.RequestException as exc:
                last_message = str(exc)
                continue

            data = self._safe_json(resp)
            if data.get("status") is True and self.uid:
                self.account_name = self._fetch_account_name() or username
                return {
                    "status": True,
                    "message": "Login successful",
                    "data": {
                        "uid": self.uid,
                        "fid": self.fid,
                        "name": self.account_name,
                    },
                }

            last_message = (
                data.get("msg2")
                or data.get("msg")
                or data.get("message")
                or last_message
            )

        return {"status": False, "message": last_message}

    def _fetch_account_name(self) -> str:
        try:
            resp = self.session.get(
                "https://passport2.chaoxing.com/mooc/accountManage",
                timeout=12,
            )
        except requests.RequestException:
            return ""

        marker = 'id="messageName"'
        idx = resp.text.find(marker)
        if idx == -1:
            return ""
        snippet = resp.text[idx: idx + 180]
        name_match = re.search(r">([^<]+)</", snippet)
        if not name_match:
            return ""
        return html.unescape(name_match.group(1).strip())

    def get_courses(self) -> List[Dict[str, Any]]:
        course_folders = [0]
        course_folders.extend(self._parse_course_folders())

        seen_folders: set[str] = set()
        seen_courses: set[tuple[str, str]] = set()
        merged_courses: List[Dict[str, Any]] = []

        for folder_id in course_folders:
            folder_key = str(folder_id)
            if not folder_key or folder_key in seen_folders:
                continue
            seen_folders.add(folder_key)

            try:
                resp = self.session.post(
                    COURSE_LIST_URL,
                    headers={"Referer": COURSE_LIST_REFERER},
                    data={
                        "courseType": 1,
                        "courseFolderId": folder_key,
                        "query": "",
                        "superstarClass": 0,
                    },
                    timeout=12,
                )
            except requests.RequestException:
                continue

            for course in self._parse_courses(resp.text):
                course_id = str(course.get("courseId") or "")
                class_id = str(course.get("classId") or "")
                key = (course_id, class_id)
                if not course_id or not class_id or key in seen_courses:
                    continue
                seen_courses.add(key)
                merged_courses.append(course)

        return merged_courses

    def _parse_course_folders(self) -> List[str]:
        try:
            resp = self.session.get(INTERACTION_URL, timeout=12)
        except requests.RequestException:
            return []

        content = resp.text or ""
        seen: set[str] = set()
        folders: List[str] = []
        for pattern in (
            r'fileid=["\'](\d+)["\']',
            r'data-fileid=["\'](\d+)["\']',
            r'courseFolderId["\']?\s*[:=]\s*["\']?(\d+)["\']?',
        ):
            for match in re.finditer(pattern, content, flags=re.IGNORECASE):
                folder_id = match.group(1)
                if folder_id not in seen:
                    seen.add(folder_id)
                    folders.append(folder_id)
        return folders

    def _parse_courses(self, content: str) -> List[Dict[str, Any]]:
        course_index: dict[tuple[str, str], int] = {}
        courses: List[Dict[str, Any]] = []

        def _normalize_name(raw_name: str, course_id: str) -> str:
            value = html.unescape((raw_name or "").strip())
            if not value:
                return f"Course {course_id}"
            return value

        def _is_placeholder_name(name: str, course_id: str) -> bool:
            normalized = (name or "").strip().lower()
            return not normalized or normalized == f"course {course_id}".lower()

        def _extract_name(snippet: str, course_id: str) -> str:
            patterns = (
                r'class=["\'][^"\']*course-name[^"\']*["\'][^>]*title=["\']([^"\']+)["\']',
                r'class=["\'][^"\']*course-name[^"\']*["\'][^>]*>\s*([^<]+)\s*<',
                r'"(?:courseName|name|title)"\s*:\s*"([^"]+)"',
                r"'(?:courseName|name|title)'\s*:\s*'([^']+)'",
                r'data-name=["\']([^"\']+)["\']',
                r'title=["\']([^"\']+)["\']',
            )
            for pattern in patterns:
                match = re.search(pattern, snippet, flags=re.IGNORECASE)
                if match:
                    return _normalize_name(match.group(1), course_id)
            return f"Course {course_id}"

        def append_course(
            course_id: str,
            class_id: str,
            cursor: int,
            preferred_name: str = "",
            preferred_cpi: str = "",
        ) -> None:
            course_id = (course_id or "").strip()
            class_id = (class_id or "").strip()
            if not course_id or not class_id:
                return
            key = (course_id, class_id)
            if key in course_index:
                item = courses[course_index[key]]
                normalized_name = _normalize_name(preferred_name, course_id)
                if preferred_cpi and not item.get("cpi"):
                    item["cpi"] = preferred_cpi
                    item["id"] = f"{course_id}_{class_id}_{preferred_cpi}"
                if preferred_name and _is_placeholder_name(str(item.get("courseName", "")), course_id):
                    item["name"] = normalized_name
                    item["courseName"] = normalized_name
                return

            start = max(0, cursor - _PARSE_SNIPPET_BEFORE)
            end = min(len(content), cursor + _PARSE_SNIPPET_AFTER)
            snippet = content[start:end]

            cpi_match = re.search(r"(?:[?&]cpi=|\"cpi\"\s*:\s*\"?)(\d+)", snippet)
            cpi = preferred_cpi or (cpi_match.group(1) if cpi_match else "")
            name = (
                _normalize_name(preferred_name, course_id)
                if preferred_name
                else _extract_name(snippet, course_id)
            )

            course_key = f"{course_id}_{class_id}_{cpi}" if cpi else f"{course_id}_{class_id}"
            courses.append(
                {
                    "id": course_key,
                    "courseId": course_id,
                    "classId": class_id,
                    "cpi": cpi,
                    "name": name,
                    "courseName": name,
                }
            )
            course_index[key] = len(courses) - 1

        # Structured parser: parse course cards directly for more reliable name extraction.
        try:
            soup = BeautifulSoup(content, "lxml")
        except Exception:
            soup = None

        if soup is not None:
            for card in soup.select("div.course, li.course, div[id^='course_'], li[id^='course_']"):
                course_id = ""
                class_id = ""
                cpi = ""
                name = ""

                id_match = re.search(r"course_(\d+)_(\d+)", str(card.get("id") or ""))
                if id_match:
                    course_id, class_id = id_match.group(1), id_match.group(2)

                course_input = card.select_one("input.courseId, input[class*='courseId'], input[name*='courseId']")
                class_input = card.select_one("input.clazzId, input.classId, input[class*='clazzId'], input[class*='classId'], input[name*='clazzId'], input[name*='classId']")
                if not course_id and course_input:
                    course_id = str(course_input.get("value") or "").strip()
                if not class_id and class_input:
                    class_id = str(class_input.get("value") or "").strip()

                link = card.select_one("a[href]")
                href = str(link.get("href") or "") if link else ""
                if href:
                    if not course_id:
                        match = re.search(r"(?:courseid|courseId)=(\d+)", href, flags=re.IGNORECASE)
                        if match:
                            course_id = match.group(1)
                    if not class_id:
                        match = re.search(r"(?:clazzid|classId)=(\d+)", href, flags=re.IGNORECASE)
                        if match:
                            class_id = match.group(1)
                    match = re.search(r"(?:[?&]cpi=)(\d+)", href, flags=re.IGNORECASE)
                    if match:
                        cpi = match.group(1)

                for attr in ("data-courseid", "courseid"):
                    if not course_id and card.get(attr):
                        course_id = str(card.get(attr)).strip()
                for attr in ("data-clazzid", "data-classid", "clazzid", "classid"):
                    if not class_id and card.get(attr):
                        class_id = str(card.get(attr)).strip()

                name_node = card.select_one(".course-name")
                if name_node:
                    name = str(name_node.get("title") or name_node.get_text(" ", strip=True) or "").strip()
                if not name and link:
                    name = str(link.get("title") or link.get_text(" ", strip=True) or "").strip()
                if not name:
                    heading = card.select_one("h3, h4, strong")
                    if heading:
                        name = heading.get_text(" ", strip=True)

                info_raw = card.get("info") or card.get("data-info")
                if info_raw:
                    decoded = html.unescape(str(info_raw))
                    for candidate in (decoded, decoded.replace("'", '"')):
                        try:
                            payload = json.loads(candidate)
                        except Exception:
                            continue
                        if isinstance(payload, dict):
                            course_id = course_id or str(payload.get("courseId") or payload.get("courseid") or "")
                            class_id = class_id or str(payload.get("classId") or payload.get("clazzId") or payload.get("clazzid") or "")
                            cpi = cpi or str(payload.get("cpi") or "")
                            name = name or str(payload.get("courseName") or payload.get("name") or payload.get("title") or "")
                            break

                if course_id and class_id:
                    cursor = content.find(f"{course_id}_{class_id}")
                    append_course(course_id, class_id, cursor if cursor >= 0 else 0, preferred_name=name, preferred_cpi=cpi)

        # Primary parser
        for match in re.finditer(r"course_(\d+)_(\d+)", content):
            append_course(match.group(1), match.group(2), match.start())

        def _run_id_pair_fallback() -> None:
            """Fallback: paired course/class ids in href query or compact JSON."""
            gap_query = _FALLBACK_ID_PAIR_GAP
            gap_json = _FALLBACK_JSON_IDS_GAP
            patterns = (
                (rf"(?:courseid|courseId)=(\d+)[^\"'<>]{{0,{gap_query}}}(?:clazzid|classId)=(\d+)", False),
                (rf"(?:clazzid|classId)=(\d+)[^\"'<>]{{0,{gap_query}}}(?:courseid|courseId)=(\d+)", True),
                (rf'"courseId"\s*:\s*"?(\d+)"?[\s\S]{{0,{gap_json}}}?"(?:classId|clazzId)"\s*:\s*"?(\d+)"?', False),
                (rf'"(?:classId|clazzId)"\s*:\s*"?(\d+)"?[\s\S]{{0,{gap_json}}}?"courseId"\s*:\s*"?(\d+)"?', True),
            )
            for pattern, reverse_pair in patterns:
                for match in re.finditer(pattern, content, flags=re.IGNORECASE):
                    if reverse_pair:
                        append_course(match.group(2), match.group(1), match.start())
                    else:
                        append_course(match.group(1), match.group(2), match.start())

        def _run_json_named_fallback() -> None:
            """Fallback: JSON blocks carrying an explicit course name near the ids."""
            gap_ids = _FALLBACK_JSON_NAME_GAP_IDS
            gap_name = _FALLBACK_JSON_NAME_GAP_NAME
            patterns = (
                (
                    rf'"courseId"\s*:\s*"?(\d+)"?[\s\S]{{0,{gap_ids}}}?"(?:classId|clazzId)"\s*:\s*"?(\d+)"?[\s\S]{{0,{gap_name}}}?"(?:courseName|name|title)"\s*:\s*"([^"]+)"',
                    False,
                ),
                (
                    rf'"(?:classId|clazzId)"\s*:\s*"?(\d+)"?[\s\S]{{0,{gap_ids}}}?"courseId"\s*:\s*"?(\d+)"?[\s\S]{{0,{gap_name}}}?"(?:courseName|name|title)"\s*:\s*"([^"]+)"',
                    True,
                ),
            )
            for pattern, reverse_pair in patterns:
                for match in re.finditer(pattern, content, flags=re.IGNORECASE):
                    if reverse_pair:
                        append_course(match.group(2), match.group(1), match.start(), preferred_name=match.group(3))
                    else:
                        append_course(match.group(1), match.group(2), match.start(), preferred_name=match.group(3))

        def _run_hidden_input_fallback() -> None:
            """Fallback: paired hidden <input> tags on rendered course cards."""
            for match in re.finditer(
                r'<input[^>]*class=["\'][^"\']*courseId[^"\']*["\'][^>]*value=["\'](\d+)["\']',
                content,
                flags=re.IGNORECASE,
            ):
                near_start = max(0, match.start() - _FALLBACK_HIDDEN_INPUT_BEFORE)
                near_end = min(len(content), match.end() + _FALLBACK_HIDDEN_INPUT_AFTER)
                near = content[near_start:near_end]
                class_match = re.search(
                    r'<input[^>]*class=["\'][^"\']*(?:clazzId|classId)[^"\']*["\'][^>]*value=["\'](\d+)["\']',
                    near,
                    flags=re.IGNORECASE,
                )
                if not class_match:
                    continue
                cpi_match = re.search(r"(?:[?&]cpi=|\"cpi\"\s*:\s*\"?)(\d+)", near, flags=re.IGNORECASE)
                cpi = cpi_match.group(1) if cpi_match else ""
                append_course(
                    match.group(1),
                    class_match.group(1),
                    match.start(),
                    preferred_name=_extract_name(near, match.group(1)),
                    preferred_cpi=cpi,
                )

        _run_id_pair_fallback()
        _run_json_named_fallback()
        _run_hidden_input_fallback()

        return courses

    def get_active_tasks(
        self,
        course_filters: Optional[List[str]] = None,
        class_filters: Optional[List[str]] = None,
        active_id: Optional[Any] = None,
        expected_type: str = "all",
    ) -> List[Dict[str, Any]]:
        courses = self.get_courses()
        filter_pairs: set[tuple[str, Optional[str]]] = set()
        for item in course_filters or []:
            filter_pairs.add(_parse_course_filter(item))
        class_filter_set = _as_filter_set(class_filters)
        active_filter_set = _as_filter_set(active_id)

        tasks: List[Dict[str, Any]] = []
        now_ms = int(time.time() * 1000)

        for course in courses:
            course_id = str(course.get("courseId", ""))
            class_id = str(course.get("classId", ""))
            if filter_pairs and (course_id, class_id) not in filter_pairs and (course_id, None) not in filter_pairs:
                continue
            if class_filter_set and class_id not in class_filter_set:
                continue

            payload = self._get_course_activity_list(course_id, class_id)
            for activity in payload:
                # Chaoxing routinely sends keys present-but-null; `int(None)` would
                # raise TypeError and abort the whole batch, so coerce with `or 0`.
                if int(activity.get("status") or 0) != 1:
                    continue
                activity_id = str(activity.get("id") or "")
                if not activity_id:
                    continue
                if active_filter_set and activity_id not in active_filter_set:
                    continue
                # The >2h age heuristic only bounds auto-discovered activities.
                # When the caller explicitly named this active_id, honor it
                # regardless of how long ago the activity started.
                explicitly_requested = activity_id in active_filter_set
                if not explicitly_requested:
                    start_time = int(activity.get("startTime") or now_ms)
                    if now_ms - start_time > 2 * 60 * 60 * 1000:
                        continue

                sign_type = self._resolve_sign_type(activity, activity_id)
                if expected_type != "all" and sign_type != expected_type:
                    continue

                tasks.append(self._activity_to_task(course, activity, sign_type=sign_type))

        return tasks

    def get_class_subjects(self) -> List[Dict[str, Any]]:
        subjects: List[Dict[str, Any]] = []
        for course in self.get_courses():
            course_id = str(course.get("courseId") or "").strip()
            class_id = str(course.get("classId") or course.get("clazzId") or "").strip()
            if not course_id or not class_id:
                continue
            name = str(course.get("courseName") or course.get("name") or course_id).strip()
            subjects.append(
                {
                    **dict(course),
                    "id": _course_selector(course),
                    "subjectType": "class",
                    "subjectId": class_id,
                    "classSubjectId": class_id,
                    "classId": class_id,
                    "clazzId": class_id,
                    "rawCourseId": course_id,
                    "courseId": course_id,
                    "courseName": name,
                    "name": name,
                }
            )
        return subjects

    def get_class_activities(
        self,
        class_id: str,
        course_id: Optional[str] = None,
        include_details: bool = True,
    ) -> List[Dict[str, Any]]:
        normalized_class_id = str(class_id or "").strip()
        normalized_course_id = str(course_id or "").strip()
        normalized_raw_course_id = _parse_course_filter(normalized_course_id)[0] if normalized_course_id else ""
        if not normalized_class_id:
            return []

        activities: List[Dict[str, Any]] = []
        for course in self.get_courses():
            current_course_id = str(course.get("courseId") or "").strip()
            current_class_id = str(course.get("classId") or course.get("clazzId") or "").strip()
            if current_class_id != normalized_class_id:
                continue
            if normalized_raw_course_id and current_course_id != normalized_raw_course_id:
                continue
            for activity in self._get_course_activity_list(current_course_id, current_class_id):
                detail = {}
                active_id = str(activity.get("id") or "").strip()
                if include_details and active_id:
                    detail = self.get_ppt_active_info(active_id)
                sign_type = self._resolve_sign_type(activity, active_id, detail)
                item = self._activity_to_task(course, activity, sign_type=sign_type, detail=detail)
                item["raw"] = activity
                activities.append(item)
        return activities

    def _get_course_activity_list(self, course_id: str, class_id: str) -> List[Dict[str, Any]]:
        # A network failure here must NOT abort discovery for the OTHER courses:
        # return [] so the per-course loop skips this one (matches the guarded
        # pattern used by every other network call in this client).
        try:
            resp = self.session.get(
                ACTIVE_LIST_URL,
                params={
                    "fid": 0,
                    "courseId": course_id,
                    "classId": class_id,
                    "_": int(time.time() * 1000),
                },
                timeout=12,
            )
        except requests.RequestException as exc:
            logger.warning(
                "activelist request failed for course=%s class=%s: %s",
                course_id, class_id, exc,
            )
            return []
        data = self._safe_json(resp)
        # `data.get("data", {})` does NOT guard an explicit ``"data": null`` (common
        # when a per-course session/cookie is invalid) — `None.get(...)` would raise
        # AttributeError and crash discovery; use `or {}`.
        active_list = (data.get("data") or {}).get("activeList", [])
        return active_list if isinstance(active_list, list) else []

    def _resolve_sign_type(
        self,
        activity: Dict[str, Any],
        active_id: str,
        info: Optional[Dict[str, Any]] = None,
    ) -> str:
        # `or 0` (not the 2-arg .get default) so a present-but-null field — which
        # Chaoxing sends routinely — does not raise TypeError on int(None).
        other_id = int(activity.get("otherId") or 0)
        if other_id == 3:
            return "gesture"
        if other_id == 5:
            return "code"
        if other_id == 4:
            return "location"
        if other_id == 2:
            return "qrcode"
        if other_id == 0:
            if int(activity.get("ifphoto") or 0) == 1:
                return "photo"
            info = info if info is not None else self.get_ppt_active_info(active_id)
            if int((info or {}).get("ifphoto") or 0) == 1:
                return "photo"
            return "normal"
        return "normal"

    def _activity_to_task(
        self,
        course: Dict[str, Any],
        activity: Dict[str, Any],
        sign_type: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        course_id = str(course.get("courseId") or "").strip()
        class_id = str(course.get("classId") or course.get("clazzId") or "").strip()
        active_id = str(activity.get("id") or activity.get("activeId") or "").strip()
        deadline = activity.get("endTime") or activity.get("startTime")
        deadline_iso = (
            datetime.fromtimestamp(int(deadline) / 1000, tz=timezone.utc).isoformat()
            if deadline
            else None
        )
        status_code = int(activity.get("status", 0) or 0)
        course_name = str(course.get("courseName") or course.get("name") or course_id).strip()
        task = {
            "taskId": f"{course_id}:{class_id}:{active_id}",
            "activeId": active_id,
            "subjectType": "class",
            "subjectId": class_id,
            "classSubjectId": class_id,
            "courseId": f"{course_id}_{class_id}",
            "courseSelector": _course_selector(course),
            "rawCourseId": course_id,
            "classId": class_id,
            "clazzId": class_id,
            "courseName": course_name,
            "className": str(course.get("className") or course.get("clazzName") or course_name).strip(),
            "name": activity.get("nameOne") or activity.get("name") or "",
            "type": sign_type or self._resolve_sign_type(activity, active_id, detail),
            "otherId": int(activity.get("otherId") or 0),
            "status": "active" if status_code == 1 else "ended" if status_code in (2, 3) else "unknown",
            "statusCode": status_code,
            "deadline": deadline_iso,
            "startTime": activity.get("startTime"),
            "endTime": activity.get("endTime"),
            "remoteEndpoints": build_remote_sign_endpoints(
                course_id=course_id,
                class_id=class_id,
                active_id=active_id,
                uid=self.uid,
                fid=self.fid,
            ),
        }
        if detail:
            task["detail"] = detail
        return task

    def get_ppt_active_info(self, active_id: str) -> Dict[str, Any]:
        try:
            resp = self.session.get(
                PPT_ACTIVE_INFO_URL,
                params={"activeId": active_id},
                timeout=10,
            )
        except requests.RequestException:
            return {}
        data = self._safe_json(resp)
        return data.get("data") or {}

    def _pre_sign(self, task: Dict[str, Any]) -> None:
        params = {
            "courseId": task["rawCourseId"],
            "classId": task["classId"],
            "activePrimaryId": task["activeId"],
            "general": 1,
            "sys": 1,
            "ls": 1,
            "appType": 15,
            "tid": "",
            "uid": self.uid,
            "ut": "s",
        }
        self.session.get(PRE_SIGN_URL, params=params, timeout=10)

    def sign_task(
        self,
        task: Dict[str, Any],
        preferred_type: str = "all",
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        options = options or {}
        sign_type = task["type"] if preferred_type == "all" else preferred_type
        self._pre_sign(task)

        if sign_type == "location":
            raw_result = self._sign_location(task, options)
        elif sign_type == "qrcode":
            raw_result = self._sign_qrcode(task, options)
        elif sign_type == "photo":
            raw_result = self._sign_photo(task, options)
        elif sign_type == "gesture":
            raw_result = self._sign_gesture(task, options)
        elif sign_type == "code":
            raw_result = self._sign_code(task, options)
        else:
            raw_result = self._sign_general(task)

        success = raw_result.strip().lower() == "success"
        return {
            "status": success,
            "message": raw_result,
            "data": {
                "task": task,
                "sign_type": sign_type,
            },
        }

    @staticmethod
    def _parse_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _extract_sign_code(options: Dict[str, Any]) -> str:
        for key in ("sign_code", "signCode", "gesture", "gesture_code", "code", "passcode"):
            value = options.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        return ""

    @staticmethod
    def _as_dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _extract_location_options(self, options: Dict[str, Any]) -> tuple[str, float, float]:
        location = self._as_dict(options.get("location"))

        lat_value = options.get("latitude")
        if lat_value is None:
            lat_value = location.get("latitude")
        if lat_value is None:
            lat_value = location.get("lat")

        lon_value = options.get("longitude")
        if lon_value is None:
            lon_value = location.get("longitude")
        if lon_value is None:
            lon_value = location.get("lng")

        address = str(
            options.get("address")
            or location.get("address")
            or location.get("name")
            or ""
        )
        latitude = self._parse_float(lat_value, -1.0)
        longitude = self._parse_float(lon_value, -1.0)
        return address, latitude, longitude

    def _extract_qrcode_options(
        self,
        options: Dict[str, Any],
    ) -> tuple[str, str, float, float, str, float]:
        qrcode = self._as_dict(options.get("qrcode"))
        location = self._as_dict(options.get("location"))

        qr_code = (
            options.get("qr_code")
            or qrcode.get("qr_code")
            or qrcode.get("url")
            or qrcode.get("code")
            or qrcode.get("enc")
            or ""
        )
        enc = _extract_enc(str(qr_code))

        lat_value = options.get("latitude")
        if lat_value is None:
            lat_value = qrcode.get("latitude")
        if lat_value is None:
            lat_value = qrcode.get("lat")
        if lat_value is None:
            lat_value = location.get("latitude")
        if lat_value is None:
            lat_value = location.get("lat")

        lon_value = options.get("longitude")
        if lon_value is None:
            lon_value = qrcode.get("longitude")
        if lon_value is None:
            lon_value = qrcode.get("lng")
        if lon_value is None:
            lon_value = location.get("longitude")
        if lon_value is None:
            lon_value = location.get("lng")

        address = str(
            options.get("address")
            or qrcode.get("address")
            or location.get("address")
            or ""
        )
        altitude_value = options.get("altitude")
        if altitude_value is None:
            altitude_value = qrcode.get("altitude")
        if altitude_value is None:
            altitude_value = location.get("altitude")

        latitude = self._parse_float(lat_value, -1.0)
        longitude = self._parse_float(lon_value, -1.0)
        altitude = self._parse_float(altitude_value, 100.0)
        return str(qr_code), enc, latitude, longitude, address, altitude

    def _sign_general(self, task: Dict[str, Any], extra_params: Optional[Dict[str, Any]] = None) -> str:
        params = {
            "activeId": task["activeId"],
            "uid": self.uid,
            "clientip": "",
            "latitude": -1,
            "longitude": -1,
            "appType": 15,
            "fid": self.fid,
            "name": self.account_name or self.username,
        }
        if extra_params:
            params.update(extra_params)
        resp = self.session.get(PPT_SIGN_URL, params=params, timeout=12)
        return (resp.text or "").strip()

    def _sign_location(self, task: Dict[str, Any], options: Dict[str, Any]) -> str:
        address, latitude, longitude = self._extract_location_options(options)
        params = {
            "activeId": task["activeId"],
            "uid": self.uid,
            "clientip": "",
            "appType": 15,
            "fid": self.fid,
            "name": self.account_name or self.username,
            "address": address,
            "latitude": latitude,
            "longitude": longitude,
            "ifTiJiao": 1,
        }
        resp = self.session.get(PPT_SIGN_URL, params=params, timeout=12)
        return (resp.text or "").strip()

    def _sign_qrcode(self, task: Dict[str, Any], options: Dict[str, Any]) -> str:
        _, enc, lat, lon, address, altitude = self._extract_qrcode_options(options)
        if not enc:
            return "fail-need-qrcode"

        location = json.dumps(
            {
                "result": "1",
                "address": address,
                "latitude": lat,
                "longitude": lon,
                "altitude": altitude,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
        params = {
            "enc": enc,
            "activeId": task["activeId"],
            "uid": self.uid,
            "clientip": "",
            "location": location,
            "latitude": -1,
            "longitude": -1,
            "fid": self.fid,
            "appType": 15,
            "name": self.account_name or self.username,
        }
        resp = self.session.get(PPT_SIGN_URL, params=params, timeout=12)
        return (resp.text or "").strip()

    def _sign_gesture(self, task: Dict[str, Any], options: Dict[str, Any]) -> str:
        sign_code = self._extract_sign_code(options)
        if not sign_code:
            return "fail-need-gesture"
        return self._sign_general(task, {"signCode": sign_code})

    def _sign_code(self, task: Dict[str, Any], options: Dict[str, Any]) -> str:
        sign_code = self._extract_sign_code(options)
        if not sign_code:
            return "fail-need-code"
        return self._sign_general(task, {"signCode": sign_code})

    def _sign_photo(self, task: Dict[str, Any], options: Dict[str, Any]) -> str:
        object_id = (
            options.get("object_id")
            or options.get("objectId")
        )
        if not object_id:
            photo_data = str(options.get("photo_base64") or options.get("photo") or "")
            if not photo_data:
                return "拍照签到失败：未收到图片数据，请重新上传照片。"
            object_id = self._upload_photo_and_get_object_id(photo_data)
        if not object_id:
            return "拍照签到失败：图片上传到学习通服务器失败，请检查网络或重试。"

        params = {
            "activeId": task["activeId"],
            "uid": self.uid,
            "clientip": "",
            "latitude": -1,
            "longitude": -1,
            "appType": 15,
            "fid": self.fid,
            "objectId": object_id,
            "name": self.account_name or self.username,
        }
        resp = self.session.get(PPT_SIGN_URL, params=params, timeout=12)
        return (resp.text or "").strip()

    def _upload_photo_and_get_object_id(self, photo_input: str) -> str:
        payload = (photo_input or "").strip()
        if not payload:
            logger.warning("photo upload: empty photo_input")
            return ""
        raw = payload.split(",", 1)[1] if payload.startswith("data:image") and "," in payload else payload
        try:
            image_bytes = base64.b64decode(raw, validate=True)
        except Exception as exc:
            logger.warning("photo upload: base64 decode failed: %s", exc)
            return ""

        if len(image_bytes) < 100:
            logger.warning("photo upload: decoded image too small (%d bytes)", len(image_bytes))
            return ""

        logger.info("photo upload: decoded %d bytes, requesting pan token", len(image_bytes))

        try:
            token_resp = self.session.get(PAN_TOKEN_URL, timeout=12)
        except requests.RequestException as exc:
            logger.warning("photo upload: pan token request failed: %s", exc)
            return ""
        token_data = self._safe_json(token_resp)
        token = token_data.get("_token") or token_data.get("token")
        if not token:
            logger.warning("photo upload: no token in response (status=%s body_len=%d)", token_resp.status_code, len(token_resp.text or ""))
            return ""

        logger.info("photo upload: got pan token, uploading image")
        try:
            upload_resp = self.session.post(
                PAN_UPLOAD_URL,
                params={"_from": "mobilelearn", "_token": token},
                files={"file": ("signin.jpg", image_bytes, "image/jpeg")},
                data={"puid": self.uid},
                timeout=25,
            )
        except requests.RequestException as exc:
            logger.warning("photo upload: upload request failed: %s", exc)
            return ""

        object_id = ""
        data = self._safe_json(upload_resp)
        if data:
            object_id = self._extract_object_id(data)
        if not object_id:
            text = upload_resp.text or ""
            match = re.search(r'"objectId"\s*:\s*"([^"]+)"', text)
            if match:
                object_id = match.group(1)

        if object_id:
            logger.info("photo upload: success, objectId=%s", object_id)
        else:
            logger.warning("photo upload: failed to extract objectId (status=%s body_len=%d)", upload_resp.status_code, len(upload_resp.text or ""))
        return object_id

    def _extract_object_id(self, value: Any) -> str:
        if isinstance(value, dict):
            for key in ("objectId", "objectid"):
                if key in value and value[key]:
                    return str(value[key])
            for item in value.values():
                found = self._extract_object_id(item)
                if found:
                    return found
            return ""
        if isinstance(value, list):
            for item in value:
                found = self._extract_object_id(item)
                if found:
                    return found
            return ""
        return ""


class ChaoxingSigninManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._clients: Dict[str, ChaoxingSigninClient] = {}
        self._history: Dict[str, List[Dict[str, Any]]] = {}
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._loaded_task_users: set[str] = set()
        self._loaded_history_users: set[str] = set()
        self._restore_tasks_from_store()
        self._restore_history_from_store()

    def login(self, user_id: str, username: str, password: str) -> Dict[str, Any]:
        client = ChaoxingSigninClient()
        result = client.login(username=username, password=password)
        if result.get("status"):
            with self._lock:
                self._clients[user_id] = client
        return result

    def _get_client(self, user_id: str) -> Optional[ChaoxingSigninClient]:
        with self._lock:
            return self._clients.get(user_id)

    def get_client(self, user_id: str) -> Optional[ChaoxingSigninClient]:
        return self._get_client(user_id)

    def get_courses(self, user_id: str) -> List[Dict[str, Any]]:
        client = self._get_client(user_id)
        if not client:
            return []
        return client.get_courses()

    def get_classes(self, user_id: str) -> List[Dict[str, Any]]:
        client = self._get_client(user_id)
        if not client:
            return []
        return client.get_class_subjects()

    def get_class_activities(
        self,
        user_id: str,
        class_id: str,
        course_id: Optional[str] = None,
        include_details: bool = True,
    ) -> List[Dict[str, Any]]:
        client = self._get_client(user_id)
        if not client:
            return []
        return client.get_class_activities(
            class_id=class_id,
            course_id=course_id,
            include_details=include_details,
        )

    def get_remote_endpoints(
        self,
        user_id: str,
        course_id: Optional[str] = None,
        class_id: Optional[str] = None,
        active_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        client = self._get_client(user_id)
        raw_course_id = _parse_course_filter(str(course_id or ""))[0] if course_id else ""
        raw_class_id = str(class_id or "").strip()
        if course_id and not raw_class_id:
            _, parsed_class_id = _parse_course_filter(str(course_id))
            raw_class_id = parsed_class_id or ""
        return build_remote_sign_endpoints(
            course_id=raw_course_id or "",
            class_id=raw_class_id,
            active_id=str(active_id or "").strip(),
            uid=client.uid if client else "",
            fid=client.fid if client else "",
        )

    def get_active_tasks(self, user_id: str, sign_type: str = "all") -> List[Dict[str, Any]]:
        client = self._get_client(user_id)
        live_tasks = client.get_active_tasks(expected_type=sign_type) if client else []
        if live_tasks:
            return [self._decorate_live_task(task) for task in live_tasks]
        return self._build_background_task_feed(user_id)

    def _build_background_task_feed(self, user_id: str) -> List[Dict[str, Any]]:
        tasks = self.list_tasks(user_id)
        running_tasks = [
            task
            for task in tasks
            if str(task.get("status") or "").lower() in BACKGROUND_TASK_ACTIVE_STATUSES
        ]
        selected_tasks = running_tasks or tasks[:TASK_FEED_FALLBACK_LIMIT]
        if selected_tasks:
            return [self._to_task_feed_item(task) for task in selected_tasks]

        history_records = self.get_history(user_id)[:TASK_FEED_FALLBACK_LIMIT]
        return [self._history_to_task_feed_item(record) for record in history_records]

    @staticmethod
    def _decorate_live_task(task: Dict[str, Any]) -> Dict[str, Any]:
        item = dict(task or {})
        item.setdefault("source", "live")
        item["actionable"] = True
        if not item.get("status"):
            item["status"] = "active"
        return item

    @staticmethod
    def _to_task_feed_item(task: Dict[str, Any]) -> Dict[str, Any]:
        task_id = str(task.get("task_id") or task.get("taskId") or task.get("id") or "").strip()
        progress = task.get("progress") if isinstance(task.get("progress"), dict) else {}
        course_name = (
            str(task.get("courseName") or "").strip()
            or str(task.get("course_name") or "").strip()
            or str(task.get("className") or "").strip()
            or str(progress.get("current_course") or "").strip()
            or "Background sign-in task"
        )
        sign_type = str(task.get("sign_type") or task.get("type") or "").strip().lower()
        task_type = sign_type if sign_type and sign_type != "all" else "background"
        type_label = {
            "background": "Background task",
            "normal": "Normal sign-in",
            "photo": "Photo sign-in",
            "location": "Location sign-in",
            "qrcode": "QR code sign-in",
            "gesture": "Gesture sign-in",
            "code": "Code sign-in",
        }.get(task_type, task_type or "Background task")
        return {
            "taskId": task_id,
            "task_id": task_id,
            "courseName": course_name,
            "type": task_type,
            "typeLabel": type_label,
            "status": str(task.get("status") or "unknown").lower(),
            "message": str(task.get("message") or ""),
            "createdAt": str(task.get("created_at") or task.get("createdAt") or ""),
            "updatedAt": str(task.get("updated_at") or task.get("updatedAt") or ""),
            "deadline": None,
            "actionable": False,
            "source": "background",
        }

    @staticmethod
    def _history_to_task_feed_item(record: Dict[str, Any]) -> Dict[str, Any]:
        record_type = str(record.get("type") or "history").strip().lower() or "history"
        return {
            "taskId": str(record.get("taskId") or ""),
            "task_id": str(record.get("taskId") or ""),
            "subjectType": str(record.get("subjectType") or "").strip(),
            "subjectId": str(record.get("subjectId") or "").strip(),
            "courseName": str(record.get("className") or record.get("courseName") or "Recent sign-in result"),
            "className": str(record.get("className") or ""),
            "type": record_type,
            "typeLabel": "Recent sign-in result",
            "status": str(record.get("status") or "success").lower(),
            "message": str(record.get("message") or ""),
            "createdAt": str(record.get("timestamp") or ""),
            "updatedAt": str(record.get("timestamp") or ""),
            "deadline": None,
            "actionable": False,
            "source": "history",
        }

    def get_history(self, user_id: str) -> List[Dict[str, Any]]:
        self._ensure_history_loaded_for_user(user_id)
        with self._lock:
            records = list(self._history.get(str(user_id or ""), []))
        return sorted(records, key=lambda item: item.get("timestamp", ""), reverse=True)

    def _append_history(self, user_id: str, record: Dict[str, Any]) -> None:
        history_record = dict(record or {})
        with self._lock:
            items = self._history.setdefault(user_id, [])
            items.append(history_record)
            if len(items) > 500:
                del items[:-500]
        self._persist_history_record(user_id, history_record)

    def sign_once(
        self,
        user_id: str,
        username: str,
        password: str,
        sign_type: str = "all",
        course_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        login_result = self.login(user_id, username, password)
        if not login_result.get("status"):
            return login_result

        client = self._get_client(user_id)
        if client is None:
            return {"status": False, "message": "Login state unavailable"}

        filters = [course_id] if course_id else None
        tasks = client.get_active_tasks(course_filters=filters, expected_type=sign_type)
        if not tasks:
            return {"status": False, "message": "No active sign-in task found", "data": []}

        target = tasks[0]
        result = client.sign_task(target, preferred_type=sign_type, options=options)
        history = {
            "status": "success" if result.get("status") else "failed",
            "message": result.get("message", ""),
            "courseName": target.get("courseName", ""),
            "type": target.get("type", "normal"),
            "timestamp": _utc_now_iso(),
        }
        self._append_history(user_id, history)
        result.setdefault("data", {})
        result["data"]["task"] = target
        return result

    def sign_class_once(
        self,
        user_id: str,
        username: str,
        password: str,
        class_id: str,
        sign_type: str = "all",
        active_id: Optional[Any] = None,
        course_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized_class_id = str(class_id or "").strip()
        if not normalized_class_id:
            return {"status": False, "message": "class_id is required", "data": []}

        login_result = self.login(user_id, username, password)
        if not login_result.get("status"):
            return login_result

        client = self._get_client(user_id)
        if client is None:
            return {"status": False, "message": "Login state unavailable"}

        course_filters = [course_id] if course_id else None
        tasks = client.get_active_tasks(
            course_filters=course_filters,
            class_filters=[normalized_class_id],
            active_id=active_id,
            expected_type=sign_type,
        )
        if not tasks:
            return {"status": False, "message": "No active class sign-in task found", "data": []}

        target = tasks[0]
        result = client.sign_task(target, preferred_type=sign_type, options=options)
        history = {
            "status": "success" if result.get("status") else "failed",
            "message": result.get("message", ""),
            "subjectType": "class",
            "subjectId": target.get("classId", normalized_class_id),
            "courseName": target.get("courseName", ""),
            "className": target.get("className", ""),
            "type": target.get("type", "normal"),
            "timestamp": _utc_now_iso(),
        }
        self._append_history(user_id, history)
        result.setdefault("data", {})
        result["data"]["task"] = target
        return result

    def start_task(self, user_id: str, payload: Dict[str, Any]) -> str:
        task_id = uuid4().hex
        now = _utc_now_iso()
        task_state = {
            "task_id": task_id,
            "user_id": user_id,
            "status": "running",
            "message": "Task started",
            "progress": {
                "total": 0,
                "completed": 0,
                "failed": 0,
                "current": 0,
            },
            "created_at": now,
            "started_at": now,
            "updated_at": now,
            "logs": [],
            "_log_cursor": 0,
        }
        with self._lock:
            self._tasks[task_id] = task_state
        self._persist_task_state(self._task_public_payload(task_state))

        threading.Thread(
            target=self._run_task_worker_guarded,
            args=(task_id, user_id, payload),
            daemon=True,
        ).start()
        return task_id

    def start_class_task(self, user_id: str, payload: Dict[str, Any]) -> str:
        class_payload = dict(payload or {})
        class_payload["subject_type"] = "class"
        class_id = str(class_payload.get("class_id") or "").strip()
        if class_id and not class_payload.get("class_list"):
            class_payload["class_list"] = [class_id]
        return self.start_task(user_id, class_payload)

    def _append_task_log(self, task_id: str, message: str, level: str = "info") -> None:
        snapshot: Optional[Dict[str, Any]] = None
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["logs"].append(
                {"timestamp": _utc_now_iso(), "message": message, "level": level}
            )
            if len(task["logs"]) > 500:
                del task["logs"][:-500]
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
            task.update(changes)
            task["updated_at"] = _utc_now_iso()
            snapshot = self._task_public_payload(task)
        if snapshot:
            self._persist_task_state(snapshot)

    def _run_task_worker(self, task_id: str, user_id: str, payload: Dict[str, Any]) -> None:
        username = str(payload.get("username") or "")
        password = str(payload.get("password") or "")
        sign_type = str(payload.get("sign_type") or "all")
        course_list = payload.get("course_list") or []
        class_list = payload.get("class_list") or []
        active_id = payload.get("active_id")
        subject_type = str(payload.get("subject_type") or ("class" if class_list else "course")).strip().lower()
        options = {
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "address": payload.get("address"),
            "qr_code": payload.get("qr_code"),
            "qrcode": payload.get("qrcode"),
            "location": payload.get("location"),
            "object_id": payload.get("object_id"),
            "photo_base64": payload.get("photo_base64"),
            "photo": payload.get("photo"),
            "altitude": payload.get("altitude"),
            "sign_code": payload.get("sign_code"),
            "signCode": payload.get("signCode"),
            "gesture": payload.get("gesture"),
            "code": payload.get("code"),
        }

        login_result = self.login(user_id, username, password)
        if not login_result.get("status"):
            self._update_task(
                task_id,
                status="error",
                message=login_result.get("message", "Login failed"),
            )
            self._append_task_log(task_id, f"Login failed: {login_result.get('message', '')}", "error")
            return

        client = self._get_client(user_id)
        if client is None:
            self._update_task(task_id, status="error", message="Login state unavailable")
            return

        self._append_task_log(task_id, "Login successful")
        tasks = client.get_active_tasks(
            course_filters=course_list,
            class_filters=class_list if subject_type == "class" else None,
            active_id=active_id,
            expected_type=sign_type,
        )
        if not tasks:
            self._update_task(task_id, status="completed", message="No active sign-in task")
            self._append_task_log(task_id, "No active sign-in task found")
            return

        total = len(tasks)
        first_task = tasks[0]
        first_course_name = str(first_task.get("courseName") or "").strip()
        first_class_name = str(first_task.get("className") or "").strip()
        first_subject_name = first_class_name if subject_type == "class" and first_class_name else first_course_name
        first_task_type = str(first_task.get("type") or sign_type or "background").strip() or "background"
        self._update_task(
            task_id,
            progress={
                "total": total,
                "completed": 0,
                "failed": 0,
                "current": 0,
                "current_course": first_subject_name,
            },
            subject_type=subject_type,
            subjectType=subject_type,
            course_name=first_subject_name,
            courseName=first_subject_name,
            className=first_class_name,
            type=first_task_type,
        )

        completed = 0
        failed = 0
        for index, task in enumerate(tasks, start=1):
            current_course_name = str(task.get("courseName") or "").strip()
            current_class_name = str(task.get("className") or "").strip()
            current_subject_name = current_class_name if subject_type == "class" and current_class_name else current_course_name
            current_task_type = str(task.get("type") or sign_type or "background").strip() or "background"
            self._append_task_log(task_id, f"Signing {current_subject_name} ({current_task_type})")
            result = client.sign_task(task, preferred_type=sign_type, options=options)
            if result.get("status"):
                completed += 1
                level = "success"
                status_name = "success"
            else:
                failed += 1
                level = "error"
                status_name = "failed"
            self._append_task_log(task_id, result.get("message", ""), level)
            self._append_history(
                user_id,
                {
                    "status": status_name,
                    "message": result.get("message", ""),
                    "subjectType": subject_type,
                    "subjectId": task.get("classId") if subject_type == "class" else task.get("courseId"),
                    "courseName": task.get("courseName", ""),
                    "className": task.get("className", ""),
                    "type": task.get("type", "normal"),
                    "timestamp": _utc_now_iso(),
                },
            )
            self._update_task(
                task_id,
                progress={
                    "total": total,
                    "completed": completed,
                    "failed": failed,
                    "current": index,
                    "current_course": current_subject_name,
                },
                message=f"Processed {index}/{total}",
                subject_type=subject_type,
                subjectType=subject_type,
                course_name=current_subject_name,
                courseName=current_subject_name,
                className=current_class_name,
                type=current_task_type,
            )

        final_status = "completed" if failed == 0 else "error"
        final_message = "Task completed" if failed == 0 else "Task completed with failures"
        self._update_task(task_id, status=final_status, message=final_message)

    def _run_task_worker_guarded(self, task_id: str, user_id: str, payload: Dict[str, Any]) -> None:
        try:
            self._run_task_worker(task_id, user_id, payload)
        except Exception as exc:  # pragma: no cover - defensive safety net
            logger.exception("Chaoxing sign-in task crashed: task_id=%s user_id=%s", task_id, user_id)
            message = f"{UNEXPECTED_WORKER_ERROR_PREFIX}: {exc}"
            self._update_task(task_id, status="error", message=message)
            self._append_task_log(task_id, message, "error")

    def get_task(self, user_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        normalized_user_id = str(user_id or "").strip()
        normalized_task_id = str(task_id or "").strip()
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if task and task.get("user_id") == normalized_user_id:
                return {k: v for k, v in task.items() if not k.startswith("_")}

        self._load_task_from_store(normalized_user_id, normalized_task_id)
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if not task or task.get("user_id") != normalized_user_id:
                return None
            return {k: v for k, v in task.items() if not k.startswith("_")}

    def list_tasks(self, user_id: str) -> List[Dict[str, Any]]:
        self._ensure_tasks_loaded_for_user(user_id)
        with self._lock:
            tasks: List[Dict[str, Any]] = []
            for task in self._tasks.values():
                if task.get("user_id") != user_id:
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

    def get_task_logs(
        self, user_id: str, task_id: str, cursor: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Return logs from ``cursor`` (default 0) WITHOUT mutating server state.

        Stateless, per-request slicing — mirrors learning_manager.get_task_logs.
        The old version advanced a single shared server-side cursor on every read,
        so reopening a task or two overlapping polls (3s poll vs manual refresh)
        raced on it and showed blank/partial logs. The client now tracks its own
        cursor and passes it back.
        """
        normalized_user_id = str(user_id or "").strip()
        normalized_task_id = str(task_id or "").strip()

        def _slice(task: Dict[str, Any]) -> Dict[str, Any]:
            all_logs = task.get("logs", [])
            start = int(cursor) if cursor is not None else 0
            if start < 0:
                start = 0
            return {"logs": list(all_logs[start:]), "cursor": len(all_logs)}

        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if task and task.get("user_id") == normalized_user_id:
                return _slice(task)

        self._load_task_from_store(normalized_user_id, normalized_task_id)
        with self._lock:
            task = self._tasks.get(normalized_task_id)
            if not task or task.get("user_id") != normalized_user_id:
                return None
            return _slice(task)

    @staticmethod
    def _task_public_payload(task: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in task.items() if not str(k).startswith("_")}

    @staticmethod
    def _default_progress() -> Dict[str, Any]:
        return {"total": 0, "completed": 0, "failed": 0, "current": 0}

    def _persist_task_state(self, task_state_public: Dict[str, Any]) -> None:
        try:
            task_store.upsert_task(SIGNIN_TASK_KIND, task_state_public)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("persist signin task failed: %s", exc)

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
                task_kind=SIGNIN_TASK_KIND,
                task_id=normalized_task_id,
                user_id=normalized_user_id,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("load signin task failed: user=%s task=%s err=%s", normalized_user_id, normalized_task_id, exc)
            stored_task = None
        if stored_task:
            self._merge_task_from_store(stored_task)

    def _load_tasks_from_store_for_user(self, user_id: str) -> None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return
        try:
            stored_tasks = task_store.list_tasks(
                task_kind=SIGNIN_TASK_KIND,
                user_id=normalized_user_id,
                limit=USER_TASK_LOAD_LIMIT,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("load signin tasks failed: user=%s err=%s", normalized_user_id, exc)
            stored_tasks = []

        for item in stored_tasks:
            self._merge_task_from_store(item)

        with self._lock:
            self._loaded_task_users.add(normalized_user_id)

    def _ensure_history_loaded_for_user(self, user_id: str) -> None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return
        with self._lock:
            if normalized_user_id in self._loaded_history_users:
                return
        self._load_history_from_store_for_user(normalized_user_id)

    def _persist_history_record(self, user_id: str, record: Dict[str, Any]) -> None:
        payload = dict(record or {})
        payload.setdefault("timestamp", _utc_now_iso())
        try:
            task_store.append_history(
                history_kind=SIGNIN_HISTORY_KIND,
                user_id=user_id,
                record=payload,
                max_records=500,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("persist signin history failed: %s", exc)

    def _restore_tasks_from_store(self) -> None:
        try:
            stored_tasks = task_store.list_tasks(task_kind=SIGNIN_TASK_KIND, user_id=None, limit=300)
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("restore signin tasks failed: %s", exc)
            stored_tasks = []

        now = _utc_now_iso()
        for item in stored_tasks:
            self._merge_task_from_store(item, now=now)

    def _restore_history_from_store(self) -> None:
        try:
            history_records = task_store.list_history(
                history_kind=SIGNIN_HISTORY_KIND,
                user_id=None,
                limit=1500,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("restore signin history failed: %s", exc)
            history_records = []

        with self._lock:
            for record in history_records:
                user_id = str(record.get("user_id") or "").strip()
                if not user_id:
                    continue
                item = dict(record)
                item.pop("user_id", None)
                items = self._history.setdefault(user_id, [])
                items.append(item)
                if len(items) > 500:
                    del items[:-500]

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
        task.setdefault("created_at", task.get("started_at") or current_time)
        task.setdefault("started_at", task.get("created_at") or current_time)
        task.setdefault("updated_at", task.get("started_at") or current_time)

        logs = task.get("logs")
        if not isinstance(logs, list):
            logs = []
        task["logs"] = logs
        task["_log_cursor"] = 0

        interrupted = str(task.get("status") or "").lower() in INTERRUPTED_TASK_STATUSES
        if interrupted:
            task["status"] = "error"
            task["message"] = RESTART_INTERRUPTED_MESSAGE
            task["updated_at"] = current_time
            task["logs"].append(
                {
                    "timestamp": current_time,
                    "message": RESTART_INTERRUPTED_MESSAGE,
                    "level": "warning",
                }
            )
            if len(task["logs"]) > 500:
                del task["logs"][:-500]

        with self._lock:
            self._tasks[task_id] = task

        if interrupted:
            self._persist_task_state(self._task_public_payload(task))
        return True

    def _load_history_from_store_for_user(self, user_id: str) -> None:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return
        try:
            records = task_store.list_history(
                history_kind=SIGNIN_HISTORY_KIND,
                user_id=normalized_user_id,
                limit=500,
            )
        except Exception as exc:  # pragma: no cover - defensive fallback
            logger.warning("load signin history failed: user=%s err=%s", normalized_user_id, exc)
            records = []

        cleaned: List[Dict[str, Any]] = []
        for record in records:
            item = dict(record)
            item.pop("user_id", None)
            cleaned.append(item)

        with self._lock:
            self._history[normalized_user_id] = cleaned
            self._loaded_history_users.add(normalized_user_id)


signin_manager = ChaoxingSigninManager()
