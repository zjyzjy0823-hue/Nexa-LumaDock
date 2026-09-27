import type { ApiKeyExpirationDays, ApiScope } from '../types/api'

export const apiScopes: ApiScope[] = ['Devices', 'Agents', 'Data', 'Automation', 'Read']
export const apiExpirations: { value: ApiKeyExpirationDays; label: string }[] = [
  { value: 30, label: '30 天' },
  { value: 90, label: '90 天' },
  { value: 365, label: '1 年' },
  { value: null, label: '永不过期' },
]
