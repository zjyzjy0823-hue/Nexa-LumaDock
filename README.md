# Studiolo

> **当前版本：`v0.7.0`** · 本地优先（Local-first）的个人数字控制中心 & 多设备 AI Agent 协同工作台。

Studiolo 将个人的日常数据管理（账本、网站、结构化数据、设备监控、自动化）与跨设备的 **AI Coding Agent 远程协同工作台** 合二为一：你可以在一台电脑、平板或手机浏览器上，安全调度家里或云端多台 Mac / Windows / Linux 宿主机上的编程智能体，且聊天正文与代码不在中心服务器数据库落盘。

---

## 核心能力

### 1. 多设备 Agent Fleet 协同工作台（`/chat` 与 `/agents`）
- **单控制台管多台机器**：每台宿主机运行轻量守护进程 [agent-node](agent-node/) 并通过反向 WebSocket 主动连回 Core，无需公网 IP 或手动配置端口映射。
- **多引擎统一驱动**：自动探测并接入宿主机上的 **OpenCode**（HTTP+SSE）、**Codex**（`app-server` stdio JSON-RPC）、**Hermes**（ACP / Gateway）、**OpenClaw**（WebSocket）、**Antigravity**、**DSH** 以及联调 Mock 运行时。
- **IDE 级代码审查与终端体验**：
  - **变更汇总条 & 高亮 Diff**：输入框上方实时汇总变更文件，工作台内提供保留完整 `--tok-*` 语法高亮的双行号 Diff、并排对比（Split）、Hunk 上下文按需展开（`+N more lines`）、行号 `+` 发起单行批注追问、逐块撤销及快捷 Git Commit。
  - **工作区浏览与终端**：支持 `allowedRoots` 沙箱目录树懒加载、行号引用与语法高亮代码预览，以及受控交互式 Shell 终端。
  - **安全执行与隐私边界**：Git Worktree 会话级隔离、高危工具人工审批、持久信任命令白名单（防拼接注入）、按 Agent 记忆模型偏好、支持导出 XSS 安全的独立 HTML / Markdown 报告。
- **端到端加密附件总线**：图片与文件附件在发送端按 2 MiB 分块执行 **AES-256-GCM 本地加密**（密钥不进 Core DB），接收端按 `LAN 局域网直传 → xtcp (frp) → VPS Edge Relay → Core 密文分块` 顺序自动降级拉取。

### 2. 本地优先个人控制中心
- **全套个人模块**：Dashboard 概览、Ledger 账本（兼容部署时区与多币种/分类统计）、Websites 收藏、Data 自定义集合（有界分页）、Devices 硬件状态（[device-client](device-client/)）、Agent Data Actions（`na_live_`）以及 Core 权威调度 Automation。
- **离线可写 + Sync Protocol v3**：支持 SQLite 离线编辑与 Outbox 持久化，接入 PostgreSQL Core 后自动双向同步，通过 Conflict Center 显式裁决冲突；当前 Alembic Schema Head 为 **`0020_fleet_nodes_and_blobs`**。

---

## 系统架构概览

```text
浏览器 / Tauri Desktop / 手机 Web
   ├── HTTP REST & /ws/fleet/client (JWT 首帧鉴权，纯内存指令透传)
   ▼
Studiolo Core (FastAPI · SQLite Local 或 PostgreSQL Core)
   ▲
   │  /ws/fleet/node (sn_live_ 反向出站长连接 · 每 30 秒心跳自报引擎与目录)
   │
宿主机 AgentNodeDaemon (allowedRoots 本地沙箱护栏)
   ├── OpenCode (REST+SSE) / Codex & Hermes (stdio JSON-RPC) / OpenClaw (WS) / CLI
   └── 可选 LAN 密文直传服务 (:18910) ──(公网跨网降级)──▶ VPS Edge Blob Relay / Core 分块
```

---

## 快速开始

### 一、本地 Web 开发启动

环境要求：**Node.js 22+**、**Python 3.12+**。

**1. 启动 FastAPI 后端**

```powershell
cd backend
Copy-Item .env.example .env
# 编辑 backend/.env，务必将 JWT_SECRET 改为随机长字符串
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**2. 启动 Vue + Vite 前端**

```powershell
# 在仓库根目录打开第二个终端
npm ci
npm run dev
```

打开 `http://127.0.0.1:5173/`，首次进入按引导设置用户名与密码登录；接口文档位于 `http://127.0.0.1:8000/docs`。

---

### 二、接入一台宿主机节点（`agent-node`）

1. 在页面右上角或左侧进入 **`/agents`**（或 **「设置 → Agent 与连接」**），点击 **「新增控制节点」**，复制生成的一次性 `sn_live_` Token（服务端仅保留哈希，关闭弹窗无法找回）。
2. 在目标工作机复制配置文件并填入 Core 地址与允许 AI 访问的目录白名单：

```powershell
cd agent-node
pip install -r requirements.txt
Copy-Item config.example.json config.json
# 编辑 config.json 中的 coreUrl 与 allowedRoots（只能访问白名单内路径）
```

3. 注入 Token 并启动节点守护进程：

```powershell
$env:STUDIOLO_NODE_TOKEN = "sn_live_你的节点令牌"
python -m agent_node --config config.json
```

守护进程上线后会自动探测该机器已安装的智能体与能力并同步到前端列表，进入 `/chat` 即可开始协同对话。

---

### 三、桌面端开发与安装包构建（Windows / macOS）

桌面端使用 **Tauri 2** 封装并将 Python 后端作为本地 Sidecar（监听 `127.0.0.1:17800`）随包启动，普通用户使用安装包无需额外配置 Python / Node 环境。

