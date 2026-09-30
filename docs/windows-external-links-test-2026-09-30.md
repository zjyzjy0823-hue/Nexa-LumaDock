# Windows 外链修复与回归（2026-09-30）

本次在 `6ae5688` 基础上修复桌面外链处理。前一轮未完成的“默认浏览器实际打开目标网址”验收已通过；此结果取代综合测试报告中该项的未完成结论。版本仍为 0.5.5，OpenClaw 未涉及。

## 实现

- 网站卡片、菜单“打开网站”、首页快捷访问和天气来源使用共享 `ExternalLink.vue`，直接调用 `openExternal()`；移除 App 的 document 全局监听和这些入口上的 `target="_blank"`。
- 左键及 Enter 使用 click，中键使用 auxclick；右键保持上下文菜单，不调用打开命令。
- 网页端在用户点击的同步调用中打开新标签，访问记录请求不阻塞打开。桌面端使用原有 HTTP/HTTPS 校验及 Rust Opener 命令。
- 首页 widget 的错误经 DashboardRenderer 转发到提示条；网站页面也显示失败提示。
- Rust 日志区分命令到达、网址拒绝、系统调用失败、系统接受请求。失败日志只包含错误类别与可用的 OS/HRESULT 代码，不记录 URL、凭据或查询参数。

## 验证

| 检查 | 结果及证据 |
| --- | --- |
| 真实 Windows 首页快捷访问 | PASS：点击后 Rust 收到命令，Edge 新增目标标签页 |
| 真实 Windows 网站卡片左键、中键 | PASS：各自新增 Edge 标签页，主窗口保留网站页面 |
| 真实 Windows 菜单“打开网站” | PASS：目标标签页出现，菜单收起 |
| 真实 Windows 右键 | PASS：显示上下文菜单，Rust 命令计数仍为 4 |
| 真实 Windows 天气来源 | PASS：Edge 打开 `https://open-meteo.com/`；天气数值使用 QA 缓存，本次不验收定位/天气服务 |
| URL 保留 | PASS：Edge 中观察到完整 `https://example.com/?nexa_qa=explicit#check`，查询参数和片段均保留 |
| 访问记录 | PASS：测试网站 lastVisitedAt 与点击同步更新，卡片中键实测为 `2026-09-30T13:56:41.717811+08:00` |
| 组件浏览器回归 | PASS：左键、中键、Enter 每次调用一次；右键不调用；内部导航不受影响；非法协议/格式在 IPC 前拒绝；网页分支实际出现新标签 |
| 四个真实页面入口的失败路径 | PASS（模拟 IPC 失败）：四个入口各调用一次；首页和网站错误提示可见；失败时网站菜单仍收起。最终页面无 console error，四条 warning 为刻意模拟打开失败 |
| 构建 | `npm run build`、`npm run build:desktop`、`npm run desktop:build`、最终默认配置 `npx tauri build --target x86_64-pc-windows-msvc` 均成功 |
| Rust URL 校验 | `cargo test --target x86_64-pc-windows-msvc`：2 通过；这两项不单独证明浏览器打开 |

Windows QA 使用独立应用标识 `com.isidel.nexa.external-20260930`、独立数据库和测试账户；使用实际 release EXE 与 sidecar。默认浏览器保持 Windows 原有配置，通过浏览器连接器读取真实 Edge 标签 URL，未通过测试脚本直接启动目标网址。未修改正式账户数据或系统权限设置。

系统接受打开请求只能说明调用已提交，不能单独证明页面显示；本次用实际 Edge 标签页补齐此项证据。没有因此断言原故障必然是 WebView2 的 `_blank` 缺陷，也未覆盖其他 Windows 默认浏览器配置。

## 交付与诊断

正式安装包为 `src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/Nexa_0.5.5_x64-setup.exe`，43,619,372 字节。默认配置重新构建后，确认 `dist/index.html` 无 QA 登录注入，`dist/qa-fixture.js` 不存在。安装/覆盖升级向导未在本次自动执行；恢复运行的原安装版仍为 0.5.1，需安装新包才能使用本次修复。

若仍失败，先核对所运行的 EXE/安装包，再查看当前应用数据目录中的 `logs/desktop.log`：没有 `External link: command received` 时检查前端/IPC；出现 `system open failed` 时看错误类别；出现 `system open request accepted` 时继续确认默认浏览器实际页面。

回归脚本、测试浏览器记录和带测试登录的 QA EXE 位于被 Git 忽略的 `output/playwright/`、`output/windows-qa-external/`，不作为正式安装包发布。测试服务和 QA 程序结束后停止，原安装程序恢复运行；仅关闭本轮新增的浏览器测试标签。
