export type DeviceKind = 'desktop' | 'laptop' | 'phone' | 'tablet' | 'server' | 'nas'

export interface Device {
  id: string
  name: string
  system: string
  kind: DeviceKind
  ip: string
  location: string
  online: boolean
  cpu: number
  memory: number
  disk: number
  battery: number | null
  activity: number[]
  lastSeen: string
  lastSeenAt: string | null
  tokenLast4: string | null
  tokenCreatedAt: string | null
  hostname: string | null
  os: string | null
  osVersion: string | null
  architecture: string | null
  cpuName: string | null
  memoryTotal: number | null
  memoryUsed: number | null
  diskTotal: number | null
  diskUsed: number | null
  uptimeSeconds: number | null
  localIp: string | null
  clientVersion: string | null
  createdAt: string
  updatedAt: string
}

export type DeviceInput = Pick<Device, 'name' | 'system' | 'kind' | 'ip' | 'location'>

export interface DeviceTokenResult {
  deviceId: string
  token: string
  last4: string
  createdAt: string
}
