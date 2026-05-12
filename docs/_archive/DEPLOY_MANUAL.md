**Language:** English | [简体中文](./DEPLOY_MANUAL.zh-CN.md)

# Manual Deployment

If you do not want to use the automation scripts, follow these minimal manual deployment steps.

## 1. Connect to the Server

```bash
ssh user@your-server
```

## 2. Create the Project Directory

```bash
mkdir -p /opt/easy_learning
cd /opt/easy_learning
```

## 3. Upload the Project

Run on your local machine:

```bash
rsync -avz ./ user@your-server:/opt/easy_learning/
```

Recommended exclusions:

- `node_modules`
- `dist`
- `__pycache__`
- `.pytest_cache`
- `%TEMP%`

## 4. Write Environment Variables

Create `.env` on the server:

```bash
cat > .env <<'EOF'
POSTGRES_PASSWORD=change-this-db-password
SECRET_KEY=change-this-jwt-secret-key-min-32-characters
SHUAKE_COMPAT_SECRET=
CORS_ORIGINS=["http://localhost:3000","http://localhost:5173"]
EOF
```

## 5. Start the Services

```bash
docker compose -f docker-compose.server.yml up -d --build
```

## 6. Verify

```bash
docker compose -f docker-compose.server.yml ps
docker compose -f docker-compose.server.yml logs --tail=100
```

## 7. Common Issues

### Port already in use

Check your reverse proxy or existing host services.

### Database did not start

```bash
docker compose -f docker-compose.server.yml logs postgres
```

### App failed to start

```bash
docker compose -f docker-compose.server.yml logs app
```

## Related Docs

- [`DEPLOY_GUIDE.md`](./DEPLOY_GUIDE.md)
- [`README.md`](./README.md)
