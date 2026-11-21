# Studiolo v0.6.2 架构审计与目标设计

审计基线为 `main @ 3537e1f`，日期为 2026-11-16。本文记录静态代码审计和上游协议核对结果。接口、数据结构和实施方式均为设计建议，待定事项以 TBD 编号标识。版本分期与独立验收见[开发路线图](Studiolo_Development_Roadmap_v0.6.2-v1.0.md)。

## Current Architecture Audit · 现状与复用边界

| 模块 | 当前实现与证据 | 复用与改动范围 |
| --- | --- | --- |
| Core | FastAPI 与 Local 共用应用、SQLAlchemy 模型和 Alembic 链，Core 要求 PostgreSQL。启动执行迁移，且只有 Core 启动 Automation Engine。现有通用 `/ws` 仅处理 ping/pong，连接入口没有业务认证。[应用入口](../backend/app/main.py) · [运行配置](../backend/app/config.py) | 沿用工作区归属、路由模式和数据库。Shared Space 使用独立路由、数据表和权限。Agent 如需经 Core 中转，提供独立有鉴权的传输入口。 |
| Desktop Local | Tauri 管理 Python sidecar 启停，FastAPI 绑定回环地址，SQLite 数据在应用目录。Local 生命周期驱动后台同步。Vue 通过现有 HTTP API 使用业务功能。[桌面入口](../backend/desktop_entry.py) · [Tauri 启动](../src-tauri/src/lib.rs) · [前端 API](../src/api/client.ts) | 保留启动、数据库与现有业务接口。新增窄的密文仓储、解密命令或服务边界，按能力接入现有壳。 |
| Android | `3537e1f` 增加 Android 配置、构建入口及平台门控，移动分支跳过桌面 sidecar。提交记录报告真机可安装，当前追踪源码只有壳、三项通用命令及同步契约样例。仓库 CI 仍缺 Android 构建与真机业务验证。[运行入口](../src-tauri/src/lib.rs) · [Android 配置](../src-tauri/tauri.android.conf.json) · [CI](../.github/workflows/ci.yml) | 沿用 Vue 和 Rust 契约样例；按「核心能力先行」顺序先以移动浏览器/薄壳接入 Mac Core `/chat` 与 `/space`，随后在 v0.8.0–v0.8.1 补齐 Rust Commands、Repository、SQLite、Keystore、Outbox 与移动完整离线同步。 |
| Sync | v3 注册 Ledger、Websites、Data、个人设置、Dashboard 与 Automation 定义等实体。包含修订、Outbox、幂等回执、分页拉取、快照重同步、Conflict Center 和 rejected 重试／忽略。未知实体在旧契约下不兼容；业务变更发布也可触发 Automation 事件。[契约](../packages/contracts/sync-protocol-v3.md) · [注册表](../backend/app/sync/adapters/registry.py) · [发布与租户锁](../backend/app/sync/service.py) · [同步路由](../backend/app/api/sync.py) | 复用绑定、事务、分页、退避与恢复模式。Shared Space 独立能力、游标和密文变更流，避免把条目放进 v3 adapter、快照、业务事件或原有冲突详情。 |
| Client Identity | 账号 JWT 管理 Personal Workspace 与 Client；`nc_live_` 用于同步和部分 Client Runtime；`nd_live_` 是设备遥测，`na_live_` 为 Agent，另有传统只读 API Key。Client 支持 enroll、rotate、revoke，安装实例在工作区内唯一。桌面 `FileCredentialStore` 以文件权限保护 ASCII 凭据，文件落盘仍为明文。Desktop Core URL 校验目前接受非回环 HTTP，不能作为新受保护接口的传输策略。Android 已有 Keystore 方案文档，尚需代码与真机验证。[认证](../backend/app/security.py) · [Clients](../backend/app/api/clients.py) · [凭据存储](../backend/app/credential_store.py) · [Core 地址验证](../backend/app/core_connection.py) · [Android 决策](android-auth.md) | 身份负责绑定、作用域和吊销；内容读取还需密码。复用凭据存储接口与原子写入思路。新增凭据进入平台安全存储，旧桌面凭据按 §迁移方案升级。 |
| Automation Engine | Core 既有扫描和执行循环，支持 schedule、manual、data_changed、agent_completed。Local 可上报完成事件，正常业务同步与事件同步各有路径。任务定义可通过 v3 同步，执行历史、计划状态、动作回执留在 Core。触发唯一键、行锁、租约、尝试 fencing、内部动作回执和 ancestry guard 已存在。[引擎](../backend/app/automation/engine.py) · [动作](../backend/app/automation/actions.py) · [API](../backend/app/api/automation/routes.py) · [个人状态 adapter](../backend/app/sync/adapters/personal_state.py) | 沿用唯一 Studiolo 调度器、执行表与历史接口。统一管理层聚合远程 Cron；Studiolo 的 `agent.run` 是一次性的旧任务派发。通用 API、webhook 和 Agent 入口需要验证均无法代读 Shared Space。 |
| Agent Runtime 与 Data Actions | 已有 Agent 登记、心跳、任务 claim、event、complete/fail。OpenClaw Python adapter 轮询任务并调用 CLI。OpenClaw Tool Plugin 通过 `na_live_` 入站调用 Studiolo Local Data Actions，按 scope 执行 Ledger、Website、Collection/Record 操作，业务更新、Outbox 与成功回执同事务。Agent 任务描述和结果现有落库路径不可用作聊天通道。[Agent 路由](../backend/app/api/agents/routes.py) · [OpenClaw adapter](../agent-adapters/openclaw/README.md) · [Data Actions](../backend/app/actions/service.py) · [Action API](../backend/app/api/agent_actions.py) | 保留既有入站集成与白名单。新增出站 Chat 与 Cron 接口；独立管理连接能力和认证，旧的任务心跳只代表旧 Runtime。 |
| 数据模型与迁移 | 现有表包括 User/Workspace/Client、Device/Agent/Task/Event/ActionLog、Ledger、Websites、Collection/Record、Dashboard/Preference、Automation 和同步状态。Alembic head 为 `0019_local_automation_events`，继 `0017_automation_engine`、`0018_data_record_tenancy`；后者已给 Record 补齐租户。Data 已有集合摘要、概览、记录详情及分页。当前 HEAD 无 v0.6.2 tag，API `APP_VERSION` 仍为 0.6.1。[模型](../backend/app/models.py) · [迁移](../backend/migrations/versions/) · [Data 路由](../backend/app/api/data/routes.py) · [v0.6.2 状态](v0.6.2-status-2026-11-16.md) | 现有 schema 与接口保持兼容。同一 Alembic 链追加迁移，显式验证 SQLite/PostgreSQL 和打包 sidecar。Android 维护自己的本地 schema 版本。 |
| Vue 组件和外观 | Vue/Pinia 共用 `src/`。全局 CSS 已有玻璃、色彩、阴影变量；`GlassCard`、弹窗与布局组件仍直接消费材质或硬编码样式。Appearance 设置可保存与同步，当前全局切换未接线。v3 的外观字段严格限制枚举与字段名。[App](../src/App.vue) · [全局 CSS](../src/styles/main.css) · [GlassCard](../src/components/ui/GlassCard.vue) · [外观设置](../src/components/settings/AppearanceSettings.vue) · [外观契约](../backend/app/sync/adapters/personal_state.py) | 原地增加语义 tokens、注册表和材质适配。现有浅／深／系统偏好可映射到显示模式；新 theme ID 先存在设备侧，跨端选择另行设计。 |

