import { apiRequest } from './client'
import type { ApiKeyCreate, ApiKeyCreated, ApiKeyPublic } from '../types/api'

export const listApiKeys = (jwt: string) => apiRequest<ApiKeyPublic[]>('/api/api-keys', {}, jwt)

export const createApiKey = (jwt: string, payload: ApiKeyCreate) =>
  apiRequest<ApiKeyCreated>('/api/api-keys', { method: 'POST', body: JSON.stringify(payload) }, jwt)

export const setApiKeyStatus = (jwt: string, id: string, status: 'active' | 'inactive') =>
  apiRequest<ApiKeyPublic>(`/api/api-keys/${encodeURIComponent(id)}/status`,
    { method: 'PUT', body: JSON.stringify({ status }) }, jwt)
