import { ApiError } from '../api/client'
import type { ConflictPayload, ConflictStrategy, SyncConflict, SyncEntityType } from '../api/sync'

const entityLabels: Record<SyncEntityType, string> = {
  'ledger.category': '账本分类', 'ledger.transaction': '账本交易',
  'website.category': '网站分类', website: '网站',
  'data.collection': '数据集合', 'data.record': '数据记录',
}
type Field = { key: string; label: string; kind?: 'type' | 'amount' | 'time' | 'boolean' | 'reference' | 'json' }
const fields: Record<SyncEntityType, Field[]> = {
  'ledger.category': [{ key: 'name', label: '名称' }, { key: 'type', label: '类型', kind: 'type' }, { key: 'icon', label: '图标' }],
  'ledger.transaction': [{ key: 'type', label: '类型', kind: 'type' }, { key: 'amount', label: '金额', kind: 'amount' },
    { key: 'categoryId', label: '分类', kind: 'reference' }, { key: 'description', label: '描述' },
    { key: 'merchant', label: '商户' }, { key: 'note', label: '备注' }, { key: 'occurredAt', label: '发生时间', kind: 'time' }],
  'website.category': [{ key: 'name', label: '名称' }, { key: 'order', label: '排序' }],
  website: [{ key: 'name', label: '名称' }, { key: 'url', label: 'URL' }, { key: 'favorite', label: '收藏', kind: 'boolean' },
    { key: 'categoryId', label: '分类', kind: 'reference' }, { key: 'description', label: '描述' }, { key: 'icon', label: '图标' },
    { key: 'order', label: '排序' }, { key: 'lastVisitedAt', label: '上次访问', kind: 'time' }],
  'data.collection': [{ key: 'name', label: '名称' }, { key: 'description', label: '描述' }, { key: 'icon', label: '图标' }, { key: 'tone', label: '颜色' }],
  'data.record': [{ key: 'name', label: '名称' }, { key: 'status', label: '状态' }, { key: 'category', label: '分类' },
    { key: 'collectionId', label: '所属集合', kind: 'reference' }, { key: 'dataJson', label: '记录内容', kind: 'json' }],
}

