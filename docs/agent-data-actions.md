# Nexa v0.5.5 Agent Data Actions

OpenClaw 的模型将自然语言转换成结构化 tool 参数。Nexa Backend 不解析提示词、不调用 LLM。所有业务工具的调用路径为：

```text
OpenClaw typed tool
  -> /api/agent/actions/execute (Nexa Local)
  -> na_live_ 身份 / 当前 scopes / 严格 Action Registry
  -> 共享 Business Service
  -> 同一 SQLite transaction: business row + outbox + successful receipt
  -> 用户手动 sync -> Nexa Core PostgreSQL -> 其他 Local Replica
```

插件不能访问 SQLite、SQLAlchemy、Core Sync API 或普通用户 REST/JWT。权限不足时直接报告错误，不寻找其他凭证或绕过权限。

## 身份、边界与授权

沿用 `na_live_` bearer token；`Agent.id/user_id/workspace_id` 从 token 对应的数据库行推导。每次调用重新读取 Agent 的 enabled、token hash 和当前 scopes。禁用返回 `403 agent_disabled`，撤销或轮换后的旧 token 返回 `401 unauthorized`。用户 JWT、`sk_live_`、`nc_live_` 和 `nd_live_` 不能认证此 API。

执行及 catalog 都依赖 `require_local_mode`；Core 返回 `404 local_only`，包括未认证请求。Core 普通 CRUD、Runtime 和 Sync 保持原有边界。所有数据查询同时绑定用户与工作区；DataRecord 通过 DataCollection 解析归属，不增加重复 ownership 字段。

Agent 管理接口 `/api/v1/agents` 增加 `dataScopes`。AgentsPage 的创建/编辑区域提供九个复选框：

| 业务域 | 读取 | 新增/修改 | 单独授权删除 |
| --- | --- | --- | --- |
| Ledger | `ledger:read` | `ledger:write` | `ledger:delete` |
| Websites | `websites:read` | `websites:write` | `websites:delete` |
| Data | `data:read` | `data:write` | `data:delete` |

没有通配符或隐式包含关系；write 不包括 read/delete。已有及新建 Agent 默认 `[]`，显示“无数据权限”。修改 scopes 立即生效，不需重新生成 token。删除权限在 UI 用单独的破坏性权限标识。

## API contract 与幂等

```json
{
  "actionId": "05505505-5055-4055-8055-055055055055",
  "action": "ledger.transaction.create",
  "arguments": {
    "type": "expense",
    "amount": "38.00",
    "description": "咖啡",
    "occurredAt": "2026-09-30T09:00:00+08:00",
    "categoryId": null
  }
}
```

所有 write/delete 必须携带 UUID `actionId`；read 不强制携带。每个 Action 使用复用业务输入模型的严格 schema，拒绝未声明参数和 envelope 中的 ownership/taskId。公开 tool 参数使用 camelCase；业务模型原有 snake_case 输入也兼容。正金额、分类类型匹配、非空描述、datetime、HTTP/HTTPS URL、依赖及 tombstone 校验由共享服务负责。

成功写入首次与 replay 都返回安全 receipt：

```json
{
  "actionId": "05505505-5055-4055-8055-055055055055",
  "action": "ledger.transaction.create",
  "status": "ok",
  "replayed": false,
  "data": {"entityId": "entity-uuid", "entityType": "ledger.transaction"}
}
```

用 read tool 查询详细数据。receipt 只存身份，不保存完整业务响应；实体后来被更新/删除后，replay 仍返回原 receipt。read 的 `data` 为当前授权查询结果，`replayed=false`。

解析后的 action + arguments 以排序 key 的 canonical JSON 计算 SHA-256；JSON 字段顺序变化不产生冲突。数据库唯一约束 `(agent_id, action_id)` 和事务内的 Agent 行写锁防止并发重复执行。

