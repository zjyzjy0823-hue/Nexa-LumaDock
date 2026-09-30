# Nexa Core（v0.5.4）

Nexa 使用同一套 `backend/app` 业务代码、FastAPI 路由、模型和 Alembic 迁移。两个宿主独立运行：

| 宿主 | 启动链 | 数据库 | 监听地址 |
| --- | --- | --- | --- |
| Local | `Nexa.exe` → Tauri → `desktop_entry.py` sidecar | AppData 中的 SQLite | `127.0.0.1:17800` |
| Core | Docker → `core_entry.py` → `app.main:app` | 持久化 PostgreSQL | 容器内 `0.0.0.0:8000` |

Desktop Local Mode 与 Core Mode 是两个独立后端。Desktop 通过本地 Backend 加入 Core并保存 Client Credential，可用 `POST /api/v1/sync/run` 手动双向同步 Ledger、Websites 和 Data。Core 分配 authoritative revision；本地离线修改保存在 SQLite outbox 中，关闭 Core 不影响本地业务。Local 与 Core 的用户、Workspace ID 独立，远端实体在 Local 重新绑定本地归属；DataRecord 通过 DataCollection 解析归属。

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

预期健康接口返回 `status: ok`、产品版本 `0.5.4`，迁移版本为 `0014_multi_entity_sync`。PostgreSQL 使用 `nexa-postgres-data` 命名卷；普通 `docker compose -f docker-compose.core.yml down` 后数据仍保留。调整数据库用户名或库名时，相应修改上面的检查命令。Core 的多实体同步协议见 [sync.md](sync.md)。

## Workspace 与 Client 身份

每个用户现在有一个自动创建的 Personal Workspace，作为 Dashboard、网站、设备、智能体、数据、自动化和账本的归属边界。现有用户和资源由 `0009` 迁移回填。当前 API 自动选用该 Workspace；多 Workspace 创建和切换尚未实现。Agent 原有的 `workspace` 字符串仍是 UI 配置，独立于新的 `workspace_id`。

Client 表示一份 Nexa 应用安装实例，与 Device（硬件及 Runtime 遥测）和 Agent（AI Runtime）是不同实体。Desktop 在 AppData 中保存稳定的 `installation.id` UUID。它只是身份标识，**不是认证凭证、Token、密钥或同步状态**。当前可用用户 JWT 访问 `GET/PATCH /api/v1/workspace`，以及 `GET/POST /api/v1/clients`、`GET /api/v1/clients/{id}`、`POST /api/v1/clients/{id}/revoke`。Client 管理只作用于当前用户的 Personal Workspace；撤销保留记录，再次用同一 installation ID 注册会返回 409。

`Client Identity` 是安装实例 UUID；`Client Credential` 是 Core 一次性签发的 `nc_live_` bearer secret。Core 仅存 SHA-256、末四位和签发时间。它与用户 JWT、`sk_live_` API Key、`nd_live_` Device Token、`na_live_` Agent Token 相互独立。用户 JWT 负责 enrollment、轮换和撤销；Client Credential 可访问 `GET /api/v1/client/me`、`POST /api/v1/client/heartbeat` 以及 Core Sync API。Sync 从认证后的 `Client.workspace_id` 获取归属，不接受客户端自报的归属 ID。

Core 端以用户 JWT 调用 `POST /api/v1/clients/enroll`，首次返回明文 credential 一次，并设置 `Cache-Control: no-store`。再次 enrollment 返回 409；`POST /api/v1/clients/{id}/credential` 显式轮换并立即使旧凭证失效。`POST /api/v1/clients/{id}/revoke` 清除 hash，旧凭证立即失效，保留撤销记录。

