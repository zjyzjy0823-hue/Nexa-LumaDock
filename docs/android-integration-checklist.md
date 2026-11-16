# Android 接入清单（v0.6.2 · 2026-11-16）

面向 Android 客户端开发者的落地清单。规范正文见 [Sync Protocol v3](../packages/contracts/sync-protocol-v3.md)，机器可读样例见 `packages/contracts/samples/**`（`cases=35`）。本文只列「接入前必须知道、否则会踩」的点，全部经 2026-11-15/16 实测。

---

## 1. 两套命名，别混

| 通道 | 命名 | 例子 |
| --- | --- | --- |
| 同步通道（`/api/v1/sync/*`） | **camelCase** | `entityType`、`baseRevision`、`mutationId` |
| 业务 REST（`/api/v1/ledger/*` 等） | **snake_case** | `category_id`、`occurred_at` |

✅ **业务 REST 现在会拒绝未知字段**（v0.6.2 起 `extra="forbid"`）：拼错字段名直接 `422`，不会再静默丢数据。Android 端必须按 snake_case 构造业务请求；同步通道则相反。

容易写错的几个真实字段：

| 想传的 | 正确字段 | 错误写法（会 422） |
| --- | --- | --- |
| 交易分类 | `category_id` | `categoryId` |
| 记录内容 | `data_json` | `data` / `dataJson` |
| 发生时间 | `occurred_at` | `occurredAt` |

> 记录内容在同步通道叫 `dataJson`、在业务 REST 叫 `data_json` —— 两套命名各自成立，别混用。

## 2. 时间格式

| 场景 | 规则 |
| --- | --- |
| 同步载荷 `occurredAt` | **必须带偏移**（`Z` 或 `+08:00`）；不带偏移会被契约拒绝（SR-2） |
| 业务 REST `occurred_at` | 带偏移按该偏移；**不带偏移按 `APP_TIMEZONE` 墙钟时间解释**（v0.6.2 起，原先误当 UTC） |
| 月度归属 | 一律按 `APP_TIMEZONE` 换算后取 `YYYY-MM` |

⚠️ `settings.timezone`（用户偏好）目前**只存不用**：改了不影响月度归属。Android 端展示时不要据此自己算月份。

## 3. 金额

- 十进制**字符串**：`"38.50"`，不是 JSON number。
- 约束：`> 0`、最多 14 位整数、最多 2 位小数（`1.234` → 422）。

## 4. 身份与凭据

| 主体 | 前缀 | 用途 |
| --- | --- | --- |
| 用户 JWT | — | 业务 REST、冲突解决、设置 |
| Client 凭据 | `nc_live_` | 同步通道（mutations/changes/snapshot/resync） |
| Device Token | `nd_live_` | `POST /api/device/heartbeat` |
| Agent Token | `na_live_` | `/api/agent/actions/*` |

- Client 凭据在 Core 侧注册获取；Android 作为一台「设备」时还需要 Device Token 上报心跳。
- API Key（`sk_live_`）只用于 **legacy `/api/*`** 四个只读接口；`/api/v1/*` 不认 API Key（401）。
- 撤销：Core 侧 `POST /api/v1/clients/{id}/revoke`；本地 `DELETE /api/v1/core/connection` 只清本地连接。

## 5. 同步主流程

```
启动 → 读本地 cursor → GET /api/v1/sync/changes?cursor=N&protocolVersion=3
     → 应用变更，cursor = 响应 cursor（hasMore 时继续翻）
     → POST /api/v1/sync/mutations（clientMutationId 由客户端生成，永久不变）
     → 处理 results[]：applied / conflict / rejected
```

必须记住四条：

1. **幂等键 = `(client_id, mutationId)`**，服务端持久化结果，**无 TTL**。重试沿用同一个 `mutationId`，不要重新生成。
2. **`baseRevision`** 来自本地实体的 `syncRevision`（快照里也给）。`0` 表示"本端认为不存在"。版本落后 → 冲突，不是覆盖。
3. **cursor 失效**（裁剪/重置）：`400 + {"resyncRequired": true, "workspaceRevision": R}` → 走 `GET /api/v1/sync/snapshot` 全量分页 → `POST /api/v1/sync/resync` 应用。
4. **删除是墓碑**（`deleted: true`, `data: null`）；快照里"缺失"**不等于**删除，只有显式墓碑才是删除。

## 6. 快照与恢复

