"""学习通 (Chaoxing) QR-code login protocol.

Drives the same flow the 学习通 web login page uses when you pick 「扫码登录」:

1. ``GET  /mlogin?newversion=true`` — HTML carrying the ``#uuid`` / ``#enc``
   hidden fields, and setting the cookies the rest of the flow needs.
2. ``GET  /createqr?uuid=…&fid=-1`` — the QR image itself (PNG bytes).
3. ``POST /getauthstatus`` — polled while the user scans and confirms on their
   phone. Confirmation is what authenticates the session's cookie jar.
4. ``GET  sso.chaoxing.com/apis/login/userLogin4Uname.do`` — the profile, which
   is where the uid / account name come from once the jar is authenticated.

Every function takes the caller's ``requests.Session`` and keeps the jar there,
so this module deliberately does not import ``signin.py`` (that would be a cycle)
and holds no state of its own.

Nothing here logs a uid, account name, or cookie value.
"""

from __future__ import annotations

import re
from typing import Any

import requests
from bs4 import BeautifulSoup
from loguru import logger

PASSPORT_ORIGIN = "https://passport2.chaoxing.com"
LOGIN_PAGE_URL = f"{PASSPORT_ORIGIN}/mlogin?newversion=true"
CREATE_QR_URL = f"{PASSPORT_ORIGIN}/createqr"
AUTH_STATUS_URL = f"{PASSPORT_ORIGIN}/getauthstatus"
PROFILE_URL = "https://sso.chaoxing.com/apis/login/userLogin4Uname.do"

QR_STATUS_PENDING = "pending"
QR_STATUS_SCANNED = "scanned"
QR_STATUS_CONFIRMED = "confirmed"
QR_STATUS_EXPIRED = "expired"

# getauthstatus `type` values. Every other value — including the repeat codes
# seen while the user is still deciding — means "keep waiting".
_TYPE_SCANNED = 4
_TYPE_EXPIRED = 6

# uuid / enc are 32 lowercase hex chars. Anything else means the login page
# changed shape, and a QR built from it would be unusable — fail loudly rather
# than hand the browser a broken image.
_QR_FIELD_RE = re.compile(r"^[a-f0-9]{32}$")

# getauthstatus is XHR-only upstream: without these headers it does not answer
# with the status JSON the poll loop depends on.
_QR_REQUEST_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Origin": PASSPORT_ORIGIN,
    "Referer": LOGIN_PAGE_URL,
}

_PAGE_TIMEOUT_SECONDS = 15
_IMAGE_TIMEOUT_SECONDS = 15
_POLL_TIMEOUT_SECONDS = 12
_PROFILE_TIMEOUT_SECONDS = 12


class ChaoxingQrError(Exception):
    """The QR login flow could not be driven to a usable state."""


def _require_ok(response: requests.Response, what: str) -> None:
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ChaoxingQrError(f"{what} failed: {exc}") from exc


def _hidden_field(soup: BeautifulSoup | None, field_id: str) -> str:
    if soup is None:
        return ""
    node = soup.find(id=field_id)
    if node is None:
        return ""
    return str(node.get("value") or "").strip()


