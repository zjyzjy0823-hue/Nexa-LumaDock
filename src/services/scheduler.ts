/**
 * 统一定时任务（/api/v1/scheduler）前端 API 客户端与 JobRef 工具函数。
 */

import { apiRequest } from '../api/client'
import {
  jobRefKey,
  sanitizeNotificationText,
  type CronHistoryMode,
  type JobRef,
  type RemoteOwnerType,
  type SchedulerOwnerType,
} from './schedulerHelpers'

export {
  jobRefKey,
  sanitizeNotificationText,
  type CronHistoryMode,
  type JobRef,
  type RemoteOwnerType,
  type SchedulerOwnerType,
}

export interface CronCapabilities {
  supported: boolean
  canCreate: boolean
  canUpdate: boolean
  canDelete: boolean
  canPause: boolean
  canRunNow: boolean
  historyMode: CronHistoryMode
  supportsProfiles: boolean
}

export interface OwnerInstance {
  ownerType: SchedulerOwnerType
  ownerInstanceId: string
  label: string
  status: 'online' | 'offline' | 'degraded'
  note: string
  capabilities: CronCapabilities
}

export interface UnifiedJob {
  ref: JobRef
  ownerLabel: string
  ownerStatus: 'online' | 'offline' | 'degraded'
  name: string
  description: string
  enabled: boolean
  scheduleKind: string
  scheduleExpression: string
  timezone: string
  nextRunAt: string | null
  lastRunAt: string | null
  lastStatus: string
  nativeRevision: string
  highImpact: boolean
  requiresManualSpaceUnlock: boolean
  capabilities: CronCapabilities
}

export interface UnifiedJobRun {
  nativeRunId: string
  scheduledAt: string | null
  startedAt: string | null
  finishedAt: string | null
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'cancelled' | 'waiting_manual_unlock' | 'unknown'
  nativeStatus: string
  summary: string
}

export interface UnifiedJobsOverview {
  instances: OwnerInstance[]
  jobs: UnifiedJob[]
}

export interface RemoteCronCreatePayload {
  ownerType: RemoteOwnerType
  ownerInstanceId: string
  ownerProfile?: string
  name: string
  description?: string
  enabled?: boolean
  scheduleKind?: 'cron' | 'interval' | 'once'
  scheduleExpression: string
  timezone?: string
  prompt?: string
}

export interface RemoteCronRunsResponse {
  ref: JobRef
  historyMode: CronHistoryMode
  historyUnavailable: boolean
  note: string
  runs: UnifiedJobRun[]
}

export const schedulerService = {
  listJobs(token: string, owner: 'all' | SchedulerOwnerType = 'all') {
    const qs = owner === 'all' ? '' : `?owner=${encodeURIComponent(owner)}`
    return apiRequest<UnifiedJobsOverview>(`/api/v1/scheduler/jobs${qs}`, {}, token)
  },
  createRemoteJob(token: string, payload: RemoteCronCreatePayload) {
    return apiRequest<UnifiedJob>(
      '/api/v1/scheduler/jobs',
      { method: 'POST', body: JSON.stringify(payload) },
      token,
    )
  },
  pauseRemoteJob(token: string, ref: JobRef, paused: boolean) {
    return apiRequest<UnifiedJob>(
      `/api/v1/scheduler/jobs/${encodeURIComponent(ref.ownerType)}/${encodeURIComponent(ref.ownerInstanceId)}/${encodeURIComponent(ref.nativeJobId)}/pause`,
      { method: 'POST', body: JSON.stringify({ paused, ownerProfile: ref.ownerProfile }) },
      token,
    )
  },
  runRemoteJob(token: string, ref: JobRef, requestId: string) {
    return apiRequest<UnifiedJobRun>(
      `/api/v1/scheduler/jobs/${encodeURIComponent(ref.ownerType)}/${encodeURIComponent(ref.ownerInstanceId)}/${encodeURIComponent(ref.nativeJobId)}/run`,
      { method: 'POST', body: JSON.stringify({ requestId, ownerProfile: ref.ownerProfile, confirmed: true }) },
      token,
    )
  },
  deleteRemoteJob(token: string, ref: JobRef) {
    const qs = new URLSearchParams({ profile: ref.ownerProfile, confirmed: 'true' }).toString()
    return apiRequest<void>(
      `/api/v1/scheduler/jobs/${encodeURIComponent(ref.ownerType)}/${encodeURIComponent(ref.ownerInstanceId)}/${encodeURIComponent(ref.nativeJobId)}?${qs}`,
      { method: 'DELETE' },
      token,
    )
  },
  listJobRuns(token: string, ref: JobRef, limit = 20) {
    const qs = new URLSearchParams({ profile: ref.ownerProfile, limit: String(limit) }).toString()
    return apiRequest<RemoteCronRunsResponse>(
      `/api/v1/scheduler/jobs/${encodeURIComponent(ref.ownerType)}/${encodeURIComponent(ref.ownerInstanceId)}/${encodeURIComponent(ref.nativeJobId)}/runs?${qs}`,
      {},
      token,
    )
  },
}
