# SPEC：已配对设备免二次登录只读 Shared Space（方案 B · Sidecar 代理）

- 状态：**已实现（待合并 main / 待发版）**
- 分支：`feat/space-device-reads`
- 目标：用户在「同步设置」里已用 `nc_live_` 连上 Core 后，打开共享空间**不再要求登录 Core 账号**；设备只能**只读 `standard` 档**，`protected` / `e2ee` 与所有写操作仍需登录 Core。
- 非目标：不做离线镜像缓存（后续可在此代理层上叠加）、不放行设备凭据直访 `/api/v1/spaces`、不改 e2ee 密码学与信封格式。

## 实现状态

| 阶段 | 提交 | 说明 |
|---|---|---|
| Core 端点 | `05fe1f3` | `/api/v1/client/space-reads/*`（7 条），设备主体 + standard 硬门禁 + 授权解析 + 审计；`/api/v1/spaces` 对设备凭据仍 403（有回归测试） |
| Sidecar 代理 + 前端 | `c24d223` | Local 代理 7 条（流式下载、传输门禁、UUID 校验）；前端 `kind='device-read'` 只读模式与 UI 收口 |

**开关**（默认关闭，需显式打开）：

- Core：`STUDIOLO_SPACE_DEVICE_READS=true`
- 默认授权（本人 workspace 的 standard 空间免逐台授权）：`STUDIOLO_SPACE_DEVICE_DEFAULT_GRANT=true`（默认 true）

**冒烟证据**（真实 `nc_live_` 凭据）：

| 请求 | 本地 Core | 公网 Core |
|---|---|---|
| `GET /client/space-reads/status` | 200 `ready, spaceCount=1` | 200 同 |
| `GET /client/space-reads/spaces` | 200 `日常笔记(standard, 2 条)` | 200 同 |
| `GET /api/v1/spaces`（设备凭据） | 403 | 403 |
| 不存在的空间 | 404 | — |

**测试**：后端 37 passed（代理 18 + Core 13 + 共享空间 6）、前端 15 passed、`npm run build` 通过。


## 0. 既有事实（实现时不要推翻）

- 设备凭据 `nc_live_`：`backend/app/models.py:68-85`（`clients` 表，`(workspace_id, installation_id)` 唯一，`token_hash`，`revoked_at`，**无过期**），校验依赖 `backend/app/security.py:22-33::client_from_token`
- 空间 API 现有鉴权：`backend/app/space/routes.py:46-65::_space_actor`，只接受用户 JWT 或 `ss_live_`/`sv_live_`；`nc_live_` 显式 403（**保持不变**）
- 访问主体：`backend/app/space/service.py:70-76::SpaceActor(kind, workspace_id, user_id, actor_id, token)`
- 档位门禁既有写法：`service.py:333`（`standard_token` 只能 `standard`）、`service.py:348`（`vault_token` 只能 `protected`）
- 授权表 `space_device_grants` 已存在但无人使用：`models.py:626-641`（`workspace_id/space_id/client_id/device_label/can_read/can_write/revoked_at`）
- 审计表 `space_access_audit_logs.space_id` 为 NOT NULL：`models.py:789`
- 本机 Local API 目前**没有**任何代理端点：`backend/app/api/core.py:33-56` 只有 connect/connection/test/delete
- 前端直连 Core：`src/services/spaceApi.ts`（`route.token` + `route.origin`），28 个导出函数中只读的仅 4 个
- 路由选择：`src/stores/space.ts:130-150`（`route` / `coreSignInRequired`），登录墙在 `src/pages/SpacePage.vue:976-978`

## 1. Core 侧契约（新路由组）

新文件 `backend/app/api/client_space_reads.py`，`router = APIRouter(prefix="/api/v1/client/space-reads", tags=["client-space-reads"])`，在 `backend/app/main.py` 注册。

鉴权依赖：`client = Depends(client_from_token)`（只认 `nc_live_`，已吊销即 401）。由 `client.workspace_id` → `workspace = get_workspace(...)`，`owner_user_id = workspace.owner_user_id`。