旧版 [062-01 审计](architecture-audit-v0.6.2.md)记录 v0.6.1 基线。其中 Android 编译阻断、缺少快照与 rejected 出路、Record 无租户列等判断以本次代码证据更新。此次未启动应用或数据库，亦未重跑真机与生产上游联调，既有验证记录和新版本验收须分别取证。

## Target Architecture Proposal · 目标边界

| 平面 | 客户端 | Core／上游 |
| --- | --- | --- |
| 原有业务 | 桌面保留 Vue/Tauri + Local FastAPI/SQLite，Android 接入受限 Rust Commands/SQLite | Core 继续通过 Sync v3 做工作区内业务变更和恢复 |
| Shared Space | 本地密文仓储、按次密码读取与加解密；已落地密文可离线查看 | Core 按工作区保管和同步密文、有限元数据与加密密钥封套，管理配额、设备授权和游标 |
| Agent Chat | 同一 Fleet Chat UI、状态与审批卡按能力工作；传输与显示值只在内存 | Core 做已鉴权跨设备 WSS 中继（不落正文）；各设备节点就地驱动 Hermes/Codex/OpenCode/dsh/Antigravity/OpenClaw 并保管上游历史 |
| Scheduler | 一个管理 UI 展示来源、任务、能力、时区及历史 | Studiolo 原生任务由 Core 现有引擎执行；远程任务由指定 Agent 实例的原生 Cron 执行 |
| Theme | Vue 根节点加载共用 Theme Registry；平台侧报告可用材质能力 | 继续保存既有外观偏好；新增主题选择是否同步 TBD-08 |

## Shared Space Security Design · 安全设计

### 信任边界与密码语义

建议采用客户端加密、Core 密文同步。核心验收口径为每一个**内容读取动作**重新提交用户输入的 Shared Space 密码。打开或重开预览、解密列表页与搜索、查看详情、复制 Key、下载或导出、小文件读取、读取冲突内容都走同一门禁。一次最多服务一个绑定具体空间、对象或页面、操作和修订的有界请求；同一次文件读取可以内部流式传输，下一次用户读取动作重新验证。返回或取消即停止待处理请求；离开视图、后台、锁屏、登出、超时和账号切换清除可见正文与密钥引用。界面短暂显示属于当次响应，密码框、剪贴板、缩略图、自动填充和系统快照均不得成为无密码重开入口。对外部明文导出及剪贴板的产品边界见 TBD-09。

