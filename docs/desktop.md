# Nexa Desktop v0.5.6

## 安装与首次启动

使用本地构建或正式发布后的 Windows 10/11 x64 的 `Nexa_0.5.6_x64-setup.exe` 安装包并安装。从开始菜单启动 Nexa。桌面程序会自动启动随安装包提供的 FastAPI Backend，创建用户数据目录，生成随机密钥，执行 Alembic 迁移，并在 Backend 就绪后打开现有 Vue 登录/注册页面。用户无需配置 `.env`，也无需安装 Python、Node.js 或 Rust。

Windows 数据目录由 Tauri `app_data_dir()` 和稳定标识 `com.isidel.nexa` 决定，通常为 `%APPDATA%\com.isidel.nexa\`。可在资源管理器地址栏输入 `%APPDATA%\com.isidel.nexa` 查找。安装目录与数据目录分离，更新或重新安装程序不会覆盖数据库。目录内容：

```text
com.isidel.nexa/
├── nexa.db
├── secret.key
├── installation.id
├── core-connections/
│   └── <local-user-id>/
│       ├── connection.json
│       └── credential
└── logs/
    ├── backend.log
    └── desktop.log
```

`nexa.db` 保存用户数据，`secret.key` 保存首次启动生成的 256 位随机 JWT 密钥。`installation.id` 是本机安装实例的稳定 UUID，不是密钥或认证凭证；重新安装后沿用该文件可保留安装身份。Phase 3 加入 Core 后，每个本地用户可有一个 `core-connections` 子目录：JSON 只存连接元数据，`credential` 独立保存 Core 签发的 `nc_live_` bearer secret。请妥善备份用户数据与密钥，保护凭证文件；未来可迁至系统 Keychain。Backend 日志轮转保留最近文件。密码、Token 和密钥不写入常规日志。

目前可通过 Local Backend API `POST /api/v1/core/connect` 加入 Core，随后使用 `GET /api/v1/core/connection` 和 `POST /api/v1/core/connection/test` 查询与验证连接；`DELETE /api/v1/core/connection` 只删除本地连接，不撤销远端 Client，也不删除 Ledger、outbox 或游标。需要远端撤销时，用 Core 用户 JWT 调用 `POST /api/v1/clients/{id}/revoke`。公网 Core 必须通过 HTTPS 暴露。v0.5.6 可通过 `POST /api/v1/sync/run` 手动双向同步 Ledger、Websites 和 Data；`GET /api/v1/sync/status` 返回队列计数和安全诊断。Core 离线时本地读写照常可用，离线修改持久保存在 SQLite。冲突保留本地编辑，并持续刷新最新远端快照。后台同步、连接/同步 UI 与冲突解决 UI 尚未启用，Dashboard 等其他模块不参与同步。

如果 Core 已注册本安装实例，而本地连接尚未保存成功，重新提供 Core 用户名和密码执行 `connect` 可恢复：Local 会查找同一 `installation.id`，显式轮换 Core 凭证并保存新连接。已撤销的 Client 不会自动恢复。本地连接元数据使用 `schemaVersion: 1` 严格验证，凭证由 `FileCredentialStore` 保存；未来可迁移至系统凭证库。已有 `connection.json` 时，普通 `connect` 不会覆盖，即使凭证文件遗失；该修复场景留给后续专门的 Repair 流程。

## 窗口、托盘与退出

Windows 10/11 x64：点击窗口右上角 X 会隐藏窗口，Backend 继续运行。从系统托盘的 Nexa 图标选择“打开 Nexa”可以恢复；选择“退出 Nexa”才会退出桌面程序并停止 Backend。再次从开始菜单启动 Nexa 时只会聚焦已有窗口，不会启动第二个 Backend。

Backend 固定监听 `http://127.0.0.1:17800`，仅可从本机访问。`GET /api/health` 返回产品版本 `0.5.6`。远程 Device Client 和原有 OpenClaw Runtime Adapter 可连接可访问的 Core Runtime；OpenClaw Data Tools 必须连接对应 Nexa Local（本机插件可连接 127.0.0.1:17800）。Desktop 的 Local Backend 不直接暴露到局域网。

macOS Intel x86_64：目标为原生 traffic lights、红色关闭后保留本地 Backend、Dock 点击恢复窗口、Cmd+Q 或“退出 Nexa”停止 Backend。实机验证状态以 [macOS QA 报告](macos-local-client-2026-10-01.md) 为准；完成前不声明 macOS 支持验收通过。Apple Silicon 与 Universal Binary 尚未验证。

macOS 数据目录同样读取 Tauri `app_data_dir()`；本机实际返回 `~/Library/Application Support/com.isidel.nexa`，不要由平台名拼接路径。Unix 上数据目录为 0700，`secret.key` 和新建 Core credential 为 0600。

