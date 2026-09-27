export type CollectionIcon = 'projects' | 'domains' | 'software' | 'servers' | 'assets' | 'subscriptions' | 'custom'
export type CollectionTone = 'blue' | 'violet' | 'cyan' | 'mint' | 'amber' | 'rose'
export type RecordTone = 'info' | 'success' | 'warning' | 'neutral'
export interface CollectionRecord { id: string; collectionId: string; name: string; status: string; statusTone: RecordTone; category: string; dataJson: Record<string, unknown>; updatedAt: string; createdAt: string }
export interface DataCollection { id: string; name: string; description: string; icon: CollectionIcon; tone: CollectionTone; recordCount: number; records: CollectionRecord[]; createdAt: string; updatedAt: string }
export interface DataActivity { id: string; title: string; detail: string; time: string; tone: CollectionTone }
export interface DataOverview { active: number; completed: number; recentActivity: number; trend: number[]; trendLabels: string[]; activities: DataActivity[] }
export interface RecordInput { name: string; status: string; category: string; data_json: Record<string, unknown> }
export interface CollectionInput { name: string; description: string; icon: CollectionIcon; tone: CollectionTone }
