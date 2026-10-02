import { apiRequest } from './client'

export type CorePlatform = 'windows' | 'macos' | 'linux' | 'android' | 'ios' | 'web'
export type CoreConnection = { connected: false } | {
  connected: true
  coreUrl: string
  clientId: string
  workspaceId: string
  installationId: string
  clientName: string
  platform: CorePlatform
  appVersion: string
  connectedAt: string
}
export type CoreConnectionTest =
  | { connected: true; status: 'connected' }
  | { connected: false; status: 'disconnected' | 'unauthorized' | 'unreachable' }
export interface CoreConnectRequest {
  coreUrl: string
  username: string
  password: string
  clientName: string
  platform: CorePlatform
  appVersion: string
}

export const getCoreConnection = (token: string) => apiRequest<CoreConnection>('/api/v1/core/connection', {}, token)
export const connectCore = (token: string, payload: CoreConnectRequest) =>
  apiRequest<CoreConnection>('/api/v1/core/connect', { method: 'POST', body: JSON.stringify(payload) }, token)
export const testCoreConnection = (token: string) =>
  apiRequest<CoreConnectionTest>('/api/v1/core/connection/test', { method: 'POST' }, token)
export const disconnectCore = (token: string) =>
  apiRequest<{ connected: false }>('/api/v1/core/connection', { method: 'DELETE' }, token)
