**语言：** [English](./DEPLOY_MANUAL.md) | 简体中文

# 手动部署

如果不想使用自动化脚本，可以按下面这组最小步骤手动部署。

## 1. 连接服务器

```bash
ssh user@your-server
```

## 2. 创建项目目录

```bash
mkdir -p /opt/easy_learning
cd /opt/easy_learning
```

## 3. 上传项目

在本地执行：

```bash
rsync -avz ./ user@your-server:/opt/easy_learning/
```

建议排除以下本地产物：

- `node_modules`
- `dist`
- `__pycache__`
- `.pytest_cache`
- `%TEMP%`

## 4. 写入环境变量

在服务器上创建 `.env`：

```bash
cat > .env <<'EOF'
POSTGRES_PASSWORD=change-this-db-password
SECRET_KEY=change-this-jwt-secret-key-min-32-characters
SHUAKE_COMPAT_SECRET=
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]
EOF
```

## 5. 启动服务

```bash
docker compose -f docker-compose.server.yml up -d --build
```

## 6. 验证

```bash
docker compose -f docker-compose.server.yml ps
docker compose -f docker-compose.server.yml logs --tail=100
```

## 7. 常见问题

### 端口已被占用

检查反向代理或宿主机上已有服务。

### 数据库未启动

```bash
docker compose -f docker-compose.server.yml logs postgres
```

### 应用启动失败

```bash
docker compose -f docker-compose.server.yml logs app
```

## 相关文档

- [`DEPLOY_GUIDE.zh-CN.md`](./DEPLOY_GUIDE.zh-CN.md)
- [`README.zh-CN.md`](./README.zh-CN.md)
