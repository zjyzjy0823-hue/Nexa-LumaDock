# 架构审计 · v0.6.2 / 062-01

> **进展（2026-11-15）**：本审计的 G3「无 resync/snapshot」与 `data_records` 租户列两项已落地——新增 `GET /api/v1/sync/snapshot`、`POST /api/v1/sync/resync`（protocol 3）与迁移 `0018_data_record_tenancy`；文中的行号与“没有 X”类结论均以当时（v0.6.1 审计时点）为准。


**基线** `main @ ab9d3ed`（v0.6.1）
**审计日期** 2026-11-15
**任务编号** 062-01（架构审计）
**方法** 10 路并行只读审计（Core / 同步 / Local Backend / 前端 / 自动化 / 测试 CI / 数据模型 / 文档漂移 / Android 准备度 / 安全凭据），结论一律以代码为准，`docs/` 仅作对照。全程未改动仓库（`git status` 干净）、未联网、未安装依赖。
**原始报告** `~/.hermes/workspace/audit/nexa-v062/01..10-*.md`（合计 1828 行，114 处 `path:line` 引用）

---

## 0. 执行摘要

1. **Android 不是"换个窗口"，是第二套后端。** 桌面所有业务逻辑住在 Python sidecar 里；Android 按路线图要用 Rust + sqlx + SQLite 重写一遍数据层。而 `src-tauri` 目前**零业务代码、零 SQL 依赖**，`sqlx|rusqlite|sqlite|tauri-plugin-sql` 全仓 0 命中。
2. **今天执行 `tauri android init` 必定编译失败**，三处硬阻断：`single-instance` 插件在 Android 是空 crate（`src-tauri/src/lib.rs:292`）、`tray-icon` 未做 cfg 门控（`lib.rs:241,304`）、`bundle.externalBin`（`src-tauri/tauri.conf.json:44`）在 APK 无对应机制。
3. **同步引擎有"永久堵死"路径。** `rejected` 状态没有任何出边（`backend/app/sync/engine.py:113` 只写不读），其依赖后继因前驱行不消失而永不就绪；未知 `entityType` 或一条 Core 脏数据会让整轮 pull 失败并永久阻塞 cursor；全仓**没有 resync/snapshot 端点**，Core 的 `Invalid sync cursor` 被映射成 `invalid_response` 后进入 blocked。
4. **契约远未冻结。** 金额 `Numeric(14,2)` 但**全仓没有 currency 列**（`models.py`/迁移 0 命中，UI 硬编码 `¥`）；时区靠应用层约定而 schema 不强制，且月度汇总用 `Asia/Shanghai` 算月份（`backend/app/services/ledger.py:272`）却拿存储值（UTC wall-clock）`strftime("%Y-%m")` 比对（`:282`），导致**月初月末 8 小时跨月错位**；URL 只做语法校验，**无规范化、无唯一约束、无查重**；`data_records`（`backend/app/models.py:290-302`）**没有 `workspace_id`/`user_id`**，租户只能经父集合推导。
5. **身份体系有两条互不相干的链路。** Client（`nc_live_`）是完整闭环；Device（`nd_live_`）是另一套手工两段式，两者无关联 —— Android 既要同步身份又要设备台账就得注册两次并维护两套凭证。这是 070-03 的核心歧义，必须在 062-05 前决策。
6. **安全边界有真实裂缝。** Desktop 的 `backend/app/core_connection.py:24-35` **没有 HTTPS 强制门禁**（`_normalize_core_url` 明确允许 `http`，`device-client` 和 `openclaw` 都有"非 localhost 必须 HTTPS"检查），可明文提交 Core 密码与 `nc_live_`；Core 自身零 TLS 执行点、裸 `0.0.0.0:8000`；`BaseAdapter.find()` 只用主键 `db.get()` 忽略 workspace，隔离靠调用方二次比对（`backend/app/sync/service.py:115-118`）；轮换覆盖同一 hash 列，令牌重叠兼容期为 **0**。
7. **主题与移动体验基本是空壳。** appearance 的 theme/accent/blur/transparency/background 五项**全部能存不生效**：`--accent` 硬编码于 `styles/main.css:11`，全仓 0 处 `setProperty`，`--glass-blur: 18px` 写死。移动侧 24 处散落断点、0 处 `env(safe-area-inset)`、触控目标 23–44px（< 48dp 标准）、无骨架屏/虚拟滚动/键盘避让，路由是手写的而非 vue-router，**无返回栈**。
8. **测试量不小（≈467 用例）但恰好漏掉最关键的失败路径。** 371 个 backend pytest 里：多页 pull（`backend/app/sync/engine.py:239-258` 有 `while hasMore` 却无人造 >100 变更）、cursor 失效、同步中途 401 重授权，**全部零覆盖**。CI 7 个 job 里**无 macOS、无 Android、无 `cargo test`**，`src-tauri` 的 5 个 `#[test]` 从不执行。
9. **文档会反向误导。** `core.md` 陈旧率 **83%**（仍写 v0.5.5 / 迁移 `0015` / `protocolVersion=2`，实际 0.6.1 / `0017` / v3），`desktop.md` **75%**（写"没有自动同步"，实际 `sync/background.py` 已落地）。这两篇无日期、以"当前状态"口吻叙述，是最大的坑。
10. **一处自我纠错**：本审计任务书最初假设「`App.vue` 已有 accent 应用逻辑」，复核**不成立**——`App.vue` 无任何外观应用代码。2026-09-30 报告里"全局主题未实现"这一条**仍然成立**。

