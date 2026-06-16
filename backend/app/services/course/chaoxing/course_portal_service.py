"""Chaoxing remote course endpoints exposed to the web frontend."""

from __future__ import annotations

import html
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

ACTIVE_API_URL = "https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist"
ACTIVE_PAGE_URL = "https://mobilelearn.chaoxing.com/page/active/stuActiveList"
COURSE_SHELL_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/stu"
CHAPTER_LIST_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse"
RESOURCE_LIST_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/coursedata/stu-datalist"
HOMEWORK_LIST_URL = "https://mooc1.chaoxing.com/mooc2/work/list"
EXAM_LIST_URL = "https://mooc1.chaoxing.com/exam-ans/mooc2/exam/exam-list"


@dataclass(frozen=True)
class ChaoxingCourseContext:
    course_id: str
    class_id: str
    cpi: str = ""
    name: str = ""
    fid: str = "0"
    stuenc: str = ""
    enc: str = ""
    openc: str = ""

    @property
    def selector(self) -> str:
        return f"{self.course_id}_{self.class_id}_{self.cpi}" if self.cpi else f"{self.course_id}_{self.class_id}"

    def as_dict(self) -> dict[str, str]:
        return {
            "id": self.selector,
            "courseId": self.course_id,
            "classId": self.class_id,
            "cpi": self.cpi,
            "name": self.name,
            "courseName": self.name,
            "fid": self.fid,
            "stuenc": self.stuenc,
            "enc": self.enc,
            "openc": self.openc,
        }


@dataclass(frozen=True)
class ChaoxingPortalTab:
    key: str
    label: str
    page_header: int
    frame_builder: Callable[[ChaoxingCoursePortalService, ChaoxingCourseContext], str] | None = None
    item_key: str = "items"
    fetch_kind: str = "html"

    def as_dict(
        self, service: ChaoxingCoursePortalService, context: ChaoxingCourseContext | None = None
    ) -> dict[str, Any]:
        fetchable = self.frame_builder is not None or self.fetch_kind == "api"
        payload: dict[str, Any] = {
            "key": self.key,
            "label": self.label,
            "pageHeader": self.page_header,
            "itemKey": self.item_key,
            "fetchKind": self.fetch_kind,
            "fetchable": fetchable,
            "supported": fetchable,
            "remoteSource": "chaoxing",
            "directBrowserRequest": False,
            "browserRequestMode": "remote-direct",
        }
        if context is not None:
            payload["shellUrl"] = service.build_shell_url(context, self.key)
            if self.frame_builder is not None:
                payload["remoteUrl"] = self.frame_builder(service, context)
                payload["frameUrl"] = payload["remoteUrl"]
            if self.key == "activities":
                payload["remoteApiUrl"] = service.build_activities_api_url(context)

            remote_request_url = payload.get("remoteApiUrl") or payload.get("remoteUrl") or payload.get("shellUrl")
            if remote_request_url:
                payload["directBrowserRequest"] = True
                payload["remoteRequest"] = {
                    "method": "GET",
                    "url": remote_request_url,
                    "credentials": "include",
                    "mode": "cors",
                    "requiresChaoxingLogin": True,
                }
        return payload


