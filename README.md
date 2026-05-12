**Language:** English | [简体中文](./README.zh-CN.md)

# University Helper

University Helper is a full-stack campus helper project built around FastAPI and React. The repository name is `university-helper`, while parts of the source tree still use the historical internal name `easy_learning`.

The current codebase includes:

- User registration and login with JWT-based authentication
- Chaoxing sign-in APIs and task polling
- Chaoxing course-learning task management
- Zhihuishu QR-code/password login and course task orchestration
- PostgreSQL-backed multi-tenant data isolation
- React frontend pages for auth, dashboard, Chaoxing, and Zhihuishu workflows

## Repository Layout

```text
backend/        FastAPI application, services, schemas, tests
frontend/       React + Vite frontend
database/       SQL schema and tenant bootstrap scripts
nginx/          Reverse-proxy configuration
scripts/        Setup, test, backup, and deployment helpers
```

## Tech Stack

- Backend: Python 3.10+, FastAPI, Pydantic, psycopg2, JWT
- Frontend: React 18, Vite, React Router, Tailwind CSS, Zustand
- Data: PostgreSQL
- Deployment: Docker / Docker Compose

## Main API Areas

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/shuake-token`
- `POST /api/v1/chaoxing/login`
- `GET /api/v1/chaoxing/courses`
- `POST /api/v1/chaoxing/sign`
- `POST /api/v1/course/start`
- `GET /api/v1/course/status/{task_id}`
- `POST /api/v1/course/zhihuishu/qr-login`
- `POST /api/v1/course/zhihuishu/password-login`
- `POST /api/v1/course/zhihuishu/tasks/course`

## Local Development

### 1. Backend

```bash
cd backend
cp .env.example .env
pip install -r requirements.txt email-validator
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Before starting the backend, update `backend/.env` at least for:

- `MAIN_DB_HOST`
- `MAIN_DB_NAME`
- `MAIN_DB_USER`
- `MAIN_DB_PASSWORD`
- `SECRET_KEY`
- `CORS_ORIGINS`

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server listens on `http://localhost:3000` by default and proxies `/api` requests to `http://localhost:8000`.

### 3. Database

Use PostgreSQL 15+ and initialize the schema from the files under [`database/`](./database).

## Recommended Deployment Path

> **Single source of truth: [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md). Production deploy uses `scripts/hotfix_publish.sh` only.**

For server deployment, use:

- [`docker-compose.server.yml`](./docker-compose.server.yml)
- [`Dockerfile.server`](./Dockerfile.server)
- [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md)

Quick start:

```bash
cp .env.example .env
docker compose -f docker-compose.server.yml up -d --build
```

The root `.env.example` is prepared for `docker-compose.server.yml`. The legacy root-level `deploy.*` scripts have been moved to [`scripts/_legacy/`](./scripts/_legacy/) and must not be run.

## Testing

```bash
cd backend && pytest -q
cd frontend && npm run test
cd frontend && npm run lint
```

## Notes

- This repository contains active application code and some historical deployment helpers.
- Generated directories such as `node_modules`, `dist`, `__pycache__`, and `%TEMP%` are intentionally ignored.
- If you plan to expose the service publicly, rotate all passwords and JWT secrets before first deploy.

## Compliance

Use this project only within the rules of your school, platform, and local laws. Review the risk and compliance implications before enabling automation against third-party services.
