# Nexa v0.5.6 macOS Local Client QA — 2026-10-01

状态：开发与本地验证进行中，尚未达到 `LOCAL COMPLETE`。以下只记录实际执行结果，未运行的项目不视为通过。

## 机器与基线

- Mac mini 2014，`Macmini7,1`，Intel Core i5 2.6 GHz / 2 cores，8 GB RAM。
- `uname -m`: `x86_64`；macOS 15.7.9 Sequoia，build `24G830`。
- 测试设备为 **OCLP macOS 15**，不是 Apple 官方支持硬件测试。安装的 OpenCore-Patcher 为 2.5.0；未修改 SIP、root patches 或 Gatekeeper。
- 源码：`~/Projects/Nexa-LumaDock`。开始时 Codex 工作目录为无提交、无远端的空仓库。
- `git fetch --all --tags --prune`、`checkout main`、`pull --ff-only` 后，HEAD 与 tag `v0.5.5` 均为 `42d2fd261a14f90b0337f2cfda8eb3cc6f1724de`，工作区 clean。
- 开发分支：`codex/v0.5.6-macos-local-client`。初始流程要求仅本地提交；2026-10-02 用户另行授权提交并推送 GitHub 开发分支，不创建 PR、tag 或 Release。

## 环境

- Xcode Command Line Tools：`/Library/Developer/CommandLineTools`；完整 Xcode 未安装。
- 系统 Node：24.21.0；开发复用已有 nvm Node 26.8.1；npm 11.19.0，满足锁定插件的 Node 条件。
- 初始 Python：系统 3.9.6、Homebrew 3.14.3；现通过用户目录内独立运行时安装 Python 3.12.14，repo 根目录 .venv，未替换系统 Python。
- Homebrew `python@3.12` 因 Intel 配置无 bottle 而失败，没有强行源码安装或替换系统 Python。
- Rust stable 1.98.1 / Cargo 1.98.1 / rustup 1.29.1；host 与 installed target 均为 x86_64-apple-darwin。官方下载发生 TLS 中断后重试成功，未使用不受信任镜像。
- Tauri CLI/API：2.12.0。修改前运行了 `npx tauri --version`、`npx tauri info`，并核对本地 `config.schema.json`。
- 初始真实 OpenClaw CLI/Gateway：2026.9.4 (`3a9d69d`)；10 月 1 日复核时均已为 2026.9.7 (`c074824`)，loopback 18789，connectivity probe ok；本任务没有执行 OpenClaw 本体升级。
- 仓库插件 SDK 固定 OpenClaw 2026.9.6；插件独立版本保持 0.1.0。
- GitHub 直连超时，开发命令复用系统已配置的 `127.0.0.1:7892` HTTP proxy；没有修改全局 Git / 系统代理。

## 实现

- 单一 FastAPI / SQLAlchemy / Alembic / SQLite / Agent Action / Sync 实现；没有创建 macOS Backend 副本。
- `scripts/build-backend-sidecar.py` 与 `desktop_target.py` 按显式 target、Tauri target 环境变量、Rust host 的优先级处理平台；PyInstaller 必须使用匹配的本机 Python，拒绝错误的架构标签。
- `scripts/desktop.mjs` 统一 npm Desktop 入口，并选择 repo `.venv` 或 `NEXA_PYTHON`。Windows PowerShell wrapper 保留；Windows 不依赖 Bash，Mac 不依赖 PowerShell。
- sidecar smoke 使用目标文件名；Windows 专用 creationflags / SystemRoot 只在 Windows 使用。原有 Agent replay、六实体 outbox、restart、persistence、迁移测试保留。
- Tauri 共享安全策略，Windows 配置保留 NSIS / custom titlebar / ICO，macOS 配置为 app/dmg、ICNS、decorations、Overlay 原生 traffic lights。
- 前端平台由微型 Rust command 提供，没有 User-Agent 判断；Mac 使用公共 36px 顶部 inset，没有 HTML 模拟 traffic lights。
- Cmd 浏览器快捷键按键过滤，保留剪贴板、undo/redo、Cmd+K 与 Cmd+Q。
- Rust macOS 使用已核对的本地 Tauri 2.12.0 crate 官方 Reopen 与 ExitRequested；保留 Windows close-to-tray。原生红色关闭、Dock reopen、Cmd+Q、单实例与重启身份持久化已在 release .app 验证。
- Unix 数据目录 0700，secret.key 新建/读取时 0600；Core credential 保留现有私有临时文件与原子替换实现。未做 Keychain migration。
- Mac WebView `tauri://localhost` 已加入 Desktop CORS；Backend 仍为 `127.0.0.1:17800`。
- 版本 0.5.6；未新增 migration，Alembic head 仍为 `0015_agent_data_actions`，Sync Protocol v2，queue seed/bootstrap version 2。

