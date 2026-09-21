import re
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

# Must align with _validate_tenant_db_name in app/db/session.py, which builds
# tenant database names as `tenant_{username}` and only accepts [a-z0-9]+.
USERNAME_RE = re.compile(r"^[a-z0-9]+$")

# Usernames that would map onto PostgreSQL's own databases. `template` is the
# dangerous one: `tenant_template` is the database every tenant is cloned from.
RESERVED_USERNAMES = frozenset({"template", "template0", "template1", "postgres", "main", "maindb", "root", "system"})
RESERVED_USERNAME_MESSAGE = "该用户名为系统保留名称，请换一个"


def normalize_email(v: str) -> str:
    """Canonicalize an address to `strip().lower()`.

    Applied to EVERY request schema carrying an email so that the whole stack
    below the edge — `users.email` lookups/updates in AuthService and the
    `(email, scene)` key of `email_verification_codes` — compares the same
    bytes. `EmailStr` only lowercases the DOMAIN, so without this a user who
    registered as `Alice@example.com` could request a reset code (stored
    lowercase by `email_verification._normalize`), pass verification, and then
    have the UPDATE match zero rows against the case-sensitive
    `users.email` column.
    """
    return (v or "").strip().lower()


def validate_password_rules(v: str) -> str:
    """Password strength rules, shared by every endpoint that sets a password.

    Registration and password reset both end in a bcrypt hash written to
    `users.password_hash`; keeping the rules in one function is what stops the
    reset path from quietly accepting passwords registration would reject.
    """
    if not v or len(v) > 128:
        raise ValueError("密码长度无效")
    if len(v) < 8:
        raise ValueError("密码至少 8 个字符")
    if not re.search(r"[A-Z]", v):
        raise ValueError("密码需包含至少一个大写字母")
    if not re.search(r"[a-z]", v):
        raise ValueError("密码需包含至少一个小写字母")
    if not re.search(r"\d", v):
        raise ValueError("密码需包含至少一个数字")
    return v


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    # Optional at the schema layer because the field only exists when
    # EMAIL_VERIFICATION_ENABLED is on. The route enforces its presence in that
    # case, so deployments with the flag off keep sending today's payload.
    code: str | None = None

    @field_validator("email")
    @classmethod
    def canonicalize_email(cls, v):
        return normalize_email(v)

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if not v or len(v) < 3 or len(v) > 30:
            raise ValueError("用户名长度需为 3-30 个字符")
        if not USERNAME_RE.match(v):
            raise ValueError("用户名只能包含小写字母和数字（a-z、0-9）")
        if v in RESERVED_USERNAMES:
            raise ValueError(RESERVED_USERNAME_MESSAGE)
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        return validate_password_rules(v)


class SendCodeRequest(BaseModel):
    email: EmailStr
    scene: Literal["register", "reset"]

    @field_validator("email")
    @classmethod
    def canonicalize_email(cls, v):
        return normalize_email(v)


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str

    @field_validator("email")
    @classmethod
    def canonicalize_email(cls, v):
        return normalize_email(v)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v):
        return validate_password_rules(v)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def canonicalize_email(cls, v):
        return normalize_email(v)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    tenant_db_name: str
    shuake_token: str | None = None
