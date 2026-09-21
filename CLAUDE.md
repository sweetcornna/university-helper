# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

University Helper (产品名 "学道"; legacy internal name `easy_learning` survives in container names, `EASY_LEARNING_*` env prefixes, and prod paths) automates coursework on two Chinese MOOC platforms: Chaoxing/超星学习通 (sign-in + Fanya course watching/quizzes — the bulk of the code) and Zhihuishu/智慧树. Quizzes are auto-answered through pluggable "tiku" (答题库) providers, including two LLM providers. It ships three ways: web SPA + API behind nginx (Docker), a Tauri desktop app wrapping a PyInstaller-frozen backend sidecar, and local dev servers.

Stack: Python 3.11 / FastAPI / raw SQL (no ORM) / PostgreSQL 15 (or SQLite in desktop mode); React 18 / Vite 5 / Tailwind (plain JS + JSX, no TypeScript source); Tauri v2.

### Other trees (outside the server build)

- `ios/` — native SwiftUI client (iOS 16+). **Untracked in git and absent from every CI and release workflow** — treat it as an in-progress local tree, not a shipped artifact. Regenerate with `xcodegen generate --spec project.yml`; build the IPA with `ios/scripts/build_ipa.sh` (without a signing identity it emits a structurally-valid ad-hoc IPA that is not device-installable). See `ios/README.md` and `docs/IOS_APP_PLAN.md`.
- `site/` — static showcase pages, deployed to GitHub Pages by `.github/workflows/pages.yml`, which triggers **only** on `site/**`.
- `promo/` — Remotion project that renders the product film checked in under `docs/`.

None of these are touched by the build/test/lint commands below.

## Commands

Local dev runs uvicorn + vite directly (Docker only for Postgres or to reproduce prod-only bugs):

```bash
make setup                # bootstrap: .env, backend/.venv, npm ci (system python3 must be 3.11; use uv otherwise)
cd backend && uvicorn app.main:app --reload --port 8000   # API; reads .env via pydantic-settings
cd frontend && npm run dev                                 # SPA on :3000, proxies /api → :8000
make start / make stop / make logs-app                     # full docker-compose stack on :8000
```

Backend env requirements: `SECRET_KEY` (≥16 chars), `CORS_ORIGINS` (JSON list), `MAIN_DB_USER`/`MAIN_DB_PASSWORD` unless `STORAGE_BACKEND=sqlite`. `CREDENTIAL_ENCRYPTION_KEY` (Fernet) is mandatory when `ENV=production`.

Local-dev gotchas (all verified by running it):

- `.env` lives at the repo root, but pydantic-settings resolves `env_file=".env"` relative to CWD — so `cd backend && uvicorn ...` finds no config. Either run from the root (`uvicorn app.main:app --app-dir backend`) or export vars explicitly.
- Do not `set -a; . .env` — the shell strips the quotes inside the `CORS_ORIGINS` JSON array and pydantic fails to parse it.
- `ENFORCE_HTTPS` defaults to `True`, so a plain-HTTP local backend 301-redirects everything. Compose sets it to `false`; for a bare uvicorn run you must too.
- `MAIN_DB_*` are only defined in the compose file, not `.env` (which has `POSTGRES_PASSWORD`). Running uvicorn on the host against the dockerized DB needs `MAIN_DB_HOST=localhost`, `MAIN_DB_USER=easylearning`, `MAIN_DB_PASSWORD=$POSTGRES_PASSWORD`, and a published `5432` (the compose file exposes Postgres only on the internal network).
- `backend/resource/font_map_table.json` is absent from the repo; Chaoxing's encrypted-font decoding logs a warning and degrades gracefully. Not a setup failure.
- `CREDENTIAL_ENCRYPTION_KEY` is **not** a `Settings` field — `app/core/credential_crypto.py` reads `os.getenv` directly, and pydantic-settings does not export `.env` into the environment. So a host-run uvicorn that relies on `.env` alone starts with the **no-op cipher and stores third-party credentials in plaintext** (it logs a loud warning). Compose passes it as a real env var, so this bites only local dev: export it explicitly, e.g. `CREDENTIAL_ENCRYPTION_KEY=$(grep -E '^CREDENTIAL_ENCRYPTION_KEY=' .env | cut -d= -f2-)`.

Tests:

