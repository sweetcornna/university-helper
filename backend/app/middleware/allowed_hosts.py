"""Host header validation with an error people can act on.

Same matching rules as Starlette's TrustedHostMiddleware (exact host or a
leading ``*.`` wildcard), but a rejected request gets a JSON body that says
which setting to change. The plain-text "Invalid host header" used to show up
verbatim in the register form when a site was opened through a LAN IP or a
second domain.
"""

from __future__ import annotations

import json
import logging

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

_MAX_LOGGED_HOSTS = 100


class AllowedHostsMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: list[str]) -> None:
        self.app = app
        self.allowed_hosts = list(allowed_hosts)
        self.allow_any = "*" in self.allowed_hosts
        self._logged: set[str] = set()

    def is_allowed(self, host: str) -> bool:
        if self.allow_any:
            return True
        for pattern in self.allowed_hosts:
            if host == pattern or (pattern.startswith("*") and host.endswith(pattern[1:])):
                return True
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket") or self.allow_any:
            await self.app(scope, receive, send)
            return

        host = Headers(scope=scope).get("host", "").split(":")[0]
        if self.is_allowed(host):
            await self.app(scope, receive, send)
            return

        if host not in self._logged and len(self._logged) < _MAX_LOGGED_HOSTS:
            self._logged.add(host)
            logger.warning("Rejected request for host %r; add it to ALLOWED_HOSTS if it is legitimate", host)

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return

        body = json.dumps(
            {
                "code": "InvalidHost",
                "message": (
                    f"Invalid host header: {host or '(empty)'}。这个访问地址没有被允许，"
                    "请在服务器 .env 的 ALLOWED_HOSTS 里加上它，然后重启 app 容器"
                ),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 400,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
