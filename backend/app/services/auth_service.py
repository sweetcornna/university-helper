from psycopg2 import sql
import psycopg2
import re
import os
import time
import json
import hmac
import hashlib
import base64
import logging
import asyncio
from app.core.security import hash_password, verify_password, create_access_token
from app.db.session import get_db_session
from app.config import settings

logger = logging.getLogger(__name__)


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

    def _validate_password_strength(self, password: str) -> None:
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r'[A-Z]', password):
            raise ValueError("Password must contain uppercase letter")
        if not re.search(r'[a-z]', password):
            raise ValueError("Password must contain lowercase letter")
        if not re.search(r'\d', password):
            raise ValueError("Password must contain digit")

    @staticmethod
    def _create_tenant_database(tenant_db_name: str) -> None:
        """Create a tenant database from template. Raises on failure."""
        ddl_conn = None
        try:
            ddl_conn = psycopg2.connect(
                host=settings.MAIN_DB_HOST,
                database=settings.MAIN_DB_NAME,
                user=settings.MAIN_DB_USER,
                password=settings.MAIN_DB_PASSWORD,
                port=settings.MAIN_DB_PORT
            )
            ddl_conn.autocommit = True
            ddl_cur = ddl_conn.cursor()
            ddl_cur.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE tenant_template").format(
                    sql.Identifier(tenant_db_name)
                )
            )
            ddl_cur.close()
            logger.info("Tenant database %s created successfully", tenant_db_name)
        finally:
            if ddl_conn:
                ddl_conn.close()

    # Must align with _validate_tenant_db_name in app/db/session.py
    _USERNAME_RE = re.compile(r'^[a-z0-9]+$')

    def _insert_user_row(
        self, username: str, email: str, password_hash: str, tenant_db_name: str
    ) -> int:
        """Synchronous DB block — must be called from a worker thread.

        We trust the UNIQUE constraints on (email, username, tenant_db_name)
        rather than pre-checking with SELECTs — that would add two extra
        round-trips per registration without closing the race window.
        """
        try:
            with get_db_session() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO users (username, email, password_hash, tenant_db_name) VALUES (%s, %s, %s, %s) RETURNING id",
                    (username, email, password_hash, tenant_db_name),
                )
                user_id = cur.fetchone()["id"]
                cur.close()
                return user_id
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
            with get_db_session() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
                cur.close()
        except Exception:
            logger.exception(
                "Failed to roll back user row id=%s after tenant DB failure", user_id
            )

    def _build_auth_response(self, user_id: int, tenant_db_name: str) -> dict:
        access_token = create_access_token(
            {"user_id": user_id, "tenant_db_name": tenant_db_name}
        )
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

        user_id = await asyncio.to_thread(
            self._insert_user_row, username, email, password_hash, tenant_db_name
        )

        # Create tenant database; roll back user row on failure.
        try:
            await asyncio.to_thread(self._create_tenant_database, tenant_db_name)
        except Exception:
            logger.exception(
                "Tenant DB creation failed for %s; rolling back user row id=%s",
                tenant_db_name, user_id,
            )
            await asyncio.to_thread(self._rollback_user_row, user_id)
            raise

        return self._build_auth_response(user_id, tenant_db_name)

    def _fetch_login_row(self, email: str):
        with get_db_session() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT id, password_hash, tenant_db_name FROM users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()
            cur.close()
            return row

    async def login_user(self, email: str, password: str) -> dict:
        # Both the DB roundtrip and bcrypt verification are blocking; offload
        # so the event loop stays responsive.
        row = await asyncio.to_thread(self._fetch_login_row, email)
        if not row or not await asyncio.to_thread(
            verify_password, password, row["password_hash"]
        ):
            raise ValueError("Invalid credentials")
        return self._build_auth_response(row["id"], row["tenant_db_name"])
