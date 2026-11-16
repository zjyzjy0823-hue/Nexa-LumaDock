# Android 凭据与配对决策

Android APP 的同步身份是 Client，设备遥测身份是 Device。两种令牌用途独立，不得混用，也不使用账号 JWT 进行后台同步。

| 用途 | 凭据 | 现有 API |
| --- | --- | --- |
| 工作区同步 | Client 凭据 `nc_live_` | `/api/v1/sync/changes`、`/api/v1/sync/mutations`、`/api/v1/sync/snapshot`，使用现有同步协议 |
| 设备遥测 | Device Token `nd_live_` | `POST /api/device/heartbeat` |

两者均使用 Android Keystore 保护：Keystore 保存不可导出的加密密钥，令牌加密后保存在应用私有存储中；按 Core 地址、工作区 ID、Client/Device ID 分隔存储。令牌不写日志、普通偏好、明文文件或备份，不经 UI 明文回显。当前仓库的桌面文件凭据存储不作为 Android 的安全存储实现。

## 配对与工作区

沿用 **POST /api/v1/core/connect**：用户手工输入 Core 地址、账号和密码，不接受扫码配对。此端点属于 Local 连接桥接层，需要本地用户 JWT，不是直接发给 Core 的请求。Android 的配对交互沿用这条流程，平台参数为 `android`，不新增二维码、配对码或兑换令牌端点。

请求字段为 `coreUrl`、`username`、`password`、`clientName`、`platform`、`appVersion`。连接桥接层依次访问 Core 的 `/api/health`、`POST /api/v1/auth/login`、`GET /api/v1/workspace`、`POST /api/v1/clients/enroll`，最后以新 Client 凭据访问 `GET /api/v1/client/me` 校验身份。密码和临时 Core JWT 只用于此次授权，不长期保存；Android 平台应将取得的 Client 凭据交给 Keystore 保护的存储。

工作区选择遵循现有 API：`GET /api/v1/workspace` 返回登录账号的 Personal Workspace，配对返回的 `workspaceId` 必须与 Client 的工作区一致。当前没有任意工作区列表、工作区选择参数或切换端点；界面展示并确认账号对应的工作区。需要另一工作区时，更换对应账号重新连接，不允许客户端随意指定 workspaceId。Local 副本已有同步状态绑定不同 Core/工作区/Client 时会拒绝同步，不能通过清空游标绕过绑定；保留原副本，使用独立本地副本建立新绑定。

## 设备遥测授权

设备身份单独创建：用户 JWT 调用 `POST /api/v1/devices` 建立设备，再调用 **POST /api/v1/devices/{id}/token** 获取 `nd_live_`，放入 Android Keystore 保护的存储。Client 凭据不能替代此管理授权，也不能用 Device Token 访问同步 API。遥测请求使用 `Authorization: Bearer <device-token>`，只携带遥测字段；令牌本身不出现在日志、UI 或导出文件中。

## 吊销、失效与重新授权

- 同步 Client 的吊销在 Core 上以账号 JWT 调用 **POST /api/v1/clients/{id}/revoke**。它标记 Client 已吊销并清除其令牌哈希；旧 `nc_live_` 随后返回 **401**。本地 `DELETE /api/v1/core/connection` 仅删除连接和本地凭据，不等于 Core 吊销。
- Client 令牌缺失、轮换或被吊销导致 401 时，停止自动同步，保留待同步修改及事件，界面提示重新授权；不无限重试、不使用 Device Token 降级认证。网络不可达时保留队列，按现有同步退避重试，不能将网络错误误判为密码错误。
- 用户确认 Core 地址与账号后，先删除失效的本地连接，再通过 `POST /api/v1/core/connect` 重新输入账号密码。未吊销的同一 installationId 若已 enrolled，现有桥接流程读取 `GET /api/v1/clients`，再调用 `POST /api/v1/clients/{id}/credential` 轮换凭据。成功后验证 `/api/v1/client/me`、原子替换安全存储，再恢复相同身份绑定的同步。
- 已吊销 Client 重新 enroll 或轮换会返回 **409**，不得自动复活。用户明确选择重新授权后，建立新的安装身份并 enroll 新 Client；由于它是新的绑定，使用独立本地副本，旧副本待同步数据保留供用户处理，不能静默迁移或丢弃。
- Device Token 的撤销独立使用 **DELETE /api/v1/devices/{id}/token**；需要恢复遥测时，以用户 JWT 再次调用 `POST /api/v1/devices/{id}/token`，旧令牌立即失效。Device Token 401 只暂停遥测，不影响有效的 Client 同步；Client revoke 也不会自动吊销 Device Token。丢失设备时需分别撤销两种凭据。

现有 Client 和 Device Token 没有固定有效期字段，不预设到期日期或刷新令牌协议。Core 登录 JWT 的有效期与这两种长期令牌不同；授权阶段登录失败时让用户重新输入账号密码，不保存密码用于静默重登。
