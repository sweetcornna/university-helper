import re
import threading
import time

import requests
from loguru import logger

from ..answer_base import Tiku


class TikuGo(Tiku):
    """GO题（网课小工具）题库实现，对接 https://q.icodef.com/wyn-nb 。

    Ported from upstream Samueli924/chaoxing and adapted to this fork's
    conventions: per-instance state (multi-tenant isolation), explicit request
    timeouts, and loguru. A free search source — `go_authorization` is optional.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = "GO题（网课小工具题库）"
        self.api = "https://q.icodef.com/wyn-nb?v=4"
        self._headers = {
            "Authorization": "",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        self._request_lock = threading.Lock()
        self._last_request_time = 0.0
        self._min_interval = 1.0
        self._retry_times = 3
        self._retry_backoff = 1.2
        self._timeout = 15

    # -- throttle ---------------------------------------------------------
    def _sleep_for_next_request(self) -> None:
        with self._request_lock:
            now = time.time()
            wait_time = max(0.0, self._last_request_time + self._min_interval - now)
            self._last_request_time = now + wait_time
        if wait_time > 0:
            time.sleep(wait_time)

    def _mark_request_finished(self) -> None:
        with self._request_lock:
            self._last_request_time = time.time()

    # -- request / parse --------------------------------------------------
    def _request_question(self, question: str, attempt: int):
        try:
            self._sleep_for_next_request()
            res = requests.post(
                self.api,
                data={"question": question},
                headers=self._headers,
                timeout=self._timeout,
            )
            self._mark_request_finished()
            return res
        except requests.exceptions.RequestException as e:
            logger.error(f"{self.name}查询异常 ({attempt}/{self._retry_times}): {e}")
            self._mark_request_finished()
            return None

    def _parse_response(self, res):
        if res.status_code != 200:
            logger.error(f"{self.name}查询失败: 状态码 {res.status_code}, 响应: {res.text}")
            return None
        try:
            res_json = res.json()
        except ValueError:
            logger.error(f"{self.name}查询失败: 返回内容不是有效JSON, 响应: {res.text}")
            return None
        # A valid-JSON-but-non-object body (list/str/number/null/bool) from this
        # free third-party host must not crash the worker via res_json.get(...).
        if not isinstance(res_json, dict):
            logger.error(f"{self.name}查询失败: 返回结构非预期对象, 响应: {res.text}")
            return None
        try:
            code = int(str(res_json.get("code", "")).strip())
        except ValueError:
            code = 0
        answer = str(res_json.get("data", "")).strip()
        msg = str(res_json.get("msg", "")).strip()
        raw_text = f"{answer} {msg}"
        is_throttled = any(key in raw_text for key in ["流控限制", "速度太快", "并发限制", "忙不过来"])
        return {"code": code, "answer": answer, "msg": msg, "is_throttled": is_throttled}

    def _sleep_retry(self, attempt: int, reason: str, include_min_interval: bool = False) -> None:
        if include_min_interval:
            sleep_seconds = max(self._min_interval, self._retry_backoff * attempt)
        else:
            sleep_seconds = self._retry_backoff * attempt
        logger.warning(f"{self.name}{reason}，{sleep_seconds:.1f}s 后重试 ({attempt}/{self._retry_times})")
        time.sleep(sleep_seconds)

    @staticmethod
    def _is_placeholder_answer(answer: str, msg: str) -> bool:
        # GO题库 returns "李恒雅正在努力撰写中..." when it has no answer.
        return "李恒雅" in answer or "李恒雅" in msg

    # -- query ------------------------------------------------------------
    def _query(self, q_info: dict):
        title = q_info.get("title", "")
        candidates = [
            title,
            re.sub(r"^【[^】]+】\s*", "", title).strip(),
            re.sub(r"^\[[^\]]+\]\s*", "", title).strip(),
        ]
        seen = set()
        normalized_titles = []
        for item in candidates:
            if item and item not in seen:
                seen.add(item)
                normalized_titles.append(item)

        for query_title in normalized_titles:
            answer = self._query_once(query_title)
            if answer:
                return answer
        return None

    def _query_once(self, question: str):
        for attempt in range(1, self._retry_times + 1):
            res = self._request_question(question, attempt)
            if res is None:
                if attempt < self._retry_times:
                    self._sleep_retry(attempt, "查询异常", include_min_interval=True)
                    continue
                break

            parsed = self._parse_response(res)
            if not parsed:
                return None

            code = parsed["code"]
            answer = parsed["answer"]
            msg = parsed["msg"]
            is_throttled = parsed["is_throttled"]

            if code != 1:
                if is_throttled and attempt < self._retry_times:
                    self._sleep_retry(attempt, "触发流控")
                    continue
                logger.info(f"{self.name}未命中或失败: {msg or '未知错误'}")
                return None

            if not answer:
                return None

            if self._is_placeholder_answer(answer, msg):
                if is_throttled and attempt < self._retry_times:
                    self._sleep_retry(attempt, "命中流控提示")
                    continue
                return None

            return answer

        return None

    # -- config -----------------------------------------------------------
    def _init_tiku(self):
        self._headers["Authorization"] = self._conf.get("go_authorization", self._headers["Authorization"])
        try:
            min_interval = float(self._conf.get("go_min_interval", self._min_interval))
            if min_interval < 0:
                raise ValueError("go_min_interval must be non-negative")
            self._min_interval = min_interval
        except (TypeError, ValueError):
            logger.warning(f"{self.name}配置 go_min_interval 无效，使用默认值 {self._min_interval}")

        try:
            retry_times = int(self._conf.get("go_retry_times", self._retry_times))
            if retry_times < 1:
                raise ValueError("go_retry_times must be >= 1")
            self._retry_times = retry_times
        except (TypeError, ValueError):
            logger.warning(f"{self.name}配置 go_retry_times 无效，使用默认值 {self._retry_times}")

        try:
            retry_backoff = float(self._conf.get("go_retry_backoff", self._retry_backoff))
            if retry_backoff < 0:
                raise ValueError("go_retry_backoff must be non-negative")
            self._retry_backoff = retry_backoff
        except (TypeError, ValueError):
            logger.warning(f"{self.name}配置 go_retry_backoff 无效，使用默认值 {self._retry_backoff}")
