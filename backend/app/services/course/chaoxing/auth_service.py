import requests
from loguru import logger
from requests import RequestException

from .cipher import AESCipher
from .config import GlobalConst as gc


class ChaoxingAuthService:
    def __init__(self, account=None, cipher=None, session_manager=None):
        self.account = account
        self.cipher = cipher or AESCipher()
        self.session_manager = session_manager

    def login(self, login_with_cookies=False):
        if login_with_cookies:
            logger.info("Logging in with cookies")
            self.session_manager.update_cookies()
            logger.debug("Cookie session loaded (cookies redacted)")
            if not self._validate_cookie_session():
                logger.warning("Cookie 登录校验失败，尝试使用账号密码重新登录")
                if self.account and self.account.username and self.account.password:
                    return self.login(login_with_cookies=False)
                return {"status": False, "msg": "cookies 已失效，请更新 cookies 或提供账号密码"}
            logger.info("登录成功...")
            return {"status": True, "msg": "登录成功"}

        _session = requests.Session()
        _url = "https://passport2.chaoxing.com/fanyalogin"
        _data = {
            "fid": "-1",
            "uname": self.cipher.encrypt(self.account.username),
            "password": self.cipher.encrypt(self.account.password),
            "refer": "https%3A%2F%2Fi.chaoxing.com",
            "t": True,
            "forbidotherlogin": 0,
            "validate": "",
            "doubleFactorLogin": 0,
            "independentId": 0,
        }
        logger.trace("正在尝试登录...")
        resp = _session.post(_url, headers=gc.HEADERS, data=_data, timeout=10)
        try:
            resp_data = resp.json()
        except ValueError:
            return {"status": False, "msg": "upstream returned non-JSON"}
        if not isinstance(resp_data, dict):
            return {"status": False, "msg": "upstream returned unexpected response"}
        if resp and resp_data.get("status") is True:
            self.session_manager.set_cookies(_session.cookies.get_dict())
            logger.info("登录成功...")
            return {"status": True, "msg": "登录成功"}
        # 超星失败响应不保证包含 'msg2'（如验证码/风控/限流的不同结构），
        # 直接索引会抛 KeyError 并被包装成模糊的 'Unexpected task failure'。
        msg = resp_data.get("msg2") or resp_data.get("msg") or resp_data.get("msg1") or "登录失败"
        return {"status": False, "msg": str(msg)}

    def _validate_cookie_session(self) -> bool:
        session = self.session_manager.get_session()
        if not session.cookies.get("_uid"):
            return False

        test_session = requests.Session()
        test_session.headers.update(gc.HEADERS)
        test_session.cookies.update(session.cookies.get_dict())

        try:
            resp = test_session.post(
                "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata",
                data={"courseType": 1, "courseFolderId": 0, "query": "", "superstarClass": 0},
                timeout=8,
            )
        except RequestException as exc:
            logger.debug("Cookie validation request failed: {}", exc)
            return False

        if resp.status_code != 200:
            return False

        if "passport2.chaoxing.com" in resp.text or "login" in resp.text.lower():
            return False

        return True

    def get_fid(self):
        _session = self.session_manager.get_session()
        return _session.cookies.get("fid")

    def get_uid(self):
        s = self.session_manager.get_session()
        if "_uid" in s.cookies:
            return s.cookies["_uid"]
        if "UID" in s.cookies:
            return s.cookies["UID"]
        raise ValueError("Cannot get uid !")
