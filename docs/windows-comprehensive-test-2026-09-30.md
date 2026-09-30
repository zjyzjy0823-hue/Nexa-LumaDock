# Nexa 0.5.5 Windows 全面回归记录

测试日期：2026-09-30。基线：`f5f3887b5e3b14d20f5fd9196724d16b261df7f9`，分支 `codex/v0.5.5-agent-data-actions`。

按用户要求跳过 OpenClaw 插件、适配器与 SDK。本轮覆盖现有 Nexa 业务功能、数据库和同步链路、Web 页面、Windows Tauri/WebView2、液态玻璃样式。已修复发现的问题，并生成新的本地安装包；尚未实现或未完成验收的功能单独列出，不能视为全部功能通过。

## 环境与隔离

- Windows 11 x64，真实 Tauri release 程序与打包后的 Python sidecar。
- Web 浏览器使用独立测试账户、独立 SQLite 和本地测试端口。
- Windows 测试使用独立应用标识 `com.isidel.nexa.regression-20260930` 与独立用户数据目录，业务增删改没有使用正式数据库。
- 原先安装的 Nexa 因固定端口 17800 需临时关闭；测试结束恢复原安装程序。
- Windows QA 构建仅增加测试应用标识与一次性测试登录 fixture。正式安装包重新执行默认 `npm run desktop:build`，确认 `dist/index.html` 不包含测试登录注入。

## 自动检查结果

| 检查 | 结果 | 范围 |
| --- | --- | --- |
| Backend `py -m pytest -q` | 148 passed | 认证、权限、幂等、审计、普通 CRUD、SQLite 迁移与同步、桌面配置/CORS/CSP |
| Device Client `py -m pytest -q` | 20 passed | 配置、采集器与心跳客户端逻辑 |
| Rust `cargo test --release --target x86_64-pc-windows-msvc --lib` | 2 passed | HTTP/HTTPS URL 保留参数与片段，拒绝文件、脚本、系统协议与相对路径 |
| PostgreSQL migration + smoke | PASS | 新库升级至 Alembic head、普通 CRUD、workspace 隔离、并发与升级兼容 |
| PostgreSQL HTTP 同步集成 | PASS | Local SQLite → Core PostgreSQL → Replica，离线、冲突、依赖、删除与撤销；使用 `--skip-agent-tools` 跳过 OpenClaw |
| 打包 sidecar smoke | PASS | 真实 EXE，scope/create/replay/audit、六类实体 outbox、tombstone、重启持久化、登录 |
| Web build / desktop frontend build | PASS | Vue/TypeScript 类型检查与 Vite 生产构建 |
| Python compileall | PASS | Backend app 与 Device Client |
| 默认 Windows NSIS bundle | PASS | `npm run desktop:build` 重新打包 sidecar、Rust 和前端，生成 x64 安装包 |

Backend 有 327 条现有依赖警告：FastAPI 使用即将弃用的 asyncio 判断函数，以及 Pydantic 字段 alias 警告。本轮没有 pytest 失败，也没有通过删除或跳过核心用例获得通过。

## 页面与操作覆盖

| 模块 | Web 实际操作 | Windows 实测 |
| --- | --- | --- |
| 账户入口 | 注册、退出、错误密码拒绝、正常登录、重载恢复会话 | 独立 fixture 恢复测试会话，避开正式账户 |
| 首页 | 真实业务统计、组件布局键盘移动与重载持久化、恢复默认、天气降级场景 | 实际天气显示、业务统计、重启后交易保留 |
| 网站 | 分类创建/重命名、网站创建/编辑/删除、搜索、列表视图、名称排序、Web 新标签打开 | 页面、分类与网站读取；桌面链接最终实际浏览器跳转未完成验收 |
| 设备 | 新增 Windows 设备及表单 | 页面读取、离线/等待心跳状态 |
| 智能体 | 新增、九项数据权限选项、新增任务 | 目录与任务读取；通用 runtime/API 生命周期由 Backend 用例覆盖 |
| 数据 | 集合与记录创建/编辑/删除、搜索、取消删除、状态更新 | 页面和测试集合/记录读取 |
| 账本 | 分类/交易创建、交易修改/删除、月汇总、金额精度 | 原生表单新增 9.99 元交易，API 核对保存金额，重启后保留 |
| 自动化 | 配置创建、试运行记录、错误/成功展示、配置保存 | 页面、配置与“尚未启用真实调度”的提示 |
| API | 密钥创建、一次性明文展示、重载后遮蔽、停用/启用 | 已遮蔽密钥与权限读取 |
| 设置 | 账户、外观、同步、存储、安全、通知、关于七个分区；时区重载持久化、密码错误拒绝、设置导入/导出、导入保存失败反馈 | 设置页面、账户、版本显示 |

Web 九个页面在 960、1280、1920 像素宽度下检查，未发现页面级横向溢出。数据表格在窄宽度允许自身横向滚动。浏览器回归中出现过资源加载 `ERR_NO_BUFFER_SPACE`，以及模拟网络/保存失败产生的预期错误，没有发现 Vue 页面异常。

## Windows 生命周期

