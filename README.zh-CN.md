**语言：** [English](./README.md) | 简体中文

# University Helper

<p align="center">
  <strong>演示网站：</strong>
  <a href="https://shuake.cornna.xyz">shuake.cornna.xyz</a>
</p>

<p align="center">
  <img src="docs/university-helper-promo.gif" alt="University Helper 产品宣传片：你睡觉时，它在超星学习通和智慧树上替你签到、刷课、答题，天亮前做完" width="640" />
  <br />
  <sub><b>「你睡觉，它上课」</b> 60 秒产品宣传片，用 Remotion 逐帧渲染。</sub>
</p>

University Helper 是一个校园辅助项目，后端用 FastAPI，前端用 React。仓库名是 `university-helper`，但部分源码目录还沿用旧的内部名称 `easy_learning`。

## 快速开始

### 桌面端

到 [最新 Release](../../releases/latest) 下载对应系统的安装包。桌面端（学道）自带后端，在你自己的电脑上运行，不需要 Docker、Postgres 或 Python。它是单用户的，不用注册账号，打开就能用。

| 系统 | 下载文件 | 说明 |
|---|---|---|
| Windows 10/11 | `xuedao_<ver>_windows_x64-setup.exe` / `xuedao_<ver>_windows_x64.msi` | 未签名：SmartScreen 中点 **更多信息 → 仍要运行** |
| macOS Apple Silicon | `xuedao_<ver>_darwin_aarch64.dmg` | 未签名：首次启动右键 App → **打开** |
| macOS Intel | `xuedao_<ver>_darwin_x64.dmg` | 同样右键 → **打开** |
| Linux | `xuedao_<ver>_linux_amd64.AppImage` / `.deb` | `chmod +x *.AppImage && ./*.AppImage` |

桌面端启动几秒后会去 GitHub 检查新版本。有新版本时，它会先弹窗显示版本号和更新说明，问你要不要更新。点「现在更新」会下载新版本并重启学道，正在跑的任务会中断；点「稍后」则等下次启动再提醒。自动更新需要发版时配置了 Tauri 签名密钥。上游仓库没有密钥时发版流程会直接失败，所以只有 fork 出来的构建可能没有自动更新。

macOS 版目前是免费的 ad-hoc 签名，没有经过公证。先试试 **右键 App → 打开**。如果系统提示「已损坏，无法打开」或「移到废纸篓」，把 App 拖到「应用程序」，再执行下面的命令去掉下载隔离标记：

```bash
xattr -dr com.apple.quarantine "/Applications/学道.app"
open "/Applications/学道.app"
```

这条命令只用于从本仓库 GitHub Releases 下载的官方安装包。

桌面端的日志文件是 `desktop.log`，位置：macOS 在 `~/Library/Logs/xyz.cornna.shuake/`，Windows 在 `%LOCALAPPDATA%\xyz.cornna.shuake\logs\`，Linux 在 `~/.local/share/xyz.cornna.shuake/logs/`。

### 一键部署服务端

新服务器装好 Docker 后，运行部署脚本即可。脚本会生成带随机密钥的 `.env`，从 GHCR 拉取预构建镜像，启动 Postgres、后端和 web 容器，并等 `/health` 通过。不需要先 git clone：脚本单独运行时，会先把对应版本的源码下载到 `./university-helper`（可用 `UH_INSTALL_DIR` 改位置）。

```bash
# Linux / macOS / WSL2，本机访问 http://localhost:8080
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y --admin-email you@example.com

# 公网 IP，纯 http
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y --host 203.0.113.10 --admin-email you@example.com

# 域名（ENV=production、https CORS，并生成配置 TLS 用的宿主机 nginx 模板）
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y --domain your.domain --admin-email you@example.com
```

Windows（Docker Desktop）：

```powershell
Invoke-WebRequest -UseBasicParsing https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.ps1 -OutFile deploy_server.ps1
powershell -ExecutionPolicy Bypass -File deploy_server.ps1 -Yes -AdminEmail you@example.com
```

已经 clone 了仓库的话，直接运行仓库里的脚本：

```bash
git clone https://github.com/sweetcornna/university-helper.git
cd university-helper

