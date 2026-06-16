import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time

import psycopg2
from psycopg2 import sql

from app.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db_session

logger = logging.getLogger(__name__)

# Precompute a dummy bcrypt hash once at import using the configured work
# factor. login_user verifies against this when the email is unknown so the
# missing-user path costs the same bcrypt time as a wrong-password path,
# closing the user-enumeration timing oracle.
_DUMMY_PASSWORD_HASH = hash_password("timing-oracle-dummy-password")


class AuthService:
    @staticmethod
    def _b64url_encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

    _SHUAKE_SECRET_MIN_LEN = 32

    def _create_shuake_token(self, user_id: int) -> str | None:
        secret = (os.getenv("SHUAKE_COMPAT_SECRET") or "").strip()
        if not secret:
            return None
        if len(secret) < self._SHUAKE_SECRET_MIN_LEN:
            logger.warning(
                "SHUAKE_COMPAT_SECRET is configured but shorter than %d chars; "
                "refusing to issue shuake tokens. Rotate to a stronger secret.",
                self._SHUAKE_SECRET_MIN_LEN,
            )
            return None

        payload = {
            "uid": str(user_id),
            "exp": int(time.time()) + 7 * 24 * 3600,
        }
        payload_b64 = self._b64url_encode(
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        )
        signature = hmac.new(
            secret.encode("utf-8"),
            payload_b64.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return f"{payload_b64}.{self._b64url_encode(signature)}"

    # bcrypt only hashes the first 72 bytes of a password; anything longer is
    # silently truncated. The schema caps length at 128 *characters*, which can
    # still exceed 72 *bytes* once UTF-8 encoded (multibyte CJK). Reject here so
    # the truncation never reaches bcrypt.
    _MAX_PASSWORD_BYTES = 72

    def _validate_password_strength(self, password: str) -> None:
        if len(password.encode("utf-8")) > self._MAX_PASSWORD_BYTES:
            raise ValueError(f"Password must not exceed {self._MAX_PASSWORD_BYTES} bytes")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", password):
            raise ValueError("Password must contain uppercase letter")
        if not re.search(r"[a-z]", password):
            raise ValueError("Password must contain lowercase letter")
        if not re.search(r"\d", password):
            raise ValueError("Password must contain digit")

    @staticmethod
    def _create_tenant_database(tenant_db_name: str) -> None:
        """Create a tenant database from template. Raises on failure.

        Registration is two non-atomic steps (insert user row, then CREATE
        DATABASE). A previous crashed run could leave an orphaned
        `tenant_<username>` DB with no referencing user row, which would make
        that username permanently un-registerable: the INSERT succeeds (no user
        row exists) but CREATE DATABASE then raises DuplicateDatabase, which is
        NOT a UniqueViolation and propagates uncaught.

        We can only reach this method *after* the user row INSERT succeeded,
        which means the UNIQUE constraint on (username, tenant_db_name) already
        guarantees no *live* user owns this tenant DB. So an existing
        `tenant_<username>` DB here is necessarily an orphan: drop and recreate
        it to make registration idempotent/recoverable.
        """
        ddl_conn = None
        try:
            ddl_conn = psycopg2.connect(
                host=settings.MAIN_DB_HOST,
                database=settings.MAIN_DB_NAME,
                user=settings.MAIN_DB_USER,
                password=settings.MAIN_DB_PASSWORD,
                port=settings.MAIN_DB_PORT,
            )
            ddl_conn.autocommit = True
            with ddl_conn.cursor() as ddl_cur:
                try:
                    ddl_cur.execute(
                        sql.SQL("CREATE DATABASE {} TEMPLATE tenant_template").format(sql.Identifier(tenant_db_name))
                    )
                except psycopg2.errors.DuplicateDatabase:
                    logger.warning(
                        "Tenant database %s already existed (orphan); dropping and recreating",
                        tenant_db_name,
                    )
                    ddl_cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(tenant_db_name)))
                    ddl_cur.execute(
                        sql.SQL("CREATE DATABASE {} TEMPLATE tenant_template").format(sql.Identifier(tenant_db_name))
                    )
            logger.info("Tenant database %s created successfully", tenant_db_name)
        finally:
            if ddl_conn:
                ddl_conn.close()

    @staticmethod
    def _drop_tenant_database(tenant_db_name: str) -> None:
        """Best-effort DROP of a tenant DB (used on the rollback path so a
        partially-created DB does not become an orphan). Never raises."""
        ddl_conn = None
        try:
            ddl_conn = psycopg2.connect(
                host=settings.MAIN_DB_HOST,
                database=settings.MAIN_DB_NAME,
                user=settings.MAIN_DB_USER,
                password=settings.MAIN_DB_PASSWORD,
                port=settings.MAIN_DB_PORT,
            )
            ddl_conn.autocommit = True
            with ddl_conn.cursor() as ddl_cur:
                ddl_cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(tenant_db_name)))
            logger.info("Dropped tenant database %s on rollback", tenant_db_name)
        except Exception:
            logger.exception("Failed to drop tenant database %s during rollback", tenant_db_name)
        finally:
            if ddl_conn:
                ddl_conn.close()

    # Must align with _validate_tenant_db_name in app/db/session.py
    _USERNAME_RE = re.compile(r"^[a-z0-9]+$")

    def _insert_user_row(self, username: str, email: str, password_hash: str, tenant_db_name: str) -> int:
        """Synchronous DB block — must be called from a worker thread.

        We trust the UNIQUE constraints on (email, username, tenant_db_name)
        rather than pre-checking with SELECTs — that would add two extra
        round-trips per registration without closing the race window.
        """
        try:
            # `with conn.cursor()` guarantees the cursor is closed even when the
            # INSERT raises, so no open cursor is returned to the pool.
            with get_db_session() as conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username, email, password_hash, tenant_db_name) VALUES (%s, %s, %s, %s) RETURNING id",
                    (username, email, password_hash, tenant_db_name),
                )
                return cur.fetchone()["id"]
        except psycopg2.errors.UniqueViolation as exc:
            constraint = (getattr(getattr(exc, "diag", None), "constraint_name", "") or "").lower()
            if "email" in constraint:
                raise ValueError("Email already registered")
            if "username" in constraint or "tenant_db_name" in constraint:
                raise ValueError("Username already taken")
            raise ValueError("用户名或邮箱已被占用")
        except psycopg2.errors.IntegrityError:
            raise ValueError("用户名或邮箱已被占用")

    def _rollback_user_row(self, user_id: int) -> None:
        try:
            with get_db_session() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        except Exception:
            logger.exception("Failed to roll back user row id=%s after tenant DB failure", user_id)

    def _build_auth_response(self, user_id: int, tenant_db_name: str) -> dict:
        access_token = create_access_token({"user_id": user_id, "tenant_db_name": tenant_db_name})
        result = {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user_id,
            "tenant_db_name": tenant_db_name,
        }
        shuake_token = self._create_shuake_token(user_id)
        if shuake_token:
            result["shuake_token"] = shuake_token
        return result

    async def register_user(self, username: str, email: str, password: str) -> dict:
        if not username or not self._USERNAME_RE.match(username):
            raise ValueError("用户名只能包含小写字母和数字（a-z、0-9）")
        self._validate_password_strength(password)
        # bcrypt is CPU-bound; offload to thread to keep the event loop responsive.
        password_hash = await asyncio.to_thread(hash_password, password)
        tenant_db_name = f"tenant_{username}"

        user_id = await asyncio.to_thread(self._insert_user_row, username, email, password_hash, tenant_db_name)

        # Create tenant database; roll back user row (and drop any partially
        # created tenant DB) on failure so neither step leaves an orphan.
        try:
            await asyncio.to_thread(self._create_tenant_database, tenant_db_name)
        except Exception:
            logger.exception(
                "Tenant DB creation failed for %s; rolling back user row id=%s",
                tenant_db_name,
                user_id,
            )
            await asyncio.to_thread(self._rollback_user_row, user_id)
            await asyncio.to_thread(self._drop_tenant_database, tenant_db_name)
            raise

        return self._build_auth_response(user_id, tenant_db_name)

    def _fetch_login_row(self, email: str):
        with get_db_session() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, password_hash, tenant_db_name FROM users WHERE email = %s",
                (email,),
            )
            return cur.fetchone()

    async def login_user(self, email: str, password: str) -> dict:
        # Both the DB roundtrip and bcrypt verification are blocking; offload
        # so the event loop stays responsive.
        row = await asyncio.to_thread(self._fetch_login_row, email)

        # Constant-time-ish: always run a bcrypt verification, even when the
        # user does not exist, against a fixed dummy hash. Otherwise the no-row
        # branch returns in microseconds while the wrong-password branch pays
        # the full bcrypt work factor, leaking which emails are registered.
        stored_hash = row["password_hash"] if row else _DUMMY_PASSWORD_HASH
        password_ok = await asyncio.to_thread(verify_password, password, stored_hash)

        if not row or not password_ok:
            raise ValueError("Invalid credentials")
        return self._build_auth_response(row["id"], row["tenant_db_name"])
