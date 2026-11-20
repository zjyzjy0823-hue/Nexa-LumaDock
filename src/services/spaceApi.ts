/**
 * Shared Space（/api/v1/spaces）REST API 客户端与类型定义。
 */

import { apiRequest, ApiError } from '../api/client'
import { getApiBaseUrl } from './fleetUrl'
import type { KeyEnvelope, SpaceEntryType, WrappedDek } from './spaceCrypto'

export type SpaceTier = 'standard' | 'protected' | 'e2ee'
export type SpaceTokenKind = 'standard' | 'vault'
export type SpaceTokenScope = 'read' | 'write'

export interface SpaceCapabilities {
  enabled: boolean
  protectedAvailable: boolean
  maxFileBytes: number
  defaultQuotaBytes: number
  defaultChunkSize: number
  tiers: SpaceTier[]
}

export interface SpaceItem {
  id: string
  workspaceId: string
  name: string
  description: string
  tier: SpaceTier
  activeEpoch: number
  envelopeVersion: number
  quotaBytes: number
  usedBytes: number
  entryCount: number
  archivedAt: string | null
  createdAt: string
  updatedAt: string
}

export interface SpaceEnvelopeResponse {
  spaceId: string
  epoch: number
  envelopeVersion: number
  envelope: KeyEnvelope
  updatedAt: string
}

export interface SpaceBlobResponse {
  id: string
  spaceId: string
  chunkSize: number
  chunkCount: number
  totalSize: number
  uploadedChunks: number[]
  committedAt: string | null
  createdAt: string
}

export interface SpaceEntrySummary {
  id: string
  spaceId: string
  tier: SpaceTier
  entryType: SpaceEntryType
  currentRevision: number
  activeEpoch: number
  title: string | null
  fileName: string | null
  mime: string
  tags: string[]
  sizeBytes: number
  hasConflict: boolean
  deletedAt: string | null
  createdAt: string
  updatedAt: string
  wrappedDek: WrappedDek | null
  encryptedManifestB64: string | null
  blobId: string | null
  chunkCount: number
  chunkSize: number
}

export interface SpaceEntryDetail extends SpaceEntrySummary {
  revision: number
  epoch: number
  contentSha256: string
  contentText: string | null
  contentBase64: string | null
  locked: boolean
  conflictRevisions: number[]
}

export interface StandardSpaceEdit {
  title: string
  tags: string[]
  contentText: string
}

export interface StandardSpaceConflict {
  id: string
  entryId: string
  deviceLabel: string
  operation: 'edit' | 'delete'
  edit: StandardSpaceEdit | null
  baseRevision: number
  createdAt: string
  current: SpaceEntryDetail
}

export interface StandardSpaceSyncResult {
  status: 'applied' | 'conflict' | 'resolved'
  revision: number
  candidateId: string | null
}

export interface StandardSpaceSnapshot { cursor: number; entries: SpaceEntrySummary[] }

export function fetchStandardSpaceSnapshot(route: SpaceRouteConfig, spaceId: string): Promise<StandardSpaceSnapshot> {
  return apiRequest(`/api/v1/spaces/${encodeURIComponent(spaceId)}/sync-snapshot`, {}, route.token, route.origin)
}

export function fetchSpaceChanges(route: SpaceRouteConfig, spaceId: string, cursor: number): Promise<{
  nextSeq: number; hasMore: boolean; changes: { entryId: string | null; changeType: string }[]
}> {
  return apiRequest(`/api/v1/spaces/${encodeURIComponent(spaceId)}/changes?sinceSeq=${cursor}`, {}, route.token, route.origin)
}

export interface SpaceTokenItem {
  id: string
  spaceId: string
  tokenKind: SpaceTokenKind
  name: string
  tokenLast4: string
  scopes: SpaceTokenScope[]
  entryIds: string[] | null
  expiresAt: string | null
  lastUsedAt: string | null
  revokedAt: string | null
  createdAt: string
}

export interface SpaceTokenCreated extends SpaceTokenItem {
  token: string
}

export interface SpaceAuditLogItem {
  id: string
  spaceId: string
  entryId: string | null
  actorKind: string
  actorId: string
  action: string
  outcome: string
  detail: string
  createdAt: string
}

export interface SpaceRouteConfig {
  token: string
  origin?: string
}

function resolveOrigin(route: SpaceRouteConfig): string {
  return (route.origin ?? getApiBaseUrl()).replace(/\/+$/, '')
}

export function fetchSpaceCapabilities(route: SpaceRouteConfig): Promise<SpaceCapabilities> {
  return apiRequest<SpaceCapabilities>('/api/v1/spaces/capabilities', {}, route.token, route.origin)
}

export function fetchSpaces(route: SpaceRouteConfig): Promise<SpaceItem[]> {
  return apiRequest<SpaceItem[]>('/api/v1/spaces', {}, route.token, route.origin)
}

export function createSpaceApi(
  route: SpaceRouteConfig,
  payload: {
    id?: string
    name: string
    description?: string
    tier: SpaceTier
    password?: string
    envelope?: KeyEnvelope
  },
): Promise<SpaceItem> {
  return apiRequest<SpaceItem>(
    '/api/v1/spaces',
    { method: 'POST', body: JSON.stringify(payload) },
    route.token,
    route.origin,
  )
}

