# Mac Core 常驻部署与 frp 穿透说明

Mac 端作为家庭/办公室私密数据中心，承载 **PostgreSQL + Studiolo Core + 本地 AgentNode**，并通过 `frpc` 主动向外网 VPS 发起加密隧道（零公网端口暴露到家庭宽带）。

## 1. 准备数据库与 Core 后端

```bash
brew install postgresql@16 frp
brew services start postgresql@16
createdb studiolo

cd ~/Studiolo/backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-postgres.txt

export STUDIOLO_MODE=core
export DATABASE_URL="postgresql+psycopg://studiolo:CHANGE_ME@127.0.0.1:5432/studiolo"
export JWT_SECRET="$(openssl rand -hex 32)"
.venv/bin/python -m alembic -c alembic.ini upgrade head
```

## 2. 配置并加载 `launchd` 服务

1. 替换 `com.studiolo.core.plist`、`com.studiolo.frpc.plist` 与 `frpc.toml` 中的 `YOU`、域名及与 VPS 一致的密钥；
2. 保证 Mac Core 后端**只绑定 `127.0.0.1:8000`**；
3. 放入 `~/Library/LaunchAgents/` 并启用：
```bash
mkdir -p ~/.studiolo-core/logs
cp frpc.toml ~/.studiolo-core/frpc.toml
cp com.studiolo.*.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.studiolo.core.plist
launchctl load -w ~/Library/LaunchAgents/com.studiolo.frpc.plist
```

## 3. 注册 Mac 本机为 Fleet 节点

1. 在 Studiolo 前端（`https://studiolo.example.com`）登录并在 `设置 -> Agent 与连接` 新增节点，获取 `sn_live_`；
2. 基于 `agent-node/config.example.json` 配置 `~/.studiolo-core/node-config.json`（务必只放行 `allowedRoots` 内的项目目录）；
3. 填入 `com.studiolo.agent-node.plist` 后 `launchctl load -w`。

## 4. 建议系统设置

- 关闭 Mac 自动休眠（`pmset -a sleep 0 disksleep 0`）或保持通电合盖运行；
- 使用 `backup-postgres.sh` + `cron` 每日将数据库备份同步到 iCloud / NAS / 外接硬盘。
