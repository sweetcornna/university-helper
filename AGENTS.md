# Repository Guidelines

## Project Structure

University Helper is a Python/FastAPI and React/Vite application with Tauri/Swift clients.

- `backend/app/api/v1/` contains HTTP routes; `backend/app/services/` contains business logic; `backend/app/storage/` and `backend/app/db/` handle raw SQL and connections.
- `backend/tests/` contains `unit/`, `integration/`, `performance/`, and `e2e/` suites. Frontend tests live beside source files and under `frontend/tests/unit/`.
- `frontend/src/pages/`, `components/`, and `utils/` hold the SPA. `frontend/src-tauri/` packages the desktop app; `ios/` contains the native client.
- `database/` holds PostgreSQL initialization and tenant templates; `scripts/` holds setup, testing, migration, backup, and deployment helpers; `docs/` holds project documentation.

Preserve the legacy `backend/api/` import shim; do not extend or delete it.

## Build, Test, and Development Commands

Run `bash scripts/setup.sh` or `make setup` to create `.env` and install dependencies. Start the API with `uvicorn app.main:app --app-dir backend --reload --port 8000`; start the SPA with `cd frontend && npm run dev`.

- `make start` / `make stop` — start or stop the Docker Compose stack.
- `make test` — run backend pytest and frontend Vitest; `make lint` — run Ruff and ESLint.
- `cd frontend && npm run build` — create SPA bundle; `make build` — build the server image.
- `cd backend && alembic upgrade main_db@head` — migrate the shared database; run `python scripts/migrate_tenants.py` for tenant databases. Never use an unqualified Alembic `head`.

## Coding Style and Testing

Backend code uses Ruff (120-column line length), raw SQL, and `asyncio.to_thread` for blocking work in async routes. Put new routes in `backend/app/api/v1/` and logic in `backend/app/services/`. Frontend is plain JavaScript/JSX: functional components, hooks, no semicolons, single quotes, and two-space indentation. Use Prettier, Tailwind tokens, and route API calls through `frontend/src/utils/api.js`.

Use `test_*.py` for pytest and `*.test.js`/`*.test.jsx` for Vitest. Mark async backend tests with `@pytest.mark.asyncio`; defaults are seeded in `backend/tests/conftest.py`. Target 70% coverage for new service files and add a Testing Library smoke test for user-input components.

## Commits and Pull Requests

Use branches such as `feat/short-description`, `fix/issue-123`, or `chore/deps`. Follow Conventional Commits, for example `fix(chaoxing): handle task retry`. Keep PRs focused; include summary, test plan, risk/rollback notes, linked issues, and UI screenshots when relevant. CI must pass lint, type, test, build, CodeQL, and Trivy; obtain CODEOWNER approval.

## Security and Documentation

Never commit `.env` or credentials. Encrypt third-party credentials through `app/core/credential_crypto.py`, avoid PII/token logging, and add integration coverage for auth or tenant-isolation changes. Keep tenant migrations synchronized with `database/templates/tenant_template.sql`. Update matching docs and `CHANGELOG.md` for user-visible or operational changes.
