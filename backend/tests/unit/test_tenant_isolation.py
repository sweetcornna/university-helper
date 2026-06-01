import pytest
from fastapi import Request
from unittest.mock import Mock, AsyncMock, patch
from app.middleware.tenant_isolation import tenant_isolation_middleware


@pytest.fixture
def mock_request():
    request = Mock(spec=Request)
    request.url.path = "/api/v1/protected"
    request.headers = {}
    request.state = Mock()
    return request


@pytest.fixture
def mock_call_next():
    return AsyncMock(return_value=Mock())


@pytest.mark.asyncio
async def test_whitelisted_paths(mock_call_next):
    paths = ["/api/v1/auth/register", "/api/v1/auth/login", "/docs", "/openapi.json"]

    for path in paths:
        request = Mock(spec=Request)
        request.url.path = path
        result = await tenant_isolation_middleware(request, mock_call_next)
        assert result is not None


@pytest.mark.asyncio
async def test_missing_authorization_header(mock_request, mock_call_next):
    response = await tenant_isolation_middleware(mock_request, mock_call_next)
    assert response.status_code == 401
    assert b"Missing token" in response.body


@pytest.mark.asyncio
async def test_malformed_token(mock_request, mock_call_next):
    mock_request.headers = {"Authorization": "Bearer malformed_token"}

    with patch("app.middleware.tenant_isolation.decode_token", side_effect=Exception("Invalid token")):
        response = await tenant_isolation_middleware(mock_request, mock_call_next)
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_token(mock_request, mock_call_next):
    mock_request.headers = {"Authorization": "Bearer expired_token"}

    with patch("app.middleware.tenant_isolation.decode_token", side_effect=Exception("Token expired")):
        response = await tenant_isolation_middleware(mock_request, mock_call_next)
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_decode_token_valueerror_is_handled_cleanly(mock_request, mock_call_next):
    """decode_token converts jwt.ExpiredSignatureError / jwt.InvalidTokenError
    into a plain ValueError, so the middleware must handle ValueError (the type
    actually raised) and return a clean 401 without echoing internal text."""
    mock_request.headers = {"Authorization": "Bearer expired_token"}

    with patch(
        "app.middleware.tenant_isolation.decode_token",
        side_effect=ValueError("Token has expired"),
    ):
        response = await tenant_isolation_middleware(mock_request, mock_call_next)

    assert response.status_code == 401
    body = response.body
    # The raw internal exception text must NOT be reflected back to the client.
    assert b"Token validation failed:" not in body
    assert b"Invalid token" in body


@pytest.mark.asyncio
async def test_decode_token_invalid_valueerror_is_handled_cleanly(mock_request, mock_call_next):
    mock_request.headers = {"Authorization": "Bearer bad_token"}

    with patch(
        "app.middleware.tenant_isolation.decode_token",
        side_effect=ValueError("Invalid token"),
    ):
        response = await tenant_isolation_middleware(mock_request, mock_call_next)

    assert response.status_code == 401
    assert b"Token validation failed:" not in response.body
    assert b"Invalid token" in response.body


@pytest.mark.asyncio
async def test_missing_tenant_db_name(mock_request, mock_call_next):
    mock_request.headers = {"Authorization": "Bearer valid_token"}

    with patch("app.middleware.tenant_isolation.decode_token", return_value={"user_id": 1}):
        response = await tenant_isolation_middleware(mock_request, mock_call_next)
        assert response.status_code == 401
        assert b"Invalid token payload" in response.body


@pytest.mark.asyncio
async def test_missing_user_id(mock_request, mock_call_next):
    mock_request.headers = {"Authorization": "Bearer valid_token"}

    with patch("app.middleware.tenant_isolation.decode_token", return_value={"tenant_db_name": "tenant_test"}):
        response = await tenant_isolation_middleware(mock_request, mock_call_next)
        assert response.status_code == 401
        assert b"Invalid token payload" in response.body


@pytest.mark.asyncio
async def test_valid_token(mock_request, mock_call_next):
    mock_request.headers = {"Authorization": "Bearer valid_token"}

    with patch("app.middleware.tenant_isolation.decode_token", return_value={"user_id": 1, "tenant_db_name": "tenant_test"}):
        result = await tenant_isolation_middleware(mock_request, mock_call_next)

        assert mock_request.state.user_id == 1
        assert mock_request.state.tenant_db_name == "tenant_test"
        assert result is not None


@pytest.mark.asyncio
async def test_malformed_tenant_db_name_is_rejected(mock_request, mock_call_next):
    """A token whose tenant_db_name does not match ^tenant_[a-z0-9]+$ must be
    rejected, so the validated value placed in request.state can be trusted by
    any future route that routes a query to a per-tenant DB."""
    mock_request.headers = {"Authorization": "Bearer valid_token"}

    bad_payload = {"user_id": 1, "tenant_db_name": "tenant_x; DROP DATABASE main"}
    with patch("app.middleware.tenant_isolation.decode_token", return_value=bad_payload):
        response = await tenant_isolation_middleware(mock_request, mock_call_next)

    assert response.status_code == 401
    assert b"Invalid token payload" in response.body
