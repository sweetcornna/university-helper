import random
import time
from hashlib import md5
from typing import Literal

import requests
from loguru import logger
from requests import RequestException
from tqdm import tqdm

from .config import GlobalConst as gc
from .constants import MILLISECONDS_MULTIPLIER, VIDEO_SLEEP_THRESHOLD, VIDEO_WAIT_TIME_MAX, VIDEO_WAIT_TIME_MIN
from .rate_limiter import RateLimiter


class ChaoxingMediaService:
    def __init__(self, get_fid_func, rate_limiter: RateLimiter, video_log_limiter: RateLimiter, session_manager=None):
        self.get_fid = get_fid_func
        self.rate_limiter = rate_limiter
        self.video_log_limiter = video_log_limiter
        self.session_manager = session_manager

    def video_progress_log(self, session, _course, _job, _job_info, _dtoken, duration, play_time, _type, headers=None):
        self.video_log_limiter.limit_rate()
        _url = "https://mooc1.chaoxing.com/multimedia/log/a/" + _course["cpi"] + "/" + _dtoken
        _data = {
            "otherInfo": _job["otherinfo"],
            "playingTime": str(play_time),
            "duration": str(duration),
            "akid": _job["property"]["akid"],
            "jobid": _job["jobid"],
            "clipTime": f"0_{duration}",
            "clazzId": _course["clazzId"],
            "objectId": _job["objectid"],
            "userid": _job["property"]["userid"],
            "isdrag": _job["property"]["isdrag"],
            "enc": md5(
                f'[{_job["property"]["userid"]}][{_course["cpi"]}][{_job["jobid"]}][{_job["objectid"]}][{play_time * MILLISECONDS_MULTIPLIER}][d_yHJ!$pdA~5][{duration * MILLISECONDS_MULTIPLIER}][0_{duration}]'.encode()
            ).hexdigest(),
            "rt": _job["property"]["rt"],
            "dtype": _job["property"]["dtype"],
            "view": "pc",
        }

        try:
            resp = session.get(_url, params=_data, timeout=8, headers=headers or {})
        except RequestException as exc:
            logger.debug("上报进度失败: {}", exc)
            return False, 0

        if resp.status_code == 403:
            logger.warning("上报进度返回403")
            return False, 403

        if resp.status_code != 200:
            logger.debug("上报进度返回码异常: {}", resp.status_code)
            return False, resp.status_code

        return resp.json().get("isPassed", False), resp.status_code

    def _refresh_video_status(
        self, session: requests.Session, job: dict, _type: Literal["Video", "Audio"]
    ) -> dict | None:
        self.rate_limiter.limit_rate(random_time=True, random_max=0.2)
        headers = gc.VIDEO_HEADERS if _type == "Video" else gc.AUDIO_HEADERS
        info_url = f"https://mooc1.chaoxing.com/ananas/status/{job['objectid']}?" f"k={self.get_fid()}&flag=normal"
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

    def _recover_after_forbidden(
        self, session: requests.Session, job: dict, _type: Literal["Video", "Audio"], account=None, login_func=None
    ):
        self.session_manager.update_cookies()
        refreshed = self._refresh_video_status(session, job, _type)
        if refreshed:
            return refreshed

        if False and account and account.username and account.password and login_func:
            login_result = login_func(login_with_cookies=False)
            if login_result.get("status"):
                self.session_manager.update_cookies()
                return self._refresh_video_status(session, job, _type)
            logger.warning("账号密码登录失败: {}", login_result.get("msg"))

        return None

    def study_video(
        self,
        _course,
        _job,
        _job_info,
        _speed: float = 1.0,
        _type: Literal["Video", "Audio"] = "Video",
        progress_callback=None,
        should_stop=None,
        account=None,
        login_func=None,
    ):
        _session = self.session_manager.get_session()

        headers = gc.VIDEO_HEADERS if _type == "Video" else gc.AUDIO_HEADERS
        _info_url = f"https://mooc1.chaoxing.com/ananas/status/{_job['objectid']}?k={self.get_fid()}&flag=normal"
        _video_info = _session.get(_info_url, headers=headers).json()

        if _video_info["status"] != "success":
            logger.error(f"Unknown status: {_video_info['status']}")
            return False

        _dtoken = _video_info["dtoken"]
        _crc = _video_info["crc"]
        _key = _video_info["key"]

        duration = int(_video_info["duration"])
        play_time = int(_job["playTime"]) // 1000
        last_log_time = 0
        last_iter = time.time()
        wait_time = int(random.uniform(VIDEO_WAIT_TIME_MIN, VIDEO_WAIT_TIME_MAX))

        logger.info(f"开始任务: {_job['name']}, 总时长: {duration}s, 已进行: {play_time}s")

        if callable(progress_callback):
            try:
                progress_callback(_course, _job, float(play_time), float(duration))
            except Exception as exc:
                logger.debug(f"视频进度回调执行失败(初始): {exc}")

        pbar = tqdm(
            total=duration,
            initial=play_time,
            desc=_job["name"],
            unit_scale=True,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}",
        )

        forbidden_retry = 0
        max_forbidden_retry = 2

        # 仅以真实的 play_time 上报一次。旧代码紧接着又以 playingTime==duration
        # 再报一次，等于一上来就声称整段视频已看完，覆盖了第一次上报。
        passed, state = self.video_progress_log(
            _session, _course, _job, _job_info, _dtoken, duration, play_time, _type, headers=headers
        )

        if passed:
            logger.info("任务瞬间完成: {}", _job["name"])
            return True

        while not passed:
            if callable(should_stop) and should_stop():
                logger.info("任务被取消: {}", _job["name"])
                return False
            if play_time - last_log_time >= wait_time or play_time == duration:
                passed, state = self.video_progress_log(
                    _session, _course, _job, _job_info, _dtoken, duration, int(play_time), _type, headers=headers
                )

                if state == 403:
                    if forbidden_retry >= max_forbidden_retry:
                        logger.warning("403重试失败, 跳过当前任务")
                        return False
                    forbidden_retry += 1
                    logger.warning("出现403报错, 正在尝试刷新会话状态 (第{}次)", forbidden_retry)
                    time.sleep(random.uniform(2, 4))
                    refreshed_meta = self._recover_after_forbidden(_session, _job, _type, account, login_func)
                    if refreshed_meta:
                        _dtoken = refreshed_meta.get("dtoken", _dtoken)
                        # 应用刷新后的 duration（旧代码赋给死变量 _duration，循环继续用旧值）。
                        refreshed_duration = refreshed_meta.get("duration", duration)
                        try:
                            duration = int(refreshed_duration)
                        except (TypeError, ValueError):
                            logger.debug("刷新返回的 duration 非法，沿用旧值: {}", refreshed_duration)
                        play_time = refreshed_meta.get("playTime", play_time)
                        logger.debug("Refreshed token: {}, duration: {}, play time: {}", _dtoken, duration, play_time)
                        continue

                elif not passed and state != 200:
                    return False

                wait_time = int(random.uniform(VIDEO_WAIT_TIME_MIN, VIDEO_WAIT_TIME_MAX))
                last_log_time = play_time

            dt = (time.time() - last_iter) * _speed
            last_iter = time.time()
            play_time = min(duration, play_time + dt)

            pbar.n = int(play_time)
            pbar.refresh()

            if callable(progress_callback):
                try:
                    progress_callback(_course, _job, float(play_time), float(duration))
                except Exception as exc:
                    logger.debug(f"视频进度回调执行失败: {exc}")

            time.sleep(VIDEO_SLEEP_THRESHOLD)

        logger.info("任务完成: {}", _job["name"])
        return True
