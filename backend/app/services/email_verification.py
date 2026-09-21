"""Email verification codes for registration and password reset.

Storage lives in the main DB table ``email_verification_codes`` (see alembic
003 / database/00-schema.sql). Only a KEYED digest of the code is persisted; the
plaintext exists in memory and in the delivered email, nowhere else.

That table only exists on a database that has had ``alembic upgrade
main_db@head`` applied — ``database/*.sql`` runs only on a virgin Postgres data
directory. On an existing deployment where the feature is switched on before the
migration is run, psycopg2 raises UndefinedTable; both public functions translate
that into :class:`VerificationUnavailableError` so the API can answer 503 with an
actionable message instead of a bare 500.

Both public functions are BLOCKING (DB + SMTP). API handlers must call them
through ``asyncio.to_thread``.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta

from app.config import settings
from app.core.mailer import MailerError, send_email
from app.db.session import get_db_session

logger = logging.getLogger(__name__)

SCENE_REGISTER = "register"
SCENE_RESET = "reset"
_SCENES = (SCENE_REGISTER, SCENE_RESET)

CODE_TTL_SECONDS = 600
RESEND_COOLDOWN_SECONDS = 60
MAX_ATTEMPTS = 5

_SUBJECTS = {
    SCENE_REGISTER: "学道 - 注册验证码",
    SCENE_RESET: "学道 - 重置密码验证码",
}
_PURPOSES = {
    SCENE_REGISTER: "注册账号",
    SCENE_RESET: "重置密码",
}


# psycopg2 SQLSTATE for "relation does not exist". Compared off the exception's
# `pgcode` attribute rather than caught as psycopg2.errors.UndefinedTable so this
# module never imports psycopg2 — the frozen desktop build deliberately does not
# bundle it (see app/db/session.py).
_UNDEFINED_TABLE_PGCODE = "42P01"
_MISSING_TABLE_DETAIL = "邮箱验证服务未初始化，请联系管理员执行数据库迁移"


class VerificationError(ValueError):
    """Expected, user-facing failure. ``str(exc)`` is shown to the user (Chinese)."""


class VerificationUnavailableError(RuntimeError):
    """The backing table is missing — the deployment has not been migrated.

    An operator problem, not a user one: the API turns this into a 503 rather
    than counting it as a rejected code.
    """


def _mask_email(email: str) -> str:
    """u***@domain — safe to log."""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "***"
    return f"{local[:1] or '*'}***@{domain}"


def _reraise_if_table_missing(exc: Exception) -> None:
    """Translate a missing ``email_verification_codes`` into a 503-able error."""
    if getattr(exc, "pgcode", None) != _UNDEFINED_TABLE_PGCODE:
        return
    logger.error(
        "email_verification_codes table is missing; run `alembic upgrade main_db@head` against the main database",
        exc_info=True,
    )
    raise VerificationUnavailableError(_MISSING_TABLE_DETAIL) from exc


def _hash_code(code: str) -> str:
    """Keyed digest of a code, for storage in ``code_hash``.

    HMAC rather than a bare SHA-256: the keyspace is only 10^6, so an unkeyed
    digest is trivially reversed by enumeration for anyone who can read the
    table (leaked backup, read replica, SQL read primitive). Keying with
    SECRET_KEY means the table alone is worthless. Output is still 64 hex chars,
    so the CHAR(64) column is unchanged, and it is still compared with
    hmac.compare_digest.
    """
    return hmac.new(settings.SECRET_KEY.encode("utf-8"), code.encode("utf-8"), hashlib.sha256).hexdigest()


def _generate_code() -> str:
    """A 6-digit code from the CSPRNG. Never `random` — these gate account access."""
    return f"{secrets.randbelow(1_000_000):06d}"


def _normalize(email: str, scene: str) -> tuple[str, str]:
    normalized = (email or "").strip().lower()
    if not normalized:
        raise VerificationError("邮箱不能为空")
    if scene not in _SCENES:
        raise VerificationError("验证码场景无效")
    return normalized, scene


def send_code(email: str, scene: str) -> None:
    """Generate, store (hashed) and email a 6-digit code. BLOCKING.

    Raises :class:`VerificationError` while within the resend cooldown, or when
    the mail could not be delivered, and :class:`VerificationUnavailableError`
    when the backing table has not been migrated in.
    """
    email, scene = _normalize(email, scene)
    code = _generate_code()
    now = datetime.now(UTC)

    # The cooldown is enforced by the UPSERT itself: the WHERE clause on the
    # DO UPDATE branch refuses to overwrite a row whose last_sent_at is inside
    # the cooldown window, so two concurrent requests cannot both win.
    try:
        with get_db_session() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO email_verification_codes (email, scene, code_hash, expires_at, attempts, last_sent_at)
                VALUES (%s, %s, %s, %s, 0, %s)
                ON CONFLICT (email, scene) DO UPDATE
                    SET code_hash = EXCLUDED.code_hash,
                        expires_at = EXCLUDED.expires_at,
                        attempts = 0,
                        last_sent_at = EXCLUDED.last_sent_at
                    WHERE email_verification_codes.last_sent_at <= %s
                RETURNING email
                """,
                (
                    email,
                    scene,
                    _hash_code(code),
                    now + timedelta(seconds=CODE_TTL_SECONDS),
                    now,
                    now - timedelta(seconds=RESEND_COOLDOWN_SECONDS),
                ),
            )
            if cur.fetchone() is None:
                raise VerificationError(f"发送过于频繁，请 {RESEND_COOLDOWN_SECONDS} 秒后再试")
    except Exception as exc:
        _reraise_if_table_missing(exc)
        raise

    try:
        send_email(
            to=email,
            subject=_SUBJECTS[scene],
            html=_render_html(code, scene),
            text=_render_text(code, scene),
        )
    except MailerError as exc:
        # The row stays; the user can retry after the cooldown. Deleting it here
        # would let a bad SMTP config turn into an unthrottled send loop.
        # `exc` may name the missing setting, so it goes to the log, not the user.
        logger.warning("verification email not delivered to %s (scene=%s): %s", _mask_email(email), scene, exc)
        raise VerificationError("验证码邮件发送失败，请稍后再试") from exc

    logger.info("verification code sent to %s (scene=%s)", _mask_email(email), scene)


