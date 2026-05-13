import jwt
import bcrypt
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict

from app.config import settings


def hash_password(password: str) -> str:
    rounds = max(4, min(settings.BCRYPT_ROUNDS, 15))
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=rounds)).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def create_access_token(data: Dict) -> str:
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
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


def decode_token(token: str) -> Dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")
