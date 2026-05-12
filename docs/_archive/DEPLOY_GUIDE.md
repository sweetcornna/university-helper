**Language:** English | [简体中文](./DEPLOY_GUIDE.zh-CN.md)

# Deployment Guide

This guide covers the recommended server-side deployment path for the current repository: `docker-compose.yml`.

## Requirements

- Docker 24+
- Docker Compose v2
- A reachable Linux server
- Persistent storage for PostgreSQL volumes

## 1. Upload the Repository

Upload the repository to your server, for example:

```bash
rsync -avz ./ user@your-server:/opt/easy_learning/
```

You can also use the deployment helpers included in this repository:

- [`deploy.sh`](./deploy.sh)
- [`deploy.ps1`](./deploy.ps1)
- [`deploy_auto.py`](./deploy_auto.py)
- [`deploy_pure.py`](./deploy_pure.py)

These scripts no longer contain embedded credentials. They read target server and secret values from environment variables.

## 2. Create `.env`

Copy from [`.env.example`](./.env.example):

```bash
cp .env.example .env
```

At minimum, review and update:

- `POSTGRES_PASSWORD`
- `SECRET_KEY`
- `CORS_ORIGINS`
- `SHUAKE_COMPAT_SECRET` if needed

## 3. Start the Services

```bash
docker compose -f docker-compose.yml up -d --build
```

Check status:

```bash
docker compose -f docker-compose.yml ps
docker compose -f docker-compose.yml logs -f
```

## 4. Update an Existing Deployment

```bash
git pull
docker compose -f docker-compose.yml up -d --build
```

## 5. Recommendations

- Put HTTPS and reverse proxy handling behind an outer Nginx or Caddy layer
- Rotate database passwords and JWT secrets before first public use
- Never commit `.env`, server addresses, or any real secrets back into the repository

## 6. Finalize Legacy Cutover

After the new stack is running and verified, you can execute the server-side cutover helper on the server:

```bash
chmod +x scripts/server_finalize_shuake_cutover.sh
REMOVE_LEGACY_DB_CONTAINER=true ./scripts/server_finalize_shuake_cutover.sh
```

Default behavior:

- backups the legacy DB
- migrates `users` into the new DB if needed
- points host Nginx to the new containerized frontend
- removes the legacy app container
- removes the legacy DB container only if `REMOVE_LEGACY_DB_CONTAINER=true`

The legacy PostgreSQL volume is still retained after that step.

## 7. Publish a Small Hotfix

For small code-only fixes, use the hotfix helper instead of a full deployment:

```bash
export EASY_LEARNING_SERVER_IP=your-server-ip
export EASY_LEARNING_SERVER_PASSWORD=your-password
./scripts/hotfix_publish.sh backend/app/api/v1/course.py frontend/src/pages/Zhihuishu.jsx frontend/src/utils/zhihuishuTasks.js
```

Behavior:

- syncs only the files you pass in
- backend Python source changes are copied into the running app container and the app container is restarted
- frontend or Nginx changes rebuild only `easy-learning-nginx`
- dependency-layer changes such as `Dockerfile` or `backend/requirements.txt` trigger an app rebuild

## Related Docs

- [`DEPLOY_MANUAL.md`](./DEPLOY_MANUAL.md)
- [`README.md`](./README.md)
