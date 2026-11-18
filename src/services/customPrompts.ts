/**
 * 用户自定义斜杠（/prompts）提示词模板持久化管理（纯 UI 配置，不存储聊天正文）。
 */

export interface CustomPromptTemplate {
  id: string
  trigger: string
  title: string
  description: string
  template: string
  createdAt: number
}

export const CUSTOM_PROMPTS_STORAGE_KEY = 'studiolo:custom-prompts:v1'

export interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

function getDefaultStorage(): StorageLike | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function loadCustomPrompts(storage: StorageLike | null = getDefaultStorage()): CustomPromptTemplate[] {
  if (!storage) return []
  try {
    const raw = storage.getItem(CUSTOM_PROMPTS_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((x): x is CustomPromptTemplate => Boolean(x && typeof x.id === 'string' && typeof x.trigger === 'string' && typeof x.template === 'string'))
      .slice(0, 50)
  } catch {
    return []
  }
}

function persist(list: CustomPromptTemplate[], storage: StorageLike | null = getDefaultStorage()): void {
  if (!storage) return
  try {
    storage.setItem(CUSTOM_PROMPTS_STORAGE_KEY, JSON.stringify(list.slice(0, 50)))
  } catch {
    // 忽略配额限制
  }
}

export function normalizeTrigger(raw: string): string {
  const clean = raw.trim().replace(/^\/+/, '').replace(/\s+/g, '-').toLowerCase()
  return clean ? `/${clean}` : ''
}

export function saveCustomPrompt(
  input: { id?: string; trigger: string; title?: string; description?: string; template: string },
  storage: StorageLike | null = getDefaultStorage(),
): CustomPromptTemplate[] {
  const trigger = normalizeTrigger(input.trigger)
  const template = input.template.trim()
  if (!trigger || !template) return loadCustomPrompts(storage)

  const cur = loadCustomPrompts(storage)
  const id = input.id || `cp-${Date.now()}`
  const item: CustomPromptTemplate = {
    id,
    trigger,
    title: (input.title || trigger).trim(),
    description: (input.description || template.slice(0, 48)).trim(),
    template,
    createdAt: Date.now(),
  }
  const next = cur.some(p => p.id === id)
    ? cur.map(p => (p.id === id ? item : p))
    : [item, ...cur.filter(p => p.trigger !== trigger)]
  persist(next, storage)
  return next
}

export function deleteCustomPrompt(
  id: string,
  storage: StorageLike | null = getDefaultStorage(),
): CustomPromptTemplate[] {
  const next = loadCustomPrompts(storage).filter(p => p.id !== id)
  persist(next, storage)
  return next
}
