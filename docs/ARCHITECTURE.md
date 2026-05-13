# Architecture

University Helper is a single-region, multi-tenant FastAPI service that
automates Chinese e-learning workflows (Chaoxing sign-in, Fanya course tasks,
Zhihuishu). The client is a Vite/React SPA served by a host-level nginx that
also proxies the API.

## Topology

```
            ┌───────────────────────────────────────────────┐
            │                Cloudflare                     │
            └──────────────────────┬────────────────────────┘
                                   │  HTTPS
            ┌──────────────────────▼────────────────────────┐
            │  host nginx (shuake.cornna.xyz)               │
            │  - serves /opt/university-helper/frontend/dist│
            │  - rate-limits /api/v1/auth/login (5r/min)    │
            │  - rate-limits /api/ (20r/s)                  │
            │  - CSP / HSTS / Permissions-Policy headers    │
            └──────────────────────┬────────────────────────┘
                       │
              /api/* proxy_pass
                       │
            ┌──────────▼────────────────────────────────────┐
            │  docker-compose: shuake-easy-learning-app     │
            │  ─ FastAPI 0.115 (uvicorn --workers 1 *)      │
            │  ─ non-root uid 10001, read-only rootfs       │
            │  ─ tini as PID1                               │
            └──────────┬────────────────────────────────────┘
                       │  psycopg2 pools
            ┌──────────▼────────────────────────────────────┐
            │  docker-compose: shuake-easy-learning-db      │
            │  ─ Postgres 15-alpine (tuned)                 │
            │  ─ main_db  + tenant_<username>  + tenant_template │
            └───────────────────────────────────────────────┘

  * --workers 1 is enforced today because chaoxing session state
    (ChaoxingSigninManager._clients, QR sessions, etc.) lives in-process.
    Lifting this requires externalizing that state to Redis or Postgres
    JSONB — tracked as a future change in CHANGELOG.
```

## Components

### Frontend — React + Vite

- React 18 + React Router 6, Tailwind tokens (light/dark CSS-vars).
- Routes are lazy-loaded; `BaiduMapPickerModal` and other heavy widgets are dynamic-imported only when used.
- Global `ErrorBoundary`, `PrivateRoute` guard, route-level `RouteFallback` skeleton, `AuthExpiredListener` that reacts to 401s.
- `utils/api.js` is the single fetch wrapper — it parses errors, emits an `auth:expired` event on authenticated 401s, and surfaces `ApiError` to callers.
- ESLint with `react`, `react-hooks`, `jsx-a11y`; Prettier; Vitest + Testing-Library.

### Backend — FastAPI

- `app/main.py` wires middleware in order: HTTPS-redirect → security headers → TrustedHost → CORS → tenant-isolation → request-metrics counter.
- `app/middleware/tenant_isolation.py` validates JWTs and rejects requests whose `tenant_db_name` claim doesn't match the user record. `PUBLIC_ROUTES` (see `app/config.py`) is the allow-list for unauthenticated endpoints.
- `app/middleware/rate_limiter.py` provides a Postgres-backed counter with an in-memory fallback; nginx adds an outer per-IP cap.
- `app/services/auth_service.py` owns registration/login; all sync DB work is offloaded via `asyncio.to_thread` so the event loop stays responsive.
- Background work: a single asyncio task in lifespan runs `cleanup_expired_entries()` every 60s.

### Persistence — PostgreSQL

- **`main_db`** holds the `users` table only (id, username, email, password_hash, tenant_db_name, timestamps).
- **`tenant_template`** is the prototype DB that every per-user tenant DB clones from (`CREATE DATABASE … TEMPLATE tenant_template`).
- **`tenant_<username>`** — one database per user, holding that user's todos/sessions/attachments. Cross-tenant data leaks are physically impossible because each request reconnects to the user's own DB.
- Connection pools: a main-DB pool (5–30) + an LRU map of tenant pools (2–10 each, max 100 pools). Eviction is refcounted, so a pool with checked-out conns is never closed.
- Migrations: Alembic wired (`backend/alembic`), idempotent baselines using `IF NOT EXISTS`. `alembic upgrade head` is safe to run repeatedly.

