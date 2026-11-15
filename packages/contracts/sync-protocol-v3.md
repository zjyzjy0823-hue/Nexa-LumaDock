# Sync Protocol v3 — 契约（normative）

**状态** v0.6.2 / 062-02 产出 · 冻结候选
**常量** `SYNC_PROTOCOL_VERSION = 3`（`backend/app/sync/protocol.py:1`）
**实现基线** `main @ 8d454e3`（v0.6.1）
**机器可读定义** [`schema/sync-v3.schema.json`](schema/sync-v3.schema.json)（normative）
**用例清单** [`cases.json`](cases.json) · 样例 [`samples/`](samples/)

> 本文所有形状均从实现代码提取，不是设计愿望。发现与本文件不符的实现，视为实现缺陷，而不是修改本文件。

---

## 0. 适用范围

契约覆盖三端（Windows/macOS 桌面 Local Backend、Android 客户端、Core）之间**唯一**的数据通道：

| 方向 | 通道 | 认证 |
| --- | --- | --- |
| 客户端 → Core | `POST /api/v1/sync/mutations` | Client 凭证 `nc_live_*` |
| 客户端 ← Core | `GET /api/v1/sync/changes` | Client 凭证 `nc_live_*` |
| 用户 → 本地 Backend | `/api/v1/sync/conflicts*` | 用户 JWT |
| 设备注册 | `POST /api/v1/clients/enroll` | 用户 JWT（Core 模式） |

**不在本契约内**：业务 REST API（`/api/v1/ledger/*` 等）、Automation API、Agent Action API。它们各自有独立文档，但**共享**本契约的数据语义（金额字符串、UTC 时间、软删除）。

---

## 1. 传输与通用规则

| 规则 | 内容 |
| --- | --- |
| 编码 | UTF-8 JSON，`Content-Type: application/json` |
| 命名 | **camelCase**（同步通道唯一命名风格；业务 REST 的 snake_case 不适用于此） |
| 时间 | ISO 8601 UTC，`YYYY-MM-DDTHH:MM:SS[.ffffff]Z`（`iso_utc()` 产出） |
| 金额 | **十进制字符串**，不是 JSON number。`"38.50"` ✅ / `38.5` ❌（`schemas.py:47-51` 强制） |
| ID | UUID v4 字符串（小写连字符格式）。非 UUID → `invalid_id` |
| 未知字段 | **一律拒绝**，不静默忽略（`extra="forbid"` / `invalid_fields`） |
| 认证失败 | `401`；凭证被吊销同样 `401`（无独立错误码） |

### 协议版本

每个请求/响应都带 `protocolVersion`。

- 客户端发送 `protocolVersion != 3` → `409` + `{"detail": "sync_protocol_mismatch"}`
- **不做版本协商、不做降级**。客户端必须先升级，或明确报错给用户。
- 未来任何不兼容变更必须递增到 v4 并同时保留 v3 端点 ≥1 个版本周期。

---

## 2. 实体类型（9 种，封闭集合）

| `entityType` | 模型 | 父实体 | 备注 |
| --- | --- | --- | --- |
| `ledger.category` | `LedgerCategory` | — | |
| `ledger.transaction` | `LedgerTransaction` | `ledger.category`（`categoryId`，可 null） | 金额字符串 |
| `website.category` | `WebsiteCategory` | — | |
| `website` | `Website` | `website.category`（`categoryId`） | URL 目前**不做**规范化/去重 |
| `data.collection` | `DataCollection` | — | |
| `data.record` | `DataRecord` | `data.collection`（`collectionId`，**创建后不可改**） | |
| `user.preferences` | `UserPreference` | — | 单例，UUID5 派生 id |
| `dashboard.layout` | `Dashboard` | — | 单例 |
| `automation.definition` | `AutomationWorkflow` | — | |

集合外任何值 → `rejected` + `unknown_entity_type`。新增实体类型属于**不兼容变更**（v4 或明确声明兼容），因为客户端会拒绝未知类型。

### 字段（按实体，来自 adapter 字段映射）

