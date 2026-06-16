# Changelog

All notable changes to this project will be documented in this file. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-06-16

### Fixed (round 4 — functional audit, validated against real 学习通/知到 accounts)
- **Zhihuishu course/video listing was fully broken** — Zhihuishu's `AppInterfaceSignInterceptor` now rejects unsigned requests (`code:400 "aes加密参数异常"`), so `get_course_list`/`get_video_list` returned empty. Requests are now AES-signed via the new `crypto.encrypt_secret_str()` (`secretStr` param + `HOME_KEY`) and read the response under `result` (the server moved it from `rt`). Verified live (request accepted, code 200). *(studyservice/video-list key still needs a real enrolled course to confirm.)*
- **CORS middleware order** — `CORSMiddleware` is now outermost so `tenant_isolation`'s 401 carries `Access-Control-Allow-Origin`; the SPA's session-expiry redirect fires instead of the app appearing to hang. (Supersedes the round-3 "metrics first-registered" note, which had the nesting backwards; metrics now sits outside tenant_isolation so it still counts those 401s.)
- **Chaoxing sign-in robustness** — activity-list `"data": null` no longer raises `AttributeError`; `int(None)` on `otherId/status/ifphoto` is coerced; one course's transient activity-list error no longer aborts the whole sign-in batch.
- **Chaoxing chapter progress** now reaches 100% for courses with pre-finished chapters (the done-callback fires on the already-finished early-return path).
- **Chaoxing sign-in task logs** use a stateless client-supplied cursor (was a destructive shared server cursor that blanked logs on reopen / overlapping polls).
- **Zhihuishu video watching** honors the configured speed and reacts to pause/cancel mid-video; a 0/None-duration video is surfaced as failed instead of fake-completed.
- **Zhihuishu QR refresh** — the QR regenerated after expiry is now delivered through the login-status poll and re-rendered.
- **Zhihuishu auto-answer** no longer silently discards the computed answer (logs that platform submission is not yet implemented).
- **Font-map resource path** resolves package-relative (was CWD-relative → wrong directory); a shipped `resource/font_map_table.json` is now found regardless of process CWD.
- **Answer-title OCR** gate now triggers for any OCR backend (external vision / HTTP endpoint), not only local Paddle OCR.
- **Rate limiter** DB round-trip on `/auth/login` and `/auth/register` is offloaded via `asyncio.to_thread` so it no longer blocks the async event loop.

### Added (round 3 — architectural foundations for previously-deferred items)
- **PWA** via `vite-plugin-pwa` — service worker + precache for hashed static assets, `NetworkOnly` policy for `/api/*` to keep tenant-scoped data uncached; build produces `dist/sw.js` and `dist/workbox-*.js`.
- **TypeScript foundation** — `frontend/tsconfig.json` with `allowJs: true`, strict mode, path alias `@/*`. New modules can be `.ts`/`.tsx`; existing `.jsx` keeps compiling unchanged. Shared API contract typings live in `frontend/src/types/api.d.ts`.
- **`app/core/session_store.py`** — pluggable key/value session store. `InMemorySessionStore` (default, behavior-equivalent to today) + `RedisSessionStore` (auto-selected when `REDIS_URL` is set). First step toward sharing `ChaoxingSigninManager` state across workers without an in-place rewrite.
- **Redis service in compose** — profile-gated (`docker compose --profile redis up -d redis`); 256 MB LRU cache, no persistence. App reads `REDIS_URL` to opt in.
- **`scripts/migrate_tenants.py`** — loops `users.tenant_db_name` and runs `alembic upgrade head` against each tenant DB. Supports `--dry-run` and `--only`, skips missing DBs with a warning, exits non-zero on any failure.
- **OpenTelemetry tracing** — `app/core/tracing.py`, env-flagged: when `OTEL_EXPORTER_OTLP_ENDPOINT` is set it wires `FastAPIInstrumentor` + best-effort psycopg2/requests/httpx instrumentors. Silently no-ops when the SDK isn't installed.

### Changed (simplify-skill review fixes)
- `metrics.py` counter is now bounded — keyed by `request.scope["route"].path` (templated, not raw URL), capped at `_MAX_KEYS=2000`, overflow buckets into `"_other_"`.
- `request_metrics_middleware` moved to first-registered so it is outermost and sees `tenant_isolation` 401s.
- `auth_service.login_user` is now async — DB roundtrip and `verify_password` both offloaded via `asyncio.to_thread`.
- `auth_service._insert_user_row` dropped the redundant pre-INSERT SELECTs — UNIQUE constraint + `UniqueViolation` analysis already identifies the conflicting field. Saves 2 DB round-trips per registration.
- Tenant pool eviction rewritten with `_TenantPoolEntry` dataclass; `pool.getconn()/putconn()` moved outside `_tenant_lock` so the outer lock only covers map mutation + refcount.
- `PUBLIC_ROUTES` lookup is now a module-level `frozenset` (was re-built per request).
- CORS production validation moved from module top level into `lifespan` (single "startup gates" place).
- `configure_logging()` moved from module import to `lifespan` — no log side effects during pytest collection.
- `/health` skips the no-op `COMMIT` round-trip via `autocommit=True`.
- `AuthExpiredListener` now uses one stable subscription + ref instead of re-subscribing on every navigation.
- `_get_cipher` no longer crosses module boundaries — `credential_crypto.init_cipher()` is the public entry.
- `create_access_token` computes `now.timestamp()` once.
- `RouteFallback` uses lucide `Loader2` instead of hand-rolled SVG.
- `api.js` no longer remaps `AbortError` to "请求超时" when caller passed their own `signal`.
- Inline `isAuthenticated()` checks removed from `Dashboard`/`ChaoxingSignin`/`Zhihuishu` — `PrivateRoute` covers them.

