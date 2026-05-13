# 企业级融合架构设计

## 1. 系统架构概览

### 1.1 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         API Gateway (Nginx)                      │
│                    (路由、限流、SSL、负载均衡)                      │
└────────────┬────────────────────────────────────────────────────┘
             │
    ┌────────┴────────┐
    │                 │
    ▼                 ▼
┌─────────┐      ┌─────────────────────────────────────────┐
│ Frontend│      │         Backend Services                │
│  React  │      │         (FastAPI)                       │
└─────────┘      └──────────┬──────────────────────────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
      ┌──────────────┐ ┌──────────┐ ┌──────────────┐
      │ Auth Service │ │  Sign-In │ │Course Service│
      │   认证服务    │ │  Service │ │   刷课服务    │
      └──────┬───────┘ └────┬─────┘ └──────┬───────┘
             │              │               │
             └──────────────┼───────────────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │PostgreSQL│  │  Redis   │  │  Queue   │
        │  主数据库 │  │缓存/会话  │  │ RabbitMQ │
        └──────────┘  └──────────┘  └──────────┘
```

## 2. 服务拆分方案

### 2.1 核心服务模块

#### **Auth Service (认证服务)**
- **职责**: 用户认证、授权、会话管理
- **功能**:
  - 用户注册/登录 (邮箱密码、OAuth)
  - JWT Token 生成/验证/刷新
  - 多租户隔离
  - 权限管理 (RBAC)
- **技术栈**: FastAPI + PostgreSQL + Redis
- **端口**: 8001

#### **Sign-In Service (签到服务)**
- **职责**: 统一签到功能
- **功能**:
  - 超星签到 (普通、二维码、位置、手势、拍照)
  - 智慧树签到
  - 签到记录管理
  - 签到任务调度
- **技术栈**: FastAPI + PostgreSQL + Redis + RabbitMQ
- **端口**: 8002

#### **Course Service (刷课服务)**
- **职责**: 自动学习课程
- **功能**:
  - 超星刷课 (视频、文档、测验、直播)
  - 智慧树刷课
  - 学习进度跟踪
  - 任务队列管理
- **技术栈**: FastAPI + PostgreSQL + Redis + RabbitMQ
- **端口**: 8003

#### **Notification Service (通知服务)**
- **职责**: 消息推送
- **功能**:
  - 邮件通知
  - PushPlus 推送
  - Bark 推送
  - WebSocket 实时通知
- **技术栈**: FastAPI + Redis
- **端口**: 8004

### 2.2 服务通信

```
┌──────────────┐     HTTP/REST      ┌──────────────┐
│ Auth Service │◄──────────────────►│ Sign-In Svc  │
└──────────────┘                    └──────────────┘
       │                                    │
       │         ┌──────────────┐          │
       └────────►│ Course Svc   │◄─────────┘
                 └──────────────┘
                        │
                        ▼
                 ┌──────────────┐
                 │Notification  │
                 │   Service    │
                 └──────────────┘
```

## 3. 统一数据模型

### 3.1 核心实体

#### **User (用户)**
```sql
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    username VARCHAR(100),
    password_hash VARCHAR(255),
    phone VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    FOREIGN KEY (tenant_id) REFERENCES tenants(tenant_id)
);
CREATE INDEX idx_users_tenant ON users(tenant_id);
CREATE INDEX idx_users_email ON users(email);
```

#### **Tenant (租户)**
```sql
CREATE TABLE tenants (
    tenant_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    domain VARCHAR(255) UNIQUE,
    settings JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);