### Reverse proxy — nginx

- Static assets `Cache-Control: public, immutable` (hashed filenames from Vite).
- SPA fallback to `/index.html` with `Cache-Control: no-cache`.
- Per-IP rate-limit zones: `api_zone` (20r/s, burst 40) and `login_zone` (5r/min, burst 5).
- Per-IP connection cap (`conn_zone`, 50) to soak slowloris.
- Strict CSP via `map` so HTML and JSON responses get appropriate policies.

## Auth

JWT in `Authorization: Bearer …`, signed HS256. Claims: `user_id`, `tenant_db_name`, `iat`, `nbf`, `exp`, `jti`. Tokens are short-lived (30 min default); the `jti` gives us a revocation surface when we want to add a blacklist. Passwords use bcrypt with `BCRYPT_ROUNDS` clamped to 4..15. Third-party platform credentials (Chaoxing/Zhihuishu) are Fernet-encrypted before storage; the cipher fails fast at startup in production if `CREDENTIAL_ENCRYPTION_KEY` is missing.

## Observability

- `/health` checks DB + cleanup-task liveness, returns `degraded` if the periodic task is dead.
- `/metrics` exposes a minimal Prometheus exposition (process uptime + request counters by path × status bucket). Swap for `prometheus-fastapi-instrumentator` when full SLOs land.
- Logging: stdlib `logging` (configured via `app/core/logging_setup.py`), `LOG_FORMAT=json` switches to single-line JSON suitable for log shippers; loguru records are bridged into the same sink.

## Deployment

- One docker-compose stack per environment: `docker-compose.server.yml` is the base; `docker-compose.staging.yml` is an overlay that swaps ports and volumes for parallel staging on the same host.
- Image is published from `Dockerfile.server` — multi-stage build, non-root runtime, capability drop, `no-new-privileges`.
- `scripts/hotfix_publish.sh` syncs single files into a running prod container for fast iteration; prefers SSH-key auth over sshpass.
- `scripts/db_backup.sh` runs `pg_dumpall` and encrypts via `age` when a recipient is configured; refuses to write plaintext `.env` snapshots unless `ALLOW_UNENCRYPTED=1`.

## Future directions

### Foundations already in place
- **`app/core/session_store.py`** — pluggable key/value store with `InMemorySessionStore` (default) and `RedisSessionStore` (selected via `REDIS_URL`). To unlock `--workers >1`, port `ChaoxingSigninManager._clients`/`_qr_sessions` to read/write through `get_session_store()`. The compose stack already ships a profile-gated `redis` service.
- **`scripts/migrate_tenants.py`** — `alembic upgrade head` per tenant DB. Run on every deploy that touches `templates/tenant_template.sql`.
- **OpenTelemetry** — `app/core/tracing.py` activates when `OTEL_EXPORTER_OTLP_ENDPOINT` is set and the SDK is installed. Wires FastAPI + psycopg2 + requests + httpx instrumentors.
- **TypeScript migration** — `frontend/tsconfig.json` with `allowJs: true` lets new files land as `.tsx`/`.ts` alongside the existing `.jsx`. Shared API types live in `frontend/src/types/api.d.ts`.
- **PWA** — `vite-plugin-pwa` generates the service worker; `/api/*` is `NetworkOnly` so tenant-scoped data is never cached.

### Still requires a design pass
- **Async DB.** Migrating every service from psycopg2 sync calls + `asyncio.to_thread` to asyncpg + SQLAlchemy 2.0 async is a large blast radius; needs a per-module port plan with integration coverage before flipping.
- **Page splitting.** `ChaoxingSignin.jsx` and `Zhihuishu.jsx` already have partial subfolders (`chaoxing-signin/`, etc.) — the remaining tabs/hooks should move out incrementally with snapshot/UI tests so behavior doesn't regress.
