# Contributing guide

Thanks for considering a contribution to University Helper.

## Code of conduct

See [`.github/CODE_OF_CONDUCT.md`](./.github/CODE_OF_CONDUCT.md).

## Reporting bugs / requesting features

Use the GitHub issue templates in [`.github/ISSUE_TEMPLATE/`](./.github/ISSUE_TEMPLATE/). Please report security vulnerabilities privately as described in [`.github/SECURITY.md`](./.github/SECURITY.md), not in a public issue.

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
- Write commit messages as [Conventional Commits](https://www.conventionalcommits.org/). The changelog is generated from them, and they make review easier.

```text
feat(auth): add JWT jti claim for revocation surface
fix(chaoxing): correct date formatting in signin history
chore(deps): bump pydantic-settings to 2.5
```

## Pull requests

1. Fork, branch, commit, push.
2. Open a PR using the template in [`.github/PULL_REQUEST_TEMPLATE.md`](./.github/PULL_REQUEST_TEMPLATE.md).
3. The blocking checks are backend Ruff lint/format, Bandit, and pytest;
   frontend ESLint, Vitest, and build; `cargo test` for the desktop shell;
   and the Docker image build. CodeQL runs in a separate workflow.
   Trivy is report-only (`exit-code: 0`), and
   `npm audit` is explicitly non-blocking.
4. At least one CODEOWNER approval is required for the affected path.

Keep each PR to one feature or fix. If you find something worth refactoring while fixing a bug, send it as a follow-up PR.

## Code style

### Python

- Ruff is the formatter and linter (config in `backend/pyproject.toml`).
- Type hints are encouraged on public functions and service boundaries. `mypy` is
  available for local checks but is not currently run by CI.
- New endpoints go in `backend/app/api/v1/` and new business logic in `backend/app/services/`. Keep the imports between them thin.
- Any `async def` route runs its DB work in `asyncio.to_thread`. `app/services/auth_service.py` shows the pattern.

### JavaScript / React

- ESLint + Prettier (configs in `frontend/.eslintrc.cjs` and `frontend/.prettierrc`).
- Functional components only, with hooks for state. There are no PropTypes because a TypeScript migration is planned.
- Heavy widgets (Leaflet, jsQR, charts) must be `lazy()` imports so they stay out of the initial bundle.
- API calls go through `frontend/src/utils/api.js`. Don't call `fetch` from a component.

## Testing

```bash
make test                 # backend pytest + frontend vitest
make lint                 # ruff + eslint
cd backend && pytest -q   # subset
cd frontend && npm test   # vitest watch
```

The desktop shell has its own Rust tests. `tauri-build` needs a sidecar binary to exist, so create the dev stub first:

```bash
cd frontend/src-tauri
bash scripts/make-dev-sidecar.sh
cargo test --locked
```

### Coverage expectations

- New backend service files: aim for ≥70% line coverage at PR time.
- New React components with user input: at least one Testing-Library smoke test (see `frontend/tests/unit/ErrorBoundary.test.jsx` for a template).

## Documentation updates

If your change is user-visible or affects ops, update the docs for that area:

- README.md: install, quickstart, surface-level API
- docs/ARCHITECTURE.md: topology, component responsibilities
- docs/API.md: endpoint surface (maintained by hand)
- docs/DEPLOYMENT.md: production deployment and ops
- CHANGELOG.md: under `## [Unreleased]` with the appropriate category

## Repository layout

```
backend/                FastAPI app, services, alembic migrations, tests
backend/app/api/v1/     HTTP routes (auth, chaoxing, course, metrics, system)
backend/app/services/   Business logic (Chaoxing, Zhihuishu, notifications, update check)
backend/app/middleware/ Tenant isolation, rate limiting, allowed hosts
backend/app/db/         Connection pools (main + per-tenant LRU), schema bootstrap
backend/api/            Legacy import shim for chaoxing modules (do not extend)
frontend/src/pages/     Route-level pages (lazy-loaded by App.jsx)
frontend/src/components/ Shared components (ErrorBoundary, PrivateRoute, …)
frontend/src/utils/     api.js, auth.js, coord transforms
frontend/src-tauri/     Desktop shell (Tauri, Rust)
database/               Postgres init SQL, auto-applied by docker-entrypoint
.github/                CI, Dependabot, CodeQL, CODEOWNERS, templates
scripts/                setup/test/backup/hotfix/deploy/release helpers
```

## Tooling

- Python 3.11, Node 20 (see `.python-version` / `.nvmrc`).
- Docker Compose v2.
- Rust stable, only for the desktop shell.
- Optional: `age` for encrypted backups (`scripts/db_backup.sh`).

Thank you!
