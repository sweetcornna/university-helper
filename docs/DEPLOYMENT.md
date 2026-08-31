**Language:** English | [简体中文](#部署指南-简体中文)

# Deployment Guide

This document is the **single source of truth** for deploying University Helper. All previous deploy docs (`DEPLOY.md`, `DEPLOY_GUIDE*.md`, `DEPLOY_MANUAL*.md`) have been archived under [`docs/_archive/`](./_archive/) and should not be followed.

> **Production deploys use `scripts/hotfix_publish.sh` only.** The current production target is
> `root@8.134.33.19:/opt/university-helper`. The legacy root-level `deploy.sh` / `deploy.ps1` /
> `deploy_auto.py` / `deploy_pure.py` / `server_deploy.sh` scripts have been moved to
> [`scripts/_legacy/`](../scripts/_legacy/) — they target a stale `/opt/easy_learning` path and
> overwrite the production `.env`. Do not run them.

---

## Quick start: a fresh server (one command)

To stand up University Helper on a **new, separate** Docker host, use the guided installer
rather than the hotfix flow below (which targets the already-provisioned production box).
It generates a hardened `.env` with random secrets, pulls the prebuilt multi-arch images
from GHCR (`ghcr.io/sweetcornna/university-helper-{app,web}`), starts the stack, waits for
health, and scaffolds a host-nginx + Let's Encrypt vhost. This installer is not the update
path for the current production host.

```bash
git clone https://github.com/sweetcornna/university-helper.git
cd university-helper
bash scripts/deploy_server.sh --domain <your-domain>     # production with TLS
# or:  bash scripts/deploy_server.sh --host <server-ip>  # plain-http on an IP
# or:  bash scripts/deploy_server.sh --build             # build from source instead of pulling
```

This wraps [`docker-compose.release.yml`](../docker-compose.release.yml). The
prebuilt images are published by [`.github/workflows/release.yml`](../.github/workflows/release.yml)
on every `v*` Git tag, with image tags like `1.4.1` (no leading `v`). The deploy
scripts accept either `1.4.1` or `v1.4.1`. Windows hosts can use `scripts/deploy_server.ps1`. The
sections below document the **existing** `shuake.cornna.xyz` production box,
where ongoing changes ship via `scripts/hotfix_publish.sh`.

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
| TLS / reverse proxy | host nginx (managed outside Compose) → `http://127.0.0.1:18082` |
| Authoritative deploy script | `scripts/hotfix_publish.sh` |
| App health check | `http://127.0.0.1:8000/health` (script default) |

The production stack has a `web` nginx container named `shuake-easy-learning-web`; it is
not host nginx. The host nginx only terminates TLS and reverse-proxies to
`127.0.0.1:18082`. The `nginx/` files in the repository are mounted into the web container.
The root `Dockerfile`, `Dockerfile.nginx` and `docker-compose.yml` were dead code and have
been deleted.

---

## Local Development

For local dev, follow the root [`README.md`](../README.md) — `uvicorn` for backend, `vite` for frontend. Do not bring up Docker locally unless you are reproducing a production-only bug.

---

## Environment Variables (production)

The production `.env` lives at `/opt/university-helper/.env` on the server and **must never be overwritten by automation**. Required keys:

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
```

If you need to seed a fresh server, copy `.env.example` and fill in real secrets manually. Never commit a populated `.env`.

---

## Deploying a Hotfix (small code change)

This is the only supported deploy path for ongoing changes. The script's production defaults
target `root@8.134.33.19`, `/opt/university-helper`, the standalone `docker-compose` binary,
and both `docker-compose.server.yml` and `docker-compose.newhost.yml` under the
`university-helper` project.

Before any non-dry-run publish, configure a trusted OpenSSH `known_hosts` file
for the exact `SERVER_IP`. Obtain the complete host-key line (or verify its
fingerprint) through the server console/provider or an already-trusted
administrator workstation, then review it out of band; do not blindly trust
an online first-connection scan on first contact.

```bash
export SSH_KNOWN_HOSTS_FILE="$HOME/.ssh/uh_known_hosts"
chmod 600 "$SSH_KNOWN_HOSTS_FILE"
# Put the verified, complete known_hosts line for SERVER_IP in this file.
```

The GitHub Actions deploy uses the same trusted line(s) from the
`SERVER_SSH_KNOWN_HOSTS` secret. The publisher refuses missing, empty,
unparseable, or non-matching host-key files before opening a transport.

Preferred: SSH-key auth (the script defaults to this whenever `SSH_KEY` is set or an agent has the key).

```bash
export SERVER_IP=8.134.33.19
export SSH_KEY=~/.ssh/uh

./scripts/hotfix_publish.sh \
  backend/app/api/v1/course.py
```

Legacy: sshpass + password auth still works but prints a warning:

```bash
export EASY_LEARNING_SERVER_IP=8.134.33.19
export EASY_LEARNING_SERVER_PASSWORD=<from secrets manager>
./scripts/hotfix_publish.sh backend/app/main.py
```

Behavior:

- Syncs only the listed files into `/opt/university-helper/` on the server.
- Uses standalone `docker-compose -p university-helper -f docker-compose.server.yml -f
  docker-compose.newhost.yml`; do not substitute the `docker compose` v2 plugin on this host.
- Backend changes are uploaded into the remote repository checkout, after which
  the script verifies that the selected Compose files contain a buildable `app`
  service and runs `up -d --build --no-deps --force-recreate app`. The read-only app container is
  replaced from that image; no files are copied into a running container. Each existing remote
  file is copied to a unique same-directory temporary backup, and each upload is written to a
  same-directory temporary file and then published with `rename`. This is a per-file replacement
  mechanism; it does not make the overall multi-file and container update atomic. After the
  replacement container is healthy, its full SHA-256 image ID matches Compose, and the bounded
  HTTP health check succeeds, temporary backups are removed. If upload, build, or health
  verification fails, the script restores/deletes the source files, retags the old image,
  recreates the old service without a build, and verifies the restored container uses the exact
  old image ID and is healthy; a rollback failure is reported as fatal for manual recovery.
  Image-only/release Compose topologies fail closed before upload.
- Frontend changes are published only through the built artifact flow. From the repository root:

  ```bash
  cd frontend && npm ci && npm run build
  cd ..
  ./scripts/hotfix_publish.sh --frontend
  ```

  This syncs `/opt/university-helper/frontend/dist/`, which is bind-mounted into the
  `shuake-easy-learning-web` nginx container. The script reloads that container's nginx;
  frontend source paths are not accepted in per-file mode.
- Dependency-layer changes (`backend/requirements.txt`, `Dockerfile.server`) trigger a full app image rebuild.

The backend transaction waits for the Compose healthcheck and then polls
`http://127.0.0.1:8000/health` (the script's default `HEALTH_URL`). Through the web container,
the same endpoint is available at `http://127.0.0.1:18082/health`; the public host nginx
forwards to that port. The web container depends on a healthy app, so check both the direct app
endpoint and the `18082` path when diagnosing an end-to-end issue.

---

## First-Time Server Bootstrap

If you are setting up a brand new server (rare) and it must match the current production
topology:

1. `ssh root@<server>`
2. `mkdir -p /opt/university-helper && cd /opt/university-helper`
3. `git clone <repo> .` or `rsync <source>/ ./` the source into the current directory (excluding `.env`, `node_modules`, `dist`, `__pycache__`).
4. Create `/opt/university-helper/.env` manually with real secrets (see above).
5. Install Node.js 20 (matching `.nvmrc`). From the repository root, build the SPA before starting the web container:
   ```bash
   node --version  # must report 20.x
   cd frontend && npm ci && npm run build
   cd ..           # return to the repository root
   ```
6. Confirm that `frontend/dist/` exists; `Dockerfile.server` builds only the backend, so this must happen before the `web` overlay starts and bind-mounts the SPA.
7. Start the two-file stack with the standalone binary:
   ```bash
   docker-compose -p university-helper \
     -f docker-compose.server.yml -f docker-compose.newhost.yml up -d --build
   ```
8. Configure host nginx with TLS termination at `shuake.cornna.xyz` and
   `proxy_pass http://127.0.0.1:18082` (the web container); do not configure host nginx to
   serve `frontend/dist/` directly.
9. Verify the app and web paths:
   ```bash
   curl -fsS http://127.0.0.1:8000/health
   curl -fsS http://127.0.0.1:18082/health
   curl -fsS https://shuake.cornna.xyz/health
   ```

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

# Alembic migrations (idempotent baselines; the heads are independent)
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

The overlay publishes the app on `127.0.0.1:8001`, uses a separate `shuake-postgres-staging-data` volume, lowers resource caps, and renames the containers so the prod stack stays untouched.

---

## Troubleshooting

- **`/health` returns 400 (Invalid host header)** — check `TrustedHostMiddleware` in `backend/app/main.py` is parsing host out of `CORS_ORIGINS`, not using the raw URL.
- **Port conflict on 8000** — `APP_PORT` is the app's host-local bind and the script's direct health-check port. Resolve it in the Compose environment and keep the script `HEALTH_URL` aligned; the web container still reaches `app:8000` on the Compose network.
- **Port conflict on 18082** — keep the web publish port and host nginx `proxy_pass` aligned; do not expose the web container publicly beyond the host reverse proxy.
- **Frontend changes do not appear** — confirm `/opt/university-helper/frontend/dist/` was updated, `shuake-easy-learning-web` was reloaded, and bypass its cache (`curl -H "Cache-Control: no-cache" http://127.0.0.1:18082/`).
- **`apt-get` failures during image build** — keep runtime apt deps minimal in `Dockerfile.server`; do not couple deploy stability to upstream Debian mirrors.

---

# 部署指南 (简体中文)

本文件是 University Helper 部署的**唯一权威说明**。此前的部署文档（`DEPLOY.md` / `DEPLOY_GUIDE*.md` / `DEPLOY_MANUAL*.md`）已归档到 [`docs/_archive/`](./_archive/)，不要再参照。

> **生产部署只使用 `scripts/hotfix_publish.sh`。** 当前生产目标是
> `root@8.134.33.19:/opt/university-helper`。仓库根目录原有的 `deploy.sh` /
> `deploy.ps1` / `deploy_auto.py` / `deploy_pure.py` / `server_deploy.sh` 已被移动到
> [`scripts/_legacy/`](../scripts/_legacy/)，它们指向已废弃的 `/opt/easy_learning` 路径，
> 并且会覆盖生产 `.env`，**禁止运行**。

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
| TLS / 反代 | 宿主机 nginx（不在 Compose 内）→ `http://127.0.0.1:18082` |
| 唯一部署脚本 | `scripts/hotfix_publish.sh` |
| app 健康检查 | `http://127.0.0.1:8000/health`（脚本默认值） |

生产栈中有名为 `shuake-easy-learning-web` 的 `web` nginx 容器，并非宿主机 nginx。
宿主机 nginx 只负责 TLS 终结，再反代到 `127.0.0.1:18082`。仓库内的 `nginx/` 文件
会挂载到 web 容器中。根目录原来的 `Dockerfile`、`Dockerfile.nginx`、`docker-compose.yml`
已是死代码，已删除。

---

## 本地开发

本地开发请按根目录的 [`README.zh-CN.md`](../README.zh-CN.md) — 使用 `uvicorn` 启动后端，`vite` 启动前端。除非要复现仅在生产出现的 bug，否则不需要在本地起 Docker。

---

## 环境变量（生产）

生产 `.env` 位于服务器上的 `/opt/university-helper/.env`，**任何自动化都不允许覆盖它**。必备字段：

```env
POSTGRES_PASSWORD=<已轮换，禁止入仓>
SECRET_KEY=<至少 32 字符，已轮换，禁止入仓>
SHUAKE_COMPAT_SECRET=<可选>
CORS_ORIGINS=["https://shuake.cornna.xyz"]
APP_PORT=8000
# Fernet 密钥（urlsafe-base64），生成命令：
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 生产环境必填；应用缺失该密钥时会拒绝启动。密钥禁止入仓。
CREDENTIAL_ENCRYPTION_KEY=<已轮换，禁止入仓>
```

若需要全新初始化一台服务器，请基于 `.env.example` 手动填写真实密钥；任何已填写真实值的 `.env` **都不要提交**。

---

## 推送热修（小改动）

这是日常迭代唯一支持的部署方式。脚本的生产默认值指向
`root@8.134.33.19`、`/opt/university-helper`、独立的 `docker-compose` 二进制，
以及 `university-helper` 项目下的 `docker-compose.server.yml` 与
`docker-compose.newhost.yml` 两个文件。

任何非 dry-run 推送前，都必须为准确的 `SERVER_IP` 配置可信的 OpenSSH
`known_hosts` 文件。应从服务器控制台/云厂商界面或已经信任的管理员工作站获取完整主机密钥行，
并通过带外方式核对指纹；首次连接不要盲目信任在线首次连接扫描结果。

```bash
export SSH_KNOWN_HOSTS_FILE="$HOME/.ssh/uh_known_hosts"
chmod 600 "$SSH_KNOWN_HOSTS_FILE"
# 将已核验的、完整的 SERVER_IP 对应 known_hosts 行写入此文件。
```

GitHub Actions 部署使用同样的可信主机密钥行（配置在
`SERVER_SSH_KNOWN_HOSTS` secret 中）。发布脚本在建立传输前会拒绝缺失、空、
无法解析或与目标不匹配的主机密钥文件。

```bash
export EASY_LEARNING_SERVER_IP=8.134.33.19
export EASY_LEARNING_SERVER_PASSWORD=<从密钥管理获取>

./scripts/hotfix_publish.sh \
  backend/app/api/v1/course.py

cd frontend && npm ci && npm run build
cd ..
./scripts/hotfix_publish.sh --frontend
```

行为：

- 仅同步指定文件到服务器的 `/opt/university-helper/`。
- 使用独立的 `docker-compose -p university-helper -f docker-compose.server.yml -f
  docker-compose.newhost.yml`；当前主机不要改用会崩溃的 `docker compose` v2 插件。
- 后端改动会先同步到远程仓库检出目录；脚本确认所选 Compose 文件中的
  `app` 服务存在可构建上下文后，执行 `up -d --build --no-deps --force-recreate app` 重建并替换
  app。app 容器是只读根文件系统，不会向运行中的容器拷贝文件。已有源文件会先复制到同目录、
  唯一的临时备份；上传先写入同目录临时文件，再用 `rename` 发布和替换。这只是单文件替换
  手段，不承诺整个多文件与容器更新是原子的。替换容器使用与 Compose 完全匹配的新 SHA-256
  镜像、容器健康且有界 HTTP 健康检查成功后，脚本清理临时备份；上传、构建或健康检查失败
  时会恢复/删除源文件、将旧镜像重新标记到原引用、无构建重建旧服务，并验证容器精确恢复旧
  镜像且健康；回滚失败会明确报致命错误，保留现场供人工恢复。构建上下文不存在（例如仅
  镜像的 release 拓扑）时会在上传前安全失败。
- 前端改动只能走已构建产物流程。在仓库根目录执行构建后，脚本同步
  `/opt/university-helper/frontend/dist/`（它会 bind mount 到 `shuake-easy-learning-web`
  nginx 容器），并 reload 该容器的 nginx；前端源码路径不能用单文件模式推送。
- 依赖层改动（`backend/requirements.txt`、`Dockerfile.server`）会触发 app 镜像重建。

后端事务会先等待 Compose 健康检查通过，再轮询
`http://127.0.0.1:8000/health`（脚本 `HEALTH_URL` 默认值）。经 web 容器访问时，同一端点
位于 `http://127.0.0.1:18082/health`；宿主机 nginx 会把公网请求转发到该端口。排查端到端
问题时应同时检查 app 直连端点和 `18082` 路径。

---

## 全新服务器初始化

仅在搭建新服务器且需要匹配当前生产拓扑时使用：

1. `ssh root@<server>`
2. `mkdir -p /opt/university-helper && cd /opt/university-helper`
3. `git clone <repo> .` 或用 `rsync <source>/ ./` 将源码同步到当前目录（排除 `.env`、`node_modules`、`dist`、`__pycache__`）。
4. 在 `/opt/university-helper/.env` 中**手动**写入真实密钥（参见上文）。
5. 安装 Node.js 20（以 `.nvmrc` 为准）。在仓库根目录先构建前端，再启动 web 容器：
   ```bash
   node --version  # 必须是 20.x
   cd frontend && npm ci && npm run build
   cd ..           # 回到仓库根目录
   ```
6. 确认 `frontend/dist/` 已生成；`Dockerfile.server` 只构建后端，因此必须在 web overlay 启动并挂载 SPA 之前完成这一步。
7. 使用独立二进制启动两个 Compose 文件：
   ```bash
   docker-compose -p university-helper \
     -f docker-compose.server.yml -f docker-compose.newhost.yml up -d --build
   ```
8. 配置宿主机 nginx：在 `shuake.cornna.xyz` 上做 TLS 终结，并将
   `proxy_pass` 指向 web 容器的 `http://127.0.0.1:18082`；不要让宿主机 nginx 直接
   serve `frontend/dist/`。
9. 验证 app 与 web 路径：
   ```bash
   curl -fsS http://127.0.0.1:8000/health
   curl -fsS http://127.0.0.1:18082/health
   curl -fsS https://shuake.cornna.xyz/health
   ```

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

- **`/health` 返回 400（Invalid host header）** — 检查 `backend/app/main.py` 中的
  `TrustedHostMiddleware` 是否从 `CORS_ORIGINS` 正确提取 host，而不是使用原始 URL；
  同时分别检查 `http://127.0.0.1:8000/health` 和
  `http://127.0.0.1:18082/health`。
- **8000 端口冲突** — `APP_PORT` 是 app 的宿主机绑定端口，也是脚本直连健康检查端口；
  在 Compose 环境中调整后同步脚本的 `HEALTH_URL`。web 容器仍通过 Compose 网络访问
  `app:8000`。
- **18082 端口冲突** — 保持 web 发布端口与宿主机 nginx 的 `proxy_pass` 一致；不要绕过
  宿主机反代将 web 容器暴露到公网。
- **前端改动未生效** — 确认 `/opt/university-helper/frontend/dist/` 已更新、
  `shuake-easy-learning-web` 已 reload，并绕过其缓存（`curl -H "Cache-Control: no-cache" http://127.0.0.1:18082/`）。
- **构建镜像时 `apt-get` 失败** — `Dockerfile.server` 中尽量减少运行时 apt 依赖，避免把部署稳定性绑定到上游 Debian 镜像源。