def verify_code(email: str, scene: str, code: str) -> None:
    """Consume a code. Single use — the row is deleted on success. BLOCKING.

    Raises :class:`VerificationError` when the code is wrong, expired, or the
    attempt budget is exhausted, and :class:`VerificationUnavailableError` when
    the backing table has not been migrated in.
    """
    email, scene = _normalize(email, scene)
    submitted = (code or "").strip()
    if not submitted:
        raise VerificationError("请输入验证码")

    now = datetime.now(UTC)

    # A failure is RECORDED here and raised after the block, never raised inside
    # it. get_db_session rolls back on exception, so raising in-block would throw
    # away the very writes that enforce the limit: attempts would reset to 0 on
    # every wrong guess, MAX_ATTEMPTS would be unreachable, and the code could be
    # brute-forced for its whole lifetime.
    failure: str | None = None

    try:
        with get_db_session() as conn, conn.cursor() as cur:
            # Opportunistic sweep: expired rows are dead weight and must never be
            # treated as a live code, so drop them before looking ours up.
            cur.execute("DELETE FROM email_verification_codes WHERE expires_at <= %s", (now,))

            cur.execute(
                "SELECT code_hash, attempts FROM email_verification_codes WHERE email = %s AND scene = %s FOR UPDATE",
                (email, scene),
            )
            row = cur.fetchone()

            if row is None:
                logger.warning("verification failed: no live code for %s (scene=%s)", _mask_email(email), scene)
                failure = "验证码已过期或不存在，请重新获取"
            elif hmac.compare_digest(row["code_hash"], _hash_code(submitted)):
                cur.execute(
                    "DELETE FROM email_verification_codes WHERE email = %s AND scene = %s",
                    (email, scene),
                )
            else:
                attempts = row["attempts"] + 1
                if attempts >= MAX_ATTEMPTS:
                    cur.execute(
                        "DELETE FROM email_verification_codes WHERE email = %s AND scene = %s",
                        (email, scene),
                    )
                    logger.warning("verification code exhausted for %s (scene=%s)", _mask_email(email), scene)
                    failure = "验证码错误次数过多，请重新获取"
                else:
                    cur.execute(
                        "UPDATE email_verification_codes SET attempts = %s WHERE email = %s AND scene = %s",
                        (attempts, email, scene),
                    )
                    logger.warning(
                        "verification code mismatch for %s (scene=%s, attempt=%d)", _mask_email(email), scene, attempts
                    )
                    failure = f"验证码错误，还可尝试 {MAX_ATTEMPTS - attempts} 次"
    except Exception as exc:
        _reraise_if_table_missing(exc)
        raise

    if failure:
        raise VerificationError(failure)


def _render_text(code: str, scene: str) -> str:
    minutes = CODE_TTL_SECONDS // 60
    return (
        f"【学道】您正在{_PURPOSES[scene]}，验证码：{code}\n\n"
        f"验证码 {minutes} 分钟内有效，请勿转发给他人。\n"
        "如果这不是您本人的操作，请忽略本邮件。"
    )


def _render_html(code: str, scene: str) -> str:
    minutes = CODE_TTL_SECONDS // 60
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<body style="margin:0;padding:24px;background:#f5f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;color:#1f2329;">
  <div style="max-width:480px;margin:0 auto;background:#ffffff;border-radius:12px;padding:32px;">
    <p style="margin:0 0 16px;font-size:18px;font-weight:600;">学道</p>
    <p style="margin:0 0 24px;font-size:14px;line-height:1.6;">您正在{_PURPOSES[scene]}，请在页面中输入以下验证码：</p>
    <p style="margin:0 0 24px;font-size:32px;font-weight:700;letter-spacing:8px;color:#2563eb;">{code}</p>
    <p style="margin:0 0 8px;font-size:13px;line-height:1.6;color:#646a73;">验证码 {minutes} 分钟内有效，请勿转发给他人。</p>
    <p style="margin:0;font-size:13px;line-height:1.6;color:#646a73;">如果这不是您本人的操作，请忽略本邮件。</p>
  </div>
</body>
</html>"""