export function archiveSpaceApi(route: SpaceRouteConfig, spaceId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/spaces/${encodeURIComponent(spaceId)}`, { method: 'DELETE' }, route.token, route.origin)
}

export function fetchSpaceEnvelope(
  route: SpaceRouteConfig,
  spaceId: string,
  epoch?: number,
): Promise<SpaceEnvelopeResponse> {
  const qs = epoch ? `?epoch=${epoch}` : ''
  return apiRequest<SpaceEnvelopeResponse>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/envelope${qs}`,
    {},
    route.token,
    route.origin,
  )
}

export function updateSpaceEnvelopeCas(
  route: SpaceRouteConfig,
  spaceId: string,
  payload: { expectedEnvelopeVersion: number; envelope: KeyEnvelope },
): Promise<SpaceEnvelopeResponse> {
  return apiRequest<SpaceEnvelopeResponse>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/envelope`,
    { method: 'PUT', body: JSON.stringify(payload) },
    route.token,
    route.origin,
  )
}

export function rotateSpaceEpochApi(
  route: SpaceRouteConfig,
  spaceId: string,
  payload: { expectedActiveEpoch: number; envelope: KeyEnvelope },
): Promise<SpaceEnvelopeResponse> {
  return apiRequest<SpaceEnvelopeResponse>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/rotate-epoch`,
    { method: 'POST', body: JSON.stringify(payload) },
    route.token,
    route.origin,
  )
}

export function changeProtectedPasswordApi(
  route: SpaceRouteConfig,
  spaceId: string,
  payload: { oldPassword: string; newPassword: string },
): Promise<SpaceItem> {
  return apiRequest<SpaceItem>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/change-password`,
    { method: 'POST', body: JSON.stringify(payload) },
    route.token,
    route.origin,
  )
}

export function initSpaceBlob(
  route: SpaceRouteConfig,
  spaceId: string,
  payload: { chunkSize: number; chunkCount: number; totalSize: number },
): Promise<SpaceBlobResponse> {
  return apiRequest<SpaceBlobResponse>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/blobs/init`,
    { method: 'POST', body: JSON.stringify(payload) },
    route.token,
    route.origin,
  )
}

export async function uploadSpaceBlobChunk(
  route: SpaceRouteConfig,
  spaceId: string,
  blobId: string,
  chunkIndex: number,
  bytes: Uint8Array<ArrayBuffer>,
  sha256: string,
): Promise<SpaceBlobResponse> {
  const url = `${resolveOrigin(route)}/api/v1/spaces/${encodeURIComponent(spaceId)}/blobs/${encodeURIComponent(blobId)}/chunks/${chunkIndex}`
  const res = await fetch(url, {
    method: 'PUT',
    credentials: 'omit', redirect: 'error',
    headers: {
      Authorization: `Bearer ${route.token}`,
      'Content-Type': 'application/octet-stream',
      'X-Chunk-Sha256': sha256,
    },
    body: bytes,
  }).catch(() => { throw new ApiError(0, '无法上传文件分块') })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new ApiError(res.status, text || `上传分块失败 (${res.status})`)
  }
  return (await res.json()) as SpaceBlobResponse
}

export async function downloadSpaceBlobChunk(
  route: SpaceRouteConfig,
  spaceId: string,
  blobId: string,
  chunkIndex: number,
): Promise<Uint8Array<ArrayBuffer>> {
  const url = `${resolveOrigin(route)}/api/v1/spaces/${encodeURIComponent(spaceId)}/blobs/${encodeURIComponent(blobId)}/chunks/${chunkIndex}`
  const res = await fetch(url, {
    credentials: 'omit', redirect: 'error',
    headers: { Authorization: `Bearer ${route.token}` },
  })
  if (!res.ok) {
    throw new Error(`拉取分块失败 (${res.status})`)
  }
  const buf = await res.arrayBuffer()
  return new Uint8Array(buf)
}

export function fetchSpaceEntries(
  route: SpaceRouteConfig,
  spaceId: string,
  params?: { search?: string; entryType?: string },
): Promise<SpaceEntrySummary[]> {
  const qs = new URLSearchParams()
  if (params?.search) qs.set('search', params.search)
  if (params?.entryType) qs.set('entryType', params.entryType)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return apiRequest<SpaceEntrySummary[]>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/entries${suffix}`,
    {},
    route.token,
    route.origin,
  )
}

export function createSpaceEntryApi(
  route: SpaceRouteConfig,
  spaceId: string,
  payload: Record<string, unknown>,
): Promise<SpaceEntryDetail> {
  return apiRequest<SpaceEntryDetail>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/entries`,
    { method: 'POST', body: JSON.stringify(payload) },
    route.token,
    route.origin,
  )
}

