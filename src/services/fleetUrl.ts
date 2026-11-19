/**
 * Studiolo Fleet URL 辅助（无框架/DOM 依赖，可在浏览器与 Node 测试环境下复用）。
 */

let configuredOrigin: string | undefined

export function setApiBaseUrl(origin: string): void {
  configuredOrigin = origin
}

export function getApiBaseUrl(): string {
  const env = (import.meta as { env?: Record<string, string | undefined> }).env
  return (configuredOrigin ?? env?.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')
}

export function normalizeCoreOrigin(value: string): string {
  const url = new URL(value.trim())
  const loopback = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) {
    throw new Error('请输入 HTTPS Core 地址。本机回环地址可使用 HTTP。')
  }
  if (url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Core 地址只能包含协议、主机和端口。')
  }
  return url.origin
}

/**
 * 构造 `/ws/fleet/client` WebSocket URL。
 * 安全约束：严禁将 JWT 写入 `?token=` URL 查询串，认证统一在建连后首帧 JSON 完成。
 */
export function buildFleetWsUrl(baseOverride?: string, originOverride?: string): string {
  const rawBase = (baseOverride ?? getApiBaseUrl()).trim().replace(/\/+$/, '')
  const fallbackOrigin =
    originOverride ?? (typeof window !== 'undefined' && window.location?.origin ? window.location.origin : '')
  const effective = rawBase || fallbackOrigin
  if (!effective) return '/ws/fleet/client'
  const wsBase = effective.replace(/^https:\/\//i, 'wss://').replace(/^http:\/\//i, 'ws://')
  return `${wsBase}/ws/fleet/client`
}