| 实体 | 字段（全 camelCase） |
| --- | --- |
| `ledger.category` | `name`(1..80), `type`(`income`\|`expense`), `icon`(≤30) |
| `ledger.transaction` | `categoryId`(uuid\|null), `type`(`income`\|`expense`), `amount`(string, >0, 最多 14 位/2 小数), `description`(1..200), `merchant`(≤120), `note`(≤500), `occurredAt`(UTC) |
| `website.category` | `name`(1..80), `order`(int) |
| `website` | `name`(1..120), `url`(≤2048, http/https), `icon`(≤500\|null), `description`, `categoryId`(uuid\|null), `favorite`(bool), `order`(int), `lastVisitedAt`(UTC\|null), `createdAt`, `updatedAt` |
| `data.collection` | `name`(1..120), `description`(≤500), `icon`(≤30), `tone`(≤30) |
| `data.record` | `collectionId`(uuid), `name`(1..160), `status`(≤40), `category`(≤80), `dataJson`(object) |
| `user.preferences` / `dashboard.layout` / `automation.definition` | 见 `schema/sync-v3.schema.json#/$defs/PersonalStateData`；自由文本会拒绝含凭据/本地路径的内容（`personal_state.py:21-29`） |

---

## 3. 写入：`POST /api/v1/sync/mutations`

### 3.1 请求

```json
{
  "protocolVersion": 3,
  "mutations": [
    {
      "mutationId": "3f9d0d5e-1c4a-4f6e-9a1b-2c3d4e5f6a7b",
      "entityType": "ledger.transaction",
      "entityId": "7c1e5b60-2f4d-4a3e-8b9c-1d2e3f4a5b6c",
      "operation": "upsert",
      "baseRevision": 0,
      "data": { "...": "实体字段" }
    }
  ]
}
```

| 约束 | 值 |
| --- | --- |
| `mutations` 长度 | **1..100**（`api/sync.py:42`） |
| `mutationId` | UUID，**客户端生成，永久不变**，是幂等键 |
| `operation` | `upsert` \| `delete` |
| `baseRevision` | 整数 `0..2^63-1`。`0` 表示"本端认为不存在" |
| 批次内 `data` | `delete` **必须省略**（出现即 `invalid_data`） |
| 批次内顺序 | 客户端按依赖排序；Core 顺序处理，不做重排 |

### 3.2 响应（永远 `200`，除非版本/认证失败）

```json
{"protocolVersion": 3, "results": [ /* 与请求 mutations 等长、同序 */ ]}
```

三种 `result`：

**applied**
```json
{"mutationId":"…","entityType":"ledger.transaction","entityId":"…","baseRevision":0,
 "status":"applied","revision":42}
```

**conflict**（乐观并发失败，Core 未写入）
```json
{"mutationId":"…","entityType":"website","entityId":"…","baseRevision":6,
 "status":"conflict","currentRevision":9,"current":{ "...": "Core 当前快照（已删除时为 null）" },"deleted":false}
```

**rejected**（请求本身不合法，Core 未写入）
```json
{"mutationId":"…","entityType":"unknown.entity","entityId":"…","baseRevision":0,
 "status":"rejected","reason":"unknown_entity_type"}
```

> ⚠️ `mutationId` 本身不是 UUID 时，early-return 的 result **只有** `mutationId` + `status` + `reason` 三个字段（`service.py:83-85`），不带 `entityType`/`entityId`/`baseRevision`。契约承认这一形状差异，校验器必须接受它。

### 3.3 拒绝原因（封闭集合，13 个）

| reason | 触发条件 |
| --- | --- |
| `invalid_id` | `mutationId` 或 `entityId` 不是 UUID |
| `invalid_fields` | mutation 对象出现白名单外字段 |
| `invalid_operation` | `operation` 不是 `upsert`/`delete` |
| `invalid_base_revision` | `baseRevision` 非整数 / 越界 |
| `invalid_data` | `data` 校验失败；或 `delete` 却带 `data` |
| `unknown_entity_type` | `entityType` 不在 9 种内 |
| `entity_id_unavailable` | 该 UUID 已属于**另一个工作区** |
| `category_not_found` | 引用的分类不存在/已删/跨工作区 |
| `category_type_mismatch` | 交易 `type` 与分类 `type` 不一致 |
| `category_has_transactions` | 分类下已有交易时改其 `type` |
| `collection_not_found` | 引用的集合不存在/已删/跨工作区 |
| `collection_id_immutable` | 已存在记录的 `collectionId` 被改动 |
| `delete_unsupported` | 该实体不允许删除（单例类个人状态） |

### 3.4 幂等语义（关键）

- 幂等键 = `(client_id, mutationId)`，服务端持久化 `result_json`（`models.SyncMutation`）。
- **重放返回与首次完全相同的结果**，包括 `applied` 的 `revision`。永不重复写入业务行。
- `invalid_id` 的请求**不留**幂等记录（因为无法建键）。
- 同批次中重复的 `mutationId`：第一条生效，后续返回同一结果（`conflict` 不会因重放变成 `applied`）。
- 幂等记录**当前无 TTL**。客户端不得假设过期，也不得复用 `mutationId` 表达不同修改。

