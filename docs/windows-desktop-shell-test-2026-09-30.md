# Nexa 0.5.5 Desktop Shell 验证（2026-09-30）

基线：`codex/v0.5.5-agent-data-actions` / `1648c2eea092526a04a9b4b70e7ead177f63ea75`。版本保持 0.5.5。本轮仅修改桌面外壳，不修改业务 API、数据库迁移、外链 opener 或 OpenClaw 实现。

## 实现与验证范围

| 项目 | 实现 / 结果 |
| --- | --- |
| Custom titlebar | `DesktopTitleBar.vue`，36px，Nexa 图标/名称、玻璃背景、最小化/最大化或还原/关闭到托盘；仅 `isTauri()` 显示 |
| decorations | 主窗口 `decorations:false`；尺寸、最小尺寸、居中、可调整大小、启动隐藏均保留 |
| Wallpaper black edge | 根因是 1920×1080 壁纸的底部 8px：第 1072 行为分界过渡，第 1073–1079 行近乎纯黑。Desktop 按 1920×1072 有效画面计算覆盖尺寸并顶端对齐；body、启动/错误/登录背景与卡片边缘渐隐层使用一致尺寸，排除图片黑边。普通窗口和最大化 release 截图通过；保留默认原生阴影/圆角 |
| Permissions | 保留 `core:default`；仅新增 window allow-minimize、allow-toggle-maximize、allow-close、allow-start-dragging；is-maximized 和 internal-toggle-maximize 已在当前 schema 的默认权限中 |
| Window controls | 使用 `getCurrentWindow()` 的原生 API；监听 onResized 同步最大化状态，并在卸载时清理监听；空白区使用 Tauri drag-region，自带双击处理 |
| Close/tray | 前端调用 `close()`；Rust 原有 CloseRequested prevent_close/hide、托盘打开/退出和单实例恢复逻辑未修改；实机结果见下表 |
| Desktop viewport | html/body/#app 高度 100%、禁止 document 滚动；titlebar + flex 剩余视口；sidebar 固定；main 顶部控件不参与内容滚动 |
| Scroll container | 首页 `.dashboard-scroll`；业务页 `.workspace-content`；min-height/min-width:0；内部导航重置当前内容区滚动，Web 保留 window.scrollTo |
| Scrollbar | 5px / thin，透明轨道、半透明圆角 thumb、hover 增强；首页横向 hover 溢出被限制；账本卡片缩放时多出的约 2px 内部滚动已修正 |
| Card clipping | 首页滚动区为悬停放大和阴影留出 16px 边缘，底部留出 32px；滚动边缘用独立的同壁纸渐隐覆盖层柔化，不对卡片祖先应用 mask（保留 backdrop blur）；调整布局时隐藏覆盖层 |
| Modal/toast | Modal backdrop 统一覆盖整个窗口（含标题栏），z-index ≥100；标题栏 z-index 90；桌面有 aria-modal 时停止主内容滚动，关闭后自动恢复；toast 仍定位于视口右下 |
| Context menu | 桌面统一禁用全部 WebView 默认右键菜单，包含输入框；本轮没有自定义编辑右键菜单，编辑依赖原生键盘快捷键 |
| Browser shortcuts | 阻止 F5、Ctrl+R/Ctrl+Shift+R、Ctrl+P、Ctrl+S、Ctrl+L、Ctrl+U；保留 Alt/系统组合与 IME 输入 |
| Nexa/editing shortcuts | 保留 Ctrl+K、Ctrl+C/V/X/A/Z/Y；未对全部 Ctrl 组合做拦截 |
| Selection | 仅 titlebar/sidebar/button/navigation/toolbar/card header 禁止选中；正文默认可选，input/textarea/contenteditable/data-selectable 显式允许文本选中 |
| Drag | 仅 img/link/svg 默认 dragstart 被阻止；编辑区和 data-allow-drag 例外；未拦截 drop，不影响现有基于 PointerEvent 的 widget 布局调整 |
| External opener | 保留组件显式调用共享 helper → HTTP(S) 校验 → Rust default browser opener；内部路由仍 history.pushState，未增加 document 外链拦截或 target=_blank |

