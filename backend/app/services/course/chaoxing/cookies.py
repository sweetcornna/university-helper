# Cookies management - simplified for unified platform
import json
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from ..task_store import task_store

# Persist cookies under a writable path. In production the container runs
# with a read-only rootfs (docker-compose.server.yml: read_only: true) and
# only /tmp is writable (tmpfs). A relative "cookies.json" resolves under the
# read-only code dir and fails with OSError [Errno 30] Read-only file system,
# which previously broke Chaoxing login and failed every learning task.
COOKIES_DIR = Path(os.environ.get("CHAOXING_COOKIES_DIR", "/tmp"))
# Legacy global file — kept for backward compat with old call sites and as the
# fallback when no user_id is supplied.
COOKIES_FILE = Path(os.environ.get("CHAOXING_COOKIES_FILE", "/tmp/cookies.json"))
# A cookie jar authenticates on its own; keep it unreadable by other local users.
COOKIES_FILE_MODE = 0o600

# user_id is a UUID hex from the app's auth layer; sanitize defensively so a
# malformed value can never escape the cookies dir via path traversal.
_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Durable session storage. The jar lives in the shared task store (per platform
# user, Fernet-encrypted) instead of only in the /tmp file, which production
# mounts as a tmpfs that is destroyed on every container restart.
CHAOXING_SESSION_KIND = "chaoxing_session"
# How long a stored Chaoxing session may be reused before the user must log in
# again. Measured from ``saved_at``, which rolls forward on successful use.
CHAOXING_SESSION_TTL = timedelta(days=7)

_USERNAME_FIELD = "chaoxing_username"
# Must stay in sync with task_store._SENSITIVE_FIELDS so the jar is encrypted.
_COOKIES_FIELD = "chaoxing_cookies"


def _cookies_file_for(user_id) -> Path:
    """Return the per-user cookie path. Falls back to the global file when
    ``user_id`` is empty or contains characters outside the safe set."""
    uid = str(user_id or "").strip()
    if uid and _USER_ID_RE.match(uid):
        return COOKIES_DIR / f"cookies_{uid}.json"
    return COOKIES_FILE


def _mask(user_id) -> str:
    """Mask a platform user id for logging."""
    uid = str(user_id or "")
    return f"{uid[:4]}***" if len(uid) > 4 else "***"


def save_cookies(session, user_id=None):
    """Save session cookies to a per-user file.

    Best-effort: persisting cookies is an optimization, not a requirement, so
    a write failure must never propagate and break login. When ``user_id`` is
    given the cookies are stored under ``cookies_<user_id>.json`` so multiple
    platform users don't overwrite each other; otherwise the legacy global
    ``cookies.json`` is used.
    """
    try:
        cookies = session.cookies.get_dict()
        target = _cookies_file_for(user_id)
        # Create at 0600 (and re-tighten a pre-existing 0644 file) so the jar is
        # not world-readable on a shared host.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, COOKIES_FILE_MODE)
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(cookies))
        os.chmod(target, COOKIES_FILE_MODE)
    except OSError:
        pass


def use_cookies(user_id=None):
    """Load cookies from the per-user file. Returns {} if unavailable or unreadable."""
    try:
        target = _cookies_file_for(user_id)
        if target.exists():
            return json.loads(target.read_text())
    except (OSError, ValueError):
        pass
    return {}