export function fetchSpaceEntryDetail(
  route: SpaceRouteConfig,
  spaceId: string,
  entryId: string,
  revision?: number,
): Promise<SpaceEntryDetail> {
  const qs = revision ? `?revision=${revision}` : ''
  return apiRequest<SpaceEntryDetail>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/entries/${encodeURIComponent(entryId)}${qs}`,
    {},
    route.token,
    route.origin,
  )
}

export function unlockProtectedEntryApi(
  route: SpaceRouteConfig,
  spaceId: string,
  entryId: string,
  password: string,
  revision?: number,
): Promise<SpaceEntryDetail> {
  return apiRequest<SpaceEntryDetail>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/entries/${encodeURIComponent(entryId)}/unlock`,
    { method: 'POST', body: JSON.stringify({ password, revision }) },
    route.token,
    route.origin,
  )
}

export async function downloadEntryBlob(
  route: SpaceRouteConfig,
  spaceId: string,
  entryId: string,
  password?: string,
  revision?: number,
): Promise<Blob> {
  const base = `${resolveOrigin(route)}/api/v1/spaces/${encodeURIComponent(spaceId)}/entries/${encodeURIComponent(entryId)}/download`
  const res = await (password
    ? fetch(base, {
        method: 'POST',
        credentials: 'omit', redirect: 'error',
        headers: {
          Authorization: `Bearer ${route.token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ password, revision }),
      })
    : fetch(revision ? `${base}?revision=${revision}` : base, {
        credentials: 'omit', redirect: 'error',
        headers: { Authorization: `Bearer ${route.token}` },
      })).catch(() => { throw new ApiError(0, '无法连接 Core 下载文件') })
  if (!res.ok) {
    throw new Error(res.status === 403 ? '空间密码不正确或无权下载' : `下载失败 (${res.status})`)
  }
  return res.blob()
}

export function updateSpaceEntryApi(
  route: SpaceRouteConfig,
  spaceId: string,
  entryId: string,
  payload: Record<string, unknown>,
): Promise<SpaceEntryDetail> {
  return apiRequest<SpaceEntryDetail>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/entries/${encodeURIComponent(entryId)}`,
    { method: 'PUT', body: JSON.stringify(payload) },
    route.token,
    route.origin,
  )
}

export function deleteSpaceEntryApi(
  route: SpaceRouteConfig,
  spaceId: string,
  entryId: string,
): Promise<void> {
  return apiRequest<void>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/entries/${encodeURIComponent(entryId)}`,
    { method: 'DELETE' },
    route.token,
    route.origin,
  )
}

export function pushStandardSpaceMutation(route: SpaceRouteConfig, spaceId: string, entryId: string, payload: {
  operation: 'edit' | 'delete'; mutationId: string; deviceLabel: string; baseRevision: number; edit?: StandardSpaceEdit
}): Promise<StandardSpaceSyncResult> {
  return apiRequest(`/api/v1/spaces/${encodeURIComponent(spaceId)}/entries/${encodeURIComponent(entryId)}/sync`,
    { method: 'POST', body: JSON.stringify(payload) }, route.token, route.origin)
}

export function fetchStandardSpaceConflicts(route: SpaceRouteConfig, spaceId: string): Promise<StandardSpaceConflict[]> {
  return apiRequest(`/api/v1/spaces/${encodeURIComponent(spaceId)}/sync-conflicts`, {}, route.token, route.origin)
}

export function resolveStandardSpaceConflict(
  route: SpaceRouteConfig, spaceId: string, conflict: StandardSpaceConflict, strategy: 'core' | 'candidate',
): Promise<StandardSpaceSyncResult> {
  return apiRequest(`/api/v1/spaces/${encodeURIComponent(spaceId)}/sync-conflicts/${encodeURIComponent(conflict.id)}/resolve`,
    { method: 'POST', body: JSON.stringify({ strategy, expectedRevision: conflict.current.currentRevision, expectedDeleted: !!conflict.current.deletedAt }) },
    route.token, route.origin)
}

export function fetchSpaceTokens(route: SpaceRouteConfig, spaceId: string): Promise<SpaceTokenItem[]> {
  return apiRequest<SpaceTokenItem[]>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/tokens`,
    {},
    route.token,
    route.origin,
  )
}

export function createSpaceTokenApi(
  route: SpaceRouteConfig,
  spaceId: string,
  payload: {
    name: string
    scopes: SpaceTokenScope[]
    entryIds?: string[] | null
    expiresInDays?: number | null
    password?: string
  },
): Promise<SpaceTokenCreated> {
  return apiRequest<SpaceTokenCreated>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/tokens`,
    { method: 'POST', body: JSON.stringify(payload) },
    route.token,
    route.origin,
  )
}

export function revokeSpaceTokenApi(route: SpaceRouteConfig, spaceId: string, tokenId: string): Promise<void> {
  return apiRequest<void>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/tokens/${encodeURIComponent(tokenId)}`,
    { method: 'DELETE' },
    route.token,
    route.origin,
  )
}

export function fetchSpaceAuditLogs(route: SpaceRouteConfig, spaceId: string, limit = 100): Promise<SpaceAuditLogItem[]> {
  return apiRequest<SpaceAuditLogItem[]>(
    `/api/v1/spaces/${encodeURIComponent(spaceId)}/audit-logs?limit=${limit}`,
    {},
    route.token,
    route.origin,
  )
}
