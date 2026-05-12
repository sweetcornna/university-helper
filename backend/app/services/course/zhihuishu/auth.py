"""智慧树二维码登录模块"""
import time
import json
from base64 import b64decode
from typing import Callable, Optional
from urllib.parse import unquote
import requests
from requests.adapters import HTTPAdapter, Retry


class ZhihuishuAuth:
    """智慧树认证服务"""

    def __init__(self, proxies: Optional[dict] = None):
        self.proxies = proxies or {}
        self.session = requests.Session()
        retry = Retry(total=5, backoff_factor=0.1, status_forcelist=[500, 502, 503, 504])
        self.session.mount('http://', HTTPAdapter(max_retries=retry))
        self.session.mount('https://', HTTPAdapter(max_retries=retry))
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

    def qr_login(self, qr_callback: Callable[[bytes], None], _retries: int = 3) -> dict:
        """
        二维码登录

        Args:
            qr_callback: 二维码回调函数，接收二维码图片字节数据

        Returns:
            登录后的 cookies 字典
        """
        if _retries <= 0:
            raise TimeoutError("QR login retries exhausted")

        login_page = "https://passport.zhihuishu.com/login?service=https://onlineservice-api.zhihuishu.com/login/gologin"
        qr_page = "https://passport.zhihuishu.com/qrCodeLogin/getLoginQrImg"
        query_page = "https://passport.zhihuishu.com/qrCodeLogin/getLoginQrInfo"

        try:
            r = self.session.get(qr_page, timeout=10).json()
            qr_token = r["qrToken"]
            img = b64decode(r["img"])
            qr_callback(img)

            scanned = False
            while True:
                time.sleep(0.5)
                msg = self.session.get(query_page, params={"qrToken": qr_token}, timeout=10).json()

                status = msg.get("status")
                if status == -1:
                    continue  # 未扫描
                elif status == 0:
                    if not scanned:
                        scanned = True
                elif status == 1:
                    # 登录成功
                    self.session.get(login_page, params={"pwd": msg["oncePassword"]},
                                   proxies=self.proxies, timeout=10)
                    self.cookies = self.session.cookies
                    if not self.cookies:
                        raise Exception("No cookies found")
                    return self.cookies
                elif status == 2:
                    raise TimeoutError("QR code expired")
                elif status == 3:
                    raise Exception("Login canceled")
                else:
                    raise Exception(f"Unknown status: {status}")

        except TimeoutError:
            return self.qr_login(qr_callback, _retries=_retries - 1)
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
        login_page = "https://passport.zhihuishu.com/login?service=https://onlineservice-api.zhihuishu.com/login/gologin"
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
            elif user_info.get("status") == -2:
                raise ValueError("Username or password invalid")
            else:
                raise Exception(f"Login failed: {user_info.get('msg')}")

        except Exception as e:
            raise Exception(f"Password login failed: {e}") from e
