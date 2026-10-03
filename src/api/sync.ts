import { apiRequest } from './client'

export interface SyncCounts {
  pending: number
  conflicts: number
  inFlight: number
  rejected: number
  cursor: number
  lastError: string | null
}
export interface SyncStatus extends SyncCounts {
  enabled: boolean
  running: boolean
  connected: boolean
  blocked: boolean
  queueSeeded: boolean
  lastAttemptAt: string | null
  lastSuccessAt: string | null
  nextRetryAt: string | null
}
export interface SyncRunResult extends SyncCounts {
  status: 'ok' | 'error'
  pushed: number
  pulled: number
  workspaceRevision: number | null
}

export const getSyncStatus = (token: string, signal?: AbortSignal) => apiRequest<SyncStatus>('/api/v1/sync/status', { signal }, token)
export const runSync = (token: string) => apiRequest<SyncRunResult>('/api/v1/sync/run', { method: 'POST' }, token)