def _delete_cookies_file(user_id=None) -> None:
    try:
        _cookies_file_for(user_id).unlink(missing_ok=True)
    except OSError:
        pass


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_iso(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _normalize_user_id(user_id) -> str:
    return str(user_id or "").strip()


def save_session(user_id, username, cookies) -> bool:
    """Persist ``cookies`` bound to the Chaoxing account that produced them.

    The username is stored alongside the jar so a later login as a *different*
    Chaoxing account can never silently reuse this session (F-account-binding).
    Returns False when the session could not be persisted; callers treat that as
    non-fatal.
    """
    uid = _normalize_user_id(user_id)
    account = str(username or "").strip()
    if not uid or not account or not cookies:
        return False

    now = _now().isoformat()
    record = {
        # One live Chaoxing session per platform user, so the row key is the user.
        "task_id": uid,
        "user_id": uid,
        "status": "active",
        "message": "",
        "started_at": now,
        "updated_at": now,
        "saved_at": now,
        _USERNAME_FIELD: account,
        _COOKIES_FIELD: json.dumps(cookies, ensure_ascii=False),
    }
    try:
        task_store.upsert_task(CHAOXING_SESSION_KIND, record)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("保存超星会话失败 user={} err={}", _mask(uid), exc)
        return False
    return True


def delete_session(user_id) -> None:
    """Drop the stored session for ``user_id``.

    The task-store protocol has no delete, so we overwrite the row with a
    revoked tombstone carrying neither a username nor cookies — which
    ``load_session`` refuses to adopt. The per-user cookie file is removed too,
    so "switch account" leaves nothing reusable behind.
    """
    uid = _normalize_user_id(user_id)
    if not uid:
        return
    now = _now().isoformat()
    try:
        task_store.upsert_task(
            CHAOXING_SESSION_KIND,
            {
                "task_id": uid,
                "user_id": uid,
                "status": "revoked",
                "message": "",
                "started_at": now,
                "updated_at": now,
                "saved_at": "",
                _USERNAME_FIELD: "",
                _COOKIES_FIELD: "",
            },
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("删除超星会话失败 user={} err={}", _mask(uid), exc)
    _delete_cookies_file(uid)


def _read_record(uid: str) -> dict[str, Any] | None:
    """Return the stored record when it is present, bound and unexpired.

    Unusable records (unbound, expired, undecryptable) are deleted here so a
    dead session never lingers.
    """
    try:
        record = task_store.get_task(CHAOXING_SESSION_KIND, uid, uid)
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("读取超星会话失败 user={} err={}", _mask(uid), exc)
        return None
    if not record:
        return None

    if not str(record.get(_USERNAME_FIELD) or "").strip():
        # An unbound jar cannot be proven to belong to any particular Chaoxing
        # account, so it is never adopted (this also covers the revoked
        # tombstone written by delete_session).
        delete_session(uid)
        return None

    saved_at = _parse_iso(record.get("saved_at"))
    if saved_at is None or _now() - saved_at >= CHAOXING_SESSION_TTL:
        logger.info("超星会话已过期，已清除 user={}", _mask(uid))
        delete_session(uid)
        return None
    return record


def load_session(user_id, expected_username=None) -> dict[str, Any] | None:
    """Load the stored session for ``user_id``.

    Returns ``{"username", "cookies", "saved_at", "expires_at"}`` or None.

    When ``expected_username`` is given, the stored session is only returned if
    it belongs to that Chaoxing account; a mismatch returns None so the caller
    falls through to a password login (which then overwrites this record).
    """
    uid = _normalize_user_id(user_id)
    if not uid:
        return None
    record = _read_record(uid)
    if not record:
        return None

    stored_username = str(record.get(_USERNAME_FIELD) or "").strip()
    wanted = str(expected_username or "").strip()
    if wanted and wanted != stored_username:
        logger.info("已保存的超星会话属于其它账号，改用账号密码登录 user={}", _mask(uid))
        return None

    try:
        cookies = json.loads(str(record.get(_COOKIES_FIELD) or ""))
    except ValueError:
        cookies = None
    if not isinstance(cookies, dict) or not cookies:
        # Empty means encryption failed on write (fail-closed drop) or the blob
        # is corrupt — either way there is nothing usable to restore.
        logger.warning("已保存的超星会话缺少可用 cookies，已清除 user={}", _mask(uid))
        delete_session(uid)
        return None

    saved_at = _parse_iso(record.get("saved_at"))
    return {
        "username": stored_username,
        "cookies": cookies,
        "saved_at": saved_at.isoformat() if saved_at else "",
        "expires_at": (saved_at + CHAOXING_SESSION_TTL).isoformat() if saved_at else "",
    }


def session_metadata(user_id) -> dict[str, Any] | None:
    """Return ``{"username", "expires_at"}`` for the stored session, or None.

    NEVER returns cookies — this feeds the session status endpoint.
    """
    uid = _normalize_user_id(user_id)
    if not uid:
        return None
    record = _read_record(uid)
    if not record:
        return None
    saved_at = _parse_iso(record.get("saved_at"))
    return {
        "username": str(record.get(_USERNAME_FIELD) or "").strip(),
        "expires_at": (saved_at + CHAOXING_SESSION_TTL).isoformat() if saved_at else "",
    }


def touch_session(user_id) -> None:
    """Roll the TTL forward after the stored session was successfully used."""
    uid = _normalize_user_id(user_id)
    if not uid:
        return
    stored = load_session(uid)
    if stored:
        save_session(uid, stored["username"], stored["cookies"])
