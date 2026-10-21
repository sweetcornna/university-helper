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
  <img src="docs/university-helper-promo.gif" alt="University Helper product film: while you sleep, it signs in, watches lectures and answers quizzes on Chaoxing and Zhihuishu, finishing by dawn" width="640" />
  <br />
  <sub><b>"You sleep, it studies."</b> A 60-second product film, rendered frame by frame with Remotion.</sub>
</p>

University Helper is a campus helper with a FastAPI backend and a React
frontend. The repository is called `university-helper`, but some container
names and env-var prefixes still use the old internal name `easy_learning`.
We are renaming those over time.

## Quick start

### Desktop app

Download the installer for your OS from the [latest release](../../releases/latest).
The desktop app (学道) bundles the backend and runs on your own machine, so you
don't need Docker, Postgres or Python. It is single-user: there is no account
to register, you open it and start.

| OS | Download | Notes |
|---|---|---|
| Windows 10/11 | `xuedao_<ver>_windows_x64-setup.exe` / `xuedao_<ver>_windows_x64.msi` | unsigned: SmartScreen → **More info → Run anyway** |
| macOS (Apple Silicon) | `xuedao_<ver>_darwin_aarch64.dmg` | unsigned: right-click the app → **Open** on first launch |
| macOS (Intel) | `xuedao_<ver>_darwin_x64.dmg` | same right-click → **Open** |
| Linux | `xuedao_<ver>_linux_amd64.AppImage` / `.deb` | `chmod +x *.AppImage && ./*.AppImage` |

Every release has installers for all the platforms above. Signed updater
artifacts and automatic updates are available only for releases where the
repository's Tauri signing secret is configured; without it, installers still
build but the release omits updater artifacts. The upstream repository refuses
to publish a release without that secret, so this only affects forks.

A few seconds after it starts, the app checks GitHub for a newer version. If
there is one, it shows the version and release notes and asks first. "现在更新"
downloads the update and restarts the app, which stops any running task.
"稍后" skips it until the next launch.

The installers are not code-signed by Apple or Microsoft yet, so the first
launch shows a warning. On macOS, try right-click → **Open** first. If
Gatekeeper says the app is damaged or should be moved to the Trash, drag it to
`/Applications` and remove the download quarantine flag:

```bash
xattr -dr com.apple.quarantine "/Applications/学道.app"
open "/Applications/学道.app"
```

Only run this for builds downloaded from this repository's GitHub Releases.

The app writes a log file, `desktop.log`, to `~/Library/Logs/xyz.cornna.shuake/`
on macOS, `%LOCALAPPDATA%\xyz.cornna.shuake\logs\` on Windows and
`~/.local/share/xyz.cornna.shuake/logs/` on Linux.

### One-command server deploy

On a clean server, install Docker and run the deploy script. It writes `.env`
with random secrets, pulls the prebuilt images from GHCR, starts Postgres, the
backend and the web container, and waits for `/health`. You don't need a git
checkout: when the script runs on its own, it first downloads the matching
source release into `./university-helper` (set `UH_INSTALL_DIR` to change that).

```bash
# Linux / macOS / WSL2, local access at http://localhost:8080
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y --admin-email you@example.com

# Plain http on a public IP
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y --host 203.0.113.10 --admin-email you@example.com

# A domain (ENV=production, https CORS, plus a host-nginx template for TLS)
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y --domain your.domain --admin-email you@example.com
```

On Windows with Docker Desktop:

```powershell
Invoke-WebRequest -UseBasicParsing https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.ps1 -OutFile deploy_server.ps1
powershell -ExecutionPolicy Bypass -File deploy_server.ps1 -Yes -AdminEmail you@example.com
```

From a checkout, the same scripts work directly:

```bash
git clone https://github.com/sweetcornna/university-helper.git
cd university-helper

# Linux / macOS / WSL2
bash scripts/deploy_server.sh --tag 1.4.7 -y                 # local: http://localhost:8080
bash scripts/deploy_server.sh --tag 1.4.7 --host 203.0.113.10 -y
bash scripts/deploy_server.sh --tag 1.4.7 --domain your.domain -y