| 场景 | 建议行为 |
| --- | --- |
| UI | 使用应用原生受限命令或回环内容服务输入密码并读取，失败返回统一错误，切换对象或再次操作重新输入。界面只显示此次获准解密的目录页，锁定界面只能显示约定的最少公开状态。 |
| API | 受信客户端上的内容 API 对每次请求验证调用者、设备绑定、空间许可与本次密码。CLI 以交互式安全输入读取密码，使用受限本机 IPC 或回环请求体传递；请求、响应和诊断禁记正文、禁缓存。Key 等敏感项也走此方法。需要直接访问 Core 的调用者可通过 SDK 完成本次密码校验和解密，Core 密文复制端点只返回密文。是否开放独立联网内容 API 见 TBD-03。 |
| 密文同步 API | 建议用独立的空间复制授权，绑定工作区、设备、读写方向与空间；普通身份令牌单独访问时不能取得明文，也不能默认访问空间复制端点。复制返回的密文、封套和有限元数据均不能充当内容读取凭据。 |
| 离线 | 已授权设备可对本机密文和封套验证当次输入，之后解密请求内的页或文件。未下载、版本不支持或密钥不可用时显示对应状态。离线可用性只覆盖实际落地的密文，吊销无法远程收回离线设备已有副本。 |
| Automation、Agent、无人值守 API | 后台仅搬运密文。所有凭据类型、webhook、原生 Action、远程 Cron、旧任务渠道都无法获得共享明文。执行如需读取，任务记录保留受保护状态，后续交互读取仍需人当次输入；具体人工接续 UX 见 TBD-06。 |

无法远程证明 API 调用者每次都亲手键入，也无法让已经得到密文和正确密码的自定义客户端遗忘它们。Studiolo 官方 UI/CLI/SDK 实现按次交互，协议层拒绝无密码内容读取。若要求证明真人在场、离线时仍能即时吊销，需修改产品约束，见 TBD-03。应用内限制失败次数和 KDF 并发可缓解实时滥用；磁盘副本失窃后的离线尝试不受限速保护。

### 加密、版本与文件事务

