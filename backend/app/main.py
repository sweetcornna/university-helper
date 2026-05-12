import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from urllib.parse import urlparse
from app.config import settings
from app.core.exceptions import AppException
from app.db.session import get_main_db_connection, _get_main_pool
from app.middleware.tenant_isolation import tenant_isolation_middleware
from app.api.v1 import auth, chaoxing
from app.api.v1.course import cleanup_expired_entries

logger = logging.getLogger(__name__)
_CLEANUP_INTERVAL_SECONDS = 60


async def _periodic_cleanup_loop() -> None:
    while True:
        try:
            cleanup_expired_entries()
        except Exception:
            logger.exception("cleanup_expired_entries iteration failed")
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    title="Unified Signin Platform API",
    description="Multi-tenant signin platform with database isolation",
    version="1.0.0",
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

# HTTPS enforcement middleware
@app.middleware("http")
async def https_redirect_middleware(request: Request, call_next):
    if settings.ENFORCE_HTTPS and request.url.scheme == "http":
        url = request.url.replace(scheme="https")
        return RedirectResponse(url, status_code=301)
    return await call_next(request)

# CSRF protection
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_build_allowed_hosts(settings.CORS_ORIGINS))

# CORS production safety checks
_cors_origins = settings.CORS_ORIGINS or []
if "*" in _cors_origins and getattr(settings, "ENV", "dev") == "production":
    raise RuntimeError("CORS_ORIGINS='*' is not allowed in production")
if getattr(settings, "ENV", "dev") == "production":
    _bad = [o for o in _cors_origins if o.startswith("http://") and "localhost" not in o]
    if _bad:
        raise RuntimeError(f"CORS_ORIGINS in production must use https://: {_bad}")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Tenant isolation middleware
app.middleware("http")(tenant_isolation_middleware)


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

# Course routes
from app.api.v1 import course
app.include_router(course.router, prefix="/api/v1/course", tags=["course"])
app.include_router(chaoxing.router, prefix="/api/v1/chaoxing", tags=["chaoxing"])


@app.get("/")
async def root():
    return {"message": "Unified Signin Platform API"}


@app.get("/health")
def health():
    conn = None
    try:
        conn = get_main_db_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return {"status": "ok", "db": "ok"}
    except Exception as e:
        raise HTTPException(
            status_code=503, detail=f"db unavailable: {type(e).__name__}"
        )
    finally:
        if conn is not None:
            try:
                _get_main_pool().putconn(conn)
            except Exception:
                pass