# Windows (PowerShell + Docker Desktop)
pwsh scripts/deploy_server.ps1 -Tag 1.4.7 -Port 8080 -Yes
```

Useful options (PowerShell names in parentheses):

- `--tag` (`-Tag`): release to install. `1.4.7` and `v1.4.7` both work; the
  default is the latest release.
- `--port` (`-Port`): host port for the web container, 8080 by default.
- `--admin-email` (`-AdminEmail`): administrator emails, comma separated.
- `--allowed-hosts` (`-AllowedHosts`): extra hostnames or IPs people will open
  the site with, such as a LAN IP or a second domain.
- `--build` (`-Build`): build the images from source instead of pulling them.

Running the script again is safe. It keeps the secrets in `.env` and the
database, and applies the options you pass. To update, run it again
with the new version from the install directory:
`bash scripts/deploy_server.sh --tag <new version> -y`.
If the installer downloaded that directory, it also brings the compose file
and scripts up to that version first.

The server never updates itself. When GitHub has a newer release, administrators
see a notice in the web app with the new version, its release notes and the
update command to copy. Administrators are the emails in `ADMIN_EMAILS` (what
`--admin-email` sets). If that is empty, the first account registered on the
server is the administrator. The server checks every 6 hours. On a server
without internet access, set `UPDATE_CHECK_ENABLED=false` in `.env` and re-run
the deploy script.

### Local development

```bash
bash scripts/setup.sh        # creates .env, installs python/node deps
make start                   # docker-compose stack (app + postgres)
make test                    # pytest + vitest
```

On Windows, run these inside WSL2 with Docker Desktop's WSL integration turned on.

## For AI agents

Follow these steps when a user asks you to install University Helper. Run the
commands yourself and report what each check printed.

### 1. Pick the edition

- One person on their own computer: use the desktop app (step 7). It needs no
  Docker and no account.
- A shared server that several people open in a browser: use the server
  edition (steps 2 to 6).

### 2. Check the machine

```bash
docker info >/dev/null && echo "docker daemon ok"
docker compose version
curl --version | head -n 1
openssl version                        # generates the secrets on first install

# Port 8080 must be free. No output means free.
ss -ltn 'sport = :8080' | tail -n +2   # Linux
lsof -nP -iTCP:8080 -sTCP:LISTEN       # macOS
```

On Windows, check with `docker info`, `docker compose version` and
`Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue`.
If 8080 is taken, add `--port <free port>` (`-Port`) below and use that port in
every later URL.

### 3. Install without prompts

Always pass `-y` (`-Yes`). Without a terminal the script treats every question
as "no". Pick one line, and ask the user for the administrator email:

```bash
# local only
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y --admin-email admin@example.com
# public IP, plain http
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y --host 203.0.113.10 --admin-email admin@example.com
# domain; afterwards follow the nginx/certbot steps the script prints
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y --domain example.com --admin-email admin@example.com
```

```powershell
Invoke-WebRequest -UseBasicParsing https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.ps1 -OutFile deploy_server.ps1
powershell -ExecutionPolicy Bypass -File deploy_server.ps1 -Yes -AdminEmail admin@example.com
```

The files land in `./university-helper`. Run every later `docker compose` and
`scripts/` command from that directory.

### 4. Verify

```bash
curl -fsS http://127.0.0.1:8080/health
```

Expect `"status":"ok"` and `"schema":"ok"`. Right after a start, `schema` can
read `unknown` for a few seconds; retry for up to a minute. `missing_users` or
`missing_tenant_template` means registration will fail (see the table below).

Then register the first account. Usernames are 3 to 30 characters of `a-z` and
`0-9`. Passwords need at least 8 characters with an uppercase letter, a
lowercase letter and a digit.

```bash
curl -sS -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:8080/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","email":"admin@example.com","password":"ChangeMe123"}'
```

Expect `HTTP 201` and a JSON body with `access_token`. This account is an
administrator if its email is in `--admin-email`, or if no admin email was set
and it is the first account. To confirm, call
`GET /api/v1/system/update` with `Authorization: Bearer <access_token>`:
administrators get `200`, everyone else `403`. Registration is rate limited,
so on `429` wait a minute before retrying.

### 5. Fix common failures

| What you see | Fix |
|---|---|
| `400` with `"code":"InvalidHost"` or "Invalid host header" | The site was opened through a hostname or IP that is not in `CORS_ORIGINS` or `ALLOWED_HOSTS`. Re-run the install with `--allowed-hosts <host1,host2>`. |
| Register returns `503` "数据库还没初始化好", or `/health` shows `missing_users` / `missing_tenant_template` | The app creates the missing schema when it starts. Run `docker compose -p university-helper -f docker-compose.release.yml restart app`, wait for `"schema":"ok"`, then check `docker compose -p university-helper -f docker-compose.release.yml logs --tail=80 app postgres` if it stays broken. |
| Register returns `503` about CREATEDB | The database account cannot create databases. Grant `CREATEDB` to the Postgres role the app uses. |
| Start fails with "port is already allocated" or "address already in use" | Re-run with `--port <free port>`. |
| "Docker is running but this user cannot use it" | Run `sudo usermod -aG docker "$USER"`, log out and back in, then re-run. |
| "ENV=production requires https:// CORS_ORIGINS" | Use `--domain` for https, or `--host <ip>` for plain http. |

### 6. Don't

- Don't delete `.env` or the `university-helper_shuake-postgres-data` volume,
  and don't run `docker compose down -v`. `.env` holds the database password
  and `CREDENTIAL_ENCRYPTION_KEY`; without them the existing data can't be
  opened. The script refuses to continue when the volume exists but `.env` is
  gone.
- Don't set `ENV=production` for a site served over plain http on an IP. In
  production the app refuses to start with `http://` origins other than
  localhost. Use `--host` instead, which keeps `ENV=dev`.