- 同一 actionId + 相同 canonical 请求：不再写业务数据、不产生新 outbox/Event/success log，`replayed=true`。
- 同一 actionId + 不同请求：`409 idempotency_conflict`。
- 当前权限、enabled 和凭证仍先检查；撤销权限后不能通过 replay 取得 receipt。
- 有效但被拒绝/业务失败的尝试可记录 denied/failed log，不保留 actionId，不永久占用成功 receipt 身份。
- Plugin 在一次 logical invocation 起始生成 UUID；网络/5xx 重试复用完整 body。相同 SDK toolCallId 的进程内重入复用 UUID。独立 invocation 使用新 UUID，不按文本长期去重。

## Audit、任务与原子性

`0015_agent_data_actions` 的 down revision 为 `0014_multi_entity_sync`；0001–0014 未修改。给 agents 增加非空 JSON `data_scopes`（数据库默认 `[]`），并创建 `agent_action_logs`：

```text
id, agent_id, workspace_id, task_id nullable, action_id nullable
action_type, required_scope, target_entity_type/id nullable
request_hash, status, error_code nullable, result_summary nullable
created_at, completed_at nullable
UNIQUE(agent_id, action_id)
indexes: agent_id, workspace_id
```

成功 write 的 business mutation、LocalMutation 和 success log 一次 commit。异常 rollback 不留下业务数据/outbox/success receipt。业务校验或权限错误的安全 audit 在 rollback 后单独提交；无法提交的数据库/未知异常返回安全错误，不宣称 audit 成功。

Audit 不保存金额、description/note、dataJson、原始请求、Authorization、token、路径或 traceback。result_summary 仅为 `entityId/entityType`。AgentEvent 仅记录 action name、安全实体身份及成功状态。read 不生成 AgentEvent。task_id 自动读取 `Agent.current_task_id`，任务结束后为 null。

`GET /api/agent/actions/catalog` 返回 connected、agentId/name、dataScopes、Nexa version 和当前有权调用的动作名称。模型可见工具始终由静态 schema 定义，catalog 不动态扩大授权。

稳定错误位于响应 `detail.code`：`unauthorized`、`agent_disabled`、`permission_denied`、`unsupported_action`、`validation_error`、`not_found`、`conflict`、`idempotency_conflict`、`local_only`。客户端只展示自己的安全错误文案，不展示服务端异常正文。

## Action / Tool catalog

每个 action 对应静态工具名 `nexa_` + 将下表动作名中的点替换为下划线。例如 `ledger.transaction.create` -> `nexa_ledger_transaction_create`。

| 域 | read | write | delete |
| --- | --- | --- | --- |
| Ledger | `ledger.categories.list`, `ledger.transactions.list`, `ledger.summary.get` | `ledger.category.create/update`, `ledger.transaction.create/update` | `ledger.category.delete`, `ledger.transaction.delete` |
| Websites | `website.categories.list`, `website.list`, `website.get` | `website.category.create/update`, `website.create/update`, `website.visit` | `website.category.delete`, `website.delete` |
| Data | `data.collections.list`, `data.collection.get`, `data.records.list`, `data.record.get` | `data.collection.create/update`, `data.record.create/update` | `data.collection.delete`, `data.record.delete` |

共 29 个业务 Action/typed tools，加 `nexa_status`。读取/更新/删除单个实体用 `id`；创建 Record 和列出 Records 用 `collectionId`。Ledger list/summary 支持 `month`；Website list 支持 `categoryId/search/favorite/sort`。

静态 JSON Schema 由 `scripts/export-agent-tools.py` 从 Registry 导出到 plugin/src/catalog.json，包含共享字段约束、required/nullable、Decimal 与日期 schema。`--check` 防止 schema 漂移；插件通过 TypeBox `Type.Unsafe<Record<string, unknown>>` 保留完整导出的 JSON Schema，SDK 的 tool 元数据不是任意 action/args 通用工具。

## OpenClaw plugin 安装与配置

实现位于 `agent-adapters/openclaw/plugin`：`src/index.ts` 使用官方 `defineToolPlugin`，`client.ts` 负责凭证与安全重试，`catalog.json` 保存静态 schema；官方 CLI 生成 `openclaw.plugin.json`。插件独立 semver 为 `0.1.0`，原 Runtime Adapter 的 `runtimeVersion=0.1.0` 保持不变；Nexa 产品为 `0.5.5`。

