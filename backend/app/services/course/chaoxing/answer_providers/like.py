import json
import random

import requests
from loguru import logger

from ..answer_base import Tiku


class TikuLike(Tiku):
    # LIKE知识库实现 参考 https://www.datam.site/
    def __init__(self) -> None:
        super().__init__()
        self.name = "LIKE知识库"
        self.ver = "2.0.0"  # 对应官网API版本
        self.query_api = "https://app.datam.site/api/v1/query"
        self.models_api = "https://app.datam.site/api/v1/query/models"
        self.balance_api = "https://app.datam.site/api/v1/balance"
        self.homepage = "https://www.datam.site"
        self._model = None
        self._timeout = 300
        self._retry = True
        self._retry_times = 3
        self._tokens = []
        self._balance = {}
        self._search = False
        self._vision = True
        self._count = 0
        self._headers = {"Content-Type": "application/json"}

    def _query(self, q_info: dict = None):
        if not q_info:
            logger.error("当前无题目信息，请检查")
            return ""

        q_info_map = {
            "single": "【单选题】",
            "multiple": "【多选题】",
            "completion": "【填空题】",
            "judgement": "【判断题】",
        }
        q_info_prefix = q_info_map.get(q_info["type"], "【其他类型题目】")
        options = ", ".join(q_info["options"]) if isinstance(q_info["options"], list) else q_info["options"]
        question = f"{q_info_prefix}{q_info['title']}\n"

        if q_info["type"] in ["single", "multiple"]:
            question += f"选项为: {options}\n"

        # 随机选择一个token进行查询
        token = random.choice(self._tokens)

        # 检查该token是否有余额
        if self._balance.get(token, 0) <= 0:
            logger.error(f"{self.name}当前Token查询次数不足: ...{token[-5:]}")
            # 尝试选择其他有余额的token
            available_tokens = [t for t in self._tokens if self._balance.get(t, 0) > 0]
            if available_tokens:
                token = random.choice(available_tokens)
            else:
                logger.error(f"{self.name}所有Token查询次数都不足")
                return None

        ans = None
        try_times = 0

        # 尝试查询，直到成功或达到重试次数
        while not ans and self._retry and try_times < self._retry_times:
            ans = self._query_single(token, question)
            try_times += 1
            if ans:  # 如果查询成功，减少余额
                self._balance[token] -= 1
                logger.info(f"使用Token ...{token[-5:]} 查询成功，剩余次数: {self._balance[token]}")
                break
            if try_times < self._retry_times:
                logger.warning(f"使用Token ...{token[-5:]} 查询失败，进行第 {try_times + 1} 次重试...")

        # 10次查询后更新余额
        self._count = (self._count + 1) % 10
        if self._count == 0:
            self.update_times()

        return ans

    def _query_single(self, token: str = "", query: str = "") -> str:
        """
        查询单个问题的答案

        Args:
            token: API访问令牌
            query: 查询的问题内容

        Returns:
            查询到的答案，如果失败则返回None
        """
        # 验证输入参数
        if not token:
            logger.error(f"{self.name}查询失败: 未提供有效的token")
            return None

        if not query:
            logger.error(f"{self.name}查询失败: 查询内容为空")
            return None

        # 设置请求头
        temp_headers = self._headers.copy()
        temp_headers["Authorization"] = f"Bearer {token}"

        # 准备请求数据
        request_data = {
            "query": query,
            "model": self._model if self._model else "",
            "search": self._search,
            "vision": self._vision,
        }

        # 发送API请求
        try:
            res = requests.post(
                self.query_api,
                json=request_data,
                headers=temp_headers,
                timeout=self._timeout,
            )
        except requests.exceptions.Timeout:
            logger.error(f"{self.name}查询超时: 请求超过300秒")
            return None
        except requests.exceptions.ConnectionError:
            logger.error(f"{self.name}网络连接错误: 无法连接到API服务器")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"{self.name}查询异常: \n{e}")
            return None
        except Exception as e:
            logger.error(f"{self.name}查询发生未知错误: \n{e}")
            return None

        # 处理HTTP响应
        if res.status_code == 200:
            return self._parse_response(res)
        if res.status_code == 401:
            logger.error(f"{self.name}认证失败: 请检查Token是否正确或已过期")
        elif res.status_code == 429:
            logger.error(f"{self.name}请求过于频繁: 已达到API速率限制")
        elif res.status_code == 500:
            logger.error(f"{self.name}服务器内部错误: API服务暂时不可用")
        elif res.status_code == 400:
            logger.error(f"{self.name}请求参数错误: 请检查查询内容格式")
        elif res.status_code == 403:
            logger.error(f"{self.name}访问被拒绝: 可能是Token权限不足")
        else:
            logger.error(f"{self.name}查询失败: 状态码 {res.status_code}, 响应内容: \n{res.text}")

        return None

    def _parse_response(self, response):
        """
        解析API响应

        Args:
            response: HTTP响应对象

        Returns:
            解析后的答案，如果解析失败则返回None
        """
        try:
            res_json = response.json()
        except json.JSONDecodeError:
            logger.error(f"{self.name}响应解析失败: 响应不是有效的JSON格式")
            return None
        except Exception as e:
            logger.error(f"{self.name}响应解析异常: {e}")
            return None

        # 记录响应消息
        msg = res_json.get("message", "")
        if msg:
            logger.info(f"{self.name}响应消息: {msg}")

        # 检查API返回的code字段，判断请求是否成功
        code = res_json.get("code", 1)
        if code != 1:
            error_msg = res_json.get("message", "未知错误")
            logger.error(f"{self.name}API返回错误: {error_msg}")
            return None

        results = res_json.get("results", {})
        if not results or not isinstance(results, dict):
            logger.error(f"{self.name}查询结果格式错误: API返回结果中results字段格式不正确")
            return None

        output = results.get("output", None)
        if output is None or not isinstance(output, dict):
            logger.error(f"{self.name}查询结果中output字段格式错误或不存在")
            return None

        q_type = output.get("questionType", None)
        if q_type is None:
            logger.error(f"{self.name}查询结果中questionType字段不存在")
            return None

        answer = output.get("answer", None)
        if answer is None:
            logger.error(f"{self.name}查询结果中answer字段不存在")
            return None

        # 根据题目类型提取答案
        return self._extract_answer_by_type(q_type, answer)

    def _extract_answer_by_type(self, q_type: str, answer: dict) -> str:
        """
        根据题目类型提取答案

        Args:
            q_type: 题目类型
            answer: 答案字典

        Returns:
            提取的答案文本
        """
        if not isinstance(answer, dict):
            logger.error(f"{self.name}答案格式错误: 不是有效的字典格式")
            return None

        if q_type == "CHOICE":
            selected_options = answer.get("selectedOptions")
            if selected_options is not None:
                if isinstance(selected_options, list) and selected_options:
                    # 过滤掉None和空字符串
                    valid_options = [opt for opt in selected_options if opt is not None and str(opt).strip()]
                    if valid_options:
                        return "\n".join(str(opt) for opt in valid_options)
                    logger.error(f"{self.name}CHOICE类型题目没有有效的选项内容")
                else:
                    logger.error(f"{self.name}CHOICE类型题目没有有效的选项内容")
            else:
                logger.error(f"{self.name}CHOICE类型题目缺少selectedOptions字段")
        elif q_type == "FILL_IN_BLANK":
            blanks = answer.get("blanks")
            if blanks is not None:
                if isinstance(blanks, list) and blanks:
                    # 过滤掉None和空字符串
                    valid_blanks = [blank for blank in blanks if blank is not None and str(blank).strip()]
                    if valid_blanks:
                        return "\n".join(str(blank) for blank in valid_blanks)
                    logger.error(f"{self.name}FILL_IN_BLANK类型题目没有有效的填空内容")
                else:
                    logger.error(f"{self.name}FILL_IN_BLANK类型题目没有有效的填空内容")
            else:
                logger.error(f"{self.name}FILL_IN_BLANK类型题目缺少blanks字段")
        elif q_type == "JUDGMENT":
            is_correct = answer.get("isCorrect")
            if is_correct is not None:
                return "正确" if is_correct else "错误"
            logger.error(f"{self.name}JUDGMENT类型题目缺少isCorrect字段")
        else:
            otherText = answer.get("otherText")
            if otherText is not None:
                return str(otherText)
            logger.error(f"{self.name}未知题目类型{q_type}且缺少otherText字段")

        return None

    def get_api_balance(self, token: str = ""):
        if not token:
            logger.error(f"{self.name}获取余额失败: 未提供有效的token")
            return 0

        temp_headers = self._headers.copy()
        temp_headers["Authorization"] = f"Bearer {token}"
        try:
            res = requests.post(
                self.balance_api,
                headers=temp_headers,
                timeout=self._timeout,
            )
            if res.status_code == 200:
                res_json = res.json()
                code = res_json.get("code", 0)
                if code == 1:
                    return int(res_json.get("balance", 0))
                error_msg = res_json.get("message", "未知错误")
                logger.error(f"{self.name}获取余额失败: {error_msg}")
                return 0
            logger.error(f"{self.name}请求余额接口失败，状态码: {res.status_code}")
            return 0
        except requests.exceptions.Timeout:
            logger.error(f"{self.name}获取余额超时: 请求超过30秒")
            return 0
        except requests.exceptions.ConnectionError:
            logger.error(f"{self.name}网络连接错误: 无法连接到余额查询API服务器")
            return 0
        except ValueError:  # json解析错误或int转换错误
            logger.error(f"{self.name}余额响应解析失败: 响应格式不正确")
            return 0
        except Exception as e:
            logger.error(f"{self.name}Token余额查询过程中出现错误: {e}")
            return 0

    def update_times(self) -> None:
        if not self._tokens:
            logger.warning(f"{self.name}未加载任何Token, 无法更新余额")
            return
        for token in self._tokens:
            balance = self.get_api_balance(token)
            self._balance[token] = balance
            logger.info(
                f"当前LIKE知识库Token: ...{token[-5:]} 的剩余查询次数为: {balance} (仅供参考, 实际次数以查询结果为准)"
            )

    def load_tokens(self) -> None:
        tokens_str = self._conf.get("tokens")
        if not tokens_str:
            logger.error(f"{self.name}配置中未找到tokens")
            self._tokens = []
            return
        if "," in tokens_str:
            tokens = [token.strip() for token in tokens_str.split(",") if token.strip()]
        else:
            tokens = [tokens_str.strip()] if tokens_str.strip() else []
        self._tokens = tokens
        if not self._tokens:
            logger.warning(f"{self.name}未加载任何有效的Token")

    def load_config(self) -> None:
        # 从配置中获取参数，提供默认值
        self._search = self._conf.get("likeapi_search", False)
        self._model = self._conf.get("likeapi_model", None)
        self._vision = self._conf.get("likeapi_vision", True)
        self._retry = self._conf.get("likeapi_retry", True)
        self._retry_times = self._conf.get("likeapi_retry_times", 3)

    def _init_tiku(self) -> None:
        self.load_config()
        self.load_tokens()
        if self._tokens:
            self.update_times()
        else:
            logger.error(f"{self.name}初始化失败: 未加载任何有效的Token")
            self.DISABLE = True
