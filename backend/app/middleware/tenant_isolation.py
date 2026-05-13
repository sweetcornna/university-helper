import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from app.core.security import decode_token
from app.config import PUBLIC_ROUTES

# Public-route set is built once at import. Also allow the metrics endpoint
# and any /docs subroutes without re-listing them in app/config.py.
_PUBLIC_PATHS = frozenset(route.rstrip("/") or "/" for route in PUBLIC_ROUTES)
_PUBLIC_PREFIXES = ("/docs", "/redoc", "/metrics")


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
    except jwt.ExpiredSignatureError:
        return JSONResponse(status_code=401, content={"detail": "Token has expired"})
    except jwt.InvalidTokenError as e:
        return JSONResponse(status_code=401, content={"detail": f"Invalid token: {str(e)}"})
    except Exception as e:
        return JSONResponse(status_code=401, content={"detail": f"Token validation failed: {str(e)}"})

    tenant_db_name = payload.get("tenant_db_name")
    user_id = payload.get("user_id")

    if not tenant_db_name or not user_id:
        return JSONResponse(status_code=401, content={"detail": "Invalid token payload"})

    request.state.tenant_db_name = tenant_db_name
    request.state.user_id = user_id

    response = await call_next(request)
    return response
