# Studiolo v0.8.0 — 设备免二次登录、共享空间离线同步与 Chat 恢复

- **发布基线**：`v0.7.0` 之后 **43 个提交**（20 feat / 11 fix / 5 docs / 2 test / 2 ci / 1 release / 1 chore / 1 merge）
- **重点领域**：设备免二次登录读共享空间、Shared Space 三档协作 + 离线同步/冲突选版、Chat 历史恢复与移动端 Inbox、Android Local-first MVP、Agent Fleet 的 Hermes 接入、统一 Cron 控制台、Theme Engine

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
- Hermes 回放保留思考与工具调用，正在运行时也能读取上下文。客户端为已打开的会话提供加密离线历史与待发队列。消息重连后以原命令 ID 重发。
- 已配对的桌面和 Android 设备可读取获授权的 standard 空间。空间所有者可管理设备授权，并查看设备访问审计。

### 4. 设备免二次登录读共享空间

- Core 新增 `/api/v1/client/space-reads/*`（status / spaces / space / entries / entry / download / chunk），**只认设备凭据**，已配对设备不必再登录 Core 账号。
- 授权：`space_device_grants` 显式授权，或「本人工作区 + standard 档」默认授权（`STUDIOLO_SPACE_DEVICE_DEFAULT_GRANT` 可关）。
- **只读且只限 standard**；`protected` / `e2ee` 仍必须登录 Core。设备凭据直访 `/api/v1/spaces` 一律 403（有回归测试锁定）。
- 本机后端新增代理 `/api/v1/core/space-reads/*`：固定路径模板、UUID 校验、HTTPS/回环门禁、禁重定向、64KB 流式下载、日志屏蔽上游 URL。
- 客户端进入「设备只读」模式：隐藏写入口，顶部提示「设备只读 · 登录 Core 后可编辑」，开关关闭时自动回退登录墙。
- Core 开关 `STUDIOLO_SPACE_DEVICE_READS`（默认关）。

### 5. 统一 Cron 控制台与调度
- 三所有者（OpenClaw / Hermes / Core）统一 Cron 控制台，聚合调度 API、脱敏与防重调。
- 单所有者 CronPort（`v0.7.2` 收口部分）。

### 6. 其它
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

- **Core**：拉取后 `docker-compose -f docker-compose.core.yml up -d --build`（本机没有 `docker compose` 插件，用独立 `docker-compose` v2.24），Alembic 自动升到 `0023_space_sync_candidates`；本次新增表均为增量，无破坏性变更。**升完务必确认容器内的 Fleet 事件白名单是 46 项**——旧容器会静默丢弃 `RunStopStatus` / `DuplicateIgnored` / `TerminalPreview`。
- **设备免登录**：需要 Core 环境变量 `STUDIOLO_SPACE_DEVICE_READS=true`（默认关闭；关闭时客户端回退到「登录 Core」）。
- **桌面端**：覆盖安装即可，SQLite 与日志仍在 `~/Library/Application Support/com.isidel.studiolo`（Windows：`%APPDATA%\com.isidel.studiolo`）。
- **Android**：需重新安装 APK（签名/包名不变，`com.isidel.studiolo`）；首次启动需登录 Core 或配对。
- **共享空间**：Core 需配置 `STUDIOLO_VAULT_MASTER_KEY` 等环境变量（见 `docs/core.md`）。

## 四、验证状态（发布前必须读完）

以下结果均来自 `d10e74f` + 两个修复提交上的真实执行，不是推断。

| 项目 | 状态 |
| --- | --- |
| 后端全量 pytest | **551 passed, 1 skipped**（11m58s，迁移测试已改为动态 head） |
| 契约校验（Python / Node / Rust） | **通过**：`cases=35 valid=13 schema-invalid=13 semantic=9`（Python + Node 一致）；Rust **27 passed** |
| 前端构建（web + desktop） | **通过**（`ci-local.sh` 只覆盖 web，desktop 需单跑 `npm run build:desktop`，两者均 exit 0） |
| 前端单测（9 套件） | **123 passed, 0 failed**；`vue-tsc --noEmit` exit 0 |
| agent-node 单测 | **25 passed**（含新增 `test_daemon_failed_frame.py`） |
| Chat 端到端（3 provider） | **通过**：列表 hermes 13 / opencode 41 / codex 15；历史加载全通；新建会话发「收到」首字 7.4s / 4.9s / 23.2s |
| Chat 并发保护 | **通过**：第二条 prompt 0.14s 收到 `Failed: 当前会话已有任务运行中` |
| Chat 取消 | **通过**：三家 provider 均秒回 `RunStopStatus status=accepted`（0.13s / 0.32s / 1.64s），物理停止有效 |
| 共享空间设备只读矩阵 | **通过**：本地 + 公网均 `status=ready`、只列 standard、`/api/v1/spaces` 403、不存在 404、protected 对设备 404、审计 `device.read` 落库（含 denied）、临时空间已清理 |
| macOS 安装包 | CI 产出 x64 / aarch64 DMG，SHA256 与 CI 记录一致，挂载后 `CFBundleShortVersionString = 0.8.0` |
| Windows x64 安装包 | CI 产出 NSIS `Studiolo_0.8.0_x64-setup.exe`（39 MB） |
| Android arm64 APK | CI 产出 `versionName=0.8.0` / `versionCode=8000` / `com.isidel.studiolo`；本机 vivo V2111A 已装 0.8.0 并连 Core（0 冲突） |
| 真机跨设备项（离线恢复 / 后台同步 / 冲突中心 / 保留本地 / 保留远端） | **未执行**，待真机复核后补 Record |

**发布前发现并修复的两个缺陷**（已包含在本 tag 内）：

1. `agent-node/agent_node/daemon.py` 缺模块级 logger，三处 `log.exception` 抛 `NameError`，导致所有 RPC 级 `Failed` 帧发不出去（客户端表现为“发消息没反应”）。已补 `_LOG` 并新增回归测试。
2. Core 容器白名单落后仓库 3 个事件（`RunStopStatus` / `DuplicateIgnored` / `TerminalPreview`），取消回执被静默丢弃。已重建 Core（46 事件），取消回执恢复。

**已知限制**（不阻塞发布）：

- `session.delete` 对 hermes 为空实现，删除后会话仍在列表（不影响使用，待补）。
- 会话整理（置顶/暂缓/归档）只在移动端收件箱生效，桌面侧栏会话树未接入。
- 历史回放只带 `role/text`（+ hermes/opencode 的 `parts`），工具调用与思考过程仅实时可见。

> 本版本按语义化版本记为 **0.8.0**：包含 Android Local-first、Shared Space 离线同步等成块新能力，而不是修补集。
