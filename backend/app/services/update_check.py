"""Check GitHub Releases for a newer server version.

The server edition cannot update itself (the app container has no Docker
socket, on purpose). Instead it polls the public releases API a few times a
day and lets administrators see the new version, its notes and the exact
command that upgrades the installation.

Everything here fails quietly: an air-gapped or GitHub-blocked server simply
never shows an update notice.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-.]?([0-9A-Za-z.-]+))?$")
_MAX_NOTES_CHARS = 2000


def parse_version(value: str | None) -> tuple[int, int, int, int, str] | None:
    """Parse ``1.4.7`` / ``v1.4.7`` / ``1.5.0-rc.1`` into a sortable key.

    A pre-release sorts below the matching release (``1.5.0-rc.1 < 1.5.0``).
    """
    match = _VERSION_RE.match((value or "").strip())
    if not match:
        return None
    major, minor, patch, pre = match.groups()
    return (int(major), int(minor), int(patch), 0 if pre else 1, pre or "")


def is_newer(candidate: str | None, current: str | None) -> bool:
    new, cur = parse_version(candidate), parse_version(current)
    return bool(new and cur and new > cur)


def update_commands(tag: str) -> dict[str, str]:
    version = tag.lstrip("v")
    return {
        "bash": f"bash scripts/deploy_server.sh --tag {version} -y",
        "powershell": f"pwsh scripts/deploy_server.ps1 -Tag {version} -Yes",
    }


@dataclass
class _Release:
    tag: str
    html_url: str
    notes: str
    published_at: str | None
    checked_at: float = field(default_factory=time.time)


class UpdateChecker:
    def __init__(
        self,
        current_version: str,
        url: str,
        ttl_seconds: float,
        timeout: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.current_version = current_version
        self.url = url
        self.ttl_seconds = ttl_seconds
        self.timeout = timeout
        self._transport = transport
        self._release: _Release | None = None
        self._last_attempt: float | None = None
        self._lock = asyncio.Lock()

    def _is_stale(self) -> bool:
        return self._last_attempt is None or time.monotonic() - self._last_attempt >= self.ttl_seconds

    async def refresh(self) -> None:
        self._last_attempt = time.monotonic()
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"university-helper/{self.current_version}",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
                response = await client.get(self.url, headers=headers, follow_redirects=True)
            if response.status_code != 200:
                logger.info("Update check returned HTTP %s", response.status_code)
                return
            data: Any = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("Update check failed: %s", exc)
            return
        if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
            return
        tag = str(data.get("tag_name") or "")
        if parse_version(tag) is None:
            return
        self._release = _Release(
            tag=tag,
            html_url=str(data.get("html_url") or ""),
            notes=str(data.get("body") or "")[:_MAX_NOTES_CHARS],
            published_at=data.get("published_at"),
        )

    async def get_status(self) -> dict[str, Any]:
        if self._is_stale():
            async with self._lock:
                if self._is_stale():
                    await self.refresh()
        release = self._release
        status: dict[str, Any] = {
            "enabled": True,
            "current": self.current_version,
            "latest": None,
            "has_update": False,
            "html_url": None,
            "notes": "",
            "published_at": None,
            "checked_at": None,
            "commands": None,
        }
        if release is None:
            return status
        latest = release.tag.lstrip("v")
        status.update(
            latest=latest,
            has_update=is_newer(latest, self.current_version),
            html_url=release.html_url,
            notes=release.notes,
            published_at=release.published_at,
            checked_at=datetime.fromtimestamp(release.checked_at, tz=UTC).isoformat(),
            commands=update_commands(latest),
        )
        return status