def _clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _course_value(course: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key in course:
            value = _clean_text(course.get(key))
            if value:
                return value
    return ""


def _split_selector(selector: str) -> dict[str, str]:
    parts = [part.strip() for part in str(selector or "").split("_") if part.strip()]
    return {
        "course_id": parts[0] if len(parts) >= 1 else "",
        "class_id": parts[1] if len(parts) >= 2 else "",
        "cpi": parts[2] if len(parts) >= 3 else "",
    }


def _to_iso(value: Any) -> str | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    timestamp = parsed / 1000 if parsed > 1_000_000_000_000 else parsed
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def _safe_json(response: Any) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _request_url(base_url: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value not in (None, "")}
    query = urlencode(clean_params)
    return f"{base_url}?{query}" if query else base_url


def _status_from_text(text: str) -> str:
    lowered = text.lower()
    if any(token in text for token in ("未开始", "待完成", "待提交", "未提交", "未交")):
        return "pending"
    if any(token in text for token in ("进行中", "正在", "未截止")):
        return "active"
    if any(token in text for token in ("已完成", "已提交", "已交", "已结束", "已批阅")):
        return "completed"
    if any(token in lowered for token in ("ended", "finished", "submitted", "done")):
        return "completed"
    return "unknown"


def _skip_link_text(text: str) -> bool:
    if not text:
        return True
    compact = re.sub(r"\s+", "", text)
    if len(compact) <= 1:
        return True
    navigation_words = {
        "首页",
        "上一页",
        "下一页",
        "尾页",
        "确定",
        "取消",
        "下载",
        "预览",
        "打开",
        "返回",
        "更多",
        "全部",
        "搜索",
        "章节",
        "讨论",
        "资料",
        "作业",
        "考试",
        "活动",
    }
    return compact in navigation_words


class ChaoxingCoursePortalService:
    """Build and fetch Chaoxing course tabs using desktop-client routes."""

    def __init__(self) -> None:
        self.tabs: list[ChaoxingPortalTab] = [
            ChaoxingPortalTab(
                "activities", "活动", 0, ChaoxingCoursePortalService.build_activities_url, "activities", "api"
            ),
            ChaoxingPortalTab(
                "chapters", "章节", 1, ChaoxingCoursePortalService.build_chapters_url, "chapters", "html"
            ),
            ChaoxingPortalTab("discussions", "讨论", 2, None, "items", "shell"),
            ChaoxingPortalTab(
                "resources", "资料", 3, ChaoxingCoursePortalService.build_resources_url, "resources", "html"
            ),
            ChaoxingPortalTab("wrong_set", "错题集", 4, None, "items", "shell"),
            ChaoxingPortalTab("learning_record", "学习记录", 6, None, "items", "shell"),
            ChaoxingPortalTab(
                "homework", "作业", 8, ChaoxingCoursePortalService.build_homework_url, "homework", "html"
            ),
            ChaoxingPortalTab("tests", "考试", 9, ChaoxingCoursePortalService.build_tests_url, "tests", "html"),
        ]
        self._tab_index = {tab.key: tab for tab in self.tabs}

    def list_tabs(self) -> list[dict[str, Any]]:
        return [tab.as_dict(self) for tab in self.tabs]

    def resolve_course(self, selector: str, courses: Iterable[dict[str, Any]]) -> ChaoxingCourseContext:
        requested = _split_selector(selector)
        matched: dict[str, Any] | None = None

        for course in courses or []:
            course_id = _course_value(course, "courseId", "course_id", "rawCourseId")
            class_id = _course_value(course, "classId", "clazzId", "class_id", "clazz_id")
            explicit_id = _course_value(course, "id", "course_id")
            if explicit_id == selector:
                matched = course
                break
            if course_id and class_id and course_id == requested["course_id"] and class_id == requested["class_id"]:
                matched = course
                break
            if course_id and not requested["class_id"] and course_id == requested["course_id"]:
                matched = course
                break

        source = matched or {}
        course_id = _first_text(
            _course_value(source, "courseId", "course_id", "rawCourseId"),
            requested["course_id"],
        )
        class_id = _first_text(
            _course_value(source, "classId", "clazzId", "class_id", "clazz_id"),
            requested["class_id"],
        )
        cpi = _first_text(_course_value(source, "cpi", "cpiId"), requested["cpi"])
        name = _first_text(
            _course_value(source, "courseName", "name", "title", "course_name", "courseTitle"),
            course_id and f"Course {course_id}",
        )
        if not course_id or not class_id:
            raise ValueError("Invalid course_id format")

        stuenc = _course_value(source, "stuenc", "stuEnc", "studentEnc")
        enc = _first_text(_course_value(source, "enc"), stuenc)
        return ChaoxingCourseContext(
            course_id=course_id,
            class_id=class_id,
            cpi=cpi,
            name=name,
            fid=_first_text(_course_value(source, "fid", "schoolId", "school_id"), "0"),
            stuenc=stuenc,
            enc=enc,
            openc=_course_value(source, "openc", "openC"),
        )

    def build_shell_url(self, context: ChaoxingCourseContext, tab_key: str) -> str:
        tab = self._get_tab(tab_key)
        params = {
            "courseid": context.course_id,
            "clazzid": context.class_id,
            "cpi": context.cpi,
            "enc": context.enc,
            "t": int(time.time() * 1000),
            "pageHeader": tab.page_header,
            "v": 2,
            "hideHead": 0,
        }
        return _request_url(COURSE_SHELL_URL, params)

    def build_portal_urls(self, context: ChaoxingCourseContext) -> dict[str, Any]:
        return {
            "course": context.as_dict(),
            "tabs": [tab.as_dict(self, context) for tab in self.tabs],
        }

    def build_proxy_path(self, context: ChaoxingCourseContext, tab_key: str) -> str:
        tab = self._get_tab(tab_key)
        if tab.frame_builder is None and tab.fetch_kind != "api":
            return ""
        endpoint_key = {
            "chapters": "chapters",
            "activities": "activities",
            "resources": "resources",
            "homework": "homework",
            "tests": "tests",
        }.get(tab.key)
        if not endpoint_key:
            return ""
        return f"/course/chaoxing/course/{context.selector}/{endpoint_key}"

    def build_activities_url(self, context: ChaoxingCourseContext) -> str:
        return _request_url(
            ACTIVE_PAGE_URL,
            {
                "courseid": context.course_id,
                "clazzid": context.class_id,
                "cpi": context.cpi,
                "ut": "s",
                "t": int(time.time() * 1000),
                "stuenc": context.stuenc,
                "fid": context.fid,
            },
        )

    def build_activities_api_url(self, context: ChaoxingCourseContext) -> str:
        return _request_url(
            ACTIVE_API_URL,
            {
                "fid": context.fid,
                "courseId": context.course_id,
                "classId": context.class_id,
                "_": int(time.time() * 1000),
            },
        )

    def build_chapters_url(self, context: ChaoxingCourseContext) -> str:
        return _request_url(
            CHAPTER_LIST_URL,
            {
                "courseid": context.course_id,
                "clazzid": context.class_id,
                "cpi": context.cpi,
                "ut": "s",
                "t": int(time.time() * 1000),
                "stuenc": context.stuenc,
            },
        )

    def build_resources_url(self, context: ChaoxingCourseContext) -> str:
        return _request_url(
            RESOURCE_LIST_URL,
            {
                "courseid": context.course_id,
                "clazzid": context.class_id,
                "cpi": context.cpi,
                "ut": "s",
                "t": int(time.time() * 1000),
                "stuenc": context.stuenc,
            },
        )

    def build_homework_url(self, context: ChaoxingCourseContext) -> str:
        return _request_url(
            HOMEWORK_LIST_URL,
            {
                "courseid": context.course_id,
                "clazzid": context.class_id,
                "cpi": context.cpi,
                "ut": "s",
                "t": int(time.time() * 1000),
                "stuenc": context.stuenc,
            },
        )

    def build_tests_url(self, context: ChaoxingCourseContext) -> str:
        return _request_url(
            EXAM_LIST_URL,
            {
                "courseid": context.course_id,
                "clazzid": context.class_id,
                "cpi": context.cpi,
                "ut": "s",
                "t": int(time.time() * 1000),
                "stuenc": context.stuenc,
                "enc": context.enc,
                "openc": context.openc,
            },
        )

    def fetch_tab(self, session: Any, context: ChaoxingCourseContext, tab_key: str) -> dict[str, Any]:
        tab = self._get_tab(tab_key)
        if tab.key == "activities":
            return self.fetch_activities(session, context)
        if tab.key == "chapters":
            return self.fetch_chapters(session, context)
        if tab.frame_builder is None:
            return {
                "course": context.as_dict(),
                "tab": tab.as_dict(self, context),
                "items": [],
                "message": "This Chaoxing tab is opened through the course shell URL.",
            }

        frame_url = tab.frame_builder(self, context)
        response = session.get(frame_url, timeout=12)
        if getattr(response, "status_code", 200) != 200:
            raise RuntimeError(f"Fetch {tab.key} failed: {getattr(response, 'status_code', 'unknown')}")
        html_text = str(getattr(response, "text", "") or "")
        items = self.parse_html_tab(tab.key, html_text, frame_url)
        return {
            "course": context.as_dict(),
            "tab": tab.as_dict(self, context),
            "url": frame_url,
            "items": items,
            tab.item_key: items,
        }

    def fetch_activities(self, session: Any, context: ChaoxingCourseContext) -> dict[str, Any]:
        tab = self._get_tab("activities")
        response = session.get(
            ACTIVE_API_URL,
            params={
                "fid": context.fid,
                "courseId": context.course_id,
                "classId": context.class_id,
                "_": int(time.time() * 1000),
            },
            timeout=12,
        )
        if getattr(response, "status_code", 200) != 200:
            raise RuntimeError(f"Fetch activities failed: {getattr(response, 'status_code', 'unknown')}")
        data = _safe_json(response)
        activities = self.parse_activities(data)
        return {
            "course": context.as_dict(),
            "tab": tab.as_dict(self, context),
            "url": self.build_activities_api_url(context),
            "remoteUrl": self.build_activities_url(context),
            "items": activities,
            "activities": activities,
            "raw": data,
        }

    def fetch_chapters(self, session: Any, context: ChaoxingCourseContext) -> dict[str, Any]:
        tab = self._get_tab("chapters")
        frame_url = self.build_chapters_url(context)
        response = session.get(frame_url, timeout=12)
        if getattr(response, "status_code", 200) != 200:
            raise RuntimeError(f"Fetch chapters failed: {getattr(response, 'status_code', 'unknown')}")
        from app.services.course.chaoxing.decode import decode_course_point

        parsed = decode_course_point(str(getattr(response, "text", "") or ""))
        chapters = parsed.get("points", []) if isinstance(parsed, dict) else []
        return {
            "course": context.as_dict(),
            "tab": tab.as_dict(self, context),
            "url": frame_url,
            "items": chapters,
            "chapters": chapters,
            "raw": parsed,
        }

    def parse_activities(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        active_list = payload.get("data", {}).get("activeList", []) if isinstance(payload.get("data"), dict) else []
        if not isinstance(active_list, list):
            return []
        return [self._normalize_activity(item) for item in active_list if isinstance(item, dict)]

    def parse_html_tab(self, tab_key: str, html_text: str, base_url: str) -> list[dict[str, Any]]:
        if not html_text:
            return []
        soup = BeautifulSoup(html_text, "lxml")
        if tab_key == "resources":
            return self._parse_link_items(soup, base_url, status_tokens=())
        if tab_key in {"homework", "tests"}:
            return self._parse_link_items(
                soup, base_url, status_tokens=("未开始", "未提交", "已提交", "待批阅", "已完成", "已结束")
            )
        return self._parse_link_items(soup, base_url, status_tokens=())

    def _normalize_activity(self, activity: dict[str, Any]) -> dict[str, Any]:
        status_code = int(activity.get("status") or 0)
        active_id = _clean_text(activity.get("id") or activity.get("activeId"))
        other_id = int(activity.get("otherId") or 0)
        sign_type = {
            0: "normal",
            2: "qrcode",
            3: "gesture",
            4: "location",
            5: "code",
        }.get(other_id, "activity")
        if sign_type == "normal" and int(activity.get("ifphoto") or 0) == 1:
            sign_type = "photo"
        status = "active" if status_code == 1 else "ended" if status_code in (2, 3) else "unknown"
        return {
            "id": active_id,
            "title": _first_text(activity.get("nameOne"), activity.get("name"), activity.get("title"), active_id),
            "type": sign_type,
            "otherId": other_id,
            "status": status,
            "statusCode": status_code,
            "startTime": _to_iso(activity.get("startTime")),
            "endTime": _to_iso(activity.get("endTime")),
            "raw": activity,
        }

    def _parse_link_items(
        self,
        soup: BeautifulSoup,
        base_url: str,
        status_tokens: Iterable[str],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for link in soup.select("a[href]"):
            href = _clean_text(link.get("href"))
            title = _first_text(link.get("title"), link.get("aria-label"), link.get_text(" ", strip=True))
            if _skip_link_text(title):
                continue

            absolute_url = "" if href.startswith("javascript:") else urljoin(base_url, href)
            container = link.find_parent(["li", "tr", "dd", "div"]) or link
            row_text = _clean_text(container.get_text(" ", strip=True))
            if not row_text:
                row_text = title

            key = (title, absolute_url or row_text[:80])
            if key in seen:
                continue
            seen.add(key)

            status = "unknown"
            for token in status_tokens:
                if token in row_text:
                    status = _status_from_text(row_text)
                    break
            if status == "unknown":
                status = _status_from_text(row_text)

            item = {
                "id": str(len(items) + 1),
                "title": title,
                "text": row_text[:300],
                "url": absolute_url,
                "status": status,
            }
            suffix_match = re.search(r"\.([a-zA-Z0-9]{2,8})(?:[?#].*)?$", href)
            if suffix_match:
                item["fileType"] = suffix_match.group(1).lower()
            items.append(item)
            if len(items) >= 80:
                break

        return items

    def _get_tab(self, tab_key: str) -> ChaoxingPortalTab:
        tab = self._tab_index.get(str(tab_key or "").strip())
        if tab is None:
            raise ValueError(f"Unsupported Chaoxing tab: {tab_key}")
        return tab


chaoxing_course_portal_service = ChaoxingCoursePortalService()