# Linux / macOS / WSL2
bash scripts/deploy_server.sh --tag 1.4.7 -y                 # 本机：http://localhost:8080
bash scripts/deploy_server.sh --tag 1.4.7 --host 203.0.113.10 -y
bash scripts/deploy_server.sh --tag 1.4.7 --domain your.domain -y

# Windows（PowerShell + Docker Desktop）
pwsh scripts/deploy_server.ps1 -Tag 1.4.7 -Port 8080 -Yes
```

常用参数（括号里是 PowerShell 的写法）：

- `--tag`（`-Tag`）：要安装的版本，`1.4.7` 和 `v1.4.7` 都行，默认是最新版。
- `--port`（`-Port`）：web 容器在宿主机上的端口，默认 8080。
- `--admin-email`（`-AdminEmail`）：管理员邮箱，多个用逗号分隔。
- `--allowed-hosts`（`-AllowedHosts`）：还会用哪些域名或 IP 打开网站，比如局域网 IP 或第二个域名。
- `--build`（`-Build`）：从源码构建镜像，不拉取预构建镜像。

脚本可以重复运行。`.env` 里的密钥和数据库都会保留，这次传入的参数会生效。升级时在安装目录里带上新版本号再跑一次：`bash scripts/deploy_server.sh --tag <新版本> -y`。安装目录如果是脚本下载的，它会先把 compose 文件和脚本换成新版本的。

服务端不会自己升级。GitHub 上有新版本时，管理员打开网页会看到提示，里面有新版本号、更新说明和可以直接复制的升级命令。管理员是 `ADMIN_EMAILS`（即 `--admin-email`）里的邮箱；没配置时，服务器上第一个注册的账号就是管理员。服务端每 6 小时检查一次；服务器不能上网的话，在 `.env` 里设 `UPDATE_CHECK_ENABLED=false`，再运行一次部署脚本。

### 本地开发

```bash
bash scripts/setup.sh        # 创建 .env，安装 Python/Node 依赖
make start                   # 启动 docker-compose 栈（app + postgres）
make test                    # 运行后端 + 前端测试
```

Windows 用户请在 WSL2 里运行这些命令，并打开 Docker Desktop 的 WSL 集成。

## 给 AI Agent 的安装指引

用户让你安装 University Helper 时，按下面的步骤做。命令由你来执行，并把每一步检查的输出告诉用户。

### 1. 选版本

- 一个人在自己电脑上用：装桌面端（第 7 步），不需要 Docker，也不用注册账号。
- 多人通过浏览器访问的服务器：装服务端（第 2 到 6 步）。

### 2. 检查环境

```bash
docker info >/dev/null && echo "docker daemon ok"
docker compose version
curl --version | head -n 1
openssl version                        # 首次安装时用来生成密钥

