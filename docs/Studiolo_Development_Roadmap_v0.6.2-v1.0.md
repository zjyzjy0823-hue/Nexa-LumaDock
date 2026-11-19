# Studiolo 开发路线图 · v0.6.2–v1.0.0

- **更新日期** 2026-11-19（已完成 `v0.7.0` 主体与多端收口提交，转入 `v0.7.1`）
- **仓库基线** `main @ 6ab1a0e`（`v0.7.0` Agent Fleet 协同工作台、内联媒体与五款气泡主题、macOS 双架构 DMG CI、Desktop/Android 原生直连 Core Fleet 登录及 OpenCode `allowedRoots` 校验均已落地）
- **关联文档** [当前架构审计、详细设计、迁移与 TBD](architecture-plan-v0.6.2.md)

## 产品方向与分期

Studiolo 保留 Local-first 及多端同步。**先让常驻 Mac Core、多设备 Agent Fleet Chat（`/chat`）与 Shared Space（`/space`）在桌面端与手机 Web 端跑通并上线可用**，再补全 Android 原生 Rust `sqlx` 离线数据层与同步闭环，降低先重造第二套本地持久化的前序等待成本。Shared Space 坚持每读必重输密码，Agent Chat 坚持零聊天正文持久化，Cron 管理坚持单所有者语义。TBD 依赖产品确认后开放对应入口。

| 版本 | 主要交付 | 依赖与主要风险 | 建议工作量 |
| --- | --- | --- | --- |
| **v0.6.2** | **已收口**：架构审计、Sync v3 契约、`0018`/`0019` 迁移与恢复、Android 壳（`3537e1f`）、Studiolo 全面更名与 Mac Core/Fleet 架构冻结 | 仅余可选打 `v0.6.2` 发行 tag | ✅ 已收口 |
| **v0.7.0** | **Mac Core 部署与多设备 Agent Fleet Chat（`/chat` MVP + 协同工作台）**：Mac 常驻 Core + VPS TLS 反向入口，接入 Hermes / Codex / OpenCode / dsh / Antigravity / OpenClaw、远程审批、Diff 评审、多端直连 Core 登录与安全边界加固 | 本地全量回归已通过（107 前端 + 6 agent-node + 503 后端），待远端推送 CI 与多节点实机最终验收 | ✅ 主体已收口 |
| **v0.7.1** | **Shared Space（`/space`）三档分级共享首版 & Theme Engine 标准化**：`standard`（随时查看/专用 Space Token API 直读）+ `protected`（UI 按次输密/细粒度 Vault Token 直读）+ `e2ee`（Argon2id/AES-256-GCM 零知识与 Epoch 轮换）；共用 Theme Registry 与可选 Liquid Glass | 本地全量单测、跨语言密码学向量与生产构建已通过，待远端 CI（含 PostgreSQL 0021 迁移）与真机验收（详单见 [v0.7.1 计划](v0.7.1-plan.md)） | ✅ 主体已落地 |
| **v0.7.2** | **统一定时任务（Cron）管理 & macOS 桌面端回归**：Studiolo / OpenClaw / Hermes 单所有者 `JobRef` 视图、CronPort 远程适配、通知脱敏与丢确认防重调、PyInstaller 打包加固 | 本地前后端与 AgentNode 单测及构建已通过，待实机 OpenClaw/Hermes 上游联调与 macOS DMG 实装验收 | ✅ 主体已落地 |
| **v0.8.0** | **Android Local-first MVP**：CI Android SDK 构建链、Rust `sqlx` SQLite + Outbox 同事务、Keystore 认证与 Websites 双向 Sync v3 | Android 工具链配置（JDK21/SDK37/NDK）、Rust 与 Python 双端 schema 一致性 | 🚧 下一阶段（12–20 人日） |
| **v0.8.1** | **Android 全业务与移动完整体验闭环**：Ledger / Data / Conflict Center、Automation、Share to Studiolo、Android 本地密文块缓存与无障碍/低端机优化 | 跨端金额/时区语义、父子依赖同步、TalkBack 与 48dp 触控规范、Android 密文块接入 | 14–24 人日 |
| **v0.9.0** | **功能冻结、安全加固与发布工程**：长离线与密文恢复、桌面旧凭据安全存储迁移、Android WorkManager 后台同步、三端签名/公证候选包 | 跨版本升级与库/blob 一致性恢复、桌面凭据无损迁移、真机持久运行诊断 | 12–22 人日 |
| **v1.0.0** | **三端正式发布**：Windows / macOS / Android 全量核心业务、Shared Space、Agent Fleet Chat、单所有者 Cron 与支持矩阵通过 | v0.9.0 候选验收、兼容矩阵、升级与故障回退演练 | 5–9 人日 |

