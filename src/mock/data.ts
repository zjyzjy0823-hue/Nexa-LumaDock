export type CollectionIcon = 'projects' | 'domains' | 'software' | 'servers' | 'assets' | 'subscriptions' | 'custom'
export type CollectionTone = 'blue' | 'violet' | 'cyan' | 'mint' | 'amber' | 'rose'
export type RecordTone = 'info' | 'success' | 'warning' | 'neutral'

export interface CollectionRecord {
  id: string
  name: string
  status: string
  statusTone: RecordTone
  category: string
  updatedAt: string
}

export interface DataCollection {
  id: string
  name: string
  recordCount: number
  description: string
  icon: CollectionIcon
  tone: CollectionTone
  records: CollectionRecord[]
}

export interface DataActivity {
  id: string
  title: string
  detail: string
  time: string
  tone: CollectionTone
}

export interface DataOverview {
  active: number
  completed: number
  recentActivity: number
  trend: number[]
  trendLabels: string[]
  activities: DataActivity[]
}

export const initialCollections: DataCollection[] = [
  {
    id: 'projects', name: 'Projects', recordCount: 12, description: '个人项目管理', icon: 'projects', tone: 'blue',
    records: [
      { id: 'project-nexa', name: 'Nexa', status: '开发中', statusTone: 'info', category: '产品开发', updatedAt: '今天 09:42' },
      { id: 'project-agentledger', name: 'AgentLedger', status: '完成', statusTone: 'success', category: 'AI 工具', updatedAt: '昨天 17:30' },
      { id: 'project-website', name: 'Website', status: '运营中', statusTone: 'warning', category: '网站', updatedAt: '9 月 22 日' },
      { id: 'project-personal', name: 'Personal OS', status: '规划中', statusTone: 'neutral', category: '效率工具', updatedAt: '9 月 18 日' },
    ],
  },
  {
    id: 'domains', name: 'Domains', recordCount: 8, description: '网站与域名资源', icon: 'domains', tone: 'violet',
    records: [
      { id: 'domain-nexa', name: 'nexa.app', status: '运行中', statusTone: 'success', category: '主站', updatedAt: '今天 08:15' },
      { id: 'domain-portfolio', name: 'portfolio.dev', status: '运行中', statusTone: 'success', category: '个人网站', updatedAt: '9 月 23 日' },
      { id: 'domain-lab', name: 'lab.tools', status: '待续费', statusTone: 'warning', category: '实验项目', updatedAt: '9 月 20 日' },
    ],
  },
  {
    id: 'software', name: 'Software', recordCount: 15, description: '软件工具管理', icon: 'software', tone: 'cyan',
    records: [
      { id: 'software-figma', name: 'Figma', status: '使用中', statusTone: 'info', category: '设计', updatedAt: '今天 10:05' },
      { id: 'software-codex', name: 'Codex', status: '使用中', statusTone: 'info', category: '开发', updatedAt: '昨天 14:20' },
      { id: 'software-obsidian', name: 'Obsidian', status: '已配置', statusTone: 'success', category: '知识管理', updatedAt: '9 月 21 日' },
    ],
  },
  {
    id: 'servers', name: 'Servers', recordCount: 6, description: '服务器资源', icon: 'servers', tone: 'mint',
    records: [
      { id: 'server-home', name: 'Home NAS', status: '在线', statusTone: 'success', category: '家庭网络', updatedAt: '今天 09:10' },
      { id: 'server-cloud', name: 'Cloud VPS', status: '在线', statusTone: 'success', category: '云服务器', updatedAt: '昨天 23:40' },
      { id: 'server-staging', name: 'Staging', status: '维护中', statusTone: 'warning', category: '测试环境', updatedAt: '9 月 19 日' },
    ],
  },
  {
    id: 'assets', name: 'Assets', recordCount: 9, description: '数字资产', icon: 'assets', tone: 'amber',
    records: [
      { id: 'asset-design', name: 'Design Library', status: '已整理', statusTone: 'success', category: '设计资源', updatedAt: '今天 08:48' },
      { id: 'asset-photo', name: 'Photo Archive', status: '同步中', statusTone: 'info', category: '媒体资源', updatedAt: '9 月 24 日' },
      { id: 'asset-license', name: 'License Vault', status: '已整理', statusTone: 'success', category: '授权许可', updatedAt: '9 月 18 日' },
    ],
  },
  {
    id: 'subscriptions', name: 'Subscriptions', recordCount: 11, description: '服务订阅', icon: 'subscriptions', tone: 'rose',
    records: [
      { id: 'subscription-chatgpt', name: 'ChatGPT Plus', status: '有效', statusTone: 'success', category: 'AI 服务', updatedAt: '今天 07:30' },
      { id: 'subscription-cloudflare', name: 'Cloudflare', status: '有效', statusTone: 'success', category: '网络服务', updatedAt: '9 月 22 日' },
      { id: 'subscription-storage', name: 'Cloud Storage', status: '待续费', statusTone: 'warning', category: '云存储', updatedAt: '9 月 20 日' },
    ],
  },
]

export const dataOverview: DataOverview = {
  active: 28,
  completed: 17,
  recentActivity: 18,
  trend: [24, 29, 27, 36, 34, 43, 40, 48, 46, 56, 54, 61],
  trendLabels: ['8 月', '9 月初', '本周'],
  activities: [
    { id: 'activity-1', title: 'Nexa', detail: '项目状态已更新', time: '12 分钟前', tone: 'blue' },
    { id: 'activity-2', title: 'Domains', detail: '新增 1 条域名记录', time: '2 小时前', tone: 'violet' },
    { id: 'activity-3', title: 'Subscriptions', detail: '订阅信息已同步', time: '昨天', tone: 'rose' },
  ],
}
