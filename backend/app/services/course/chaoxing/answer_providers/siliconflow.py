import json
import math
import time

import requests
from loguru import logger

from ..answer_base import Tiku
from ..answer_utils import (
    _clean_option_prefix,
    _ensure_answer_list,
    _prepare_option_lines,
    _strip_json_block,
)

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_MIN_INTERVAL = 3.0
_DEFAULT_RETRY_DELAY = 2.0


def _parse_attempt_count(value, default: int = _DEFAULT_MAX_RETRIES) -> int:
    """Parse total attempts while keeping one request for a zero setting."""
    try:
        if isinstance(value, bool):
            parsed = int(value)
        elif isinstance(value, int):
            parsed = value
        elif isinstance(value, float):
            if not math.isfinite(value) or not value.is_integer():
                raise ValueError
            parsed = int(value)
        elif isinstance(value, str):
            parsed = int(value.strip(), 10)
        else:
            parsed = int(value)
        if parsed < 0:
            raise ValueError
        return max(1, parsed)
    except (TypeError, ValueError, OverflowError):
        return default


def _parse_non_negative_finite(value, default: float) -> float:
    """Parse a delay-like setting, falling back for invalid/non-finite values."""
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed) or parsed < 0:
        return default
    return parsed


class SiliconFlow(Tiku):
    """硅基流动大模型答题实现"""

    def __init__(self):
        super().__init__()
        self.name = "硅基流动大模型"
        self.last_request_time = None
        self.min_interval = _DEFAULT_MIN_INTERVAL
        self.timeout = 30
        self.max_retries = _DEFAULT_MAX_RETRIES
        self.retry_delay = _DEFAULT_RETRY_DELAY

    def _query(self, q_info: dict):
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        prompt_map = {
            "single": '单选题。直接输出JSON，禁止解释或Markdown。格式：{"Answer": ["B"]}（仅填选项字母）',
            "multiple": '多选题。直接输出JSON，禁止解释或Markdown。格式：{"Answer": ["A", "C"]}（填所有正确选项字母）',
            "completion": '填空题。直接输出JSON，禁止解释或Markdown。格式：{"Answer": ["答案"]}',
            "judgement": '判断题。直接输出JSON，禁止解释或Markdown。格式：{"Answer": ["正确"]} 或 {"Answer": ["错误"]}',
        }

        system_prompt = prompt_map.get(
            q_info.get("type"), '直接输出JSON答案，禁止解释或Markdown。格式：{"Answer": ["答案"]}'
        )

        cleaned_options = [_clean_option_prefix(opt) for opt in _prepare_option_lines(q_info.get("options", []))]
        user_content = f"题目：{q_info.get('title', '')}".strip()
        if cleaned_options:
            user_content = f"{user_content}\n选项：{chr(10).join(cleaned_options)}"

        payload = {
            "model": self.model_name,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
            "stream": False,
            "max_tokens": 4096,
            "temperature": 0.7,
            "top_p": 0.7,
            "response_format": {"type": "text"},
        }

        last_error = None
        max_attempts = _parse_attempt_count(self.max_retries)
        retry_delay = _parse_non_negative_finite(self.retry_delay, _DEFAULT_RETRY_DELAY)
        min_interval = _parse_non_negative_finite(self.min_interval, _DEFAULT_MIN_INTERVAL)
        for attempt in range(1, max_attempts + 1):
            try:
                if self.last_request_time:
                    interval = time.time() - self.last_request_time
                    if interval < min_interval:
                        time.sleep(min_interval - interval)

                response = self._session.post(self.api_endpoint, headers=headers, json=payload, timeout=self.timeout)
                self.last_request_time = time.time()

                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")

                result = response.json()
                content = result["choices"][0]["message"]["content"]
                parsed = json.loads(_strip_json_block(content))
                answers = _ensure_answer_list(parsed.get("Answer") or parsed.get("answer"))
                if not answers:
                    raise ValueError("硅基流动返回答案为空")
                return "\n".join(answers).strip()
            except (requests.RequestException, ValueError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
                last_error = exc
                logger.warning(f"硅基流动API调用失败 ({attempt}/{max_attempts}): {exc}")
                if attempt < max_attempts:
                    time.sleep(retry_delay * attempt)

        logger.error(f"硅基流动API连续失败，最后错误: {last_error}")
        return None

    def _init_tiku(self):
        # 从配置文件读取参数
        self.api_endpoint = self._conf.get("siliconflow_endpoint", "https://api.siliconflow.cn/v1/chat/completions")
        self.api_key = self._conf["siliconflow_key"]
        self.model_name = self._conf.get("siliconflow_model", "deepseek-ai/DeepSeek-V3")
        self.min_interval = _parse_non_negative_finite(
            self._conf.get("min_interval_seconds", _DEFAULT_MIN_INTERVAL),
            _DEFAULT_MIN_INTERVAL,
        )
        self.timeout = int(self._conf.get("timeout", 30))
        self.max_retries = _parse_attempt_count(self._conf.get("max_retries", _DEFAULT_MAX_RETRIES))
        self.retry_delay = _parse_non_negative_finite(
            self._conf.get("retry_delay", _DEFAULT_RETRY_DELAY),
            _DEFAULT_RETRY_DELAY,
        )
        self._session = requests.Session()