- 建议由密码和每空间随机盐通过 Argon2id 派生包装密钥，以成熟库的 AEAD 解包随机 Space Key；封套验证失败即拒绝，Core 不存密码、密码派生密钥或额外明文验证器。用每内容版本独立 DEK 加密目录、正文或文件块，Space Key 再包装 DEK。采用有版本的封套、算法 ID、KDF 参数、nonce 和 key epoch；AEAD 关联数据绑定工作区、空间、对象、版本、用途与文件块序号。算法候选为 XChaCha20-Poly1305 或 AES-GCM，具体参数、跨平台库和最低设备预算见 TBD-02。 [Argon2 规范 RFC 9106](https://www.rfc-editor.org/rfc/rfc9106.html)
- 密钥和正文仅留在本次调用的必要内存，按平台能力尽力清理，限制输入、分块和并发；避免明文临时文件、普通 SQLite、WebView 持久化、系统备份、崩溃报告、预览、日志和诊断。锁定阶段仅保留不透明 ID、修订、必要的大小/块数等复制元数据，文件名、类型标签、摘要和内容索引放进加密 manifest。Core/网络运营者仍可看到访问时间与流量大小，进一步的填充或隐藏见 TBD-02。
- Core 的建议模型为 `Space`、`DeviceGrant`、`KeyEnvelope(epoch)`、`EntryRevision`、`CipherBlob`、`Change` 与 `MutationReceipt`；各端维护独立本地密文目录、块仓储、Outbox、Cursor 和冲突记录。Workspace 与 grant 由服务器鉴权派生。密码掌握不替代身份授权，读取权也不自动授予写入、复制管理和轮换权。先验证现有 Personal Workspace 内多设备；共享成员、角色和每用户封套 TBD-01。
- 小型文本、配置和 Key 与文件走同一密文格式，存储策略以本地私有目录与 Core 私有 blob 接口为候选。先暂存密文块，校验限额、密文 digest 和 complete manifest，再以原子元数据事务发布对象与变更。客户端先提交本地密文对象与 Outbox，再展示待同步。失败可重传原块、原 mutation ID；未发布块回收与 tombstone/历史保留联动，已提交引用不能被清理。首发限额和 PostgreSQL／对象存储选型见 TBD-02。禁止发公开链接或可绕过授权的明文下载链接。
- 复制 API 独立协商版本，按密文修订分页并用隔离游标；快照重建保留 Outbox，快照到增量需要同一锚点，按租户/设备检查并对记录设上限。未获取新密钥世代时仍可传输密文，写入旧 epoch 则拒绝并保留可恢复的本地草稿。并发编辑保留两个加密版本与基线，冲突每次查看都输入密码，解决时按修订 CAS 提交。删除/过期游标、未下载块与损坏密文分别报错。
- 建议区分改密码与密钥事件响应。常规改密验证旧密码，生成新盐和封套并用 CAS 更新封套版本。怀疑密钥泄露或撤销共享成员时，需新随机 Space Key 与新 epoch；只换封套无法保护已泄露的旧密钥和旧密文。按威胁决定旧版本重包或重新生成 DEK 并重加密正文，先暂存并验证，再切换活跃 epoch，跨设备拒绝陈旧写入，故障可断点续做。新端记住已接受的最高 epoch 并拒绝静默回退；合法恢复需显式识别并对账。历史、旧备份和已被复制的内容仍可能被旧密码读取；离线吊销提示、重加密范围及恢复策略见 TBD-01/04。

## Agent Adapter Design · 聊天与多设备舰队协同设计

### 上游实证与目标协议矩阵

| 项目 / Harness | 协议与实现证据 | Studiolo 候选映射与传输方式 |
| --- | --- | --- |
| OpenClaw Gateway | 官方 WebSocket 握手支持协议范围、operator scope、设备身份与配对；会话用 `sessions.list`，正文用 `chat.history`，提交／中止用 `chat.send`、`chat.abort`。当前文档描述发送幂等键、事件和历史游标恢复，部署版本须协商。 [协议](https://docs.openclaw.ai/gateway/protocol) · [传输](https://docs.openclaw.ai/gateway/protocol/transport) · [会话控制](https://docs.openclaw.ai/gateway/protocol/rpc-session-control) | 认证成功才标为可用，按方法授权分别开放读／写；通过同一 `requestId` 处理确认丢失与历史游标恢复。 |
| Hermes Agent | 官方 `hermes serve` 提供 Remote Gateway（`GET /api/sessions`、`GET /api/sessions/{id}/messages`、`/api/ws`），同时原生支持 **`hermes acp`**（标准 **ACP** JSON-RPC 2.0 over stdio，`session/new`、`session/load`、`session/prompt`、`session/update`、`session/request_permission`）。 [Remote Gateway](https://hermes-agent.nousresearch.com/docs/user-guide/desktop) · [Dashboard API](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/web-dashboard.md) | 同一机器节点优先走 `hermes acp`（统一 ACP 适配器）或经授权的 `hermes serve` WSS/REST；支持分页历史与增量更新。 |
| Hermes Mobile（参考） | 社区实现 `goncharik/hermes-mobile @ 52dae9b` 使用 `session.resume`、`prompt.submit` 与流事件并作断线重放与 rehydrate。 | 借鉴断线重连和服务端 rehydrate 状态机；Studiolo 坚持不建跨端聊天正文落盘缓存。 |
| OpenAI Codex CLI | 官方提供 **`codex app-server`**（双向 JSON-RPC 2.0，默认 `stdio` JSONL 或 `--listen ws://`）及 `codex exec --json`；内置 Thread/Turn（`thread/resume`、`thread/fork`）、流式增量与工具审批请求，支持 `codex app-server generate-ts` 生成类型并接入 ACP 生态。 | 作为 Headless 结构化编码 Runner 接入本机/远端节点（不用重型 PTY）；默认强制人工审批高危命令。 |
| OpenCode | 官方提供 **`opencode serve`**（OpenAPI 3.1 HTTP + SSE/WS、HTTP Basic Auth、`http://<host>:<port>/doc`、`/session/...`）及 `@opencode-ai/sdk`（`createOpencode` / `createOpencodeClient`），并兼容 ACP 生态。 | 优先通过 `@opencode-ai/sdk` / HTTP+SSE 或 ACP 适配器接入；复用其自带 `/session` 会话历史。 |
| DeepSeek Harness (`dsh`) | 采用插件化本地架构，社区配套有 `codsh` / `dsh-cli` / MCP Gateway（`dsh-agent-gateway`）及带鉴权的 HTTP 外观插件（`dsh-gateway-server`）。 | 本机节点经受控 CLI Wrapper（`dsh-cli`/JSON 输出）或本地带鉴权 HTTP/MCP 网关接入，不向公网裸露内部 HTTP 端口。 |
| Google Antigravity (`antigravity` / `agy`) | 提供 **`agy`** 终端 CLI 与官方 **`google-antigravity` Python SDK**（`Agent` / `LocalAgentConfig` 异步上下文，`agent.chat()` 实时流式输出 `response`、`response.thoughts` 与 `response.tool_calls`）。 | 在运行 Python 环境的桌面或服务器节点上直接以 `google-antigravity` Python SDK 包装为 `AgentAdapter` 流式 Provider，保留只读/读写能力显式开关。 |

### 个人多设备部署拓扑（Mac Core + frp/VPS 边缘入口 + 控制/数据双面分离）

针对你的实际拓扑（**Core 运行于 macOS；外加 1 台 Windows + 2 台手机 + 2 台 OCI VPS + 1 台腾讯云 VPS；常用 `frp` 内网穿透**），核心架构为「**Mac Core 轻控制面与数据库 + `frp` 控制隧道 + 云端 Edge Blob Relay / LAN 直传双通道文件总线**」：

```text
  移动端 (Android ×2) / 外网设备 (/chat、/space & Sync v3)
            │
            ├──[控制面 & Sync] HTTPS + WSS ──▶ 公网 VPS (Caddy/Nginx TLS + frps) ──frpc──▶ Mac Core (PostgreSQL + Relay Hub)
            │                                                                                ▲
            └──[大文件数据面] 直连 LAN / frp xtcp P2P 优先；不可直连则走同台 VPS 上的 Edge Blob Relay（客户端 AEAD 密文分块，零回流 Mac）
                                                                                             │
   ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐                               │
   │  Windows 桌面   │ │  OCI VPS #1/#2  │ │  腾讯云 VPS      │ ───── outbound WSS (sn_live_) ─┘
   │ agent-node      │ │ frps + EdgeRelay│ │ 或轻量 Node CLI │
   │ codex/opencode/ │ │ + agent-node    │ │ hermes/dsh/agy  │
   │ dsh/antigravity │ │                 │ │                 │
   └─────────────────┘ └─────────────────┘ └─────────────────┘
```

1. **Mac 无公网 IP 时的 `frp` + 双面分离策略**：
   - **轻控制面走 `frps → frpc → Mac Core`**：VPS 终结公网 HTTPS/WSS 后，仅将体积小、低延迟的 Sync v3、节点心跳、Chat 流式增量、审批信令与 `ArtifactRef` 文件票据经 `frp` 转入 Mac 回环口（`127.0.0.1:8000`）。
   - **大文件数据面不经 Mac 二跳**：无论是 `/chat` 互传文件/截图/构建产物还是 `/space` 共享文件，均采用客户端 AEAD 预加密的 `1–4 MiB` 内容寻址分块 HTTP 流（含 SHA-256 校验与 `Range` 断点续传）；优先尝试同局域网 `LAN` 或 `frp xtcp` 直连端点互传，不可直连或收件方休眠时流式写入公网 VPS 旁的 **Edge Blob Relay**（仅存密文分块与 TTL，拿不到密钥与明文），避免 Mac 住宅窄带上行成为全端瓶颈。
2. **Mac Host 常驻与同机隔离要求**：
   - **防休眠与备份**：Core 落在 Mac 上后，Mac 即为全端同步与 Agent 调度中心，需关闭自动休眠（电源常开 + `launchd` 守护）并定期向 OCI / 腾讯云加密异地备份 PostgreSQL 与 Core 配置。
   - **同机逻辑隔离**：Mac 上的 Core 服务与 Mac 本机 `Agent Node` 使用独立身份与目录边界——远端/手机访问 Mac 文件或执行命令仍必须经过 `Node Token` 与本地不可远端覆盖的 `allowedRoots` 目录白名单及默认人工审批。
3. **本机直连、跨设备与休眠状态语义**：同机前端/桌面 Sidecar 直接对接本机实例或 Mac Core；跨设备由 Windows / OCI / 腾讯云节点主动向 Mac Core 建立反向认证 WSS 长连接。Windows 笔记本合盖休眠时仅标示「Windows 节点离线」，OCI/腾讯云节点与 Mac 本机服务持续在线。
4. **多 Agent 协作模式（/chat Fleet Console）**：
   - **Fleet 并行监管**：左栏按设备展示 Mac / Windows / OCI / 腾讯云上所有在线 Agent 实例与实时状态灯（`idle` / `running` / `waiting_approval` / `offline`），右栏展示所在设备、当前工作目录、`dataScopes` 及绑定原生 Cron。
   - **结构化批准流（Remote Approval）**：Codex / OpenCode / Hermes 在 Mac、Windows 或 VPS 执行写文件或 Shell 前触发 `session/request_permission`，经 Mac Core 推到手机或桌面弹窗（展示命令、目标路径与风险等级），明确点选「允许一次 / 本会话允许 / 拒绝」后继续执行。
   - **协作编排（Fan-out 与 @Handoff）**：支持将同一提示并发广播给同仓或跨机的多个 Agent（同仓库并行编码时由所在节点先 `git worktree add` 隔离目录再启动会话）；以及在同一协作流中把云端 VPS（如 OCI 上的 Hermes）的研究结论一键引用转交给 Mac 或 Windows 上的 Codex 执行。

### 统一接口、零持久化与远程执行安全边界

建议 `AgentAdapter` 以 `connect/close/probe/capabilities` 管理通道；可选 `ChatPort` 提供 `listSessions(page)`、`openSession(ref?)`、`getHistory(ref, page)`、`send(ref, text, requestId)`、`watch(ref, cursor?)`、`respondPermission(ref, callId, decision)` 与 `cancel(ref, runId)`；可选 `CronPort` 实现下一节接口。连接存在 Core 工作区、目标设备节点 ID、Agent Provider（`openclaw`/`hermes`/`codex`/`opencode`/`dsh`/`antigravity`）、上游实例/profile 与连接身份的完整绑定。会话/消息/任务标识为上游不透明值，跨连接引用无效。每项能力独立呈现，包括历史、分页模式、发送幂等、取消、审批支持、断线重放和 Cron 权限。

- **严格控制远程执行攻击面**：手机经 Core 调度 Windows/Mac/VPS 上的 Coding CLI 等同于远程代码/命令触发能力，必须满足以下硬约束：
  1. 跨机控制强制 Core 非回环 HTTPS/WSS 证书校验与每节点独立可吊销设备凭证（`Node Token`），节点禁止开放公网无鉴权入站端口；
  2. 每个节点本地配置不可从远端覆盖的 **工作区目录白名单（`allowedRoots`）**，任何会话只能在白名单目录（及其隔离 worktree）内启动；
  3. 远端节点默认开启人工审批（等价于 Codex `on-request` / `untrusted`），严禁默认放行 `--full-auto` 或 `danger-full-access`。
- **网络状态与流事件**：状态区分从未连接、连接中、鉴权失效、在线、重连、所在设备离线、不可达、协议不兼容和能力缺失。在线由已认证握手加心跳／近期请求确认，和旧 Agent Runtime 心跳独立。流事件规范化为 `Accepted`、`ThoughtDelta`、`TextDelta`、`ToolCall`、`PermissionRequest`、`Snapshot`、`Completed`、`Failed`、`ConnectionState`，保留上游 run/message ID 与受支持 sequence/cursor，限制内存和渲染大小。中断与取消语义分开；发送确认丢失先查回执、活跃 run 或历史，仅在上游明示幂等时复用 `requestId` 重发。
- **Core 零正文持久化**：在线历史由目标节点的上游 Harness 提供。客户端在当前设备用 AES-GCM 加密保存最近打开的会话和待发消息，按 Core 和账号隔离。浏览器或 WebView 使用不可导出的本地密钥。草稿、审批卡和历史附件的传输密钥保留在内存。Agent Node 的命令回执只存命令 ID 的摘要和时间，Core 中继不保存聊天正文。
- **凭据与隐私隔离**：模型订阅凭据与网关密钥留在跑 Agent 的节点系统凭据库或本地配置内，Core 不代管用户的 Claude/OpenAI/DeepSeek 订阅密钥，只在 Core ↔ Node 间维护连接身份凭证；禁止将入站 `na_live_` 直接用作上游密钥。Shared Space 的密码和内容严禁进入聊天、Agent 凭据例外或自动化。部署拓扑与协议基线见 TBD-05；附件、Diff 预览与多 Agent 协作房范围见 TBD-07。

## Unified Scheduler Design · 定时任务管理

| 所有者 | 已有存储、接口及语义 | 集成方式 |
| --- | --- | --- |
| Studiolo Core | Workflow、Execution、ScheduleState、ActionReceipt 和 Event；原生 schedule、manual 与业务事件，支持已有运行记录与内部动作回执。配置定义经 v3 同步；执行调度在 Core。 [调度实现](../backend/app/automation/schedule.py) · [执行引擎](../backend/app/automation/engine.py) | Job 管理视图映射到既有 API 与表；保留原生非定时触发类型和原有定义、ID、历史。 |
| OpenClaw Gateway | Gateway 自己存与执行 Cron。官方 RPC 含 `cron.list/get/add/update/remove/run/runs`；所核对文档版本的手动执行返回 runId，可查询分页摘要。暂停／恢复经支持的更新字段。 [Cron RPC](https://docs.openclaw.ai/gateway/protocol/rpc-devices-nodes-and-approvals) · [Cron 行为](https://docs.openclaw.ai/automation/cron-jobs) | 原生 CRUD 直接路由到目标实例；按当前 scope 和协议显示权限，从上游读执行状态。 |
| Hermes Gateway/profile | 原生调度在 Hermes，每 profile 持有 `jobs.json`、调度锁与 `executions.db`；官方 Dashboard 管理接口包括 `/api/cron/jobs`、更新和 pause/resume/trigger，API Server 还有一套 `/api/jobs`。固定源码提交还提供 `GET /api/cron/jobs/{job_id}/runs?profile=…&limit=…`，合并会话、脚本输出和执行账本，返回有界历史。目标发行版、服务模式和认证能否访问该接口仍需联调；存在 profile 自带的 ticker 仲裁，同一安装可能还使用 Hermes 官方托管 Cron。 [Dashboard](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/web-dashboard.md) · [API Server 源码](https://github.com/NousResearch/hermes-agent/blob/main/gateway/platforms/api_server.py) · [Cron 行为](https://hermes-agent.nousresearch.com/docs/user-guide/features/cron) · [固定提交的 Cron 路由](https://github.com/NousResearch/hermes-agent/blob/f8acc26834bf1275c34d09ccc3e51250bcd1e26b/hermes_cli/web_routers/cron.py#L3389) · [账本源码](https://github.com/NousResearch/hermes-agent/blob/f8acc26834bf1275c34d09ccc3e51250bcd1e26b/cron/executions.py) | 优先验证获授权的原生 Dashboard/Gateway 接口，按精确能力区分分页、最近 N 条、仅有最后状态和不可查询。保留 Hermes 对 catch-up、暂停、取消及手动运行的原生语义；受其他调度服务托管的任务先标明来源，按实际所有权和可验证能力开放操作。 |

- 建议 `JobRef(workspaceId, ownerType, ownerInstanceId, ownerProfile, nativeJobId)` 为稳定主键，实例去别名后才聚合。 `Job` 包含显示名、启用态、`ScheduleSpec`、所有者原生时区、下次计划时间、原生修订及 capability。 `JobRun` 使用所有者 run ID、计划时间、实际起止时间、规范化状态和原生状态；允许 unknown 和 historyUnavailable，返回有界分页及来源。Cron、interval、one-shot、非定时触发和 DST/misfire 各按原生语义展示；不支持的计划格式只读。
- `CronPort` 定义 `list/get/create/update/delete/pause/resume/runNow/listRuns`。CRUD 路由给唯一 owner，服务端验证连接、工作区和具体权限；写入采用明确 allowlist、provider revision/CAS（若支持）、操作确认及请求关联 ID。无 CAS 时比较最近快照，界面提醒上游并发编辑限制且冲突时重新读取；远端离线时禁用写入。失败或未知结果先查询所有者，使用远端 idempotency/回执确认后才重试；无法去重则标为未知并要求人工核对。仅存必要的连接引用和无内容回执，远程定义及历史以所有者实时结果为准。
- 原生任务继续通过现有唯一触发键（手动运行沿用 request_id）、schedule state、行锁、租约和 fencing，内部副作用通过回执获得可重放语义。外部副作用按至少一次／结果未知建模，接受稳定幂等键的下游才可安全重试；不得宣传外部 exactly-once。远程 Cron 定义绝不写入 `AutomationWorkflow` 的可调度集合，轮询仅刷新状态，断线不接管。Studiolo workflow 若执行一次 `agent.run`，调度所有者依然是 Studiolo；不得再为同一次 run 创建 Agent Cron。
- 同一逻辑任务可配置在两个上游，名字或表达式不足以认定重复。联接记录以实例、profile 和原生 ID 去重；计划迁移为 TBD-10。若将来批准迁移，必须先停旧 owner、确认无排队或进行中、记录切换锚点，才启用新 owner。旧端停用无法确认时保持新任务禁用。另需验证原生 Cron 在上游自己的多实例部署下仍符合单所有者要求。

## Theme Engine Design · 主题引擎

- 将现有 CSS 变量迁移到语义层，包括背景、浮层、表面、正文、弱文本、强调色、焦点、状态色、边框、间距、圆角、字号与动效。材质层单独定义表面底色、透明度、模糊、边缘高光、遮罩与阴影。先在现有 `src/` 增加共享模块，桌面与 Android 使用同一份定义、校验与 CSS，平台差异从根节点能力输入。
- `ThemeDefinition` 建议包含稳定 `id`、定义版本、浅／深语义 tokens、材质预设和可用特性。Theme Registry 校验字段，Vue 根节点根据主题、显式 light/dark 或系统模式以及可及性/性能覆盖项统一设置 CSS；预览容器使用相同解析器。新增主题通过登记定义交付，具体默认主题和未来动态扩展 TBD-08。
- Liquid Glass 是可选材质主题。首批覆盖导航、快捷面板、状态卡和弹窗；长列表、输入区与长文本用高对比实体表面。将 `GlassCard` 等组件逐步改为按 surface role 消费 tokens；保留旧类名兼容入口，先迁移共用控件，再迁业务页。平台报告不支持模糊、用户选择减少透明／减少动态效果、低性能模式时退化为不透明表面、简化阴影与静态切换。CSS `@supports` 作防线，性能判定和预算见 TBD-08。
- 旧 v3 的 `appearance.theme = light/dark/auto` 映射为色彩模式，主偏好 `theme = light/dark/system` 用于缺失值回退；旧 accent/blur/transparency/background 安全映射，材质参数仅在对应主题生效。新 `themeId` 先走设备设置，禁止直接注入旧 v3 严格对象。未知主题渲染已登记的默认回退并保留选择，支持未来版本识别。验收比较 Windows、macOS、Android 的同一 tokens、亮暗及降级效果，覆盖键盘、系统返回、安全区、字体放大和 TalkBack。

## Migration and Compatibility Plan · 迁移与兼容

1. **先确定基线。** 保存当前 schema head、v3 样例、受支持版本和客户端能力，使用脱敏 v0.6.1 及 v0.6.2 样本覆盖 SQLite、PostgreSQL、桌面打包、待同步队列、冲突与 Agent 旧接口。Android 本地迁移按版本单独演练。比对数量、主键、外键、代表性字段、待同步行与 Cursor，包含写入中断和备份恢复。
2. **加法部署。** Core 先上线有默认关闭开关的独立能力和 additive migrations，旧客户端继续使用原路由及 v3，未知 Shared Space 能力只影响相应入口。新端连接旧 Core 时仍能使用旧业务，受保护的新能力标为不可用。新受保护接口上线前验证非回环 HTTPS/WSS、证书和安全存储。功能关闭保留加密表、文件和各端待同步项，升级故障优先回滚应用／关闭功能，旧二进制对新 schema 的支持须实测。
3. **迁移现有数据时保留来源。** Shared Space 初始为空，除非获批明确的按项导入。导入由本地显式发起，完成新密文及校验后报告状态，用可重试的映射防止重复；既有 Data/配置、历史备份或外部来源按原兼容路径保留，迁移范围和清理选项见 TBD-09。跨版本读取继续校验工作区；含密码学版本的新旧客户端拒绝未知 envelope，保留原密文和 Outbox。
4. **迁移旧桌面凭据。** 独立于 Shared Space，使用 `CredentialStore` 兼容接入 Windows/macOS 安全存储。验证旧绑定、原子登记并回读新凭据成功后收口旧副本。失败时保留原绑定状态或引导重新配对，并保持 Outbox，不静默另建工作区；旧备份里的明文令牌需通过轮换失效。凭据迁移后回退到旧二进制的路径是已验证的重新授权／恢复方案，不能靠重新写入明文令牌。
5. **数据库与密文备份。** 新旧库演练仅用隔离副本。Core 数据库与密文 blob 做同一恢复点验证，校验引用及 checksum；数据库回退后验证陈旧设备的快照、队列重放、epoch 冲突与吊销状态。恢复备份中的密文不会恢复用户密码。发布前演练错误升级、磁盘满、服务重启及远端不可用；遇数据不一致暂停新能力并遵循本地待同步项保全流程。

## Risk Register and TBD Decisions · 风险与待定

| 风险 | 级别 | 控制与验证 | 归口 |
| --- | --- | --- | --- |
| 离线密文副本可被猜密码，遗失设备无法即时收回 | 高 | 端到端封套、强密码与实机 KDF 基准；验证撤销在线访问、旧 epoch 冲突，文档明确离线边界 | Shared Space，TBD-01/02/04 |
| 读取门禁被搜索、预览、历史、导出或代理路径绕过 | 高 | 同一按次门禁，构建 UI/API/离线/自动化负向矩阵，逐处扫描哨兵内容 | Shared Space，TBD-03/06/09 |
| 新实体阻塞 v3，密文块与数据库提交出现悬挂 | 高 | 隔离游标与版本；模拟断电、重复上传、缺块、Core 恢复及并行写入 | Sync 与 Shared Space |
| Android 壳工程误算为业务 MVP；桌面发布回归不足 | 高 | 固定工具链，v0.8.0 先完成 Websites 原生垂直切片；按既有版本和候选安装包保存三端真机/实机记录 | v0.8.x / v0.9.0 |
| 多端 Agent 协议漂移或远程 Shell/工作区越权执行 | 高 | 按版本锁定契约样例，强制 TLS WSS + 独立节点凭证、`allowedRoots` 目录白名单及默认人工审批 | Agent，TBD-05/06 |
| 流式内容误入日志、存储、Job 或通知 | 高 | 正文哨兵检测、空磁盘恢复验证、禁原始事件持久化及默认错误回流 | Chat，TBD-07 |
| 远端重试或错误投影触发重复执行 | 高 | 单 owner、原生回执、未知状态不自动重试；并发、丢确认、重启与恢复测试 | Scheduler，TBD-10 |
| 外观字段不兼容、低端机掉帧或文本对比不足 | 中 | v3 字段保持，跨端对比、无模糊与减少动态效果验收 | Theme，TBD-08 |
| 旧明文凭据和新安全存储迁移失败 | 高 | 双平台安全存储验证、原子切换、失败重新配对与原队列保全 | 身份，v0.9.0 发布门槛 |

| TBD | 待决定项 | 最晚决策点与影响 |
| --- | --- | --- |
| TBD-01 | 共享范围是否从个人多设备扩至多用户，读写角色、设备缓存与撤销策略 | v0.7.1 Shared Space 原型前冻结；影响封套、ACL 与离线撤销文案 |
| TBD-02 | 密码强度规则、KDF/AEAD 选型、低端机预算、单文件／空间限额、后端 blob 选型、可见元数据和保留期 | v0.7.1 Shared Space 原型前确认，通过跨语言、配额和负载验证 |
| TBD-03 | 每次读取的列表页/文件流边界、API 是否要求真人在场、是否开放直接联网的内容 API | v0.7.1 对外契约冻结前确认；每次重新输入密码是既定约束 |
| TBD-04 | 忘记密码后的恢复／无恢复提示、旧备份处理、密码变更与泄露时轮换的历史范围 | v0.7.1 可用性设计前确认；不可自行增加恢复密钥或托管 |
| TBD-05 | Windows / Mac / OCI / 腾讯云等设备节点拓扑、各 Harness 锁定版本（Hermes ACP/Gateway、Codex app-server、OpenCode serve、dsh、Antigravity/agy）与重连边界 | v0.7.0 Mac Core & Fleet 联调前固化；影响节点注册表、凭据和状态实现 |
| TBD-06 | Agent 连接凭据是否允许特例，由谁保管、Scheduler 是否允许无人值守用独立授权，Shared Space 读取任务如何人工接续 | v0.7.0/v0.7.2 各相关功能开启前审批；任何设计仍受内容按次密码约束 |
| TBD-07 | `/chat` 多 Agent 协同（Fan-out 并发、git worktree 自动隔离、@Handoff 转交）、工具审批卡、Diff 预览与附件首发范围 | v0.7.0 提出候选范围，待决部分按能力开关控制 |
| TBD-08 | 默认主题、用户选中主题是否跨端同步、兼容映射细则、低端机和视觉预算 | v0.7.1 主题验收前冻结；影响兼容和性能门槛 |
| TBD-09 | 现存文本/配置/Key 的显式导入范围、外部明文导出、剪贴板与原件清理方案 | v0.7.1 导入／导出入口开启前确认 |
| TBD-10 | 远程所有者转移、需要支持的精准执行历史、Hermes 版本/接口差异、兼容版本窗口 | v0.7.2 统一调度验收前确认；可独立决定转移功能是否排期 |
