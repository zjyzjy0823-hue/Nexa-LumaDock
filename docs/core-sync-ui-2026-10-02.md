# v0.5.6 Core Connection + Manual Sync UI — 2026-10-02

本次在 Windows 本机继续 `codex/v0.5.6-macos-local-client`。fetch 后远端基线为 `898ee82c63d8e63e5bdbe1bdf91dcfb88832ae25`。只补前端 API、状态逻辑和 Settings Sync UI；Backend、Sync Protocol v2、Alembic `0015_agent_data_actions`、queue seed 2、产品版本 0.5.6、Tauri CSP 和平台 shell 均未修改。开发、测试后仅本地提交，不 push、创建 PR、merge、tag 或 Release。

## 实现

- `src/api/core.ts`：公开连接联合类型、平台和请求类型，connect/get/test/disconnect；复用现有 apiRequest 和 Local User JWT。
- `src/api/sync.ts`：根据实际 Backend 定义 status/run 类型和接口。
- `src/composables/useCoreSync.ts`：页面进入及操作后的状态加载、互斥操作、断开确认、真实手动同步和结果；无定时轮询。401 调用现有 auth.restore 判断 Local 登录是否过期，Core 登录失败不会误登出 Local 用户。
- `src/services/coreSyncErrors.ts`：允许列表映射已知 Backend 错误，未知响应不原样展示。
- `src/components/settings/SyncSettings.vue`：Core Connection + Data Sync 两张 Glass 卡片，未连接表单、连接元数据、技术信息、测试状态、统计、时间、安全错误和最近同步结果。
- `src/pages/SettingsPage.vue`：移除用 Settings refresh 冒充同步的 syncNow；保留旧 Settings 导入/导出 schema，连接元数据不写入 settings_json。
- `tests/core-sync.test.mjs` / `npm run test:core-sync`：真实 Vue composable 和 API helper 的请求/状态测试。

## Windows UI + 真实 Docker Core

运行 `npm run desktop:dev`，使用本次创建的独立测试账户，在 Windows Nexa WebView 真实点击操作。Docker 使用仓库 `docker-compose.core.yml`；Core 为 `127.0.0.1:8000` + PostgreSQL 16，Local sidecar 为 `127.0.0.1:17800` + SQLite。API 仅用于准备测试账户和读回结果；connect、connection test、sync、disconnect、重连及本地业务数据创建均通过 UI。

| 验收步骤 | 真实结果 |
| --- | --- |
| 未连接 Sync 页面 | 显示 Core 地址、用户名、密码、Nexa Windows 默认设备名；状态可加载，立即同步禁用 |
| UI 连接 Core | connected=true，显示 Windows / 0.5.6 / 连接时间；主界面隐藏密码表单 |
| UI 测试连接 | 连接正常 |
| UI 本地写入 | Ledger transaction 1、Website 1、Data collection 1、Data record 1；pending=4 |
| 首次 UI 手动同步 | 上传 4、接收 4，pending=0，cursor=4，lastSuccessAt 更新，conflicts/inFlight/rejected=0 |
| Core 实际数据 | API 读回 Ledger/Website/Collection 均为 1，集合的记录已同步 |
| 停止 Docker Core/PostgreSQL | Local UI 新建 Ledger 成功；本地 Ledger=2，pending=1 |
| 离线 UI 立即同步 | 同步未完成，上传 0、接收 0；安全显示「无法连接 Core」，lastError=unreachable，pending=1，cursor=4，成功时间保持不变 |
| 恢复 Core | UI 测试连接恢复正常 |
| 恢复后 UI 立即同步 | 上传 1、接收 1，pending=0，cursor=5，lastError=null，成功时间更新 |
| UI 断开 | 显示准确确认文案，确认后 connection={connected:false}；Ledger 2 / Website 1 / Collection 1 保留，Core Client 未撤销 |
| 错误 Core 密码 | UI 明确提示用户名或密码不正确，密码框清空，Local 登录保持 |
| UI 重连 | connected=true，Client ID / Installation ID / Workspace ID 与首次连接相同；再次测试连接正常 |
| Windows shell 交互 | 自定义标题栏正常；关闭到托盘后窗口隐藏、进程保留，再次启动唤回原窗口，进程 PID 相同、仅一个实例 |
| 外部浏览器 | UI 点击测试 Website，链接交给 Microsoft Edge，Nexa 保持在网站页面 |
| 最后一次 UI 同步 | Website 访问产生 1 条修改；上传 1、接收 1，最终 pending=0、cursor=6；Core Data record=1 |

连接/同步操作按钮在 invocation 期间禁用；成功和失败返回均刷新 Local status。手动同步结果不会用 Settings refresh 替代。组件只保存短期表单状态，未连接时 Local pending 仍可查看。

## 回归与构建

| 检查 | 结果 |
| --- | --- |
| 根目录 npm ci | PASS，0 vulnerabilities |
| npm run build / build:desktop | PASS，TypeScript + Vite |
| npm run test:desktop | 5 passed |
| npm run test:core-sync | 6 passed：Local outbox、连接/API/确认、重复点击、离线失败重试、Core 401/Client 失效、Local JWT 过期和安全错误 |
| Windows Backend python -m pytest -q | 155 passed, 1 skipped；唯一 skip 是已有 Unix process ownership 测试 |
| Linux Docker Python 3.12 Backend 全量 pytest | 156 passed；在容器中补齐仓库测试和依赖源码后运行 |
| Device | 20 passed |
| OpenClaw Runtime | 11 passed |
| OpenClaw Plugin npm ci / build / plugin:build / validate / test | PASS，valid=true，13 passed；使用仓库已有 Node 24.16.0。系统 Node 24.13.0 不符合 OpenClaw 要求 |
| export-agent-tools.py --check | PASS，29 static Action schemas |
| npm run desktop:build | PASS，Windows x64 NSIS |
| smoke-backend-sidecar.py | PASS，六实体 offline outbox、Agent scopes/create/replay/audit、tombstone、持久化和登录 |

安装包：`D:\xiangmu\LumaDock\src-tauri\target\x86_64-pc-windows-msvc\release\bundle\nsis\Nexa_0.5.6_x64-setup.exe`（约 41.61 MiB）。安装包、sidecar、target、node_modules、数据库、环境文件和运行日志均为本地忽略产物，不进入提交。

密码提交前从 ref 清空，请求结束和组件卸载再清空；没有 Settings/Pinia/browser storage 写入路径。实机 API 读回确认 Settings 不包含测试密码或 Core URL，公开元数据不包含密码、登录 Token 或 Client credential；本机 Backend 日志也没有测试密码和测试 Token。Core 元数据类型不包含秘密字段，所有连接请求只到 Local Backend。Tauri CSP、Windows/macOS shell、sidecar lifecycle、OpenClaw Runtime、同步架构及迁移均保持原实现。

## 限制

本次没有 macOS 实机 UI 测试，没有真实 Mac 与 Windows 双设备双向验收。连接恢复继续由现有 Backend 负责；不自动修复失效 Client，不支持切换已绑定的 Core 工作区、不做后台同步或冲突解决。Windows 本机构建使用 Python 3.14.3，会出现既有依赖弃用警告；构建和 smoke 成功。macOS signing/notarization/Universal binary/新增 CI 均不在本次范围。

最终状态为 **v0.5.6 CORE SYNC UI COMPLETE**；最终 Release Gate 仍为 **Mac Local ↔ Real Core ↔ Windows Local** 实机双向同步。此记录不表示 v0.5.6 已发布。
