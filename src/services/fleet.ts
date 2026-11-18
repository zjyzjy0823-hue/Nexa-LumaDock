/**
 * Studiolo Fleet 控制面 HTTP 与 WebSocket URL 服务。
 */

import { apiRequest } from '../api/client'
import type { AgentNode, NodePlatform, NodeTokenOut } from '../types/fleet'

export { buildFleetWsUrl, getApiBaseUrl } from './fleetUrl'

export const listFleetNodes = (token: string) => apiRequest<AgentNode[]>('/api/v1/fleet/nodes', {}, token)

export const createFleetNode = (
  token: string,
  payload: { name: string; platform: NodePlatform; hostname?: string | null },
) =>
  apiRequest<NodeTokenOut>(
    '/api/v1/fleet/nodes',
    { method: 'POST', body: JSON.stringify(payload) },
    token,
  )

export const updateFleetNode = (
  token: string,
  nodeId: string,
  payload: { name?: string; platform?: NodePlatform; hostname?: string | null },
) =>
  apiRequest<AgentNode>(
    `/api/v1/fleet/nodes/${nodeId}`,
    { method: 'PATCH', body: JSON.stringify(payload) },
    token,
  )

export const rotateFleetNodeToken = (token: string, nodeId: string) =>
  apiRequest<NodeTokenOut>(`/api/v1/fleet/nodes/${nodeId}/token`, { method: 'POST' }, token)

export const revokeFleetNode = (token: string, nodeId: string) =>
  apiRequest<AgentNode>(`/api/v1/fleet/nodes/${nodeId}/revoke`, { method: 'POST' }, token)

export const deleteFleetNode = (token: string, nodeId: string) =>
  apiRequest<void>(`/api/v1/fleet/nodes/${nodeId}`, { method: 'DELETE' }, token)
