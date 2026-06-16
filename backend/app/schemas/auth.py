import re

from pydantic import BaseModel, EmailStr, field_validator

# Must align with _validate_tenant_db_name in app/db/session.py, which builds
# tenant database names as `tenant_{username}` and only accepts [a-z0-9]+.
USERNAME_RE = re.compile(r"^[a-z0-9]+$")


class RegisterRequest(BaseModel):
    username: str
    email: EmailStr
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        if not v or len(v) < 3 or len(v) > 30:
            raise ValueError("用户名长度需为 3-30 个字符")
        if not USERNAME_RE.match(v):
            raise ValueError("用户名只能包含小写字母和数字（a-z、0-9）")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
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


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    tenant_db_name: str
    shuake_token: str | None = None