# 8080 端口必须空闲，没有输出就是空闲
ss -ltn 'sport = :8080' | tail -n +2   # Linux
lsof -nP -iTCP:8080 -sTCP:LISTEN       # macOS
```

Windows 上用 `docker info`、`docker compose version` 和 `Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue` 检查。8080 被占用时，下面的命令加上 `--port <空闲端口>`（`-Port`），后面所有地址也换成这个端口。

### 3. 无交互安装

一定要加 `-y`（`-Yes`）。没有终端时，脚本会把所有提问都当成「否」。管理员邮箱向用户确认后，选一条执行：

```bash
# 仅本机访问
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y --admin-email admin@example.com
# 公网 IP，纯 http
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y --host 203.0.113.10 --admin-email admin@example.com
# 域名；装完后按脚本输出的 nginx/certbot 步骤配置 TLS
curl -fsSL https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.sh | bash -s -- -y --domain example.com --admin-email admin@example.com
```

```powershell
Invoke-WebRequest -UseBasicParsing https://github.com/sweetcornna/university-helper/releases/latest/download/deploy_server.ps1 -OutFile deploy_server.ps1
powershell -ExecutionPolicy Bypass -File deploy_server.ps1 -Yes -AdminEmail admin@example.com
```

文件会装到 `./university-helper`，之后的 `docker compose` 和 `scripts/` 命令都在这个目录里执行。

### 4. 验收

```bash
curl -fsS http://127.0.0.1:8080/health
```

应该看到 `"status":"ok"` 和 `"schema":"ok"`。刚启动的几秒里 `schema` 可能是 `unknown`，最多重试一分钟。如果是 `missing_users` 或 `missing_tenant_template`，注册会失败，按下面的表处理。

然后注册第一个账号。用户名 3 到 30 个字符，只能用 `a-z` 和 `0-9`；密码至少 8 位，要包含大写字母、小写字母和数字。

```bash
curl -sS -w '\nHTTP %{http_code}\n' -X POST http://127.0.0.1:8080/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","email":"admin@example.com","password":"ChangeMe123"}'
```

应该返回 `HTTP 201`，响应 JSON 里有 `access_token`。如果这个账号的邮箱在 `--admin-email` 里，或者没配置管理员邮箱而它是第一个账号，它就是管理员。可以带上 `Authorization: Bearer <access_token>` 请求 `GET /api/v1/system/update` 确认：管理员返回 `200`，其他账号返回 `403`。注册接口有限流，返回 `429` 时等一分钟再试。

### 5. 常见问题

| 现象 | 处理 |
|---|---|
| 返回 `400`，内容有 `"code":"InvalidHost"` 或「Invalid host header」 | 打开网站用的域名或 IP 不在 `CORS_ORIGINS` 或 `ALLOWED_HOSTS` 里。带上 `--allowed-hosts <host1,host2>` 重新运行安装命令。 |
| 注册返回 `503`「数据库还没初始化好」，或 `/health` 显示 `missing_users` / `missing_tenant_template` | 应用启动时会补建缺失的表和模板库。执行 `docker compose -p university-helper -f docker-compose.release.yml restart app`，等 `"schema":"ok"`；还不行就看 `docker compose -p university-helper -f docker-compose.release.yml logs --tail=80 app postgres`。 |
| 注册返回 `503`，提示没有建库权限（CREATEDB） | 应用连接数据库用的 Postgres 账号不能建库，给它授予 `CREATEDB`。 |
| 启动时报「port is already allocated」或「address already in use」 | 换个端口，加 `--port <空闲端口>` 重新运行。 |
| 「Docker is running but this user cannot use it」 | 执行 `sudo usermod -aG docker "$USER"`，退出重新登录后再运行。 |
| 「ENV=production requires https:// CORS_ORIGINS」 | 有域名用 `--domain`（https），只有 IP 用 `--host <ip>`（纯 http）。 |

### 6. 不要做的事

- 不要删除 `.env` 或 `university-helper_shuake-postgres-data` 数据卷，也不要执行 `docker compose down -v`。`.env` 里有数据库密码和 `CREDENTIAL_ENCRYPTION_KEY`，丢了就打不开已有数据。数据卷还在而 `.env` 没了时，脚本会拒绝继续。
- 不要在用 IP 走纯 http 访问的站点上设 `ENV=production`。生产模式下，除 localhost 以外的 `http://` 来源会让应用拒绝启动。这种情况用 `--host`，它会保持 `ENV=dev`。
- 生产环境不要设 `ALLOWED_HOSTS=*`，应用同样会拒绝启动。
- 永远不要把 `.env` 提交到仓库，把它备份到私密的地方。

### 7. 桌面端

从最新 Release 下载对应系统的文件，例如 `gh release download --repo sweetcornna/university-helper --pattern 'xuedao_*_darwin_aarch64.dmg'`：

- Windows：`xuedao_<ver>_windows_x64-setup.exe`（或 `xuedao_<ver>_windows_x64.msi`）
- macOS：`xuedao_<ver>_darwin_aarch64.dmg`（Apple Silicon）或 `xuedao_<ver>_darwin_x64.dmg`（Intel）
- Linux：`xuedao_<ver>_linux_amd64.AppImage` 或 `xuedao_<ver>_linux_amd64.deb`

