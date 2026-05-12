**语言：** [English](./DEPLOY_GUIDE.md) | 简体中文

# 部署指南

这份文档针对当前仓库推荐的服务端部署方式：`docker-compose.server.yml`。

## 准备条件

- Docker 24+
- Docker Compose v2
- 一台可访问的 Linux 服务器
- PostgreSQL 数据卷持久化存储

## 1. 上传仓库

把仓库上传到服务器，例如：

```bash
rsync -avz ./ user@your-server:/opt/easy_learning/
```

也可以直接使用仓库内置的部署辅助脚本：

- [`deploy.sh`](./deploy.sh)
- [`deploy.ps1`](./deploy.ps1)
- [`deploy_auto.py`](./deploy_auto.py)
- [`deploy_pure.py`](./deploy_pure.py)

这些脚本已经移除了硬编码凭据，统一通过环境变量读取目标服务器和密钥。

## 2. 创建 `.env`

从 [`.env.example`](./.env.example) 复制：

```bash
cp .env.example .env
```

至少需要确认并修改：

- `POSTGRES_PASSWORD`
- `SECRET_KEY`
- `CORS_ORIGINS`
- `SHUAKE_COMPAT_SECRET`（如果需要）

## 3. 启动服务

```bash
docker compose -f docker-compose.server.yml up -d --build
```

查看状态：

```bash
docker compose -f docker-compose.server.yml ps
docker compose -f docker-compose.server.yml logs -f
```

## 4. 更新已有部署

```bash
git pull
docker compose -f docker-compose.server.yml up -d --build
```

## 5. 建议

- HTTPS 和反向代理建议由外层 Nginx 或 Caddy 统一处理
- 首次公开部署前先更换数据库密码和 JWT 密钥
- 不要把 `.env`、服务器地址或任何真实密钥提交回仓库

## 相关文档

- [`DEPLOY_MANUAL.zh-CN.md`](./DEPLOY_MANUAL.zh-CN.md)
- [`README.zh-CN.md`](./README.zh-CN.md)
