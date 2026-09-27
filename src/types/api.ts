export type ApiKeyStatus = 'active' | 'inactive' | 'expired'
export type ApiScope = 'Devices' | 'Agents' | 'Data' | 'Automation' | 'Read'
export type ApiKeyExpirationDays = 30 | 90 | 365 | null
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE'

export interface ApiKeyPublic {
  id: string
  name: string
  status: ApiKeyStatus
  masked_key: string
  scopes: ApiScope[]
  created_at: string
  last_used_at: string | null
  expires_at: string | null
}

export interface ApiKeyCreate {
  name: string
  scopes: ApiScope[]
  expires_in_days: ApiKeyExpirationDays
}

export interface ApiKeyCreated extends ApiKeyPublic { secret: string }

export interface ApiRequest {
  id: string
  method: HttpMethod
  path: string
  status: number
  durationMs: number
  time: string
}

export interface Webhook {
  id: string
  name: string
  url: string
  method: 'POST'
  enabled: boolean
}

export interface ApiUsagePoint {
  day: string
  requests: number
  errors: number
}

export interface ApiStat {
  id: 'requests' | 'keys' | 'webhooks' | 'errors'
  label: string
  value: string
  trend: string
  tone: 'blue' | 'mint' | 'violet' | 'amber'
  sparkline: number[]
}