## 故障排查

- **Nexa 无法启动 / Backend failed to start**：打开 `%APPDATA%\com.isidel.nexa\logs\backend.log` 与 `desktop.log` 查看最近错误；确认安装文件完整后重启 Nexa。
- **Port 17800 already in use**：另一程序占用了本机 17800 端口。退出该程序或旧 Nexa 实例，再重新启动 Nexa。桌面版目前使用固定端口。
- **Database migration failed**：先退出 Nexa 并备份 `nexa.db` 与 `secret.key`，再查看 `backend.log` 中的迁移错误。不要直接删除数据库。
- **Backend 已停止**：窗口会显示不可用状态；从托盘退出并重新启动 Nexa。没有无限自动重启。

## Existing Web Installation Migration

Desktop 不会自动移动已有 Web 数据库。迁移前先关闭 Web Backend 和 Nexa，备份 `backend/nexa.db`，然后将副本复制到 `%APPDATA%\com.isidel.nexa\nexa.db`，再启动 Nexa。Alembic 会将旧版本升级到最新结构。用户账户和密码哈希随数据库迁移，可以用原用户名和密码登录。

Desktop 默认生成新的 JWT 密钥，因此旧浏览器中的登录 Token 不再有效，重新登录即可。如果必须保留已有 Token，先备份 Desktop 的 `secret.key`，再用原 Web 环境的 `JWT_SECRET` 值替换它；该值须至少 64 个字符，否则 Desktop 会拒绝启动。通常建议使用新生成的密钥并重新登录。

## 开发构建

Windows x64 需要 Rust stable、MSVC C++ 工具链与 Windows SDK；macOS Intel 需要 Rust stable 和 Xcode Command Line Tools。Web CI 使用 Node 22，涉及 OpenClaw 插件时使用 Node >=24.16.0 <25 或 >=26.1.0。Backend 推荐 Python 3.12，在仓库根目录创建 `.venv` 并安装 `backend/requirements.txt` 与 `pyinstaller>=6,<7`。Windows 不需要 Bash；macOS 不需要 PowerShell。

```text
npm ci
python -m pip install -r backend/requirements.txt 'pyinstaller>=6,<7'
npm run desktop:build
```

`desktop:prepare/dev/build` 使用 `scripts/desktop.mjs`，优先选择 repo `.venv`，或通过 `NEXA_PYTHON` 指定解释器。统一实现 `scripts/build-backend-sidecar.py` 使用同一 `backend/nexa-backend.spec`。target 优先级为显式 `--target`、`TAURI_ENV_TARGET_TRIPLE`、`rustc --print host-tuple`。PyInstaller 要求 Python 与目标平台/架构一致，不支持交叉编译；Apple Silicon 预留 target 参数，不代表已验证支持。

```text
npm run desktop:build:windows
npm run desktop:build:macos
npm run desktop:build -- --target x86_64-apple-darwin
python scripts/smoke-backend-sidecar.py --target x86_64-apple-darwin
```

Windows sidecar 为 `src-tauri/binaries/nexa-backend-x86_64-pc-windows-msvc.exe`，NSIS 输出在 `src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/`。兼容 PowerShell wrapper 仅调用统一 Python 实现。macOS sidecar 没有 `.exe`，拥有 executable bit；app/dmg 输出在 `src-tauri/target/x86_64-apple-darwin/release/bundle/`。

本机普通 DMG 构建在 Finder AppleScript 布局步骤发生 AppleEvent 超时。使用 Tauri 官方 CI 模式 `CI=true npm run desktop:build` 构建成功，跳过 Finder 镜像布局步骤，app 与 dmg 均生成；没有修改系统安全设置。`.app` 未签名，未 notarize，当前仅验证本机开发运行。

Tauri 2 自动合并 `tauri.windows.conf.json` / `tauri.macos.conf.json`。共享配置保留安全策略与外部 Backend；Windows 配置保留无边框窗口、NSIS 与 ICO；macOS 配置使用 decorations、Overlay 原生标题栏与 ICNS。JSON merge patch 会整体替换 windows 数组，因此平台配置需要完整窗口几何参数，调整时应保持与共享配置一致。

macOS shell 使用 36px 顶部空间与原生 AppKit 控件；Windows 使用现有 `DesktopTitleBar.vue`。平台由 Rust command 返回，不依赖 User-Agent。Desktop 禁止刷新/打印/保存/地址栏/源码快捷键：Windows Ctrl，macOS Cmd；保留剪贴板、撤销/重做与搜索。Web 保留浏览器布局与默认交互。

开发窗口可使用 `npm run desktop:dev`，它同样会先准备 sidecar。原有 Web 开发模式继续使用 `npm run dev` 与 `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`。Web 构建使用相对 `/api` 与 Vite proxy；Desktop 构建使用 `.env.desktop` 将 API 指向 `http://127.0.0.1:17800`。