- Don't set `ALLOWED_HOSTS=*` in production; the app refuses that too.
- Never commit `.env`. Back it up somewhere private.

### 7. Desktop app

Download the file for the user's OS from the latest release, for example
`gh release download --repo sweetcornna/university-helper --pattern 'xuedao_*_darwin_aarch64.dmg'`:

- Windows: `xuedao_<ver>_windows_x64-setup.exe` (or `xuedao_<ver>_windows_x64.msi`)
- macOS: `xuedao_<ver>_darwin_aarch64.dmg` (Apple Silicon) or `xuedao_<ver>_darwin_x64.dmg` (Intel)
- Linux: `xuedao_<ver>_linux_amd64.AppImage` or `xuedao_<ver>_linux_amd64.deb`

If macOS says the app is damaged, move it to `/Applications` and run
`xattr -dr com.apple.quarantine "/Applications/学道.app"`. When something goes
wrong, read `desktop.log` in `~/Library/Logs/xyz.cornna.shuake/` (macOS),
`%LOCALAPPDATA%\xyz.cornna.shuake\logs\` (Windows) or
`~/.local/share/xyz.cornna.shuake/logs/` (Linux).

## Highlights

- Multi-tenant: each user gets their own Postgres database (`tenant_<username>`), so no two users' data share a database.
- JWT-authenticated REST API on FastAPI 0.115, Pydantic v2 and psycopg2 connection pools.
- Chaoxing sign-in and Fanya course automation.
- Zhihuishu QR or password login, plus course task orchestration.
- React 18 + Vite 5 + Tailwind SPA with route-level code splitting, lazy-loaded heavy widgets, a global error boundary and authenticated routes.
- Hardened docker-compose: non-root runtime, multi-stage build, security headers, nginx rate limiting and encrypted backups.

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

- Backend: Python 3.11, FastAPI 0.115, Pydantic v2, psycopg2, PyJWT, bcrypt, Fernet credential encryption
- Frontend: React 18, Vite 5, React Router 6, Tailwind, lucide-react, leaflet
- Desktop: Tauri 2 shell around a PyInstaller build of the backend
- Data: PostgreSQL 15 (`max_connections=300`, `work_mem=8MB`)
- Migrations: Alembic
- Deployment: Docker + Compose in production, with host nginx in front of the app
- CI: GitHub Actions runs blocking checks for the backend (Ruff, Bandit,
  pytest), the frontend (ESLint, Vitest, build), the desktop Rust tests and the
  Docker image build. CodeQL runs separately. Trivy and `npm audit` are
  report-only; `mypy` is not currently run by CI.

## Supported platforms

The desktop app runs natively on Windows, macOS and Linux. The server edition
is a web app: Linux is the production target, and it runs anywhere Docker
runs, using the multi-arch images described below. Any device, Android
included, can use a server through the browser or the installed PWA.

| Platform | Status | Recommended path |
|---|---|---|
| Linux | Full local dev + production deployment | Docker Engine + Compose, Python 3.11, Node 20 |
| macOS | Local dev + deploy client | Docker Desktop or Colima, Python 3.11, Node 20 |
| Windows | Server (Docker Desktop) + deploy client | `scripts/deploy_server.ps1` (PowerShell) or WSL2 + `deploy_server.sh` |
| Android | End-user client | Install the PWA from Chrome/Edge; there is no native APK |

See [Platform Support](./docs/PLATFORMS.md) for platform-specific steps.

## Development details

### Backend only

```bash
cd backend
install -m 600 .env.example .env  # then edit SECRET_KEY / CORS_ORIGINS / DB creds
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Required env vars: `MAIN_DB_*`, `SECRET_KEY` (at least 16 characters),
`CORS_ORIGINS`, and `CREDENTIAL_ENCRYPTION_KEY` (a Fernet key, required in
production and optional in dev).