export const conflictEntityLabel = (entityType: SyncEntityType) => entityLabels[entityType] ?? '同步数据'
export function conflictTitle(conflict: SyncConflict) {
  const data = conflict.local ?? conflict.remote
  const title = data?.name ?? data?.description
  return typeof title === 'string' && title.trim() ? title : conflictEntityLabel(conflict.entityType)
}
export function conflictTime(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间不可用' : date.toLocaleString()
}
export function detectedTime(value: string, now = Date.now()) {
  const elapsed = now - new Date(value).getTime()
  if (!Number.isFinite(elapsed) || elapsed < 0) return conflictTime(value)
  if (elapsed < 60_000) return '刚刚检测到'
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)} 分钟前检测到`
  return conflictTime(value)
}

// Canonical key order avoids highlighting JSON objects whose property order differs.
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical((value as ConflictPayload)[key])}`).join(',')}}`
  return JSON.stringify(value) ?? 'null'
}
function display(value: unknown, field: Field, references: Record<string, string>) {
  if (field.kind === 'json') return JSON.stringify(value ?? {}, null, 2)
  if (value === null || value === undefined || value === '') return field.kind === 'reference' ? (field.key === 'collectionId' ? '无集合' : '未分类') : '—'
  if (field.kind === 'amount') {
    const amount = Number(value)
    return Number.isFinite(amount) ? `¥${amount.toFixed(2)}` : '金额不可用'
  }
  if (field.kind === 'type') return value === 'income' ? '收入' : value === 'expense' ? '支出' : String(value)
  if (field.kind === 'boolean') return value ? '是' : '否'
  if (field.kind === 'time') return typeof value === 'string' ? conflictTime(value) : '时间不可用'
  if (field.kind === 'reference') return references[String(value)] ?? String(value)
  if (field.key === 'status') return ({ active: '进行中', done: '已完成', completed: '已完成', archived: '已归档' } as Record<string, string>)[String(value)] ?? String(value)
  return typeof value === 'string' || typeof value === 'number' ? String(value) : '—'
}
export function conflictFields(conflict: SyncConflict, references: Record<string, string> = {}) {
  return (fields[conflict.entityType] ?? []).map(field => ({
    key: field.key, label: field.label, json: field.kind === 'json',
    local: conflict.localDeleted ? '已删除' : display(conflict.local?.[field.key], field, references),
    remote: conflict.remoteDeleted ? '已删除' : !conflict.remote ? 'Core 中不存在' : display(conflict.remote[field.key], field, references),
    different: conflict.localDeleted !== conflict.remoteDeleted || canonical(conflict.local?.[field.key]) !== canonical(conflict.remote?.[field.key]),
  }))
}
export function conflictConfirmation(conflict: SyncConflict, strategy: ConflictStrategy) {
  if (strategy === 'remote') return `使用 Core 版本？当前本机修改${conflict.hasPendingTail ? '及冲突检测后的后续编辑' : ''}将被放弃，此操作无法直接撤销。${conflict.remoteDeleted ? 'Core 已删除此数据，本机也将删除。' : !conflict.remote ? 'Core 中不存在此数据，本机也将删除。' : ''}`
  return `保留本机版本？${conflict.hasPendingTail ? '将保留当前最新本机数据，包括冲突检测后的后续编辑。' : ''}本机${conflict.localDeleted ? '删除操作' : '版本'}将作为新的修改在后台同步到 Core，并覆盖当前 Core 版本。${conflict.remoteDeleted && !conflict.localDeleted ? '这会恢复 Core 中已删除的数据。' : ''}若 Core 再次更改，系统会重新显示冲突，由你再次决定。`
}

const safeErrors: Record<string, string> = {
  invalid_conflict_snapshot: '冲突快照无效，本机数据已保留，请检查本机后端。',
  malformed_conflict_snapshot: '冲突快照无效，本机数据已保留，请检查本机后端。',
  unknown_entity_type: '此同步数据类型不受支持。',
  conflict_snapshot_changed: 'Core 版本已更新，请查看最新版本后重新确认。',
  stale_conflict_snapshot: 'Core 版本已更新，请查看最新版本后重新确认。',
  missing_collection: '缺少关联集合，请先同步或处理集合冲突。',
  collection_not_found: '缺少关联集合，请先同步或处理集合冲突。',
  missing_category: '缺少关联分类，请先同步或处理分类冲突。',
  category_not_found: '缺少关联分类，请先同步或处理分类冲突。',
  collection_id_immutable: '记录所属集合发生变化，本机数据已保留。',
  category_type_mismatch: '交易与分类的类型不匹配，本机数据已保留。',
  category_has_transactions: '分类已有交易，请先处理相关交易。',
  invalid_local_state: '本机同步状态异常，数据已保留，请检查本机后端。',
  invalid_resolution_receipt: '冲突处理记录异常，请刷新状态。',
  conflict_already_resolved: '此冲突已处理，请刷新冲突列表。',
  sync_in_progress: '同步正在进行，请稍后查看最新版本并重新确认。',
  conflict_busy: '此冲突正在处理，请稍后查看最新版本并重新确认。',
  conflict_not_found: '此冲突已处理或不可访问，请刷新冲突列表。',
}
export function conflictRequestError(error: unknown) {
  if (!(error instanceof ApiError)) return '冲突操作未完成，请重试。'
  if (Object.prototype.hasOwnProperty.call(safeErrors, error.message)) return safeErrors[error.message]!
  switch (error.status) {
    case 0: return '无法连接到 Nexa 本机后端。'
    case 401: return '本机登录已过期，请重新登录。'
    case 404: return '此冲突已处理或不可访问，请刷新冲突列表。'
    case 409: return '冲突状态发生变化，请查看最新版本后重新确认。'
    case 422: return '冲突请求无效，本机数据已保留。'
    default: return '冲突操作未完成，本机数据已保留，请重试。'
  }
}