```bash
cd backend && pytest -q                                    # pytest.ini governs (NOT pyproject's [tool.pytest.ini_options])
cd backend && pytest tests/unit/test_config.py::test_name  # single test; suites: tests/{unit,integration,performance,e2e}
cd backend && pytest --ignore=tests/performance            # what CI runs
cd frontend && npm test                                    # vitest watch mode
cd frontend && npm test -- run src/utils/api.test.js       # single file, one-shot
cd frontend && npm run test:ci                             # one-shot with coverage
```

Async backend tests need explicit `@pytest.mark.asyncio` — pytest.ini overrides pyproject, so `asyncio_mode = auto` is NOT in effect. Tests must set env vars before importing app modules (see `tests/conftest.py`).

**The `env =` block in `pytest.ini` is dead.** It needs the `pytest-env` plugin, which is not in `requirements-dev.txt`; pytest just warns `Unknown config option: env` and ignores all five variables. `tests/conftest.py` seeds them instead, and that list is what actually takes effect — extend it there, not in pytest.ini. Two failure modes this causes, both of which look like a bug in your new code:

- Missing `MAIN_DB_USER`/`MAIN_DB_PASSWORD` makes `Settings()` raise, so *collection* fails for any test that imports the app in the default server profile. Existing tests dodged this only because they run `PROFILE=local`/SQLite.
- Missing `ENFORCE_HTTPS=false` makes the redirect middleware 301 every plain-HTTP test request. httpx follows the redirect and downgrades POST to GET, which misses the POST-only route and lands on the SPA catch-all — so an endpoint test asserting JSON gets **200 with `index.html`** instead of the 422/400 it expected.

`get_db_session` commits on clean exit and **rolls back on exception**. Never mutate then `raise` inside the `with` block — the write is silently discarded. `verify_code` in `app/services/email_verification.py` shows the pattern: record the failure, exit the block, then raise.

Lint/format:

```bash
cd backend && ruff check app/ && ruff format --check app/  # ruff is both linter and formatter; line-length 120
cd frontend && npm run lint                                # eslint --max-warnings 0 (any warning fails)
cd frontend && npm run format                              # prettier
```

`make precommit` installs the pre-commit hooks (ruff, prettier, gitleaks, private-key detection). Note the version skew: pre-commit pins ruff `v0.7.4` while CI installs `ruff==0.8.4` — a clean hook run does not guarantee a clean CI run.

Migrations — **two independent alembic branches**; plain `alembic upgrade head` is ambiguous and fails:

```bash
cd backend && alembic upgrade main_db@head                 # shared main DB
python scripts/migrate_tenants.py [--dry-run]              # tenant_db@head across every tenant_<user> database
cd backend && alembic revision -m "..."                    # hand-written idempotent DDL via op.execute(); autogenerate is disabled (no ORM)
```

Tenant schema changes must also update `database/templates/tenant_template.sql` (used for new tenants) — keep both in sync.

`database/*.sql` runs **only on a virgin Postgres data directory**, and nothing in the Dockerfile, the compose files, or the deploy workflow ever invokes alembic. A new main-DB table therefore exists on fresh installs but is missing on every upgraded deployment until someone runs `alembic upgrade main_db@head` by hand. Add new tables to both places and assume the migration has not been run — the email-verification path translates the resulting `UndefinedTable` (SQLSTATE 42P01) into a 503 with an actionable message rather than letting it surface as a 500.

## Architecture

### Backend (`backend/app/`)

Request flow (server mode): `tenant_isolation` middleware (JWT gate; everything not in `PUBLIC_ROUTES` in `app/config.py` gets 401) → routers in `app/api/v1/` (auth, course, chaoxing, metrics) → services in `app/services/` → storage via `app/storage/factory.get_storage()` (Protocol-typed `PostgresStorage`/`SqliteStorage` singleton) and `app/db/session.py` connection pools (one main pool + LRU map of per-tenant pools).

- **No ORM anywhere.** `app/models/` is empty; everything is raw SQL behind storage adapters.
- **Middleware order in `app/main.py` is load-bearing** (Starlette runs middleware in reverse registration order): tenant_isolation innermost, CORS outermost, so short-circuited 401s still get CORS headers and are counted by metrics. Preserve when adding middleware.
- **Multi-tenancy = one Postgres DB per user** (`tenant_<username>`, cloned from `tenant_template`); shared `users` table lives in `main_db`.
- **Dual profile** via `settings.PROFILE`: `server` (multi-tenant Postgres) vs `local` (desktop: SQLite, JWT middleware skipped, identity injected via `app.dependency_overrides`, SPA served from `FRONTEND_DIST`). Guard local-only behavior behind `settings.PROFILE` checks — server mode must stay byte-for-byte unchanged.
- `backend/api/` (top-level, not `app/api/`) is a **legacy import shim** that is still load-bearing at runtime — seven modules under `services/course/chaoxing/` import from it (`answer_base.py` → `api.answer`; `cipher.py`/`decode.py` → `api.config`; `decode.py`/`cxsecret_font.py`/`font_decoder.py` → `api.exceptions`/`api.logger`/`api.vision_ocr`; `live.py`/`live_process.py` → `api.base`/`api.live`). It resolves because `backend/` is the import root. Excluded from ruff/mypy. Never add code there; never delete it as "dead code".
- Blocking DB/service calls from `async def` routes go through `asyncio.to_thread` (`_run_blocking` in `api/v1/course.py` is the pattern).

