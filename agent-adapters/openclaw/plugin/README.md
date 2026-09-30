# Nexa OpenClaw Tools 0.1.0

用于 Nexa Local 0.5.5 的官方 OpenClaw Tool Plugin。包含 29 个静态业务工具和 `nexa_status`，共 30 个 tools。Runtime Adapter 保持独立版本 0.1.0。

要求 OpenClaw **2026.9.6** 与 Node **24.16.0+（<25）或 26.1.0+**。实际 SDK 使用 `openclaw/plugin-sdk/tool-plugin` 的 `defineToolPlugin`，不使用社区旧格式。

```powershell
npm install
npm run build
npm run plugin:build
npm run validate
npm test
```

修改 schema 后先在仓库根目录执行 `py scripts/export-agent-tools.py`；修改插件静态元数据后执行 `npx openclaw plugins build --root . --entry dist/index.js`，再检查 `npm run plugin:build`。不要只修改 generated manifest。

安装：`openclaw plugins install --link <此目录的绝对路径>`，然后 `openclaw plugins enable nexa-tools`。通过 `openclaw plugins doctor` 和 `openclaw plugins inspect nexa-tools --runtime --json` 验证发现/加载，再调用 `nexa_status`。

配置推荐只指定 `adapterConfigPath`，明确指向现有 runtime adapter/config.json，共享 `serverUrl/agentToken`。该凭证必须由目标 Nexa **Local** 创建。也可设置 `serverUrl` 与 `agentTokenEnv`，让 Gateway 从环境变量 `NEXA_AGENT_TOKEN` 读取 secret；环境中的 token 优先。只连接受信任 Local，远程使用 HTTPS。没有普通 REST、Core 或数据库权限回退。

完整安装配置示例、tool 清单、Scope、幂等、审计与离线同步说明：[Agent Data Actions](../../../docs/agent-data-actions.md)。
