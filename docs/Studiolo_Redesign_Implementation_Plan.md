# Studiolo 重设计落地方案

**基线** `main @ 3537e1f`　｜　**日期** 2026-11-17

**采用 Opus 的工作台设计，Liquid Glass 为默认主题，纸墨可选。** 桌面端围绕浏览、编辑和对照，Android 围绕快速记录、查找和跟进。两端共用主题定义、业务语义和状态文字，各自安排导航和详情布局。第一批用真实的「今天 → 网站 → 收藏 → 同步」验证新版界面。Agent 首个集成对象建议按当前方向收敛为 Hermes。

本方案依据开源项目的官方文档、界面截图和公开源码，以及 Studiolo 的现有 Vue、Tauri、同步契约与静态原型。外部产品按指定场景做参考对照，部署表现、Android 真机和 Hermes 真服务需要在对应阶段联调。 [原型入口](../design/studiolo-redesign/index.html) · [版本路线图](Studiolo_Development_Roadmap_v0.6.2-v1.0.md) · [架构与安全设计](architecture-plan-v0.6.2.md)

## 1. 开源设计对照与取舍

| 参考项目 | 看到的设计 | Studiolo 的取舍 |
| --- | --- | --- |
| **Actual Budget** | 账本标题、余额与新增／筛选靠在一起，搜索独立放在另一侧。账户列表在左侧，服务器状态与手动同步是两个控件。 [账本截图与交互](https://actualbudget.org/docs/tour/accounts/) · [界面概览](https://actualbudget.org/docs/tour/user-interface/) | 桌面账本采用紧凑工具条和表格，详情就地展开。把「Core 连通」和「保存／同步」分开。手机快捷记账优先金额、收支和分类，保存后回到原位置。银行对账、账户体系等额外业务单独评估。 |
| **Linkwarden** | 新增收藏先突出 URL 和集合，名称、标签、说明位于可展开的选项中，保存按钮在底部。 [新增收藏截图](https://docs.linkwarden.app/usage/links) · [收藏分类模型](https://docs.linkwarden.app/usage/overview) | 手机接收分享时先预填 URL，名称与分组按现有 Studiolo 规则提供默认值或可编辑字段。桌面保留搜索和筛选，呈现已有分类及标签。首批工作沿用现有模型，网页快照、全文索引和标签扩展单独评估。 |
| **Home Assistant** | 总览顶部用少量全局状态，内容卡按用途分区。Quick Search 可带用户跳往相关页面。Trace 可从一次运行进入时间线与步骤详情。 [总览截图](https://www.home-assistant.io/dashboards/sections/) · [快捷搜索](https://www.home-assistant.io/docs/tools/quick-search) · [运行追踪](https://www.home-assistant.io/docs/automation/testing/#traces) | 「今天」聚焦同步异常、待处理任务和最近使用，每项可跳至处理位置。桌面命令面板优先页面跳转、搜索和打开表单。任务详情优先呈现结果、时间、原因与来源，按上游证据显示更多细节。 |
| **Cryptomator** | 解锁框明确标出目标保险库，提供取消；解锁后可从虚拟盘继续访问，并提供记住密码选项。 [解锁与锁定截图](https://docs.cryptomator.org/desktop/accessing-vaults/) · [文件加密设计](https://docs.cryptomator.org/security/vault/) | 借鉴「目标清楚、动作明确」的密码框。Studiolo 的确认绑定本次目录页或对象、操作与修订，单个对象和目录分别验密。采用按次输入，无常驻解锁、记住密码或全局明文索引。 |
| **Ionic Vue** | 主标签分别拥有返回栈；从详情返回所在标签，而非按全局访问时间回到另一个标签。 [标签导航示例](https://ionicframework.com/docs/vue/navigation#how-tabs-in-ionic-work) | 复用导航行为，在 Studiolo Vue 里保留「今天 · 资料 · ＋ · 对话 · 任务」。`＋` 是全局动作，取消或保存后回到原标签。只保留普通页面的导航位置，受保护页面按各自的清理规则重开。 |
| **Hy4ri Hermes Mobile** | Android 客户端用 REST 读取会话和历史，用 Gateway WebSocket 处理聊天，同时提供 Cron 管理。它把聊天历史保存在 Room。 [项目说明](https://github.com/Hy4ri/hermes-mobile) · [会话与 Cron 客户端源码](https://github.com/Hy4ri/hermes-mobile/blob/f032f9520ca25e12ef89f3347455902bd2711a9b/app/src/main/java/com/m57/hermescontrol/data/remote/HermesApiService.kt) | 参考鉴权、分页、连接状态和 Cron 操作，沿用 Studiolo 原型的聊天视觉。Studiolo 由 Hermes 提供历史，正文、草稿、流式片段和工具输出只在内存，重新进入时按需取回。 |

## 2. 桌面与手机的产品方案

| 任务 | Windows／macOS | Android |
| --- | --- | --- |
| **找到今天要处理的事** | 「今天」顶部放快捷操作和同步状态，下方按现有组件排列最近收藏、账本摘要和需处理事项。底部状态栏汇总队列、冲突和在线状态。 | 首页显示少量高频动作、最近内容及异常。点异常进入对应详情；日常同步成功留在状态视图。 |
| **查找、编辑和新增资料** | 左侧常驻分组，主区按页面显示工具条、列表和可选详情。窄窗口优先保留列表宽度，详情改为浮层或独立页。命令面板跳转与搜索可访问数据；录入命令打开预填表单。 | 「资料」集中网站、账本、数据及设备。搜索和筛选跟随当前分类；详细编辑用推入页。中间 `＋` 打开快捷表单，单手能完成取消和提交。 |
| **共享小文件、文本、配置与 Key** | 「共享空间」为独立入口，锁定态显示无内容的状态。输入密码后显示当次请求结果，查看对象另开按次密码对话框。 | 「资料」中提供明确入口，可从「今天」快捷进入，沿用同一按次规则，使用底部弹层。未下载密文时明确提示需联网。 |
| **接续 Hermes 对话** | 对话页左侧选择会话，右侧显示消息。侧板使用同一模块；切换全页与侧板不重复发起会话或发送。窄窗口可让侧板覆盖主区。 | 从「对话」进会话列表，再进会话。在会话详情给输入框和软键盘留空间。掉线时标示「连接中断／重新连接」，从 Hermes 恢复历史；离线重开时说明历史暂不可用。 |
| **查和管任务** | Studiolo 和 Hermes 的任务同页筛选。列表放所有者、下次运行和最近状态，详情展开真实执行历史。 | 「任务」优先显示运行中、需关注、最近完成，以及所有者。点进详情看时间线；远程写操作仅在服务可达、权限与能力已验时开放。 |

**主题。** Liquid Glass 是默认主题，集中用在导航、面板和浮层。用户可以切到纸墨。长列表、输入、共享内容与大段正文使用可读的实体表面。深浅色独立于主题，通过一份 CSS 语义变量映射。禁模糊、减少动态效果与平台不支持时各有可用样式。 [现有主题样式](../design/studiolo-redesign/studiolo.css) · [Theme Engine 设计](architecture-plan-v0.6.2.md#theme-engine-design--主题引擎)

**状态。** 保存回执、待同步、已同步和冲突各有含义。「仅本机」用于明确没有同步绑定的情况，不能冒充「待同步」。Core、Hermes 连接状态与每条记录的同步状态分别展示。业务当前只返回全局队列时，首版使用全局提示，条目级状态等有真实数据来源再显示。

**入口。** 手机设置从「今天」的头像进入，设备归「资料」。桌面继续提供已存在的 API 入口，手机 API 归属待定，修正文案与原型的现有不一致。对话和远程任务在接入前按真实能力展示，不出现模拟成功或模拟同步回执。

## 3. Vue 和后端的接入边界

| 交付项 | 实现做法与依赖 |
| --- | --- |
| **主题与界面骨架** | 先把原型 CSS 拆出颜色、材质、尺寸与动效变量，按主题根节点应用。保留现有 AuthGate 和路由路径，把桌面壳、手机壳、命令面板、列表／详情和通用弹层逐步做成 Vue 组件。去掉模拟状态栏、固定 `392px` 外框和试玩说明旁栏。实际交互通过 Vue 模板与数据绑定，原型脚本用于对照行为。现有弹窗若无法覆盖焦点与键盘行为，可评估 Reka UI 的 Dialog。 [应用入口](../src/App.vue) · [原型手机 CSS](../design/studiolo-redesign/mobile.css) · [Reka UI Dialog](https://reka-ui.com/docs/components/dialog) |
| **桌面既有业务** | 继续调用 Websites、Ledger、Data、Dashboard 和 Sync 的现有 service/store。先迁首页、网站和同步入口，再迁账本、数据和其他模块。保留 Data 有界读取与冲突双选；字段级合并只有在新增并验证同步契约后才开放。 [网站 service](../src/services/websites.ts) · [Data service](../src/services/data.ts) · [冲突接口](../src/api/sync.ts) |
| **Android 本地能力** | UI 复用表单、数据类型和状态组件；Android 原生持久化通过受限 Tauri Command 提供网站读写、Outbox 和 Sync 状态，先以 Websites 与桌面打通闭环。SQLite 本地事务同时写入实体与 Outbox，Keystore 保护已注册 Client 凭据。照用 Sync v3 契约、工作区绑定和恢复用例。 [Android 启动分支](../src-tauri/src/lib.rs) · [Android 凭据](android-auth.md) · [同步契约](../packages/contracts/sync-protocol-v3.md) |
| **Hermes Chat** | 先用隔离实例验证一个受支持版本和认证路径。核对两端 WebView 对 REST、WebSocket 鉴权及证书的支持；根据结果评估直连、受限本机桥接或已批准的中转。先给 Vue 提供小型 `HermesAdapter`，覆盖连接、分页、发送、订阅及重连，同一模块供桌面全页／侧板和手机使用。版本及认证见 TBD-05，附件和额外操作见 TBD-07。 [Hermes 官方会话契约](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/gateway-local-sessions.md) |
| **Studiolo／Hermes 任务** | 通过原生 API 读两端定义和运行历史，用 `所有者 + 实例／profile + 原生任务 ID` 标识一项任务。先上线查询与状态，再按支持矩阵开放写操作。远端命令超时先核对原生回执或历史，未知时停止自动补发。现有 Core Automation 只扫描 Studiolo 自有工作流，远端 Cron 由其原生调度器执行。 [Studiolo Automation API](../backend/app/api/automation/routes.py) · [Hermes Cron 路由](https://github.com/NousResearch/hermes-agent/blob/f8acc26834bf1275c34d09ccc3e51250bcd1e26b/hermes_cli/web_routers/cron.py#L3389) |
| **Shared Space** | 先用隔离样例验证密码派生与密文格式，再落独立同步流。Core 保存密文块与必要复制元数据，原有 Sync v3 游标和快照继续服务现有数据。客户端每次从用户取得密码，核对当次操作与权限，使用密文副本完成在线／离线读取。锁定状态、失败诊断、搜索和通知禁止产出私密目录内容。密码恢复、成员范围、明文导出和完整密码学参数仍按各自 TBD。 [Shared Space 安全设计](architecture-plan-v0.6.2.md#shared-space-security-design--安全设计) · [加密文件库候选](https://doc.libsodium.org/secret-key_cryptography/secretstream) · [密文同步参考](https://docs.syncthing.net/specs/untrusted) |

## 4. 开发顺序与退出标准

建议把桌面新壳先作为开发分支上的可跑通业务切片。Android 数据层与 Hermes 协议验证可以独立前进，各有自己的上线门槛。以下是对现有路线图的建议调整，待确认的范围集中列在下一节。

| 批次 | 交付与依赖 | 退出标准 |
| --- | --- | --- |
| **第一批 · 桌面「今天 → 网站」** | 默认 Liquid Glass 与可选纸墨、桌面壳、网站列表与新增表单、同步入口。现有路由将尚未迁移的页面接回原有功能。 | 登录后从新版首页新建网站；Core 离线时保存在本机，重启可查，有连接后可同步。验证表单失败、空状态、窄窗口、键盘操作和既有页面可达。 |
| **v0.7.0 · Android 网站闭环** | 安卓壳、底栏与安全区适配，SQLite、Keystore、Outbox 和前台 v3 同步。 | 真机冷启动、旋转、系统返回和键盘场景正常。断网新增、杀进程重开、重连后桌面读到同一条记录；重复回执与失效游标按既有契约恢复。 |
| **v0.7.1–v0.7.2 · 资料、主题与稳定性** | 完成账本、Data、设备／设置的双端界面，接上现有二选一冲突处理。交付可选 Liquid Glass、Android 分享和 Shared Space 安全原型。 | Windows、macOS、Android 能完成核心读写、离线和冲突处理。纸墨与玻璃、亮暗、关模糊、减少动效均可操作。键盘焦点、TalkBack、放大字体和实际对比度有记录。Shared Space 原型以合成内容验证密码和旧 v3 兼容。 |
| **v0.8.0 · Hermes 文本 Chat 与 Shared Space** | Chat 在 Hermes 联调通过后交付。Shared Space 依赖密码、复制流、保留与导入等设计确认，可以独立开关。 | 同一 Hermes 会话在手机与桌面实际接续，断网重连、丢确认均不重复发送，聊天测试正文未写入持久化位置。Shared Space 验证两端密文、按次验密、错密码、普通令牌、离线已落地内容与缺失密文、重复上传及冲突。 |
| **v0.8.1 · Studiolo／Hermes 任务管理** | 以支持矩阵为准，先读列表与历史，再开远程 CRUD、暂停／恢复与手动执行。 | 两类任务所有者清楚可辨。断开 Studiolo 不影响 Hermes 原生调度；断开 Hermes 不触发 Studiolo 接管。超时呈现未知且可查证。上游只提供最新 N 条历史时按实际能力标示。 |
| **v0.9.0–v1.0.0 · 发布** | 沿用存量数据兼容、安装升级、签名、密文备份恢复和平台性能验收。 | 旧库与旧版客户端兼容组合有取证；真机完成完整工作流，安全回归关闭后才发候选及正式包。 |

第一批优先做一个用真实本机数据的可演示版本。完成后，用同一条「新增收藏 → 看见本机保存 → 恢复联网 → 查到同步结果」路径带着验收 Android，也能及早发现哪些原型交互需要补数据接口。

## 5. 发布范围与待定项

- **首发 Agent 建议。** 以 Hermes 文本聊天和 Studiolo／Hermes 任务为当前首发建议。OpenClaw 新聊天与新 Cron 管理移至候选，已有 OpenClaw Runtime、任务和 Data Actions 继续按原入口回归。原路线图中双 Agent 首发的变更待正式确认。
- **仍须确认的边界。** Hermes 部署与凭据模式、Shared Space 的恢复与导出、聊天附件、主题选择是否跨端同步。完整编号沿用现有架构设计。 [风险与 TBD](architecture-plan-v0.6.2.md#risk-register-and-tbd-decisions--风险与待定)
- **上游取证。** 参考研究使用了官方发布截图与源码。研发阶段需记录 Hermes 支持版本、认证方式与 profile 隔离实测，Android 真机需验证后退、输入法与长时间离线恢复。浏览器原型只作设计基线。
