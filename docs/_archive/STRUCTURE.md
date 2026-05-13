# 统一签到平台 - 项目结构设计

## 1. 完整目录树结构

```
unified-signin-platform/
├── backend/                          # FastAPI 后端服务
│   ├── app/                          # 应用核心代码
│   │   ├── __init__.py
│   │   ├── main.py                   # FastAPI 应用入口
│   │   ├── config.py                 # 配置管理（环境变量、常量）
│   │   ├── dependencies.py           # 依赖注入（数据库会话、认证等）
│   │   │
│   │   ├── api/                      # API 路由层
│   │   │   ├── __init__.py
│   │   │   ├── v1/                   # API v1 版本
│   │   │   │   ├── __init__.py
│   │   │   │   ├── auth.py           # 认证相关路由（登录、注册、刷新）
│   │   │   │   ├── users.py          # 用户管理路由
│   │   │   │   ├── tenants.py        # 租户管理路由
│   │   │   │   ├── signin.py         # 签到功能路由
│   │   │   │   └── admin.py          # 管理员路由
│   │   │   └── deps.py               # API 层依赖（权限检查等）
│   │   │
│   │   ├── core/                     # 核心功能模块
│   │   │   ├── __init__.py
│   │   │   ├── security.py           # 安全相关（密码哈希、JWT）
│   │   │   ├── auth.py               # 认证逻辑
│   │   │   └── tenant.py             # 租户隔离逻辑
│   │   │
│   │   ├── models/                   # SQLAlchemy ORM 模型
│   │   │   ├── __init__.py
│   │   │   ├── base.py               # 基础模型类
│   │   │   ├── user.py               # 用户模型
│   │   │   ├── tenant.py             # 租户模型
│   │   │   └── signin.py             # 签到记录模型
│   │   │
│   │   ├── schemas/                  # Pydantic 数据验证模型
│   │   │   ├── __init__.py
│   │   │   ├── user.py               # 用户相关 schema
│   │   │   ├── tenant.py             # 租户相关 schema
│   │   │   ├── auth.py               # 认证相关 schema
│   │   │   └── signin.py             # 签到相关 schema
│   │   │
│   │   ├── services/                 # 业务逻辑层
│   │   │   ├── __init__.py
│   │   │   ├── user_service.py       # 用户业务逻辑
│   │   │   ├── tenant_service.py     # 租户业务逻辑
│   │   │   ├── auth_service.py       # 认证业务逻辑
│   │   │   └── signin_service.py     # 签到业务逻辑
│   │   │
│   │   ├── middleware/               # 中间件
│   │   │   ├── __init__.py
│   │   │   ├── tenant_isolation.py   # 租户隔离中间件
│   │   │   ├── error_handler.py      # 错误处理中间件
│   │   │   └── logging.py            # 日志中间件
│   │   │
│   │   ├── db/                       # 数据库相关
│   │   │   ├── __init__.py
│   │   │   ├── session.py            # 数据库会话管理
│   │   │   └── base.py               # 数据库基础配置
│   │   │
│   │   └── utils/                    # 工具函数
│   │       ├── __init__.py
│   │       ├── validators.py         # 自定义验证器
│   │       └── helpers.py            # 辅助函数
│   │
│   ├── tests/                        # 测试代码
│   │   ├── __init__.py
│   │   ├── conftest.py               # pytest 配置和 fixtures
│   │   ├── unit/                     # 单元测试
│   │   │   ├── __init__.py
│   │   │   ├── test_auth.py
│   │   │   ├── test_user_service.py
│   │   │   └── test_tenant_service.py
│   │   ├── integration/              # 集成测试
│   │   │   ├── __init__.py
│   │   │   ├── test_api_auth.py
│   │   │   └── test_api_signin.py
│   │   └── e2e/                      # 端到端测试
│   │       ├── __init__.py
│   │       └── test_signin_flow.py
│   │
│   ├── alembic/                      # 数据库迁移
│   │   ├── versions/                 # 迁移版本文件
│   │   ├── env.py                    # Alembic 环境配置
│   │   └── script.py.mako            # 迁移脚本模板
│   │
│   ├── scripts/                      # 运维脚本
│   │   ├── init_db.py                # 初始化数据库
│   │   ├── create_tenant.py          # 创建租户脚本
│   │   └── seed_data.py              # 种子数据
│   │
│   ├── requirements.txt              # Python 依赖（生产环境）
│   ├── requirements-dev.txt          # Python 依赖（开发环境）
│   ├── pyproject.toml                # Python 项目配置
│   ├── pytest.ini                    # pytest 配置
│   ├── alembic.ini                   # Alembic 配置
│   └── README.md                     # 后端文档
│
├── frontend/                         # React + Vite 前端应用
│   ├── src/                          # 源代码
│   │   ├── main.jsx                  # 应用入口
│   │   ├── App.jsx                   # 根组件
│   │   │
│   │   ├── assets/                   # 静态资源
│   │   │   ├── images/               # 图片资源
│   │   │   ├── icons/                # 图标资源
│   │   │   └── styles/               # 全局样式
│   │   │       ├── index.css         # 主样式文件
│   │   │       └── tailwind.css      # Tailwind 入口
│   │   │
│   │   ├── components/               # 可复用组件
│   │   │   ├── common/               # 通用组件
│   │   │   │   ├── Button.jsx
│   │   │   │   ├── Input.jsx
│   │   │   │   ├── Modal.jsx
│   │   │   │   └── Loading.jsx
│   │   │   ├── layout/               # 布局组件
│   │   │   │   ├── Header.jsx
│   │   │   │   ├── Sidebar.jsx
│   │   │   │   └── Footer.jsx
│   │   │   └── signin/               # 签到相关组件
│   │   │       ├── SigninButton.jsx
│   │   │       ├── SigninHistory.jsx
│   │   │       └── SigninStats.jsx
│   │   │
│   │   ├── pages/                    # 页面组件
│   │   │   ├── Login.jsx             # 登录页
│   │   │   ├── Register.jsx          # 注册页
│   │   │   ├── Dashboard.jsx         # 仪表盘
│   │   │   ├── Signin.jsx            # 签到页
│   │   │   ├── Profile.jsx           # 个人资料
│   │   │   └── Admin/                # 管理页面
│   │   │       ├── Users.jsx
│   │   │       ├── Tenants.jsx
│   │   │       └── Settings.jsx
│   │   │
│   │   ├── hooks/                    # 自定义 Hooks
│   │   │   ├── useAuth.js            # 认证 Hook
│   │   │   ├── useSignin.js          # 签到 Hook
│   │   │   └── useTenant.js          # 租户 Hook
│   │   │
│   │   ├── services/                 # API 服务层
│   │   │   ├── api.js                # Axios 实例配置
│   │   │   ├── authService.js        # 认证 API
│   │   │   ├── userService.js        # 用户 API
│   │   │   ├── tenantService.js      # 租户 API
│   │   │   └── signinService.js      # 签到 API
│   │   │
│   │   ├── store/                    # 状态管理（如使用 Zustand/Redux）
│   │   │   ├── authStore.js          # 认证状态
│   │   │   ├── userStore.js          # 用户状态
│   │   │   └── signinStore.js        # 签到状态
│   │   │
│   │   ├── utils/                    # 工具函数
│   │   │   ├── constants.js          # 常量定义
│   │   │   ├── validators.js         # 表单验证
│   │   │   ├── formatters.js         # 数据格式化
│   │   │   └── helpers.js            # 辅助函数
│   │   │
│   │   ├── router/                   # 路由配置
│   │   │   ├── index.jsx             # 路由主文件
│   │   │   └── ProtectedRoute.jsx    # 受保护路由组件
│   │   │
│   │   └── config/                   # 配置文件
│   │       └── env.js                # 环境变量配置
│   │
│   ├── public/                       # 公共静态资源
│   │   ├── favicon.ico
│   │   └── robots.txt
│   │
│   ├── tests/                        # 测试代码
│   │   ├── unit/                     # 单元测试
│   │   │   ├── components/
│   │   │   └── utils/
│   │   ├── integration/              # 集成测试
│   │   └── e2e/                      # E2E 测试（Playwright/Cypress）
│   │       └── signin.spec.js
│   │
│   ├── .env.example                  # 环境变量示例
│   ├── .eslintrc.cjs                 # ESLint 配置
│   ├── .prettierrc                   # Prettier 配置
│   ├── index.html                    # HTML 入口
│   ├── package.json                  # NPM 依赖
│   ├── package-lock.json             # NPM 锁文件
│   ├── vite.config.js                # Vite 配置
│   ├── tailwind.config.js            # Tailwind CSS 配置
│   ├── postcss.config.js             # PostCSS 配置
│   ├── vitest.config.js              # Vitest 测试配置
│   └── README.md                     # 前端文档
│
├── database/                         # 数据库相关文件
│   ├── schema.sql                    # 数据库 schema
│   ├── tenant_template.sql           # 租户模板
│   ├── create_tenant.sql             # 创建租户脚本
│   ├── init.sh                       # 初始化脚本
│   └── README.md                     # 数据库文档
│
├── nginx/                            # Nginx 配置
│   ├── nginx.conf                    # Nginx 主配置
│   ├── ssl/                          # SSL 证书目录
│   └── conf.d/                       # 站点配置
│       └── default.conf
│
├── docs/                             # 项目文档
│   ├── STRUCTURE.md                  # 项目结构说明（本文件）
│   ├── API.md                        # API 文档
│   ├── DEPLOYMENT.md                 # 部署文档
│   ├── DEVELOPMENT.md                # 开发指南
│   ├── ARCHITECTURE.md               # 架构设计
│   └── SECURITY.md                   # 安全规范
│
├── scripts/                          # 项目级脚本
│   ├── setup.sh                      # 项目初始化脚本
│   ├── deploy.sh                     # 部署脚本
│   ├── backup.sh                     # 备份脚本
│   └── test.sh                       # 测试脚本
│
├── .github/                          # GitHub 配置
│   ├── workflows/                    # CI/CD 工作流
│   │   ├── ci.yml                    # 持续集成
│   │   ├── cd.yml                    # 持续部署
│   │   └── test.yml                  # 自动化测试
│   └── ISSUE_TEMPLATE/               # Issue 模板
│
├── .gitignore                        # Git 忽略文件
├── .env.example                      # 环境变量示例（项目级）
├── docker-compose.yml                # Docker Compose 配置
├── docker-compose.dev.yml            # 开发环境 Docker Compose
├── docker-compose.prod.yml           # 生产环境 Docker Compose
├── Dockerfile                        # Docker 镜像构建文件
├── Makefile                          # Make 命令集合
├── README.md                         # 项目主文档
├── LICENSE                           # 开源协议
└── CHANGELOG.md                      # 变更日志
```

