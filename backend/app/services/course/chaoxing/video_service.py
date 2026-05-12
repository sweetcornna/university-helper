# -*- coding: utf-8 -*-
"""Video/Audio learning service for Chaoxing."""

import re
import random
import time
from typing import Optional, Literal

import requests
from requests import RequestException
from loguru import logger
from tqdm import tqdm

from .config import GlobalConst as gc
from .course_service import get_timestamp
from .rate_limiter import RateLimiter
from .session_manager import SessionManager
from .constants import (
    VIDEO_LOG_RATE_LIMIT,
    VIDEO_WAIT_TIME_MIN,
    VIDEO_WAIT_TIME_MAX,
    VIDEO_SLEEP_THRESHOLD,
    MAX_FORBIDDEN_RETRY,
    MILLISECONDS_MULTIPLIER,
)


class ChaoxingVideoService:
    """Handles video and audio progress logging and study tasks."""

    def __init__(self, get_fid_func, get_uid_func, rate_limiter: RateLimiter, video_log_limiter: RateLimiter):
        self._get_fid = get_fid_func
        self._get_uid = get_uid_func
        self.rate_limiter = rate_limiter
        self.video_log_limiter = video_log_limiter

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def get_enc(self, clazzId, jobid, objectId, playingTime, duration, userid):
        from hashlib import md5
        return md5(
            f"[{clazzId}][{userid}][{jobid}][{objectId}][{playingTime * MILLISECONDS_MULTIPLIER}][d_yHJ!$pdA~5][{duration * MILLISECONDS_MULTIPLIER}][0_{duration}]".encode()
        ).hexdigest()

    # ------------------------------------------------------------------
    # Progress logging
    # ------------------------------------------------------------------

    def video_progress_log(
            self,
            _session,
            _course,
            _job,
            _job_info,
            _dtoken,
            _duration,
            _playingTime,
            _type: str = "Video",
            headers: Optional[dict] = None,
    ) -> tuple[bool, int]:
        """
        Log video/audio progress to the server.

        Returns:
            Tuple of (isPassed: bool, status_code: int)
        """

        if headers is None:
            logger.warning("null headers")
            headers = gc.VIDEO_HEADERS

        self.video_log_limiter.limit_rate(random_time=True, random_max=VIDEO_LOG_RATE_LIMIT)

        if "courseId" in _job["otherinfo"]:
            logger.error(_job["otherinfo"])
            raise RuntimeError("this is not possible")

        enc = self.get_enc(_course["clazzId"], _job["jobid"], _job["objectid"], _playingTime, _duration, self._get_uid())
        params = {
            "clazzId": _course["clazzId"],
            "playingTime": _playingTime,
            "duration": _duration,
            "clipTime": f"0_{_duration}",
            "objectId": _job["objectid"],
            "otherInfo": _job["otherinfo"],
            "courseId": _course["courseId"],
            "jobid": _job["jobid"],
            "userid": self._get_uid(),
            "isdrag": "3",
            "view": "pc",
            "enc": enc,
            "dtype": _type
        }

        _url = (
            f"https://mooc1.chaoxing.com/mooc-ans/multimedia/log/a/"
            f"{_course['cpi']}/"
            f"{_dtoken}"
        )

        face_capture_enc = _job["videoFaceCaptureEnc"]
        att_duration = _job["attDuration"]
        att_duration_enc = _job["attDurationEnc"]

        if face_capture_enc:
            params["videoFaceCaptureEnc"] = face_capture_enc
        if att_duration:
            params["attDuration"] = att_duration
        if att_duration_enc:
            params["attDurationEnc"] = att_duration_enc

        rt = _job['rt']
        if not rt:
            rt_search = re.search(r"-rt_([1d])", _job['otherinfo'])
            if rt_search:
                rt_char = rt_search.group(1)
                rt = "0.9" if rt_char == "d" else "1"
                logger.trace(f"Got rt from otherinfo: {rt}")

        if rt:
            logger.trace(f"Got rt: {rt}")
            params.update({"rt": rt,
                           "_t": get_timestamp()})
            resp = _session.get(_url, params=params, headers=headers)
        else:
            logger.warning("Failed to get rt")
            for rt in [0.9, 1]:
                params.update({"rt": rt,
                               "_t": get_timestamp()})
                resp = _session.get(_url, params=params, headers=headers)
                if resp.status_code == 200:
                    logger.trace(resp.text)
                    return resp.json()["isPassed"], 200
                elif resp.status_code == 403:
                    logger.warning("出现403报错, 正常尝试切换rt")
                else:
                    logger.warning("未知错误 jobid={}, status_code={}, 摘要:\n{}",
                                   _job.get("jobid"),
                                   resp.status_code,
                                   resp.text[:200]
                    )
                    break

        if resp.status_code == 200:
            logger.trace(resp.text)
            return resp.json()["isPassed"], 200

        elif resp.status_code == 403:
            logger.debug(
                "视频进度上报返回403, jobid={}, 摘要={}",
                _job.get("jobid"),
                resp.text[:200],
            )

            logger.error("出现403报错, 尝试修复无效, 正在跳过当前任务点...")
            logger.error("请求url: {}", resp.url)
            logger.error("请求头: {}", dict(_session.headers) | headers)
            return False, 403

        logger.error(f"未知错误: {resp.status_code}")
        logger.error("请求url: {}", resp.url)
        logger.error("请求头: {}", dict(_session.headers) | headers)
        return False, resp.status_code

    # ------------------------------------------------------------------
    # Refresh / recovery
    # ------------------------------------------------------------------

    def _refresh_video_status(self, session: requests.Session, job: dict, _type: Literal["Video", "Audio"]) -> Optional[dict]:
        self.rate_limiter.limit_rate(random_time=True, random_max=0.2)
        headers = gc.VIDEO_HEADERS if _type == "Video" else gc.AUDIO_HEADERS
        info_url = (
            f"https://mooc1.chaoxing.com/ananas/status/{job['objectid']}?"
            f"k={self._get_fid()}&flag=normal"
        )
        try:
            resp = session.get(info_url, timeout=8, headers=headers)
        except RequestException as exc:
            logger.debug("刷新视频状态失败: {}", exc)
            return None

        if resp.status_code != 200:
            logger.debug("刷新视频状态返回码异常: {}", resp.status_code)
            logger.debug(resp.text)
            return None

        try:
            data = resp.json()
        except ValueError as exc:
            logger.debug("解析视频状态响应失败: {}", exc)
            return None

        if data.get("status") == "success":
            return data

        return None

    def _recover_after_forbidden(self, session: requests.Session, job: dict, _type: Literal["Video", "Audio"]):
        SessionManager.update_cookies()
        refreshed = self._refresh_video_status(session, job, _type)
        if refreshed:
            return refreshed
        return None

    # ------------------------------------------------------------------
    # Main study entry point
    # ------------------------------------------------------------------

    def study_video(
        self,
        _course,
        _job,
        _job_info,
        _speed: float = 1.0,
        _type: Literal["Video", "Audio"] = "Video",
        progress_callback=None,
        should_stop=None,
    ):
        """
        Complete a video or audio learning task.

        Returns:
            StudyResult indicating success, forbidden, error, or timeout
        """
        from .client import StudyResult

        _session = SessionManager.get_session()

        headers = gc.VIDEO_HEADERS if _type == "Video" else gc.AUDIO_HEADERS
        _info_url = f"https://mooc1.chaoxing.com/ananas/status/{_job['objectid']}?k={self._get_fid()}&flag=normal"
        try:
            _video_info = _session.get(_info_url, headers=headers).json()
        except (RequestException, ValueError) as exc:
            logger.warning("获取视频信息失败 (jobid={}): {}", _job.get("jobid"), exc)
            return StudyResult.ERROR

        if _video_info["status"] != "success":
            logger.error(f"Unknown status: {_video_info['status']}")
            return StudyResult.ERROR

        _dtoken = _video_info["dtoken"]
        _crc = _video_info["crc"]
        _key = _video_info["key"]

        duration = int(_video_info["duration"])
        play_time = int(_job["playTime"]) // 1000
        last_log_time = 0
        last_iter = time.time()

        # Adaptive polling: shorter videos use shorter intervals
        if duration < 180:
            wait_time = int(random.uniform(20, 40))
        elif duration < 600:
            wait_time = int(random.uniform(30, 60))
        else:
            wait_time = int(random.uniform(VIDEO_WAIT_TIME_MIN, VIDEO_WAIT_TIME_MAX))

        logger.info(f"开始任务: {_job['name']}, 总时长: {duration}s, 已进行: {play_time}s")

        # 首次上报进度
        if callable(progress_callback):
            try:
                progress_callback(_course, _job, float(play_time), float(duration))
            except Exception as exc:
                logger.debug(f"视频进度回调执行失败(初始): {exc}")

        pbar = tqdm(total=duration, initial=play_time, desc=_job["name"],
                    unit_scale=True, bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')

        forbidden_retry = 0
        max_forbidden_retry = MAX_FORBIDDEN_RETRY

        passed, state = self.video_progress_log(_session, _course, _job, _job_info, _dtoken, duration, play_time, _type, headers=headers)

        if passed:
            logger.info("任务瞬间完成: {}", _job['name'])
            return StudyResult.SUCCESS

        while not passed:
            if callable(should_stop) and should_stop():
                return StudyResult.CANCELLED
            if play_time - last_log_time >= wait_time or play_time == duration:

                passed, state = self.video_progress_log(_session, _course, _job, _job_info, _dtoken, duration,
                                                        int(play_time), _type, headers=headers)

                if state == 403:
                    if forbidden_retry >= max_forbidden_retry:
                        logger.warning("403重试失败, 跳过当前任务")
                        return StudyResult.FORBIDDEN
                    forbidden_retry += 1
                    logger.warning(
                        "出现403报错, 正在尝试刷新会话状态 (第{}次)",
                        forbidden_retry,
                    )
                    time.sleep(random.uniform(2, 4))
                    refreshed_meta = self._recover_after_forbidden(_session, _job, _type)
                    if refreshed_meta:
                        _dtoken = refreshed_meta.get("dtoken", _dtoken)
                        _duration = refreshed_meta.get("duration", duration)
                        play_time = refreshed_meta.get("playTime", play_time)

                        logger.debug("Refreshed session: duration={}, play_time={}", _duration, play_time)
                        continue

                elif not passed and state != 200:
                    return StudyResult.ERROR

                # Adaptive polling interval
                if duration < 180:
                    wait_time = int(random.uniform(20, 40))
                elif duration < 600:
                    wait_time = int(random.uniform(30, 60))
                else:
                    wait_time = int(random.uniform(VIDEO_WAIT_TIME_MIN, VIDEO_WAIT_TIME_MAX))
                last_log_time = play_time

            dt = (time.time() - last_iter) * _speed
            last_iter = time.time()
            play_time = min(duration, play_time + dt)

            pbar.n = int(play_time)
            pbar.refresh()

            # 实时上报进度给外部（如 Web 前端）
            if callable(progress_callback):
                try:
                    progress_callback(_course, _job, float(play_time), float(duration))
                except Exception as exc:
                    logger.debug(f"视频进度回调执行失败: {exc}")

            time.sleep(VIDEO_SLEEP_THRESHOLD)

        logger.info("任务完成: {}", _job['name'])
        return StudyResult.SUCCESS
