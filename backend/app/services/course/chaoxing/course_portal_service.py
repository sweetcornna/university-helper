"""Chaoxing remote course endpoints exposed to the web frontend."""

from __future__ import annotations

import html
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from bs4 import BeautifulSoup

ACTIVE_API_URL = "https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist"
ACTIVE_PAGE_URL = "https://mobilelearn.chaoxing.com/page/active/stuActiveList"
COURSE_SHELL_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/stu"
CHAPTER_LIST_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/mycourse/studentcourse"
RESOURCE_LIST_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/coursedata/stu-datalist"
HOMEWORK_LIST_URL = "https://mooc1.chaoxing.com/mooc2/work/list"
EXAM_LIST_URL = "https://mooc1.chaoxing.com/exam-ans/mooc2/exam/exam-list"
STUDENT_NAV_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/coursemanagev3/stu-base-info"
# Path fragment that identifies each HTML tab inside the student course navigation.
_NAV_PATHS = {"resources": "/coursedata/stu-datalist", "homework": "/work/list", "tests": "/exam/exam-list"}


class ChaoxingPortalDeniedError(RuntimeError):
    """Chaoxing answered with its "invalid parameter / no permission" placeholder page."""


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


def _read_html_response(response: Any, tab_key: str) -> str:
    status_code = getattr(response, "status_code", 200)
    html_text = str(getattr(response, "text", "") or "")
    response_url = getattr(response, "url", "")
    headers = getattr(response, "headers", {}) or {}
    location = headers.get("Location", "")
    login_redirect = any(
        isinstance(value, str) and urlsplit(value).hostname in {"passport2.chaoxing.com", "passport2-api.chaoxing.com"}
        for value in (response_url, location)
    )
    login_form = re.search(
        r'<(?:form|input)\b[^>]*(?:fanyalogin|name=["\']uname["\']|id=["\']phone["\'])',
        html_text,
        flags=re.IGNORECASE,
    )
    if status_code == 401 or login_redirect or login_form:
        raise RuntimeError("学习通登录已失效，请重新登录后加载课程内容")
    if status_code != 200:
        raise RuntimeError(f"Fetch {tab_key} failed: {status_code}")
    soup = BeautifulSoup(html_text, "lxml")
    error_node = soup.select_one(".nullMain .word_null")
    error_message = _clean_text(error_node.get_text(" ", strip=True)) if error_node else ""
    if re.search(r"无效|无权限|没有权限|参数错误|访问失败", error_message):
        raise ChaoxingPortalDeniedError(f"学习通课程内容加载失败：{error_message}")
    return html_text


