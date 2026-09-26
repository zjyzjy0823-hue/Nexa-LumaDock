export type LedgerStatTone = 'blue' | 'mint' | 'violet' | 'amber'
export type LedgerStatIcon = 'income' | 'expense' | 'balance' | 'budget'

export interface LedgerStat {
  id: LedgerStatIcon
  label: string
  value: string
  detail: string
  tone: LedgerStatTone
  progress?: number
}

export const ledgerStats: LedgerStat[] = [
  { id: 'income', label: 'Monthly Income', value: '¥5,200', detail: '本月总收入', tone: 'mint' },
  { id: 'expense', label: 'Monthly Expense', value: '¥2,719', detail: '本月总支出', tone: 'blue' },
  { id: 'balance', label: 'Balance', value: '¥2,481', detail: '本月收支结余', tone: 'violet' },
  { id: 'budget', label: 'Budget Usage', value: '70%', detail: '月预算 ¥3,900', tone: 'amber', progress: 70 },
]

export type ExpensePeriod = '30d' | '6m' | 'year'

export interface ExpenseTrend {
  id: ExpensePeriod
  label: string
  caption: string
  labels: string[]
  values: number[]
}

export const expenseTrends: ExpenseTrend[] = [
  {
    id: '30d', label: '30天', caption: '近 30 天每日支出',
    labels: ['1日', '4日', '7日', '10日', '13日', '16日', '19日', '22日', '24日', '26日', '28日', '30日'],
    values: [76, 92, 69, 128, 102, 86, 151, 119, 169, 121, 143, 108],
  },
  {
    id: '6m', label: '6个月', caption: '近 6 个月每月支出',
    labels: ['4月', '5月', '6月', '7月', '8月', '9月'],
    values: [2250, 2380, 2135, 2590, 2460, 2719],
  },
  {
    id: 'year', label: '年度', caption: '近 12 个月每月支出',
    labels: ['10月', '11月', '12月', '1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月'],
    values: [2030, 2290, 2860, 2260, 1940, 2150, 2250, 2380, 2135, 2590, 2460, 2719],
  },
]

export interface SpendingCategory {
  id: string
  name: string
  amount: number
  color: string
}

export const spendingCategories: SpendingCategory[] = [
  { id: 'dining', name: '餐饮', amount: 780, color: '#728df1' },
  { id: 'servers', name: '服务器', amount: 624, color: '#9a82e7' },
  { id: 'software', name: '软件', amount: 438, color: '#70c5d8' },
  { id: 'shopping', name: '购物', amount: 430, color: '#eda6b7' },
  { id: 'transport', name: '交通', amount: 247, color: '#f2c47c' },
  { id: 'other', name: '其他', amount: 200, color: '#9eb2cb' },
]

export type TransactionIcon = 'software' | 'cloud' | 'server' | 'income' | 'dining' | 'shopping'

export interface Transaction {
  id: string
  description: string
  detail: string
  category: string
  date: string
  amount: number
  icon: TransactionIcon
}

export const transactions: Transaction[] = [
  { id: 'tx-1', description: 'ChatGPT Plus', detail: '每月订阅', category: '软件', date: '2026-09-26', amount: -138, icon: 'software' },
  { id: 'tx-2', description: 'Cloudflare', detail: '网站服务', category: '服务器', date: '2026-09-24', amount: -120, icon: 'cloud' },
  { id: 'tx-3', description: 'Server', detail: '云主机费用', category: '云服务', date: '2026-09-22', amount: -304, icon: 'server' },
  { id: 'tx-4', description: 'Income', detail: '本月收入', category: '收入', date: '2026-09-20', amount: 5200, icon: 'income' },
  { id: 'tx-5', description: '日常餐饮', detail: '周末用餐', category: '餐饮', date: '2026-09-18', amount: -96, icon: 'dining' },
  { id: 'tx-6', description: '桌面配件', detail: '个人采购', category: '购物', date: '2026-09-16', amount: -219, icon: 'shopping' },
]

export type InsightTone = 'violet' | 'blue' | 'amber'

export interface LedgerInsight {
  id: string
  title: string
  detail: string
  tone: InsightTone
}

export const ledgerInsights: LedgerInsight[] = [
  { id: 'server', title: '服务器支出增加 12%', detail: '相比上月略有上升，建议检查云服务资源的使用率。', tone: 'violet' },
  { id: 'software', title: '软件订阅优化建议', detail: '梳理低频使用的订阅，可以为每月预算留出更多空间。', tone: 'blue' },
  { id: 'budget', title: '预算完成 70%', detail: '本月已使用 ¥2,719，距离预算上限还有 ¥1,181。', tone: 'amber' },
]
