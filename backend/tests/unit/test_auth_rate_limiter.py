from typing import Optional

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.middleware.rate_limiter import RateLimiter


def _build_request(client_host: str, forwarded_for: Optional[str] = None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("latin-1")))

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/login",
        "headers": headers,
        "client": (client_host, 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    }
    return Request(scope)


def test_spoofed_left_xff_entry_does_not_change_bucket_key():
    """A client-supplied left XFF hop must NOT be used as the limiter key.

    In production nginx forwards `X-Forwarded-For $proxy_add_x_forwarded_for`,
    which APPENDS the real peer IP to whatever the client sent. So an attacker
    sending `X-Forwarded-For: 1.2.3.4` produces a header `1.2.3.4, <real-ip>`.
    The limiter must key on the rightmost-untrusted entry (the real client),
    not the attacker-chosen left hop — otherwise rotating the spoofed value
    yields unlimited attempts.
    """
    limiter = RateLimiter(requests=2, window=60)

    # All requests come from the same real client (8.8.8.8), but the attacker
    # rotates the spoofed first hop on every request.
    limiter.check_rate_limit(
        _build_request("172.18.0.10", forwarded_for="1.1.1.1, 8.8.8.8")
    )
    limiter.check_rate_limit(
        _build_request("172.18.0.10", forwarded_for="2.2.2.2, 8.8.8.8")
    )

    # Third request: still the same real client. The spoofed left hop changed
    # again, but the bucket key must remain the real client → blocked.
    with pytest.raises(HTTPException) as exc_info:
        limiter.check_rate_limit(
            _build_request("172.18.0.10", forwarded_for="3.3.3.3, 8.8.8.8")
        )
    assert exc_info.value.status_code == 429


def test_xff_chain_with_multiple_trusted_proxies_picks_real_client():
    """Walk past several trusted-proxy hops to the rightmost untrusted entry.

    The first XFF entry here is itself a private/trusted IP that an attacker
    set to try to forge a stable key; the correct behavior is to skip every
    trailing trusted hop AND not key on a leading trusted IP, landing on the
    real client 8.8.4.4.
    """
    limiter = RateLimiter(requests=1, window=60)

    # XFF: <attacker-set trusted-looking IP>, <real client>, <nginx hops...>
    fwd = "10.0.0.99, 8.8.4.4, 172.18.0.5, 172.18.0.6"
    limiter.check_rate_limit(_build_request("172.18.0.10", forwarded_for=fwd))
    with pytest.raises(HTTPException) as exc_info:
        limiter.check_rate_limit(_build_request("172.18.0.10", forwarded_for=fwd))
    assert exc_info.value.status_code == 429

    # A DIFFERENT real client (different rightmost-untrusted entry) gets its own
    # bucket and is NOT immediately blocked, even though the leading trusted hop
    # and trailing nginx hops are identical.
    other = "10.0.0.99, 8.8.8.8, 172.18.0.5, 172.18.0.6"
    limiter.check_rate_limit(_build_request("172.18.0.10", forwarded_for=other))


def test_rate_limiter_uses_forwarded_client_ip_when_present():
    limiter = RateLimiter(requests=5, window=60)

    for _ in range(5):
        limiter.check_rate_limit(
            _build_request("172.18.0.10", forwarded_for="8.8.8.8")
        )

    for _ in range(5):
        limiter.check_rate_limit(
            _build_request("172.18.0.10", forwarded_for="8.8.4.4")
        )


def test_rate_limiter_blocks_after_forwarded_client_exceeds_limit():
    limiter = RateLimiter(requests=2, window=60)
    request = _build_request("172.18.0.10", forwarded_for="8.8.8.8")

    limiter.check_rate_limit(request)
    limiter.check_rate_limit(request)

    with pytest.raises(HTTPException) as exc_info:
        limiter.check_rate_limit(request)

    assert exc_info.value.status_code == 429


def test_request_at_exact_limit_boundary_is_allowed():
    """The Nth request (where N == limit) should succeed; N+1 should be blocked."""
    limiter = RateLimiter(requests=5, window=60)
    request = _build_request("10.0.0.1")

    # Requests 1 through 5 should all succeed
    for _ in range(5):
        limiter.check_rate_limit(request)

    # The 6th request should be blocked
    with pytest.raises(HTTPException) as exc_info:
        limiter.check_rate_limit(request)

    assert exc_info.value.status_code == 429


def test_request_allowed_after_window_expires():
    """After the rate-limit window expires, requests should be allowed again."""
    from unittest.mock import patch
    from datetime import datetime, timedelta

    limiter = RateLimiter(requests=2, window=60)
    request = _build_request("10.0.0.2")

    # Exhaust the limit
    limiter.check_rate_limit(request)
    limiter.check_rate_limit(request)

    with pytest.raises(HTTPException):
        limiter.check_rate_limit(request)

    # Simulate time passing beyond the window
    future_time = datetime.now() + timedelta(seconds=61)
    with patch("app.middleware.rate_limiter.datetime") as mock_dt:
        mock_dt.now.return_value = future_time
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        # After window expires, request should succeed
        limiter.check_rate_limit(request)


def test_cleanup_expired_removes_stale_entries():
    """_cleanup_expired should remove entries whose window has passed."""
    from unittest.mock import patch
    from datetime import datetime, timedelta

    limiter = RateLimiter(requests=5, window=60)

    # Manually populate the cache with entries that are already expired
    past_time = datetime.now() - timedelta(seconds=120)
    limiter._cache["expired_client_1"] = (3, past_time)
    limiter._cache["expired_client_2"] = (5, past_time)

    # Add one fresh entry
    fresh_time = datetime.now()
    limiter._cache["fresh_client"] = (1, fresh_time)

    assert len(limiter._cache) == 3

    limiter._cleanup_expired()

    assert "expired_client_1" not in limiter._cache
    assert "expired_client_2" not in limiter._cache
    assert "fresh_client" in limiter._cache
    assert len(limiter._cache) == 1
