import json
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


class SiliconFlow(Tiku):
    """硅基流动大模型答题实现"""

    def __init__(self):
        super().__init__()
        self.name = "硅基流动大模型"
        self.last_request_time = None

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
        for attempt in range(1, self.max_retries + 1):
            try:
                if self.last_request_time:
                    interval = time.time() - self.last_request_time
                    if interval < self.min_interval:
                        time.sleep(self.min_interval - interval)

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
                logger.warning(f"硅基流动API调用失败 ({attempt}/{self.max_retries}): {exc}")
                time.sleep(self.retry_delay * attempt)

        logger.error(f"硅基流动API连续失败，最后错误: {last_error}")
        return None

    def _init_tiku(self):
        # 从配置文件读取参数。缺 key 时禁用本 provider，避免整条刷课任务崩溃。
        conf = self._conf or {}
        self.api_endpoint = str(
            conf.get("siliconflow_endpoint") or conf.get("endpoint") or "https://api.siliconflow.cn/v1/chat/completions"
        ).strip()
        self.api_key = str(conf.get("siliconflow_key") or conf.get("key") or conf.get("token") or "").strip()
        self.model_name = str(conf.get("siliconflow_model") or conf.get("model") or "deepseek-ai/DeepSeek-V3").strip()
        if not self.api_key:
            self.DISABLE = True
            logger.error("硅基流动题库缺少 API Key，已禁用。请填写 Token/密钥。")
            return
        self.min_interval = int(conf.get("min_interval_seconds", 3))
        self.timeout = int(conf.get("timeout", 30))
        self.max_retries = int(conf.get("max_retries", 3))
        self.retry_delay = float(conf.get("retry_delay", 2))
        self._session = requests.Session()
