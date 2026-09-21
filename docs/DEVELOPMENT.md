# Development guide

## Prerequisites

- Docker + Docker Compose v2
- Node.js 20 (see `.nvmrc`)
- Python 3.11 (see `.python-version`)
- Git
- Optional: `pre-commit`, `age` (for backups), `ruff` CLI, Rust stable (desktop shell only)

## Quick start

```bash
bash scripts/setup.sh        # creates .env, installs python + node deps
pre-commit install           # optional
make start                   # docker-compose stack on http://127.0.0.1:8000
make test                    # full backend + frontend
```

## Backend

```bash
cd backend
source .venv/bin/activate

# Run dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Tests
pytest -q                              # full suite
pytest tests/unit -q                   # unit only
pytest tests/integration -q            # integration only (no real DB needed)
pytest --cov=app --cov-report=term-missing  # coverage

# Lint + format
ruff check app/
ruff format app/

# Database migrations — ALWAYS branch-qualified, and run from `backend/`.
# There are TWO branches (main_db and tenant_db), so a bare
# `alembic upgrade head` is ambiguous.
alembic upgrade main_db@head           # main DB: users, rate_limit_counters,
                                       #          email_verification_codes
python scripts/migrate_tenants.py      # every tenant_<username> DB (tenant_db@head)
alembic revision -m "describe change"  # write SQL via op.execute(...)
```

> **`database/*.sql` only runs on an EMPTY Postgres data directory, and nothing
> runs Alembic for you.** Any database that already has data needs
> `alembic upgrade main_db@head` by hand after pulling new migrations. In
> particular, `EMAIL_VERIFICATION_ENABLED=true` requires migration `003`
> (`email_verification_codes`); without it `/auth/send-code` and
> `/auth/reset-password` return 503 `邮箱验证服务未初始化，请联系管理员执行数据库迁移`.

Environment variables read by `app/config.py` (see `.env.example` for defaults):
`MAIN_DB_*`, `SECRET_KEY` (≥ 16 chars), `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`,
`CORS_ORIGINS`, `ALLOWED_HOSTS`, `ENFORCE_HTTPS`, `BCRYPT_ROUNDS`, `ENV`, `DOCS_ENABLED`,
`BAIDU_MAP_API_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, `ADMIN_EMAILS`, `UPDATE_CHECK_ENABLED`,
`DB_AUTO_BOOTSTRAP`, `EMAIL_VERIFICATION_ENABLED`, `SMTP_*`.

A few of these change what happens at startup:

- `DB_AUTO_BOOTSTRAP` (default `true`) makes the server create a missing `users` table or `tenant_template` database in the background. The test suite turns it off in `tests/conftest.py`.
- `UPDATE_CHECK_ENABLED` (default `true`) polls GitHub Releases so administrators see a new-version notice. Set it to `false` on machines without internet access.
- `ADMIN_EMAILS` is a comma-separated list of administrator emails. When it is empty, the first registered account is the administrator.
- `EMAIL_VERIFICATION_ENABLED` (default `false`) gates the email-code flows in `/auth/send-code` and `/auth/reset-password`; it needs the `email_verification_codes` table (migration `003`).

Note there are **two** `.env.example` files — the root one (Docker
Compose) and `backend/.env.example` (running `uvicorn` directly); both carry the
SMTP block.

## Frontend

```bash
cd frontend
npm install                  # uses package-lock.json
npm run dev                  # http://localhost:3000 with /api proxy to :8000
npm test                     # vitest watch
npm run test:ci              # vitest run + coverage
npm run lint                 # eslint, fails CI on any warning
npm run build                # production build into dist/
npm run build:analyze        # writes dist/stats.html (rollup-plugin-visualizer)
```

Tech: React 18, Vite 5, React Router 6, Tailwind (CSS-var tokens, dark mode
via `.dark` class), Vitest + Testing-Library, ESLint (react · react-hooks ·
jsx-a11y). There are no PropTypes; a TypeScript migration is planned.

## Desktop shell

The Tauri shell in `frontend/src-tauri/` has Rust unit tests. `tauri-build` refuses to run unless the sidecar binary exists, so stage the dev stub first:

```bash
cd frontend/src-tauri
bash scripts/make-dev-sidecar.sh
cargo test --locked
```

## Database

`docker compose -f docker-compose.server.yml exec postgres psql -U easylearning -d main_db`

Schema layout:
- `main_db` has a single shared `users` table.
- `tenant_template` is the prototype DB cloned for each user at registration.
- `tenant_<username>` is one DB per user and holds that user's task state.

Init SQL lives in `database/`:
- `00-schema.sql` and `01-create_tenant.sql` run against `main_db`.
- `02-bootstrap-tenant-template.sh` creates `tenant_template`, applies `templates/tenant_template.sql` to it and marks it `IS_TEMPLATE`.

These scripts only run when Postgres starts on an empty data volume. The server
checks again at startup (`backend/app/db/bootstrap.py`) and rebuilds a missing
`users` table or `tenant_template` from the SQL files copied into the image.
`/health` reports the result in its `schema` field.

Migrations are tracked in `backend/alembic/versions/` on two independent
heads. The shared `main_db` branch is applied from `backend/` with
`alembic upgrade main_db@head`. To apply the `tenant_db` branch to every
existing tenant database, run the helper from the repository root (with the
backend virtual environment active):

```bash
python scripts/migrate_tenants.py
```

New migrations should use idempotent DDL (`CREATE … IF NOT EXISTS`), because the
production DB was baselined by hand.

## Project structure

```
backend/
  app/api/v1/         HTTP routes (auth, chaoxing, course, metrics, system)
  app/services/       Business logic (chaoxing, zhihuishu, notifications, update_check, admin)
  app/middleware/     tenant_isolation, rate_limiter, allowed_hosts
  app/db/             connection pools, schema bootstrap
  app/core/           security, credential_crypto, logging_setup, exceptions
  alembic/            wired alembic; versions/ holds migrations
  tests/              unit + integration + performance pytest suites
  desktop_entry.py    entrypoint of the desktop sidecar (uh-backend)