权限依据同时核对本地生成的 ACL schema 和 [Tauri 官方窗口定制文档](https://v2.tauri.app/learn/window-customization/)。
原生阴影和附带边框的行为依据 [Tauri shadow 配置文档](https://v2.tauri.app/reference/config/#shadow)；最终保留默认 shadow 和原生 resizable，不手写 resize 或裁切 WebView。曾尝试关闭阴影，但它未解决图片中的黑边，最终撤销该配置。

边界诊断使用仅存在于隔离 QA dist 的可见标记和尺寸读数：普通窗口 DOM 为 1280×800，原生 inner/outer 都为 1920×1200 physical pixels，scale factor=1.5；最大化 DOM 为 1707×1066，inner 为 2560×1599 physical pixels。页面高度与 WebView 客户区一致。直接读取壁纸像素确认原图黑边，排除“页面少占了 8px”的错误判断。诊断标记没有进入最终 QA 或正式安装包。

## 自动与浏览器验证

| 检查 | 结果 |
| --- | --- |
| `npm run test:desktop` | 3 个纯逻辑测试通过：浏览器命令、编辑/搜索组合、系统/IME 例外 |
| DOM predicate/event 测试 | 34 项通过：真实 input/textarea/contenteditable（含 false、大小写、继承）、link/img/svg、drag opt-in、菜单阻止、快捷键、drop 保留、监听清理 |
| 9 页面 × 3 视口 | 27 个场景通过：首页/网站/设备/智能体/数据/账本/自动化/API/设置，1280×800、960×640、1920×1080 |
| 滚动结构 | 上述场景的 body/document 高度等于视口、window.scrollY=0、sidebar 与 titlebar 坐标不变、没有额外垂直滚动区；测试用临时 DOM spacer 验证长内容，未创建大量业务数据 |
| Chrome 区域滚轮 | 标题栏、sidebar 滚轮不会滚动 document 或主内容 |
| Card edge regression | 1280×800、960×640、1920×1080 均验证首张卡片悬停后处于完整可视范围，滚到底最后一张悬停卡片距下边缘 >32px；布局调整把手可见；截图确认卡片玻璃模糊保留 |
| Wallpaper regression | 4 个视口（1280×800、960×640、1707×1066、2560×1080）× ready/starting/error/auth，16 项通过；检查实际 CSS 背景尺寸/位置、视口最下方映射到原图黑边之前、无 document overflow；渐隐层与 body 背景尺寸一致 |
| Ctrl+K | 应用原有搜索输入框获得焦点 |
| Modal + clipboard | 960×640 的网站 URL、数据集合名称、账本描述，Ctrl+A/C/Backspace/V 往返一致；Modal 边界在视口内、标题栏被 backdrop 覆盖、主滚动暂停/恢复 |
| Settings input | 用户名 Ctrl+A/C/V 往返一致，保留原用户名，未提交业务变更 |
| Startup/AuthGate | starting/error/auth 三种状态始终显示 titlebar 和三个控制按钮，无 document overflow；Desktop AuthGate 用户名键盘复制粘贴通过 |
| Web regression | 无 titlebar、无 desktop class；普通 document 滚动正常；默认右键及 Ctrl+R 未被阻止；AuthGate 复制粘贴通过；实际外链 popup 保留完整 query/fragment |
| Backend | `python -m pytest -q`：148 passed；327 条现有 Python 3.14/FastAPI/Pydantic 警告，没有失败 |
| Device Client | 20 passed |
| Rust | `cargo test --release --target x86_64-pc-windows-msvc`：2 passed；保留现有 browser_url 校验 |
| OpenClaw CI regression | runtime 11 passed；plugin build / plugin:build / validate 成功，plugin 13 passed；没有实现变更 |
| Frontend | Web build、desktop frontend build 均成功，无 TS/Vue 错误 |
| Packaged sidecar | `scripts/smoke-backend-sidecar.py` 通过（Agent scope/create/replay/audit、六类离线 outbox/tombstone、持久化、登录） |
| Windows bundle | `npm run desktop:build` 成功生成 0.5.5 NSIS；QA 构建后重新使用默认配置生成正式产物并检查无测试登录注入 |

浏览器中的 Desktop 页面检查模拟 Tauri IPC，只验证 DOM、事件和布局；不把这些结果当作原生窗口控制、Windows Snap 或系统托盘的实机证明。

可复现的关键逻辑测试：运行 `npm run test:desktop`。DOM 测试先启动 `npm run dev`，再使用 Playwright CLI 打开本地页面并执行 `tests/desktop-interactions.browser.js`；此脚本应在普通 Web 上下文运行。

## Packaged Windows 验收

使用实际 release EXE + 打包 sidecar；独立标识 `com.isidel.nexa.shell-20260930`、独立数据库和测试账户 `desktop_shell_qa`。QA fixture 只预置一个测试网站与缓存天气，不操作正式数据库、secret.key 或 0.5.1 安装目录。

| 实机项 | 结果 |
| --- | --- |
| 标题栏/玻璃/粗滚动条 | 已观察到无白色系统标题栏、Nexa custom titlebar 与细内容滚动条；账本内部细条修正后消失 |
| Backend error 状态 | 实际 QA 后端停止时错误面板与 titlebar/控制按钮均保留，无 document 粗滚动条 |
| 最大化/还原 | 原生窗口尺寸变化正确；还原图标随实际状态更新；还原后恢复原先尺寸 |
| 标题栏双击 | Tauri drag region 双击可最大化 |
| 原生右键 | 首页空白、Sidebar、首页卡片、网站链接卡片均未出现 WebView 浏览器菜单 |
| 原生搜索 / 快捷键 | Ctrl+K 打开并聚焦搜索；输入测试文本后 F5、Ctrl+R、Ctrl+Shift+R 均保留原搜索文本和浮层；Ctrl+P / Ctrl+S 不出现打印/保存界面 |
| 原生剪贴板 | 搜索输入 Ctrl+A 选中文字与测试文本一致；Ctrl+C → Backspace → Ctrl+V 后再次读取确认原文本恢复 |
| 原生外链 | 左键点击测试网站后 Edge 新增一个标签，读取标签 URL 确认完整 `https://example.com/?nexa_qa=explicit#check`；Nexa 保留网站页；随后关闭该测试标签 |
| 最小化 | 点击自绘按钮后原生工具返回窗口已最小化，主进程与后端继续运行 |
| 自绘 X / hide | 点击 X 后可见窗口列表中 QA 窗口消失，主进程 PID 与健康的后端仍在 |
| Single instance | 实际再次启动 QA EXE 后恢复既有窗口，首轮主进程 PID 24976 不变；中间 release 的最小化、X 隐藏和第二次启动恢复也已回归，PID 51428 不变；最终配置保留原有 Rust 实现 |
| 原生内容滚动 | 首页、智能体、数据、账本、设置的长内容滚轮移动内容；titlebar、Sidebar、页面顶部控件保持固定；标题栏和 Sidebar 上滚轮不会带动主内容 |
| 最终卡片 / 底部 | 实机滚到底后最后一排卡片完整，悬停首张卡片上缘完整、玻璃模糊保留；最终 release 普通窗口、最大化和还原后，壁纸原有的整条底部黑边均消失；状态图标同步正确 |
| 标题栏拖动 | 用户人工验收通过；自动工具未取得可信的位置变化证据，未将工具拖拽当成证明 |
| 边缘 / 角落 resize | 用户人工验收通过；工具遇到 user input 检测后停止，未继续干扰用户 |
| Snap / 托盘菜单 | 用户人工验收通过：Snap、托盘“打开 Nexa”与“退出 Nexa”；工具没有可访问的系统托盘界面 |

原生窗口操作使用实际打包产物；`sky.launch_app` 只激活现有窗口不算 single-instance 证明，因此该项另以确实启动第二个 EXE 的方式验证。图片和文本快照偶尔早于渲染更新，剪贴板与隐藏等结果均以随后的新快照判定。

## 产物与截图

- 正式 NSIS：`src-tauri/target/x86_64-pc-windows-msvc/release/bundle/nsis/Nexa_0.5.5_x64-setup.exe`，43,628,268 bytes。
- NSIS SHA256：`A118DB3165CA8DA9CAA05EA41671525C4E8002A0F87E1E81AC72811C2980F00F`。
- 最终隔离 QA release：`output/windows-qa-shell-wallpaper/Nexa.exe`，SHA256 `8429FA4680F8386A03EDBC1D36BCDFD05D62B01A5B8442C690906250A901A423`。
- 正式构建的 `dist` 已确认没有 `qa-fixture.js` 或测试 access-token 注入。
- 新的实际 Windows 窗口截图：`output/nexa-desktop-shell-2026-09-30.png`，1283×803（含默认原生边框，客户区为 1280×800）；可见自绘玻璃标题栏、固定 Sidebar 和细内容滚动条，底部壁纸黑边已消失。最大化修复截图：`output/nexa-desktop-shell-max-2026-09-30.png`，1707×1067。

修改文件共 12 个：`package.json`、`src-tauri/tauri.conf.json`、`src-tauri/capabilities/default.json`、`src/main.ts`、`src/App.vue`、`src/pages/DashboardPage.vue`、`src/components/desktop/DesktopTitleBar.vue`、`src/desktop/desktopInteractions.ts`、`src/desktop/desktop.css`、`tests/desktop-shortcuts.test.mjs`、`tests/desktop-interactions.browser.js`、本报告。

## 交付状态与限制

本报告随 `Polish the v0.5.5 desktop shell` 本地提交交付；具体 SHA 和最终 diff 统计见交付回复或 `git show --stat HEAD`。未 push、未打 tag、未创建 Release。QA EXE、注入脚本、截图、临时 fixture 均位于被忽略的 output 目录，不进入 Git。临时浏览器与 Vite 已关闭，修复后的隔离 QA 窗口保留供查看；原安装的进程因同用 17800 端口已暂时停止，安装文件和正式数据未改。

Windows 工具的可访问窗口列表没有系统托盘界面；标题栏拖拽自动输入也未取得可靠的位置变化证据。标题栏拖动、边缘/角落缩放、Snap 和托盘菜单采用用户回复“我的操作验证通过”的人工验收证据；最终原生 shadow/resizable 配置与该轮一致，后续只修正壁纸绘制和卡片内容边缘。卡片裁切和壁纸黑边的最终回归通过。正式 0.5.1 安装/覆盖升级向导及 PostgreSQL 集成 CI 本轮不执行。

`git diff --check` 通过。提交范围共 12 个文件，QA 产物、截图和 fixture 均被 Git 忽略。提交后再检查 git status；最终 SHA、统计和工作区状态记录在交付回复中，避免报告嵌入自身提交 SHA。

## 32 项交付核对

| # | 要求 | 结果 / 对应证据 |
| --- | --- | --- |
| 1 | Commit SHA | 本地提交 `Polish the v0.5.5 desktop shell`；具体 SHA 见交付回复 / git log -1 |
| 2 | 修改文件 | 上述 12 个文件 |
| 3 | Custom titlebar | 36px / 真实 Tauri Window API / runtime isTauri |
| 4 | decorations | false，其他窗口与打包身份配置保持 |
| 5 | Window permissions | core:default + 4 项最小窗口权限，schema 与 release build 通过 |
| 6 | minimize/maximize/close | 原生均已验证；close 调用窗口 close |
| 7 | close-to-tray | X 隐藏，进程和后端继续；托盘菜单人工通过 |
| 8 | single-instance | 启动第二个 EXE 恢复现有窗口，PID 不变 |
| 9 | Desktop viewport | titlebar + 剩余 flex 视口 + Sidebar/main |
| 10 | document scrollbar | 27 个浏览器场景与实际原生窗口均无 document 粗滚动条 |
| 11 | internal scroll | dashboard-scroll / workspace-content，Modal 独立滚动 |
| 12 | scrollbar visual | thin / 5px / 透明轨道 / 圆角半透明 thumb |
| 13 | context menu | Desktop 全部禁用，含输入框；Web 保留 |
| 14 | input clipboard | 浏览器 input/textarea/Modal 与原生搜索往返复制粘贴通过 |
| 15 | blocked shortcuts | F5 / Ctrl+R / Ctrl+Shift+R / Ctrl+P / Ctrl+S 原生通过；Ctrl+L/U 纯逻辑测试通过 |
| 16 | preserved shortcuts | Ctrl+K 原生通过；C/V/A 原生通过，X/Z/Y 逻辑确认不拦截 |
| 17 | user-select | Chrome 不选中；正文/编辑区/显式 opt-in 保留 |
| 18 | drag | img/a/svg ghost drag 禁用；编辑区/opt-in/drop 保留 |
| 19 | external opener | 原生 Edge 新标签完整 URL 已观察；原 helper/Rust 未改 |
| 20 | Web regression | 无 Desktop bar；自然滚动/默认菜单/快捷键/剪贴板/完整 URL 通过 |
| 21 | Backend pytest | 148 passed，327 条现有警告 |
| 22 | Device tests | 20 passed |
| 23 | Rust tests | release 2 passed |
| 24 | Frontend builds | Web / Desktop 均通过 |
| 25 | Tauri / NSIS | 完整 desktop:build 通过，默认身份的正式 NSIS 已重建 |
| 26 | Packaged smoke | Sidecar smoke 与实际隔离 release EXE 已验证 |
| 27 | titlebar controls / drag | minimize/maximize/X/双击原生工具通过；拖动人工通过 |
| 28 | tray | 打开/退出菜单人工通过 |
| 29 | Snap / resize | 用户人工通过；最终恢复相同原生 shadow/resizable 配置，未用 DOM 模拟代替 |
| 30 | diff --stat | 12 个文件；具体行数见交付回复 / git show --stat HEAD |
| 31 | git status | 提交后检查工作区；未 push/tag/Release |
| 32 | known limitations | 托盘/Snap/resize/拖动的人工证据见上；正式安装升级与 PostgreSQL 集成 CI 未运行；正式安装程序没有覆盖旧安装，当前展示隔离 QA 版本 |
