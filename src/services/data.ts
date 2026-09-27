import { apiRequest } from '../api/client'
import type { CollectionInput, DataCollection, CollectionRecord, RecordInput } from '../types/data'
const root = '/api/v1/data'
export const dataService = {
  list(token: string) { return apiRequest<DataCollection[]>(`${root}/collections`, {}, token) },
  create(token: string, data: CollectionInput) { return apiRequest<DataCollection>(`${root}/collections`, { method: 'POST', body: JSON.stringify(data) }, token) },
  update(token: string, id: string, data: Partial<CollectionInput>) { return apiRequest<DataCollection>(`${root}/collections/${id}`, { method: 'PATCH', body: JSON.stringify(data) }, token) },
  remove(token: string, id: string) { return apiRequest<void>(`${root}/collections/${id}`, { method: 'DELETE' }, token) },
  createRecord(token: string, id: string, data: RecordInput) { return apiRequest<CollectionRecord>(`${root}/collections/${id}/records`, { method: 'POST', body: JSON.stringify(data) }, token) },
  updateRecord(token: string, id: string, data: Partial<RecordInput>) { return apiRequest<CollectionRecord>(`${root}/records/${id}`, { method: 'PATCH', body: JSON.stringify(data) }, token) },
  removeRecord(token: string, id: string) { return apiRequest<void>(`${root}/records/${id}`, { method: 'DELETE' }, token) },
}
