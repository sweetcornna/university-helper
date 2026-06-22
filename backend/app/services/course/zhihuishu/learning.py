"""智慧树自动学习模块"""

import logging
import math
import time
from base64 import b64encode

import requests

from .crypto import HOME_KEY, VIDEO_KEY, WatchPoint, encrypt_secret_str, get_ev, hms

logger = logging.getLogger(__name__)

# 站点（用于 Origin/Referer，部分网关接口缺失会被风控拦）
ONLINEWEB = "https://onlineweb.zhihuishu.com"
STUDYH5 = "https://studyh5.zhihuishu.com"

# 接口地址
COURSE_LIST_URL = "https://onlineservice-api.zhihuishu.com/gateway/t/v1/student/course/share/queryShareCourseInfo"
GOLOGIN_URL = "https://studyservice-api.zhihuishu.com/login/gologin"
QUERY_COURSE_URL = "https://studyservice-api.zhihuishu.com/gateway/t/v1/learning/queryCourse"
VIDEO_LIST_URL = "https://studyservice-api.zhihuishu.com/gateway/t/v1/learning/videolist"
PRELEARNING_NOTE_URL = "https://studyservice-api.zhihuishu.com/gateway/t/v1/learning/prelearningNote"
SAVE_DB_V2_URL = "https://studyservice-api.zhihuishu.com/gateway/t/v1/learning/saveDatabaseIntervalTimeV2"
# 注意："Stuy" 是平台接口本身的拼写错误，不是笔误
QUERY_STUDY_INFO_URL = "https://studyservice-api.zhihuishu.com/gateway/t/v1/learning/queryStuyInfo"

PAGE_SIZE = 5
DB_REPORT_INTERVAL = 30  # 真实秒：每 30 秒上报一次进度（与官方客户端节奏一致）
# 共享课状态：0=进行中, 1=已完成。两者都拉，否则已完成的课会"加载不出来"。
COURSE_STATUSES = (0, 1)