```

#### **Platform Account (平台账号)**
```sql
CREATE TABLE platform_accounts (
    account_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    platform VARCHAR(50) NOT NULL, -- 'chaoxing', 'zhihuishu'
    username VARCHAR(255) NOT NULL,
    password_encrypted TEXT NOT NULL,
    cookies JSONB,
    last_login TIMESTAMP,
    is_valid BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE(user_id, platform)
);
CREATE INDEX idx_platform_accounts_user ON platform_accounts(user_id);
```

#### **Course (课程)**
```sql
CREATE TABLE courses (
    course_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    platform VARCHAR(50) NOT NULL,
    platform_course_id VARCHAR(255) NOT NULL,
    title VARCHAR(500) NOT NULL,
    teacher VARCHAR(255),
    progress DECIMAL(5,2) DEFAULT 0.00,
    total_chapters INTEGER DEFAULT 0,
    completed_chapters INTEGER DEFAULT 0,
    status VARCHAR(50) DEFAULT 'active', -- 'active', 'completed', 'paused'
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE(user_id, platform, platform_course_id)
);
CREATE INDEX idx_courses_user ON courses(user_id);
CREATE INDEX idx_courses_status ON courses(status);
```

#### **Sign-In Record (签到记录)**
```sql
CREATE TABLE signin_records (
    record_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    platform VARCHAR(50) NOT NULL,
    course_id UUID,
    activity_id VARCHAR(255),
    signin_type VARCHAR(50), -- 'general', 'qrcode', 'location', 'photo', 'gesture'
    location_data JSONB,
    status VARCHAR(50) DEFAULT 'pending', -- 'pending', 'success', 'failed'
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE SET NULL
);
CREATE INDEX idx_signin_user ON signin_records(user_id);
CREATE INDEX idx_signin_status ON signin_records(status);
CREATE INDEX idx_signin_created ON signin_records(created_at DESC);
```

#### **Learning Record (学习记录)**
```sql
CREATE TABLE learning_records (
    record_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    course_id UUID NOT NULL,
    chapter_id VARCHAR(255),
    chapter_title VARCHAR(500),
    task_type VARCHAR(50), -- 'video', 'document', 'quiz', 'live'
    duration INTEGER, -- 秒
    progress DECIMAL(5,2),
    status VARCHAR(50) DEFAULT 'in_progress',
    started_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (course_id) REFERENCES courses(course_id) ON DELETE CASCADE
);
CREATE INDEX idx_learning_user ON learning_records(user_id);
CREATE INDEX idx_learning_course ON learning_records(course_id);
```

#### **Task Queue (任务队列)**
```sql
CREATE TABLE task_queue (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    task_type VARCHAR(50) NOT NULL, -- 'signin', 'course_study'
    priority INTEGER DEFAULT 5,
    payload JSONB NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    scheduled_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error_message TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);
CREATE INDEX idx_task_status ON task_queue(status, scheduled_at);
CREATE INDEX idx_task_user ON task_queue(user_id);
```

## 4. API 网关设计

### 4.1 路由规则

```nginx
# API Gateway Configuration
upstream auth_service {
    server localhost:8001;
}

upstream signin_service {
    server localhost:8002;
}

upstream course_service {
    server localhost:8003;
}

upstream notification_service {
    server localhost:8004;
}

