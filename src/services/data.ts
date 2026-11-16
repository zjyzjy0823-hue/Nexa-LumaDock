import { apiRequest } from '../api/client'
import type { CollectionInput, CollectionSummary, DataCollection, CollectionRecord, DataOverviewV1, RecordInput, RecordPage } from '../types/data'
const root = '/api/v1/data'
export interface CollectionListOptions { includeRecords?: boolean; q?: string }
export interface RecordListOptions { limit?: number; cursor?: string | null; q?: string; includeDataJson?: boolean }

function list(token: string): Promise<DataCollection[]>
function list(token: string, options: CollectionListOptions & { includeRecords: false }): Promise<CollectionSummary[]>
function list(token: string, options: CollectionListOptions & { includeRecords?: true }): Promise<DataCollection[]>
function list(token: string, options: CollectionListOptions): Promise<(CollectionSummary | DataCollection)[]>
function list(token: string, options?: CollectionListOptions) {
  const params = new URLSearchParams()
  if (options?.includeRecords !== undefined) params.set('include_records', String(options.includeRecords))
  if (options?.q !== undefined) params.set('q', options.q)
  return apiRequest<(CollectionSummary | DataCollection)[]>(`${root}/collections${params.size ? `?${params}` : ''}`, {}, token)
}
function listRecords(token: string, id: string, options: RecordListOptions & { includeDataJson: true }): Promise<RecordPage<CollectionRecord>>
function listRecords(token: string, id: string, options?: RecordListOptions): Promise<RecordPage>
function listRecords(token: string, id: string, options: RecordListOptions = {}) {
  const path = `${root}/collections/${encodeURIComponent(id)}/records`
  const params = new URLSearchParams({ page: 'true', limit: String(options.limit ?? 50), cursor: options.cursor ?? '', q: options.q ?? '', include_data_json: String(options.includeDataJson ?? false) })
  return apiRequest<RecordPage>(`${path}?${params}`, {}, token)
}
function create(token: string, data: CollectionInput): Promise<DataCollection>
function create(token: string, data: CollectionInput, options: { includeRecords: false }): Promise<CollectionSummary>
function create(token: string, data: CollectionInput, options?: { includeRecords: false }) {
  return apiRequest<CollectionSummary | DataCollection>(`${root}/collections${options ? '?include_records=false' : ''}`, { method: 'POST', body: JSON.stringify(data) }, token)
}
function update(token: string, id: string, data: Partial<CollectionInput>): Promise<DataCollection>
function update(token: string, id: string, data: Partial<CollectionInput>, options: { includeRecords: false }): Promise<CollectionSummary>
function update(token: string, id: string, data: Partial<CollectionInput>, options?: { includeRecords: false }) {
  return apiRequest<CollectionSummary | DataCollection>(`${root}/collections/${encodeURIComponent(id)}${options ? '?include_records=false' : ''}`, { method: 'PATCH', body: JSON.stringify(data) }, token)
}
export const dataService = {
  list, listRecords, create, update,
  overview(token: string, recentLimit = 4) { return apiRequest<DataOverviewV1>(`${root}/overview?recent_limit=${recentLimit}`, {}, token) },
  getRecord(token: string, id: string) { return apiRequest<CollectionRecord>(`${root}/records/${encodeURIComponent(id)}`, {}, token) },
  remove(token: string, id: string) { return apiRequest<void>(`${root}/collections/${encodeURIComponent(id)}`, { method: 'DELETE' }, token) },
  createRecord(token: string, id: string, data: RecordInput) { return apiRequest<CollectionRecord>(`${root}/collections/${encodeURIComponent(id)}/records`, { method: 'POST', body: JSON.stringify(data) }, token) },
  updateRecord(token: string, id: string, data: Partial<RecordInput>) { return apiRequest<CollectionRecord>(`${root}/records/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(data) }, token) },
  removeRecord(token: string, id: string) { return apiRequest<void>(`${root}/records/${encodeURIComponent(id)}`, { method: 'DELETE' }, token) },
}
