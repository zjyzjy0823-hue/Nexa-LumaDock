# Nexa Desktop v0.5.4

## 安装与首次启动

使用本地构建或正式发布后的 Windows 10/11 x64 的 `Nexa_0.5.4_x64-setup.exe` 安装包并安装。从开始菜单启动 Nexa。桌面程序会自动启动随安装包提供的 FastAPI Backend，创建用户数据目录，生成随机密钥，执行 Alembic 迁移，并在 Backend 就绪后打开现有 Vue 登录/注册页面。用户无需配置 `.env`，也无需安装 Python、Node.js 或 Rust。

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

目前可通过 Local Backend API `POST /api/v1/core/connect` 加入 Core，随后使用 `GET /api/v1/core/connection` 和 `POST /api/v1/core/connection/test` 查询与验证连接；`DELETE /api/v1/core/connection` 只删除本地连接，不撤销远端 Client，也不删除 Ledger、outbox 或游标。需要远端撤销时，用 Core 用户 JWT 调用 `POST /api/v1/clients/{id}/revoke`。公网 Core 必须通过 HTTPS 暴露。v0.5.4 可通过 `POST /api/v1/sync/run` 手动双向同步 Ledger、Websites 和 Data；`GET /api/v1/sync/status` 返回队列计数和安全诊断。Core 离线时本地读写照常可用，离线修改持久保存在 SQLite。冲突保留本地编辑，并持续刷新最新远端快照。后台同步、连接/同步 UI 与冲突解决 UI 尚未启用，Dashboard 等其他模块不参与同步。

如果 Core 已注册本安装实例，而本地连接尚未保存成功，重新提供 Core 用户名和密码执行 `connect` 可恢复：Local 会查找同一 `installation.id`，显式轮换 Core 凭证并保存新连接。已撤销的 Client 不会自动恢复。本地连接元数据使用 `schemaVersion: 1` 严格验证，凭证由 `FileCredentialStore` 保存；未来可迁移至系统凭证库。已有 `connection.json` 时，普通 `connect` 不会覆盖，即使凭证文件遗失；该修复场景留给后续专门的 Repair 流程。

## 窗口、托盘与退出

点击窗口右上角 X 会隐藏窗口，Backend 继续运行。从系统托盘的 Nexa 图标选择“打开 Nexa”可以恢复；选择“退出 Nexa”才会退出桌面程序并停止 Backend。再次从开始菜单启动 Nexa 时只会聚焦已有窗口，不会启动第二个 Backend。

Backend 固定监听 `http://127.0.0.1:17800`，仅可从本机访问。`GET /api/health` 返回产品版本 `0.5.4`。远程 Device Client 和 OpenClaw Adapter 需要连接可访问的 Core Runtime；Desktop 的 Local Backend 不直接暴露到局域网。

## 故障排查

- **Nexa 无法启动 / Backend failed to start**：打开 `%APPDATA%\com.isidel.nexa\logs\backend.log` 与 `desktop.log` 查看最近错误；确认安装文件完整后重启 Nexa。
- **Port 17800 already in use**：另一程序占用了本机 17800 端口。退出该程序或旧 Nexa 实例，再重新启动 Nexa。桌面版目前使用固定端口。
- **Database migration failed**：先退出 Nexa 并备份 `nexa.db` 与 `secret.key`，再查看 `backend.log` 中的迁移错误。不要直接删除数据库。
- **Backend 已停止**：窗口会显示不可用状态；从托盘退出并重新启动 Nexa。没有无限自动重启。

## Existing Web Installation Migration

Desktop 不会自动移动已有 Web 数据库。迁移前先关闭 Web Backend 和 Nexa，备份 `backend/nexa.db`，然后将副本复制到 `%APPDATA%\com.isidel.nexa\nexa.db`，再启动 Nexa。Alembic 会将旧版本升级到最新结构。用户账户和密码哈希随数据库迁移，可以用原用户名和密码登录。

Desktop 默认生成新的 JWT 密钥，因此旧浏览器中的登录 Token 不再有效，重新登录即可。如果必须保留已有 Token，先备份 Desktop 的 `secret.key`，再用原 Web 环境的 `JWT_SECRET` 值替换它；该值须至少 64 个字符，否则 Desktop 会拒绝启动。通常建议使用新生成的密钥并重新登录。

## 开发构建

Windows x64 开发环境需要 Node.js 22、Python 3.12、Rust stable、MSVC C++ 工具链与 Windows SDK。标准生产构建路径：

```powershell
npm ci
python -m pip install -r backend/requirements.txt
npm run desktop:build
```

构建脚本检查或安装 PyInstaller，将 `backend/desktop_entry.py` 打包为 `nexa-backend.exe`，并自动复制为 Tauri `externalBin` 要求的 `src-tauri/binaries/nexa-backend-x86_64-pc-windows-msvc.exe`。Tauri 随后构建前端和 NSIS 安装包，输出在 `src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/`。

开发窗口可使用 `npm run desktop:dev`，它同样会先准备 sidecar。原有 Web 开发模式继续使用 `npm run dev` 与 `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`。Web 构建使用相对 `/api` 与 Vite proxy；Desktop 构建使用 `.env.desktop` 将 API 指向 `http://127.0.0.1:17800`。

## v0.5.4 数据升级

同步实体为 `ledger.category`、`ledger.transaction`、`website.category`、`website`、`data.collection`、`data.record`。首次启动升级至 `0014_multi_entity_sync`，保留原数据、Ledger revision、outbox、cursor 与安装身份。Local `queue_seed_version` 会继续为已完成 Ledger seeding 的旧库补入 Website/Data，父实体先于子实体推送。普通页面隐藏 tombstone；删除网站分类会清空网站分类引用，删除 Collection 会逻辑删除 Records。

Client 和 Core 必须同时使用 Sync Protocol v2；混合旧版同步会明确报错，queue/cursor 留存。手动 sync API 保持不变，连接元数据仍为 schemaVersion 1。Settings、Device、Agent、Automation 与 Dashboard 尚未同步；后台同步、Sync UI 和冲突解决 UI 尚未实现。Settings 中可能跨设备共享的偏好与必须 Local-only 的连接/安全配置分类见 [Sync 说明](sync.md)。本版本可本地构建安装包，正式下载以随后单独发布的 Release 为准。
