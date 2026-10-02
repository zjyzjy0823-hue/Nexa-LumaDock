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
  queueSeeded: boolean
  lastSuccessAt: string | null
}
export interface SyncRunResult extends SyncCounts {
  status: 'ok' | 'error'
  pushed: number
  pulled: number
  workspaceRevision: number | null
}

export const getSyncStatus = (token: string) => apiRequest<SyncStatus>('/api/v1/sync/status', {}, token)
export const runSync = (token: string) => apiRequest<SyncRunResult>('/api/v1/sync/run', { method: 'POST' }, token)
