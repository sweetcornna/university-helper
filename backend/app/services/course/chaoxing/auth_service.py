import requests
from loguru import logger
from requests import RequestException

from .cipher import AESCipher
from .config import GlobalConst as gc
from .cookies import delete_session, load_session, save_cookies, save_session, touch_session

COURSE_LIST_PROBE_URL = "https://mooc2-ans.chaoxing.com/mooc2-ans/visit/courselistdata"


def validate_session_cookies(cookies: dict | None) -> bool:
    """Return True when ``cookies`` still authenticate against Chaoxing.

    Single probe shared by the task-path cookie login and the SPA session
    rehydration so both trust exactly the same signal.
    """
    if not cookies or not cookies.get("_uid"):
        return False

    test_session = requests.Session()
    test_session.headers.update(gc.HEADERS)
    test_session.cookies.update(cookies)

    try:
        resp = test_session.post(
            COURSE_LIST_PROBE_URL,
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


class ChaoxingAuthService:
    def __init__(self, account=None, cipher=None, session_manager=None, user_id=None):
        self.account = account
        self.cipher = cipher or AESCipher()
        self.session_manager = session_manager
        # Platform user_id — used to namespace the persisted cookie file so
        # multiple platform users don't overwrite each other's login session.
        self.user_id = user_id

    def login(self, login_with_cookies=False):
        if login_with_cookies:
            logger.info("Logging in with cookies")
            username = str(getattr(self.account, "username", "") or "").strip()
            if not username:
                # A stored jar authenticates with no password and no MFA. With no
                # username to bind it against we cannot prove it belongs to the
                # caller, so an unbound jar is never adopted — fail closed.
                logger.warning("未提供超星账号，拒绝复用已保存的会话")
                return {"status": False, "msg": "cookies 已失效，请更新 cookies 或提供账号密码"}

            stored = load_session(self.user_id, expected_username=username)
            if not stored:
                logger.info("没有可复用的超星会话（不存在/已过期/账号不匹配），改用账号密码登录")
                return self._password_login_fallback()

            self.session_manager.update_cookies(stored["cookies"])
            logger.debug("Cookie session loaded (cookies redacted)")
            if not self._validate_cookie_session():
                logger.warning("Cookie 登录校验失败，尝试使用账号密码重新登录")
                delete_session(self.user_id)
                return self._password_login_fallback()
            # Actively-used session rolls its 7-day window forward.
            touch_session(self.user_id)
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
            # Drop whatever was in the jar first: after a rejected cookie login
            # the previous account's cookies are still there, and merging the new
            # ones over them can leave us authenticated as the wrong account.
            self.session_manager.get_session().cookies.clear()
            self.session_manager.set_cookies(_session.cookies.get_dict())
            # Persist the fresh cookies so subsequent tasks can skip the
            # password login (best-effort: a write failure is non-fatal).
            save_cookies(_session, self.user_id)
            save_session(self.user_id, self.account.username, _session.cookies.get_dict())
            logger.info("登录成功...")
            return {"status": True, "msg": "登录成功"}
        # 超星失败响应不保证包含 'msg2'（如验证码/风控/限流的不同结构），
        # 直接索引会抛 KeyError 并被包装成模糊的 'Unexpected task failure'。
        msg = resp_data.get("msg2") or resp_data.get("msg") or resp_data.get("msg1") or "登录失败"
        return {"status": False, "msg": str(msg)}

    def _password_login_fallback(self):
        if self.account and self.account.username and self.account.password:
            return self.login(login_with_cookies=False)
        return {"status": False, "msg": "cookies 已失效，请更新 cookies 或提供账号密码"}

    def _validate_cookie_session(self) -> bool:
        return validate_session_cookies(self.session_manager.get_session().cookies.get_dict())

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