### Email verification (`app/core/mailer.py`, `app/services/email_verification.py`)

Registration codes and password reset, gated behind `EMAIL_VERIFICATION_ENABLED` (**default false** — with the flag off, `/auth/register` behaves exactly as it did before the feature existed, which is what keeps the SQLite desktop profile working, since this path needs `main_db`). `mailer.py` is blocking smtplib; `email_verification.py` owns the `email_verification_codes` table. Both are called via `asyncio.to_thread`.

Invariants worth knowing before touching this:

- Codes come from `secrets.randbelow`, are stored only as an **HMAC-SHA256 keyed with `SECRET_KEY`** (a bare digest over a 10⁶ keyspace is trivially reversed from a leaked backup), compared with `hmac.compare_digest`, deleted on success, and locked out after 5 attempts.
- The resend cooldown is enforced by the `ON CONFLICT … DO UPDATE … WHERE last_sent_at <= …` clause itself, so two concurrent requests cannot both win. A cooldown hit returns zero rows.
- The `reset` scene must stay indistinguishable for registered and unregistered addresses in **status, body, and timing**. Do not let a cooldown 429 or an SMTP failure escape on that path — it turns into a user-enumeration oracle.
- Email is normalized to lowercase at the schema edge. `users.email` is a case-sensitive column, so any comparison that skips normalization silently fails to match.

### Chaoxing task pipeline (`app/services/course/chaoxing/`)

`POST /api/v1/course/start` → `learning_manager` (module singleton, `learning_manager.py`) owns all task lifecycle: one daemon thread per task, in-memory state dict under a lock, pause/stop `threading.Event`s, persistence via `task_store.py` (Fernet-encrypts named credential fields before storage). High-frequency progress writes are throttled to one per `PROGRESS_PERSIST_INTERVAL` (5s) per task by `learning_manager._should_persist_now` — that throttle lives in `learning_manager.py`, not `task_store.py`; status/terminal transitions pass `force=True` and always write. `learning.py` owns the execution engine (`JobProcessor`: PriorityQueue + worker threads + retry thread; per-chapter ThreadPoolExecutor). `client.py`'s `Chaoxing` class is a pure facade composing per-instance auth/course/quiz/video sub-services.

- **Per-user session isolation is a hard rule**: every `Chaoxing` instance owns its own `SessionManager` (wrapping a `requests.Session`); never share sessions or mutable class-level state across users (single uvicorn worker serves everyone).
- Answer providers ("tiku"): base class in `answer_base.py`; implementations in `answer_providers/` (TikuYanxi/TikuGo/TikuLike/TikuAdapter/LocalCache + LLM providers AI/SiliconFlow). `tiku_config.provider` accepts a comma-separated fallback chain. Providers must **self-disable** (`DISABLE=True`) on missing config instead of raising — a crash kills the whole learning task. Shared answer cache is always consulted first.
- Task-state keys prefixed `_` (e.g. `_stop_event`) are runtime-only and are stripped before persistence/API responses.
- Thread-start exhaustion (`"can't start new thread"`) is a first-class failure mode: string-matched and mapped to 503 in `course.py` or inline single-threaded fallback in `learning.py`. Preserve this when touching task startup.
- Chaoxing service internals log via loguru; API layer/managers use stdlib logging (see `backend/LOGGING_GUIDELINES.md`: no PII/tokens, expected failures are WARNING not ERROR, `exc_info=True` on exceptions).
- Other services: `services/course/zhihuishu/` (second platform, per-user adapter cache), `chaoxing/signin.py` (separate signin_manager), `course_portal_service.py` (read-only portal scraping), `services/notification/` (push providers; all URLs must pass the `validate_notification_url` SSRF guard).

### Frontend (`frontend/src/`)