| 端点 | 说明 |
| --- | --- |
| `GET /api/v1/sync/snapshot?protocolVersion=3&limit=200` | 返回 `snapshotId`、`workspaceRevision`、`entities[]`、`cursor`、`hasMore`；`limit` 1..500 |
| 翻页 | 带 `snapshotId` + `cursor`；`workspaceRevision` 全程恒定，跨页一致 |
| `POST /api/v1/sync/resync` | Local 侧执行：应用整份快照 + 同事务写 `cursor = R`；本地 pending 一律转 conflict，不静默丢 |
| 过期 | 快照会话过期 → `409 snapshot_expired`，重新从头拉 |

## 7. 错误码速查

| 场景 | 响应 |
| --- | --- |
| `protocolVersion != 3` | `409 {"detail":"sync_protocol_mismatch"}` |
| cursor 失效 | `400` + `resyncRequired: true` + `workspaceRevision` |
| 实体校验失败 | `results[].status = "rejected"` + 13 个封闭 `reason` 之一 |
| 冲突 | `results[].status = "conflict"`，带远端快照；解决走 `POST /api/v1/sync/conflicts/{id}/resolve` |
| 同步正在进行 | `409 sync_in_progress`（服务端持 workspace 锁，10s 上限等待） |
| 被拒绝的写入 | `POST /api/v1/sync/rejected/{id}/dismiss`（放弃 + 依赖项 skipped）或 `/retry`（按当前数据重建，新 `mutationId`） |

## 8. 状态与诊断

`GET /api/v1/sync/status` 返回 `blocked / cursor / lastError / pending / conflicts / rejected / queueSeeded / lastAttemptAt / lastSuccessAt / nextRetryAt`。

- **没有 `status` 字段**：需要判断"该 resync"就看 `lastError === "resync_required"`。
- `POST /api/v1/sync/run` 的响应里才有 `status`（`ok` / `resync_required` / …）。

## 9. 尚未提供（别按已存在设计）

| 能力 | 现状 |
| --- | --- |
| `rejected` 的 dismiss/retry | ✅ 已提供：`GET /api/v1/sync/rejected`、`POST .../{id}/dismiss`、`POST .../{id}/retry`（Local + 用户 JWT） |
| resync 的前端/客户端按钮 | 后端已可用，客户端需自己接 |
| 多 Workspace 切换 | 无 API，只有个人 workspace |
| 通知投递（Email/Telegram/Webhook） | 无实现，仅设置项 |
| 2FA | 无实现 |
| 存储用量接口 | 无 |

## 10. 实测覆盖（截至 2026-11-16）

- 9 种实体全量同步、墓碑、分页（`limit=1` 13 页一致）、冲突双方解决、resync 恢复：已实测通过。
- 500 实体：快照 546 条 / 3 页 / 0.31s；resync 1.08s（目标 < 5s）。
- 租户隔离：REST / API Key / Agent Token 三条路径跨账号访问均为 404。
- 5 万条记录：集合摘要 238B / 174ms；记录分页 12KB / 324ms（第 50 页 338ms）；概览 289ms；旧全量接口对照 166MB / 5.1s。

## 11. 数据读取（有界，Android 必须用这套）

集合列表默认会把每个集合的全部记录内嵌返回，5 万条时是 166MB —— 移动端必须显式要走有界读取。

| 用途 | 请求 | 返回 |
| --- | --- | --- |
| 集合摘要 | `GET /api/v1/data/collections?include_records=false&q=` | 元数据 + `recordCount`，**无 `records`** |
| 记录分页 | `GET /api/v1/data/collections/{id}/records?page=true&limit=50&cursor=&q=&include_data_json=false` | `{items,total,matchedCount,nextCursor,hasMore}` |
| 概览 | `GET /api/v1/data/overview?recent_limit=4` | 总数 / 完成数 / 最近记录（含 `collectionName`） |
| 单条详情 | `GET /api/v1/data/records/{id}` | 完整记录（含 `dataJson`） |

规则：

- `nextCursor` 必须原样回传；它用服务端密钥签名并绑定用户、工作区、集合、`q` 与排序，跨集合或改关键词后使用会 **422**。
- 排序固定 `updatedAt DESC, id DESC`，同毫秒也不会重漏。
- `page=false`（默认）仍是旧的裸数组契约；此时若显式传 `limit/cursor/q/include_data_json` 会 **422**，不会静默忽略。
- `include_data_json=false` 时列表不含 `dataJson`，编辑前用单条详情接口取完整内容。
- 摘要里的 `recordCount` 由 SQL 聚合得出，可直接用于角标，不需要再拉记录。

