import { apiRequest, ApiError } from './client'
import { androidInvoke, isAndroidLocal } from '../desktop/androidLocal'

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

export const getSyncStatus = (token: string, signal?: AbortSignal) =>
  isAndroidLocal() ? androidInvoke<SyncStatus>('android_sync_status') : apiRequest<SyncStatus>('/api/v1/sync/status', { signal }, token)
export const runSync = (token: string) => apiRequest<SyncRunResult>('/api/v1/sync/run', { method: 'POST' }, token)
export async function runAndroidSync(resync = false): Promise<SyncRunResult> {
  const report = await androidInvoke<Pick<SyncRunResult, 'pulled' | 'pushed' | 'workspaceRevision'>>(
    resync ? 'android_sync_resync' : 'android_sync_run')
  return { ...await getSyncStatus(''), ...report, status: 'ok' }
}

export type SyncEntityType = 'ledger.category' | 'ledger.transaction' | 'website.category' | 'website' | 'data.collection' | 'data.record' | 'user.preferences' | 'dashboard.layout' | 'automation.definition'
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

export const getSyncConflicts = async (token: string, signal?: AbortSignal) =>
  isAndroidLocal()
    ? { conflicts: await androidInvoke<SyncConflict[]>('android_sync_conflicts_list') }
    : apiRequest<{ conflicts: SyncConflict[] }>('/api/v1/sync/conflicts', { signal }, token)
export async function getSyncConflict(token: string, id: string, signal?: AbortSignal) {
  if (!isAndroidLocal()) return apiRequest<SyncConflict>(`/api/v1/sync/conflicts/${encodeURIComponent(id)}`, { signal }, token)
  const conflict = (await getSyncConflicts(token)).conflicts.find(entry => entry.id === id)
  if (!conflict) throw new ApiError(404, 'conflict_not_found')
  return conflict
}
export const resolveSyncConflict = (token: string, id: string, strategy: ConflictStrategy, expectedRemoteRevision: number) =>
  isAndroidLocal()
    ? androidInvoke<ConflictResolution>('android_sync_conflict_resolve', { id, strategy, expectedRemoteRevision })
    : apiRequest<ConflictResolution>(`/api/v1/sync/conflicts/${encodeURIComponent(id)}/resolve`, { method: 'POST', body: JSON.stringify({ strategy, expectedRemoteRevision }) }, token)

export interface RejectedEntry {
  id: string
  mutationId: string
  entityType: SyncEntityType
  entityId: string
  operation: 'upsert' | 'delete'
  baseRevision: number
  reason: string | null
  attempts: number
  payload: Record<string, unknown> | null
  updatedAt: string
}
export interface RejectedDecision {
  id: string
  decision: 'dismiss' | 'retry'
  status: 'resolved'
  mutationId: string | null
  resolvedAt: string
}

export const getSyncRejected = (token: string, signal?: AbortSignal) =>
  isAndroidLocal() ? androidInvoke<RejectedEntry[]>('android_sync_rejected_list') : apiRequest<RejectedEntry[]>('/api/v1/sync/rejected', { signal }, token)
export const decideSyncRejected = (token: string, id: string, decision: 'dismiss' | 'retry') =>
  isAndroidLocal()
    ? androidInvoke<RejectedDecision>(`android_sync_rejected_${decision}`, { id })
    : apiRequest<RejectedDecision>(`/api/v1/sync/rejected/${encodeURIComponent(id)}/${decision}`, { method: 'POST' }, token)
