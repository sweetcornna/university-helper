**Language:** English | [简体中文](#部署指南-简体中文)

# Deployment Guide

This document is the **single source of truth** for deploying University Helper. All previous deploy docs (`DEPLOY.md`, `DEPLOY_GUIDE*.md`, `DEPLOY_MANUAL*.md`) have been archived under [`docs/_archive/`](./_archive/) and should not be followed.

> **Production deploys use `scripts/hotfix_publish.sh` only.** The legacy root-level `deploy.sh` / `deploy.ps1` / `deploy_auto.py` / `deploy_pure.py` / `server_deploy.sh` scripts have been moved to [`scripts/_legacy/`](../scripts/_legacy/) — they target a stale `/opt/easy_learning` path and overwrite the production `.env`. Do not run them.

---

## Production Topology (authoritative)

| Concern | Value |
|---|---|
| Public URL | `https://shuake.cornna.xyz` |
| Server IP | `111.228.53.64` |
| Server install root | `/opt/university-helper/` |
| Compose file | `docker-compose.server.yml` (root) |
| Backend image | built from `Dockerfile.server` (root) |
| Frontend serving | host-machine **nginx** serves `frontend/dist/` directly (no nginx container) |
| Database | PostgreSQL 15 in container |
| TLS / reverse proxy | host nginx (managed outside Compose) |
| Authoritative deploy script | `scripts/hotfix_publish.sh` |
| Legacy server cutover helper | `scripts/server_finalize_shuake_cutover.sh` (one-shot, already executed) |

There is **no `nginx` container** in the production stack. The `nginx/` directory in the repo holds reference configs that the host nginx loads from `/etc/nginx/`. The root `Dockerfile`, `Dockerfile.nginx` and `docker-compose.yml` were dead code and have been deleted.

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
```

If you need to seed a fresh server, copy `.env.example` and fill in real secrets manually. Never commit a populated `.env`.

---

## Deploying a Hotfix (small code change)

This is the only supported deploy path for ongoing changes.

```bash
export EASY_LEARNING_SERVER_IP=111.228.53.64
export EASY_LEARNING_SERVER_PASSWORD=<from secrets manager>

./scripts/hotfix_publish.sh \
  backend/app/api/v1/course.py \
  frontend/src/pages/Zhihuishu.jsx
```

Behavior:

- Syncs only the listed files into `/opt/university-helper/` on the server.
- Backend `.py` changes are copied into the running app container; container is restarted.
- Frontend changes are rebuilt locally (or on the server) and emitted into `frontend/dist/`, which the host nginx already serves.
- Dependency-layer changes (`backend/requirements.txt`, `Dockerfile.server`) trigger a full app image rebuild.

---

## First-Time Server Bootstrap

If you are setting up a brand new server (rare):

1. `ssh root@<server>`
2. `mkdir -p /opt/university-helper && cd /opt/university-helper`
3. `git clone <repo>` or `rsync` the source (excluding `.env`, `node_modules`, `dist`, `__pycache__`).
4. Create `/opt/university-helper/.env` manually with real secrets (see above).
5. `docker compose -f docker-compose.server.yml up -d --build`
6. Configure host nginx with TLS termination at `shuake.cornna.xyz`, `root frontend/dist;`, and `proxy_pass http://127.0.0.1:8000` for `/api/`.
7. Verify: `curl -fsS http://127.0.0.1:8000/health` and `curl -fsS https://shuake.cornna.xyz/`.

---

## Operations

```bash
# Status
docker compose -f docker-compose.server.yml ps

# Logs
docker compose -f docker-compose.server.yml logs -f app
docker compose -f docker-compose.server.yml logs -f postgres

# DB shell
docker compose -f docker-compose.server.yml exec postgres psql -U easylearning -d main_db

# DB backup
docker compose -f docker-compose.server.yml exec postgres \
  pg_dump -U easylearning main_db > /opt/university-helper/backups/main_db-$(date +%F).sql
```

---

## Troubleshooting

- **`/health` returns 400 (Invalid host header)** — check `TrustedHostMiddleware` in `backend/app/main.py` is parsing host out of `CORS_ORIGINS`, not using the raw URL.
- **Port conflict on 8000** — change `APP_PORT` in `/opt/university-helper/.env`, then update host nginx `proxy_pass`.
- **Frontend changes do not appear** — confirm `frontend/dist/` on the server was updated and host nginx cache is bypassed (`curl -H "Cache-Control: no-cache"`).
- **`apt-get` failures during image build** — keep runtime apt deps minimal in `Dockerfile.server`; do not couple deploy stability to upstream Debian mirrors.

---

# 部署指南 (简体中文)

本文件是 University Helper 部署的**唯一权威说明**。此前的部署文档（`DEPLOY.md` / `DEPLOY_GUIDE*.md` / `DEPLOY_MANUAL*.md`）已归档到 [`docs/_archive/`](./_archive/)，不要再参照。

> **生产部署只使用 `scripts/hotfix_publish.sh`。** 仓库根目录原有的 `deploy.sh` / `deploy.ps1` / `deploy_auto.py` / `deploy_pure.py` / `server_deploy.sh` 已被移动到 [`scripts/_legacy/`](../scripts/_legacy/)，它们指向已废弃的 `/opt/easy_learning` 路径，并且会覆盖生产 `.env`，**禁止运行**。

---

## 生产拓扑（权威）

| 项 | 值 |
|---|---|
| 对外域名 | `https://shuake.cornna.xyz` |
| 服务器 IP | `111.228.53.64` |
| 服务器安装根目录 | `/opt/university-helper/` |
| Compose 文件 | 仓库根目录 `docker-compose.server.yml` |
| 后端镜像 | 由根目录 `Dockerfile.server` 构建 |
| 前端 | 宿主机 **nginx** 直接 serve `frontend/dist/`（**没有** nginx 容器） |
| 数据库 | PostgreSQL 15 容器 |
| TLS / 反代 | 宿主机 nginx（不在 Compose 内） |
| 唯一部署脚本 | `scripts/hotfix_publish.sh` |
| 一次性切换脚本 | `scripts/server_finalize_shuake_cutover.sh`（已执行完毕） |

生产栈中**没有 nginx 容器**。仓库内的 `nginx/` 目录存放的是参考配置，宿主机 nginx 从 `/etc/nginx/` 加载真正使用的版本。根目录原来的 `Dockerfile`、`Dockerfile.nginx`、`docker-compose.yml` 已是死代码，已删除。

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
```

若需要全新初始化一台服务器，请基于 `.env.example` 手动填写真实密钥；任何已填写真实值的 `.env` **都不要提交**。

---

## 推送热修（小改动）

这是日常迭代唯一支持的部署方式。

```bash
export EASY_LEARNING_SERVER_IP=111.228.53.64
export EASY_LEARNING_SERVER_PASSWORD=<从密钥管理获取>

./scripts/hotfix_publish.sh \
  backend/app/api/v1/course.py \
  frontend/src/pages/Zhihuishu.jsx
```

行为：

- 仅同步指定文件到服务器的 `/opt/university-helper/`。
- 后端 `.py` 文件被拷贝进运行中的 app 容器并重启。
- 前端改动会重新构建并写入 `frontend/dist/`，宿主机 nginx 已直接 serve 这个目录。
- 依赖层改动（`backend/requirements.txt`、`Dockerfile.server`）会触发 app 镜像重建。

---

## 全新服务器初始化

仅在搭建新服务器时使用：

1. `ssh root@<server>`
2. `mkdir -p /opt/university-helper && cd /opt/university-helper`
3. `git clone <repo>` 或用 `rsync` 上传源码（排除 `.env`、`node_modules`、`dist`、`__pycache__`）。
4. 在 `/opt/university-helper/.env` 中**手动**写入真实密钥（参见上文）。
5. `docker compose -f docker-compose.server.yml up -d --build`
6. 配置宿主机 nginx：在 `shuake.cornna.xyz` 上做 TLS 终结，`root frontend/dist;`，并将 `/api/` 反代到 `http://127.0.0.1:8000`。
7. 验证：`curl -fsS http://127.0.0.1:8000/health` 与 `curl -fsS https://shuake.cornna.xyz/`。

---

## 运维

```bash
# 状态
docker compose -f docker-compose.server.yml ps

# 日志
docker compose -f docker-compose.server.yml logs -f app
docker compose -f docker-compose.server.yml logs -f postgres

# 数据库 shell
docker compose -f docker-compose.server.yml exec postgres psql -U easylearning -d main_db

# 备份
docker compose -f docker-compose.server.yml exec postgres \
  pg_dump -U easylearning main_db > /opt/university-helper/backups/main_db-$(date +%F).sql
```

---

## 故障排查

- **`/health` 返回 400（Invalid host header）** — 检查 `backend/app/main.py` 中 `TrustedHostMiddleware` 是否从 `CORS_ORIGINS` 中正确提取 host，而不是使用原始 URL。
- **8000 端口冲突** — 修改 `/opt/university-helper/.env` 中的 `APP_PORT`，并同步更新宿主机 nginx 的 `proxy_pass`。
- **前端改动未生效** — 确认服务器上的 `frontend/dist/` 已被更新，并绕过 nginx 缓存（`curl -H "Cache-Control: no-cache"`）。
- **构建镜像时 `apt-get` 失败** — `Dockerfile.server` 中尽量减少运行时 apt 依赖，避免把部署稳定性绑定到上游 Debian 镜像源。