## 已执行验证

| 检查 | 实际结果 |
| --- | --- |
| root npm ci | PASS |
| locked plugin npm ci | PASS |
| Web frontend build | PASS |
| Desktop frontend build | PASS |
| Desktop shortcuts | 5 passed，包含 macOS Command 与原有 Windows Ctrl |
| Plugin build / metadata check / validate | PASS，锁定 SDK 2026.9.6 |
| Plugin tests | 13 passed |
| 真实 OpenClaw 2026.9.4 / 2026.9.7 plugin validate | valid=true，errors=[] |
| Browser interaction fixture | 48 passed；Web desktop/titlebar/macInset 均为 false |
| Web dev server | 已在 127.0.0.1:5173 启动 |
| Backend tests | 156 passed（148 基线 + 8 新增） |
| Rust release tests | 2 passed，x86_64-apple-darwin |
| Native sidecar build | PASS，Python 3.12.14 / PyInstaller 6.22.3 |
| Packaged sidecar smoke | PASS，原有全部业务/outbox/replay/restart 强度保留 |
| file | Mach-O 64-bit executable x86_64 |
| otool -L | 仅 Carbon / libSystem / libz / ApplicationServices / CoreFoundation / CoreServices 系统库，无开发虚拟环境路径 |
| Device Client tests | 20 passed |
| OpenClaw Runtime Adapter tests | 11 passed |
| Schema drift | PASS，29 static Action schemas |
| Python syntax / git diff --check | PASS |

## Release bundle 实机结果

