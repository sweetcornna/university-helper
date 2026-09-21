# Architecture

University Helper is a single-region, multi-tenant FastAPI service that
automates Chinese e-learning workflows (Chaoxing sign-in, Fanya course tasks,
Zhihuishu). The client is a Vite/React SPA served by a host-level nginx that
also proxies the API. The same backend also ships inside a desktop app, which
runs it for one local user on SQLite (see [Desktop edition](#desktop-edition)).

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

### Frontend: React + Vite

- React 18 + React Router 6, Tailwind tokens (light/dark CSS-vars).
- Routes are lazy-loaded. `BaiduMapPickerModal` and other heavy widgets are imported dynamically when first used.
- A global `ErrorBoundary`, the `PrivateRoute` guard, a route-level `RouteFallback` skeleton, and an `AuthExpiredListener` that reacts to 401s.
- `utils/api.js` is the only fetch wrapper. It parses errors, emits an `auth:expired` event on authenticated 401s and throws `ApiError` to callers. When a 5xx response carries no useful message, or the network request itself fails, it replaces the error with a readable Chinese message instead of showing "Internal server error".
- `RuntimeProfileProvider` asks `/api/v1/runtime` whether the backend needs a login. The desktop build does not, so the login and register pages are skipped there.
- `UpdateNotice` (server edition only) shows administrators a dialog when a newer release exists. See [Update notice](#update-notice).
- ESLint with `react`, `react-hooks`, `jsx-a11y`; Prettier; Vitest + Testing-Library.

### Backend: FastAPI

- `app/main.py` sets up the middleware. A request passes through them from the outside in: CORS, then `AllowedHostsMiddleware` (Host header check), security headers, HTTPS redirect, the request-metrics counter, and finally tenant isolation. The desktop profile does not register tenant isolation.
- `app/middleware/allowed_hosts.py` accepts `localhost`, `127.0.0.1`, every host named in `CORS_ORIGINS`, and the extra names in `ALLOWED_HOSTS`. Other hosts get a JSON 400 with code `InvalidHost` that names the `ALLOWED_HOSTS` setting. Production refuses to start with `ALLOWED_HOSTS=*`.
- `app/middleware/tenant_isolation.py` validates JWTs and rejects requests whose `tenant_db_name` claim doesn't match the user record. `PUBLIC_ROUTES` (see `app/config.py`) is the allow-list for unauthenticated endpoints.
- `app/middleware/rate_limiter.py` provides a Postgres-backed counter with an in-memory fallback; nginx adds an outer per-IP cap.
- `app/services/auth_service.py` owns registration and login, and runs all sync DB work through `asyncio.to_thread` so the event loop stays free. Failures while creating a tenant database become typed errors instead of a bare 500: `DatabaseNotInitializedError` and `TenantProvisioningError`, both 503 with a message that says what to fix. A busy `tenant_template` (for example during `pg_dumpall`) is retried with backoff of 0.5, 1, 2 and 4 seconds first.
- In the desktop profile every `/api/v1/auth/*` route answers 409 `LocalProfileAuthUnavailable`.
- Background tasks started in lifespan:
  - `cleanup_expired_entries()` every 60s.
  - The schema bootstrap (server profile, Postgres, `DB_AUTO_BOOTSTRAP=true`). It runs once at startup and retries every 5 s for up to 5 minutes while Postgres is still starting.
  - The update check (server profile, `UPDATE_CHECK_ENABLED=true`). The first check runs 30 s after startup, then every `UPDATE_CHECK_INTERVAL_SECONDS` (6 hours by default).

### Persistence: PostgreSQL

- `main_db` holds only the `users` table (id, username, email, password_hash, tenant_db_name, timestamps).
- `tenant_template` is the prototype DB that every per-user tenant DB is cloned from (`CREATE DATABASE … TEMPLATE tenant_template`). It is marked `IS_TEMPLATE`, so Postgres refuses to drop it. Registration rejects a short list of reserved usernames (`template`, `postgres`, `root` and a few more).
- `tenant_<username>` is one database per user, holding that user's todos, sessions and attachments. Each request connects to the user's own database, so a query cannot reach another tenant's data.
- Connection pools: a main-DB pool (5 to 30 connections) + an LRU map of tenant pools (2 to 10 each, max 100 pools). Eviction is refcounted, so a pool with checked-out connections is never closed. Connections use TCP keepalives and a 5 s connect timeout. A connection that fails with a connection error is closed instead of returned to the pool, and a closed connection found at checkout is replaced.
- Schema self-repair (`app/db/bootstrap.py`): the Postgres init scripts in `database/` only run on an empty data volume, and they can fail silently (CRLF line endings from a Windows checkout, a reused half-initialized volume). At startup the app checks for the `users` table and `tenant_template` and rebuilds whichever is missing from the SQL files that `Dockerfile.server` copies into the image. A Postgres advisory lock keeps several app processes from doing this at once. If registration still finds the template missing, it tries the same repair once before returning 503.
- Migrations: Alembic wired (`backend/alembic`) with independent `main_db` and
  `tenant_db` heads. Apply the shared database branch from `backend/` with
  `alembic upgrade main_db@head`; apply the tenant branch to all tenant
  databases from the repository root with `python scripts/migrate_tenants.py`.
  Baselines use `IF NOT EXISTS` and are safe to run repeatedly.

### Reverse proxy: nginx

- Static assets `Cache-Control: public, immutable` (hashed filenames from Vite).
- SPA fallback to `/index.html` with `Cache-Control: no-cache`.
- Per-IP rate-limit zones: `api_zone` (20r/s, burst 40) and `login_zone` (5r/min, burst 5).
- A per-IP connection cap (`conn_zone`, 50) limits slowloris-style attacks.
- Strict CSP via `map` so HTML and JSON responses get appropriate policies.

## Auth

JWT in `Authorization: Bearer …`, signed HS256. Claims: `user_id`, `tenant_db_name`, `iat`, `nbf`, `exp`, `jti`. Tokens are short-lived (30 min default), and the `jti` claim leaves room for a revocation list later. Passwords use bcrypt with `BCRYPT_ROUNDS` clamped to 4..15. Third-party platform credentials (Chaoxing/Zhihuishu) are Fernet-encrypted before storage; in production the cipher fails at startup if `CREDENTIAL_ENCRYPTION_KEY` is missing.

## Update notice

The server container has no Docker socket, so it cannot upgrade itself. Instead `app/services/update_check.py` polls the GitHub Releases API (`UPDATE_CHECK_URL`) with a 5 s timeout and ignores drafts and prereleases. When a check fails, the last result is kept and the notice simply does not appear.

`GET /api/v1/system/update` returns the current and latest version, the release notes and the commands that upgrade an installation (`deploy_server.sh --tag <version> -y` and the PowerShell equivalent). Only administrators get an answer; everyone else gets 403. `app/services/admin.py` decides who is an administrator: the accounts listed in `ADMIN_EMAILS` (comma separated, case-insensitive), or, when that is empty, the account with the smallest `users.id`, which is normally whoever registered first.

The frontend asks this endpoint after login. Administrators can hide the dialog for 24 hours or skip that version; the choice is stored in the browser's `localStorage`.

## Desktop edition

The desktop app is a Tauri shell (`frontend/src-tauri`, Rust) plus the backend frozen with PyInstaller as a sidecar binary called `uh-backend`. `backend/desktop_entry.py` sets `PROFILE=local` and `STORAGE_BACKEND=sqlite`, keeps its secrets and database in the per-user app-data directory, binds a free loopback port and serves the built SPA itself.

Stopping the backend reliably takes a few layers, because a PyInstaller onefile binary runs as two processes (a bootloader and the Python child):

- On exit the shell stops the whole sidecar process tree. On macOS and Linux it sends SIGTERM, waits up to 1.5 s, then kills it; on Windows it runs `taskkill /T /F`.
- The shell passes its own PID in `UH_PARENT_PID`. The backend checks once a second and exits when that process is gone (on macOS and Linux, also when it has been re-parented). On macOS and Linux it sends itself SIGTERM and forces the exit after 5 s; on Windows it exits immediately.
- The backend records itself in `uh-backend.pid` in the app-data directory. At startup it stops a backend left over from an earlier run, but only if that process is still the sidecar and its desktop parent is gone. Frozen builds on macOS and Linux also stop sidecar processes that were re-parented to init.
- The Windows NSIS installer runs `taskkill /F /T /IM uh-backend.exe` before installing or uninstalling, so an old backend cannot lock files that the update needs to replace.

Auto-update uses `tauri-plugin-updater`. About 8 s after launch the shell checks `releases/latest/download/latest.json` (20 s timeout). If a newer version exists it asks first, in a dialog titled 学道有新版本 that shows the version and up to 600 characters of release notes. It downloads and installs only after the user picks 现在更新, then stops the sidecar and restarts the app. Shell events go to `desktop.log` in the app log directory, rotated at 1 MB.

## Observability

- `/health` checks the DB and whether the cleanup task is alive. It returns 503 when the database does not answer and `degraded` when the periodic task is dead. On the server with Postgres it also reports `schema`: `ok`, `missing_users`, `missing_tenant_template` or `unknown`. Anything other than `ok` makes the status `degraded`, but the response is still 200.
- `/metrics` exposes a minimal Prometheus exposition (process uptime + request counters by path × status bucket). It can be replaced with `prometheus-fastapi-instrumentator` once full SLOs are defined.
- Logging: stdlib `logging` (configured via `app/core/logging_setup.py`), `LOG_FORMAT=json` switches to single-line JSON suitable for log shippers; loguru records are bridged into the same sink.

## Deployment

- One docker-compose stack per environment: `docker-compose.server.yml` is the base; `docker-compose.staging.yml` is an overlay that swaps ports and volumes for parallel staging on the same host.
- Image is published from `Dockerfile.server`: multi-stage build, non-root runtime, capability drop, `no-new-privileges`.
- `scripts/hotfix_publish.sh` uploads canonical single-file changes into the
  remote checkout and rebuilds/replaces the Compose `app` service (the runtime
  rootfs is read-only); it prefers SSH-key auth over sshpass.
- `scripts/db_backup.sh` runs `pg_dumpall` and encrypts via `age` when a recipient is configured. It refuses to write plaintext `.env` snapshots unless `ALLOW_UNENCRYPTED=1`.

## Future directions

### Foundations already in place

- `app/core/session_store.py` is a pluggable key/value store with `InMemorySessionStore` (default) and `RedisSessionStore` (selected via `REDIS_URL`). To allow `--workers >1`, port `ChaoxingSigninManager._clients`/`_qr_sessions` to read and write through `get_session_store()`. The compose stack already ships a profile-gated `redis` service.
- `scripts/migrate_tenants.py` runs the `tenant_db` head per tenant DB.
  Run `python scripts/migrate_tenants.py` on every deploy that touches
  `templates/tenant_template.sql`.
- OpenTelemetry: `app/core/tracing.py` activates when `OTEL_EXPORTER_OTLP_ENDPOINT` is set and the SDK is installed. It wires the FastAPI, psycopg2, requests and httpx instrumentors.
- TypeScript: `frontend/tsconfig.json` with `allowJs: true` lets new files land as `.tsx`/`.ts` alongside the existing `.jsx`. Shared API types live in `frontend/src/types/api.d.ts`.
- PWA: `vite-plugin-pwa` generates the service worker; `/api/*` is `NetworkOnly` so tenant-scoped data is never cached.

### Still needs a design pass

- Async DB. Moving every service from psycopg2 sync calls + `asyncio.to_thread` to asyncpg + SQLAlchemy 2.0 async touches most of the backend. It needs a per-module port plan with integration coverage before the switch.
- Page splitting. `ChaoxingSignin.jsx` and `Zhihuishu.jsx` already have partial subfolders (`chaoxing-signin/`, etc.). The remaining tabs and hooks should move out gradually, with snapshot/UI tests so behavior doesn't regress.