Desktop Local Backend 可用本地用户 JWT 调用 `POST /api/v1/core/connect`，传入 `coreUrl`、Core 用户名和密码、`clientName`、`platform`、`appVersion`。它依次检查 Core 健康状态、登录、读取 Workspace、注册 Client、用新凭证验证 `/api/v1/client/me`，然后在 AppData 中保存非敏感的 `connection.json` 和单独的 `credential` 文件。用户名密码和临时 Core JWT 不落盘。`GET /api/v1/core/connection` 只返回元数据；`POST /api/v1/core/connection/test` 验证保存的凭证；`DELETE /api/v1/core/connection` 仅删除本地连接，不撤销远端 Client。Core 不开放这些 Local 接口。

如果 Core 已完成 enrollment，但 Local 在保存连接前失败，用户可重新输入 Core 账号密码再调用 `connect`。Local 会在 Core 返回 409 后读取**当前用户 Personal Workspace** 的 Client 列表，只匹配本机 `installation.id`；未撤销的匹配项经显式 credential rotation 取得新凭证，旧凭证立即失效。已撤销的 Client 保持撤销状态；找不到匹配项时连接失败，不会轮换其他安装实例。已存在本地连接元数据时，普通 `connect` 仍拒绝覆盖。

本地连接元数据使用严格验证的 `schemaVersion: 1`，不包含凭证。旧版无版本字段的有效连接元数据会在读取时升级。凭证通过 `CredentialStore` 接口保存；当前实现为原子写入的 `FileCredentialStore`，未来可替换为系统 Credential Manager 或 Keychain。游标、outbox 和同步诊断保存在 Local SQLite 中，不写入连接元数据。

公网 Core 必须通过 HTTPS 暴露。HTTP 仅适用于可信 localhost/LAN 开发环境；连接流程不会跳过 TLS 证书验证或自动跟随重定向。Desktop 仍只请求 `127.0.0.1:17800`，由 Python Local Backend 请求 Core，WebView 不直连 Core。Client 凭证当前保存在受 AppData 用户权限保护的独立文件；未来可迁至 Windows Credential Manager、macOS Keychain、Android Keystore 或 iOS Keychain。`/connection/test` 对远端 401 统一报告 `unauthorized`，包括撤销情形，因为 Core 不泄露凭证失效原因。

v0.5.3 引入手动双向 Ledger 同步；v0.5.4 扩展到 `ledger.category`、`ledger.transaction`、`website.category`、`website`、`data.collection`、`data.record`。冲突持久保留本地编辑，其 remote snapshot 随 Core 后续 revision 刷新；后台同步、同步 UI、冲突解决 UI、Workspace 切换尚未启用。Settings、Device、Agent、Automation 与 Dashboard 尚未同步。

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

## v0.5.4 升级与协议兼容

0014 为 WebsiteCategory、Website、DataCollection、DataRecord 增加 `sync_revision` 和 `deleted_at`。`bootstrap_version` 将已完成 v0.5.3 Ledger 初始化的 Core 标记为 generation 1，首次 v2 请求仅接纳 generation 2 的 Website/Data；现有 Ledger revision/change 不重建。bootstrap 和普通 API 发布均持有 Workspace 锁，实体更新、revision 分配与 change 同事务提交。

Sync 请求必须显式声明 `protocolVersion=2`（GET query / POST JSON）；缺省按旧版 v1 处理并返回 HTTP 409 `sync_protocol_mismatch`，不引导 bootstrap 或写入 mutation history。响应为 v2，旧 Client 无法跳过新实体 revision。升级 Client 请求旧 Core 时在 freeze/replay 前检测响应版本，报告 `protocol_mismatch` 并保留 queue/cursor。连接元数据的 `schemaVersion: 1` 不随 Sync 协议变更。

Settings 仍为 Local-only：整数主键的 UserPreference/settings_json 同时承载用户偏好与本机连接、安全信息，本版不迁移、不注册 Adapter。未来可能同步 theme、language、timezone、notifications、appearance；sync、security、Core URL、Client credential、installation id、DB path 和设备配置必须留在本机。密码、token、Core JWT 和 `nc_live_` 凭证不作为系统业务字段发布。