人日为建议范围，含实现、联调和回归；采购、签名账号、上游 CLI 协议变更和 TBD 等待时间单列。`/chat` 的 Node 适配与 `/space` 的密文服务可各自独立测试并按开关灰度开放。

## v0.6.2 · 兼容基线与决策收尾（✅ 主体完成）

- **062-01–05** 已在 [状态盘点](v0.6.2-status-2026-11-16.md) 全部验收通过（1828 行架构审计、Sync v3 契约与三语言校验、`0018`/`0019` 迁移与 `5` 万条压测、三路越权 404 测试及 `docs/android-auth.md`）。
- **062-06** `3537e1f` 已完成 Android 纯代码工程壳补齐并在真机启动安装（`#9`）。
- **062-07** 已完成全仓更名 **Studiolo**、几何 **S** 矢量图标重绘、纯白默认桌面/移动 UI 收敛及 Mac Core + 7 设备 Agent Fleet 方案冻结（`7e0a138`）；后续仅按需补充 `v0.6.2` Git tag 与发行元数据。

## v0.7.0 · Mac Core 与多设备 Agent Fleet Chat（`/chat`）（✅ 主体已收口）

- **070-01 Mac Core 常驻与 `/chat` 控制台**：在 macOS 主机部署常驻 Studiolo Core（PostgreSQL + `launchd` 防休眠 + 定期异地备份），通过腾讯云/OCI VPS TLS 反向隧道或 Tailscale 私网向手机与 Windows 开放入口；已实现独立 [ChatPage.vue](file:///d:/xiangmu/LumaDock/src/pages/ChatPage.vue) 三栏与移动端 Agent Fleet 控制台，支持设备在网感知、并发对话、同仓 `git worktree` 隔离、结构化工具审批卡、Fan-out 广播、`@Handoff` 转交、正文内联图片/文件卡片及五款对话气泡主题。
- **070-02 统一 `AgentAdapter` 与多设备 Node 接入**：实现标准化事件总线（`Accepted`、`ThoughtDelta`、`TextDelta`、`ToolCall`、`PermissionRequest`、`Snapshot`、`Completed`、`Failed`、`ConnectionState`）与轻量 Device Agent Node（桌面 Sidecar / Mac 独立边界节点 / Windows 与 Linux VPS 常驻节点），首批支持 **Hermes（`hermes acp` / `hermes serve`）、Codex（`codex app-server`）、OpenCode（`opencode serve` / SDK）、dsh（受控 CLI/网关）、Google Antigravity（`agy` / Python SDK）** 与 **OpenClaw Gateway**。
- **070-03 远程执行安全边界与零正文持久化验收**：强制非回环 HTTPS/WSS 证书校验与每节点可吊销 `Node Token`、不可远端覆盖的 `allowedRoots` 目录白名单（含 `8596fb7` OpenCode 会话目录强校验）、高危命令默认人工审批；复用并修复 `agent.run` 与 Data Actions scope 校验；全端库/日志/缓存哨兵扫描确认聊天正文零落盘。
- **070-04 多节点兼容列表、多端直连与打包收口**：已完成 macOS Intel/Apple Silicon 双架构 DMG CI（`41d5627`/`ee85eab`）、Desktop 独立会话级登录 Core Fleet 及 Android 首次启动直连 Core（`6ab1a0e`），本地全量回归全部通过；剩余远端推送 CI 校验与 7 设备实机联合演练按发布窗口补齐证据。

**独立验收** 在真实 Mac Core + Windows + 手机 + OCI/腾讯云节点环境下完成 6 类 Harness 建连、历史上游拉取、并发流式输出、远程工具批准、节点休眠离线与断网重连；数据库、日志、Outbox 与诊断导出均无任何聊天正文与模型订阅密钥；既有 Local / Sync v3 / Data Actions 零回归。

## v0.7.1 · Shared Space（`/space`）三档分级共享与 Theme Engine

详见 [v0.7.1 详细设计决策与开发清单](v0.7.1-plan.md)。

- **071-01 安全原型与契约冻结**：确立三档安全分级——**普通共享（`standard`）**、**受控机密（`protected`）**、**极密保险库（`e2ee`）**；验证 `Argon2id` + `AES-256-GCM` 密文格式与 TS/Python 跨语言测试向量，冻结 TBD-01–04/08/09、配额与鉴权矩阵。
- **071-02 分级同步 API、独立 Token 与仓储**：Core 落地隔离 `Space`、`SpaceToken`（普通 `ss_live_` / 机密 `sv_live_`）、`DeviceGrant`、`KeyEnvelope(epoch)`、`EntryRevision`、`CipherBlob`、`SpaceChange`、`SpaceMutationReceipt` 与访问审计表；`standard` 支持 JWT / `ss_live_` 及 Agent Data Actions 白名单只读，`protected` 仅允许细粒度 `sv_live_` 直读（Core 主密钥信封加密落库），`e2ee` 仅同步密文；桌面 Sidecar 落地本地块仓储与 Outbox。
- **071-03 `/space` 分级工作台与按次输密/轮换**：将 `/space` 占位页升级为独立 [SpacePage.vue](file:///d:/xiangmu/LumaDock/src/pages/SpacePage.vue)（桌面 + 手机 Web）：`standard` 随时查看/预览/下载；`protected` 与 `e2ee` 每次读取必重输密码、离页即清空内存；支持常规改密（CAS 重包封套）、`e2ee` 泄露撤销 `epoch` 轮换及 Token 签发/吊销/审计视图。
- **071-04 Theme Engine 与可选 Liquid Glass**：在共用 Vue 层固化 Design Tokens、Theme Registry（衔接当前 `纯白（默认）`、`纸墨`、`Liquid Glass` 与 5 款气泡风格）、浅/深与无模糊降级适配，严格兼容旧 v3 外观字段。

**独立验收** 四类共享对象（小型文件、文本、配置、Key）按三档分级在 Mac/Windows/手机端可用：`standard` 可随时查看及经 `ss_live_` / 白名单 Agent API 读取；`protected` UI 必输密码且仅细粒度 `sv_live_` 可直读并留审计日志；`e2ee` 错密码、无密码、任何令牌、篡改块、旧 epoch 写入、切页/重开/搜索均无法绕过当次密码门禁且 Core 零明文；三套主题与降级状态对比度 ≥ 4.5:1 且切换无损失。

## v0.7.2 · 统一定时任务（Cron）与 macOS 回归

- **072-01 统一 Job/Run 视图与单所有者集成**：在既有 Automation 页面按 `JobRef` 展示 Studiolo Core、OpenClaw、Hermes 三类所有者任务、原生时区、下次运行及有界执行历史；保留引擎单所有者语义，不向远端伪造重复调度。
- **072-02 OpenClaw & Hermes Cron 适配**：实现 `CronPort` 在线 CRUD、暂停/恢复、手动触发与运行账本查询，离线禁用写入并返回清晰能力边界。
- **072-03 通知脱敏与 TBD-06 确认边界**：落地无聊天正文/无凭据的任务通知，高影响 Data Actions 显式二次确认，受 Shared Space 密码保护的自动化任务停在待人工接续状态。
- **072-04 macOS 桌面端回归与兼容验证**：验证 macOS 桌面包构建、启动、在位升级、Core 同步及跨端恢复。

**独立验收** 三类 owner 各自独立维护周期、权限与运行历史；关闭 Mac Core 时远端 Hermes/OpenClaw Cron 按自身规则续跑，断网时 Studiolo 不误接管；通知与日志无正文和密钥泄漏；macOS 桌面端核心同步回归通过。

## v0.8.0 · Android Local-first MVP（原生离线切片）

- **080-01b** 补齐干净环境 Android SDK/NDK/JDK21 工具链锁定与 GitHub CI APK 产出。
- **080-02** 落地 Rust Commands、`sqlx` SQLite 迁移、受限 Repository 与 Websites/Outbox 同事务写入。
- **080-03** 接入 Core HTTPS 登录、Personal Workspace 确认、Android Keystore 凭据存储与重新授权。
- **080-04** 实现 Sync v3 前台推拉、游标分页、部分失败重放、冲突登记与快照恢复。
- **080-05** 在真机上联调 Windows / macOS / Mac Core / Android Websites 端到端离线与重启收敛。

**独立验收** 干净环境 CI 与真机可装可用；Windows/macOS 建站后 Android 可拉取；Android 断网编辑、强杀重启并联网后，UUID 与最终数据在 Core 及桌面端完整收敛。

## v0.8.1 · Android 全业务与移动离线完整闭环

- **081-01–08** 补齐 Android 离线 Dashboard、Ledger（严格遵循金额与 `Asia/Shanghai` 部署时区）、Websites 搜索标签、Data 有界读取、Automation 手动触发、Conflict Center 人工裁决、Devices/Settings 真实能力清理，以及底部「＋」快捷录入。
- **081-09** 实现 **Share to Studiolo**（冷/热启动接收系统浏览器分享 URL 离线入库）。
- **081-10–11** 接入 Android 本地 Shared Space 密文块缓存（复用桌面同套密码学与每次输密规则），并在真机完成安全区、≥48dp 触控、Android 返回栈、TalkBack、放大字体及低端机无模糊性能预算验收。

**独立验收** 手机端所有核心业务与 Shared Space 在完全离线状态下均可读写并在联网后正确解决冲突或收敛；可及性与低端机降级符合支持门槛。

## v0.9.0 · 功能冻结、安全加固与发布工程

- **090-01/02** 演练长离线、Core 回退、Cursor 失效、分页中断与密文 blob 同点备份恢复验证。
- **090-03** 完成桌面旧明文 `FileCredentialStore` 向系统安全存储平滑迁移、令牌轮换吊销传播、非回环 TLS 门禁与统一日志脱敏验证。
- **090-04** 完成 Android WorkManager 前后台同步、省电与重启恢复压测，汇总 Windows / macOS / Android 长期稳定性基线。
- **090-05/06** 产出 Windows 安装包、macOS 签名/公证包及 Android 签名 APK/AAB 候选件、校验和、兼容矩阵与回退指南。

## v1.0.0 · 三端正式发布

- **100-01–06** 在最终三端签名候选包上完成全新安装、旧版升级、全业务跨端同步与冲突解决、Shared Space 按次输密与轮换、Mac Core 多设备 Agent Fleet Chat（零正文落盘）、单所有者 Cron、多主题降级、支持矩阵及故障恢复回退全套验收。

## 发布顺序与证据规则

- 每个版本记录候选提交、包版本、Core schema、各端与 Agent CLI 锁定版本、真机结果与未覆盖项。
- 涉及 TBD 的入口在决策确认与测试矩阵通过前维持关闭或只读开关保护；高风险阻断项包括数据丢失、租户越权、Shared Space 密码绕过、聊天正文落盘、Cron 重复调度及升级失败。
