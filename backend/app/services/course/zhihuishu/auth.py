"""智慧树二维码登录模块"""

import json
import threading
from base64 import b64decode
from collections.abc import Callable
from urllib.parse import unquote

import requests
from requests.adapters import HTTPAdapter, Retry


class ZhihuishuAuth:
    """智慧树认证服务"""

    def __init__(self, proxies: dict | None = None):
        self.proxies = proxies or {}
        self.session = requests.Session()
        retry = Retry(total=5, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.uuid = None
        self._cookies = None

    @property
    def cookies(self):
        return self._cookies

    @cookies.setter
    def cookies(self, cookies):
        self._cookies = self._normalize_cookies(cookies)
        if self._cookies:
            try:
                caslogc = self._cookies["CASLOGC"] if "CASLOGC" in self._cookies else "{}"
                self.uuid = json.loads(unquote(caslogc))["uuid"]
                self._cookies[f"exitRecod_{self.uuid}"] = "2"
            except (KeyError, json.JSONDecodeError, TypeError) as exc:
                raise ValueError("Cookies invalid") from exc

    @staticmethod
    def _normalize_cookies(cookies) -> dict:
        """Normalize cookies to a plain dict and avoid conflict-prone get behavior."""
        if not cookies:
            return {}

        normalized = {}
        if isinstance(cookies, dict):
            for name, value in cookies.items():
                if value is None:
                    continue
                normalized[str(name)] = str(value)
            return normalized

        for cookie in cookies:
            normalized[cookie.name] = cookie.value
        return normalized

    def qr_login(
        self,
        qr_callback: Callable[[bytes], None],
        _retries: int = 3,
        cancel_event: threading.Event | None = None,
    ) -> dict:
        """Log in with a refreshable QR code and cooperative cancellation."""
        cancel_event = cancel_event or threading.Event()
        login_page = (
            "https://passport.zhihuishu.com/login?service=https://onlineservice-api.zhihuishu.com/login/gologin"
        )
        qr_page = "https://passport.zhihuishu.com/qrCodeLogin/getLoginQrImg"
        query_page = "https://passport.zhihuishu.com/qrCodeLogin/getLoginQrInfo"

        try:
            for attempt in range(_retries):
                if cancel_event.is_set():
                    raise InterruptedError("QR login cancelled")

                r = self.session.get(qr_page, timeout=10).json()
                qr_token = r["qrToken"]
                qr_callback(b64decode(r["img"]))

                while not cancel_event.wait(0.5):
                    msg = self.session.get(query_page, params={"qrToken": qr_token}, timeout=10).json()
                    status = msg.get("status")
                    if status in {-1, 0}:
                        continue
                    if status == 1:
                        if cancel_event.is_set():
                            raise InterruptedError("QR login cancelled")
                        self.session.get(
                            login_page,
                            params={"pwd": msg["oncePassword"]},
                            proxies=self.proxies,
                            timeout=10,
                        )
                        self.cookies = self.session.cookies
                        if not self.cookies:
                            raise Exception("No cookies found")
                        return self.cookies
                    if status == 2:
                        break
                    if status == 3:
                        raise Exception("Login canceled")
                    raise Exception(f"Unknown status: {status}")
                else:
                    raise InterruptedError("QR login cancelled")

                if attempt == _retries - 1:
                    raise TimeoutError("QR login retries exhausted")
        except InterruptedError:
            raise
        except Exception as e:
            raise Exception(f"QR login failed: {e}") from e

    def password_login(self, username: str, password: str) -> dict:
        """
        账号密码登录

        Args:
            username: 用户名
            password: 密码

        Returns:
            登录后的 cookies 字典
        """
        login_page = (
            "https://passport.zhihuishu.com/login?service=https://onlineservice-api.zhihuishu.com/login/gologin"
        )
        valid_url = "https://passport.zhihuishu.com/user/validateAccountAndPassword"

        try:
            self.session.get(login_page, proxies=self.proxies, timeout=10)
            form = {"account": username, "password": password}
            user_info = self.session.post(valid_url, data=form, timeout=10).json()

            if user_info.get("status") == 1:
                params = {"account": username, "pwd": user_info["pwd"], "validate": 0}
                self.session.get(login_page, params=params, proxies=self.proxies, timeout=10)
                self.cookies = self.session.cookies
                return self.cookies
            if user_info.get("status") == -2:
                raise ValueError("Username or password invalid")
            raise Exception(f"Login failed: {user_info.get('msg')}")

        except Exception as e:
            raise Exception(f"Password login failed: {e}") from e
