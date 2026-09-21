**Language:** English | [简体中文](#部署指南-简体中文)

# Deployment Guide

This is the deployment guide to follow for University Helper. The older deploy docs (`DEPLOY.md`, `DEPLOY_GUIDE*.md`, `DEPLOY_MANUAL*.md`) are archived under [`docs/_archive/`](./_archive/) and are out of date.

> Changes to the production box ship through `scripts/hotfix_publish.sh` and nothing else.
> Production is `root@8.134.33.19:/opt/university-helper`. The old root-level `deploy.sh`,
> `deploy.ps1`, `deploy_auto.py`, `deploy_pure.py` and `server_deploy.sh` scripts now live in
> [`scripts/_legacy/`](../scripts/_legacy/). They target the stale `/opt/easy_learning` path and
> overwrite the production `.env`, so do not run them.

---

## Quick start: a fresh server (one command)

Use the guided installer to run University Helper on a new Docker host of your own. It is not
how the existing production box gets updates; that box uses the hotfix flow further down.

On Linux, macOS or WSL2 you do not need a checkout. The installer downloads the source of the
release it installs:

```bash
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- --domain <your-domain> --admin-email you@example.com -y
```

From a git checkout, the script uses the files next to it:

```bash
git clone https://github.com/sweetcornna/university-helper.git
cd university-helper
bash scripts/deploy_server.sh --domain <your-domain>     # production with TLS
# or:  bash scripts/deploy_server.sh --host <server-ip>  # plain-http on an IP
# or:  bash scripts/deploy_server.sh --build             # build from source instead of pulling
```

On the first run it writes a `.env` with random secrets. It then pulls the prebuilt multi-arch
images from GHCR (`ghcr.io/sweetcornna/university-helper-{app,web}`), or builds them locally
with `--build`, starts app, postgres and web, waits for `/health`, and checks that the database
is ready for registration. With `--domain` it also writes a host-nginx template under
`deploy/nginx/` and prints the `certbot` commands that finish TLS.

Without a checkout, the source is unpacked into `./university-helper`. Set `UH_INSTALL_DIR` to
pick another directory, or `UH_DEPLOY_OFFLINE=1` to forbid downloads. The `.env` ends up in that
directory, so run later commands from there.

| Option | Effect |
|---|---|
| `--domain <fqdn>` | `ENV=production`, an `https://` CORS origin and the host-nginx template |
| `--host <ip>` | plain http on that IP (`ENV=dev`); the web port binds to `0.0.0.0` |
| `--port <port>` | host port of the web container (default `8080`) |
| `--tag <tag>` | release to install, `1.4.7` or `v1.4.7` (default: latest) |
| `--admin-email <emails>` | administrator emails, comma separated (see the update notice below) |
| `--allowed-hosts <list>` | extra hostnames or IPs people open the site with, comma separated |
| `--build` | build the images from source instead of pulling them |
| `--no-tls` | with `--domain`, skip the nginx template |
| `-y`, `--yes` | answer yes to every prompt |

Without `--domain` or `--host`, the site is only reachable locally at `http://localhost:8080`.
With `--host` and no `--allowed-hosts`, an empty `ALLOWED_HOSTS` is filled with the server's own
IPv4 addresses (Linux only).

Windows hosts with Docker Desktop use `scripts/deploy_server.ps1`. It behaves the same way, takes
`-Domain`, `-HostIp`, `-Port`, `-Tag`, `-AdminEmail`, `-AllowedHosts`, `-Build` and `-Yes`, and
does not write the nginx template. Without a checkout:

```powershell
Invoke-WebRequest -UseBasicParsing https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.ps1 -OutFile deploy_server.ps1
powershell -ExecutionPolicy Bypass -File deploy_server.ps1 -Yes
```

The installer wraps [`docker-compose.release.yml`](../docker-compose.release.yml).
[`.github/workflows/release.yml`](../.github/workflows/release.yml) publishes the images on every
`v*` Git tag, with image tags like `1.4.1` (no leading `v`); the scripts accept `1.4.1` and
`v1.4.1`. Every service has `restart: unless-stopped`, so the stack comes back after a reboot as
soon as Docker starts.

### Running the installer again

Re-run the installer to change a setting or to upgrade. It keeps whatever already works:

- Secrets in `.env` stay as they are. Missing or example secrets are generated, except that an
  example `POSTGRES_PASSWORD` is kept when the database already uses it. A `SECRET_KEY` shorter
  than 32 characters is replaced, which signs everyone out.
- Options you pass are written to `.env`. Options you leave out keep their current values, so a
  bare re-run does not reset the port, bind address, CORS origins, `ENV`, `ALLOWED_HOSTS` or
  `ADMIN_EMAILS`.
- If the database volume `university-helper_shuake-postgres-data` exists but `.env` is missing,
  or `POSTGRES_PASSWORD` is empty, the script stops. A new password cannot open the existing
  data, so restore `.env` from your backup.
- A `CREDENTIAL_ENCRYPTION_KEY` that is not a valid Fernet key also stops the script, because
  replacing it would make stored platform credentials unreadable.
- `ENV=production` together with a plain `http://` origin other than localhost is refused before
  anything starts.
- If `docker compose up` fails, the script prints the container list and the last app and
  postgres logs. `.env` and the database are left in place.

Keep a backup of `.env`. Without `CREDENTIAL_ENCRYPTION_KEY` the stored platform credentials
cannot be decrypted, and without `POSTGRES_PASSWORD` you cannot open the database.

### New-version notice

The server looks for a newer release on GitHub 30 seconds after it starts and then every 6 hours
(`UPDATE_CHECK_INTERVAL_SECONDS`). Drafts and pre-releases are ignored. When there is a newer
version, administrators see a dialog in the web app with the version, its release notes and the
command that upgrades the install:

```bash
bash scripts/deploy_server.sh --tag <version> -y
```

```powershell
pwsh scripts/deploy_server.ps1 -Tag <version> -Yes
```

Administrators are the accounts whose email is in `ADMIN_EMAILS` (comma separated, case
insensitive). If it is empty, the first account ever registered is the administrator. Set it with
`--admin-email`, or type it when the interactive installer asks. Other users never get the dialog:
the endpoint behind it, `GET /api/v1/system/update`, answers 403 for them. An administrator can
skip a version or be reminded 24 hours later; that choice is stored in their browser.

The server does not update itself, because the app container has no access to the Docker socket.
An administrator runs the command from the install directory. In a directory the installer
downloaded, it first swaps in that release's compose file and scripts (`.env` and the data stay);
a git checkout is left alone, and the script asks you to check out the matching tag. On servers
that cannot reach GitHub, set `UPDATE_CHECK_ENABLED=false`; a failed check is only logged. The existing production
box keeps shipping through `scripts/hotfix_publish.sh`, so ignore the installer command there.

The rest of this guide covers the existing `shuake.cornna.xyz` production box.

---

## Production Topology (authoritative)

| Concern | Value |
|---|---|
| Public URL | `https://shuake.cornna.xyz` |
| Server IP | `8.134.33.19` |
| SSH target | `root@8.134.33.19` |
| Server install root | `/opt/university-helper` |
| Compose binary | standalone `docker-compose` (not the `docker compose` v2 plugin) |
| Compose files | `docker-compose.server.yml` + `docker-compose.newhost.yml` (root) |
| Compose project | `university-helper` |
| Backend image | built from `Dockerfile.server` (root) |
| App container | `shuake-easy-learning-app` on `127.0.0.1:8000` |
| Frontend / web container | `shuake-easy-learning-web` (`nginx:1.27-alpine`) serves the read-only `frontend/dist/` bind mount and proxies `/api/` and `/ws` to `app:8000` |
| Web publish port | `127.0.0.1:18082` (container port 80) |
| Database | PostgreSQL 15 in container |
| TLS / reverse proxy | host nginx (managed outside Compose), proxying to `http://127.0.0.1:18082` |
| Authoritative deploy script | `scripts/hotfix_publish.sh` |
| App health check | `http://127.0.0.1:8000/health` (script default) |

The `web` container, `shuake-easy-learning-web`, is an nginx that runs inside the stack. Host
nginx is a separate process that only terminates TLS and proxies to `127.0.0.1:18082`. The
repository's `nginx/` files are mounted into the web container. There is no root `Dockerfile`,
`Dockerfile.nginx` or `docker-compose.yml` any more.

---

## Local Development

For local development, follow the root [`README.md`](../README.md): `uvicorn` for the backend and
`vite` for the frontend. Only run Docker locally when you are reproducing a bug that happens in
production alone.

---

## Environment Variables (production)

The production `.env` is `/opt/university-helper/.env` on the server. Automation must never
overwrite it. Required keys come first, optional ones after:

```env
POSTGRES_PASSWORD=<rotated, never commit>
SECRET_KEY=<>=32 chars, rotated, never commit>
SHUAKE_COMPAT_SECRET=<optional>
CORS_ORIGINS=["https://shuake.cornna.xyz"]
APP_PORT=8000
ENV=production
# Fernet key (urlsafe-base64), generated with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Required in production; the app refuses to start without it.
CREDENTIAL_ENCRYPTION_KEY=<rotated, never commit>

# Optional. Extra hostnames/IPs the site is opened with, comma separated.
ALLOWED_HOSTS=
# Optional. Administrator emails; empty means the first registered account.
ADMIN_EMAILS=
# Optional. Set to false on servers that cannot reach GitHub.
UPDATE_CHECK_ENABLED=true
```

To seed a fresh server by hand, copy `.env.example` and fill in real secrets. Never commit a
filled-in `.env`.

The app container reads `.env` only when it is created. After changing a value, recreate it:

```bash
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml up -d app
```

---

## ⚠️ Database Migrations — REQUIRED on every existing deployment

**`database/*.sql` runs ONLY on an empty Postgres data directory.** Nothing in
`Dockerfile.server`, the compose files, or the deploy workflow runs Alembic, so
on any server whose volume already has data, **new tables do not appear until you
run the migration by hand.**

This repo has **two** migration branches (`main_db` and `tenant_db`), so a plain
`alembic upgrade head` is ambiguous. Always branch-qualify:

```bash
# Main database (users, rate_limit_counters, email_verification_codes)
docker compose -f docker-compose.server.yml exec app alembic upgrade main_db@head

# Tenant databases (per-user todos/attachments/sessions)
docker compose -f docker-compose.server.yml exec app python scripts/migrate_tenants.py
```

All migrations use idempotent DDL, so re-running is safe.

### Before turning on `EMAIL_VERIFICATION_ENABLED`

Registration codes and password reset store rows in `email_verification_codes`,
which is created by migration `003`. Run

```bash
docker compose -f docker-compose.server.yml exec app alembic upgrade main_db@head
```

**before** setting `EMAIL_VERIFICATION_ENABLED=true`. If the flag is on and the
table is missing, `/api/v1/auth/send-code` and `/api/v1/auth/reset-password`
answer **503 `邮箱验证服务未初始化，请联系管理员执行数据库迁移`** and the app log
carries `email_verification_codes table is missing; run 'alembic upgrade
main_db@head' against the main database`.

---

## Deploying a Hotfix (small code change)

This is the only supported way to ship ongoing changes. The script's production defaults are
`root@8.134.33.19`, `/opt/university-helper`, the standalone `docker-compose` binary, and both
`docker-compose.server.yml` and `docker-compose.newhost.yml` under the `university-helper`
project.

Before any publish that is not a dry run, set up a trusted OpenSSH `known_hosts` file for the
exact `SERVER_IP`. Get the complete host-key line, or at least check its fingerprint, through the
server console, the cloud provider, or an administrator workstation that already trusts the host.
Do not accept whatever key an online scan returns on first contact.

```bash
export SSH_KNOWN_HOSTS_FILE="$HOME/.ssh/uh_known_hosts"
chmod 600 "$SSH_KNOWN_HOSTS_FILE"
# Put the verified, complete known_hosts line for SERVER_IP in this file.
```

The GitHub Actions deploy reads the same trusted lines from the `SERVER_SSH_KNOWN_HOSTS` secret.
Before it opens a connection, the publisher refuses a host-key file that is missing, empty,
unparseable or does not match the server.

SSH key auth is preferred. The script uses it whenever `SSH_KEY` is set or an agent holds the key.

```bash
export SERVER_IP=8.134.33.19
export SSH_KEY=~/.ssh/uh

./scripts/hotfix_publish.sh \
  backend/app/api/v1/course.py
```

Password auth through sshpass still works but prints a warning:

```bash
export EASY_LEARNING_SERVER_IP=8.134.33.19
export EASY_LEARNING_SERVER_PASSWORD=<from secrets manager>
./scripts/hotfix_publish.sh backend/app/main.py
```

How it works:

- Only the listed files are synced into `/opt/university-helper/` on the server.
- Compose runs as the standalone `docker-compose -p university-helper -f
  docker-compose.server.yml -f docker-compose.newhost.yml`. Do not swap in the `docker compose`
  v2 plugin on this host.
- Backend files are uploaded into the server's repository checkout. The script checks that the
  selected Compose files define a buildable `app` service and runs
  `up -d --build --no-deps --force-recreate app`. The app container is read-only and gets replaced
  from the new image; nothing is copied into a running container.
- Before a remote file is replaced, it is copied to a unique temporary backup in the same
  directory. The upload is written to a temporary file in that directory and published with
  `rename`. This works per file and does not make the overall multi-file and container update
  atomic.
- The temporary backups are removed once the new container is healthy, its full SHA-256 image ID
  matches what Compose expects, and the bounded HTTP health check passes. If the upload, build or
  health check fails, the script restores or deletes the source files, retags the old image,
  recreates the old service without building, and checks that the restored container runs the
  exact old image ID and is healthy. A failed rollback is reported as fatal and left for manual
  recovery. Image-only topologies, such as the release Compose file, are refused before anything
  is uploaded.
- Frontend changes ship only as a built artifact. From the repository root:

  ```bash
  cd frontend && npm ci && npm run build
  cd ..
  ./scripts/hotfix_publish.sh --frontend
  ```

  This syncs `/opt/university-helper/frontend/dist/`, which is bind-mounted into the
  `shuake-easy-learning-web` nginx container, and reloads that container's nginx. Per-file mode
  does not accept frontend source paths.
- Changes to the dependency layer (`backend/requirements.txt`, `Dockerfile.server`) rebuild the
  whole app image.

For backend changes the script waits for the Compose healthcheck, then polls
`http://127.0.0.1:8000/health` (its default `HEALTH_URL`). The same endpoint is reachable through
the web container at `http://127.0.0.1:18082/health`, which is where host nginx sends public
traffic. The web container depends on a healthy app, so when something breaks end to end, check
both the direct app endpoint and the `18082` path.

---

## First-Time Server Bootstrap

Use this only when a new server (rare) has to match the current production topology. For any
other new host, the quick start at the top is simpler.

1. `ssh root@<server>`
2. `mkdir -p /opt/university-helper && cd /opt/university-helper`
3. `git clone <repo> .` or `rsync <source>/ ./` the source into the current directory (excluding `.env`, `node_modules`, `dist`, `__pycache__`).
4. Create `/opt/university-helper/.env` by hand with real secrets (see above).
5. Install Node.js 20 (the version in `.nvmrc`). From the repository root, build the SPA before starting the web container:
   ```bash
   node --version  # must report 20.x
   cd frontend && npm ci && npm run build
   cd ..           # return to the repository root
   ```
6. Confirm that `frontend/dist/` exists. `Dockerfile.server` builds only the backend, so the SPA has to exist before the `web` overlay starts and bind-mounts it.
7. Start both Compose files with the standalone binary:
   ```bash
   docker-compose -p university-helper \
     -f docker-compose.server.yml -f docker-compose.newhost.yml up -d --build
   ```
8. Configure host nginx to terminate TLS for `shuake.cornna.xyz` and
   `proxy_pass http://127.0.0.1:18082` (the web container). Host nginx should not serve
   `frontend/dist/` itself.
9. Check the app and web paths:
   ```bash
   curl -fsS http://127.0.0.1:8000/health
   curl -fsS http://127.0.0.1:18082/health
   curl -fsS https://shuake.cornna.xyz/health
   ```
   Each response should report `schema` as `ok`. Anything else means registration will fail;
   see Troubleshooting.

---

## Operations

```bash
# Status
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml ps

# Logs
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml logs -f app
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml logs -f postgres
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml logs -f web

# DB shell
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml exec postgres \
  psql -U easylearning -d main_db

# Encrypted DB backup (recommended)
AGE_RECIPIENT=age1xxxxxx... ./scripts/db_backup.sh
# - dumps pg_dumpall through age → /opt/backups/university-helper/uh-<stamp>.sql.gz.age
# - refuses to write plaintext .env snapshots unless ALLOW_UNENCRYPTED=1

# Alembic migrations (idempotent baselines). ALWAYS branch-qualified — there are
# two branches (main_db / tenant_db) and a bare `upgrade head` is ambiguous.
# Shared users/rate-limit schema in main_db:
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml exec app \
  alembic upgrade main_db@head

# Tenant schemas: mount the repository helper into the app context and run it
# from the app's /srv/backend working directory so it can reach postgres:
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml run --rm \
  -v "$PWD/scripts:/srv/backend/scripts:ro" app \
  python scripts/migrate_tenants.py
```

## Staging on the same host

```bash
docker-compose \
  -f docker-compose.server.yml -f docker-compose.staging.yml \
  -p uh-staging up -d --build
```

The overlay publishes the app on `127.0.0.1:8001`, gives it its own `shuake-postgres-staging-data` volume, lowers the resource limits and renames the containers, so the production stack is not touched.

---

## Troubleshooting

- **Registration fails with 503 `DatabaseNotInitializedError`.** The database has no `users`
  table or no `tenant_template` database. Postgres runs its init scripts only on a brand-new data
  volume, so a reused or half-initialised volume can lack them. At startup the app checks for both
  and recreates what is missing from the SQL files bundled in the image (`DB_AUTO_BOOTSTRAP`, on
  by default). A registration that finds no template also tries one repair. `/health` reports the
  result in `schema`: `ok`, `missing_users`, `missing_tenant_template` or `unknown`. Anything
  other than `ok` sets `status` to `degraded`, and the endpoint still answers 200. Read the app
  logs, re-run the installer, or apply the SQL by hand as described in
  [`database/README.md`](../database/README.md).
- **Registration fails with 503 `TenantProvisioningError`.** The message names the cause.
  "数据库正忙" means another connection kept using `tenant_template` (a running `pg_dumpall`
  backup, for example) through several retries; try again. "没有建库权限（CREATEDB）" means the
  database role cannot create databases. The role in the bundled Postgres container is a
  superuser, so this happens with an external Postgres whose role lacks `CREATEDB`.
  "数据库暂时连不上" means Postgres cannot be reached.
- **Some usernames are refused.** `template`, `template0`, `template1`, `postgres`, `main`,
  `maindb`, `root` and `system` are reserved, and registering one returns
  "该用户名为系统保留名称，请换一个".
- **400 with `"code": "InvalidHost"` (message starting with `Invalid host header`).** The site was
  opened through a hostname or IP the app does not allow. `localhost`, `127.0.0.1` and the hosts in
  `CORS_ORIGINS` are always allowed. Add anything else, such as a LAN IP or a second domain, to
  `ALLOWED_HOSTS` (comma separated; `*.example.com` matches its subdomains). On an installer
  deployment, re-run it with `--allowed-hosts`; on the production box, edit `.env` and recreate the
  app container. The app logs a warning the first time it rejects a host. With `ENV=production`,
  `ALLOWED_HOSTS=*` stops the app from starting.
- **The installer cannot use Docker.** When the current user is not in the `docker` group, the
  script falls back to passwordless `sudo` if that works. Otherwise run
  `sudo usermod -aG docker "$USER"`, log out and back in, and re-run it.
- **Port 8080 is taken on an installer deployment.** Re-run the installer with `--port <port>`.
- **Port conflict on 8000.** `APP_PORT` is the app's host-local port and the port the hotfix
  script checks directly. Change it in the Compose environment and keep the script's `HEALTH_URL`
  in step. The web container still reaches `app:8000` over the Compose network.
- **Port conflict on 18082.** Keep the web publish port and the host nginx `proxy_pass` in step,
  and expose the web container only through the host reverse proxy.
- **Frontend changes do not appear.** Check that `/opt/university-helper/frontend/dist/` was
  updated and `shuake-easy-learning-web` was reloaded, then bypass its cache
  (`curl -H "Cache-Control: no-cache" http://127.0.0.1:18082/`).
- **`apt-get` fails during the image build.** Keep runtime apt dependencies in `Dockerfile.server`
  to a minimum, so that deploys do not depend on upstream Debian mirrors.

---

# 部署指南 (简体中文)

University Helper 的部署以本文为准。旧的部署文档（`DEPLOY.md`、`DEPLOY_GUIDE*.md`、`DEPLOY_MANUAL*.md`）已归档到 [`docs/_archive/`](./_archive/)，内容已过时，不要再照着做。

> 生产机上的改动只通过 `scripts/hotfix_publish.sh` 发布。生产目标是
> `root@8.134.33.19:/opt/university-helper`。仓库根目录原来的 `deploy.sh`、`deploy.ps1`、
> `deploy_auto.py`、`deploy_pure.py`、`server_deploy.sh` 已移到
> [`scripts/_legacy/`](../scripts/_legacy/)。它们指向已废弃的 `/opt/easy_learning` 路径，
> 还会覆盖生产 `.env`，不要运行。

---

## 快速开始：全新服务器（一条命令）

想在自己的新 Docker 主机上跑 University Helper，用引导式安装脚本。现有生产机不走这条路，
它用下文的热修流程更新。

在 Linux、macOS 或 WSL2 上不需要先克隆仓库，脚本会自己下载所装版本的源码：

```bash
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- --domain <your-domain> --admin-email you@example.com -y
```

在已克隆的仓库里，脚本直接使用旁边的文件：

```bash
git clone https://github.com/sweetcornna/university-helper.git
cd university-helper
bash scripts/deploy_server.sh --domain <your-domain>     # 带 TLS 的生产部署
# 或:  bash scripts/deploy_server.sh --host <server-ip>  # 用 IP 走纯 http
# 或:  bash scripts/deploy_server.sh --build             # 从源码构建，不拉镜像
```

第一次运行时，脚本生成带随机密钥的 `.env`；然后从 GHCR 拉取预构建的多架构镜像
（`ghcr.io/sweetcornna/university-helper-{app,web}`），或在 `--build` 时本地构建；接着启动
app、postgres 和 web，等 `/health` 通过，并确认数据库已经可以注册。加了 `--domain` 时，
它还会在 `deploy/nginx/` 下写一份宿主机 nginx 模板，并打印完成 TLS 所需的 `certbot` 命令。

没有克隆仓库时，源码解压到 `./university-helper`。可以用 `UH_INSTALL_DIR` 换目录，
设 `UH_DEPLOY_OFFLINE=1` 则禁止下载。`.env` 也在那个目录里，之后的命令都在那里执行。

| 参数 | 作用 |
|---|---|
| `--domain <fqdn>` | `ENV=production`、`https://` 的 CORS 来源，并生成宿主机 nginx 模板 |
| `--host <ip>` | 用该 IP 走纯 http（`ENV=dev`），web 端口绑定到 `0.0.0.0` |
| `--port <port>` | web 容器在宿主机上的端口（默认 `8080`） |
| `--tag <tag>` | 要安装的版本，`1.4.7` 或 `v1.4.7` 均可（默认最新版） |
| `--admin-email <emails>` | 管理员邮箱，多个用逗号分隔（见下文的新版本提醒） |
| `--allowed-hosts <list>` | 用户访问站点时用的其他域名或 IP，逗号分隔 |
| `--build` | 从源码构建镜像，不从 GHCR 拉取 |
| `--no-tls` | 与 `--domain` 同用时，不生成 nginx 模板 |
| `-y`, `--yes` | 所有提示都回答 yes |

不带 `--domain` 或 `--host` 时，站点只能在本机通过 `http://localhost:8080` 访问。
带 `--host` 但没带 `--allowed-hosts` 时，如果 `ALLOWED_HOSTS` 为空，脚本会填入本机的
IPv4 地址（仅 Linux）。

Windows 上装了 Docker Desktop 的主机用 `scripts/deploy_server.ps1`。行为相同，参数是
`-Domain`、`-HostIp`、`-Port`、`-Tag`、`-AdminEmail`、`-AllowedHosts`、`-Build`、`-Yes`，
不生成 nginx 模板。不克隆仓库时这样运行：

```powershell
Invoke-WebRequest -UseBasicParsing https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.ps1 -OutFile deploy_server.ps1
powershell -ExecutionPolicy Bypass -File deploy_server.ps1 -Yes
```

安装脚本封装的是 [`docker-compose.release.yml`](../docker-compose.release.yml)。
每打一个 `v*` Git tag，[`.github/workflows/release.yml`](../.github/workflows/release.yml)
就会发布镜像，镜像 tag 形如 `1.4.1`（不带 `v`），脚本 `1.4.1` 和 `v1.4.1` 两种写法都接受。
所有服务都设了 `restart: unless-stopped`，服务器重启后只要 Docker 起来，整套服务就会自动恢复。

### 再次运行安装脚本

修改配置或升级版本，都是重新运行安装脚本。已经能用的配置它不会动：

- `.env` 里已有的密钥保持不变。缺失的或仍是示例值的密钥会自动生成；但如果数据库已经在用示例
  `POSTGRES_PASSWORD`，这个值会保留。`SECRET_KEY` 短于 32 个字符时会被替换，所有人需要重新登录。
- 这次传入的参数会写进 `.env`；没传的参数沿用当前值。所以不带参数重跑，不会重置端口、绑定地址、
  CORS 来源、`ENV`、`ALLOWED_HOSTS` 或 `ADMIN_EMAILS`。
- 如果数据卷 `university-helper_shuake-postgres-data` 已存在，但 `.env` 不见了或
  `POSTGRES_PASSWORD` 为空，脚本会停下。新密码打不开已有数据，请从备份恢复 `.env`。
- `CREDENTIAL_ENCRYPTION_KEY` 不是合法的 Fernet 密钥时，脚本同样会停下，因为换掉它会让已保存的
  平台凭据无法解密。
- `ENV=production` 却配了 localhost 以外的 `http://` 来源时，脚本在启动任何服务前就会拒绝。
- `docker compose up` 失败时，脚本会打印容器列表和 app、postgres 的最近日志，`.env` 和数据库都保留。

请备份 `.env`。丢了 `CREDENTIAL_ENCRYPTION_KEY`，已保存的平台凭据就无法解密；丢了
`POSTGRES_PASSWORD`，就进不了数据库。

### 新版本提醒

服务启动 30 秒后会去 GitHub 查一次有没有新版本，之后每 6 小时查一次
（`UPDATE_CHECK_INTERVAL_SECONDS`），草稿和预发布版本不算。有新版本时，管理员在网页里会看到
一个弹窗，写着版本号、更新说明和升级命令：

```bash
bash scripts/deploy_server.sh --tag <version> -y
```

```powershell
pwsh scripts/deploy_server.ps1 -Tag <version> -Yes
```

管理员是邮箱列在 `ADMIN_EMAILS` 里的账号（逗号分隔，不区分大小写）。留空时，第一个注册的账号
就是管理员。可以用 `--admin-email` 设置，也可以在交互式安装时按提示填写。其他用户看不到这个弹窗，
它背后的接口 `GET /api/v1/system/update` 对他们返回 403。管理员可以跳过某个版本，或者 24 小时后
再提醒，这个选择保存在各自的浏览器里。

服务端不会自己升级，因为 app 容器访问不到 Docker socket，需要管理员在安装目录里执行上面的命令。
如果安装目录是脚本自己下载的，它会先换成该版本的 compose 文件和脚本，`.env` 和数据不动；
如果是 git 仓库，脚本不改文件，只提醒你先切到对应的 tag。
服务器连不上 GitHub 时，把 `UPDATE_CHECK_ENABLED` 设为 `false`；检查失败只会写一条日志。
现有生产机继续用 `scripts/hotfix_publish.sh` 发布，那里不要执行弹窗里的安装命令。

下文说明现有的 `shuake.cornna.xyz` 生产机。

---

## 生产拓扑（权威）

| 项 | 值 |
|---|---|
| 对外域名 | `https://shuake.cornna.xyz` |
| 服务器 IP | `8.134.33.19` |
| SSH 目标 | `root@8.134.33.19` |
| 服务器安装根目录 | `/opt/university-helper` |
| Compose 二进制 | 独立的 `docker-compose`（不是 `docker compose` v2 插件） |
| Compose 文件 | 仓库根目录的 `docker-compose.server.yml` + `docker-compose.newhost.yml` |
| Compose 项目 | `university-helper` |
| 后端镜像 | 由根目录 `Dockerfile.server` 构建 |
| app 容器 | `shuake-easy-learning-app`，发布在 `127.0.0.1:8000` |
| 前端 / web 容器 | `shuake-easy-learning-web`（`nginx:1.27-alpine`）从只读 bind mount 提供 `frontend/dist/`，并将 `/api/`、`/ws` 反代到 `app:8000` |
| Web 发布端口 | `127.0.0.1:18082`（容器端口 80） |
| 数据库 | PostgreSQL 15 容器 |
| TLS / 反代 | 宿主机 nginx（不在 Compose 内），反代到 `http://127.0.0.1:18082` |
| 唯一部署脚本 | `scripts/hotfix_publish.sh` |
| app 健康检查 | `http://127.0.0.1:8000/health`（脚本默认值） |

`web` 容器 `shuake-easy-learning-web` 是栈内的 nginx，和宿主机 nginx 是两回事。宿主机 nginx
只负责 TLS 终结，再反代到 `127.0.0.1:18082`。仓库里的 `nginx/` 文件挂载进 web 容器。
仓库根目录已经没有 `Dockerfile`、`Dockerfile.nginx` 和 `docker-compose.yml`。

---

## 本地开发

本地开发按根目录的 [`README.zh-CN.md`](../README.zh-CN.md) 来：后端用 `uvicorn`，前端用 `vite`。
只有在复现仅生产环境才出现的 bug 时，才需要在本地起 Docker。

---

## 环境变量（生产）

生产 `.env` 是服务器上的 `/opt/university-helper/.env`，任何自动化都不能覆盖它。先列必填项，
后面是可选项：

```env
POSTGRES_PASSWORD=<已轮换，禁止入仓>
SECRET_KEY=<至少 32 字符，已轮换，禁止入仓>
SHUAKE_COMPAT_SECRET=<可选>
CORS_ORIGINS=["https://shuake.cornna.xyz"]
APP_PORT=8000
ENV=production
# Fernet 密钥（urlsafe-base64），生成命令：
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 生产环境必填；应用缺失该密钥时会拒绝启动。密钥禁止入仓。
CREDENTIAL_ENCRYPTION_KEY=<已轮换，禁止入仓>

# 可选：用户访问站点时用的其他域名或 IP，逗号分隔。
ALLOWED_HOSTS=
# 可选：管理员邮箱；留空表示第一个注册的账号。
ADMIN_EMAILS=
# 可选：服务器连不上 GitHub 时设为 false。
UPDATE_CHECK_ENABLED=true
```

要手动初始化一台新服务器，复制 `.env.example` 再填入真实密钥。填了真实值的 `.env` 不要提交。

app 容器只在创建时读取 `.env`。改了值之后要重建它：

```bash
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml up -d app
```

---

## ⚠️ 数据库迁移 —— 老部署必须手动执行

**`database/*.sql` 只会在 Postgres 数据目录为空时执行。** `Dockerfile.server`、
各 compose 文件、部署流水线都**不会**运行 Alembic，所以只要数据卷里已经有数据，
**新表就不会自动出现，必须手动跑迁移。**

本仓库有 **两条** 迁移分支（`main_db` 与 `tenant_db`），因此裸写
`alembic upgrade head` 是有歧义的，务必带上分支名：

```bash
# 主库（users、rate_limit_counters、email_verification_codes）
docker compose -f docker-compose.server.yml exec app alembic upgrade main_db@head

# 各租户库（每个用户的 todos/attachments/sessions）
docker compose -f docker-compose.server.yml exec app python scripts/migrate_tenants.py
```

所有迁移都使用幂等 DDL，重复执行是安全的。

### 开启 `EMAIL_VERIFICATION_ENABLED` 之前

注册验证码与找回密码会写入 `email_verification_codes` 表，该表由迁移 `003` 创建。
在把 `EMAIL_VERIFICATION_ENABLED` 置为 `true` **之前**，先执行：

```bash
docker compose -f docker-compose.server.yml exec app alembic upgrade main_db@head
```

若开关已打开但表不存在，`/api/v1/auth/send-code` 与 `/api/v1/auth/reset-password`
会返回 **503 `邮箱验证服务未初始化，请联系管理员执行数据库迁移`**，同时应用日志会打印
`email_verification_codes table is missing; run 'alembic upgrade main_db@head' against the main database`。

---

## 推送热修（小改动）

日常迭代只支持这一种发布方式。脚本的生产默认值是 `root@8.134.33.19`、`/opt/university-helper`、
独立的 `docker-compose` 二进制，以及 `university-helper` 项目下的 `docker-compose.server.yml`
和 `docker-compose.newhost.yml` 两个文件。

不是 dry-run 的推送之前，必须为准确的 `SERVER_IP` 配好可信的 OpenSSH `known_hosts` 文件。
完整的主机密钥行要从服务器控制台、云厂商界面或已经信任该主机的管理员工作站获取，至少也要
带外核对指纹。首次连接时不要直接信任在线扫描拿到的密钥。

```bash
export SSH_KNOWN_HOSTS_FILE="$HOME/.ssh/uh_known_hosts"
chmod 600 "$SSH_KNOWN_HOSTS_FILE"
# 将已核验的、完整的 SERVER_IP 对应 known_hosts 行写入此文件。
```

GitHub Actions 部署从 `SERVER_SSH_KNOWN_HOSTS` secret 读取同样的可信主机密钥行。发布脚本在
建立连接之前，会拒绝缺失、为空、无法解析或与目标不匹配的主机密钥文件。

推荐用 SSH 密钥认证：设置了 `SSH_KEY`，或 agent 里有密钥时，脚本会自动使用。下面的密码方式
仍然可用，但会打印警告。

```bash
export EASY_LEARNING_SERVER_IP=8.134.33.19
export EASY_LEARNING_SERVER_PASSWORD=<从密钥管理获取>

./scripts/hotfix_publish.sh \
  backend/app/api/v1/course.py

cd frontend && npm ci && npm run build
cd ..
./scripts/hotfix_publish.sh --frontend
```

脚本的行为：

- 只把指定的文件同步到服务器的 `/opt/university-helper/`。
- Compose 用的是独立的 `docker-compose -p university-helper -f docker-compose.server.yml -f
  docker-compose.newhost.yml`。这台主机上的 `docker compose` v2 插件会崩溃，不要换成它。
- 后端文件先同步到服务器上的仓库检出目录。脚本确认所选 Compose 文件里的 `app` 服务可以构建后，
  执行 `up -d --build --no-deps --force-recreate app`，用新镜像替换 app。app 容器的根文件系统
  是只读的，不会往运行中的容器里拷文件。
- 替换前，已有的源文件会先复制成同目录下唯一的临时备份；上传内容先写入同目录的临时文件，
  再用 `rename` 发布。这只是逐个文件替换，不承诺整个多文件与容器更新是原子的。
- 新容器健康、完整的 SHA-256 镜像 ID 与 Compose 一致、有界的 HTTP 健康检查也通过之后，脚本
  才清理临时备份。上传、构建或健康检查失败时，脚本会恢复或删除源文件，把旧镜像重新打回原来的
  tag，不构建直接重建旧服务，再确认容器恢复到完全相同的旧镜像 ID 并且健康。回滚本身失败会报
  致命错误，保留现场供人工恢复。没有构建上下文的拓扑（例如只用镜像的 release 拓扑）会在上传前
  直接失败。
- 前端改动只能发布构建好的产物。在仓库根目录构建后，脚本同步
  `/opt/university-helper/frontend/dist/`（它以 bind mount 挂进 `shuake-easy-learning-web`
  nginx 容器），并 reload 该容器的 nginx。单文件模式不接受前端源码路径。
- 依赖层的改动（`backend/requirements.txt`、`Dockerfile.server`）会重建整个 app 镜像。

发布后端时，脚本先等 Compose 健康检查通过，再轮询 `http://127.0.0.1:8000/health`（脚本
`HEALTH_URL` 的默认值）。通过 web 容器访问时，同一个端点在 `http://127.0.0.1:18082/health`，
宿主机 nginx 也把公网请求转发到这个端口。web 容器依赖健康的 app，所以排查端到端问题时，
app 直连端点和 `18082` 路径都要看。

---

## 全新服务器初始化

只在搭建新服务器、并且要和当前生产拓扑一致时使用。其他新主机用文首的快速开始更省事。

1. `ssh root@<server>`
2. `mkdir -p /opt/university-helper && cd /opt/university-helper`
3. `git clone <repo> .` 或用 `rsync <source>/ ./` 将源码同步到当前目录（排除 `.env`、`node_modules`、`dist`、`__pycache__`）。
4. 在 `/opt/university-helper/.env` 中手动写入真实密钥（见上文）。
5. 安装 Node.js 20（以 `.nvmrc` 为准）。在仓库根目录先构建前端，再启动 web 容器：
   ```bash
   node --version  # 必须是 20.x
   cd frontend && npm ci && npm run build
   cd ..           # 回到仓库根目录
   ```
6. 确认 `frontend/dist/` 已经生成。`Dockerfile.server` 只构建后端，所以这一步必须在 web overlay 启动并挂载 SPA 之前完成。
7. 用独立二进制启动两个 Compose 文件：
   ```bash
   docker-compose -p university-helper \
     -f docker-compose.server.yml -f docker-compose.newhost.yml up -d --build
   ```
8. 配置宿主机 nginx：为 `shuake.cornna.xyz` 做 TLS 终结，并把
   `proxy_pass` 指向 web 容器的 `http://127.0.0.1:18082`。不要让宿主机 nginx 直接
   提供 `frontend/dist/`。
9. 验证 app 与 web 路径：
   ```bash
   curl -fsS http://127.0.0.1:8000/health
   curl -fsS http://127.0.0.1:18082/health
   curl -fsS https://shuake.cornna.xyz/health
   ```
   每个响应里的 `schema` 都应该是 `ok`，否则注册会失败，处理方法见故障排查。

---

## 运维

```bash
# 状态
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml ps

# 日志
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml logs -f app
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml logs -f postgres
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml logs -f web

# 数据库 shell
docker-compose -p university-helper \
  -f docker-compose.server.yml -f docker-compose.newhost.yml exec postgres \
  psql -U easylearning -d main_db

# 加密数据库备份（推荐；请从仓库根目录执行）
AGE_RECIPIENT=age1xxxxxx... \
  bash scripts/db_backup.sh /opt/backups/university-helper
# 或使用 recipient 文件：
AGE_RECIPIENT_FILE=/etc/uh/age-recipients.txt \
  bash scripts/db_backup.sh /opt/backups/university-helper
# - 文件名、原子发布和保留天数均由脚本统一负责
```

---

## 故障排查

- **注册返回 503 `DatabaseNotInitializedError`。** 数据库缺少 `users` 表或 `tenant_template`
  模板库。Postgres 只在全新数据卷上执行初始化脚本，复用的或初始化到一半的数据卷可能缺这两样。
  app 启动时会检查两者，缺什么就用镜像里自带的 SQL 文件补上（`DB_AUTO_BOOTSTRAP`，默认开启）；
  注册时发现模板库不存在，也会尝试修复一次。`/health` 的 `schema` 字段给出结果：`ok`、
  `missing_users`、`missing_tenant_template` 或 `unknown`。只要不是 `ok`，`status` 就是
  `degraded`，但接口仍返回 200。请查看 app 日志、重跑安装脚本，或按
  [`database/README.md`](../database/README.md) 手动执行 SQL。
- **注册返回 503 `TenantProvisioningError`。** 提示信息会说明原因。「数据库正忙」表示另一个连接
  （比如正在跑的 `pg_dumpall` 备份）一直占用 `tenant_template`，重试几次后仍未释放，稍后再注册即可。
  「没有建库权限（CREATEDB）」表示数据库账号不能建库；自带的 Postgres 容器里这个账号是超级用户，
  所以通常出现在外部 Postgres 的账号缺少 `CREATEDB` 时。「数据库暂时连不上」表示连不到 Postgres。
- **有些用户名注册不了。** `template`、`template0`、`template1`、`postgres`、`main`、`maindb`、
  `root`、`system` 是保留名，注册时会提示「该用户名为系统保留名称，请换一个」。
- **返回 400，`"code": "InvalidHost"`（提示以 `Invalid host header` 开头）。** 访问站点用的域名或
  IP 没有被允许。`localhost`、`127.0.0.1` 和 `CORS_ORIGINS` 里的主机始终允许，其他的（比如局域网
  IP 或第二个域名）要加进 `ALLOWED_HOSTS`，逗号分隔，`*.example.com` 可以匹配子域名。用安装脚本
  部署的，带 `--allowed-hosts` 重跑脚本；生产机上改 `.env` 后重建 app 容器。app 第一次拒绝某个
  主机时会写一条警告日志。`ENV=production` 时设 `ALLOWED_HOSTS=*`，app 会拒绝启动。
- **安装脚本用不了 Docker。** 当前用户不在 `docker` 组时，如果免密 `sudo` 可用，脚本会改用
  `sudo`。否则执行 `sudo usermod -aG docker "$USER"`，退出重新登录后再运行脚本。
- **安装脚本部署时 8080 端口被占用。** 带 `--port <port>` 重跑安装脚本。
- **8000 端口冲突。** `APP_PORT` 是 app 在宿主机上的绑定端口，也是热修脚本直连做健康检查的端口。
  在 Compose 环境里改掉后，同步修改脚本的 `HEALTH_URL`。web 容器仍通过 Compose 网络访问 `app:8000`。
- **18082 端口冲突。** 保持 web 发布端口与宿主机 nginx 的 `proxy_pass` 一致，web 容器只通过宿主机
  反代对外提供服务，不要直接暴露到公网。
- **前端改动没生效。** 确认 `/opt/university-helper/frontend/dist/` 已更新、
  `shuake-easy-learning-web` 已 reload，再绕过缓存访问（`curl -H "Cache-Control: no-cache" http://127.0.0.1:18082/`）。
- **构建镜像时 `apt-get` 失败。** `Dockerfile.server` 里的运行时 apt 依赖尽量少，免得部署是否
  成功取决于上游 Debian 镜像源。