- `npm run desktop:build` 生成 Nexa.app，但默认 DMG Finder 布局 AppleScript 超时（`Finder: AppleEvent timed out -1712`）。这属于 Tauri bundler 与本机 Finder 自动化交互问题；没有加入 OCLP-specific hack。
- `CI=true CARGO_BUILD_JOBS=2 npm run desktop:build` PASS，使用 Tauri 官方 CI 模式跳过 Finder 布局，生成 app 与 dmg。
- App：`src-tauri/target/x86_64-apple-darwin/release/bundle/macos/Nexa.app`，49.35 MiB。
- DMG：`src-tauri/target/x86_64-apple-darwin/release/bundle/dmg/Nexa_0.5.6_x64.dmg`，41.71 MiB；`hdiutil verify` checksum VALID。
- App 名称 Nexa、版本 0.5.6、ICNS 图标均位于 bundle。`codesign` 检查 .app 为未签名；没有 Developer ID 或 notarization，不宣称可正式公开分发。
- 关闭开发进程后以 `open Nexa.app` 独立启动成功，无 Vite、手动 FastAPI 或激活 .venv；Backend loopback health 0.5.6。
- 通过真实 WebKit UI 登录 QA 用户，Dashboard / Sidebar 正常，原生 traffic lights 与顶部 36px inset 避开内容，搜索提示 Cmd+K。
- 原生 AXCloseButton：关闭后 Backend health ok；点击 Dock Nexa 恢复主窗口。
- `open -n Nexa.app`：第二个 Nexa 进程短暂出现后退出，只保留原进程和 PyInstaller 的父/子 sidecar 对；没有第二个监听 Backend。
- 原生 Cmd+Q：Nexa 与 sidecar 退出，17800 不再监听；随后重新 open .app，health 恢复。
- Tauri 实际数据目录：`/Users/zjy/Library/Application Support/com.isidel.nexa`；SQLite 为同目录 `nexa.db`，Alembic 0015。
- data dir 0700、secret.key 0600、core-connections 0700；installation.id 0644（非敏感身份，受 0700 父目录保护）。真实 Core credential 尚未生成，文件权限实现已由 Backend 测试验证。
- 重启前后 installation.id / secret.key 的 SHA-256 比较相同（不记录内容或 hash），QA Agent 与 SQLite 数据保留。真实 Core connection 持久化仍待连接验收。
- 天气来源 Open-Meteo 链接通过 Nexa opener 打开 macOS 默认 Chrome，桌面日志确认 system open accepted。Website UI 真实打开 `https://example.com/?nexa=mac-qa#coffee`，Chrome tab URL 确认 query / fragment 完整；测试 URL 经真实 Agent typed update 保存、audit=ok。
- 真实 Gateway 已 link/enable nexa-tools；runtime inspect：loaded、30 tools、diagnostics=[]。doctor：没有 install-tree 问题，但现有 Codex 插件有 settings upgrade 警告，命令 exit 1。
- QA Agent `Nexa Mac QA`：ledger/websites/data 各 read/write 六个 scopes，无 delete；凭据位于仓库外 0700 目录、0600 文件，没有写入 Git 或 prompt。
- 真实自然语言 status 调用首次因 Gateway 连接中断未执行；后续发现既有 riri Agent 白名单只允许七项工具。通过官方 config set 增加 nexa-tools，保留原 allow / deny，未升级 Gateway 或扩大 Nexa scopes；之后真实 model status 调用成功。
- macOS App 菜单采用官方预定义 Quit / Edit 等行为，App 子菜单与 About / Hide / Quit 名称为 Nexa；实际 “Quit Nexa” 菜单退出后 17800 释放。
- Tauri dev 首次启动与真实 UI 登录通过；热重载曾留下旧 sidecar，已增加 macOS desktop owner PID 与 Unix 存活探测（signal 0 不发送信号），父进程消失后 Uvicorn 正常退出。Windows 启动参数与行为不变；同一 spec / Backend。
- 新增 packaged smoke：owner 自然退出后 sidecar exit 0，端口释放；原完整 smoke 仍通过。最终 `npm run desktop:dev` 热重载实际复核 PASS：源文件仅触碰 mtime 触发官方 watcher，旧 port 释放，新 owner / Backend health 恢复，只有一个 App。
- 实际左键与右键点击 status item：均显示“打开 Nexa / 退出 Nexa”；选“退出 Nexa”后 App、sidecar 退出，17800 释放。
- 完整 Backend 最终重跑：156 passed，143 warnings，314.89s；Rust release 2 passed；最终 app/dmg 重建 PASS，DMG checksum VALID；app 仍未签名。

## 真实 OpenClaw / Local SQLite / 离线写入

CLI / Gateway 2026.9.7，Agent riri，DeepSeek `deepseek-flash`，普通 `openclaw agent` 走真实 Gateway，未使用 `--local` 或向外发送消息。模型只用 typed tools 执行业务，未用 curl / 普通 REST / DB 写入替代。

| 自然语言 | 成功工具 / 验证 |
| --- | --- |
| 检查 Nexa 状态 | nexa_status：connected=true，Nexa Mac QA，0.5.6，六个 read/write scopes |
| 查看我的账本分类 | nexa_ledger_categories_list：ok，QA workspace 分类为空 |
| 记一笔咖啡 38 元 | nexa_ledger_transaction_create：ok，expense 38，未 replay |
| 把 https://example.com 保存到网站收藏 | nexa_website_create / get：收藏创建并回读 |
| 在 Mac QA Test 新增 Mac mini 2014 记录 | nexa_data_collections_list / record_create / record_get：model=Macmini7,1 |