本机原先没有 PATH 中的 OpenClaw CLI。开发依赖锁定 npm 发布的 OpenClaw `2026.9.6 (eb377ac)`，已核对其实际 SDK `.d.ts`、`plugins --help`、build 和 validate。该版本要求 Node `>=24.16.0 <25 || >=26.1.0`。未来更换 SDK 版本须重新 build/validate/tests，不假设兼容。

```powershell
cd agent-adapters/openclaw/plugin
npm install
npm run build
npm run plugin:build
npm run validate
npm test
# 修改工具/元数据后，使用当前官方 CLI 重新生成并检查：
npx openclaw plugins build --root . --entry dist/index.js
npm run plugin:build
```

在安装了同版本 OpenClaw 的 Gateway 主机上：

```powershell
openclaw plugins install --link D:\xiangmu\LumaDock\agent-adapters\openclaw\plugin
openclaw plugins enable nexa-tools
openclaw plugins doctor
openclaw plugins inspect nexa-tools --runtime --json
```

按当前 CLI 的 capability/trust 提示完成本地开发安装。插件开发命令不修改用户整份 Gateway 配置；本任务没有替用户 install/link/enable 到正在使用的 Gateway。

推荐复用明确指定的现有 runtime adapter 配置：

```json
{
  "plugins": {
    "entries": {
      "nexa-tools": {
        "enabled": true,
        "config": {
          "adapterConfigPath": "D:\\xiangmu\\LumaDock\\agent-adapters\\openclaw\\config.json"
        }
      }
    }
  }
}
```

该文件原有 `serverUrl/agentToken` 供 Runtime Adapter 和 Tool Plugin 共享。它必须指向 Nexa **Local** 并使用该 Local 创建的 Agent token。原来连接 Core Runtime 的 Agent 凭证不能直接用于 Local Data Actions；Runtime 仍可按原设计独立连接 Core。

另一种配置只保存环境变量名称，实际 secret 由 Gateway 进程环境提供：

```json
{
  "serverUrl": "http://127.0.0.1:17800",
  "agentTokenEnv": "NEXA_AGENT_TOKEN"
}
```

不指定 serverUrl 时可从 `NEXA_LOCAL_URL` 或明确的 adapterConfigPath 读取。环境中的 token 优先于共享配置。不要把真实 token 写入这些文档示例、prompt、CLI 参数或日志，也不要提交 config.json。Gateway 以何种方式接收环境变量取决于其启动方式；不要把 secret 放入模型工具参数。

在 OpenClaw 中调用 `nexa_status` 检查 connected、Agent 名称/id、scopes、产品版本；然后 `nexa_ledger_categories_list` 等读取工具确认授权。创建账单前先读取分类并选择 type 匹配的 categoryId；无分类可 null。新增 Record 前先读取集合。

## Local-first / Sync 与限制

Core 停机时 write 仍成功并排队；不强制联网，不自动调用 `/sync/run`，不增加 background sync。Sync Protocol 保持 v2，bootstrap generation 保持 2，不新增同步实体，Agent scopes/audit 本身不参与同步。

Website Category 删除沿用 active Website 引用清空 + 子 mutation + category tombstone；Data Collection 删除沿用 record tombstones/delete mutations + collection tombstone。Agent 修改发生跨端冲突仍使用现有 Sync Engine，保留本地编辑与冲突快照，不添加 last-write-wins 或自动解决。

本版本不开放 Settings、Device、Agent/Automation 管理、API Key、Core/Client 配置、安全或凭证工具。没有 Prompt Parser、自动 AI 分类、Automation Runtime、Sync UI、Action History 页面或 Conflict Resolution UI。

Agent token 是 bearer secret；只连接受信任的 Nexa Local。非 loopback HTTP 会被插件拒绝，远程连接必须 HTTPS；禁止 URL 内嵌账号、query token 或重定向。按最小权限授权，delete 单独启用。超过进程内 4096 个缓存 toolCallId 后最老身份会淘汰；进程重启后也不会保留 invocation cache。内部 HTTP 重试完整保留 actionId；最终网络失败后，不应把自动新建的独立调用当作原 invocation 的安全重放。
