import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import settings

# bcrypt only considers the first 72 bytes of the password and silently
# ignores (truncates) the rest. Without an explicit guard, two distinct
# passwords sharing the first 72 bytes would hash/verify identically, and a
# password whose char length passes the schema check (<=128 chars) can still
# exceed 72 bytes once UTF-8 encoded (e.g. multibyte CJK). Reject such inputs
# rather than pre-hashing, which would invalidate existing stored hashes.
BCRYPT_MAX_PASSWORD_BYTES = 72


def _encode_password(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must not exceed {BCRYPT_MAX_PASSWORD_BYTES} bytes")
    return encoded


def hash_password(password: str) -> str:
    rounds = max(4, min(settings.BCRYPT_ROUNDS, 15))
    return bcrypt.hashpw(_encode_password(password), bcrypt.gensalt(rounds=rounds)).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Fail closed on missing/non-string input rather than raising; callers run
    # this on the login path against a dummy hash even when the user is unknown.
    if not isinstance(plain_password, str) or not isinstance(hashed_password, str):
        return False
    # An over-long candidate can never match a hash produced by hash_password
    # (which rejects them), so fail closed instead of letting bcrypt truncate.
    encoded = plain_password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        return False
    return bcrypt.checkpw(encoded, hashed_password.encode())


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    now = datetime.now(UTC)
    now_ts = int(now.timestamp())
    # iat/nbf/jti give us a future-proof revocation surface (jti can be
    # blacklisted on logout) without changing the wire format consumers see.
    to_encode.update(
        {
            "iat": now_ts,
            "nbf": now_ts,
            "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
            "jti": secrets.token_urlsafe(16),
        }
    )
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")
