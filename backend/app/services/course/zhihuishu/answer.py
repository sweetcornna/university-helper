"""智慧树 AI 答题模块"""

import hashlib
import json
import re
import string
import time
from random import choice as random_choice
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests


class ZhihuishuAnswer:
    """智慧树 AI 答题服务"""

    def __init__(self, cookies: dict, ai_config: dict, proxies: dict | None = None):
        self.cookies = cookies
        self.proxies = proxies or {}
        self.session = requests.Session()
        self.session.cookies.update(cookies)

        self.ai_enabled = ai_config.get("enabled", False)
        self.use_zhidao_ai = ai_config.get("use_zhidao_ai", True)
        self.stream = ai_config.get("use_stream", True)
        self.prefix = "8ZflKEagfL"

        openai_config = ai_config.get("openai", {})
        self.api_base = openai_config.get("api_base", "https://api.openai.com")
        self.api_key = openai_config.get("api_key", "")
        self.model_name = openai_config.get("model_name", "gpt-4")

    def answer_question(self, question: dict) -> str | None:
        """
        回答问题

        Args:
            question: 问题字典，包含题目、选项等信息

        Returns:
            答案字符串
        """
        if not self.ai_enabled:
            return None

        prompt = self._build_prompt(question)

        try:
            if self.use_zhidao_ai:
                return self._zhidao_completion(prompt)
            return self._openai_completion(prompt)
        except Exception as e:
            raise Exception(f"Failed to answer question: {e}")

    def _build_prompt(self, question: dict) -> str:
        """构建提示词"""
        q_text = question.get("title", "")
        choices = question.get("choices", [])

        prompt = f"请回答以下问题：\n\n{q_text}\n\n选项：\n"
        for choice in choices:
            prompt += f"{choice.get('name', '')}: {choice.get('content', '')}\n"

        prompt += "\n请在 ```answer 和 ``` 之间给出答案，只需要选项字母。"
        return prompt

    def _openai_completion(self, prompt: str, max_retries: int = 3) -> str:
        """使用 OpenAI API 完成答题"""
        url = f"{self.api_base}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        body = {
            "messages": [{"role": "user", "content": prompt}],
            "model": self.model_name,
            "stream": self.stream,
        }

        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers=headers, json=body, timeout=30, stream=self.stream)
                response.raise_for_status()

                if self.stream:
                    result = self._parse_stream(response)
                else:
                    result = response.json()
                    return result["choices"][0]["message"]["content"]

                return result

            except requests.exceptions.RequestException:
                if attempt < max_retries - 1:
                    time.sleep(1.0)
                else:
                    raise

    def _zhidao_completion(self, prompt: str, max_retries: int = 3) -> str:
        """使用智道 AI 完成答题"""
        base_url = "https://ai-knowledge-map-platform.zhihuishu.com/knowledgemap/gateway/t/qa/platform/stream"

        body = {
            "messageList": [{"role": "user", "content": prompt}],
            "modelCode": "moonshot-v1-32k",
            "stream": self.stream,
        }

        url, body = self._zhidao_sign(base_url, body)

        for attempt in range(max_retries):
            try:
                response = self.session.post(url, json=body, timeout=30, stream=self.stream)
                response.raise_for_status()

                if self.stream:
                    result = self._parse_stream(response)
                else:
                    result = json.loads(response.text[5:])
                    return result["choices"][0]["message"]["content"]

                return result

            except requests.exceptions.RequestException:
                if attempt < max_retries - 1:
                    time.sleep(1.0)
                else:
                    raise

    def _parse_stream(self, response: requests.Response) -> str:
        """解析流式响应"""
        cache = ""
        aim_start = "```answer"
        aim_end = "```"

        for line in response.iter_lines():
            if not line:
                continue

            try:
                json_data = json.loads(line.decode("utf-8")[5:])
                content = json_data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                if content:
                    cache += content
                    match = re.search(f"{re.escape(aim_start)}(.*?){re.escape(aim_end)}", cache, re.DOTALL)
                    if match:
                        return cache
            except json.JSONDecodeError:
                continue

        return cache

    def _zhidao_sign(self, url: str, data: dict) -> tuple:
        """生成智道 API 签名"""
        scheme, netloc, path, query_string, fragment = urlsplit(url)
        query_params = dict(parse_qsl(query_string))

        if "sessionNid" not in data:
            data["sessionNid"] = self._generate_session_nid()

        input_string = self._build_input_string(data)
        signature = self._generate_signature(input_string)
        query_params["sign"] = signature

        new_query_string = urlencode(query_params)
        new_url = urlunsplit((scheme, netloc, path, new_query_string, fragment))

        return new_url, data

    def _generate_session_nid(self) -> str:
        """生成随机会话 ID"""
        chars = string.ascii_lowercase + string.digits
        return "chatcmpl-" + "".join(random_choice(chars) for _ in range(24))

    def _generate_signature(self, input_string: str) -> str:
        """生成 MD5 签名"""
        return hashlib.md5((self.prefix + input_string).encode("utf-8")).hexdigest()

    def _build_input_string(self, data: dict) -> str:
        """构建签名输入字符串"""
        json_data = {
            "messageList": "[object Object]",
            "modelCode": data.get("modelCode", ""),
            "sessionNid": data.get("sessionNid", ""),
            "stream": data.get("stream", False),
        }
        return json.dumps(json_data, separators=(",", ":")).replace('"true"', "true").replace('"false"', "false")
