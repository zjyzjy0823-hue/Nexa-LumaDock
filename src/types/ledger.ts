export type LedgerStatTone = 'blue' | 'mint' | 'violet' | 'amber'
export type LedgerStatIcon = 'income' | 'expense' | 'balance' | 'budget'
export interface LedgerStat { id: LedgerStatIcon; label: string; value: string; detail: string; tone: LedgerStatTone; progress?: number }
export type ExpensePeriod = '30d' | '6m' | 'year'
export interface ExpenseTrend { id: ExpensePeriod; label: string; caption: string; labels: string[]; values: number[] }
export interface SpendingCategory { id: string; name: string; amount: number; color: string }
export type TransactionIcon = 'software' | 'cloud' | 'server' | 'income' | 'dining' | 'shopping'
export interface Transaction { id: string; description: string; detail: string; category: string; date: string; amount: number; icon: TransactionIcon }
export type InsightTone = 'violet' | 'blue' | 'amber'
export interface LedgerInsight { id: string; title: string; detail: string; tone: InsightTone }
export interface LedgerCategory { id: string; name: string; type: 'income' | 'expense'; icon: string; createdAt: string }
export interface LedgerTransaction { id: string; categoryId: string | null; categoryName: string | null; type: 'income' | 'expense'; amount: string; description: string; occurredAt: string; merchant: string; note: string; createdAt: string; updatedAt: string }
export interface LedgerSummary { month: string; income: string; expense: string; balance: string; monthlyTrend: { month: string; expense: string }[]; categories: { id: string; name: string; amount: string }[] }
export interface LedgerTransactionInput { category_id: string | null; type: 'income' | 'expense'; amount: string; description: string; occurred_at: string; merchant: string; note: string }
export interface LedgerCategoryInput { name: string; type: 'income' | 'expense'; icon: string }