---

## 2. 目录用途说明

### 2.1 后端（backend/）

#### app/ - 应用核心
- **main.py**: FastAPI 应用入口，注册路由、中间件、异常处理
- **config.py**: 集中管理配置（数据库连接、JWT 密钥、CORS 等）
- **dependencies.py**: 全局依赖注入（数据库会话、当前用户等）

#### app/api/ - API 路由层
- 按版本组织（v1/），便于 API 版本管理
- 每个模块一个文件（auth.py, users.py 等）
- deps.py 存放 API 层专用依赖（权限检查、分页等）

#### app/core/ - 核心功能
- **security.py**: 密码哈希、JWT 生成/验证
- **auth.py**: 认证逻辑（登录、注册、令牌刷新）
- **tenant.py**: 租户隔离核心逻辑

#### app/models/ - ORM 模型
- SQLAlchemy 模型定义
- base.py 定义公共字段（id, created_at, updated_at）
- 每个实体一个文件

#### app/schemas/ - 数据验证
- Pydantic 模型，用于请求/响应验证
- 与 models/ 对应，但关注数据传输而非持久化

#### app/services/ - 业务逻辑层
- 复杂业务逻辑从路由层抽离
- 可复用的业务操作
- 便于单元测试

#### app/middleware/ - 中间件
- **tenant_isolation.py**: 自动注入租户上下文
- **error_handler.py**: 统一异常处理
- **logging.py**: 请求日志记录