macOS 提示 App 已损坏时，先把它移到 `/Applications`，再执行 `xattr -dr com.apple.quarantine "/Applications/学道.app"`。出问题时看 `desktop.log`：macOS 在 `~/Library/Logs/xyz.cornna.shuake/`，Windows 在 `%LOCALAPPDATA%\xyz.cornna.shuake\logs\`，Linux 在 `~/.local/share/xyz.cornna.shuake/logs/`。

## 功能概览

- 基于 JWT 的用户注册与登录
- 超星签到接口与任务轮询
- 超星刷课任务管理
- 智慧树二维码或账号密码登录，以及课程任务编排
- 基于 PostgreSQL 的多租户数据隔离，每个用户一个独立数据库
- 认证、仪表盘、超星、智慧树流程的 React 前端页面
- 服务端管理员的新版本提醒，桌面端更新前先询问

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
- 桌面端：Tauri 2 外壳，内置 PyInstaller 打包的后端
- 数据层：PostgreSQL 15
- 部署：Docker / Docker Compose + nginx

## 支持平台

桌面端可以在 Windows、macOS、Linux 上原生运行。服务端是 Web 应用，生产环境以 Linux 为主，任何装了 Docker 的机器都能用下文的多架构镜像一条命令跑起来。包括安卓在内的任何设备，都可以通过浏览器或安装好的 PWA 访问服务端。

| 平台 | 支持范围 | 推荐方式 |
|---|---|---|
| Linux | 本地开发 + 生产部署 | Docker Engine + Compose、Python 3.11、Node 20 |
| macOS | 本地开发 + 部署客户端 | Docker Desktop 或 Colima、Python 3.11、Node 20 |
| Windows | 服务端（Docker Desktop）+ 部署客户端 | `scripts/deploy_server.ps1`（PowerShell）或 WSL2 + `deploy_server.sh` |
| Android | 终端用户访问 | 在 Chrome/Edge 中安装 PWA；目前没有原生 APK |

详细说明见 [平台支持](./docs/PLATFORMS.md)。

## 主要 API

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
- `GET /api/v1/system/update`（仅服务端，仅管理员）
- `GET /health`

## 题库

自动答题时，每道题都会去可配置的题库（`tiku`）里查。查到的答案会按题型校验并写入缓存，所以一份 N 道题的试卷只需要 O(1) 次缓存读取。题库来源在 `tiku_config.provider` 里配置，泛雅页面上对应「题库来源」。

| 题库 | `provider` 取值 | Token | 说明 |
|------|----------------|-------|------|
| 言溪题库 | `TikuYanxi` | 需要 | 通用题库。 |
| GO 题库 | `TikuGo` | 可选 | 免费搜题源（网课小工具，`q.icodef.com`），有节流。 |
| Like 题库 | `TikuLike` | 需要 | 备用题库（datam.site）。 |
| 题库适配器 | `TikuAdapter` | 不需要 | 指向自建的 [tikuAdapter](https://github.com/DokiDoki1103/tikuAdapter)（`url`）。 |
| AI 智能答题 | `AI` | 不需要 | OpenAI 兼容大模型（`endpoint`/`key`/`model`）。 |
| 硅基流动 | `SiliconFlow` | 需要 | 硅基流动大模型。 |
| 本地缓存 | `LocalCache` | 不需要 | 只用已缓存的答案，不调用外部 API。 |

### 多题库回退

`provider` 也可以写成逗号分隔的有序列表。前一个题库没查到，或者返回的答案和题型对不上，就换下一个。无法初始化的题库（比如缺 Token 的题库、缺 key 的大模型）会被自动移出回退链，所以链上只要还有一个能用，整条链就能用。

```jsonc
// tiku_config：先查言溪，没查到再用免费的 GO题库
{ "provider": "TikuYanxi,TikuGo", "token": "<言溪 token>" }
```

> 答案缓存总是在所有题库之前查一次，所以 `LocalCache` 只有单独选用（纯缓存模式）时才有用，放进回退链里没有意义。

## 开发细节

### 后端单独启动

```bash
cd backend
install -m 600 .env.example .env  # 然后编辑 SECRET_KEY / CORS_ORIGINS / 数据库配置
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

## 部署细节

> 完整的部署文档见 [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md)。

每次发版都会向 GHCR 推送多架构（amd64 + arm64）镜像，不需要本地编译：

- `ghcr.io/sweetcornna/university-helper-app`：FastAPI 后端
- `ghcr.io/sweetcornna/university-helper-web`：nginx 和构建好的前端

