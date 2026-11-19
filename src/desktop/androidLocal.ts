import { invoke } from '@tauri-apps/api/core'
import { desktopPlatform } from './platform'

export const isAndroidLocal = () => desktopPlatform() === 'android'

export interface AndroidBinding {
  installationId: string
  coreUrl: string | null
  workspaceId: string | null
  workspaceName: string | null
  clientId: string | null
  clientName: string | null
  appVersion: string | null
  connectedAt: string | null
  status: 'disconnected' | 'connected' | 'revoked'
}

export interface PairingPreview {
  confirmationId: string
  coreUrl: string
  workspaceId: string
  workspaceName: string
}

const errors: Record<string, string> = {
  invalid_data: '请检查输入内容。若同步冲突已变化，请刷新后重试。',
  invalid_core_url: '请输入 Core HTTPS 地址。HTTP 仅支持回环地址。',
  not_found: '这条本机记录已不存在，请刷新后重试。',
  category_not_found: '所选网站分类已不存在。',
  connection_binding_mismatch: '本机副本已绑定其他 Core 身份，请使用原账号或新建独立副本。',
  client_revoked: 'Core 已吊销此安装身份，请新建独立副本后配对。',
  workspace_confirmation_expired: '工作区确认已过期，请重新连接。',
  invalid_credentials: 'Core 用户名或密码不正确。',
  unauthorized: 'Core Client 凭据失效，请重新授权。',
  disconnected: '请先连接 Core。',
  network_error: '无法连接 Core，请检查地址和网络。',
  invalid_response: 'Core 返回的数据格式无效。',
  sync_protocol_mismatch: 'Core 与本机的同步协议不兼容。',
  sync_in_progress: '正在同步，请稍后重试。',
  snapshot_expired: 'Core 快照已过期，请重试。',
  resync_required: '同步游标已失效，正在重新获取数据。',
  credential_storage: '无法读写 Android 安全存储。',
  local_database: '无法读写本机数据库。',
  local_database_migration: '无法初始化本机数据库。',
}

export class AndroidLocalError extends Error {
  constructor(public code: string) {
    super(Object.prototype.hasOwnProperty.call(errors, code) ? errors[code] : '本机操作未完成，请重试。')
  }
}

export async function androidInvoke<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  try { return await invoke<T>(command, args) }
  catch (error) { throw new AndroidLocalError(typeof error === 'string' ? error : '') }
}