---

## 1. 真实架构

```
Windows / macOS                                Android（尚未开始）
┌──────────────────────────┐                  ┌──────────────────────────┐
│ Vue 3 + Pinia (src/)      │                  │ 同款 Vue（复用受限）      │
│  · 手写路由，9 页          │                  │  · 无返回栈/深链          │
│  · 86 处 apiRequest 直连   │                  │  · 需经 Rust Command      │
└───────────┬──────────────┘                  └───────────┬──────────────┘
            │ 明文 HTTP + 用户 JWT                         │ 待定
┌───────────┴──────────────┐                  ┌───────────┴──────────────┐
│ Tauri 2 壳（3 个 command） │                  │ Rust Repository (sqlx)    │
│  · 无 IPC、无 token 交换   │                  │  **不存在，需从零写**      │
│  · 端口 17800 两端硬编码   │                  │                          │
└───────────┬──────────────┘                  └──────────────────────────┘
┌───────────┴──────────────┐
│ Python sidecar (FastAPI)  │ ← Android 上**不适用**
│  · SQLite，单一 Alembic 链 │    (0001→0017 与 Core 共用)
│  · outbox 串行同步引擎     │
└───────────┬──────────────┘
            │ Sync Protocol v3（`protocol.py:1`）
┌───────────┴──────────────┐
│ Studiolo Core (FastAPI + PG)  │
│  · 115 路由 / 22 router    │
│  · 只有 CORS 一层中间件     │
│  · Automation engine      │
└──────────────────────────┘
```

**与路线图 2.1 的差异**：路线图目标结构是 `apps/desktop`、`apps/mobile`、`packages/contracts|domain|sync-client|ui-tokens|shared`，仓库现在是扁平的 `src/ backend/ src-tauri/ device-client/ agent-adapters/` —— **monorepo 拆分在路线图里没有独立任务**，只在"目标目录可按需演进"一句中带过。

---

