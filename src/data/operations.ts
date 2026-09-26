export interface LedgerSnapshot {
  balance: number
  income: number
  expense: number
  changePercent: number
  currency: string
  trend: number[]
}

export const ledgerSnapshot: LedgerSnapshot = {
  balance: 2481,
  income: 5200,
  expense: 2719,
  changePercent: 12,
  currency: 'CNY',
  trend: [12, 35, 57, 82, 46, 41, 72],
}

export interface SystemMetric {
  id: 'cpu' | 'memory' | 'disk' | 'network'
  label: string
  value: string
  detail: string
  percent: number
}

export const systemSnapshot = {
  status: '系统运行正常',
  uptime: '已运行 6 天 14 小时',
  cpuPercent: 38,
  memoryPercent: 61,
  memoryUsed: '9.8 / 16 GB',
  networkDown: '12.4 MB/s',
  networkUp: '3.8 MB/s',
  metrics: [
    { id: 'cpu', label: 'CPU', value: '38%', detail: '8 核', percent: 38 },
    { id: 'memory', label: '内存', value: '61%', detail: '9.8 / 16 GB', percent: 61 },
    { id: 'disk', label: '磁盘', value: '72%', detail: '720 GB / 1 TB', percent: 72 },
    { id: 'network', label: '网络', value: '12.4 MB/s', detail: '下载', percent: 54 },
  ] satisfies SystemMetric[],
}

export interface CollectionItem {
  id: 'transactions' | 'subscriptions' | 'domains' | 'projects'
  name: string
  count: number
  unit: string
}

export const collectionItems: CollectionItem[] = [
  { id: 'transactions', name: '交易记录', count: 248, unit: '条' },
  { id: 'subscriptions', name: '订阅', count: 12, unit: '项' },
  { id: 'domains', name: '域名', count: 8, unit: '个' },
  { id: 'projects', name: '项目', count: 6, unit: '个' },
]

export interface AutomationItem {
  id: 'backup' | 'sync' | 'health' | 'telegram'
  name: string
  description: string
  enabled: boolean
}

export const automationItems: AutomationItem[] = [
  { id: 'backup', name: '每日备份', description: '每天 02:00', enabled: true },
  { id: 'sync', name: '同步到 NAS', description: '文件和照片', enabled: true },
  { id: 'health', name: '服务器健康检查', description: '每 15 分钟', enabled: true },
  { id: 'telegram', name: 'Telegram 通知', description: '重要提醒', enabled: false },
]

export interface RecentNote {
  id: string
  title: string
  preview: string
  updatedAt: string
  color: 'blue' | 'violet' | 'peach' | 'mint'
}

export const recentNotes: RecentNote[] = [
  { id: 'project-ideas', title: '项目构想', preview: '个人工作空间的下一步计划', updatedAt: '9月24日', color: 'blue' },
  { id: 'shopping-list', title: '购物清单', preview: '桌面布置和日常用品', updatedAt: '9月22日', color: 'peach' },
  { id: 'server-tasks', title: '服务器任务', preview: '更新、快照和维护', updatedAt: '9月20日', color: 'mint' },
  { id: 'ideas', title: '灵感', preview: '值得以后探索的想法', updatedAt: '9月18日', color: 'violet' },
]