#### app/db/ - 数据库管理
- session.py: 数据库会话工厂
- base.py: 数据库引擎配置

#### tests/ - 测试代码
- **unit/**: 单元测试（测试单个函数/类）
- **integration/**: 集成测试（测试 API 端点）
- **e2e/**: 端到端测试（测试完整业务流程）
- **conftest.py**: pytest fixtures 和配置

#### alembic/ - 数据库迁移
- 使用 Alembic 管理数据库版本
- versions/ 存放迁移脚本

#### scripts/ - 运维脚本
- 数据库初始化、租户创建、数据填充等

---

### 2.2 前端（frontend/）

#### src/ - 源代码

##### components/ - 组件库
- **common/**: 通用 UI 组件（按钮、输入框、模态框等）
- **layout/**: 布局组件（头部、侧边栏、底部）
- **signin/**: 业务组件（签到相关）

##### pages/ - 页面组件
- 每个路由对应一个页面组件
- Admin/ 子目录存放管理后台页面

##### hooks/ - 自定义 Hooks
- 封装可复用的状态逻辑
- useAuth: 认证状态和操作
- useSignin: 签到功能
- useTenant: 租户信息

##### services/ - API 服务层
- **api.js**: Axios 实例配置（拦截器、基础 URL）
- 各 Service 文件封装 API 调用

##### store/ - 状态管理
- 使用 Zustand/Redux 管理全局状态
- 按功能模块划分 store

##### utils/ - 工具函数
- **constants.js**: 常量定义（API 路径、状态码等）
- **validators.js**: 表单验证规则
- **formatters.js**: 数据格式化（日期、货币等）

##### router/ - 路由配置
- React Router 配置
- ProtectedRoute 实现权限控制

##### config/ - 配置
- 环境变量管理

#### public/ - 静态资源
- 不经过构建工具处理的文件
- favicon、robots.txt 等

#### tests/ - 测试
- **unit/**: 组件和工具函数单元测试
- **integration/**: 页面集成测试
- **e2e/**: Playwright/Cypress E2E 测试

---

### 2.3 数据库（database/）

- **schema.sql**: 主数据库结构（租户表、用户表等）
- **tenant_template.sql**: 租户数据库模板
- **create_tenant.sql**: 创建租户的 SQL 脚本
- **init.sh**: 数据库初始化 Shell 脚本

---

### 2.4 Nginx（nginx/）

- **nginx.conf**: Nginx 主配置
- **conf.d/**: 站点配置（反向代理、静态文件服务）
- **ssl/**: SSL 证书存放目录

---

### 2.5 文档（docs/）

- **STRUCTURE.md**: 项目结构说明（本文件）
- **API.md**: API 接口文档
- **DEPLOYMENT.md**: 部署指南
- **DEVELOPMENT.md**: 开发环境搭建
- **ARCHITECTURE.md**: 系统架构设计
- **SECURITY.md**: 安全规范和最佳实践

---

### 2.6 脚本（scripts/）

项目级自动化脚本：
- **setup.sh**: 一键初始化项目（安装依赖、配置环境）
- **deploy.sh**: 部署脚本
- **backup.sh**: 数据库备份
- **test.sh**: 运行所有测试

---

### 2.7 CI/CD（.github/workflows/）

- **ci.yml**: 持续集成（代码检查、测试）
- **cd.yml**: 持续部署（自动部署到服务器）
- **test.yml**: 自动化测试工作流

---

## 3. 必要文件清单

### 3.1 配置文件

#### 后端
- [x] `backend/requirements.txt` - 生产依赖
- [x] `backend/requirements-dev.txt` - 开发依赖
- [ ] `backend/pyproject.toml` - Python 项目配置
- [ ] `backend/pytest.ini` - pytest 配置
- [ ] `backend/alembic.ini` - Alembic 配置
- [ ] `backend/.env.example` - 环境变量示例

#### 前端
- [x] `frontend/package.json` - NPM 依赖
- [x] `frontend/vite.config.js` - Vite 配置
- [x] `frontend/tailwind.config.js` - Tailwind CSS 配置
- [x] `frontend/postcss.config.js` - PostCSS 配置
- [ ] `frontend/.eslintrc.cjs` - ESLint 配置
- [ ] `frontend/.prettierrc` - Prettier 配置
- [ ] `frontend/vitest.config.js` - Vitest 配置
- [x] `frontend/.env.example` - 环境变量示例

#### 项目级
- [x] `.gitignore` - Git 忽略规则
- [x] `.env.example` - 环境变量示例
- [x] `docker-compose.yml` - Docker Compose 配置
- [ ] `docker-compose.dev.yml` - 开发环境配置
- [ ] `docker-compose.prod.yml` - 生产环境配置
- [x] `Dockerfile` - Docker 镜像构建
- [ ] `Makefile` - Make 命令集合

---

### 3.2 文档文件

- [x] `README.md` - 项目主文档
- [x] `backend/README.md` - 后端文档
- [x] `frontend/README.md` - 前端文档
- [x] `database/README.md` - 数据库文档
- [x] `DEPLOY.md` - 部署文档
- [x] `docs/STRUCTURE.md` - 项目结构（本文件）
- [ ] `docs/API.md` - API 文档
- [ ] `docs/DEVELOPMENT.md` - 开发指南
- [ ] `docs/ARCHITECTURE.md` - 架构设计
- [ ] `docs/SECURITY.md` - 安全规范
- [ ] `CHANGELOG.md` - 变更日志
- [ ] `LICENSE` - 开源协议

---

### 3.3 脚本文件

#### 后端脚本
- [ ] `backend/scripts/init_db.py` - 初始化数据库
- [ ] `backend/scripts/create_tenant.py` - 创建租户
- [ ] `backend/scripts/seed_data.py` - 填充测试数据

#### 项目脚本
- [ ] `scripts/setup.sh` - 项目初始化
- [ ] `scripts/deploy.sh` - 部署脚本
- [ ] `scripts/backup.sh` - 备份脚本
- [ ] `scripts/test.sh` - 测试脚本

---

### 3.4 CI/CD 文件

- [ ] `.github/workflows/ci.yml` - 持续集成
- [ ] `.github/workflows/cd.yml` - 持续部署
- [ ] `.github/workflows/test.yml` - 自动化测试

---

## 4. 设计原则

### 4.1 后端设计原则（FastAPI）

1. **分层架构**: API → Service → Model，职责清晰
2. **依赖注入**: 使用 FastAPI 的 Depends 机制
3. **类型安全**: 充分利用 Pydantic 和类型提示
4. **测试优先**: 每个 Service 都有对应的单元测试
5. **数据库迁移**: 使用 Alembic 管理 schema 变更

### 4.2 前端设计原则（React + Vite）

1. **组件化**: 组件按功能和复用性分类
2. **Hooks 优先**: 使用自定义 Hooks 封装逻辑
3. **状态管理**: 全局状态用 Zustand，局部状态用 useState
4. **代码分割**: 使用 React.lazy 和动态 import
5. **样式隔离**: Tailwind CSS + CSS Modules

### 4.3 Monorepo 考虑

当前结构为 **Multi-repo**（前后端分离），如需 Monorepo：
- 使用 **pnpm workspaces** 或 **Turborepo**
- 共享类型定义（TypeScript）
- 统一依赖管理

---

## 5. 下一步行动

1. **补充缺失的配置文件**（见 3.1）
2. **创建核心目录结构**（app/api/, app/services/ 等）
3. **编写 API 文档**（docs/API.md）
4. **设置 CI/CD 流程**（GitHub Actions）
5. **编写开发指南**（docs/DEVELOPMENT.md）

---

## 6. 参考资料

- [FastAPI 最佳实践](https://fastapi.tiangolo.com/tutorial/)
- [React + Vite 官方文档](https://vitejs.dev/guide/)
- [Alembic 迁移指南](https://alembic.sqlalchemy.org/)
- [Tailwind CSS 文档](https://tailwindcss.com/docs)
