# Nexa Core（v0.5.2 Phase 2）

Nexa 使用同一套 `backend/app` 业务代码、FastAPI 路由、模型和 Alembic 迁移。两个宿主独立运行：

| 宿主 | 启动链 | 数据库 | 监听地址 |
| --- | --- | --- | --- |
| Local | `Nexa.exe` → Tauri → `desktop_entry.py` sidecar | AppData 中的 SQLite | `127.0.0.1:17800` |
| Core | Docker → `core_entry.py` → `app.main:app` | 持久化 PostgreSQL | 容器内 `0.0.0.0:8000` |

Desktop Local Mode 与 Core Mode 是两个独立后端。本阶段**没有 Local ↔ Core 数据同步**；启动 Core 不会迁移或共享 Desktop 数据，关闭 Core 也不影响 Desktop。本阶段不改变 Tauri 到本地 sidecar 的网络连接。

## 启动 Core

从仓库根目录复制示例配置，并将 `POSTGRES_PASSWORD` 与 `DATABASE_URL` 中的密码改为同一个强密码，同时将 `JWT_SECRET` 改为独立生成的长随机值。`.env.core` 已被 Git 忽略；不要提交它。

```powershell
Copy-Item .env.core.example .env.core
# 编辑 .env.core 中的密码和 JWT_SECRET
docker compose -f docker-compose.core.yml up --build -d
```

若数据库密码包含 URL 特殊字符，请在 `DATABASE_URL` 中进行 URL 编码。Compose 会先等待 PostgreSQL 的 `pg_isready`，Core 启动时执行同一套 Alembic `upgrade head`。两项服务各有 healthcheck。

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
docker compose -f docker-compose.core.yml exec postgres psql -U nexa -d nexa -Atc 'SELECT version_num FROM alembic_version'
```

预期健康接口返回 `status: ok`，迁移版本为 `0009_workspace_clients`。PostgreSQL 使用 `nexa-postgres-data` 命名卷；普通 `docker compose -f docker-compose.core.yml down` 后数据仍保留。调整数据库用户名或库名时，相应修改上面的检查命令。

## Workspace 与 Client 身份

每个用户现在有一个自动创建的 Personal Workspace，作为 Dashboard、网站、设备、智能体、数据、自动化和账本的归属边界。现有用户和资源由 `0009` 迁移回填。当前 API 自动选用该 Workspace；多 Workspace 创建和切换尚未实现。Agent 原有的 `workspace` 字符串仍是 UI 配置，独立于新的 `workspace_id`。

Client 表示一份 Nexa 应用安装实例，与 Device（硬件及 Runtime 遥测）和 Agent（AI Runtime）是不同实体。Desktop 在 AppData 中保存稳定的 `installation.id` UUID。它只是身份标识，**不是认证凭证、Token、密钥或同步状态**。当前可用用户 JWT 访问 `GET/PATCH /api/v1/workspace`，以及 `GET/POST /api/v1/clients`、`GET /api/v1/clients/{id}`、`POST /api/v1/clients/{id}/revoke`。Client 管理只作用于当前用户的 Personal Workspace；撤销保留记录，再次用同一 installation ID 注册会返回 409。

Phase 2 仍没有 Client Authentication、Enrollment 或 Local/Core 数据同步。Desktop 仍只请求本地后端。

## 配置

| 变量 | Local | Core |
| --- | --- | --- |
| `NEXA_MODE` | Desktop 强制设为 `local`；Web 开发默认 `local` | 必须为 `core` |
| `DATABASE_URL` | 默认 `sqlite:///./nexa.db`；Desktop 强制使用 AppData 的 `nexa.db` | 必填 `postgresql+psycopg://...`，禁止 SQLite |
| `JWT_SECRET` | Desktop 的 `secret.key`；Web 开发需自行配置 | 必填，至少 16 字符；容器重启后应保持不变 |
| `CORS_ORIGINS` | Desktop 含 Tauri 和本地 Vite origins | 逗号分隔的明确 origins；不允许 `*`，未配置时为空 |
| `APP_TIMEZONE` | 默认 `Asia/Shanghai` | 默认 `Asia/Shanghai` |
| `ALLOW_REGISTRATION` | 默认 `true` | 默认 `true`；设为 `false` 可关闭公开注册 |
| `NEXA_HOST` / `NEXA_PORT` | Desktop 固定 `127.0.0.1:17800` | 入口默认 `0.0.0.0:8000`；Docker Compose 的端口映射和健康检查按 8000 配置 |

Core 也可在 `backend` 目录安装 `requirements-postgres.txt` 后运行 `python core_entry.py`；此时设置 `NEXA_MODE=core`、PostgreSQL URL 和 JWT secret。配置错误会在连接数据库前退出，错误消息不会打印数据库密码。
