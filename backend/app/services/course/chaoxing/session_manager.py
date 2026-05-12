# -*- coding: utf-8 -*-
import functools
import threading
import time
from typing import Self
import requests
from requests.adapters import HTTPAdapter
from .config import GlobalConst as gc
from .cookies import use_cookies


class SessionManager:
    _instance = None
    _lock = threading.Lock()
    _last_cookie_update = 0
    _cookie_update_interval = 5.0

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._session = requests.Session()
        adapter = HTTPAdapter(max_retries=3, pool_connections=50, pool_maxsize=100)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session.request = functools.partial(self._session.request, timeout=5)
        self._session.headers.clear()
        self._session.headers.update(gc.HEADERS)
        self._session.cookies.update(use_cookies())

    @classmethod
    def get_instance(cls) -> Self:
        return cls()

    @classmethod
    def get_session(cls) -> requests.Session:
        instance = cls.get_instance()
        return instance._session

    @classmethod
    def update_cookies(cls):
        now = time.time()
        if now - cls._last_cookie_update < cls._cookie_update_interval:
            return
        cls._last_cookie_update = now
        cls.get_instance()._session.cookies.update(use_cookies())
