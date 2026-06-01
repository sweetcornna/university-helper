import pytest
import jwt
from datetime import datetime, timedelta, timezone
from app.core.security import hash_password, verify_password, create_access_token, decode_token
from app.config import settings


def test_hash_password():
    password = "test123"
    hashed = hash_password(password)
    assert hashed != password
    assert len(hashed) > 0


def test_verify_password_valid():
    password = "test123"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True


def test_verify_password_invalid():
    password = "test123"
    hashed = hash_password(password)
    assert verify_password("wrong", hashed) is False


def test_create_access_token():
    data = {"user_id": 1, "tenant_db_name": "tenant_test"}
    token = create_access_token(data)
    assert isinstance(token, str)
    assert len(token) > 0


def test_decode_token_valid():
    data = {"user_id": 1, "tenant_db_name": "tenant_test"}
    token = create_access_token(data)
    decoded = decode_token(token)
    assert decoded["user_id"] == 1
    assert decoded["tenant_db_name"] == "tenant_test"
    assert "exp" in decoded


def test_decode_token_expired():
    data = {"user_id": 1, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}
    token = jwt.encode(data, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    with pytest.raises(ValueError, match="Token has expired"):
        decode_token(token)


def test_decode_token_invalid():
    with pytest.raises(ValueError, match="Invalid token"):
        decode_token("invalid_token")


# --- bcrypt 72-byte truncation enforcement (audit: bcrypt silently truncates >72 bytes) ---

def test_hash_password_rejects_over_72_bytes():
    # 73 ASCII bytes — bcrypt would silently truncate to 72.
    with pytest.raises(ValueError, match="72 bytes"):
        hash_password("A" * 73)


def test_hash_password_rejects_multibyte_over_72_bytes():
    # 30 chars but 90 UTF-8 bytes — passes a 128-char schema check yet
    # exceeds bcrypt's 72-byte limit.
    pw = "密" * 30
    assert len(pw) <= 128
    assert len(pw.encode("utf-8")) > 72
    with pytest.raises(ValueError, match="72 bytes"):
        hash_password(pw)


def test_hash_password_accepts_exactly_72_bytes():
    pw = "A" * 72
    hashed = hash_password(pw)
    assert verify_password(pw, hashed) is True


def test_verify_password_rejects_over_72_bytes_without_truncation_collision():
    # A 72-byte password and a 73-byte password sharing the first 72 bytes must
    # NOT verify as equal (bcrypt's native truncation would make them collide).
    base = "A" * 72
    hashed = hash_password(base)
    assert verify_password(base + "X", hashed) is False