frontend/src/
  components/         ErrorBoundary, PrivateRoute, RouteFallback, AuthExpiredListener, UpdateNotice, …
  pages/              Login, Register, Dashboard, ChaoxingSignin, ChaoxingFanya, Zhihuishu, NotFound
  utils/              api.js, auth.js, coordTransform.js
  assets/styles/      Tailwind base + CSS-var tokens
frontend/src-tauri/   Tauri desktop shell (Rust)
database/             Auto-applied by docker-entrypoint
scripts/              setup, test, db_backup, hotfix_publish, deploy_server, updater_manifest
.github/              CI, Dependabot, CodeQL, CODEOWNERS, templates
```

## Debugging

- Backend: `LOG_LEVEL=DEBUG` enables verbose logging; `LOG_FORMAT=json` switches to one-line-per-record JSON for log shippers.
- Frontend: React DevTools + Vite's `?debug` query parameter.
- Docker: `docker compose -f docker-compose.server.yml logs -f app`.

## Common issues

- **Port 8000 already in use.** Find the process with `lsof -i :8000` and stop it, or change `APP_PORT`.
- **DB connection failed locally.** Start the stack (`make start`) before the dev backend, or point uvicorn at the dockerized DB.
- **/health or any request returns 400 `InvalidHost`.** The server only answers to `localhost`, `127.0.0.1`, the hosts in `CORS_ORIGINS` and the names in `ALLOWED_HOSTS`. Add the host or IP you are calling from to `ALLOWED_HOSTS` (comma separated). Production refuses `ALLOWED_HOSTS=*`.
- **Registration returns 503 `DatabaseNotInitializedError`.** The `users` table or `tenant_template` is missing. Check the `schema` field of `/health` and the app log; restarting the app runs the schema bootstrap again.
- **Frontend build complains about leaflet assets.** Leaflet assets are bundled through Vite imports now. If you still see unpkg URLs, rebase on `main`.

## Security checklist before merging

- No new dependency without `npm audit` / pip security review.
- Any new env var must be added to `.env.example`.
- Touching auth or tenant isolation requires an integration test.
- Credentials at rest go through `app/core/credential_crypto.encrypt_str`.

## See also

- [ARCHITECTURE.md](./ARCHITECTURE.md): topology and component responsibilities
- [API.md](./API.md): REST surface
- [DEPLOYMENT.md](./DEPLOYMENT.md): production deploy and ops
- [../CONTRIBUTING.md](../CONTRIBUTING.md): branch and PR workflow
