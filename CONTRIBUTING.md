# Contributing Guide

Thanks for considering a contribution to University Helper.

## Code of conduct

See [`.github/CODE_OF_CONDUCT.md`](./.github/CODE_OF_CONDUCT.md).

## Reporting bugs / requesting features

Use the GitHub issue templates in [`.github/ISSUE_TEMPLATE/`](./.github/ISSUE_TEMPLATE/). For security vulnerabilities, follow [`.github/SECURITY.md`](./.github/SECURITY.md) — **don't** open a public issue.

## Development setup

```bash
bash scripts/setup.sh        # creates .env, installs python + node deps
pre-commit install           # optional but recommended
```

Backend smoke run:

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
```

Frontend dev server (proxies `/api` to `:8000`):

```bash
cd frontend
npm run dev
```

## Branching & commits

- Branch off `main`: `feat/short-description`, `fix/issue-123`, `chore/…`.
- Use [Conventional Commits](https://www.conventionalcommits.org/) for messages — the changelog generator (and reviewers' brains) thank you.

```text
feat(auth): add JWT jti claim for revocation surface
fix(chaoxing): correct date formatting in signin history
chore(deps): bump pydantic-settings to 2.5
```

## Pull requests

1. Fork, branch, commit, push.
2. Open a PR using the template in [`.github/PULL_REQUEST_TEMPLATE.md`](./.github/PULL_REQUEST_TEMPLATE.md).
3. CI must be green: lint · type · test · build · CodeQL · Trivy.
4. At least one CODEOWNER approval is required for the affected path.

PRs should be focused — one feature/fix per PR. If a refactor surfaces while fixing a bug, prefer a follow-up PR over an avalanche.

## Code style

### Python

- Ruff is the formatter and linter (config in `backend/pyproject.toml`).
- Type hints encouraged on public functions and service boundaries; mypy runs in CI for `backend/app/`.
- New endpoints go in `backend/app/api/v1/`; new business logic in `backend/app/services/`. Keep imports thin between them.
- DB work runs in `asyncio.to_thread` from any `async def` route — `app/services/auth_service.py` is the canonical example.

### JavaScript / React

- ESLint + Prettier (configs in `frontend/.eslintrc.cjs` and `frontend/.prettierrc`).
- Functional components only; hooks for state. No PropTypes — TypeScript migration is on the roadmap.
- Heavy widgets (Leaflet, jsQR, charts) must be `lazy()` imports so they don't land in the initial bundle.
- API calls go through `frontend/src/utils/api.js` — don't `fetch` from a component.

## Testing

```bash
make test                 # backend pytest + frontend vitest
make lint                 # ruff + eslint
cd backend && pytest -q   # subset
cd frontend && npm test   # vitest watch
```

### Coverage expectations
- New backend service files: aim for ≥70% line coverage at PR time.
- New React components with user input: at least one Testing-Library smoke test (see `frontend/tests/unit/ErrorBoundary.test.jsx` for a template).

## Documentation updates

If your change is user-visible or affects ops, update the docs that match the area:

- README.md — install / quickstart / surface-level API
- docs/ARCHITECTURE.md — topology, component responsibilities
- docs/API.md — endpoint surface (currently hand-maintained; see CONTRIBUTING note below)
- docs/DEPLOYMENT.md — production deployment and ops
- CHANGELOG.md — under `## [Unreleased]` with the appropriate category

## Repository layout (real)

```
backend/                FastAPI app, services, alembic migrations, tests
backend/app/api/v1/     HTTP routes (auth, chaoxing, course, metrics)
backend/app/services/   Business logic (Chaoxing, Zhihuishu, notifications)
backend/app/middleware/ Tenant isolation, rate limiting
backend/app/db/         Connection pools (main + per-tenant LRU)
backend/api/            Legacy import shim for chaoxing modules (do not extend)
frontend/src/pages/     Route-level pages (lazy-loaded by App.jsx)
frontend/src/components/Shared components (ErrorBoundary, PrivateRoute, …)
frontend/src/utils/     api.js, auth.js, coord transforms
database/               Postgres init SQL — auto-applied by docker-entrypoint
.github/                CI, Dependabot, CodeQL, CODEOWNERS, templates
scripts/                setup/test/backup/hotfix helpers
```

## Tooling

- Python 3.11, Node 20 (see `.python-version` / `.nvmrc`).
- Docker Compose v2.
- Optional: `age` for encrypted backups (`scripts/db_backup.sh`).

Thank you!
