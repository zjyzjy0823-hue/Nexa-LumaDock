/**
 * 统一定时任务（Cron）无框架纯函数辅助（供浏览器与 Node 单元测试共用）。
 */

export type SchedulerOwnerType = 'studiolo' | 'openclaw' | 'hermes'
export type RemoteOwnerType = 'openclaw' | 'hermes'
export type CronHistoryMode = 'paginated' | 'recent_only' | 'last_only' | 'unavailable'

export interface JobRef {
  workspaceId: string
  ownerType: SchedulerOwnerType
  ownerInstanceId: string
  ownerProfile: string
  nativeJobId: string
}

/** 生成稳定无冲突的 JobRef 复合键，供列表渲染与去重使用。 */
export function jobRefKey(ref: Pick<JobRef, 'ownerType' | 'ownerInstanceId' | 'ownerProfile' | 'nativeJobId'>): string {
  return `${ref.ownerType}::${ref.ownerInstanceId}::${ref.ownerProfile || 'default'}::${ref.nativeJobId}`
}

/** 前端兜底脱敏：防止任何敏感凭据或 Token 意外进入通知 Toast。 */
export function sanitizeNotificationText(input: string): string {
  return input
    .replace(/\b(?:ss_live_|sv_live_|na_live_|nc_live_|nd_live_|sn_live_)[A-Za-z0-9_-]{8,}/g, '[REDACTED_TOKEN]')
    .replace(/\bsk-[A-Za-z0-9_-]{12,}/g, '[REDACTED_API_KEY]')
    .replace(/\bBearer\s+[A-Za-z0-9._-]{12,}/gi, 'Bearer [REDACTED]')
    .trim()
}