构造设备主体：

```python
SpaceActor(kind="device", workspace_id=client.workspace_id,
           user_id=workspace.owner_user_id, actor_id=f"client:{client.id}")
```

`SpaceActor.kind` 的 `Literal` 增加 `"device"`。

### 授权解析（两案共用，MVP 规则）

`_granted_space_ids(db, client, workspace) -> set[str]`：

1. `space_device_grants` 中 `client_id == client.id`、`revoked_at IS NULL`、`can_read IS TRUE` 的 `space_id`
2. 默认授权（开关 `STUDIOLO_SPACE_DEVICE_DEFAULT_GRANT`，默认 `"1"`）：该 workspace 下 `shared_spaces.user_id == workspace.owner_user_id` 且 `tier == 'standard'` 且 `archived_at IS NULL` 的空间，视为已授权
3. 只保留 `tier == 'standard'` 且未归档的空间

### 端点

| 方法 | 路径 | 响应 | 说明 |
|---|---|---|---|
| GET | `/status` | `{status: "ready"\|"no_grant", workspaceId, spaceCount}` | 探测用，永不 500 |
| GET | `/spaces` | `list[SpaceOut]` | 按授权过滤 |
| GET | `/spaces/{space_id}` | `SpaceOut` | 非授权 / 非 standard / 跨工作区 → **404** |
| GET | `/spaces/{space_id}/entries?search=&entryType=&limit=&offset=` | `list[SpaceEntrySummaryOut]` | 同 `_space_actor` 版语义 |
| GET | `/spaces/{space_id}/entries/{entry_id}` | `SpaceEntryDetailOut` | 明文 standard 内容，不加密码校验 |
| GET | `/spaces/{space_id}/entries/{entry_id}/download` | `FileResponse` | 与现有下载同格式 |
| GET | `/spaces/{space_id}/blobs/{blob_id}/chunks/{chunk_index}` | 原始字节 | 与现有分块读取同格式 |

**硬约束**：任何 `tier != 'standard'` 一律 404（不泄露存在性）；所有写方法（POST/PUT/DELETE）在该路由组不存在。

### 开关与审计

- 环境变量 `STUDIOLO_SPACE_DEVICE_READS`（默认关闭）：关闭时所有端点返回 404（前端回退到登录 Core）
- 审计：写请求带 `space_id` 的读操作写 `space_access_audit_logs`（`action="device.read"`，`actor_kind` 复用现有字段或备注 `detail` 里带 `client_id`）；无法定位空间的拒绝（如 `/status`）走普通日志，**不要**试图写审计表

## 2. Sidecar 侧契约（Local API 代理）

文件 `backend/app/api/core.py` 追加一组端点（同文件或新文件 `core_space_reads.py` 均可，需在 `main.py` 注册）：

| Local 路径 | 转发到 Core |
|---|---|
| `GET /api/v1/core/space-reads/status` | `GET /api/v1/client/space-reads/status` |
| `GET /api/v1/core/space-reads/spaces` | 同名 |
| `GET /api/v1/core/space-reads/spaces/{id}` | 同名 |
| `GET /api/v1/core/space-reads/spaces/{id}/entries` | 同名（透传 query） |
| `GET /api/v1/core/space-reads/spaces/{id}/entries/{eid}` | 同名 |
| `GET /api/v1/core/space-reads/spaces/{id}/entries/{eid}/download` | 同名 |
| `GET /api/v1/core/space-reads/spaces/{id}/blobs/{bid}/chunks/{i}` | 同名 |

要求：

