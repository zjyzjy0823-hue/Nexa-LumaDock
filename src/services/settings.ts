import { apiRequest } from '../api/client'
import type { SettingsPayload } from '../types/settings'
import type { User } from '../types/widget'

export const settingsService = {
  get(token: string) { return apiRequest<SettingsPayload>('/api/v1/settings', {}, token) },
  update(token: string, payload: Partial<SettingsPayload>) { return apiRequest<SettingsPayload>('/api/v1/settings', { method: 'PATCH', body: JSON.stringify(payload) }, token) },
  account(token: string, payload: { username?: string; avatar?: string | null }) { return apiRequest<User>('/api/v1/account', { method: 'PATCH', body: JSON.stringify(payload) }, token) },
  password(token: string, current_password: string, new_password: string) { return apiRequest<{ message: string }>('/api/v1/account/password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) }, token) },
}