## 2. 能力现状矩阵

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| Client 身份闭环（enroll→rotate→revoke） | ✅ 完整 | `api/clients.py:124-166` |
| Device 身份 | ⚠️ 独立另一套，与 Client 无关 | `security.py` 两套 token 解析 |
| 同步 push/pull/cursor/幂等 | ✅ 主链路完整，丢响应与中断恢复有实测 | `sync/service.py:84-89`、`engine.py:175-234` |
| 冲突记录与解决 UI | ✅ **已实现**（双栏字段级差异、Keep Local/Remote、409 恢复、删除冲突） | `ConflictCenter.vue:23,78-79`、`conflictPresentation.ts` |
| `rejected` 状态恢复 | ❌ 无出边，永久堵死 | `engine.py:113` |
| 重同步 / resync 快照 | ❌ 全仓无端点 | — |
| 多页 pull | ⚠️ 有实现无测试 | `engine.py:239-258` |
| Automation 4 类触发器 + lease/fencing | ✅ 完整 | `engine.py:77-206` |
| 自动化动作权限 | ⚠️ 以用户全权执行，**完全不过 Agent scope** | `actions/service.py:114-151` |
| Agent Data Actions 原子性 | ✅ 业务行+outbox+日志同事务 | 同上 |
| Workspace 隔离 | ⚠️ 查询层强制，但 `BaseAdapter.find()` 例外 | `sync/service.py:115-118` |
| Desktop HTTPS 门禁 | ❌ 缺失（其他两个客户端有） | `core_connection.py:24-35` |
| 全局主题 / 外观 | ❌ 只存不生效，0 处 `setProperty` | `styles/main.css:11,16` |
| 移动可用性（安全区/48dp/返回栈） | ❌ 系统性缺失 | 24 处断点、0 处 safe-area |
| Android 构建 | ❌ 零起点 + 3 处硬阻断 | `lib.rs:241,292,304` |
| macOS 签名 / 公证 | ❌ 未做 | `tauri.conf.json` 无 signing |
| macOS / Android CI | ❌ 无 | `.github/workflows/ci.yml` 仅 7 job |

---

## 3. 路线图任务校准

| 任务 | 校准结论 |
| --- | --- |
| **062-01 架构审计** | ✅ **本文档即交付物**，可勾选 |
| 062-02 契约冻结 | 需要**加强**：单写文档无用，必须同时产出 `packages/contracts` 的可执行样例 + 三语言校验脚本进 CI，否则 070 必返工 |
| 062-03 模型对齐 | 需要**扩范围**：currency 列决策、时区月聚合缺陷修复、URL 规范化+唯一约束、`data_records` 租户列、REST snake_case 与 sync camelCase 命名统一 —— 这五项都是"改 schema"，不是"写文档" |
| 062-04 回归与迁移 | 需要**补夹具**：现有升级测试只覆盖 PostgreSQL、从 0008/0013/0015 起跑、无 v0.6.1 真实夹具；P0 是补齐多页 pull 与 cursor 失效用例 |
| 062-05 安全边界 | 需要**加决策**：Client 与 Device 身份是否合并（Android 否则要注册两次）、`BaseAdapter.find()` 修复、Desktop HTTPS 门禁、吊销传播与自愈 |
| **070-01 构建** | 必须**拆成 01a / 01b**：01a 纯代码（cfg 门控 + `tauri.android.conf.json`，不需 SDK，今天可做）；01b 装 SDK/NDK 后 `android init`。混成一步是最易踩的排期坑 |
| 071-06 Devices/Settings | 需处理**假实现**：存储统计从未拉取、清缓存固定文案、2FA 写死 disabled |
| 072-01 主题与组件 | 与现状差距最大的一条：不是"落地 tokens"，是**从零建立主题系统**（当前只有预览变量） |
| 路线图**缺失**的任务 | ① 通知投递通道（`080-04` 只写了需求）② 存储统计/API 用量/Webhook 面板（假实现）③ 共享 Modal 组件 ④ `scripts/ci-local.sh` 一条命令复现 CI ⑤ 文档归档（7 篇该进 `docs/archive/`） |

---

## 4. Top 风险（合并去重后）