### Frontend only

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000 (proxies /api to :8000)
```

### Database

Postgres 15 or newer. The docker entrypoint runs the schema files in
[`database/`](./database) automatically. Alembic migrations live in
[`backend/alembic/versions/`](./backend/alembic/versions) and have separate
`main_db` and `tenant_db` heads. From `backend/`, upgrade the shared main
database with:

```bash
alembic upgrade main_db@head
```

From the repository root, upgrade every existing tenant database with:

```bash
python scripts/migrate_tenants.py
```

## Main API areas

`POST /api/v1/auth/register` · `POST /api/v1/auth/login` · `GET /api/v1/auth/shuake-token`
`POST /api/v1/chaoxing/{login,sign}` · `GET /api/v1/chaoxing/courses`
`POST /api/v1/course/start` · `GET /api/v1/course/status/{task_id}`
`POST /api/v1/course/zhihuishu/{qr-login,password-login,tasks/course}`
`GET /api/v1/system/update` (server edition, administrators only) · `GET /health`

## Answer banks (题库)

When the worker answers Chaoxing quizzes, it looks each question up in a
configurable answer bank (`tiku`). The answer is checked against the question
type and cached, so a quiz of N questions does O(1) cache reads. Choose the
source in `tiku_config.provider`; the Fanya page labels this field **题库来源**.

| Provider | `provider` value | Token | Notes |
|----------|------------------|-------|-------|
| 言溪题库 | `TikuYanxi` | required | General-purpose bank. |
| GO 题库 | `TikuGo` | optional | Free search source (网课小工具, `q.icodef.com`), throttled. |
| Like 题库 | `TikuLike` | required | Backup bank (datam.site). |
| 题库适配器 | `TikuAdapter` | none | Points at a self-hosted [tikuAdapter](https://github.com/DokiDoki1103/tikuAdapter) (`url`). |
| AI 智能答题 | `AI` | none | OpenAI-compatible LLM (`endpoint`/`key`/`model`). |
| 硅基流动 | `SiliconFlow` | required | SiliconFlow LLM. |
| 本地缓存 | `LocalCache` | none | Uses cached answers only and never calls an external API. |

### Fallback chain (多题库回退)

`provider` also takes an ordered, comma-separated list. The worker tries each
provider in turn and moves to the next one when a provider has no answer or
returns one that doesn't match the question type. Providers that can't start,
such as a bank without a token or an LLM without a key, are dropped from the
chain, so the chain keeps working as long as one provider does.

```jsonc
// tiku_config: try 言溪 first, then fall back to the free GO题库
{ "provider": "TikuYanxi,TikuGo", "token": "<yanxi-token>" }
```

> The shared answer cache is checked before any provider, so `LocalCache` only
> helps when it is selected on its own (cache-only mode).

## Deployment details

> [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md) is the full deployment guide.

Every release publishes multi-arch (amd64 + arm64) images to GHCR, so there is
nothing to compile:

- `ghcr.io/sweetcornna/university-helper-app`: the FastAPI backend
- `ghcr.io/sweetcornna/university-helper-web`: nginx with the built SPA

Release image tags have no leading `v` (`1.4.7`, not `v1.4.7`). The deploy
scripts accept either form.

### When registration fails

Registration needs the `users` table and the `tenant_template` database.
`curl http://127.0.0.1:8080/health` reports both in its `schema` field: `ok`,
`missing_users`, `missing_tenant_template` or `unknown` (the database could not
be checked). The app repairs a missing schema when it starts, so restarting the
`app` container is the first thing to try. The register page shows the
server's message, and the app log has the details. For an install made by the
deploy script:

