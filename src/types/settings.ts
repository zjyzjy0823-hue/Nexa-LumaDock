export type SettingsSectionId = 'account' | 'appearance' | 'sync' | 'storage' | 'security' | 'notifications' | 'about'
export type GlassTheme = 'light' | 'dark' | 'auto'
export type AccentColor = 'blue' | 'purple' | 'mint' | 'pink' | 'orange'
export type BackgroundChoice = 'sky' | 'aurora' | 'minimal' | 'custom'
export type SyncMode = 'cloud' | 'local' | 'hybrid'
export type NotificationChannel = 'desktop' | 'email' | 'telegram' | 'webhook'
export type NotificationEvent = 'agentComplete' | 'deviceOffline' | 'automationFailure' | 'budgetAlert' | 'securityAlert'

export interface UserProfile {
  username: string
  email: string
  timezone: string
  language: string
}

export interface AppearanceConfig {
  theme: GlassTheme
  transparency: number
  blur: number
  accent: AccentColor
  background: BackgroundChoice
}

export interface SyncConfig {
  mode: SyncMode
  serverUrl: string
  automatic: boolean
  cellular: boolean
  lastSynced: string
}

export interface StorageSegment {
  id: 'database' | 'attachments' | 'cache' | 'logs'
  label: string
  bytes: number
  display: string
  color: string
}

export interface StorageInfo {
  usedGb: number
  totalGb: number
  segments: StorageSegment[]
}

export interface SecurityConfig {
  twoFactor: boolean
  requireRemoteConfirmation: boolean
  trustedDevices: number
  activeSessions: number
  apiTokens: number
}

export interface NotificationConfig {
  events: Record<NotificationEvent, boolean>
  channels: Record<NotificationChannel, boolean>
}

export interface AboutInfo {
  product: string
  version: string
  build: string
}

export interface SettingsPayload {
  theme: 'light' | 'dark' | 'system'
  language: string
  timezone: string
  notifications: NotificationConfig
  appearance: Partial<AppearanceConfig>
  sync: Partial<SyncConfig>
  security: Partial<SecurityConfig>
}