## v0.5.5 数据升级

同步实体为 `ledger.category`、`ledger.transaction`、`website.category`、`website`、`data.collection`、`data.record`。首次启动升级至 `0015_agent_data_actions`（包含原有 0014 多实体迁移），保留原数据、Ledger revision、outbox、cursor 与安装身份。Local `queue_seed_version` 会继续为已完成 Ledger seeding 的旧库补入 Website/Data，父实体先于子实体推送。普通页面隐藏 tombstone；删除网站分类会清空网站分类引用，删除 Collection 会逻辑删除 Records。

Client 和 Core 必须同时使用 Sync Protocol v2；混合旧版同步会明确报错，queue/cursor 留存。手动 sync API 保持不变，连接元数据仍为 schemaVersion 1。Settings、Device、Agent、Automation 与 Dashboard 尚未同步；后台同步与冲突解决 UI 尚未实现。v0.5.6 已提供 Core Connection 和 Manual Sync UI，使用说明见下节。Settings 中可能跨设备共享的偏好与必须 Local-only 的连接/安全配置分类见 [Sync 说明](sync.md)。本版本可本地构建安装包，正式下载以随后单独发布的 Release 为准。

## v0.5.6 Core 连接与手动同步

Windows 与 macOS Local Client 可直接在 **设置 → 同步（Settings → Sync）** 中连接 Core、测试连接、断开连接、查看 Sync Status 和执行 Manual Sync，无需手工调用 Core API。

1. 准备 Core 账户，在未连接表单输入 Core 地址、Core 用户名、密码和设备名称。地址示例为 `https://core.example.com`；可信局域网开发环境也可用 `http://192.168.1.50:8000`。点击「连接 Core」。
2. 已连接卡片显示 Backend 保存的 Core 地址、设备名称、平台、客户端版本及连接时间。Client、Installation 和 Workspace ID 折叠在「技术信息」中。点击「测试连接」验证是否连接正常；无法访问或凭证失效会明确提示，不会自动重新注册设备。
3. 数据同步卡片显示真实 pending、conflicts、inFlight、rejected、cursor、上次成功时间和安全错误提示。点击「立即同步」运行一次同步，查看上传/接收数量及更新后的状态。存在冲突时会提示当前版本暂不支持在界面解决。
4. 「断开连接」需要确认：只移除这台设备保存的 Core 连接信息，不会删除本地数据，也不会自动撤销 Core 上的 Client。使用同一 Core 账户重连时，沿用 Backend 的安装身份恢复和凭证轮换逻辑；连接 UI 不重置 outbox 或 cursor，也不支持直接切换已绑定的 Core 身份。

Core 不可用时，Ledger、Website、Data 仍先写入本机 SQLite。未连接时也能查看 Local outbox，「立即同步」禁用；已连接但 Core 离线时，手动同步安全失败，数据和队列留存。恢复 Core 后测试连接并再次点击「立即同步」即可。本版本没有自动同步、定时同步、启动同步或网络恢复同步；旧 Settings 同步配置字段继续保留兼容，但不再作为真实 Core 连接配置展示。

连接密码只在表单/连接请求中短暂使用，提交时清空，离开页面也清空；不会保存至 Settings 或浏览器存储。Core 用户登录 Token 和 Client credential 由 Backend 管理，前端只接收公开连接元数据。Desktop 前端只调用 `127.0.0.1:17800` 的 Local API，由 Local Backend 访问 Core；无需改变 Tauri CSP 或允许 WebView 直连 Core。Docker 测试 Core 的 `127.0.0.1:8000` 与 Local 端口不同。

2026-10-02 的 Windows 实机结果见 [Core Sync UI 验收](core-sync-ui-2026-10-02.md)。macOS UI 沿用跨平台内容布局和现有平台检测，本次没有 macOS 实机 UI 验收。**Mac Local ↔ Real Core ↔ Windows Local 的真实两台设备双向同步仍是最终 Release Gate。**

## Agent Data Actions

v0.5.5 的 `0015_agent_data_actions` 为 Agent 添加默认空的 dataScopes 和持久化安全 Action receipts。已有 Agent 不自动授权。`/api/agent/actions/*` 只在 Nexa Local 可用，Core 返回 404；普通 Core CRUD 与 Runtime API 保持原有行为。业务服务与普通 REST 共享，Agent 业务写入与本地 outbox/audit 同事务提交，仍由用户手动 sync。安装、权限与幂等说明见 [Agent Data Actions](agent-data-actions.md)。

sidecar 默认固定 17800；测试可通过 `--port` 指定独立 loopback 端口，不占用正在运行的 Desktop。`scripts/smoke-backend-sidecar.py` 自动选择测试端口。
