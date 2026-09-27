export type ApiKeyStatus = 'active' | 'inactive'
export type ApiScope = 'Devices' | 'Agents' | 'Data' | 'Ledger' | 'Automation' | 'Read'
export type ApiKeyExpiration = '30 days' | '90 days' | '1 year' | 'Never'
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE'

export interface ApiKey {
  id: string
  name: string
  status: ApiKeyStatus
  maskedKey: string
  secret: string
  scopes: ApiScope[]
  lastUsed: string
  expiration: ApiKeyExpiration
}

export interface ApiKeyDraft {
  name: string
  scopes: ApiScope[]
  expiration: ApiKeyExpiration
}

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