```bash
docker compose -p university-helper -f docker-compose.release.yml restart app
docker compose -p university-helper -f docker-compose.release.yml logs --tail=80 app postgres
```

If the site is opened through an address the server doesn't know, the error
says "Invalid host header". Add that address with `--allowed-hosts`, or to
`ALLOWED_HOSTS` in `.env`, and re-run the deploy script.

### Manual (build from source)

This path runs Compose from the source tree behind host nginx. Install Docker
Compose and Node.js 20 (the version in `.nvmrc`) first. `Dockerfile.server`
only builds the backend, so build the SPA on the host before nginx serves it.

```bash
install -m 600 .env.example .env  # fill SECRET_KEY, POSTGRES_PASSWORD, CREDENTIAL_ENCRYPTION_KEY, CORS_ORIGINS
node --version              # must report 20.x
cd frontend && npm ci && npm run build
cd ..                       # return to the repository root
docker compose -f docker-compose.server.yml -p university-helper up -d --build
```

Check that `frontend/dist/` exists before pointing host nginx at it.

To hotfix individual files in the remote production checkout and rebuild the
app service (SSH key auth preferred):

```bash
SERVER_IP=… SSH_KEY=~/.ssh/uh ./scripts/hotfix_publish.sh backend/app/main.py
```

## Security

- The backend container runs as non-root (UID/GID 10001) with a read-only root filesystem and dropped capabilities.
- Postgres has a capped `max_connections`, slow-query logging and WAL compression.
- nginx sets `Content-Security-Policy`, HSTS and `frame-ancestors` deny, and limits `/api/v1/auth/login` to 5 requests per minute.
- Third-party credentials are stored encrypted with Fernet (`CREDENTIAL_ENCRYPTION_KEY`).
- Report vulnerabilities as described in [`.github/SECURITY.md`](./.github/SECURITY.md).

## Compliance

Use this project only within the rules of your school, the platforms involved
and local law. Think through the risks before you turn on automation against
third-party services.

## Acknowledgements

The Chaoxing and Zhihuishu automation is based on protocol research from the
open-source projects below, and in places adapts it. Thanks to their authors.

**Chaoxing 学习通: sign-in**
- [cxOrz/chaoxing-signin](https://github.com/cxOrz/chaoxing-signin): protocol reference for normal, photo, gesture, location and QR sign-in.

**Chaoxing 学习通: course automation (刷课)**
- [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing): unattended task-point completion for Chaoxing, Erya and Fanya. Our Chaoxing course module follows its overall approach.

**Zhihuishu 智慧树 / Zhidao 知到: course automation (刷课)**
- [luoyily/zhihuishu-tool](https://github.com/luoyily/zhihuishu-tool): reference for the Zhihuishu and Zhidao APIs and tooling.

**Question banks, font de-obfuscation and OCR (used directly)**
- [SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy](https://github.com/SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy): Chaoxing encrypted-font de-obfuscation and answer proxy (see `backend/app/services/course/chaoxing/cxsecret_font.py`, `answer_cache.py`).
- Server images fetch a pinned `resource/font_map_table.json` from [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing) during the Docker build and verify its SHA-256. The data file is not vendored in this repository; its upstream repository is GPL-3.0 licensed.
- [DokiDoki1103/tikuAdapter](https://github.com/DokiDoki1103/tikuAdapter): pluggable question-bank adapter (see `answer_providers/adapter.py`).
- [sml2h3/ddddocr](https://github.com/sml2h3/ddddocr): captcha OCR (see `captcha.py`).

Each of these projects has its own license; please follow its terms. If your
project is listed here and you want the attribution changed or removed, open an
issue.

## License

[MIT](./LICENSE)
