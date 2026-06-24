**语言：** [English](./README.md) | 简体中文

# University Helper

<p align="center">
  <strong>演示网站：</strong>
  <a href="https://shuake.cornna.xyz">shuake.cornna.xyz</a>
</p>

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

- 后端：Python 3.11、FastAPI 0.115、Pydantic v2、psycopg2、PyJWT、bcrypt、Fernet 凭据加密
- 前端：React 18、Vite 5、React Router 6、Tailwind CSS
- 数据层：PostgreSQL 15
- 部署：Docker / Docker Compose + nginx

## 支持平台

University Helper 是 Web 应用。Linux 是生产服务器目标；macOS、Linux、Windows 可作为开发/部署客户端；Android 以 PWA 方式使用。

| 平台 | 支持范围 | 推荐方式 |
|---|---|---|
| Linux | 本地开发 + 生产部署 | Docker Engine + Compose、Python 3.11、Node 20 |
| macOS | 本地开发 + 部署客户端 | Docker Desktop 或 Colima、Python 3.11、Node 20 |
| Windows | 服务端（Docker Desktop）+ 部署客户端 | `scripts/deploy_server.ps1`（PowerShell）或 WSL2 + `deploy_server.sh` |
| Android | 终端用户访问 | 在 Chrome/Edge 中安装 PWA；当前不提供原生 APK |

「可在 Windows/macOS/Linux 运行」指的是**服务端**可在任何装有 Docker 的机器上一条命令跑起来
（下方有多架构预构建镜像）；任意设备（含安卓）通过浏览器或已安装的 PWA 访问即可。

详细说明见 [平台支持](./docs/PLATFORMS.md)。

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

## 题库

自动答题时，每道题都会经过一个可配置的**题库**（`tiku`）查询。命中的答案会按题型
校验并写入缓存，因此一份 N 题的试卷只需 O(1) 次缓存读取。题库来源通过
`tiku_config.provider` 配置（泛雅页面对应「题库来源」）。

| 题库 | `provider` 取值 | Token | 说明 |
|------|----------------|-------|------|
| 言溪题库 | `TikuYanxi` | 需要 | 通用题库。 |
| GO 题库 | `TikuGo` | 可选 | 免费搜题源（网课小工具，`q.icodef.com`），有节流。 |
| Like 题库 | `TikuLike` | 需要 | 备用题库（datam.site）。 |
| 题库适配器 | `TikuAdapter` | — | 指向自建的 [tikuAdapter](https://github.com/DokiDoki1103/tikuAdapter)（`url`）。 |
| AI 智能答题 | `AI` | — | OpenAI 兼容大模型（`endpoint`/`key`/`model`）。 |
| 硅基流动 | `SiliconFlow` | 需要 | 硅基流动大模型。 |
| 本地缓存 | `LocalCache` | — | 仅用已缓存答案，从不调用外部 API。 |

**多题库回退。** `provider` 支持逗号分隔的有序列表：前一个未命中或返回的答案类型
不符时，自动回退到下一个。无法初始化的题库（如缺 Token 的题库、缺 key 的大模型）
会被自动从回退链中剔除，因此只要链中有一个可用，整条链就仍然有效。

```jsonc
// tiku_config —— 先言溪，未命中再用免费的 GO题库 兜底
{ "provider": "TikuYanxi,TikuGo", "token": "<言溪 token>" }
```

> 答案缓存总会在所有题库之前先查一次，因此 `LocalCache` 仅在单独选用（纯缓存模式）时才有意义，放进回退链里是冗余的。

## 本地开发

### 快速启动

```bash
bash scripts/setup.sh        # 创建 .env，安装 Python/Node 依赖
make start                   # 启动 docker-compose 栈（app + postgres）
make test                    # 运行后端 + 前端测试
```

Windows 用户请在 WSL2 中运行以上命令，并开启 Docker Desktop 的 WSL 集成。

### 后端单独启动

```bash
cd backend
cp .env.example .env         # 然后编辑 SECRET_KEY / CORS_ORIGINS / 数据库配置
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端单独启动

```bash
cd frontend
npm install
npm run dev                  # http://localhost:3000，/api 代理到 :8000
```

## 推荐部署方式

> **唯一权威文档：[`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md)。**

### 一键部署（推荐）

引导式安装脚本只依赖 Docker：自动生成带随机密钥的 `.env`
（`SECRET_KEY` / `POSTGRES_PASSWORD` / Fernet `CREDENTIAL_ENCRYPTION_KEY`）、
拉取预构建镜像、启动整套服务、等待健康检查，并在传入 `--domain` 时为宿主机
nginx + Let's Encrypt 生成可启用的反代模板。

```bash
git clone https://github.com/sweetcornna/university-helper.git
cd university-helper

# Linux / macOS / WSL2
bash scripts/deploy_server.sh --domain your.domain          # 带 TLS 的生产部署
bash scripts/deploy_server.sh --host 203.0.113.10           # 仅用 IP 的 http 部署
bash scripts/deploy_server.sh                               # 本机：http://localhost:8080

# Windows（PowerShell + Docker Desktop）
pwsh scripts/deploy_server.ps1 -Port 8080
```

每次发版都会向 GHCR 推送 **多架构（amd64 + arm64）** 镜像，无需本地编译：

- `ghcr.io/sweetcornna/university-helper-app` —— FastAPI 后端
- `ghcr.io/sweetcornna/university-helper-web` —— nginx + 已构建的前端

加 `--build`（Windows 为 `-Build`）则改为从源码本地构建。

### 手动部署（从源码构建）

```bash
cp .env.example .env
docker compose -f docker-compose.server.yml up -d --build
```

仓库根目录下的 `.env.example` 已按 `docker-compose.server.yml` 准备好。原根目录下的 `deploy.*` 脚本已经移动到 [`scripts/_legacy/`](./scripts/_legacy/)，禁止运行。增量更新生产环境请用 `scripts/hotfix_publish.sh`。

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

## 致谢

University Helper 站在开源社区的肩膀上。本项目中超星学习通与智慧树的自动化能力，参考、学习并在部分实现上借鉴了以下优秀开源项目的协议研究成果，在此向各位作者致以诚挚谢意：

**超星学习通 · 签到**
- [cxOrz/chaoxing-signin](https://github.com/cxOrz/chaoxing-signin) —— 普通 / 拍照 / 手势 / 位置 / 二维码签到协议参考。

**超星学习通 · 刷课**
- [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing) —— 超星 / 尔雅 / 泛雅全自动完成任务点；本项目超星刷课模块整体思路与其一脉相承。

**智慧树 / 知到 · 刷课**
- [luoyily/zhihuishu-tool](https://github.com/luoyily/zhihuishu-tool) —— 知到 / 智慧树 API 与工具参考。

**题库 / 字体解密 / 验证码（直接使用）**
- [SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy](https://github.com/SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy) —— 超星加密字体反混淆与题库代理（见 `backend/app/services/course/chaoxing/cxsecret_font.py`、`answer_cache.py`）。
- [DokiDoki1103/tikuAdapter](https://github.com/DokiDoki1103/tikuAdapter) —— 可插拔题库适配器（见 `answer_providers/adapter.py`）。
- [sml2h3/ddddocr](https://github.com/sml2h3/ddddocr) —— 验证码 OCR 识别（见 `captcha.py`）。

以上各上游项目均遵循其各自的开源许可证，请在使用时遵守相应条款。若您的项目被列于此处、希望调整或移除署名，请提交 issue 告知。

## 合规提示

请仅在符合学校规定、平台规则和当地法律的前提下使用本项目。在对第三方平台启用自动化前，请先评估相应的风险与合规要求。
