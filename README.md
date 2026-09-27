# Nexa

Nexa 是自托管个人控制中心。前端使用 Vue 3、TypeScript、Pinia 和 Vite；后端使用 FastAPI、SQLAlchemy 2、Alembic 和 JWT。**Websites、Devices、Agents** 已接入真实数据库；Automation 等页面仍处于演示阶段。

## 开发启动

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

打开 `http://127.0.0.1:5173/`。首次进入会显示登录与注册页，只需设置用户名和密码。登录后可从侧边栏头像菜单退出；首页问候语使用当前用户名。网站、设备、智能体与任务的更改在刷新浏览器后仍会保留。前端将 `/api` 代理到本地后端。接口文档位于 `http://127.0.0.1:8000/docs`。

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
│  ├─ mock/            尚未接入后端的页面演示数据
│  └─ styles/          全局样式与设计变量
├─ backend/
│  ├─ app/
│  │  ├─ api/          FastAPI 路由
│  │  ├─ models.py     SQLAlchemy 数据模型
│  │  ├─ database.py   数据库连接
│  │  ├─ security.py   密码与认证
│  │  └─ realtime/     WebSocket 事件类型
│  ├─ migrations/      Alembic 数据库迁移
│  └─ tests/           后端接口测试
├─ public/             图片与静态资源
└─ README.md
```

## 数据与认证

默认数据库为从 `backend` 目录启动时的 `backend/nexa.db`。`DATABASE_URL` 支持 SQLite 和 PostgreSQL；PostgreSQL 额外安装 `requirements-postgres.txt`，使用 `postgresql+psycopg://...` 连接串。启动后端或创建管理员时会执行 Alembic 迁移，已有数据库可升级。切换数据库前请备份原数据库。

`.env` 支持 `DATABASE_URL`、`JWT_SECRET`、`APP_TIMEZONE` 和 `CORS_ORIGINS`。缺少 `JWT_SECRET` 时后端拒绝启动。密码以 PBKDF2 哈希保存，登录返回 JWT，网站、分类、设备、智能体和任务按用户隔离。注册默认开放；自托管实例如需关闭后续注册，可设置 `ALLOW_REGISTRATION=false`。管理员也可在 `backend` 目录运行 `python -m app.create_admin`，通过终端设置用户名和密码。数据库保留内部邮箱字段以兼容旧数据，但用户无需填写邮箱。

前端数据链路：`页面 → Pinia store → service → /api/v1 → SQLAlchemy → 数据库`。三个真实数据页面都通过服务层调用 API，不直接请求网络。

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
| GET、POST | `/api/v1/agents` | 智能体列表、新建智能体 |
| GET、PATCH、DELETE | `/api/v1/agents/{id}` | 读取、修改、删除智能体；PATCH 可设置 `enabled` |
| POST | `/api/v1/agents/{id}/heartbeat` | 更新运行时状态与在线时间 |
| POST | `/api/v1/agents/{id}/tasks` | 创建任务 |
| PATCH、DELETE | `/api/v1/agents/{id}/tasks/{taskId}` | 更新或删除任务 |
| WebSocket | `/ws` | 基础 ping/pong 连接 |

网站列表支持 `categoryId`、`search`、`favorite` 和 `sort=order|name|createdAt|updatedAt|recent`。打开网站会写入最近访问时间，首页快捷访问展示最近打开的网站。添加网站时浏览器会尝试读取该站点的 `/favicon.ico` 或 `/apple-touch-icon.png`，也可手动指定图标。受保护接口须发送 `Authorization: Bearer <token>`。错误结构为 `{ "error": { "code": "...", "message": "..." } }`。旧 `/api/auth` 和 `/api/dashboard` 路径为现有 Dashboard 保留。

设备添加后默认离线。设备端通过带用户 JWT 的 `POST /api/v1/devices/{id}/heartbeat` 发送 `{"cpu":24,"memory":40,"disk":55,"battery":80}`；最近 120 秒内收到心跳才显示在线。智能体可以管理资料、启停设置与任务，并记录操作日志；运行时可向 `POST /api/v1/agents/{id}/heartbeat` 发送 `{"status":"running"}` 或 `{"status":"idle"}`。当前版本未接入实际设备采集程序或 AI 任务执行器，页面不会伪造指标、模型调用或任务完成结果。

首页天气卡片在浏览器允许定位后，从 [BigDataCloud](https://www.bigdatacloud.com/geocoding-apis/free-reverse-geocode-to-city-api) 获取城市，并从 [Open-Meteo](https://open-meteo.com/en/docs) 获取该位置的天气。拒绝定位时会尝试按 IP 显示大致城市，卡片标注“约”。位置请求由浏览器直接发出，成功结果和失败状态均缓存 30 分钟，避免每次进入首页重复请求；点击卡片中的位置可手动重试。

## 检查

```powershell
npm run build
cd backend
python -m pytest -q
```
