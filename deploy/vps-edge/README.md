# Studiolo VPS公网入口部署指南（frps + Caddy TLS + Edge Blob Relay）

本目录用于最小规格公网 VPS（推荐 >= 1 vCPU / 512 MiB RAM），仅承担三件事：
1. **TLS/WSS 终结（Caddy）**：为 Mac Core 与 Edge Relay 统一签发 Let's Encrypt HTTPS 证书；
2. **frp 内网穿透服务端（frps）**：接收家中 Mac Core 与外网 Node 的出站加密隧道；
3. **Edge Blob Relay**：零账号、无数据库缓存 AES-256-GCM 密文分块，彻底消除大文件经家庭宽带双跳转发的瓶颈。

## 快速上线步骤

1. 替换 `Caddyfile` 中的域名 `studiolo.example.com`，并做好 DNS `A` 记录解析。
2. 生成强随机密钥（切勿使用示例值）：
   - `frp` 通信令牌：`openssl rand -hex 32` 写入 `frps.toml` 与 Mac 端 `frpc.toml`；
   - Edge Blob 票据签名密钥：`openssl rand -hex 32` 作为环境变量 `STUDIOLO_EDGE_SECRET`（与 Mac Core 一致）。
3. 放行防火墙端口：
   - `TCP 80`、`TCP 443`（Caddy HTTPS/WSS 与证书续签）
   - `TCP 7000`（frp 隧道接入，`transport.tls.force = true` 强制加密）
   - 若启用 `xtcp` P2P 直传，额外放行 `UDP 7000`（STUN NAT 探测）
   - 严禁对外开放 `8080` 与 `8090`（仅绑定 `127.0.0.1` 供 Caddy 反代）。
4. 启动：
   ```bash
   export STUDIOLO_EDGE_SECRET="你的随机密钥"
   export STUDIOLO_EDGE_CORS_ORIGINS="https://studiolo.example.com"
   docker compose -f docker-compose.edge.yml up -d --build
   ```
5. 验证：
   ```bash
   curl -fsS https://studiolo.example.com/api/edge/blobs/invalid-id || true
   curl -fsS https://studiolo.example.com/api/health
   ```