- 后端正常启动与健康检查通过。
- 端口 17800 被占用时显示明确错误。
- 窗口最大化及最小化后的恢复已观察。
- Alt+F4 关闭窗口后程序与后端继续运行；再次启动恢复原单实例，没有重复后端。
- 后端通过 shutdown 文件停止时，窗口显示后端已停止的提示。
- 重启后原生测试交易仍存在，金额与汇总一致。

## 本轮修复

1. **Windows 天气**：补齐 production/dev CSP 中的城市查询服务域名。WebView2 下按坐标查询城市仍可能遭遇服务端 CORS 拒绝，改为城市名查询失败时继续使用已有定位坐标请求天气，显示“当前位置”。真实 Windows 构建观察到温度和天气恢复；另外通过模拟城市服务失败验证降级链路。
2. **玻璃弹窗与菜单**：建立共享弹窗/浮层背景和 blur token；账本弹窗改用共享 Modal；补齐设备、智能体、网站、集合、API 菜单、账户菜单、通知浮层和启动错误面板的玻璃材质。
3. **确认交互**：将业务删除等操作的原生 `window.confirm` 改为应用内玻璃确认框；网站分类重命名从原生 `prompt` 改为内联表单。共享 Modal 增加 Tab 焦点循环、Escape、焦点返回、滚动锁及多弹窗栈。实际验证取消删除不改变数据、Escape 不关闭下层分类弹窗。
4. **遗漏控件**：自动化卡片和数据表格操作改用 ActionButton；账户用户名、工作流选择、设备令牌输入补齐圆角与透明背景；提高 API 页说明文字对比度。
5. **设置可靠性**：版本改从 package.json 读取；同步服务器地址输入完整值后保存，避免每个字符触发保存；滑块结束操作后保存；导入过程中后端保存失败不会再显示成功。外观页明确说明当前仅预览与保存偏好。
6. **桌面浏览器接口**：加入 Tauri Opener 和仅允许 HTTP/HTTPS 的 Rust 命令；统一处理外部锚点左键/中键及键盘点击，覆盖网站、快捷访问和天气来源。Web 新标签行为、模拟 IPC 的 URL 保留/错误提示/非法协议拒绝、Rust URL 检查均通过。实现参考 [Tauri Opener 官方说明](https://v2.tauri.app/plugin/opener/)。

## 液态玻璃检查结论

主导航、九个主页面容器、卡片、设置分区、业务编辑弹窗、确认框、上下文/排序/账户菜单和已检查通知浮层均有玻璃样式。修复前账本编辑/分类区域、原生 confirm/prompt、部分操作按钮与用户名输入遗漏已处理。最终 Web 截图检查了透明背景、模糊、边框高光和文字可读性；Windows 原生交易弹窗也观察到正确材质。

Windows 标题栏、系统选择列表、日期/文件选择器、托盘系统菜单仍由操作系统绘制。本轮没有将这些操作系统控件替换为应用自绘界面。

截图保存在本地 `output/playwright/`（被 Git 忽略），包括九个页面、七个设置分区、业务弹窗，以及最终 `qa-automation-final.png`、`qa-api-final.png`、`qa-settings-account-final.png`、`qa-dialog-confirm-final.png`、`qa-dialog-password-final.png`。

## 未实现或未完成验收

- **桌面网站实际跳转（后续已通过）**：初次测试未观察到目标浏览器页面；后续改为组件直接打开外链并补齐日志，Windows 实测确认首页快捷访问、网站卡片左键/中键、菜单和天气来源在默认 Edge 中打开目标 URL。详见 [外链修复回归报告](windows-external-links-test-2026-09-30.md)。
- 外观设置保存与预览可用，全局主题、强调色、背景、透明度和模糊度应用仍未实现。
- 设置中的同步偏好不是 Core 连接/同步控制台；实际手动同步后端已测，后台自动同步与移动网络策略尚未实现。
- 自动化只保存配置和测试执行记录，真实事件监听、定时调度、动作执行尚未实现。
- 通知渠道实际投递、双因素认证、存储用量/缓存统计、API 请求日志/用量统计/Webhook，以及部分关于页资源/检查更新入口尚未实现。设置备份仅包含账户设置，不是完整业务数据库备份。
- 没有验收实际安装/覆盖升级/卸载向导、高 DPI 多屏、托盘菜单实际点击、真实硬件设备到服务端的完整运行链路。
- 共享 Modal 完成键盘焦点处理；其他自定义业务弹窗没有统一迁移成共享 Modal，不能宣称所有弹窗已完成完整可访问性验收。
- OpenClaw 按用户要求跳过。

## 本地产物

安装包：`src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/Nexa_0.5.5_x64-setup.exe`，43,615,011 字节（约 41.59 MiB）。版本仍为 0.5.5，没有开始 v0.5.6。

本轮仅本地提交，不执行 push、tag 或 GitHub Release。

测试 HTTP 服务、Vite、测试浏览器和临时 PostgreSQL 容器已停止，原安装程序已重新启动。测试令牌文件及 WebView2 诊断日志已清理。自动审批拒绝删除临时 QA EXE，停止清理这些可执行文件；它们仍在被 Git 忽略的 `output/windows-qa*` 目录中，包含测试登录 fixture，不作为可交付安装包分发。
