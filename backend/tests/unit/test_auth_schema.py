import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginRequest


def test_login_password_accepts_128_characters() -> None:
    request = LoginRequest(email="user@example.com", password="x" * 128)

    assert len(request.password) == 128


def test_login_password_rejects_129_characters() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="user@example.com", password="x" * 129)


def test_login_schema_accepts_normal_credentials() -> None:
    request = LoginRequest(email="user@example.com", password="ValidPass1")

    assert request.email == "user@example.com"
    assert request.password == "ValidPass1"