---

## 4. 读取：`GET /api/v1/sync/changes`

### 4.1 请求参数

| 参数 | 类型 | 约束 | 默认 |
| --- | --- | --- | --- |
| `cursor` | int | ≥0 | `0` |
| `limit` | int | 1..100 | `100` |
| `protocolVersion` | int | 必须 = 3 | `1`（故意默认成不兼容值） |

### 4.2 响应

```json
{"protocolVersion":3,
 "changes":[{"revision":43,"entityType":"website","entityId":"…","operation":"upsert","data":{ "...": "…" }},
            {"revision":44,"entityType":"website","entityId":"…","operation":"delete","data":null}],
 "cursor":44,"hasMore":false,"workspaceRevision":44}
```

| 规则 | 内容 |
| --- | --- |
| `revision` | 工作区内单调递增，**从 1 开始**，无空洞 |
| `operation` | `upsert`（`data` 为完整快照）\| `delete`（`data` 为 `null`） |
| `hasMore` | 本次返回的是否还有下一页（Core 用 `limit+1` 探测） |
| `cursor` | 客户端下次请求应使用的值 = 本页最后一条 `revision`；空页时**回显请求值** |
| `workspaceRevision` | 工作区当前最大 revision，用于判断"已追平" |
| 分页 | 每页 ≤ `limit`；**客户端必须循环直到 `hasMore=false`** |
| 应用顺序 | 必须按 `revision` 升序逐条应用 |

### 4.3 错误

| 情况 | 状态码 | body |
| --- | --- | --- |
| `cursor > workspaceRevision` | `400` | `{"detail": "Invalid sync cursor"}` |
| `protocolVersion != 3` | `409` | `{"detail": "sync_protocol_mismatch"}` |

> ⚠️ **已知缺口（v0.6.1）**：`cursor` 失效没有独立的机器可读错误码，只有一个英文人话 `detail`；也**没有** resync 端点。客户端只能把它当作 `invalid_response` → 进 blocked 状态（`engine.py` 的现状）。修复属 090-01，届时本契约递增为 `400 {"detail":"sync_cursor_expired","resyncRequired":true}`。在此之前：**客户端不得自行把 cursor 重置为 0**，否则将重复应用全部历史并破坏 outbox 幂等假设。

---

## 5. 冲突

### 5.1 检测

Core 在 `apply` 前比较 `baseRevision` 与当前 `sync_revision`：

| 场景 | 结果 |
| --- | --- |
| 记录不存在 + `baseRevision == 0` + `upsert` | 应用 |
| 记录不存在 + (`baseRevision != 0` 或 `delete`) | `conflict`（`currentRevision: 0`） |
| 记录存在 + `baseRevision == 当前 revision` | 应用 |
| 记录存在 + `baseRevision != 当前 revision` | `conflict` |
| 记录存在 + `baseRevision == 0` + 单例实体（个人状态） | `conflict`（`accepts_initial_upsert` 例外） |

`conflict` 时 Core **不写入任何业务数据**，客户端负责把它持久化为冲突记录（Local 侧表 `LocalMutation.status = conflict`）。

### 5.2 解析（仅本地 Backend，用户 JWT）

`POST /api/v1/sync/conflicts/{id}/resolve`

```json
{"strategy": "local", "expectedRemoteRevision": 9}
```

| 字段 | 约束 |
| --- | --- |
| `strategy` | `local`（保留本机）\| `remote`（使用 Core） |
| `expectedRemoteRevision` | 可选，整数 ≥0；不匹配 → `409 conflict_snapshot_changed` |

响应：解析 receipt（本地队列推进后的状态）。错误：`422 invalid_resolution_strategy`、`409 sync_in_progress`、`409 conflict_snapshot_changed`、`409 <依赖原因>`（如 `category_not_found`）。

---

## 6. 设备注册（Android 接入用）

`POST /api/v1/clients/enroll`（Core 模式，用户 JWT）

```json
{"installationId":"9b2c…","name":"Pixel 9","platform":"android","appVersion":"0.7.0"}
```

响应 `201`：

```json
{"client":{"id":"…","installationId":"…","workspaceId":"…","name":"Pixel 9","platform":"android","appVersion":"0.7.0"},
 "credential":"nc_live_…","tokenLast4":"a1b2","tokenCreatedAt":"2026-11-15T08:00:00Z"}
```

