# Nexa Desktop v0.5.1

首次提供 Windows 10/11 x64 桌面安装包。安装后启动 `Nexa.exe`，Tauri 会自动准备用户 AppData、启动独立 FastAPI sidecar、等待数据库迁移和健康检查完成，再显示现有 Vue 界面。

- 关闭窗口后驻留系统托盘；托盘可重新打开或完整退出。
- 单实例运行，重复启动会聚焦原窗口。
- SQLite、JWT 密钥与日志保存在 `%APPDATA%\com.isidel.nexa`，升级安装不会覆盖数据。
- Backend 仅监听 `127.0.0.1:17800`；保留原有登录认证和全部业务 API。
- Web 开发模式及 Device Client、OpenClaw Adapter 继续受支持。

下载 `Nexa_0.5.1_x64-setup.exe` 安装。已有 Web 数据迁移和故障排查见 [Desktop 文档](https://github.com/zjyzjy0823-hue/Nexa-LumaDock/blob/main/docs/desktop.md)。

本版暂不提供局域网 Runtime 访问；远程 OpenClaw 与 Device Client 的连接流程属于 v0.5.2。
