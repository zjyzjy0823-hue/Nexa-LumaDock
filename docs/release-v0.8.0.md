# Studiolo v0.8.0 — Android Local-first、共享空间离线同步与 Agent Fleet 完善

- **发布基线**：`v0.7.0` 之后 31 个提交（15 feat / 9 fix / 4 docs / 2 ci / 1 test）
- **重点领域**：Android Local-first MVP（Websites 垂直切片）、Shared Space 三档协作 + 离线同步/冲突选版、Agent Fleet 的 Hermes 接入、统一 Cron 控制台、Theme Engine

---

## 一、主要新增

### 1. Android Local-first（Websites 垂直切片）
- 新增独立纯 Rust crate `studiolo-local-core`：SQLite（sqlx bundled）+ 本地迁移 + Websites 仓储 + Outbox 同事务提交 + CredentialVault（Android Keystore / InMemory）+ Sync v3 客户端。
- Android 原生壳（`LocalCorePlugin.kt` / `AndroidNotifications.kt`）把 Websites 与同步走 `invoke()`，其余页面仍直连 Core。
- 首次启动直连 Core、配对与凭据存 Keystore；`scripts/android-prepare.mjs` 负责工程生成、Kotlin 插件、启动图标与网络安全配置。
- CI 新增 `android.yml`：`cargo test`（本地核心）+ `tauri android build --apk --target aarch64 --debug` 出包。

### 2. Shared Space 三档协作 + 离线同步
- 密码学契约 v1（TS/Python 跨语言向量验证）、三档数据模型（0021 迁移）、API、Token 与审计、Agent 只读白名单。
- 三档共享工作台 UI、按次输密门禁。
- 新增 Core 侧同步候选表（`0023_space_sync_candidates`）与离线编辑/删除合并：`/spaces/{id}/sync`、`/sync-conflicts`、`/sync-snapshot`、`/sync-conflicts/{cid}/resolve`。
- 桌面端 offline replica + outbox，冲突在客户端选「保留本地 / 保留远端」后回传 Core。

### 3. Agent Fleet 完善
- Hermes 一并接入 Fleet：会话列表分组、模型列表（60 个模型）与按轮切换模型、逐模型思考档位（取自 ACP `configOptions` 的 `none … ultra` 八档）。
- 桌面端可独立登录 Core Fleet；Android 首次启动直连 Core。
- Codex 续聊、图片附件预览修复；Agent 推流与 MCP 错误隔离。

### 4. 统一 Cron 控制台与调度
- 三所有者（OpenClaw / Hermes / Core）统一 Cron 控制台，聚合调度 API、脱敏与防重调。
- 单所有者 CronPort（`v0.7.2` 收口部分）。

### 5. 其它
- Theme Engine 注册表、无障碍降级防线与对比度验收。
- 订阅额度查询、Core 用量统计、手机首页卡片。
- 对话正文段落间内联图片/文件卡片、五款气泡主题、移动端会话体验优化。

## 二、修复

- `fix(agent-node)`：ACP 子进程静默退出后自动重建；`Failed` 帧不再是无因空白（`node_execution_error` 现在带原因）。
- `fix(fleet)`：Hermes 模型行补齐 `efforts`，避免会话视图整块白屏。
- `fix(agent-node)`：Hermes 适配器声明 `models` 能力，模型面板不再被前端门禁关掉。
- `fix(space)`：空间条目增删后刷新卡片计数。
- `fix(agent-node)`：强制校验 OpenCode 会话目录位于 `allowedRoots` 内。
- `test(backend)`：迁移测试不再写死 head 版本号（新增迁移不会再让 11 个升级测试集体变红）。

## 三、升级说明

- **Core**：拉取后 `docker compose -f docker-compose.core.yml up -d --build`，Alembic 自动升到 `0023_space_sync_candidates`；本次新增表均为增量，无破坏性变更。
- **桌面端**：覆盖安装即可，SQLite 与日志仍在 `~/Library/Application Support/com.isidel.studiolo`（Windows：`%APPDATA%\com.isidel.studiolo`）。
- **Android**：需重新安装 APK（签名/包名不变，`com.isidel.studiolo`）；首次启动需登录 Core 或配对。
- **共享空间**：Core 需配置 `STUDIOLO_VAULT_MASTER_KEY` 等环境变量（见 `docs/core.md`）。

## 四、验证状态（发布前必须读完）

| 项目 | 状态 |
| --- | --- |
| 后端全量 pytest | 通过（迁移测试已改为动态 head） |
| 契约校验（Python / Node / Rust） | 通过 |
| 前端构建（web + desktop） | 通过 |
| macOS x86_64 打包 + 安装冒烟 | 通过 |
| Android arm64 APK + 真机安装 | 见发布说明后续补充 |
| 真机跨设备项（离线恢复 / 后台同步 / 冲突中心 / 保留本地 / 保留远端） | 需真机复核，结果记录在发布 PR 评论 |
| Windows x64 安装包 | 本次不在本机产出（需 CI 或 Windows 机器） |

> 本版本按语义化版本记为 **0.8.0**：包含 Android Local-first、Shared Space 离线同步等成块新能力，而不是修补集。