React SPA, all pages `React.lazy`-loaded; protected pages nest under `<PrivateRoute><AppLayout/></PrivateRoute>`. Complex pages follow a pattern: thin orchestrator `src/pages/<Name>.jsx` + `src/pages/<kebab-name>/{components,hooks,utils.js}` (e.g. `ChaoxingFanya.jsx`). Shared components exported via the `src/components/index.js` barrel. State is React context only (theme, toast) — no Redux.

- **All API calls go through `src/utils/api.js`** (fetch wrapper: Bearer token, 20s AbortController timeout, typed `ApiError`) — never `fetch` from a component. It distinguishes the app's own session expiry (clears tokens, dispatches `auth:expired`) from third-party platform 401s (e.g. Zhihuishu not logged in), which must surface to the page.
- Tokens live in localStorage (`src/utils/auth.js`) — deliberate, documented tradeoff; don't expose them on `window`.
- No TypeScript source: tsconfig.json is editor-only. Use relative imports (the `@/` alias exists only in tsconfig and is unused). Style: no semicolons, single quotes, 2-space indent.
- Tailwind semantic tokens (`primary`, `surface`, `text-muted`, …) mapped to CSS variables — use tokens, not raw palette colors, so dark mode (class-based) remaps automatically.
- UI copy and user-facing errors are in Chinese.
- Heavy widgets (Leaflet, jsQR) must be `lazy()` imports, as must every route component.

### Desktop (`frontend/src-tauri/` + `backend/desktop_entry.py`)

Tauri shell does NOT bundle the Vite dist — it spawns the PyInstaller-frozen `uh-backend` sidecar (built by `scripts/build_sidecar.sh` from `desktop_entry.py`, which embeds `frontend/dist`), parses the `UH_BACKEND_LISTENING <port>` line, waits for `/health`, and opens a webview on that loopback port. Dev loop: `bash frontend/src-tauri/scripts/make-dev-sidecar.sh` once, then `npm run tauri dev`.

## Deployment & release

- `docs/DEPLOYMENT.md` is the single source of truth. `docs/_archive/` and `scripts/_legacy/` are stale — never follow or run them.
- Compose files: `docker-compose.server.yml` (base build-from-source stack used by Makefile and prod), `docker-compose.release.yml` (pull prebuilt GHCR images; used by `scripts/deploy_server.sh` for fresh hosts), `docker-compose.staging.yml` / `docker-compose.newhost.yml` (overlays).
- Ongoing prod changes ship ONLY via `scripts/hotfix_publish.sh` (file-level rsync + container restart), not full redeploys.
- **Never raise `uvicorn --workers` above 1**: Chaoxing login/session state is per-process; a second worker reintroduces the cross-worker login bug. Redis (`REDIS_URL`) does not fix this.
- `ENFORCE_HTTPS` stays `false` in compose deployments (nginx terminates TLS; app-level redirect would loop).
- Release: pushing a `v*` git tag builds GHCR images tagged without the `v`. `scripts/set_version.sh <version>` stamps the version into exactly six manifests — never hand-edit them individually.

## Conventions

- **Commit every change as you make it — do not wait to be asked, and do not leave work uncommitted at the end of a turn.** After each coherent change (a fix, a feature, a doc edit, a config tweak), stage exactly what that change touched and commit it with a Conventional Commit subject. One concern per commit: if a single file carries two unrelated changes, stage them separately rather than bundling. Branch first if you are on `main`.
- Branches `feat/...`, `fix/issue-123`, `chore/...`; Conventional Commits (`fix(chaoxing): ...`) — they feed the changelog. Add CHANGELOG.md entries under `## [Unreleased]`.
- New endpoints go in `backend/app/api/v1/`, new business logic in `backend/app/services/`. New public (unauthenticated) routes must be added to `PUBLIC_ROUTES` in `app/config.py` or the middleware 401s them.
- Comments citing bug/workstream IDs (`(F05)`, `F62`, "workstream F") document invariants — preserve them when editing nearby code.
- Runtime deps are pinned in `backend/requirements.txt` (single source of truth; pyproject `[project].dependencies` is intentionally empty); dev tooling in `requirements-dev.txt`.
- Ruff baseline suppressions in pyproject (B008, TID252, PLW0603) are intentional idioms here, not violations to fix.
- User-visible or ops-affecting changes must update the matching doc: README.md, docs/ARCHITECTURE.md, docs/API.md, docs/DEPLOYMENT.md, CHANGELOG.md.