### Added
- Multi-stage `Dockerfile.server`; final image runs as non-root (uid/gid 10001), tini as PID 1, read-only rootfs with tmpfs `/tmp`, dropped capabilities, `no-new-privileges`.
- Root `.dockerignore` to keep `.git`, `node_modules`, `.env*`, docs and `_legacy` scripts out of the build context.
- Security response-headers middleware in FastAPI: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Content-Security-Policy`, conditional HSTS.
- Frontend `ErrorBoundary`, `PrivateRoute`, `RouteFallback`, `NotFound` route, and `AuthExpiredListener` that reacts to 401s and redirects with a `from` state for round-trip return.
- Lazy `BaiduMapPickerModal` import (~150 KB pulled only when the picker opens).
- Web manifest, SVG favicon, theme-color and OG meta in `index.html`.
- Backend `app/core/logging_setup.py` — single dictConfig pipeline, optional JSON formatter via `LOG_FORMAT=json`, loguru records bridged into stdlib.
- Alembic wired: `alembic.ini`, `env.py` reading `MAIN_DB_*` env vars, idempotent baseline migrations (`CREATE … IF NOT EXISTS`).
- nginx rate-limit zones (`/api/v1/auth/login` 5r/min, `/api/` 20r/s, per-IP conn cap), modern CSP, `server_tokens off`.
- CI: split lint · type · test · build · trivy scan; CodeQL workflow; Dependabot for pip/npm/actions/docker; CodeOwners; issue & PR templates; `.github/SECURITY.md`.
- `.pre-commit-config.yaml` (ruff, prettier, gitleaks).
- `pyproject.toml` rewritten under PEP 621 with `[tool.ruff]`, `[tool.mypy]`, `[tool.pytest.ini_options]`, `[tool.coverage]` blocks.
- `scripts/db_backup.sh` now supports `age` encryption (`AGE_RECIPIENT`/`AGE_RECIPIENT_FILE`); refuses to write plaintext `.env` snapshots without `ALLOW_UNENCRYPTED=1`.
- `scripts/hotfix_publish.sh` now supports SSH-key auth (`SSH_KEY=`) and prefers it over the sshpass fallback (which now uses `accept-new` host-key policy).

### Changed
- Postgres in `docker-compose.server.yml` tuned: `max_connections=300`, `shared_buffers=128MB`, `work_mem=8MB`, `effective_cache_size=384MB`, `wal_compression=on`, `log_min_duration_statement=500ms`.
- Database init reorganized: `00-schema.sql`, `01-create_tenant.sql`, `02-bootstrap-tenant-template.sh` (creates the `tenant_template` DB and applies its schema from `templates/`), so the docker-entrypoint never pollutes `main_db` with the tenant template.
- `users.created_at/updated_at` switched from naive `TIMESTAMP` to `TIMESTAMPTZ DEFAULT NOW()`.
- `auth_service.register_user` now runs all sync DB work via `asyncio.to_thread` (matches `login_user`); bcrypt hashing also offloaded so the event loop stays responsive.
- `app/config.py` migrated to Pydantic v2 `SettingsConfigDict` + `field_validator`; `SECRET_KEY` validated for length ≥ 16; `BCRYPT_ROUNDS` and `ENV` exposed as settings.
- `app/main.py`: removed misleading "CSRF protection" comment over `TrustedHostMiddleware`; eager `_get_cipher()` call at startup so missing `CREDENTIAL_ENCRYPTION_KEY` fails fast in production; `/health` no longer leaks the raw pool connection.
- `frontend/utils/api.js`: typed `ApiError`, 401-with-token now triggers a `auth:expired` CustomEvent so the SPA can redirect via React Router without coupling `api.js` to routing.
- Vite `BaiduMapPickerModal` no longer fetches marker icons from `unpkg`; assets bundled via `leaflet/dist/images/*` imports.
- `Makefile`, `scripts/setup.sh`, `scripts/test.sh` rewritten to target the real stack (`docker-compose.server.yml`, no redis service) and use docker compose v2.
- Frontend `package.json` renamed from `easy-learning-frontend` to `university-helper-frontend`.
- Frontend ESLint config: disabled `react/prop-types` (project doesn't use PropTypes), enabled `react/react-in-jsx-scope: off` for new JSX runtime, fixed mis-deps in `ChaoxingFanya.jsx`.

### Removed
- Unused `zustand` dependency from `frontend/package.json`.
- `scripts/deploy.sh` and `scripts/backup.sh` moved to `scripts/_legacy/` (referenced non-existent compose services and would overwrite prod `.env`).
- `app/main.py` legacy `from app.db.session import get_main_db_connection, _get_main_pool` (replaced by context-managed `get_db_session`).

### Security
- Container hardening: non-root, read-only rootfs, capability drop, `no-new-privileges`.
- nginx: rate-limit `/api/v1/auth/login` to 5r/min per IP; drop deprecated `X-XSS-Protection`; add CSP and Permissions-Policy.
- Backup script encrypts dumps and refuses plaintext `.env` snapshots by default.
- CI: CodeQL (python + javascript), Trivy image scan, Bandit, `npm audit` for high+ severity.
- `CREDENTIAL_ENCRYPTION_KEY` enforced at startup (was lazy, surfaced only on first credential op).

## [1.0.0] - 2024-01-01
Initial release with core authentication features.
