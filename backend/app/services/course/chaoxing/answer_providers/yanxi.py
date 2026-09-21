import requests
from loguru import logger

from ..answer_base import Tiku


class TikuYanxi(Tiku):
    # 言溪题库实现
    def __init__(self) -> None:
        super().__init__()
        self.name = "言溪题库"
        self.api = "https://tk.enncy.cn/query"
        self._token = None
        self._token_index = 0  # token队列计数器
        self._times = 100  # 查询次数剩余, 初始化为100, 查询后校对修正

    def _query(self, q_info: dict):
        try:
            res = requests.get(
                self.api,
                params={
                    "question": q_info["title"],
                    "token": self._token,
                    # 'type':q_info['type'], #修复478题目类型与答案类型不符（不想写后处理了）
                    # 没用，就算有type和options，言溪题库还是可能返回类型不符，问了客服，type仅用于收集
                },
                timeout=30,
            )
        except requests.exceptions.Timeout as exc:
            logger.error(f"{self.name}查询超时: {exc.__class__.__name__}")
            return None
        except requests.exceptions.ConnectionError as exc:
            logger.error(f"{self.name}网络连接失败: {exc.__class__.__name__}")
            return None
        except requests.exceptions.RequestException as exc:
            logger.error(f"{self.name}请求失败: {exc.__class__.__name__}")
            return None

        if res.status_code != 200:
            logger.error(f"{self.name}查询失败: HTTP 状态码 {res.status_code}")
            return None

        try:
            res_json = res.json()
        except ValueError as exc:
            logger.error(f"{self.name}查询失败: 响应不是有效JSON ({exc.__class__.__name__})")
            return None

        if not isinstance(res_json, dict) or "code" not in res_json or not isinstance(res_json.get("data"), dict):
            logger.error(f"{self.name}查询失败: 响应结构无效")
            return None

        response_data = res_json["data"]
        response_answer = response_data.get("answer")
        if not isinstance(response_answer, str):
            logger.error(f"{self.name}查询失败: 响应结构无效")
            return None

        if not res_json["code"]:
            # 如果是因为TOKEN次数到期, 则更换token
            if self._times == 0 or "次数不足" in response_answer:
                logger.info("TOKEN查询次数不足, 将会更换并重新搜题")
                self._token_index += 1
                self.load_token()
                # 重新查询
                return self._query(q_info)
            logger.error(f"{self.name}查询失败: provider 返回未命中")
            return None
        self._times = response_data.get("times", self._times)
        return response_answer.strip()

    def load_token(self):
        token_list = self._conf["tokens"].split(",")
        if self._token_index == len(token_list):
            # TOKEN 用完
            logger.error("TOKEN用完, 请自行更换再重启脚本")
            raise PermissionError(f"{self.name} TOKEN 已用完, 请更换")
        self._token = token_list[self._token_index]

    def _init_tiku(self):
        self.load_token()
