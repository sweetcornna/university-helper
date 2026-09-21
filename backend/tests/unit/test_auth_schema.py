import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginRequest, RegisterRequest


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


@pytest.mark.parametrize("username", ["template", "template0", "template1", "postgres", "main", "root"])
def test_register_rejects_reserved_usernames(username: str) -> None:
    with pytest.raises(ValidationError, match="保留"):
        RegisterRequest(username=username, email="someone@example.com", password="Password1")


def test_register_accepts_names_that_merely_contain_reserved_words() -> None:
    request = RegisterRequest(username="templates2", email="someone@example.com", password="Password1")
    assert request.username == "templates2"
