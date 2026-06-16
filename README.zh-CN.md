**语言：** [English](./README.md) | 简体中文

# University Helper

<p align="center">
  <img src="docs/university-helper-promo.gif" alt="University Helper 产品宣传片：你睡觉时，它在超星学习通 / 智慧树替你签到、刷课、答题，天亮前全部完成" width="640" />
  <br />
  <sub><b>「你睡觉，它上课」</b> — 60 秒产品宣传片，使用 Remotion 逐帧渲染</sub>
</p>

University Helper 是一个基于 FastAPI 和 React 的全栈校园辅助项目。仓库名使用 `university-helper`，但部分源码目录仍保留历史内部名称 `easy_learning`。

当前代码库包含：

- 基于 JWT 的用户注册与登录
- 超星签到接口与任务轮询
- 超星刷课任务管理
- 智慧树二维码/账号密码登录与课程任务编排
- 基于 PostgreSQL 的多租户数据隔离
- 面向认证、仪表盘、超星、智慧树流程的 React 前端页面

## 仓库结构

```text
backend/        FastAPI 应用、服务、数据模型、测试
frontend/       React + Vite 前端
database/       SQL schema 与租户初始化脚本
nginx/          反向代理配置
scripts/        安装、测试、备份、部署脚本
```

## 技术栈

- 后端：Python 3.10+、FastAPI、Pydantic、psycopg2、JWT
- 前端：React 18、Vite、React Router、Tailwind CSS、Zustand
- 数据层：PostgreSQL
- 部署：Docker / Docker Compose

## 主要 API 区域

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/shuake-token`
- `POST /api/v1/chaoxing/login`
- `GET /api/v1/chaoxing/courses`
- `POST /api/v1/chaoxing/sign`
- `POST /api/v1/course/start`
- `GET /api/v1/course/status/{task_id}`
- `POST /api/v1/course/zhihuishu/qr-login`
- `POST /api/v1/course/zhihuishu/password-login`
- `POST /api/v1/course/zhihuishu/tasks/course`

## 本地开发

### 1. 后端

```bash
cd backend
cp .env.example .env
pip install -r requirements.txt email-validator
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后端前，至少需要在 `backend/.env` 中配置：

- `MAIN_DB_HOST`
- `MAIN_DB_NAME`
- `MAIN_DB_USER`
- `MAIN_DB_PASSWORD`
- `SECRET_KEY`
- `CORS_ORIGINS`

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

默认情况下，Vite 开发服务器运行在 `http://localhost:3000`，并会把 `/api` 请求代理到 `http://localhost:8000`。

### 3. 数据库

使用 PostgreSQL 15+，并通过 [`database/`](./database) 下的脚本初始化数据库。

## 推荐部署方式

> **唯一权威文档：[`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md)。生产部署只使用 `scripts/hotfix_publish.sh`。**

服务端部署建议使用：

- [`docker-compose.server.yml`](./docker-compose.server.yml)
- [`Dockerfile.server`](./Dockerfile.server)
- [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md)

快速启动：

```bash
cp .env.example .env
docker compose -f docker-compose.server.yml up -d --build
```

仓库根目录下的 `.env.example` 已按 `docker-compose.server.yml` 准备好。原根目录下的 `deploy.*` 脚本已经移动到 [`scripts/_legacy/`](./scripts/_legacy/)，禁止运行。

## 测试

```bash
cd backend && pytest -q
cd frontend && npm run test
cd frontend && npm run lint
```

## 说明

- 该仓库包含当前可运行的应用代码，以及部分历史部署辅助脚本。
- `node_modules`、`dist`、`__pycache__`、`%TEMP%` 等生成目录默认已忽略。
- 如果要对外提供服务，请在首次部署前立即更换数据库密码和 JWT 密钥。

## 合规提示

请仅在符合学校规定、平台规则和当地法律的前提下使用本项目。在对第三方平台启用自动化前，请先评估相应的风险与合规要求。
