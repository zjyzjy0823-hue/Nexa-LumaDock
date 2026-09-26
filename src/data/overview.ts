export const demoProfile = { name: 'zjy', avatar: '/avatar-doodle.svg' }
export const demoNotifications = [
  { id: 'backup', kind: 'success', title: '每日备份已完成', detail: '文件已安全同步至 NAS。' },
  { id: 'workspace', kind: 'info', title: '工作空间已就绪', detail: '今天一切运行正常。' },
] as const

export type QuickAccessIcon =
  | 'chatgpt'
  | 'github'
  | 'youtube'
  | 'nas'
  | 'cloudflare'
  | 'claude'
  | 'notion'
  | 'gmail'
  | 'add'

export interface QuickAccessItem {
  id: string
  label: string
  icon: QuickAccessIcon
  tone: 'mint' | 'ink' | 'coral' | 'blue' | 'amber' | 'violet' | 'neutral'
  href?: string
}

export const quickAccessItems: QuickAccessItem[] = [
  { id: 'chatgpt', label: 'ChatGPT', icon: 'chatgpt', tone: 'ink', href: 'https://chatgpt.com' },
  { id: 'claude', label: 'Claude', icon: 'claude', tone: 'violet', href: 'https://claude.ai' },
  { id: 'github', label: 'GitHub', icon: 'github', tone: 'ink', href: 'https://github.com' },
  { id: 'youtube', label: 'YouTube', icon: 'youtube', tone: 'coral', href: 'https://youtube.com' },
  { id: 'notion', label: 'Notion', icon: 'notion', tone: 'ink', href: 'https://notion.so' },
  { id: 'gmail', label: 'Gmail', icon: 'gmail', tone: 'coral', href: 'https://mail.google.com' },
  { id: 'cloudflare', label: 'Cloudflare', icon: 'cloudflare', tone: 'amber', href: 'https://dash.cloudflare.com' },
  { id: 'nas', label: 'NAS', icon: 'nas', tone: 'blue' },
  { id: 'add', label: '添加', icon: 'add', tone: 'neutral' },
]

export const weatherSnapshot = {
  location: '圣何塞',
  temperature: 26,
  condition: '晴朗',
  high: 28,
  low: 17,
}

export type DeviceIcon = 'desktop' | 'mac' | 'phone' | 'server'

export interface DeviceSnapshot {
  id: string
  name: string
  platform: string
  icon: DeviceIcon
  online: boolean
  cpu: number
  ram: number
  battery?: number
  activity: number[]
}

export const deviceSnapshots: DeviceSnapshot[] = [
  {
    id: 'desktop',
    name: '台式电脑',
    platform: 'Windows 11',
    icon: 'desktop',
    online: true,
    cpu: 24,
    ram: 61,
    activity: [28, 37, 32, 47, 36, 53, 41, 62, 48, 58, 51, 69],
  },
  {
    id: 'mac-mini',
    name: 'Mac mini',
    platform: 'macOS 14',
    icon: 'mac',
    online: true,
    cpu: 12,
    ram: 48,
    activity: [31, 43, 37, 48, 42, 35, 52, 48, 56, 47, 61, 49],
  },
  {
    id: 'phone',
    name: '安卓手机',
    platform: 'Android 14',
    icon: 'phone',
    online: true,
    cpu: 9,
    ram: 58,
    battery: 76,
    activity: [43, 30, 54, 42, 34, 47, 36, 55, 44, 38, 51, 40],
  },
  {
    id: 'minecraft',
    name: 'Minecraft 服务器',
    platform: 'Ubuntu 22.04',
    icon: 'server',
    online: true,
    cpu: 18,
    ram: 42,
    activity: [35, 46, 57, 45, 66, 54, 73, 62, 68, 57, 78, 70],
  },
]

export type AgentIcon = 'lili' | 'coding' | 'browser'

export interface AgentSnapshot {
  id: string
  name: string
  status: '运行中' | '空闲'
  model: string
  description: string
  icon: AgentIcon
  activity: number[]
}

export const agentSnapshots: AgentSnapshot[] = [
  {
    id: 'lili',
    name: '黎黎',
    status: '运行中',
    model: 'GPT-5',
    description: '正在准备晚间简报',
    icon: 'lili',
    activity: [25, 32, 35, 43, 48, 42, 53, 61, 55, 67, 63, 74],
  },
  {
    id: 'coding',
    name: '编程智能体',
    status: '空闲',
    model: 'Claude 4',
    description: '等待下一项构建任务',
    icon: 'coding',
    activity: [19, 25, 21, 26, 20, 28, 23, 25, 22, 29, 21, 25],
  },
  {
    id: 'browser',
    name: '浏览器智能体',
    status: '空闲',
    model: 'GPT-4.1',
    description: '暂无浏览器任务',
    icon: 'browser',
    activity: [16, 18, 15, 19, 16, 17, 16, 20, 18, 17, 19, 17],
  },
]