| 规则 | 内容 |
| --- | --- |
| `credential` | **只返回一次**，响应带 `Cache-Control: no-store` |
| 重复注册（已发凭证） | `409 {"detail": "Client is already enrolled"}` |
| 已吊销 | `409 {"detail": "Client is revoked"}` |
| 轮换 | `POST /api/v1/clients/{id}/credential`，旧凭证**立即失效**（重叠期 = 0） |
| 吊销 | `POST /api/v1/clients/{id}/revoke` |

> ⚠️ **未决（062-05 必须定）**：Client 与 Device（`nd_live_`）是两套互不关联的身份。Android 若要同时进同步链路和设备台账，当前需要注册两次。契约暂按"同步只用 Client 凭证"冻结；若决定合并，属不兼容变更。

---

## 7. 删除语义

| 规则 | 内容 |
| --- | --- |
| 表示 | **软删除**：`deleted_at` 非空；变更记录 `operation=delete`、`data=null` |
| 客户端处理 | 必须把本地行标记删除（或物理移除并保留墓碑，以便识别迟到变更） |
| 复活 | 对已删除实体的 `upsert` 会清空 `deleted_at`（复活） |
| 重复删除 | 允许，消耗新 `revision` |
| 级联 | 三类不一致：Website 分类清空子引用；Collection 墓碑化子记录但保留 `collection_id`；Ledger 分类**不清空**子交易的 `categoryId` |
| 墓碑 TTL | **无**。删除标记永久保留 |

> ⚠️ 删除标记保留期与幂等窗口需要联合设计（090-01）。当前实现是"永久保留"，客户端可安全假设删除变更永远不会因过期而丢失。

---

## 8. 一致性模型（客户端必须实现的保证）

1. **每条变更一个事务**：业务行 + outbox 写入必须同事务提交；崩溃后可从 outbox 恢复。
2. **单流串行**：同一工作区同时只允许一个推送任务；推送与拉取不得并发修改 cursor。
3. **先持久化再发送**：outbox 行先置 `in_flight` 并提交，再发 HTTP；避免"已发送但未知"。
4. **拉取按页事务**：一页的变更应用 + cursor 推进必须在同一事务；中断后从最后提交的 cursor 重放。
5. **乐观反馈**：本地写入先行展示，远端确认后更新同步状态，二者状态**分开**呈现给用户。

---

## 9. 兼容性矩阵

| 客户端 | Core v0.6.1（protocol 3） | 未来 Core v4 |
| --- | --- | --- |
| protocol 3 | ✅ | ❌ `409 sync_protocol_mismatch` |
| protocol 2 | ❌ `409` | ❌ |

客户端必须在收到 `409 sync_protocol_mismatch` 时：停止自动重试 → 提示用户升级 → **保留** outbox。

---

## 10. 校验

```bash
python3 scripts/check-contracts.py     # 规范 + 样例 + 语义规则
node    scripts/check-contracts.mjs    # 同一份 cases.json 的独立实现
cargo test -p nexa-contracts           # Rust 侧 serde 结构严格性
bash scripts/ci-local.sh --contracts-only   # 三件套一次跑完
```

三者读取同一份 `cases.json`，任何一方失败即视为契约被破坏。当前期望输出：

```
CONTRACTS OK cases=32 valid=10 schema-invalid=13 semantic=9
```

### 校验分三层（重要）

| 层 | 负责什么 | 归属 |
| --- | --- | --- |
| 信封（schema） | 外形、键白名单、标量格式、枚举成员 | `schema/sync-v3.schema.json` |
| 跨字段不变量 | `cursor`/`workspaceRevision`/`revision` 关系（SR-5/6/7） | 各语言校验器 |
| 实体载荷 | `data` 按 `entityType` 校验（SR-2） | 服务层 + 各语言实体结构 |

`Mutation.data` / `Change.data` 在 schema 里是**不透明对象**（`{"type":"object"}`），因此"amount 是 JSON number""occurredAt 缺 Z"这类问题**不会**在信封层被拒，而在 SR-2 层被拒（对应样例放在 `samples/semantic/`）。这是刻意的分层，不是遗漏：信封要能被任何客户端的传输层复用，实体语义由领域层把关。

**修订规则**：修改本文件必须同步更新 `schema/`、`samples/`、`cases.json`，并让三种校验器全部通过；否则 CI 拒绝合并。
