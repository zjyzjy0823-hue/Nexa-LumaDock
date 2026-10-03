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

export type SyncEntityType = 'ledger.category' | 'ledger.transaction' | 'website.category' | 'website' | 'data.collection' | 'data.record'
export type ConflictStrategy = 'local' | 'remote'
export type ConflictPayload = Record<string, unknown>
export interface SyncConflict {
  id: string
  entityType: SyncEntityType
  entityId: string
  local: ConflictPayload | null
  localDeleted: boolean
  remote: ConflictPayload | null
  remoteRevision: number
  remoteDeleted: boolean
  createdAt: string
  detectedAt: string
  updatedAt: string
  hasPendingTail: boolean
}
export interface ConflictResolution {
  id: string
  strategy: ConflictStrategy
  status: 'resolved'
  remoteRevision: number
  mutationId: string | null
  resolvedAt: string
}

export const getSyncConflicts = (token: string, signal?: AbortSignal) => apiRequest<{ conflicts: SyncConflict[] }>('/api/v1/sync/conflicts', { signal }, token)
export const getSyncConflict = (token: string, id: string, signal?: AbortSignal) => apiRequest<SyncConflict>(`/api/v1/sync/conflicts/${encodeURIComponent(id)}`, { signal }, token)
export const resolveSyncConflict = (token: string, id: string, strategy: ConflictStrategy, expectedRemoteRevision: number) =>
  apiRequest<ConflictResolution>(`/api/v1/sync/conflicts/${encodeURIComponent(id)}/resolve`, { method: 'POST', body: JSON.stringify({ strategy, expectedRemoteRevision }) }, token)