def create_qr_session(session: requests.Session) -> dict[str, Any]:
    """Start a QR login against ``session``.

    Returns ``{"uuid", "enc", "image", "content_type"}``; ``image`` is raw PNG
    bytes. The authenticated jar ends up in ``session.cookies`` once the user
    confirms on their phone — see :func:`poll_qr_login`.
    """
    try:
        page = session.get(LOGIN_PAGE_URL, timeout=_PAGE_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise ChaoxingQrError(f"qr login page failed: {exc}") from exc
    _require_ok(page, "qr login page")

    try:
        soup = BeautifulSoup(page.text, "lxml")
    except Exception:  # pragma: no cover - parser fallback
        soup = None

    uuid = _hidden_field(soup, "uuid")
    enc = _hidden_field(soup, "enc")
    if not _QR_FIELD_RE.match(uuid) or not _QR_FIELD_RE.match(enc):
        # Do not log the page body: it carries the session cookies' context.
        logger.warning("chaoxing qr login page did not expose usable uuid/enc")
        raise ChaoxingQrError("学习通扫码登录页没有返回二维码参数，请稍后重试")

    image = fetch_qr_image(session, uuid, enc)
    return {
        "uuid": uuid,
        "enc": enc,
        "image": image["image"],
        "content_type": image["content_type"],
    }


def _sniff_image_type(content: bytes, fallback: str) -> str:
    """Name the image from its magic bytes rather than trusting the header.

    Chaoxing's ``createqr`` serves a PNG while declaring ``Content-Type:
    image/jpeg``. The SPA embeds this in a ``data:`` URI, where the declared
    type is what the browser believes, so a wrong one is worth correcting.
    """
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    return fallback


def fetch_qr_image(session: requests.Session, uuid: str, enc: str) -> dict[str, Any]:
    """Fetch (or re-fetch) the QR image for an existing session."""
    try:
        response = session.get(
            CREATE_QR_URL,
            params={"uuid": uuid, "fid": "-1"},
            timeout=_IMAGE_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise ChaoxingQrError(f"qr image failed: {exc}") from exc
    _require_ok(response, "qr image")

    content = response.content or b""
    if not content:
        raise ChaoxingQrError("二维码图片为空，请稍后重试")
    declared = (response.headers.get("content-type") or "").split(";")[0].strip()
    return {
        "image": content,
        "content_type": _sniff_image_type(content, declared or "image/png"),
    }


def poll_qr_login(session: requests.Session, uuid: str, enc: str) -> str:
    """Poll the scan status once.

    Returns one of :data:`QR_STATUS_PENDING`, :data:`QR_STATUS_SCANNED`,
    :data:`QR_STATUS_CONFIRMED` or :data:`QR_STATUS_EXPIRED`. On
    ``confirmed`` the caller's ``session`` now holds an authenticated jar.
    """
    try:
        response = session.post(
            AUTH_STATUS_URL,
            data={"uuid": uuid, "enc": enc},
            headers=_QR_REQUEST_HEADERS,
            timeout=_POLL_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise ChaoxingQrError(f"qr poll failed: {exc}") from exc
    _require_ok(response, "qr poll")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ChaoxingQrError("二维码状态响应不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise ChaoxingQrError("二维码状态响应格式异常")

    if payload.get("status") is True:
        return QR_STATUS_CONFIRMED

    raw_type = payload.get("type")
    try:
        status_type = int(raw_type)
    except (TypeError, ValueError):
        status_type = -1

    if status_type == _TYPE_SCANNED:
        return QR_STATUS_SCANNED
    if status_type == _TYPE_EXPIRED:
        return QR_STATUS_EXPIRED
    return QR_STATUS_PENDING


def fetch_profile(session: requests.Session) -> dict[str, str]:
    """Read the authenticated account's identity.

    Called only after :func:`poll_qr_login` reports ``confirmed``. ``uid`` is
    what the rest of the app needs — ``ChaoxingSigninClient.uid`` reads it from
    the ``_uid`` cookie, which the QR flow does not always set.
    """
    try:
        response = session.get(PROFILE_URL, timeout=_PROFILE_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise ChaoxingQrError(f"profile failed: {exc}") from exc
    _require_ok(response, "profile")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ChaoxingQrError("用户信息响应不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise ChaoxingQrError("用户信息响应格式异常")

    message = payload.get("msg")
    if not isinstance(message, dict):
        raise ChaoxingQrError("扫码登录后未能读取用户信息")

    def text(key: str) -> str:
        return str(message.get(key) or "").strip()

    uid = text("uid") or text("puid")
    if not uid:
        raise ChaoxingQrError("扫码登录后未返回用户 uid")

    return {
        "uid": uid,
        "puid": text("puid") or uid,
        "fid": text("fid") or "-1",
        "name": text("name"),
        "uname": text("uname"),
        "schoolname": text("schoolname"),
    }
