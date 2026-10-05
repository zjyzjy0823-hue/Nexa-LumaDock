import { apiRequest } from '../api/client'

export interface Diagnostics {
  appVersion: string
  mode: 'local' | 'core'
  backend: string
  database: { kind: string; status: string }
  workspaceId: string | null
  core: { status: string; url: string | null; workspaceId: string | null; clientId: string | null; tokenConfigured: boolean } | null
  sync: { pending: number; rejected: number; conflicts: number; inFlight: number; lastSuccessAt: string | null; lastError: string | null } | null
  protocol: { local: number; core: number | null; compatible: boolean | null }
  automation: Record<'local' | 'core', { scheduler: boolean | null; worker: boolean | null }>
}

export function getDiagnostics(token: string) {
  return apiRequest<Diagnostics>('/api/v1/settings/diagnostics', {}, token)
}

export function diagnosticsRows(value: Diagnostics) {
  const runtime = (enabled: boolean | null) => enabled === null ? '未知' : enabled ? 'ON' : 'OFF'
  const statuses: Record<string, string> = { connected: '已连接', disconnected: '未连接', unauthorized: '认证不可用', unreachable: '无法连接', unavailable: '不可用' }
  return [
    ['App Version', value.appVersion],
    ['Backend', `${value.mode === 'local' ? 'Local' : 'Core'} / ${value.backend}`],
    ['Database', `${value.database.kind} / ${value.database.status}`],
    ['Core', value.core ? (statuses[value.core.status] ?? '未知') : '当前为 Core'],
    ['Core URL', value.core?.url ?? '—'],
    ['Workspace', value.workspaceId ?? '不存在'],
    ['Core Workspace', value.core?.workspaceId ?? '—'],
    ['Client', value.core?.clientId ?? '—'],
    ['Client Token', value.core?.tokenConfigured ? '已配置' : '未配置'],
    ['Sync', value.sync ? `最近成功：${value.sync.lastSuccessAt ?? '尚无记录'}；Pending: ${value.sync.pending} · Rejected: ${value.sync.rejected} · Conflicts: ${value.sync.conflicts} · In Flight: ${value.sync.inFlight}` : 'Core 模式'],
    ['Sync Error', value.sync?.lastError ?? '—'],
    ['Protocol', `Local: ${value.protocol.local} · Core: ${value.protocol.core ?? '未知'} · ${value.protocol.compatible === null ? '尚未验证' : value.protocol.compatible ? '兼容' : '不兼容'}`],
    ['Automation Runtime', `Local Scheduler: ${runtime(value.automation.local.scheduler)} · Local Worker: ${runtime(value.automation.local.worker)} · Core Scheduler: ${runtime(value.automation.core.scheduler)} · Core Worker: ${runtime(value.automation.core.worker)}`],
  ]
}

// Copy only fields shown to the user; never serialize an entire server response.
export function diagnosticsText(value: Diagnostics) {
  return ['Nexa Diagnostics', ...diagnosticsRows(value).map(([label, text]) => `${label}: ${text}`)].join('\n')
}
