import functools

import requests
from requests.adapters import HTTPAdapter

from .config import GlobalConst as gc


class SessionManager:
    """Per-instance HTTP session holder.

    Each Chaoxing client owns its own SessionManager (and therefore its own
    ``requests.Session`` / cookie jar). This is required for multi-tenant
    isolation: when several users share a single process (uvicorn
    ``--workers 1``), a process-wide shared session would let one user's login
    cookies overwrite another user's in-flight session, leaking identity across
    tenants.
    """

    def __init__(self, cookies: dict | None = None):
        self._session = requests.Session()
        adapter = HTTPAdapter(max_retries=3, pool_connections=50, pool_maxsize=100)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._session.request = functools.partial(self._session.request, timeout=5)
        self._session.headers.clear()
        self._session.headers.update(gc.HEADERS)
        if cookies:
            self._session.cookies.update(cookies)

    def get_session(self) -> requests.Session:
        return self._session

    def set_cookies(self, cookies: dict):
        self._session.cookies.update(cookies)

    def update_cookies(self, cookies: dict | None = None):
        if cookies:
            self._session.cookies.update(cookies)
