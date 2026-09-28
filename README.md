# Nexa Desktop — Nexa-LumaDock v0.5.1

Nexa 是 Windows 10/11 x64 桌面个人控制中心。安装后从开始菜单打开 **Nexa**，桌面窗口、FastAPI Backend 和 SQLite 会自动启动；关闭窗口后驻留系统托盘。普通用户无需安装 Python、Node.js 或 Rust。现有 Dashboard、Websites、Devices、Agents、API Keys、Settings、Data、Automation 工作流和 Ledger 均保留。

v0.5.2 Phase 1 开始提供独立的 PostgreSQL Nexa Core 运行基础，见 [Core 开发说明](docs/core.md)。Desktop 与 Core 当前没有数据同步。

## Nexa Desktop

推荐个人用户使用 [Windows 安装包](https://github.com/zjyzjy0823-hue/Nexa-LumaDock/releases)。首次启动会在用户 AppData 中创建数据库和密钥，随后直接显示登录/注册页。点击窗口右上角 X 会隐藏窗口；从托盘选择“打开 Nexa”恢复，选择“退出 Nexa”会同时停止 Backend。安装、数据位置、故障排查与已有 Web 数据迁移见 [Desktop 使用说明](docs/desktop.md)。Desktop 的本地 Backend 只监听 `127.0.0.1:17800`；跨设备能力将在后续阶段处理。

开发者在 Windows x64 上安装 Node.js 22、Python 3.12、Rust stable 与 MSVC 工具链后，可运行：

```powershell
npm ci
python -m pip install -r backend/requirements.txt
npm run desktop:build
```

安装包位于 `src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/`。该命令自动打包 Python sidecar、构建 Vue UI 和生成 NSIS 安装包。`npm run desktop:dev` 启动 Tauri 开发窗口；详情见 Desktop 使用说明。

## Web Development

现有 Web 开发模式仍受支持。前端使用 Vue 3、TypeScript、Pinia 和 Vite；后端使用 FastAPI、SQLAlchemy 2、Alembic 和 JWT。

### 开发启动

需要 Node.js 和 Python 3.11+。在 `backend` 目录复制 `.env.example` 为 `.env`，将 `JWT_SECRET` 改为随机长字符串。`.env` 已被 Git 忽略。

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

在另一终端从仓库根目录运行：

```powershell
npm ci
npm run dev
```

打开 `http://127.0.0.1:5173/`。首次进入会显示登录与注册页，只需设置用户名和密码。登录后可从侧边栏头像菜单退出；首页问候语使用当前用户名。网站、设备、智能体、设置、数据集合、工作流和账本的更改在刷新浏览器后仍会保留。前端将 `/api` 代理到本地后端。接口文档位于 `http://127.0.0.1:8000/docs`。

## 项目结构

```text
Nexa/
├─ src/
│  ├─ pages/           各业务页面
│  ├─ components/      通用 UI、布局和首页组件
│  ├─ stores/          Pinia 状态与页面操作
│  ├─ services/        前端业务 API 封装
│  ├─ api/             HTTP 客户端
│  ├─ types/           TypeScript 数据类型
│  ├─ mock/            静态选项与触发器模板
│  └─ styles/          全局样式与设计变量
├─ backend/
│  ├─ app/
│  │  ├─ api/          FastAPI 路由
│  │  ├─ models.py     SQLAlchemy 数据模型
│  │  ├─ database.py   数据库连接
│  │  ├─ security.py   密码与认证
│  │  └─ realtime/     现有 WebSocket ping/pong 事件类型
│  ├─ migrations/      Alembic 数据库迁移
│  └─ tests/           后端接口测试
├─ device-client/      Windows Python 指标采集与心跳
├─ agent-adapters/openclaw/  OpenClaw Agent Runtime Adapter
├─ public/             图片与静态资源
└─ README.md
```

## 数据与认证

Web 开发模式默认数据库为从 `backend` 目录启动时的 `backend/nexa.db`。默认 SQLite 路径相对后端进程的工作目录；请从 `backend` 目录启动，以便重启后继续使用同一文件。Desktop 模式使用 Tauri AppData 中的绝对路径 SQLite 数据库。`NEXA_MODE=local` 使用 SQLite；独立的 `NEXA_MODE=core` 使用 PostgreSQL，额外安装 `requirements-postgres.txt`，并要求 `postgresql+psycopg://...` 连接串。启动后端或创建管理员时会执行 Alembic 迁移，已有数据库可升级。切换数据库前请备份原数据库。

`.env` 支持 `DATABASE_URL`、`JWT_SECRET`、`APP_TIMEZONE` 和 `CORS_ORIGINS`。缺少 `JWT_SECRET` 时后端拒绝启动。密码以 PBKDF2 哈希保存，登录返回 JWT，业务资源按用户隔离。注册默认开放；自托管实例如需关闭后续注册，可设置 `ALLOW_REGISTRATION=false`。管理员也可在 `backend` 目录运行 `python -m app.create_admin`，通过终端设置用户名和密码。数据库保留内部邮箱字段以兼容旧数据，但用户无需填写邮箱。

前端数据链路：`页面 → Pinia store → service → /api/v1 → SQLAlchemy → 数据库`。四个新后端化页面通过服务层调用 API，不直接请求网络。

| 页面 | 状态 |
| --- | --- |
| Dashboard | Persistent user-scoped widgets and layout |
| Websites | Persistent |
| Devices | Persistent |
| Agents | Persistent |
| Data | Persistent |
| Automation | Persistent workflows / test execution only |
| Ledger | Persistent local ledger |
| API Keys | Persistent |
| Settings | Persistent |

Automation 目前仅保存工作流与触发器配置、执行历史，并提供模拟 `test-run`。Real scheduler / action execution engine is not implemented yet. 启用状态不会自动执行动作。Ledger 是轻量本地账本，不提供银行同步、OCR 或 AI 记账。

Settings 的存储用量、跨设备同步和双重身份验证尚未实现。Dashboard 的快捷网站、设备、智能体、数据集、最近记录、工作流、账本均读取当前用户持久化数据；无数据或请求失败时显示相应状态。系统卡片仅显示在线设备实际心跳指标，不提供设备端心跳时不显示 CPU、内存或磁盘值。通知尚无统一事件来源，保持空状态。

## Agent Runtime

```text
Nexa → Agent Task → Agent Runtime API → OpenClaw Adapter → OpenClaw → result/events → Nexa
```

OpenClaw is the first adapter. Nexa Agent Runtime protocol is adapter-independent. 创建 Agent 后在 Agents 页面生成 `na_live_` Token，复制到 `agent-adapters/openclaw/config.json`。参考 [Adapter 配置和启动说明](agent-adapters/openclaw/README.md)。Adapter 每次只处理一个 queued 任务：先 claim 为 running，调用 OpenClaw 后写入结果和 completed，或写入错误和 failed；任务日志写入现有 AgentEvent。心跳每 10–30 秒发送，超过 120 秒未收到时 Agents 页面派生 offline 状态。页面每 20 秒刷新，无 WebSocket 依赖。

Agent Token 是 bearer credential；仅生成时返回明文，数据库只存 SHA-256 hash 和末四位。重新生成或撤销后旧 Token 立即失效，删除 Agent 时凭证随之失效。请安全保存 Token，远程部署使用 HTTPS，不要提交 `config.json`。Agent Token 仅能控制其对应 Agent 的 Runtime 资源，不能作为用户 JWT 使用。

本版未实现 WebSocket realtime streaming、Automation Engine、远程 shell、multi-agent orchestration、distributed/priority queue、Agent memory synchronization、file upload protocol、tool/live token streaming、Agent marketplace 或 Codex Adapter。Automation 不消费 Agent Event。

## API

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| POST | `/api/v1/auth/login` | 登录 |
| POST | `/api/v1/auth/register` | 注册 |
| GET | `/api/v1/auth/me` | 当前用户 |
| GET、POST | `/api/v1/websites` | 查询、创建网站 |
| GET、PATCH、DELETE | `/api/v1/websites/{id}` | 读取、修改、删除网站 |
| POST | `/api/v1/websites/{id}/visit` | 记录最近访问时间 |
| GET、POST | `/api/v1/website-categories` | 分类列表、新建分类 |
| PATCH、DELETE | `/api/v1/website-categories/{id}` | 修改、删除分类 |
| GET、POST | `/api/v1/devices` | 设备列表、新建设备 |
| GET、PATCH、DELETE | `/api/v1/devices/{id}` | 读取、修改、删除设备 |
| POST | `/api/v1/devices/{id}/heartbeat` | 更新在线时间和 CPU、内存、磁盘、电量指标 |
| POST、DELETE | `/api/v1/devices/{id}/token` | JWT 用户生成或撤销专属 Device Token |
| POST | `/api/device/heartbeat` | Device Token 上报 Windows 运行指标 |
| GET、POST | `/api/v1/agents` | 智能体列表、新建智能体 |
| GET、PATCH、DELETE | `/api/v1/agents/{id}` | 读取、修改、删除智能体；PATCH 可设置 `enabled` |
| POST | `/api/v1/agents/{id}/heartbeat` | 更新运行时状态与在线时间 |
| POST、DELETE | `/api/v1/agents/{id}/token` | JWT 用户生成或撤销专属 Agent Token |
| POST | `/api/v1/agents/{id}/tasks` | 创建任务 |
| PATCH、DELETE | `/api/v1/agents/{id}/tasks/{taskId}` | 更新任务文本或删除非运行任务；状态由 Runtime 控制 |
| POST | `/api/agent/heartbeat` | Agent Token 上报 idle/running/error 及 Runtime 信息 |
| GET | `/api/agent/tasks` | Agent Token 查询自己 queued 任务 |
| POST | `/api/agent/tasks/{id}/claim` | 原子 claim queued → running |
| POST | `/api/agent/tasks/{id}/events` | 写入自己的任务事件和日志 |
| POST | `/api/agent/tasks/{id}/complete` | running → completed，保存结果 |
| POST | `/api/agent/tasks/{id}/fail` | running → failed，保存错误 |
| GET、POST | `/api/api-keys` | 列出、创建当前账户的 API Key（仅 JWT） |
| PUT | `/api/api-keys/{id}/status` | 启用或停用 API Key（仅 JWT） |
| GET | `/api/devices`、`/api/agents`、`/api/data`、`/api/automation` | JWT 或具有对应 scope 的 API Key 读取 |
| GET、PATCH | `/api/v1/settings` | 读取与保存当前用户设置 |
| PATCH | `/api/v1/account` | 修改当前用户名称与头像 URL |
| POST | `/api/v1/account/password` | 验证原密码后修改密码 |
| GET、POST | `/api/v1/data/collections` | 集合列表与创建 |
| GET、PATCH、DELETE | `/api/v1/data/collections/{id}` | 集合读取、修改、删除 |
| GET、POST | `/api/v1/data/collections/{id}/records` | 集合记录列表与创建 |
| GET、PATCH、DELETE | `/api/v1/data/records/{id}` | 记录读取、修改、删除 |
| GET、POST | `/api/v1/automations` | 工作流列表与创建 |
| GET、PATCH、DELETE | `/api/v1/automations/{id}` | 工作流读取、修改、删除 |
| GET | `/api/v1/automations/{id}/executions` | 执行历史 |
| POST | `/api/v1/automations/{id}/test-run` | 写入模拟成功的执行记录，不运行真实动作 |
| GET、POST | `/api/v1/ledger/categories`、`/api/v1/ledger/transactions` | 分类与交易列表、创建 |
| GET、PATCH、DELETE | `/api/v1/ledger/categories/{id}`、`/api/v1/ledger/transactions/{id}` | 分类与交易读取、修改、删除 |
| GET | `/api/v1/ledger/summary?month=YYYY-MM` | 月度收支、趋势与分类统计 |
| WebSocket | `/ws` | 基础 ping/pong 连接 |

网站列表支持 `categoryId`、`search`、`favorite` 和 `sort=order|name|createdAt|updatedAt|recent`。打开网站会写入最近访问时间，首页快捷访问展示最近打开的网站。添加网站时浏览器会尝试读取该站点的 `/favicon.ico` 或 `/apple-touch-icon.png`，也可手动指定图标。受保护接口须发送 `Authorization: Bearer <token>`。错误响应包含 FastAPI 风格的 `detail`，并保留现有客户端使用的 `error` 字段。旧 `/api/auth` 和 `/api/dashboard` 路径为现有 Dashboard 保留。

API Key 在 API 页面创建；请求体为 `{"name":"Production App","scopes":["Devices"],"expires_in_days":90}`。名称去首尾空白后须为 1–48 个字符；可用 scope 为 `Devices`、`Agents`、`Data`、`Automation`、`Read`，期限为 30、90、365 天或 `null`（永不过期）。`Read` 允许读取上述四个 GET 接口，其他 scope 只允许相应模块。Key 的明文仅在创建成功响应和当次页面弹窗中出现；请立即复制保存，关闭或刷新后无法找回。列表仅显示掩码。停用或过期的 Key 无法调用接口，过期 Key 无法重新启用。Key 不能访问账户、Dashboard、Key 管理或其他写入接口；这些接口仍须使用 JWT。API 页面中的请求日志、用量统计和 Webhook 暂不可用。

设备添加后默认离线。旧 `POST /api/v1/devices/{id}/heartbeat` 仍接受用户 JWT，供兼容与开发调试；真实 Windows Client 使用下方 Device Token 接口。最近 120 秒内收到心跳才显示在线。智能体可以管理资料、启停设置与任务，并记录操作日志；运行时可向 `POST /api/v1/agents/{id}/heartbeat` 发送 `{"status":"running"}` 或 `{"status":"idle"}`。当前版本未接入 AI 任务执行器，页面不会伪造指标、模型调用或任务完成结果。

## Device Runtime

Nexa-LumaDock can receive runtime metrics from the Windows Device Client. 数据链路：`Windows Client → Device Token → POST /api/device/heartbeat → FastAPI → Device DB → Devices Store / Dashboard`。客户端默认每 30 秒上报 CPU、内存、系统盘、可选电量、主机名、Windows 版本、架构、CPU 名称、开机时长和局域网 IP。服务器按最近一次心跳动态计算在线状态，超过 120 秒变为离线。页面和 Dashboard 约每 30 秒刷新，无 WebSocket 实时推送。

1. 在 Devices 页面添加设备。
2. 在设备详情生成 Device Token，立即复制；明文仅显示一次。重新生成会立即使旧 Token 失效。
3. 在 `device-client` 目录复制 `config.example.json` 为 `config.json`，填入 `serverUrl` 与 `deviceToken`。
4. 运行 `python -m pip install -r requirements.txt`。
5. 运行 `python main.py`，按 Ctrl+C 停止；`python main.py --once` 可发送一次心跳用于检查。

Device Token should be treated as a secret. `config.json` contains a secret. Do not commit it. 服务器仅保存 SHA-256 hash 和末四位；Token 只可调用自己的设备心跳，不能访问用户资源。客户端仅支持 Windows，第一版只统计 Windows 系统盘；无电池或无法取得局域网 IP 时字段为 `null`。没有远程控制、命令执行、进程管理、Agent Runtime、Automation Engine，也没有 WebSocket 实时推送。

## Security Notes

Device Token is a long-lived bearer credential. It can be intercepted over HTTP. Use HTTPS for production and cross-machine deployments. The Windows client permits HTTP only for `localhost` and `127.0.0.1` by default. Trusted LAN development can explicitly set `"allowInsecureHttp": true` in `config.json`; the token is then exposed to network eavesdropping. Device Token can be revoked in the Devices dialog, immediately stopping the current client from reporting.

## Migration Policy

Alembic revisions are immutable after merge. Revisions 0001–0006 are frozen after this v0.4.1 repair. Every future schema change requires a new revision (0007, 0008, and so on); historical migrations must never import current ORM models or `Base.metadata`.

## CI

GitHub Actions runs three jobs on pushes and pull requests: frontend build, backend pytest, and Windows device client compile/test.

## License

This project is licensed under the [MIT License](LICENSE).

首页天气卡片在浏览器允许定位后，从 [BigDataCloud](https://www.bigdatacloud.com/geocoding-apis/free-reverse-geocode-to-city-api) 获取城市，并从 [Open-Meteo](https://open-meteo.com/en/docs) 获取该位置的天气。拒绝定位时会尝试按 IP 显示大致城市，卡片标注“约”。位置请求由浏览器直接发出，成功结果和失败状态均缓存 30 分钟，避免每次进入首页重复请求；点击卡片中的位置可手动重试。

## 检查

```powershell
npm run build
cd backend
python -m pytest -q
```