def _extract(payload: dict) -> dict:
    """读取智慧树网关响应里的数据体。

    共享课接口的数据在 ``result``，studyservice 接口在 ``data``，旧版网关为 ``rt``。
    """
    if not isinstance(payload, dict):
        return {}
    for key in ("data", "result", "rt"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


class ZhihuishuLearning:
    """智慧树自动学习服务"""

    def __init__(self, cookies: dict, proxies: dict | None = None, uuid: str | None = None):
        self.cookies = cookies
        self.proxies = proxies or {}
        self.uuid = uuid or ""
        self.session = requests.Session()
        self.session.cookies.update(cookies)

    def _signed_post(self, url: str, payload: dict, key: bytes, site: str | None = None):
        """统一的 AES 签名 POST（对齐参考实现 zhidaoQuery）。

        把 ``dateFormate`` 注入明文，再整体 AES-CBC 加密成 ``secretStr`` 表单字段，同时把
        ``dateFormate`` 作为顶层明文字段一起发；可按需带 Origin/Referer。
        """
        data = dict(payload)
        ts = int(time.time()) * 1000
        data["dateFormate"] = ts
        form = {"secretStr": encrypt_secret_str(data, key=key), "dateFormate": ts}
        headers = {"Origin": site, "Referer": site + "/"} if site else None
        return self.session.post(url, data=form, headers=headers, proxies=self.proxies, timeout=10)

    def get_course_list(self) -> list[dict]:
        """获取共享课列表（onlineservice queryShareCourseInfo）。

        ``secretStr`` 明文必须是分页对象 ``{"status","pageNo","pageSize"}``（不是单纯
        ``dateFormate``），否则平台返回空集 → 课程"无法加载"。``status`` 0=进行中、1=已完成，
        两者都要拉取并合并，否则已完成的课加载不出来（实测此即主因）。数据在
        ``result.courseOpenDtos``，按 ``result.totalCount`` 翻页。每门课的 ``secret`` 即后续视频
        接口所需的 ``recruitAndCourseId``，这里补成同名字段方便上层使用。
        """
        try:
            courses: list[dict] = []
            seen: set[str] = set()
            for status in COURSE_STATUSES:
                resp = self._signed_post(
                    COURSE_LIST_URL,
                    {"status": status, "pageNo": 1, "pageSize": PAGE_SIZE},
                    key=HOME_KEY,
                    site=ONLINEWEB,
                )
                result = _extract(resp.json())
                total = int(result.get("totalCount") or 0)
                batch = list(result.get("courseOpenDtos") or [])
                for page in range(2, math.ceil(total / PAGE_SIZE) + 1):
                    resp = self._signed_post(
                        COURSE_LIST_URL,
                        {"status": status, "pageNo": page, "pageSize": PAGE_SIZE},
                        key=HOME_KEY,
                        site=ONLINEWEB,
                    )
                    batch.extend(_extract(resp.json()).get("courseOpenDtos") or [])
                for course in batch:
                    if not isinstance(course, dict):
                        continue
                    key = str(course.get("courseId") or course.get("secret") or id(course))
                    if key in seen:
                        continue
                    seen.add(key)
                    if course.get("secret") and not course.get("recruitAndCourseId"):
                        course["recruitAndCourseId"] = course["secret"]
                    courses.append(course)
            return courses
        except Exception as e:
            raise Exception(f"Failed to get course list: {e}")

    def gologin(self, rac_id: str) -> None:
        """跨站登录：访问 studyservice 的 gologin 让该域 cookie 生效。

        不先做这一步，后续 studyservice 接口会因 cookie 未对该域生效而失败/空。
        """
        params = {"fromurl": f"{STUDYH5}/videoStudy.html#/studyVideo?recruitAndCourseId={rac_id}"}
        try:
            self.session.get(GOLOGIN_URL, params=params, proxies=self.proxies, timeout=10)
        except Exception as e:  # noqa: BLE001 - gologin 失败不致命，留给后续接口暴露真实错误
            logger.warning("Zhihuishu gologin failed for %s: %s", rac_id, e)

    def query_course(self, rac_id: str) -> dict:
        """查询课程信息（含 recruitId、courseInfo.courseId）。"""
        resp = self._signed_post(QUERY_COURSE_URL, {"recruitAndCourseId": rac_id}, key=VIDEO_KEY, site=STUDYH5)
        return _extract(resp.json())

    def get_video_list(self, rac_id: str) -> dict:
        """获取章节/视频树（studyservice videolist）。

        返回 ``data`` 字典：含 ``videoChapterDtos``（章 → ``videoLessons`` → ``videoSmallLessons``）、
        ``courseId``、``recruitId``。需先 ``gologin`` 让 studyservice 域 cookie 生效，并用
        ``VIDEO_KEY`` 签名（与共享课列表的 ``HOME_KEY`` 不同）。
        """
        try:
            self.gologin(rac_id)
            resp = self._signed_post(VIDEO_LIST_URL, {"recruitAndCourseId": rac_id}, key=VIDEO_KEY, site=STUDYH5)
            return _extract(resp.json())
        except Exception as e:
            raise Exception(f"Failed to get video list: {e}")

    def query_study_info(self, lesson_ids: list, video_ids: list, recruit_id) -> dict:
        """查询各（小）节的学习状态（studyservice queryStuyInfo）。

        返回 ``data`` 字典：``lv`` 按 lessonVideoId（小节 id）索引、``lesson`` 按 lessonId 索引，
        值含 ``studyTotalTime``（已学秒数）与 ``watchState``（1=已完成）。用于让上报从真实进度
        续播、并跳过已完成视频，避免服务器以 "学习总时长下降了"(code -8) 拒绝。
        """
        payload = {"lessonIds": lesson_ids, "lessonVideoIds": video_ids, "recruitId": recruit_id}
        resp = self._signed_post(QUERY_STUDY_INFO_URL, payload, key=VIDEO_KEY, site=STUDYH5)
        return _extract(resp.json())

    def _learning_token_id(self, video: dict) -> str | None:
        """从 prelearningNote 取 learningTokenId（``studiedLessonDto.id`` 的 base64）。"""
        payload = {
            "ccCourseId": video.get("course_id"),
            "chapterId": video.get("chapter_id"),
            "isApply": 1,
            "lessonId": video.get("lesson_id"),
            "lessonVideoId": video.get("small_lesson_id"),
            "recruitId": video.get("recruit_id"),
            "videoId": video.get("video_id"),
        }
        resp = self._signed_post(PRELEARNING_NOTE_URL, payload, key=VIDEO_KEY, site=STUDYH5)
        note = _extract(resp.json())
        token = (note.get("studiedLessonDto") or {}).get("id")
        if token is None:
            return None
        return b64encode(str(token).encode()).decode()

    def _save_progress(self, video: dict, played: float, last_submit: float, watch_point: str, token_id):
        """上报一次进度（saveDatabaseIntervalTimeV2），返回平台响应 ``code``。

        ``sdsew`` 由 ``get_ev`` 对一组字段（recruitId/lessonId/smallLessonId/videoId/chapterId/…）
        异或混淆得到，整体再经 ``secretStr`` AES 签名发送。成功码为 0；-8 表示
        "学习总时长下降了"（上报值低于服务器已记录值），由调用方处理。
        """
        video_sec = int(video.get("video_sec") or 0)
        raw_ev = [
            video.get("recruit_id"),
            video.get("lesson_id"),
            video.get("small_lesson_id"),
            video.get("video_id"),
            video.get("chapter_id"),
            "0",  # studyStatus，固定 0
            int(played - last_submit),  # 本段播放时长
            int(played),  # 累计学习时长
            hms(min(video_sec, int(played))),
            f"{self.uuid}zhs",
        ]
        data = {
            "ewssw": watch_point,
            "sdsew": get_ev(raw_ev),
            "zwsds": token_id,
            "courseId": video.get("course_id"),
        }
        resp = self._signed_post(SAVE_DB_V2_URL, data, key=VIDEO_KEY, site=STUDYH5)
        return resp.json().get("code")

    def watch_video(self, video: dict, speed: float = 1.0, is_cancelled=None, is_paused=None) -> bool:
        """真实上报某个视频的学习进度。

        Args:
            video: ``ZhihuishuAdapter._flatten_videos`` 产出的上下文 dict，含
                recruit/chapter/lesson/small/video id 与 ``video_sec``。
            speed: 倍速（钳制到 [0.5, 2.0]）；越大墙钟越短。
            is_cancelled / is_paused: 可选回调，分别在播放过程中即时中止 / 暂停上报。

        Returns:
            是否成功（全部分段上报成功）。
        """
        video_id = video.get("video_id") or video.get("id")
        try:
            video_sec = int(video.get("video_sec") or video.get("duration") or 0)
        except (TypeError, ValueError):
            video_sec = 0
        if video_sec <= 0:
            # 时长缺失/为 0：绝不"秒标完成"，抛错让上层记为失败。(F-zero-duration)
            raise Exception(f"video {video_id} has no usable duration ({video_sec!r})")

        # 已完成的视频直接跳过（watchState==1），避免无谓上报与 code -8。
        if int(video.get("watch_state") or 0) == 1:
            return True

        try:
            eff_speed = float(speed)
        except (TypeError, ValueError):
            eff_speed = 1.0
        eff_speed = min(max(eff_speed, 0.5), 2.0)

        # 从服务器记录的已学时长续播：否则上报值会小于已有进度，被判 "学习总时长下降了"(-8)。
        try:
            played = float(min(int(video.get("study_total_time") or 0), video_sec))
        except (TypeError, ValueError):
            played = 0.0
        if played >= video_sec:
            return True

        token_id = self._learning_token_id(video)
        watch_point = WatchPoint(int(played))
        last_submit = played
        elapsed = 0

        try:
            while played < video_sec:
                # 每周期开头检查取消/暂停，使其在"播放过程中"即可生效。(F-pause-cancel)
                if callable(is_cancelled) and is_cancelled():
                    return False
                while callable(is_paused) and is_paused():
                    if callable(is_cancelled) and is_cancelled():
                        return False
                    time.sleep(0.3)

                time.sleep(1)
                elapsed += 1
                played = min(played + eff_speed, video_sec)

                if elapsed % 2 == 0:
                    watch_point.add(int(played))

                if elapsed % DB_REPORT_INTERVAL == 0 or played >= video_sec:
                    watch_point.add(int(played))
                    code = self._save_progress(video, played, last_submit, watch_point.get(), token_id)
                    if code == -8:
                        # 服务器已记录 >= 本次上报：该节已学满/被其他端推进，视为完成。
                        return True
                    if code not in (0, 200, None):
                        return False
                    last_submit = played
                    watch_point.reset(int(played))

            return True
        except Exception as e:
            raise Exception(f"Failed to watch video: {e}")

    def complete_course(self, rac_id: str) -> dict:
        """完成整个课程（遍历章节→小节→视频逐个上报）。

        Args:
            rac_id: recruitAndCourseId（共享课列表里每门课的 ``secret``）。
        """
        data = self.get_video_list(rac_id)
        recruit_id = data.get("recruitId")
        course_id = data.get("courseId")
        completed = 0
        failed = 0

        for chapter in data.get("videoChapterDtos") or []:
            chapter_id = chapter.get("id") or chapter.get("chapterId")
            for lesson in chapter.get("videoLessons") or []:
                lesson_id = lesson.get("id")
                smalls = lesson.get("videoSmallLessons") or ([lesson] if lesson.get("videoId") else [])
                for small in smalls:
                    video = {
                        "recruit_and_course_id": rac_id,
                        "recruit_id": recruit_id,
                        "course_id": course_id,
                        "chapter_id": chapter_id,
                        "lesson_id": lesson_id,
                        "small_lesson_id": 0 if small is lesson else small.get("id"),
                        "video_id": small.get("videoId"),
                        "video_sec": small.get("videoSec") or 0,
                    }
                    try:
                        if self.watch_video(video):
                            completed += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1

        return {"completed": completed, "failed": failed, "total": completed + failed}
