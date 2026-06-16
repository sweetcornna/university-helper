**Language:** English | [简体中文](./README.zh-CN.md)

<p align="center">
  <img src="frontend/public/favicon.svg" width="72" alt="University Helper logo" />
</p>

<h1 align="center">University Helper</h1>

<p align="center">
  <a href="../../actions/workflows/test.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/OWNER/REPO/test.yml?branch=main&label=ci&style=flat-square" /></a>
  <a href="../../actions/workflows/codeql.yml"><img alt="CodeQL" src="https://img.shields.io/github/actions/workflow/status/OWNER/REPO/codeql.yml?branch=main&label=codeql&style=flat-square" /></a>
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/github/license/OWNER/REPO?style=flat-square" /></a>
  <img alt="python" src="https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white&style=flat-square" />
  <img alt="react" src="https://img.shields.io/badge/react-18-61DAFB?logo=react&logoColor=black&style=flat-square" />
  <img alt="fastapi" src="https://img.shields.io/badge/fastapi-0.115-009688?logo=fastapi&logoColor=white&style=flat-square" />
</p>

<p align="center">
  <img src="docs/university-helper-promo.gif" alt="University Helper — 60-second product film: while you sleep, it signs in, watches lectures and answers quizzes on Chaoxing and Zhihuishu, finishing by dawn" width="640" />
  <br />
  <sub><b>“You sleep, it studies.”</b> — 60-second product film, rendered frame-by-frame with Remotion</sub>
</p>

University Helper is a full-stack campus helper built on FastAPI + React. The
repository name is `university-helper`; parts of the source tree still use the
historical internal name `easy_learning` (container names, env-var prefixes)
and we are gradually unifying these.

## Highlights

- Multi-tenant via **one Postgres DB per user** (`tenant_<username>`) — cross-tenant data leaks are physically impossible.
- JWT-authenticated REST API behind FastAPI 0.115 + Pydantic v2 + psycopg2 pools.
- Chaoxing sign-in and Fanya course automation.
- Zhihuishu QR / password login + course task orchestration.
- React 18 + Vite 5 + Tailwind SPA with route-level code splitting, lazy-loaded heavy widgets, global error boundary, and authenticated route gating.
- Hardened docker-compose: non-root runtime, multi-stage build, security headers, nginx rate-limiting, encrypted backups.

## Repository layout

```text
backend/        FastAPI application, services, schemas, alembic migrations, tests
frontend/       React + Vite frontend (Tailwind, lazy routes, error boundary)
database/       Postgres init SQL (auto-run by docker-entrypoint) + tenant_template/ schema
nginx/          Reverse-proxy configuration (rate limits, CSP, HSTS)
scripts/        setup / test / backup / hotfix-publish helpers
.github/        CI workflows, CodeQL, Dependabot, CODEOWNERS, issue templates
```

## Tech stack

- **Backend**: Python 3.11, FastAPI 0.115, Pydantic v2, psycopg2, PyJWT, bcrypt, Fernet credential encryption
- **Frontend**: React 18, Vite 5, React Router 6, Tailwind, lucide-react, leaflet
- **Data**: PostgreSQL 15 (tuned: `max_connections=300`, `work_mem=8MB`)
- **Migrations**: Alembic (wired)
- **Deployment**: Docker + Compose (production), host nginx fronts the app
- **CI**: GitHub Actions (lint · type · test · build · trivy · CodeQL)

## Local development

### Quick bootstrap

```bash
bash scripts/setup.sh        # creates .env, installs python/node deps
make start                   # docker-compose stack (app + postgres)
make test                    # pytest + vitest
```

### Backend only

```bash
cd backend
cp .env.example .env         # then edit SECRET_KEY / CORS_ORIGINS / DB creds
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Required env vars: `MAIN_DB_*`, `SECRET_KEY` (≥16 chars), `CORS_ORIGINS`, and
`CREDENTIAL_ENCRYPTION_KEY` (Fernet key — required in production, optional in dev).

### Frontend only

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000 (proxies /api to :8000)
```

### Database

Postgres 15+. The schema files in [`database/`](./database) are picked up
automatically by the docker entrypoint. Alembic migrations live in
[`backend/alembic/versions/`](./backend/alembic/versions); apply with
`alembic upgrade head`.

## Main API areas

`POST /api/v1/auth/register` · `POST /api/v1/auth/login` · `GET /api/v1/auth/shuake-token`
`POST /api/v1/chaoxing/{login,sign}` · `GET /api/v1/chaoxing/courses`
`POST /api/v1/course/start` · `GET /api/v1/course/status/{task_id}`
`POST /api/v1/course/zhihuishu/{qr-login,password-login,tasks/course}`

## Deployment

> **Single source of truth: [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md).**
> Production uses `docker-compose.server.yml` + `Dockerfile.server` + host nginx.

```bash
cp .env.example .env       # fill SECRET_KEY, POSTGRES_PASSWORD, CREDENTIAL_ENCRYPTION_KEY, CORS_ORIGINS
docker compose -f docker-compose.server.yml -p university-helper up -d --build
```

Hotfix individual files to a running prod box (SSH-key auth preferred):
```bash
SERVER_IP=… SSH_KEY=~/.ssh/uh ./scripts/hotfix_publish.sh backend/app/main.py
```

## Security

- Backend container runs as **non-root** (UID/GID 10001), read-only rootfs, dropped capabilities.
- Postgres tuned with capped `max_connections`, slow-query logging, WAL compression.
- nginx enforces `Content-Security-Policy`, HSTS, frame-ancestors deny, rate-limits `/api/v1/auth/login` to 5r/min.
- Third-party credentials at rest are Fernet-encrypted (`CREDENTIAL_ENCRYPTION_KEY`).
- See [`.github/SECURITY.md`](./.github/SECURITY.md) for vulnerability reporting.

## Compliance

Use this project only within the rules of your school, platform, and local
laws. Review the risk and compliance implications before enabling automation
against third-party services.

## License

[MIT](./LICENSE)
