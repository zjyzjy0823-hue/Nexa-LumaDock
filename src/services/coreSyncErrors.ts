import { ApiError } from '../api/client'

const syncErrors: Record<string, string> = {
  protocol_mismatch: 'Core 与本机同步协议不兼容',
  unreachable: '无法连接 Core',
  timeout: '连接 Core 超时，请检查网络',
  unauthorized: 'Core Client 凭证无效，需要重新连接或修复',
  invalid_response: 'Core 返回的同步数据无效',
  invalid_local_state: '本地同步状态异常',
  ownership_conflict: '同步数据的工作区归属不一致',
  missing_category: '同步数据缺少关联分类',
}

// Never render an arbitrary server body, traceback, URL or credential.
export function syncErrorMessage(code: string | null): string {
  if (!code) return '同步失败'
  return syncErrors[code] ?? '同步失败（未知错误）'
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
  if (typeof error.message === 'string' && connectionErrors[error.message]) return connectionErrors[error.message]
  switch (error.status) {
    case 0: return '无法连接到 Nexa 本机后端'
    case 401: return '本机登录已过期，请重新登录'
    case 404: return 'Core 连接和手动同步仅在 Nexa Local 中可用'
    case 409: return '连接或同步状态发生变化，请刷新后重试'
    case 422: return '请检查 Core 地址、用户名和设备名称'
    case 502: return 'Core 请求未完成，请检查服务和网络'
    case 500: return '本机连接或同步状态异常，请检查本机后端'
    default: return '操作未完成，请稍后重试'
  }
}