def _empty_state_message(html_text: str) -> str:
    soup = BeautifulSoup(html_text, "lxml")
    for node in soup.select(".nodata, .null-data, .no-data, .noData, .dataBody > .NoResult"):
        if node.find_parent(class_="maskDiv") is None:
            message = _clean_text(node.get_text(" ", strip=True))
            if re.search(
                r"(?:暂无|没有).*(?:章节|资料|文件|作业|考试|数据|内容)|无(?:章节|资料|作业|考试)|全部章节.*隐藏",
                message,
            ):
                return message
    return ""


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
                "message": "这个栏目需要在学习通中打开",
            }

        frame_url = tab.frame_builder(self, context)
        response = session.get(frame_url, timeout=12)
        try:
            html_text = _read_html_response(response, tab.key)
        except ChaoxingPortalDeniedError:
            # Teachers can hide a tab from students; the course navigation is the
            # source of truth for which tabs exist and the URL (with tokens) to use.
            navigation = self._student_navigation_urls(session, context)
            if navigation is None:
                raise
            nav_url = navigation.get(tab.key)
            if nav_url is None:
                return {
                    "course": context.as_dict(),
                    "tab": tab.as_dict(self, context),
                    "url": frame_url,
                    "items": [],
                    tab.item_key: [],
                    "unavailable": True,
                    "message": f"这门课没有向学生开放「{tab.label}」栏目",
                }
            if nav_url == frame_url:
                raise
            frame_url = nav_url
            html_text = _read_html_response(session.get(frame_url, timeout=12), tab.key)
        items = self.parse_html_tab(tab.key, html_text, frame_url)
        payload = {
            "course": context.as_dict(),
            "tab": tab.as_dict(self, context),
            "url": frame_url,
            "items": items,
            tab.item_key: items,
        }
        if not items:
            message = _empty_state_message(html_text)
            if not message:
                raise RuntimeError("学习通返回的不是可识别的课程列表，请检查访问权限或页面验证后重试")
            payload["message"] = message
        return payload

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
        _read_html_response(response, "activities")
        data = _safe_json(response)
        active_data = data.get("data")
        if not isinstance(active_data, dict) or not isinstance(active_data.get("activeList"), list):
            raise RuntimeError("学习通返回的不是可识别的活动列表，请检查登录状态或页面验证后重试")
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
        html_text = _read_html_response(response, "chapters")
        from app.services.course.chaoxing.decode import decode_course_point

        parsed = decode_course_point(html_text)
        chapters = parsed.get("points", []) if isinstance(parsed, dict) else []
        payload = {
            "course": context.as_dict(),
            "tab": tab.as_dict(self, context),
            "url": frame_url,
            "items": chapters,
            "chapters": chapters,
            "raw": parsed,
        }
        if not chapters:
            message = _empty_state_message(html_text)
            if not message:
                # Units without task points have no `cur<id>` rows; list their titles.
                soup = BeautifulSoup(html_text, "lxml")
                titles = [
                    _first_text(node.get("title"), node.get_text(" ", strip=True))
                    for node in soup.select(".chapter_unit .catalog_name .clicktitle span[title]")
                ]
                titles = [title for title in titles if title]
                if not titles:
                    raise RuntimeError("学习通返回的不是可识别的章节列表，请检查访问权限或页面验证后重试")
                chapters = [
                    {"id": str(index), "title": title, "jobCount": 0, "has_finished": False, "need_unlock": False}
                    for index, title in enumerate(titles, start=1)
                ]
                payload["items"] = payload["chapters"] = chapters
                message = "这门课的章节没有任务点"
            payload["message"] = message
        return payload

    def _student_navigation_urls(self, session: Any, context: ChaoxingCourseContext) -> dict[str, str] | None:
        """Map tab key → URL from the student's course navigation; None when it cannot be read."""
        try:
            response = session.get(
                STUDENT_NAV_URL,
                params={"courseId": context.course_id, "clazzId": context.class_id, "cpi": context.cpi},
                timeout=12,
            )
            data = response.json()
        except Exception:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("navigationList"), list):
            return None

        urls: dict[str, str] = {}
        pending = list(data["navigationList"])
        while pending:
            item = pending.pop(0)
            if not isinstance(item, dict):
                continue
            pending.extend(item.get("children") or [])
            link = _clean_text(item.get("linkUrl"))
            if not link:
                continue
            absolute = urljoin("https://mooc2-ans.chaoxing.com/", link)
            path = urlsplit(absolute).path
            for tab_key, fragment in _NAV_PATHS.items():
                if fragment in path:
                    urls.setdefault(tab_key, absolute)
        return urls

    def parse_activities(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        active_list = payload.get("data", {}).get("activeList", []) if isinstance(payload.get("data"), dict) else []
        if not isinstance(active_list, list):
            return []
        return [self._normalize_activity(item) for item in active_list if isinstance(item, dict)]

    def parse_html_tab(self, tab_key: str, html_text: str, base_url: str) -> list[dict[str, Any]]:
        if not html_text:
            return []
        soup = BeautifulSoup(html_text, "lxml")
        if tab_key == "resources" and soup.select(".dataBody .dataBody_td"):
            return self._parse_resource_rows(soup, base_url)
        if tab_key == "tests" and soup.select(".bottomList ul li"):
            return self._parse_exam_rows(soup, base_url)
        return self._parse_link_items(soup, base_url, tab_key)

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

    def _parse_resource_rows(self, soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for row in soup.select(".dataBody .dataBody_td"):
            if row.find_parent(class_="maskDiv") is not None:
                continue
            title_node = row.select_one(".rename_title")
            title = _first_text(
                row.get("dataname"),
                title_node.get("title") if title_node else "",
                title_node.get_text(" ", strip=True) if title_node else "",
            )
            if not title:
                continue
            # The preview is a JavaScript action; use the supplied download
            # link when permitted, otherwise leave navigation to the list.
            item_url = base_url
            for link in row.select(".operate_down a[href]"):
                content_url = self._content_link_url("resources", _clean_text(link.get("href")), base_url)
                if content_url:
                    item_url = content_url
                    break
            details = [title]
            for selector in (".dataBody_size_stu", ".dataBody_creater_stu", ".dataBody_time_stu"):
                detail = row.select_one(selector)
                if detail:
                    details.append(_clean_text(detail.get_text(" ", strip=True)))
            item = {
                "id": _first_text(row.get("id"), str(len(items) + 1)),
                "title": title,
                "text": " ".join(part for part in details if part)[:300],
                "url": item_url,
                "status": "unknown",
            }
            file_type = _clean_text(row.get("type")).lower()
            if re.fullmatch(r"[a-z0-9]{2,8}", file_type):
                item["fileType"] = file_type
            items.append(item)
        return items

    def _parse_exam_rows(self, soup: BeautifulSoup, base_url: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for row in soup.select(".bottomList ul li"):
            title_node = row.select_one(".right-content p:first-child")
            if title_node is None:
                continue
            title = _first_text(title_node.get("title"), title_node.get_text(" ", strip=True))
            if not title:
                continue
            status_node = row.select_one(".status")
            row_text = _clean_text(row.get_text(" ", strip=True))
            status_text = status_node.get_text(" ", strip=True) if status_node else row_text
            # The list uses JavaScript actions that can start or reset an exam.
            # Keep the official list URL unless the row supplies a real link.
            item_url = base_url
            for link in row.select("a[href], [data]"):
                content_url = self._content_link_url("tests", _first_text(link.get("href"), link.get("data")), base_url)
                if content_url:
                    item_url = content_url
                    break
            items.append(
                {
                    "id": _first_text(row.get("id"), str(len(items) + 1)),
                    "title": title,
                    "text": row_text[:300],
                    "url": item_url,
                    "status": _status_from_text(status_text),
                }
            )
        return items

    @staticmethod
    def _content_link_url(tab_key: str, href: str, base_url: str) -> str:
        if not href or href.startswith("#"):
            return ""
        try:
            absolute_url = urljoin(base_url, href)
            parsed = urlsplit(absolute_url)
        except ValueError:
            return ""
        if parsed.scheme not in {"http", "https"}:
            return ""
        path = parsed.path.lower()
        query = {key.lower(): values for key, values in parse_qs(parsed.query).items()}
        if tab_key == "resources":
            if path.endswith("/coursedata/downloaddata") and query.get("dataid"):
                return absolute_url
            if re.search(r"/(?:file|resource)/(?:download|preview|view)(?:/|$)", path) or re.search(
                r"\.(?:pdf|docx?|pptx?|xlsx?|txt|csv|zip|rar|7z|mp[34]|jpe?g|png)$", path
            ):
                return absolute_url
        elif tab_key == "homework":
            if (
                "/work/" in path
                and not path.endswith("/list")
                and any(query.get(key) for key in ("workid", "workanswerid"))
            ):
                return absolute_url
        elif tab_key == "tests" and "/exam/" in path and not path.endswith("/exam-list") and query.get("examid"):
            return absolute_url
        return ""

    def _parse_link_items(
        self,
        soup: BeautifulSoup,
        base_url: str,
        tab_key: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for link in soup.select("a[href]"):
            if (
                link.find_parent(class_="maskDiv") is not None
                or link.find_parent(attrs={"role": "alertdialog"}) is not None
            ):
                continue
            href = _clean_text(link.get("href"))
            title = _first_text(link.get("title"), link.get("aria-label"), link.get_text(" ", strip=True))
            if _skip_link_text(title):
                continue

            absolute_url = self._content_link_url(tab_key, href, base_url)
            if not absolute_url:
                continue
            container = link.find_parent(["li", "tr", "dd", "div"]) or link
            row_text = _clean_text(container.get_text(" ", strip=True))
            if not row_text:
                row_text = title

            key = (title, absolute_url or row_text[:80])
            if key in seen:
                continue
            seen.add(key)

            status = _status_from_text(row_text)

            item = {
                "id": str(len(items) + 1),
                "title": title,
                "text": row_text[:300],
                "url": absolute_url,
                "status": status,
            }
            suffix_match = re.search(r"\.([a-zA-Z0-9]{2,8})$", urlsplit(absolute_url).path)
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
