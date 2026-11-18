/**
 * Studiolo Fleet URL 辅助（无框架/DOM 依赖，可在浏览器与 Node 测试环境下复用）。
 */

export function getApiBaseUrl(): string {
  const env = (import.meta as { env?: Record<string, string | undefined> }).env
  return (env?.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')
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
