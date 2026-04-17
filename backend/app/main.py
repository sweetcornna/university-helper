import asyncio
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import RedirectResponse
from urllib.parse import urlparse
from app.config import settings
from app.middleware.tenant_isolation import tenant_isolation_middleware
from app.api.v1 import auth, chaoxing
from app.api.v1.course import cleanup_expired_entries

logger = logging.getLogger(__name__)
_CLEANUP_INTERVAL_SECONDS = 60

app = FastAPI(
    title="Unified Signin Platform API",
    description="Multi-tenant signin platform with database isolation",
    version="1.0.0",
    docs_url="/docs" if settings.DOCS_ENABLED else None,
    redoc_url="/redoc" if settings.DOCS_ENABLED else None,
    openapi_url="/openapi.json" if settings.DOCS_ENABLED else None,
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

# Routes
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])

# Course routes
from app.api.v1 import course
app.include_router(course.router, prefix="/api/v1/course", tags=["course"])
app.include_router(chaoxing.router, prefix="/api/v1/chaoxing", tags=["chaoxing"])


async def _periodic_cleanup_loop() -> None:
    while True:
        try:
            cleanup_expired_entries()
        except Exception:
            logger.exception("cleanup_expired_entries iteration failed")
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)


@app.on_event("startup")
async def _start_cleanup_task() -> None:
    app.state.cleanup_task = asyncio.create_task(_periodic_cleanup_loop())


@app.on_event("shutdown")
async def _stop_cleanup_task() -> None:
    task = getattr(app.state, "cleanup_task", None)
    if task is None:
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@app.get("/")
async def root():
    return {"message": "Unified Signin Platform API"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
