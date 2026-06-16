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
        res = requests.post(
            self.api,
            json={
                "question": q_info["title"],
                "options": [sub(r"^[A-Za-z]\.?、?\s?", "", option) for option in options.split("\n")],
                "type": type,
            },
            timeout=30,
        )
        if res.status_code == 200:
            res_json = res.json()
            # if bool(res_json['plat']):
            # plat无论搜没搜到答案都返回0
            # 这个参数是tikuadapter用来设定自定义的平台类型
            if not len(res_json["answer"]["bestAnswer"]):
                logger.error("查询失败, 返回：" + res.text)
                return None
            sep = "\n"
            return sep.join(res_json["answer"]["bestAnswer"]).strip()
        # else:
        #   logger.error(f'{self.name}查询失败:\n{res.text}')
        return None

    def _init_tiku(self):
        # self.load_token()
        self.api = self._conf["url"]
