"""Outbound URL validation for user-configured answer providers.

Answer-provider endpoints are supplied as part of a course task, so they must
not be allowed to turn the worker into a general-purpose SSRF client.  The
checks in this module intentionally use only the standard library and are
performed both when a task is admitted and immediately before each request.
The latter is a defensive re-check for DNS changes between task admission and
the request.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Mapping
from urllib.parse import urlsplit

INVALID_ENDPOINT_CONFIG_DETAIL = "Invalid answer-provider endpoint configuration"
_ALLOWED_SCHEMES = frozenset({"http", "https"})
_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "metadata",
        "metadata.google.internal",
        "metadata.azure.com",
        "instance-data.ec2.internal",
    }
)


class UnsafeEndpointError(ValueError):
    """Raised when a configured endpoint or proxy is not a public HTTP URL."""

    def __init__(self) -> None:
        # Do not include the user-supplied host or URL in the exception.  The
        # same message is safe to expose from the API's 4xx error response.
        super().__init__(INVALID_ENDPOINT_CONFIG_DETAIL)


def _is_public_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an address is globally routable for this use case."""
    # Keep IPv4-mapped IPv6 literals out of the allowlist entirely.  Treating
    # ``::ffff:8.8.8.8`` as an ordinary public IPv6 address creates an address
    # family ambiguity for HTTP clients and makes the policy harder to audit.
    if getattr(address, "ipv4_mapped", None) is not None:
        return False
    return (
        address.is_global
        and not address.is_loopback
        and not address.is_private
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_unspecified
        and not address.is_reserved
    )


def _resolved_addresses(hostname: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for info in infos:
            try:
                sockaddr = info[4]
                address = ipaddress.ip_address(sockaddr[0])
            except Exception as exc:
                raise UnsafeEndpointError from exc
            addresses.append(address)
        if not addresses:
            raise UnsafeEndpointError
        return addresses
    except UnsafeEndpointError:
        raise
    except Exception as exc:
        raise UnsafeEndpointError from exc


def assert_public_endpoint(url: object) -> str:
    """Validate and return a normalized public HTTP(S) endpoint.

    All resolved addresses must be globally routable.  Rejecting the entire
    hostname when one DNS answer is private avoids selecting a safe-looking
    address from a mixed or rebinding answer set.
    """
    if not isinstance(url, str):
        raise UnsafeEndpointError
    normalized = url.strip()
    if not normalized:
        raise UnsafeEndpointError
    # Backslashes are not valid in an HTTP authority, but requests and URL
    # parsers can interpret them differently.  Reject them before parsing so
    # an authority such as ``127.0.0.1:8080\\@public.example`` cannot be
    # validated as one host and requested as another.
    if "\\" in normalized:
        raise UnsafeEndpointError

    try:
        parsed = urlsplit(normalized)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        # Accessing .port validates malformed or out-of-range ports.
        _ = parsed.port
        # Userinfo is not needed by any provider and may hide the actual
        # destination from callers that parse the URL differently.  This also
        # rejects an empty userinfo marker (``http://@host``).
        if "@" in parsed.netloc or parsed.username is not None or parsed.password is not None:
            raise UnsafeEndpointError
    except UnsafeEndpointError:
        raise
    except Exception as exc:
        raise UnsafeEndpointError from exc

    if scheme not in _ALLOWED_SCHEMES or not hostname:
        raise UnsafeEndpointError

    normalized_hostname = hostname.rstrip(".").lower()
    if not normalized_hostname or normalized_hostname in _BLOCKED_HOSTNAMES:
        raise UnsafeEndpointError

    try:
        literal = ipaddress.ip_address(normalized_hostname)
    except UnicodeError as exc:
        raise UnsafeEndpointError from exc
    except ValueError:
        literal = None
    except Exception as exc:
        raise UnsafeEndpointError from exc

    addresses = [literal] if literal is not None else _resolved_addresses(normalized_hostname)
    if any(address is None or not _is_public_ip(address) for address in addresses):
        raise UnsafeEndpointError
    return normalized


def is_public_endpoint(url: object) -> bool:
    """Return whether ``url`` passes the public endpoint policy."""
    try:
        assert_public_endpoint(url)
    except Exception:
        return False
    return True


def _configured_value(config: Mapping[str, object], key: str) -> object | None:
    value = config.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise UnsafeEndpointError
    if not value.strip():
        return None
    return value


def validate_tiku_config(config: object) -> None:
    """Validate every user-controlled URL used by selected answer providers.

    A missing SiliconFlow endpoint intentionally remains valid because that
    provider has a fixed public default.  TikuAdapter and AI have no safe
    default, so selecting either requires a non-empty endpoint.  Proxy values
    are optional but, when present, use the same public HTTP(S) policy.
    """
    if config is None:
        return
    if not isinstance(config, Mapping):
        raise UnsafeEndpointError

    providers = {name.strip() for name in str(config.get("provider") or "").split(",") if name.strip()}

    if "TikuAdapter" in providers:
        adapter_url = _configured_value(config, "url")
        if adapter_url is None:
            raise UnsafeEndpointError
        assert_public_endpoint(adapter_url)
    elif _configured_value(config, "url") is not None:
        # A URL supplied alongside another provider is still user input; reject
        # it rather than leaving a future provider-selection change unguarded.
        assert_public_endpoint(config["url"])

    if "AI" in providers:
        ai_endpoint = _configured_value(config, "endpoint")
        if ai_endpoint is None:
            raise UnsafeEndpointError
        assert_public_endpoint(ai_endpoint)
    elif _configured_value(config, "endpoint") is not None:
        assert_public_endpoint(config["endpoint"])

    if "siliconflow_endpoint" in config:
        siliconflow_endpoint = _configured_value(config, "siliconflow_endpoint")
        if siliconflow_endpoint is None:
            raise UnsafeEndpointError
        assert_public_endpoint(siliconflow_endpoint)

    proxy = _configured_value(config, "http_proxy")
    if proxy is not None:
        assert_public_endpoint(proxy)
