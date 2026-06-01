import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import PUBLIC_ROUTES
from app.core.security import decode_token
from app.db.session import _TENANT_NAME_RE

logger = logging.getLogger(__name__)


def _is_valid_tenant_db_name(name: object) -> bool:
    """Validate a tenant DB name against the canonical ^tenant_[a-z0-9]+$
    pattern (single source of truth in app.db.session)."""
    return isinstance(name, str) and bool(_TENANT_NAME_RE.match(name))

# Public-route set is built once at import. Also allow /docs + /redoc subroutes
# without re-listing them in app/config.py.
#
# IMPORTANT: /metrics is matched EXACTLY (added to _PUBLIC_PATHS), not via a
# startswith prefix. Swagger (/docs, /redoc) legitimately has child paths
# (/docs/oauth2-redirect, etc.), but /metrics is a single endpoint — a prefix
# match would silently make any future "/metrics*" route public. The /metrics
# endpoint enforces its own optional bearer-token guard (METRICS_TOKEN).
_PUBLIC_PATHS = frozenset(
    [*(route.rstrip("/") or "/" for route in PUBLIC_ROUTES), "/metrics"]
)
_PUBLIC_PREFIXES = ("/docs", "/redoc")


async def tenant_isolation_middleware(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    if path in _PUBLIC_PATHS or any(path.startswith(p) for p in _PUBLIC_PREFIXES):
        return await call_next(request)

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return JSONResponse(status_code=401, content={"detail": "Missing token"})

    parts = auth_header.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return JSONResponse(status_code=401, content={"detail": "Invalid authorization header format"})

    token = parts[1].strip()
    if not token:
        return JSONResponse(status_code=401, content={"detail": "Missing token"})

    try:
        payload = decode_token(token)
    except ValueError as exc:
        # decode_token (app/core/security.py) catches jwt.ExpiredSignatureError
        # and jwt.InvalidTokenError internally and re-raises them as a plain
        # ValueError. So ValueError is the type that actually reaches here —
        # the previous jwt.* except branches were dead code. We return a
        # CONSTANT message and never echo the raw exception text back to the
        # client (which could leak internal crypto/JWT state).
        logger.debug("tenant_isolation: token rejected (%s)", exc)
        return JSONResponse(status_code=401, content={"detail": "Invalid token"})
    except Exception as exc:  # pragma: no cover - defensive catch-all
        logger.warning("tenant_isolation: unexpected token error (%s)", exc)
        return JSONResponse(status_code=401, content={"detail": "Invalid token"})

    tenant_db_name = payload.get("tenant_db_name")
    user_id = payload.get("user_id")

    if not tenant_db_name or not user_id:
        return JSONResponse(status_code=401, content={"detail": "Invalid token payload"})

    # DESIGN NOTE (per-tenant DB isolation): today the data path is main-DB-only
    # — routes/services scope per-user state by `user_id` in process memory and
    # the shared `users` table, NOT by routing each query to a `tenant_<name>`
    # database. `request.state.tenant_db_name` is therefore not yet consumed by
    # any route. We keep setting it (the tenant DBs are provisioned at
    # registration) but VALIDATE it here against the canonical tenant-name
    # pattern so that if/when a route starts trusting request.state to pick a
    # DB, the value is already proven safe (e.g. cannot inject a crafted DB
    # name). This closes the latent foot-gun the value would otherwise be.
    if not _is_valid_tenant_db_name(tenant_db_name):
        logger.warning("tenant_isolation: rejected malformed tenant_db_name in token")
        return JSONResponse(status_code=401, content={"detail": "Invalid token payload"})

    request.state.tenant_db_name = tenant_db_name
    request.state.user_id = user_id

    response = await call_next(request)
    return response
