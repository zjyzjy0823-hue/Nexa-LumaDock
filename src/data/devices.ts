export type DeviceKind = 'desktop' | 'mac' | 'phone' | 'tablet' | 'server' | 'nas'

export interface ManagedDevice {
  id: string
  name: string
  system: string
  kind: DeviceKind
  ip: string
  online: boolean
  cpu: number
  memory: number
  disk: number
  battery: number | null
  activity: number[]
  lastSeen: string
  location: string
}

export const initialDevices: ManagedDevice[] = [
  {
    id: 'desktop', name: '台式电脑', system: 'Windows 11 Pro', kind: 'desktop',
    ip: '192.168.31.102', online: true, cpu: 24, memory: 61, disk: 68, battery: null,
    activity: [27, 36, 31, 46, 38, 52, 42, 59, 48, 56, 51, 66, 57, 63],
    lastSeen: '刚刚', location: '书房 · 工作台',
  },
  {
    id: 'mac-mini', name: 'Mac mini', system: 'macOS Sequoia 15.2', kind: 'mac',
    ip: '192.168.31.108', online: true, cpu: 12, memory: 48, disk: 37, battery: null,
    activity: [30, 42, 36, 46, 40, 34, 51, 46, 54, 44, 58, 47, 53, 49],
    lastSeen: '刚刚', location: '书房 · 工作台',
  },
  {
    id: 'phone', name: '安卓手机', system: 'Android 14', kind: 'phone',
    ip: '192.168.31.116', online: true, cpu: 9, memory: 58, disk: 42, battery: 76,
    activity: [42, 29, 51, 40, 33, 46, 35, 52, 43, 37, 49, 39, 44, 40],
    lastSeen: '刚刚', location: '随身设备',
  },
  {
    id: 'minecraft', name: 'Minecraft 服务器', system: 'Ubuntu 22.04 LTS', kind: 'server',
    ip: '192.168.31.210', online: true, cpu: 18, memory: 42, disk: 54, battery: null,
    activity: [35, 44, 55, 43, 62, 52, 70, 60, 66, 55, 74, 68, 63, 70],
    lastSeen: '刚刚', location: '家庭机柜',
  },
  {
    id: 'ipad', name: 'iPad Air', system: 'iPadOS 18.2', kind: 'tablet',
    ip: '192.168.31.123', online: false, cpu: 6, memory: 32, disk: 49, battery: 43,
    activity: [32, 30, 28, 35, 29, 27, 23, 21, 19, 17, 15, 12, 9, 8],
    lastSeen: '2 小时前', location: '随身设备',
  },
  {
    id: 'nas', name: '家庭 NAS', system: 'Synology DSM 7.2', kind: 'nas',
    ip: '192.168.31.201', online: false, cpu: 14, memory: 36, disk: 81, battery: null,
    activity: [43, 48, 42, 51, 47, 39, 34, 31, 26, 24, 18, 16, 12, 8],
    lastSeen: '昨天 22:48', location: '家庭机柜',
  },
]
