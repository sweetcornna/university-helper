# Development Guide

## Prerequisites

- Docker + Docker Compose v2
- Node.js 20 (see `.nvmrc`)
- Python 3.11 (see `.python-version`)
- Git
- Optional: `pre-commit`, `age` (for backups), `ruff` CLI

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

# Database migrations
alembic upgrade head
alembic revision -m "describe change"  # write SQL via op.execute(...)
```

Environment variables read by `app/config.py` (see `.env.example` for defaults):
`MAIN_DB_*`, `SECRET_KEY` (≥ 16 chars), `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`,
`CORS_ORIGINS`, `ENFORCE_HTTPS`, `BCRYPT_ROUNDS`, `ENV`, `DOCS_ENABLED`,
`BAIDU_MAP_API_KEY`, `CREDENTIAL_ENCRYPTION_KEY`.

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
jsx-a11y), no PropTypes (TypeScript migration is on the roadmap).

## Database

`docker compose -f docker-compose.server.yml exec postgres psql -U easylearning -d main_db`

Schema layout:
- `main_db` — single shared `users` table.
- `tenant_template` — prototype DB cloned per user on registration.
- `tenant_<username>` — one DB per user, holds that user's task state.

Init SQL lives in `database/`:
- `00-schema.sql` and `01-create_tenant.sql` run against `main_db`.
- `02-bootstrap-tenant-template.sh` creates `tenant_template` and applies `templates/tenant_template.sql` against it.

Migrations are tracked in `backend/alembic/versions/`. New migrations should
use idempotent DDL (`CREATE … IF NOT EXISTS`) to stay safe against the
ad-hoc-baselined production DB.

## Project structure (real layout)

```
backend/
  app/api/v1/         HTTP routes (auth, chaoxing, course, metrics)
  app/services/       Business logic (chaoxing, zhihuishu, notifications)
  app/middleware/     tenant_isolation, rate_limiter
  app/db/             connection pools
  app/core/           security, credential_crypto, logging_setup, exceptions
  alembic/            wired alembic; versions/ holds migrations
  tests/              unit + integration + performance pytest suites
frontend/src/
  components/         ErrorBoundary, PrivateRoute, RouteFallback, AuthExpiredListener, …
  pages/              Login, Register, Dashboard, ChaoxingSignin, ChaoxingFanya, Zhihuishu, NotFound
  utils/              api.js, auth.js, coordTransform.js
  assets/styles/      Tailwind base + CSS-var tokens
database/             Auto-applied by docker-entrypoint
scripts/              setup, test, db_backup, hotfix_publish
.github/              CI, Dependabot, CodeQL, CODEOWNERS, templates
```

## Debugging

- Backend: `LOG_LEVEL=DEBUG` enables verbose logging; `LOG_FORMAT=json` switches to one-line-per-record JSON for log shippers.
- Frontend: React DevTools + Vite's `?debug` query parameter.
- Docker: `docker compose -f docker-compose.server.yml logs -f app`.

## Common issues

- **Port 8000 already in use** — `lsof -i :8000`, kill, or change `APP_PORT`.
- **DB connection failed locally** — start the stack (`make start`) before the dev backend, or run uvicorn against the dockerized DB.
- **/health returns 400 (Invalid host header)** — `CORS_ORIGINS` must include the actual host you're calling from.
- **Frontend build complains about leaflet assets** — assets are bundled via Vite imports now; if you see unpkg URLs, rebase against `main`.

## Security checklist before merging

- No new dependency without `npm audit` / pip security review.
- Any new env var must be added to `.env.example`.
- Touching auth or tenant isolation requires an integration test.
- Credentials at rest go through `app/core/credential_crypto.encrypt_str`.

## See also

- [ARCHITECTURE.md](./ARCHITECTURE.md) — topology and component responsibilities
- [API.md](./API.md) — REST surface
- [DEPLOYMENT.md](./DEPLOYMENT.md) — production deploy + ops
- [../CONTRIBUTING.md](../CONTRIBUTING.md) — branch + PR workflow
