"""智慧树自动学习模块"""
import time
import json
from typing import Optional, Dict, List
import requests
from .crypto import Cipher, WatchPoint, VIDEO_KEY, HOME_KEY, encrypt_secret_str


class ZhihuishuLearning:
    """智慧树自动学习服务"""

    def __init__(self, cookies: dict, proxies: Optional[dict] = None):
        self.cookies = cookies
        self.proxies = proxies or {}
        self.session = requests.Session()
        self.session.cookies.update(cookies)
        self.cipher = Cipher(VIDEO_KEY)

    def get_course_list(self) -> List[Dict]:
        """获取课程列表（共享课）

        Zhihuishu 的 AppInterfaceSign 拦截器现在强制要求 AES 签名参数 ``secretStr``：
        未签名请求会被拒（code 400 "aes加密参数异常"），导致旧代码读不到数据→空列表。
        已对真实账号验证：HOME_KEY + secretStr(JSON对象) → code 200，数据在 ``result``
        下（旧版为 ``rt``）。courseOpenDtos 可能为 null → []。
        """
        url = "https://onlineservice-api.zhihuishu.com/gateway/t/v1/student/course/share/queryShareCourseInfo"
        try:
            resp = self.session.post(
                url,
                data={"secretStr": encrypt_secret_str(key=HOME_KEY)},
                proxies=self.proxies,
                timeout=10,
            )
            data = resp.json()
            result = data.get("result") or data.get("rt") or {}
            return result.get("courseOpenDtos") or []
        except Exception as e:
            raise Exception(f"Failed to get course list: {e}")

    def get_video_list(self, course_id: str) -> List[Dict]:
        """获取课程视频列表

        同 get_course_list：studyservice-api 走同一套 AppInterfaceSign 拦截器，故同样
        需要 ``secretStr`` 签名（把请求参数加密放进 secretStr）。响应同样优先读 ``result``，
        回退 ``rt``。注意：此端点的密钥未能在本次离线验证（账号当前无共享课），沿用
        HOME_KEY；如线上仍报 "aes解密异常"，需用真实选课账号抓包确认该服务的密钥。
        """
        url = "https://studyservice-api.zhihuishu.com/gateway/t/v1/learning/queryStudyInfo"
        try:
            resp = self.session.post(
                url,
                data={"secretStr": encrypt_secret_str({"recruitAndCourseId": course_id}, key=HOME_KEY)},
                proxies=self.proxies,
                timeout=10,
            )
            data = resp.json()
            result = data.get("result") or data.get("rt") or {}
            return result.get("videoChapterDtos") or []
        except Exception as e:
            raise Exception(f"Failed to get video list: {e}")

    def watch_video(
        self,
        course_id: str,
        video_id: str,
        duration: int,
        speed: float = 1.0,
        is_cancelled=None,
        is_paused=None,
    ) -> bool:
        """
        观看视频

        Args:
            course_id: 课程ID
            video_id: 视频ID
            duration: 视频时长（秒）
            speed: 播放倍速（>1 加快，钳制到合理范围以保持上报节奏）
            is_cancelled: 可选回调，返回 True 时立即中止（响应取消）
            is_paused: 可选回调，返回 True 时暂停上报（响应暂停）

        Returns:
            是否成功
        """
        url = "https://studyservice-api.zhihuishu.com/gateway/t/v1/learning/saveDatabaseIntervalTime"

        try:
            duration = int(duration or 0)
        except (TypeError, ValueError):
            duration = 0
        if duration <= 0:
            # 时长缺失/为 0：绝不"秒标完成"。原实现会让 while 一次都不进、直接返回
            # True，于是视频被记为 100% 却一个观看点都没上报。改为抛错→上层记为失败，
            # 让进度反映真实情况。(F-zero-duration)
            raise Exception(f"video {video_id} has no usable duration ({duration!r})")

        # 倍速：以前 watch_video 完全忽略 speed，N 小时课就实打实跑 N 小时。这里把
        # speed 钳制到 [1,2]，缩短真实 sleep（studyTime 仍按 5 秒步进上报），既加速又
        # 保持可信的上报节奏以规避风控。(F-speed)
        try:
            eff_speed = float(speed)
        except (TypeError, ValueError):
            eff_speed = 1.0
        eff_speed = min(max(eff_speed, 1.0), 2.0)
        interval = 5
        sleep_seconds = interval / eff_speed

        watch_point = WatchPoint()
        current_time = 0

        try:
            while current_time < duration:
                # 在每个上报周期开始时检查取消/暂停，使暂停与取消在"播放过程中"即可生效，
                # 而不必等整段视频跑完。(F-pause-cancel)
                if callable(is_cancelled) and is_cancelled():
                    return False
                while callable(is_paused) and is_paused():
                    if callable(is_cancelled) and is_cancelled():
                        return False
                    time.sleep(0.3)

                time.sleep(sleep_seconds)
                current_time += interval
                watch_point.add(current_time)

                data = {
                    "recruitAndCourseId": course_id,
                    "videoId": video_id,
                    "watchPoint": watch_point.get(),
                    "studyTime": current_time
                }

                encrypted = self.cipher.encrypt(json.dumps(data))
                resp = self.session.post(url, json={"data": encrypted},
                                       proxies=self.proxies, timeout=10)
                result = resp.json()

                if result.get("status") != 200:
                    return False

            return True

        except Exception as e:
            raise Exception(f"Failed to watch video: {e}")

    def complete_course(self, course_id: str) -> Dict:
        """
        完成整个课程

        Args:
            course_id: 课程ID

        Returns:
            完成统计信息
        """
        videos = self.get_video_list(course_id)
        completed = 0
        failed = 0

        for chapter in videos:
            for video in chapter.get("videoLearningDtos", []):
                video_id = video.get("videoId")
                duration = video.get("videoSec", 0)

                try:
                    if self.watch_video(course_id, video_id, duration):
                        completed += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1

        return {"completed": completed, "failed": failed, "total": completed + failed}
