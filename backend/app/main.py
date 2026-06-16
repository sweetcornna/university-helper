import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.v1 import auth, chaoxing
from app.api.v1.course import cleanup_expired_entries
from app.api.v1.metrics import record_request
from app.api.v1.metrics import router as metrics_router
from app.config import settings
from app.core.credential_crypto import init_cipher
from app.core.exceptions import AppException
from app.core.logging_setup import configure_logging
from app.core.tracing import configure_tracing
from app.db.session import get_db_session
from app.middleware.tenant_isolation import tenant_isolation_middleware

logger = logging.getLogger(__name__)
_CLEANUP_INTERVAL_SECONDS = 60


def _validate_runtime_settings() -> None:
    """All "production gates" in one place — called from lifespan."""
    origins = settings.CORS_ORIGINS or []
    env = getattr(settings, "ENV", "dev")
    if env == "production":
        if "*" in origins:
            raise RuntimeError("CORS_ORIGINS='*' is not allowed in production")
        bad = [o for o in origins if o.startswith("http://") and "localhost" not in o]
        if bad:
            raise RuntimeError(f"CORS_ORIGINS in production must use https://: {bad}")


async def _periodic_cleanup_loop() -> None:
    while True:
        try:
            cleanup_expired_entries()
        except Exception:
            logger.exception("cleanup_expired_entries iteration failed")
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    _validate_runtime_settings()
    # Fail fast at startup if the credential cipher cannot be initialized
    # (in production this raises when CREDENTIAL_ENCRYPTION_KEY is missing).
    init_cipher()
    # Opt-in OTel tracing when OTEL_EXPORTER_OTLP_ENDPOINT is set.
    configure_tracing(app)
    app.state.cleanup_task = asyncio.create_task(_periodic_cleanup_loop())
    try:
        yield
    finally:
        task = getattr(app.state, "cleanup_task", None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="University Helper API",
    description="Multi-tenant campus helper platform with database-per-tenant isolation",
    version="1.2.0",
    docs_url="/docs" if settings.DOCS_ENABLED else None,
    redoc_url="/redoc" if settings.DOCS_ENABLED else None,
    openapi_url="/openapi.json" if settings.DOCS_ENABLED else None,
    lifespan=lifespan,
)


def _build_allowed_hosts(origins: list[str]) -> list[str]:
    hosts = {"localhost", "127.0.0.1"}
    for origin in origins:
        value = str(origin or "").strip()
        if not value:
            continue
        parsed = urlparse(value if "://" in value else f"http://{value}")
        host = parsed.hostname
        if host:
            hosts.add(host)
    return sorted(hosts)


# NOTE on middleware ordering:
# Starlette runs middleware in REVERSE registration order — the LAST registered
# is the OUTERMOST. We need, from outer to inner:
#     CORS -> TrustedHost -> security_headers -> https_redirect -> metrics -> tenant_isolation -> route
# so that (a) CORS is outermost and wraps EVERY response — including the bare 401
# that tenant_isolation short-circuits on a missing/expired token — giving it the
# Access-Control-Allow-Origin header so the browser can READ the 401 and the SPA's
# 401 handler fires (otherwise session-expiry looks like a hung app); and (b)
# request_metrics sits OUTSIDE tenant_isolation so it still counts those 401s.
# Therefore tenant_isolation is registered FIRST (innermost) and CORS LAST.

# Innermost middleware: registered first so its short-circuit responses still
# travel back out through request_metrics (counted) and CORS (CORS headers added).
app.middleware("http")(tenant_isolation_middleware)


@app.middleware("http")
async def request_metrics_middleware(request: Request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/metrics"):
        route = request.scope.get("route")
        template = getattr(route, "path", None) or request.url.path
        record_request(template, response.status_code)
    return response


# HTTPS enforcement
@app.middleware("http")
async def https_redirect_middleware(request: Request, call_next):
    if settings.ENFORCE_HTTPS and request.url.scheme == "http":
        url = request.url.replace(scheme="https")
        return RedirectResponse(url, status_code=301)
    return await call_next(request)


# Security response headers (defense-in-depth — nginx also sets these).
@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "geolocation=(), microphone=(), camera=(), payment=()",
    )
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    )
    if settings.ENFORCE_HTTPS:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
    return response


# Host-header validation (NOT CSRF — CSRF would need cookie-based auth + token).
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=_build_allowed_hosts(settings.CORS_ORIGINS),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
# (tenant_isolation_middleware is registered ABOVE as the innermost middleware so
# its short-circuit 401 still passes back out through CORS — see the ordering note.)


# Global exception handlers
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    return JSONResponse(
        status_code=getattr(exc, "status_code", 400),
        content={
            "code": exc.__class__.__name__,
            "message": str(exc),
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception", extra={"path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={"code": "InternalServerError", "message": "Internal server error"},
    )


# Routes
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])

from app.api.v1 import course

app.include_router(course.router, prefix="/api/v1/course", tags=["course"])
app.include_router(chaoxing.router, prefix="/api/v1/chaoxing", tags=["chaoxing"])
app.include_router(metrics_router, tags=["metrics"])


@app.get("/")
async def root():
    return {"message": "University Helper API"}


@app.get("/health")
def health():
    cleanup_task = getattr(app.state, "cleanup_task", None)
    cleanup_alive = bool(cleanup_task and not cleanup_task.done())
    try:
        with get_db_session() as conn:
            conn.autocommit = True  # avoid an unnecessary COMMIT round-trip
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
            finally:
                # Always reset autocommit before the connection is returned to
                # the pool. If SELECT 1 raised, skipping this reset would leave
                # the pooled connection in autocommit=True, silently breaking
                # the transactional contract (commit/rollback become no-ops)
                # for the next caller that reuses it.
                conn.autocommit = False
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"db unavailable: {type(e).__name__}")
    status = "ok" if cleanup_alive else "degraded"
    return {"status": status, "db": "ok", "cleanup_task": "alive" if cleanup_alive else "dead"}
