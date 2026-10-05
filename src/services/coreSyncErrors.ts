import { ApiError } from '../api/client'
import type { SyncStatus } from '../api/sync'

const syncErrors: Record<string, string> = {
  protocol_mismatch: 'Core 与本机同步协议不兼容',
  unreachable: '无法连接 Core',
  timeout: '连接 Core 超时，请检查网络',
  unauthorized: 'Core Client 凭证无效，需要重新连接或修复',
  invalid_client: 'Core Client 无效，需要重新连接或修复',
  workspace_binding_conflict: '本地同步数据已绑定其他 Core 身份，需要检查连接',
  invalid_connection: '本机保存的 Core 连接信息无效，需要重新连接',
  invalid_response: 'Core 返回的同步数据无效',
  invalid_local_state: '本地同步状态异常',
  ownership_conflict: '同步数据的工作区归属不一致',
  missing_category: '同步数据缺少关联分类',
  category_not_found: '同步数据的关联分类不存在',
  collection_not_found: '同步数据的关联集合不存在',
  missing_collection: '同步数据缺少关联集合',
  collection_id_immutable: '同步记录不能更改所属集合',
  unknown_entity_type: '同步数据类型不受支持',
  internal_error: '本机同步未完成，请检查本机后端',
}

// Never render an arbitrary server body, traceback, URL or credential.
export function syncErrorMessage(code: string | null): string {
  if (!code) return '同步失败'
  return Object.prototype.hasOwnProperty.call(syncErrors, code) ? syncErrors[code]! : '同步失败（未知错误）'
}

export function syncStatusDisplay(status: SyncStatus, now = Date.now()) {
  const changes = status.pending + status.inFlight
  if (status.running) return { label: '正在同步…', detail: changes ? `${changes} 个本地更改` : '正在检查 Core 的更改', tone: 'active' }
  if (status.conflicts || status.rejected) {
    const problems = [status.conflicts ? `${status.conflicts} 个同步冲突` : '', status.rejected ? `${status.rejected} 个更改已被拒绝` : ''].filter(Boolean)
    return { label: '需要处理', detail: problems.join('，'), tone: 'warning' }
  }
  if (status.blocked) return { label: '需要处理', detail: syncErrorMessage(status.lastError), tone: 'warning' }
  if (!status.connected) return { label: '等待同步', detail: changes ? `${changes} 个更改已安全保存在本机，连接 Core 后将自动同步` : '连接 Core 后将自动同步', tone: 'waiting' }
  if (status.lastError === 'unreachable' || status.lastError === 'timeout') {
    return { label: 'Core 离线', detail: changes ? `${changes} 个更改已安全保存在本机` : '本机数据已安全保存，后台将自动重试', tone: 'waiting' }
  }
  if (status.lastError) return { label: '需要处理', detail: syncErrorMessage(status.lastError), tone: 'warning' }
  if (changes) return { label: '等待同步', detail: `${changes} 个本地更改`, tone: 'waiting' }
  if (!status.enabled || !status.lastSuccessAt) return { label: '等待同步', detail: '等待后台检查 Core 的更改', tone: 'waiting' }
  const elapsed = now - new Date(status.lastSuccessAt).getTime()
  const detail = elapsed >= 0 && elapsed < 60_000 ? '刚刚' : '本地更改已同步'
  return { label: '已同步', detail, tone: 'success' }
}

const connectionErrors: Record<string, string> = {
  'Core login failed': 'Core 用户名或密码不正确',
  'Client credential is unavailable': 'Core Client 凭证无效，需要重新连接或修复',
  'Core connection already exists': '已保存 Core 连接，请刷新连接状态',
  'Core connection is not configured': '尚未连接 Core',
  'Sync is already running for this workspace': '此工作区正在同步，请稍后再试',
  'Invalid Core URL': '请输入有效的 Core HTTP 或 HTTPS 地址',
  'Local Core connection is invalid': '本机保存的 Core 连接信息无效',
  'Local Core connection could not be saved': '无法保存本机 Core 连接信息',
  'Local Core connection could not be removed': '无法移除本机 Core 连接信息',
  'Local installation ID is not configured': '本机安装身份尚未配置，请使用 Nexa Desktop',
  'Core is unreachable': '无法访问 Core，请检查地址和网络',
  'Target is not Nexa Core': '目标服务不是 Nexa Core',
  'Core redirect is not allowed': 'Core 地址不能重定向，请输入直接地址',
  'Core Client is revoked': '此设备的 Core Client 已被撤销',
  'Core enrollment state is inconsistent': 'Core 设备注册状态不一致',
  'Local sync state is bound to a different Core identity': '本地同步数据已绑定其他 Core 身份，不能直接切换',
}

export function coreSyncRequestError(error: unknown): string {
  if (!(error instanceof ApiError)) return '操作未完成，请重试'
  if (typeof error.message === 'string' && Object.prototype.hasOwnProperty.call(connectionErrors, error.message)) return connectionErrors[error.message]!
  switch (error.status) {
    case 0: return '无法连接到 Nexa 本机后端'
    case 401: return '本机登录已过期，请重新登录'
    case 404: return 'Core 连接和同步仅在 Nexa Local 中可用'
    case 409: return '连接或同步状态发生变化，请刷新后重试'
    case 422: return '请检查 Core 地址、用户名和设备名称'
    case 502: return 'Core 请求未完成，请检查服务和网络'
    case 500: return '本机连接或同步状态异常，请检查本机后端'
    default: return '操作未完成，请稍后重试'
  }
}