Release 镜像 tag 不带前缀 `v`（是 `1.4.7`，不是 `v1.4.7`）。部署脚本两种写法都接受。

### 注册失败怎么查

注册需要 `users` 表和 `tenant_template` 模板库。`curl http://127.0.0.1:8080/health` 返回的 `schema` 字段会说明它们的状态：`ok`、`missing_users`、`missing_tenant_template`，或者 `unknown`（检查不了数据库）。应用启动时会补建缺失的部分，所以第一步先重启 `app` 容器。注册页会显示服务端返回的原因，详细信息在应用日志里。用部署脚本安装的话：

```bash
docker compose -p university-helper -f docker-compose.release.yml restart app
docker compose -p university-helper -f docker-compose.release.yml logs --tail=80 app postgres
```

如果打开网站用的地址服务端不认识，会报「Invalid host header」。用 `--allowed-hosts` 或在 `.env` 的 `ALLOWED_HOSTS` 里加上这个地址，再运行一次部署脚本。

### 手动部署（从源码构建）

这种方式是宿主机 nginx 加源码目录里的 Compose，需要先装好 Docker Compose 和 Node.js 20（版本以 `.nvmrc` 为准）。`Dockerfile.server` 只构建后端，所以要先在宿主机上构建前端静态文件，再交给 nginx。

```bash
install -m 600 .env.example .env
node --version              # 必须是 20.x
cd frontend && npm ci && npm run build
cd ..                       # 回到仓库根目录
docker compose -f docker-compose.server.yml -p university-helper up -d --build
```

确认 `frontend/dist/` 已经生成，再配置宿主机 nginx 指向这个目录。

仓库根目录的 `.env.example` 是按 `docker-compose.server.yml` 写的。`scripts/_legacy/` 里的旧 `deploy.*` 脚本不要运行。生产环境的增量更新用 `scripts/hotfix_publish.sh`。

## 测试

```bash
cd backend && pytest -q
cd frontend && npm run test
cd frontend && npm run lint
```

## 说明

- 仓库里是当前可运行的应用代码，另有一些历史部署辅助脚本。
- `node_modules`、`dist`、`__pycache__`、`%TEMP%` 等生成目录默认已忽略。
- 手动部署并对外提供服务时，首次启动前要换掉数据库密码和 JWT 密钥。部署脚本会自动生成随机值。

## 致谢

本项目超星学习通和智慧树的自动化功能，参考了下面这些开源项目的协议研究，部分实现也借鉴了它们。感谢各位作者。

**超星学习通 · 签到**
- [cxOrz/chaoxing-signin](https://github.com/cxOrz/chaoxing-signin)：普通、拍照、手势、位置、二维码签到的协议参考。

**超星学习通 · 刷课**
- [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing)：超星、尔雅、泛雅任务点全自动完成。本项目超星刷课模块的整体思路来自它。

**智慧树 / 知到 · 刷课**
- [luoyily/zhihuishu-tool](https://github.com/luoyily/zhihuishu-tool)：知到、智慧树的 API 与工具参考。

**题库、字体解密、验证码（直接使用）**
- [SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy](https://github.com/SocialSisterYi/xuexiaoyi-to-xuexitong-tampermonkey-proxy)：超星加密字体反混淆与题库代理（见 `backend/app/services/course/chaoxing/cxsecret_font.py`、`answer_cache.py`）。
- 服务端镜像构建时会从 [Samueli924/chaoxing](https://github.com/Samueli924/chaoxing) 的固定提交下载 `resource/font_map_table.json` 并校验 SHA-256；该数据文件不存入本仓库，其上游仓库采用 GPL-3.0 许可证。
- [DokiDoki1103/tikuAdapter](https://github.com/DokiDoki1103/tikuAdapter)：可插拔题库适配器（见 `answer_providers/adapter.py`）。
- [sml2h3/ddddocr](https://github.com/sml2h3/ddddocr)：验证码 OCR 识别（见 `captcha.py`）。

这些上游项目各有自己的开源许可证，使用时请遵守。如果你的项目列在这里，想调整或移除署名，请提 issue。

## 合规提示

请只在符合学校规定、平台规则和当地法律的前提下使用本项目。对第三方平台启用自动化之前，先想清楚相应的风险和合规要求。