```powershell
# 启动 Tauri 桌面开发窗口
npm run desktop:dev

# Windows x64 构建原生 Sidecar + NSIS 安装包
# 需预先安装 Rust toolchain + PyInstaller (`pip install -r backend/requirements.txt 'pyinstaller>=6,<7'`)
npm run desktop:build
```

打包产物位于 `src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/`。桌面数据目录（数据库、日志与密钥）说明见 [Desktop 使用说明](docs/desktop.md)。

---

### 四、公网自托管与多机部署

- **Mac Core + PostgreSQL 部署**：参考根目录 [.env.core.example](.env.core.example) 与 [docker-compose.core.yml](docker-compose.core.yml)，详细步骤见 [Core 部署文档](docs/core.md)。
- **公网 VPS TLS / frps / Edge Relay**：使用 [deploy/vps-edge/README.md](deploy/vps-edge/README.md) 一键拉起 Caddy HTTPS/WSS 终结、frp XTCP 隧道及无明文盲盒密文中继 [deploy/edge-relay/edge_relay.py](deploy/edge-relay/edge_relay.py)，突破家庭上行带宽瓶颈。
- **跨平台常驻启动模板**：参考 [deploy/mac-core](deploy/mac-core)、[deploy/linux-node](deploy/linux-node) 与 [deploy/windows-node](deploy/windows-node)。

> **Web 模式接入 Core 注意事项**：若以非桌面版独立 Web 后端连接远程 Core（`POST /api/v1/core/connect`），需在后端进程中配置 `STUDIOLO_INSTALLATION_ID`（本机 UUID）与 `STUDIOLO_DATA_DIR`（凭证存储目录）。

---

## 仓库目录结构

```text
Studiolo/
├─ src/                         Vue 3 + TypeScript + Pinia 前端控制台
├─ backend/                     FastAPI 后端（SQLAlchemy 2 + Alembic + Fleet Hub Relay）
│  ├─ app/fleet/                Fleet 控制节点管理、WSS 透传中心与加密 Blob 接口
│  └─ migrations/versions/      Alembic 迁移链（当前 head: 0020_fleet_nodes_and_blobs）
├─ agent-node/                  多设备宿主机守护进程（7 类 Agent 适配器、受控终端、Worktree/Diff）
├─ deploy/                      Core / Edge Relay / frps / Mac-Linux-Windows 常驻部署模板
├─ device-client/               Windows 硬件运行指标采集端（nd_live_）
├─ agent-adapters/openclaw/     OpenClaw 原生 Data Actions Tool 插件（na_live_）
├─ packages/contracts/          Sync Protocol v3 跨语言契约用例与 Rust 校验crate
├─ src-tauri/                   Tauri 2 桌面端外壳与 Sidecar 封装
├─ scripts/                     契约校验、Sidecar 构建冒烟与 Release 校验脚本
├─ docs/                        设计文档、同步协议说明与阶段验收记录
└─ tests/                       前端集成/工具单元测试集
```

---

## 凭证隔离与安全说明

| 凭证前缀 | 作用域 | 说明 |
| --- | --- | --- |
| 用户 **JWT** | 账户与控制台 | 访问个人工作区 REST API 及 `/ws/fleet/client`（严禁放入 URL Query） |
| **`sn_live_`** | Fleet 控制节点 | 绑定到单台物理/虚拟主机节点 `/ws/fleet/node` 与产物分块通道 |
| **`nc_live_`** | Core 同步客户端 | 桌面 Local Backend 与 Core 之间的 Sync v3 双向同步身份凭证 |
| **`na_live_`** | Data Actions 智能体 | 独立智能体对 Ledger / Websites / Data 的受限 Scopes API 调用 |
| **`nd_live_`** | Device 硬件监控 | 仅用于 `device-client` 上报 CPU/内存/磁盘/电量遥测 |
| **`sk_live_`** | 个人 API Key | 在 API 页签发、按 Scope 限制的只读/指定模块集成秘钥 |

---

## 测试与发版门禁

```powershell
# 1. 前端类型检查与生产构建
npm run build
npm run build:desktop

# 2. 前端与桌面单元测试
npm run test:fleet
npm run test:desktop
npm run test:automation
npm run test:local-time
npm run test:core-sync
npm run test:data-bounded-reads
node --test tests/diagnostics.test.mjs

# 3. 跨语言 Sync v3 契约校验三件套
python scripts/check-contracts.py
node scripts/check-contracts.mjs
cargo test --manifest-path packages/contracts/rust/Cargo.toml

# 4. Python 服务与工具测试
python -m unittest discover -s tests -p test_validation_tooling.py
cd backend && python -m pytest -q
cd ..\agent-node && python -m pytest -q
cd ..\deploy\edge-relay && python -m pytest -q
```

- 完整 CI 检查清单见 [.github/workflows/ci.yml](.github/workflows/ci.yml) 与 [scripts/ci-local.sh](scripts/ci-local.sh)；发布前验证入口见 [scripts/validate-release.py](scripts/validate-release.py)。

---

## 延伸文档

- [开发路线图（v0.6.2–v1.0.0）](docs/Studiolo_Development_Roadmap_v0.6.2-v1.0.md)
- [Core 服务配置与节点认证说明](docs/core.md)
- [桌面端使用、数据目录与排障](docs/desktop.md)
- [Sync Protocol v3 与同步范围边界](docs/sync-scopes.md)
- [Agent Data Actions 工具规范](docs/agent-data-actions.md)
- [发布校验流程](docs/validation-workflow.md)

## License

[MIT License](LICENSE)
