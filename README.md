**Language:** English | [简体中文](./README.zh-CN.md)

<p align="center">
  <img src="frontend/public/favicon.svg" width="72" alt="University Helper logo" />
</p>

<h1 align="center">University Helper</h1>

<p align="center">
  <a href="../../actions/workflows/test.yml"><img alt="CI" src="https://img.shields.io/github/actions/workflow/status/sweetcornna/university-helper/test.yml?branch=main&label=ci&style=flat-square" /></a>
  <a href="../../actions/workflows/codeql.yml"><img alt="CodeQL" src="https://img.shields.io/github/actions/workflow/status/sweetcornna/university-helper/codeql.yml?branch=main&label=codeql&style=flat-square" /></a>
  <a href="../../releases/latest"><img alt="Release" src="https://img.shields.io/github/v/release/sweetcornna/university-helper?style=flat-square&label=release" /></a>
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/github/license/sweetcornna/university-helper?style=flat-square" /></a>
  <img alt="python" src="https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white&style=flat-square" />
  <img alt="react" src="https://img.shields.io/badge/react-18-61DAFB?logo=react&logoColor=black&style=flat-square" />
  <img alt="fastapi" src="https://img.shields.io/badge/fastapi-0.115-009688?logo=fastapi&logoColor=white&style=flat-square" />
</p>

<p align="center">
  <strong>Demo:</strong>
  <a href="https://shuake.cornna.xyz">shuake.cornna.xyz</a>
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

## Quick Start

### Desktop app

Download the native installer for your OS from the [latest release](../../releases/latest).
It bundles the backend and runs locally without Docker, Postgres, or Python.

| OS | Download | Notes |
|---|---|---|
| Windows 10/11 | `University.Helper_<ver>_x64-setup.exe` / `.msi` | unsigned: SmartScreen → **More info → Run anyway** |
| macOS (Apple Silicon) | `University.Helper_<ver>_aarch64.dmg` | unsigned: right-click the app → **Open** on first launch |
| macOS (Intel) | `University.Helper_<ver>_x64.dmg` | same right-click → **Open** |
| Linux | `university-helper_<ver>_amd64.AppImage` / `.deb` | `chmod +x *.AppImage && ./*.AppImage` |

The app auto-updates from GitHub Releases. Builds are signed for the updater but
are not yet OS code-signed, so first launch may show Windows/macOS warnings.

### One-command server deploy

For a clean server, install Docker first, then run the guided deploy script. It
generates `.env`, pulls the prebuilt GHCR images, starts Postgres/backend/web,
and waits for `/health`.

```bash
git clone https://github.com/sweetcornna/university-helper.git
cd university-helper

# Linux / macOS / WSL2
bash scripts/deploy_server.sh --tag 1.4.1 -y                 # local: http://localhost:8080
bash scripts/deploy_server.sh --tag 1.4.1 --host 203.0.113.10 -y
bash scripts/deploy_server.sh --tag 1.4.1 --domain your.domain -y

# Windows (PowerShell + Docker Desktop)
pwsh scripts/deploy_server.ps1 -Tag 1.4.1 -Port 8080 -Yes
```

The scripts also accept `v1.4.1` and normalize it to the GHCR image tag
`1.4.1`. Add `--build` (`-Build` on Windows) to build from source instead of
pulling release images.

### Local development

```bash
bash scripts/setup.sh        # creates .env, installs python/node deps
make start                   # docker-compose stack (app + postgres)
make test                    # pytest + vitest
```

Windows users: run these commands inside WSL2, with Docker Desktop WSL
integration enabled.

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

## Supported platforms

University Helper is a web app. Linux is the production server target; macOS,
Linux, and Windows are supported as development/deployment clients; Android is
supported as a PWA client.

| Platform | Status | Recommended path |
|---|---|---|
| Linux | Full local dev + production deployment | Docker Engine + Compose, Python 3.11, Node 20 |
| macOS | Local dev + deploy client | Docker Desktop or Colima, Python 3.11, Node 20 |
| Windows | Server (Docker Desktop) + deploy client | `scripts/deploy_server.ps1` (PowerShell) or WSL2 + `deploy_server.sh` |
| Android | End-user client | Install the PWA from Chrome/Edge; no native APK is shipped |