1. 鉴权：Local 用户 JWT（与 `core.py` 现有依赖一致）
2. 连接：从 `core_connection` 读取该用户的 Core 连接（origin + `nc_live_` 凭据），未连接 → 409 `{"detail": "Core not connected"}`
3. **传输门禁**：Core origin 必须是 `https://` 或回环 `http://127.0.0.1|localhost`，否则 400（现有 URL 校验允许远程 HTTP，这里必须另设门槛）
4. **路径固定**：只允许上表 7 条，用显式模板拼 URL，**禁止**把用户传入的任意 path 拼进去；`space_id/entry_id/blob_id` 必须过 UUID 正则校验
5. 转发：`Authorization: *** nc.live 凭据`，`follow_redirects=False`（3xx → 502），`Cache-Control: no-store`
6. 超时：JSON 请求 connect 5s / read 30s；download 与 chunk connect 5s / read 300s
7. 流式：download 与 chunk 用 `StreamingResponse`（`iter_bytes(64*1024)`），不整体读入内存
8. 错误映射：Core 401/403 → 401（并清本机缓存状态）；404 → 404；409 → 409；5xx/超时 → 502 `{"detail": "Core unavailable"}`
9. 日志脱敏：**禁止**把 `Authorization`、响应 body、文件名写进日志

## 3. 前端改动

- `src/services/spaceApi.ts`：只读 4 个函数（`fetchSpaces`、`fetchSpaceEntries`、`fetchSpaceEntryDetail`、下载/chunk）支持 `route.kind === 'device-read'`：origin 用本机 `getApiBaseUrl()`，token 用本机 JWT，路径前缀 `/api/v1/core/space-reads`
- `src/stores/space.ts:130-150`：新增路由态

```ts
type SpaceRouteConfig = { kind: 'user' | 'device-read'; token: string; origin: string }
```

  - 已有 Core 连接（`linkedCore`）且没有用户 JWT → `kind: 'device-read'`
  - 设备只读模式下 `available = true`、`coreSignInRequired = false`
  - 登出 / 断开 / 重绑时清空设备视图并丢弃在途响应（复用现有模式）
- `src/pages/SpacePage.vue`：`deviceReadOnly` 为真时
  - 隐藏：新建/编辑/上传、Token 管理、审计、冲突处理、副本相关入口
  - 顶部提示条：「设备只读 · 登录 Core 后可编辑」+ 登录按钮（复用现有 `FleetCoreSignIn`）
- 不做：设备模式下不打开/写入 `SpaceReplica`、不写 outbox、不合并草稿

## 4. 测试清单

后端新增 `backend/tests/test_client_space_reads.py`：

1. 无授权（关掉默认授权开关）→ `/status` = `no_grant`、`/spaces` = `[]`
2. 默认授权命中（本人 workspace + standard）→ 列表/详情/条目/下载均 200 且内容正确
3. `protected` / `e2ee` 空间 → 列表不出现、直接访问 404
4. 跨工作区 client 访问 → 404
5. grant 存在但 `revoked_at` 非空 → 404
6. `nc_live_` 直访 `/api/v1/spaces` 仍然 403（**回归锁定**）
7. 设备读路由组不存在任何写方法（POST/PUT/DELETE 返回 405/404）
8. 开关关闭 → 全部 404

后端新增 `backend/tests/test_core_space_proxy.py`：

1. 白名单：`/api/v1/core/space-reads/../../spaces` 之类越权路径被拒
2. 非 https 远程 Core → 400；回环 HTTP 允许
3. Core 401 → Local 401；Core 404 → 404；Core 超时 → 502
4. download 走流式（大响应不会整体驻留，可用 mock 断言 `StreamingResponse`）
5. 日志不含 Authorization / 文件名

前端新增 `tests/space-device-reads.test.mjs`：设备路由选择、前缀正确、设备模式不触发任何写接口。

门禁：`backend` 全量 `pytest`、`npm run build`、`npm run build:desktop`、`bash scripts/ci-local.sh --with-frontend`。

## 5. 明令禁止

- ❌ 不要修改 `_space_actor` 放行 `nc_live_`（保持 403）
- ❌ 不要动 e2ee 信封、Argon2id、AES-GCM 任何代码
- ❌ 不要给设备模式开放写、冲突处理、Token 管理、审计查询
- ❌ 不要在日志或错误信息里输出凭据、文件名、正文
- ❌ 不要提交（commit）—— 完成后报告改动文件与测试结果，由我审阅后统一提交