| 级别 | 风险 | 影响 | 建议落点 |
| --- | --- | --- | --- |
| 🔴 P0 | **Android = 第二套后端**，Rust 数据层从零写，且 `sidecar` 模式在移动端完全不适用 | 070 全部 | 重估 070 工期；先做 01a |
| 🔴 P0 | **同步永久堵死**：rejected 无出边 / 脏数据阻塞 cursor / 无 resync | 用户数据"变砖" | 062-02 定契约，062-04 补测 |
| 🔴 P0 | **契约未冻**：无 currency、时区错位、URL 无唯一、Record 无租户列、命名分裂 | v0.7 返工 | 062-03 |
| 🔴 P0 | **身份双轨 + 安全裂缝**：Device/Client 不关联、Desktop 无 HTTPS 门禁、`find()` 绕过隔离、令牌无缝轮换 | 凭据泄露、越权 | 062-05 |
| 🟡 P1 | 主题与移动体验空壳（0 处 setProperty、触控 23–44px、无返回栈） | v0.7.2 全部 | 072-01/072-02 前置 |
| 🟡 P1 | 测试恰好漏掉失败路径；CI 无 macOS/Android/cargo | 质量不可控 | 062-04 |
| 🟡 P1 | 文档陈旧反向误导（core.md 83%、desktop.md 75%） | 新人/新会话误判 | 文档归档 |
| 🟡 P1 | 桌面可靠性：`journal_mode=delete`、`busy_timeout=0`、`studiolo.db` 0644、内置 sidecar 停在 0.5.6/0015、Cmd+Q 阻塞 20s | 数据损坏/升级错乱 | 062-04 / 090-05 |
| 🟢 P2 | 死代码与假实现：`sync/schemas.py` 无人引用、8 个死组件、`callsToday` 硬编码、webhook 在 workspace 行锁内同步 HTTP ≤30s | 维护成本 | 071 / 080 |
| 🟢 P2 | 无迁移降级路径演练；`DataRecord` 级联行为与另两类实体不一致 | 升级风险 | 090-02 |

---

## 5. 建议的下一步（按依赖排序）

1. **062-02 契约冻结**：先出 `packages/contracts/`（请求/响应/错误码/分页/幂等/删除/冲突/Cursor 失效），配 `scripts/check-contracts.sh` 做三语言校验，进 CI。
2. **062-03 模型对齐**：把第 4 节 P0 里"改 schema"的五项一次改完，赶在任何客户端接入之前。
3. **062-05 安全边界**：三条决策 + 一个修复（`find()`）+ 一个门禁（Desktop HTTPS）。
4. **070-01a**：纯代码 Android 就绪（cfg 门控、配置文件、编译错误收敛），不依赖 SDK，可并行进行。
5. **文档归档**：`core.md` / `desktop.md` 重写为"当前状态"，7 篇历史报告移入 `docs/archive/` 并加横幅。

---

## 附录：原始报告索引

| 报告 | 行数 | 主题 |
| --- | --- | --- |
| `01-core-api.md` | 198 | Core 结构、认证、设备身份、Workspace 隔离（15 缺口） |
| `02-sync-engine.md` | 216 | push/pull/cursor/幂等/冲突（13 缺口） |
| `03-local-backend.md` | 199 | Local Backend、sidecar、Tauri 桥接（9 缺口） |
| `04-frontend-map.md` | 219 | 前端地图、ConflictCenter、主题实现度（15 缺口） |
| `05-automation-agent.md` | 172 | Automation 引擎、Action 原子性、权限（17 缺口） |
| `06-tests-ci.md` | 129 | 测试与 CI 覆盖、最小回归集（8 条建议） |
| `07-schema-contract.md` | 206 | 迁移链、四实体字段契约（12 条冻结清单） |
| `08-doc-drift.md` | 156 | 44 条文档声明判定（25 陈旧 / 17 真未做 / 6 待定） |
| `09-android-readiness.md` | 192 | Android 前置环境与代码缺口（5 步最小动作） |
| `10-security-credentials.md` | 141 | 六类凭证、吊销、脱敏、HTTPS（16 风险） |
