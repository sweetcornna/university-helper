from re import sub

import requests
from loguru import logger

from ..answer_base import Tiku


class TikuAdapter(Tiku):
    # TikuAdapter题库实现 https://github.com/DokiDoki1103/tikuAdapter
    def __init__(self) -> None:
        super().__init__()
        self.name = "TikuAdapter题库"
        self.api = ""

    def _query(self, q_info: dict):
        # 判断题目类型
        if q_info["type"] == "single":
            type = 0
        elif q_info["type"] == "multiple":
            type = 1
        elif q_info["type"] == "completion":
            type = 2
        elif q_info["type"] == "judgement":
            type = 3
        else:
            type = 4

        options = q_info["options"]
        try:
            res = requests.post(
                self.api,
                json={
                    "question": q_info["title"],
                    "options": [sub(r"^[A-Za-z]\.?、?\s?", "", option) for option in options.split("\n")],
                    "type": type,
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

        if not isinstance(res_json, dict) or not isinstance(res_json.get("answer"), dict):
            logger.error(f"{self.name}查询失败: 响应结构无效")
            return None

        best_answers = res_json["answer"].get("bestAnswer")
        if not isinstance(best_answers, list) or not all(isinstance(answer, str) for answer in best_answers):
            logger.error(f"{self.name}查询失败: 响应结构无效")
            return None

        # if bool(res_json['plat']):
        # plat无论搜没搜到答案都返回0
        # 这个参数是tikuadapter用来设定自定义的平台类型
        if not best_answers:
            logger.error(f"{self.name}查询失败: 响应未返回答案")
            return None
        sep = "\n"
        return sep.join(best_answers).strip()

    def _init_tiku(self):
        # self.load_token()
        self.api = self._conf["url"]
