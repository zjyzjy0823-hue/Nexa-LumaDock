# Nexa · 个人控制中心

Nexa 使用 Vue 3、TypeScript、Pinia、FastAPI 和 SQLAlchemy。Phase 2 将原有玻璃 Dashboard 接入按用户保存的 Widget 布局，同时保留现有卡片和拖拽体验。

## 启动开发环境

需要 Node.js、Python 3.11+。分别打开两个终端：

```powershell
# 终端 1：后端
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:JWT_SECRET = '替换为随机且保密的长字符串'
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

```powershell
# 终端 2：前端，在项目根目录
npm install
npm run dev
```

访问 `http://127.0.0.1:5173/`。Vite 将 `/api` 代理到 `http://127.0.0.1:8000`。后端接口文档位于 `http://127.0.0.1:8000/docs`。若前后端不使用同一来源，可设置 `VITE_API_BASE_URL` 和后端的 `CORS_ORIGINS`（逗号分隔）。

默认数据库是 `backend/nexa.db`（从 `backend` 目录启动时）。设置 `DATABASE_URL` 可切换数据库；PostgreSQL 使用 `pip install -r requirements-postgres.txt` 和 `postgresql+psycopg://...` 连接串。生产环境设置 `NEXA_ENV=production` 与独立的 `JWT_SECRET`；缺少密钥时后端拒绝启动。当前启动时由 SQLAlchemy 创建基础表；后续修改表结构应加入迁移工具。

## 架构

```text
src/data/dashboard.json      默认 Widget 清单、类型、位置和尺寸
src/widgets/registry.ts      Widget type → Vue 组件与最小尺寸
src/components/dashboard/    DashboardRenderer
src/composables/             拖拽、缩放、碰撞流动与保存
src/stores/                  Pinia 账户与 Dashboard 状态
src/api/                     REST 客户端
src/components/ui/GlassCard.vue  所有现有 Widget 共用的玻璃容器
backend/app/models.py        User、Dashboard SQLAlchemy 模型
backend/app/schemas.py       Widget、Layout 与 API 数据校验
backend/app/api/             认证、Dashboard 和模块路由
backend/app/mock_data.py     模块 API 的临时数据
backend/app/realtime/        WebSocket 扩展位置
```

数据流：`GET /api/dashboard` → Pinia → `DashboardRenderer` → `widgetRegistry[type]` → 对应组件。布局调整完成后向 `PUT /api/dashboard/layout` 发送整个 `widgets` 数组。每个 Widget 有 `id`、`type`、`title`、`icon`、`position`、`size`、`config`、`datasource`。新增 Widget 只需添加 Vue 组件、Registry 条目与默认配置；Dashboard 核心不需修改。未知类型会显示占位卡片。

首页不显示登录入口。首次打开时，浏览器会自动创建一个随机本地账户并保存凭据，以 JWT 访问按账户隔离的 Dashboard；拖拽后仍向布局 API 保存。后端不可用时可继续预览和调整，布局先保存在此浏览器。清除浏览器站点数据会失去这个本地账户的访问凭据。`/api/auth/register` 和 `/api/auth/login` 仍保留，供后续正式账户功能使用。

## REST API

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/auth/register` | 注册并返回 JWT |
| POST | `/api/auth/login` | 登录并返回 JWT |
| GET | `/api/auth/me` | 当前用户 |
| GET | `/api/dashboard` | 当前用户的 Dashboard |
| PUT | `/api/dashboard/layout` | 保存 Widget 布局 |
| GET | `/api/devices` | 设备示例数据 |
| GET | `/api/agents` | 智能体示例数据 |
| GET | `/api/data` | 数据集与账本示例数据 |
| GET | `/api/automation` | 自动化示例数据 |

除注册和登录外，接口都需要 `Authorization: Bearer <JWT>`。Widget 视觉数据仍位于 `src/data/overview.ts`、`src/data/operations.ts`；四个模块 API 目前返回 `backend/app/mock_data.py` 中的示例数据，尚未连接真实设备或外部服务。WebSocket 仅预留目录，尚未开放连接。

## 检查

```powershell
npm run build
cd backend
python -m pytest -q
```

在桌面宽度（至少 1280px）下点击“调整布局”，拖动卡片上方手柄移动，拖动右下角缩放。手柄支持方向键微调、Shift 加方向键快速调整、双击恢复该卡片。较窄屏幕使用响应式排列。