"Runs on Windows/macOS/Linux" means the **server** runs anywhere Docker runs —
one command via the prebuilt multi-arch images below — and any device (Android
included) reaches it through the browser or installed PWA.

See [Platform Support](./docs/PLATFORMS.md) for platform-specific steps.

## Development Details

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

## Answer banks (题库)

When auto-answering Chaoxing quizzes, the worker resolves each question through a
configurable **answer bank** (`tiku`). The chosen answer is checked against the
question type and cached, so a quiz of N questions does O(1) cache reads. Set the
source(s) under `tiku_config.provider` (the Fanya page surfaces this as **题库来源**).

| Provider | `provider` value | Token | Notes |
|----------|------------------|-------|-------|
| 言溪题库 | `TikuYanxi` | required | General-purpose bank. |
| GO 题库 | `TikuGo` | optional | Free search source (网课小工具, `q.icodef.com`); throttled. |
| Like 题库 | `TikuLike` | required | Backup bank (datam.site). |
| 题库适配器 | `TikuAdapter` | — | Points at a self-hosted [tikuAdapter](https://github.com/DokiDoki1103/tikuAdapter) (`url`). |
| AI 智能答题 | `AI` | — | OpenAI-compatible LLM (`endpoint`/`key`/`model`). |
| 硅基流动 | `SiliconFlow` | required | SiliconFlow LLM. |
| 本地缓存 | `LocalCache` | — | Cache-only; never calls an external API. |

**多题库回退 (fallback chain).** `provider` accepts a comma-separated, ordered
list — the worker tries each in turn and falls through to the next when one
misses or returns a type-mismatched answer. Providers that can't initialize
(e.g. a token-less bank, or an LLM with no key) are dropped from the chain
automatically, so a mixed chain stays usable as long as one link works.

```jsonc
// tiku_config — try 言溪 first, then fall back to the free GO题库
{ "provider": "TikuYanxi,TikuGo", "token": "<yanxi-token>" }
```

> The shared answer cache is always consulted before any provider, so the
> `LocalCache` source only adds value when selected on its own (cache-only mode).

## Deployment Details

> **Single source of truth: [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md).**

Pre-built **multi-arch (amd64 + arm64)** images are published to GHCR on every
release, so there is nothing to compile:

- `ghcr.io/sweetcornna/university-helper-app` — FastAPI backend
- `ghcr.io/sweetcornna/university-helper-web` — nginx + the built SPA

Release image tags omit the leading `v` (`1.4.1`, not `v1.4.1`). The deploy
scripts accept either form.

### Manual (build from source)

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

## Acknowledgements

University Helper stands on the shoulders of the open-source community. Its
Chaoxing and Zhihuishu automation studies, learns from, and in places adapts the
protocol research of these excellent projects — sincere thanks to their authors:

**Chaoxing 学习通 — sign-in**
- [cxOrz/chaoxing-signin](https://github.com/cxOrz/chaoxing-signin) — protocol reference for normal / photo / gesture / location / QR sign-in.

**Chaoxing 学习通 — course automation (刷课)**
- [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing) — unattended task-point completion for Chaoxing / Erya / Fanya; our Chaoxing course module follows its overall approach.

**Zhihuishu 智慧树 / Zhidao 知到 — course automation (刷课)**
- [luoyily/zhihuishu-tool](https://github.com/luoyily/zhihuishu-tool) — Zhihuishu / Zhidao API tooling reference.

**Question banks, font de-obfuscation & OCR (used directly)**
- [SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy](https://github.com/SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy) — Chaoxing encrypted-font de-obfuscation & answer proxy (see `backend/app/services/course/chaoxing/cxsecret_font.py`, `answer_cache.py`).
- [DokiDoki1103/tikuAdapter](https://github.com/DokiDoki1103/tikuAdapter) — pluggable question-bank adapter (see `answer_providers/adapter.py`).
- [sml2h3/ddddocr](https://github.com/sml2h3/ddddocr) — captcha OCR (see `captcha.py`).

Each upstream project is distributed under its own license — please respect
those terms. If your project is listed here and you'd like the attribution
adjusted or removed, please open an issue.

## License

[MIT](./LICENSE)
