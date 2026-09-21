# 多租户数据库架构

## 架构设计

**隔离方案**：独立数据库（每用户一个 PostgreSQL 数据库）

```
main_db (主数据库)
└── users 表：用户认证 + 租户映射

tenant_<username> (租户数据库)
├── todos 表
├── attachments 表
└── sessions 表
```

## 租户命名规则

格式：`tenant_<username>`（用户名只包含小写字母和数字）

示例：
- 用户名 `alice` → `tenant_alice`
- 用户名 `student42` → `tenant_student42`

## 初始化步骤

### Docker entrypoint（推荐）

Compose 将仓库根目录下的 `database/` 只读挂载到
`/docker-entrypoint-initdb.d/`。在全新的 PostgreSQL 数据卷上，官方
entrypoint 会按文件名顺序执行以下文件（已有数据卷不会重复执行）：

1. `database/00-schema.sql`：在 `main_db`（`POSTGRES_DB`）中创建主库结构。
2. `database/01-create_tenant.sql`：在 `main_db` 中安装保留的辅助定义。
3. `database/02-bootstrap-tenant-template.sh`：在容器内创建
   `tenant_template`（DDL 必须在事务外执行），然后使用挂载路径
   `/docker-entrypoint-initdb.d/templates/tenant_template.sql` 应用
   `database/templates/tenant_template.sql`。

脚本最后执行 `ALTER DATABASE tenant_template WITH IS_TEMPLATE true`，
这样 PostgreSQL 会拒绝 `DROP DATABASE tenant_template`。这里没有关闭
`ALLOW_CONNECTIONS`，因为 `pg_dumpall` 会跳过不允许连接的库，备份里就
少了模板库。

`02-bootstrap-tenant-template.sh` 是 Docker entrypoint 的辅助脚本，不能
直接按容器内的绝对路径在宿主机执行。仓库的 `.gitattributes` 强制它保持
LF 换行；如果在 Windows 上用别的方式拷贝导致变成 CRLF，初始化会中途
失败，数据库里就不会有 `tenant_template`。

### 应用启动时的自检与修复

服务器版 app 启动后会在后台检查 `users` 表和 `tenant_template` 库，缺哪个就用
镜像里自带的 `00-schema.sql` 和 `tenant_template.sql` 补上（`backend/app/db/bootstrap.py`）。
所以数据卷没有跑过初始化脚本时，通常重启一次 app 就能恢复注册。检查结果写在
`/health` 的 `schema` 字段：`ok`、`missing_users`、`missing_tenant_template` 或
`unknown`。数据库账号没有 CREATEDB 权限时修复会失败，日志里会说明原因。
设置 `DB_AUTO_BOOTSTRAP=false` 可以关闭这个行为。

### 宿主机手工初始化

以下命令均从仓库根目录执行；仅在对应数据库尚不存在时运行 `createdb`：

```bash
cd /path/to/university-helper

createdb -U postgres main_db             # 若 main_db 尚不存在
psql -v ON_ERROR_STOP=1 -U postgres -d main_db -f database/00-schema.sql
psql -v ON_ERROR_STOP=1 -U postgres -d main_db -f database/01-create_tenant.sql
createdb -U postgres tenant_template     # 若 tenant_template 尚不存在
psql -v ON_ERROR_STOP=1 -U postgres -d tenant_template \
  -f database/templates/tenant_template.sql
psql -v ON_ERROR_STOP=1 -U postgres -d main_db \
  -c "ALTER DATABASE tenant_template WITH IS_TEMPLATE true;"
```

这组宿主机命令是 `02-bootstrap-tenant-template.sh` 的等价操作；不要在
事务中执行 `CREATE DATABASE`。

## 创建新租户

用户注册时由当前应用的 `AuthService` 自动创建租户数据库。应用通过
`autocommit=True` 的 PostgreSQL 连接执行
`CREATE DATABASE <tenant_db_name> TEMPLATE tenant_template`；不依赖
SQL 函数调用。

运维需要手工创建租户时，也必须使用事务外的 CLI，例如：

```bash
cd /path/to/university-helper
createdb -U postgres --template=tenant_template tenant_alice
```

应用注册流程仍负责写入 `users` 记录并生成对应的租户名称；手工创建
数据库不会替代用户注册流程。PostgreSQL 不允许在函数内执行
`CREATE DATABASE`，因此不要调用 `create_tenant_database()`。

## 动态连接池（Node.js 示例）

```javascript
const { Pool } = require('pg');
const pools = new Map();

function getTenantPool(tenantDbName) {
  if (!pools.has(tenantDbName)) {
    pools.set(tenantDbName, new Pool({
      host: 'localhost',
      database: tenantDbName,
      user: 'app_user',
      password: process.env.DB_PASSWORD,
      max: 10
    }));
  }
  return pools.get(tenantDbName);
}
```

## 表结构说明

### 主数据库 (main_db)

**users 表**：
- `id`：用户 ID（主键）
- `username`：用户名（唯一）
- `email`：邮箱（唯一）
- `password_hash`：密码哈希
- `tenant_db_name`：租户数据库名（唯一）
- `created_at`：创建时间
- `updated_at`：更新时间

### 租户数据库 (tenant_*)

**todos 表**：待办事项
**attachments 表**：文件附件
**sessions 表**：会话管理