- 咖啡 entity：`76452ddf-47da-4ced-ae51-fd70f3933d3b`；Website：`d171ac22-f1a3-487a-ae78-6e6dbebd8338`；DataRecord：`5c067760-dbd9-49b1-bdb1-b5b4f0e48fcb`。这些是 QA 业务标识，用于后续跨设备匹配，不是 bearer 凭据。
- SQLite 查证三项 write audit 均 status=ok，action_id、target_entity_id 与持久化 result_summary receipt 存在。
- Core 尚未连接，三项业务写入仍成功。pending outbox：data.collection / data.record / ledger.transaction / website 各一条；未自动 sync。
- queue payload 不含 userId / workspaceId / clientId ownership；实际不同 Core UUID 的设备 E2E 仍未运行。
- 独立 .app Ledger 显示支出 ¥38.00、余额 -¥38.00、1 笔交易；交易 Modal 实测避开 traffic lights。受控临时 loopback listener 占用 17800 后，Error 页显示端口已占用并提供重试，内容避开 traffic lights；随后通过原生 Cmd+Q 退出并关闭测试 listener。
- 执行真实 Cmd+R / Cmd+Shift+R 后 Ledger 页面保留；内部滚动已操作。

## 待验证与限制

- 真实 Core credential 权限与 Core connection 重启持久化。
- Login / Dashboard / Ledger / Modal、原生 App menu Quit、status item 左/右键与退出、最终 dev 热重载均已验证。受控占用端口触发的 Error 页也已验证避开 traffic lights。
- Website 与天气来源 opener 已通过；query / fragment 已在默认浏览器验证，非法 URL 的 Rust tests 已通过。
- 三项自然语言业务写入、状态与 audit / receipt 已通过；Core 未连接时 Local-first 已通过，恢复 Core 后的传输验收仍待真实 Core。
- Core URL 与 Windows 设备操作方式尚未由用户提供。Mac → Core → Windows、反向同步、真实设备身份隔离与离线恢复不能以 API/unit tests 冒充。
- Windows packaged regression not run on Mac。
- 尚未添加 macOS CI：按任务约定，须本地 Mac 验证完成后再决定；远端 CI 未运行。
- Apple Silicon、Universal Binary、Developer ID signing、notarization、updater 不在本轮验收范围。

仍不标记 LOCAL COMPLETE。2026-10-02 用户另行要求提交代码到 GitHub，授权提交并推送当前开发分支；Core / Windows / 离线恢复验收保持待完成。

Sidecar 路径：`src-tauri/binaries/nexa-backend-x86_64-apple-darwin`，可执行权限已验证。构建命令：`.venv/bin/python scripts/build-backend-sidecar.py --target x86_64-apple-darwin`；烟测：`.venv/bin/python scripts/smoke-backend-sidecar.py --target x86_64-apple-darwin`。后续构建复用 PyInstaller 的依赖缓存，必要时可加 `--clean`。

## Git 提交与外部设备验收状态（2026-10-02 更新）

- Branch：`codex/v0.5.6-macos-local-client`。
- 开发基线：`42d2fd261a14f90b0337f2cfda8eb3cc6f1724de`；用户已授权将本轮实现提交并推送该开发分支，提交 SHA 以 Git 日志为准。
- 本轮实现涉及 33 个文件，包含新增文件与 ICNS binary；最终 diff stat 以提交为准。
- git diff --check PASS；真实 QA password / JWT / Agent token / secret.key 匹配扫描：Git 与 Nexa logs 均无泄露。
- .venv / node_modules / target / backend build/dist / .app / dmg / QA 数据与截图均未纳入提交。
- 本次提交记录已完成的 Mac 本机实现和验证；真实 Core / Windows / 离线恢复验收仍待完成，不能据此标记 LOCAL COMPLETE。
- 本次发布范围仅为开发分支代码；不创建 PR、tag 或 GitHub Release。