server {
    listen 80;
    server_name api.example.com;

    # 认证服务
    location /api/v1/auth/ {
        proxy_pass http://auth_service/;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # 签到服务
    location /api/v1/signin/ {
        proxy_pass http://signin_service/;
        proxy_set_header Authorization $http_authorization;
    }

    # 刷课服务
    location /api/v1/courses/ {
        proxy_pass http://course_service/;
        proxy_set_header Authorization $http_authorization;
    }

    # 通知服务
    location /api/v1/notifications/ {
        proxy_pass http://notification_service/;
        proxy_set_header Authorization $http_authorization;
    }

    # WebSocket
    location /ws/ {
        proxy_pass http://notification_service/ws/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### 4.2 统一 API 规范

#### **请求格式**
```json
{
  "method": "POST",
  "headers": {
    "Authorization": "Bearer <jwt_token>",
    "X-Tenant-ID": "<tenant_id>",
    "Content-Type": "application/json"
  },
  "body": {
    "data": {}
  }
}
```

#### **响应格式**
```json
{
  "success": true,
  "data": {},
  "message": "操作成功",
  "timestamp": "2026-02-17T10:00:00Z",
  "request_id": "uuid"
}
```

#### **错误响应**
```json
{
  "success": false,
  "error": {
    "code": "AUTH_001",
    "message": "认证失败",
    "details": {}
  },
  "timestamp": "2026-02-17T10:00:00Z",
  "request_id": "uuid"
}
```

## 5. 企业级特性

### 5.1 日志系统

#### **结构化日志**
```python
# 统一日志格式
{
    "timestamp": "2026-02-17T10:00:00Z",
    "level": "INFO",
    "service": "signin-service",
    "request_id": "uuid",
    "user_id": "uuid",
    "tenant_id": "uuid",
    "message": "签到成功",
    "context": {
        "platform": "chaoxing",
        "signin_type": "qrcode"
    }
}
```

#### **日志级别**
- **DEBUG**: 详细调试信息
- **INFO**: 常规操作日志
- **WARNING**: 警告信息
- **ERROR**: 错误信息
- **CRITICAL**: 严重错误

#### **日志存储**
- 本地文件: `/var/log/app/{service}/{date}.log`
- 集中式: ELK Stack (Elasticsearch + Logstash + Kibana)
- 保留期: 30 天

### 5.2 监控系统

#### **指标监控 (Prometheus)**
```yaml
# 关键指标
- http_requests_total: 请求总数
- http_request_duration_seconds: 请求耗时
- signin_success_rate: 签到成功率
- course_completion_rate: 课程完成率
- active_users: 活跃用户数
- task_queue_length: 任务队列长度
- database_connections: 数据库连接数
```

#### **健康检查**
```python
# /health endpoint
{
    "status": "healthy",
    "services": {
        "database": "up",
        "redis": "up",
        "rabbitmq": "up"
    },
    "uptime": 86400
}
```

#### **告警规则**
- API 错误率 > 5%
- 响应时间 > 2s
- 数据库连接数 > 80%
- 磁盘使用率 > 85%
- 内存使用率 > 90%

### 5.3 限流策略

#### **令牌桶算法**
```python
# Redis 实现
class RateLimiter:
    def __init__(self, redis_client):
        self.redis = redis_client

    async def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window: int
    ) -> bool:
        """
        key: 限流键 (user_id, ip, etc.)
        max_requests: 最大请求数
        window: 时间窗口(秒)
        """
        current = await self.redis.incr(key)
        if current == 1:
            await self.redis.expire(key, window)
        return current <= max_requests
```

#### **限流规则**
```yaml
# 全局限流
global:
  rate: 1000 req/min
  burst: 100

# 用户级限流
per_user:
  rate: 100 req/min
  burst: 20

# IP 限流
per_ip:
  rate: 200 req/min
  burst: 50

# 端点限流
endpoints:
  /api/v1/signin/execute:
    rate: 10 req/min
  /api/v1/courses/start:
    rate: 5 req/min
```

### 5.4 缓存策略

#### **多级缓存**
```
L1: 应用内存缓存 (LRU, 1000 items, 5min TTL)
L2: Redis 缓存 (1 hour TTL)
L3: 数据库
```

#### **缓存键设计**
```python
# 用户信息
user:{user_id}:profile

# 课程列表
user:{user_id}:courses:{platform}

# 签到记录
user:{user_id}:signin:recent

# 会话
session:{session_id}
```

#### **缓存更新策略**
- **Cache-Aside**: 读取时缓存未命中则查询数据库并写入缓存
- **Write-Through**: 写入时同步更新缓存和数据库
- **Write-Behind**: 异步更新数据库

### 5.5 安全措施

#### **认证与授权**
- JWT Token (HS256)
- Token 过期时间: 1 小时
- Refresh Token: 7 天
- 多租户隔离

#### **数据加密**
- 密码: bcrypt (cost=12)
- 平台账号密码: AES-256-GCM
- 传输: TLS 1.3
- 敏感数据: 字段级加密

#### **安全头**
```python
# FastAPI Middleware
app.add_middleware(
    SecurityHeadersMiddleware,
    headers={
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "X-XSS-Protection": "1; mode=block",
        "Strict-Transport-Security": "max-age=31536000"
    }
)
```

## 6. 技术选型

### 6.1 后端技术栈

| 组件 | 技术 | 版本 | 说明 |
|------|------|------|------|
| Web 框架 | FastAPI | 0.115+ | 高性能异步框架 |
| ORM | SQLAlchemy | 2.0+ | 数据库 ORM |
| 数据验证 | Pydantic | 2.0+ | 数据验证 |
| 数据库 | PostgreSQL | 16+ | 主数据库 |
| 缓存 | Redis | 7.0+ | 缓存/会话 |
| 消息队列 | RabbitMQ | 3.13+ | 任务队列 |
| 任务调度 | Celery | 5.3+ | 异步任务 |
| HTTP 客户端 | httpx | 0.27+ | 异步 HTTP |

### 6.2 前端技术栈

| 组件 | 技术 | 版本 | 说明 |
|------|------|------|------|
| 框架 | React | 18+ | UI 框架 |
| 构建工具 | Vite | 5+ | 构建工具 |
| 路由 | React Router | 6+ | 路由管理 |
| 状态管理 | Zustand | 4+ | 状态管理 |
| UI 库 | Tailwind CSS | 3+ | 样式框架 |
| 图标 | Lucide React | 0.400+ | 图标库 |
| HTTP 客户端 | Axios | 1.7+ | HTTP 请求 |

### 6.3 DevOps 工具

| 组件 | 技术 | 说明 |
|------|------|------|
| 容器化 | Docker | 容器运行时 |
| 编排 | Docker Compose | 本地开发 |
| 反向代理 | Nginx | API 网关 |
| 监控 | Prometheus + Grafana | 指标监控 |
| 日志 | ELK Stack | 日志聚合 |
| CI/CD | GitHub Actions | 持续集成 |

## 7. 部署架构

### 7.1 开发环境

```yaml
# docker-compose.dev.yml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: unified_signin
      POSTGRES_USER: dev
      POSTGRES_PASSWORD: dev123
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  rabbitmq:
    image: rabbitmq:3.13-management
    ports:
      - "5672:5672"
      - "15672:15672"

  auth-service:
    build: ./backend/auth-service
    ports:
      - "8001:8000"
    depends_on:
      - postgres
      - redis

  signin-service:
    build: ./backend/signin-service
    ports:
      - "8002:8000"
    depends_on:
      - postgres
      - redis
      - rabbitmq

  course-service:
    build: ./backend/course-service
    ports:
      - "8003:8000"
    depends_on:
      - postgres
      - redis
      - rabbitmq
```

### 7.2 生产环境

```
┌─────────────────────────────────────────┐
│          Load Balancer (Nginx)          │
└────────────┬────────────────────────────┘
             │
    ┌────────┴────────┐
    │                 │
    ▼                 ▼
┌─────────┐      ┌─────────┐
│ Node 1  │      │ Node 2  │
│ (Docker)│      │ (Docker)│
└─────────┘      └─────────┘
    │                 │
    └────────┬────────┘
             │
    ┌────────┴────────┐
    │                 │
    ▼                 ▼
┌──────────┐    ┌──────────┐
│PostgreSQL│    │  Redis   │
│ (Primary)│    │ Cluster  │
└──────────┘    └──────────┘
    │
    ▼
┌──────────┐
│PostgreSQL│
│ (Replica)│
└──────────┘
```

## 8. 迁移路径

### 8.1 阶段一: 基础设施 (Week 1-2)
- 搭建 PostgreSQL + Redis + RabbitMQ
- 配置 Docker 环境
- 实现 Auth Service
- 实现统一数据模型

### 8.2 阶段二: 核心服务 (Week 3-4)
- 迁移超星签到功能到 Sign-In Service
- 迁移智慧树签到功能
- 实现任务队列系统
- 实现通知服务

### 8.3 阶段三: 刷课服务 (Week 5-6)
- 迁移超星刷课功能到 Course Service
- 迁移智慧树刷课功能
- 实现学习进度跟踪
- 实现任务调度

### 8.4 阶段四: 企业特性 (Week 7-8)
- 实现日志系统
- 实现监控告警
- 实现限流缓存
- 性能优化

## 9. 性能指标

### 9.1 目标 SLA

| 指标 | 目标值 |
|------|--------|
| API 响应时间 (P95) | < 500ms |
| API 响应时间 (P99) | < 1s |
| 可用性 | 99.9% |
| 签到成功率 | > 95% |
| 刷课成功率 | > 90% |
| 并发用户数 | 1000+ |

### 9.2 容量规划

| 资源 | 配置 |
|------|------|
| CPU | 4 核 |
| 内存 | 8 GB |
| 磁盘 | 100 GB SSD |
| 数据库连接池 | 20 |
| Redis 连接池 | 50 |

## 10. 总结

本架构设计实现了:
1. **服务化**: 按功能拆分为独立服务
2. **标准化**: 统一数据模型和 API 规范
3. **可扩展**: 支持水平扩展和新平台接入
4. **高可用**: 多级缓存、限流、监控告警
5. **安全性**: 多租户隔离、数据加密、权限控制

适用于企业级生产环境部署。
