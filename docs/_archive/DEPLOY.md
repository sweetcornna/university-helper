# Docker 部署文档

## 概述

当前仓库的正式部署入口是根目录 `docker-compose.yml`。

它会启动 3 个容器：

- `easy-learning-app`: FastAPI 后端
- `easy-learning-nginx`: 提供前端静态资源并反向代理后端
- `easy-learning-db`: PostgreSQL 15

`docker-compose.server.yml` 只保留为精简后端场景，不作为完整站点的默认部署入口。

## 前置要求

- Docker Engine 20.10+
- `docker compose` 或 `docker-compose`
- 至少 2GB 可用内存
- 至少 5GB 可用磁盘空间

## 环境配置

```bash
cp .env.example .env
```

编辑 `.env`：

```env
POSTGRES_PASSWORD=your_secure_password
SECRET_KEY=your_secret_key_min_32_chars
SHUAKE_COMPAT_SECRET=
CORS_ORIGINS=["https://your-domain.com","http://your-domain.com"]
APP_PORT=8000
NGINX_PORT=80
```

说明：

- `APP_PORT` 是宿主机到后端容器的本地绑定端口，默认 `127.0.0.1:8000`
- `NGINX_PORT` 是容器前端入口暴露端口
- 如果宿主机已有 Nginx/Cloudflare，通常让宿主机反代到 `NGINX_PORT`

## 启动与更新

```bash
docker-compose -f docker-compose.yml up -d --build
```

如果机器只有 Compose v1：

```bash
docker-compose -f docker-compose.yml up -d --build
```

如果机器是 Docker Compose Plugin：

```bash
docker compose -f docker-compose.yml up -d --build
```

## 访问方式

- 容器内前端入口：`http://<server>:<NGINX_PORT>`
- 后端健康检查：`http://127.0.0.1:<APP_PORT>/health`
- 若宿主机已有 Nginx，建议用域名反代到 `127.0.0.1:<NGINX_PORT>`

## 日志与状态

```bash
docker-compose -f docker-compose.yml ps
docker-compose -f docker-compose.yml logs -f app
docker-compose -f docker-compose.yml logs -f nginx
docker-compose -f docker-compose.yml logs -f postgres
```

## 数据库管理

```bash
docker-compose -f docker-compose.yml exec postgres psql -U easylearning -d main_db
docker-compose -f docker-compose.yml exec postgres pg_dump -U easylearning main_db > backup.sql
```

## 重要迁移说明

不要在未校验数据前删除旧数据库容器或旧数据卷。

已验证过一种真实场景：

- 新库只有 `course_task_history`、`course_task_store`
- 旧库额外包含 `users`

这意味着“新版本可运行”不等于“旧数据已迁移”。正确流程是：

1. 先启动新栈
2. 对比新旧数据库表结构和关键行数
3. 完成数据迁移
4. 再删除旧数据库容器和旧卷

## 故障排查

### 健康检查 400 / Invalid host header

如果容器健康检查访问 `/health` 返回 `400`，检查 `TrustedHostMiddleware` 是否只接受了原始 `CORS_ORIGINS` 字符串，未提取 host。

### 端口冲突

如果宿主机已有旧应用占用 `8000` 或已有宿主机 Nginx 占用 `80/443`，在 `.env` 中改用：

```env
APP_PORT=8002
NGINX_PORT=18082
```

然后由宿主机现有 Nginx 反代到新端口。

### Debian 源网络抖动

如果镜像构建阶段 `apt-get install` 无法连接 `deb.debian.org`，优先减少运行时 `apt-get` 依赖，避免把部署稳定性绑定到外部系统包源。
