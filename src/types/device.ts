export type DeviceKind = 'desktop' | 'mac' | 'phone' | 'tablet' | 'server' | 'nas'

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
  createdAt: string
  updatedAt: string
}

export type DeviceInput = Pick<Device, 'name' | 'system' | 'kind' | 'ip' | 'location'>
