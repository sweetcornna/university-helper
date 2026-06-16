import json
import re
import threading
import time

import httpx
from loguru import logger

from ..answer_base import Tiku
from ..answer_utils import (
    _clean_option_prefix,
    _ensure_answer_list,
    _prepare_option_lines,
    _strip_json_block,
)


class AI(Tiku):
    """AI大模型答题实现，带重试与更鲁棒的解析"""

    def __init__(self) -> None:
        super().__init__()
        self.name = "AI大模型答题"
        self.last_request_time = None
        # NOTE: this provider talks to the model over httpx (self._httpx_client),
        # not the `openai` SDK; `OpenAI` was never imported. Drop the dead type
        # reference (the attribute is always None / unused here). (ruff F821)
        self.client = None
        self._httpx_client: httpx.Client | None = None
        self.http_proxy: str | None = None
        self.min_interval_seconds: float = 3
        self.timeout: float = 30
        self.max_retries: int = 3
        self.retry_delay: float = 2.0
        self.disable_ssl_verify: bool = False
        self._interval_lock = threading.Lock()
        # 全局并发控制：限制同一 AI 客户端同时在请求中的题目数量
        self.max_active_requests: int = 3
        self._request_semaphore: threading.Semaphore | None = None
        # 精简提示词：直接输出 JSON，禁止多余内容
        self._system_prompts = {
            "single": (
                "单选题答题。直接输出JSON，禁止解释、思考过程或Markdown。\n"
                '格式：{"Answer": ["B"]}  （B为正确选项字母，仅填A/B/C/D之一）'
            ),
            "multiple": (
                "多选题答题。直接输出JSON，禁止解释、思考过程或Markdown。\n"
                '格式：{"Answer": ["A", "C"]}  （填所有正确选项字母）'
            ),
            "completion": (
                "填空题答题。直接输出JSON，禁止解释、思考过程或Markdown。\n"
                '格式：{"Answer": ["答案1", "答案2"]}  （按空格顺序填写答案）'
            ),
            "judgement": (
                "判断题答题。直接输出JSON，禁止解释、思考过程或Markdown。\n"
                '格式：{"Answer": ["正确"]} 或 {"Answer": ["错误"]}'
            ),
            "default": ("答题助手。直接输出JSON，禁止解释、思考过程或Markdown。\n" '格式：{"Answer": ["答案"]}'),
        }

    def _build_client(self):
        httpx_kwargs = {"timeout": self.timeout}
        if self.http_proxy:
            httpx_kwargs["proxy"] = self.http_proxy
        if self.disable_ssl_verify:
            httpx_kwargs["verify"] = False
        if self._httpx_client:
            try:
                self._httpx_client.close()
            except Exception:
                pass
        self._httpx_client = httpx.Client(**httpx_kwargs)

    def _respect_interval(self):
        sleep_time = 0
        with self._interval_lock:
            if self.last_request_time:
                interval_time = time.time() - self.last_request_time
                if interval_time < self.min_interval_seconds:
                    sleep_time = self.min_interval_seconds - interval_time
            self.last_request_time = time.time()
        if sleep_time > 0:
            logger.debug(f"AI请求间隔过短, 等待 {sleep_time:.2f} 秒")
            time.sleep(sleep_time)

    def _build_messages(self, q_info: dict) -> list[dict]:
        options = [_clean_option_prefix(opt) for opt in _prepare_option_lines(q_info.get("options", []))]
        q_type = q_info.get("type", "single")
        system_prompt = self._system_prompts.get(q_type, self._system_prompts["default"])
        user_content = f"题目：{q_info.get('title', '')}".strip()
        if options:
            user_content = f"{user_content}\n选项：{chr(10).join(options)}"
        return [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]

    def _invoke_completion(self, messages: list[dict]) -> str | None:
        if not self._httpx_client:
            logger.error("AI题库 HTTP 客户端未初始化")
            return None
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            sem = self._request_semaphore
            acquired = False
            try:
                if sem is not None:
                    sem.acquire()
                    acquired = True
                self._respect_interval()
                headers = {
                    "Authorization": f"Bearer {self.key}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "model": self.model,
                    "messages": messages,
                }
                response = self._httpx_client.post(
                    self.endpoint,
                    headers=headers,
                    json=payload,
                )
                if acquired:
                    sem.release()
                    acquired = False
                if response.status_code != 200:
                    try:
                        err_body = response.json()
                    except Exception:
                        err_body = response.text[:200]
                    raise RuntimeError(f"Error code: {response.status_code} - {err_body}")

                data = response.json()
                raw_content = data["choices"][0]["message"]["content"] or ""

                # 去掉 <think> 和 </think> 标记本身，但保留其中的内容，以便从中提取 Answer JSON
                text_without_tags = re.sub(r"(?is)</?think>", "", raw_content)
                base_text = (text_without_tags or "").strip()
                if not base_text:
                    logger.warning("AI大模型返回内容为空（仅包含 <think> 标签或空白），将视为无答案处理")
                    return None

                answers: list[str] = []

                # 优先从文本中提取包含 Answer/answer 字段的 JSON 段，取最后一个作为最终答案
                json_candidate = None
                try:
                    pattern = r'\{[^{}]*(?:"Answer"|"answer")\s*:\s*\[[^\]]*\][^{}]*\}'
                    matches = re.findall(pattern, base_text, flags=re.DOTALL)
                    if matches:
                        json_candidate = matches[-1].strip()
                    else:
                        # 回退到去除 Markdown 代码块后的整体文本
                        json_candidate = _strip_json_block(base_text)
                except Exception:
                    json_candidate = _strip_json_block(base_text)

                json_candidate_stripped = (json_candidate or "").strip()

                if json_candidate_stripped:
                    # 优先按JSON解析；若失败，再尝试将单引号风格的字典转换为JSON
                    try:
                        payload = json.loads(json_candidate_stripped)
                        answers = _ensure_answer_list(payload.get("Answer") or payload.get("answer"))
                    except json.JSONDecodeError as json_exc:
                        payload = None
                        candidate_fixed = json_candidate_stripped
                        # 针对形如 {'Answer': ['输入/输出']} 的内容，尝试将单引号替换为双引号后再次解析
                        if "'" in candidate_fixed and '"' not in candidate_fixed:
                            try:
                                candidate_fixed = candidate_fixed.replace("'", '"')
                                payload = json.loads(candidate_fixed)
                            except Exception:
                                payload = None
                        if payload is not None:
                            answers = _ensure_answer_list(payload.get("Answer") or payload.get("answer"))
                        else:
                            logger.warning(
                                f"AI大模型返回内容不是标准JSON，将按纯文本处理: {json_exc}; candidate={json_candidate_stripped[:200]!r}"
                            )
                            answers = _ensure_answer_list(base_text)
                # 没有可用的 JSON 片段，直接按纯文本处理
                elif base_text:
                    answers = _ensure_answer_list(base_text)
                else:
                    logger.warning("AI大模型返回内容为空，将视为无答案处理")
                    return None

                if not answers:
                    logger.warning("AI大模型返回空答案，将视为无答案处理")
                    return None
                return "\n".join(answers).strip()
            except Exception as exc:
                last_error = exc
                msg = str(exc)
                if "429" in msg or "rate limit" in msg.lower():
                    cool_down = max(self.min_interval_seconds * 2, 5)
                    logger.warning(
                        f"AI大模型请求失败 ({attempt}/{self.max_retries}) 且触发限流，将休眠 {cool_down:.2f} 秒: {exc}"
                    )
                    time.sleep(cool_down)
                else:
                    logger.warning(f"AI大模型请求失败 ({attempt}/{self.max_retries}): {exc}")
                    time.sleep(self.retry_delay * attempt)
            finally:
                if acquired and sem is not None:
                    sem.release()
        logger.error(f"AI大模型连续失败，最后错误: {last_error}")
        return None

    def _query(self, q_info: dict):
        messages = self._build_messages(q_info)
        return self._invoke_completion(messages)

    def _init_tiku(self):
        self.endpoint = self._conf["endpoint"]
        self.key = self._conf["key"]
        self.model = self._conf["model"]
        self.http_proxy = self._conf.get("http_proxy")
        self.min_interval_seconds = float(self._conf.get("min_interval_seconds", 3))
        self.timeout = float(self._conf.get("timeout", 30))
        self.max_retries = int(self._conf.get("max_retries", 3))
        self.retry_delay = float(self._conf.get("retry_delay", 2))
        self.disable_ssl_verify = str(self._conf.get("disable_ssl_verify", "false")).lower() in {
            "1",
            "true",
            "yes",
            "on",
            "y",
        }
        # 允许通过 ai_concurrency 配置最大同时在请求中的题目数量；缺省为 3
        max_req_raw = self._conf.get("ai_concurrency")
        try:
            self.max_active_requests = int(max_req_raw) if max_req_raw is not None else 3
        except (TypeError, ValueError):
            self.max_active_requests = 3
        self.max_active_requests = max(self.max_active_requests, 1)
        self._request_semaphore = threading.Semaphore(self.max_active_requests)
        self._build_client()
