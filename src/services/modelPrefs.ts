/**
 * 每个 Agent 运行时（Codex / OpenCode / Hermes 等）的模型偏好持久化工具。
 * 优先按 `nodeId::provider` 精确记忆，其次按 `provider` 跨节点兜底；
 * 仅记录非敏感的模型 ID 与思考强度名称，绝不保存聊天正文或凭证。
 */

import type { AdapterProvider } from '../types/fleet'

export interface SavedModelPref {
  model: string
  effort?: string
  updatedAt: number
}

export interface ModelPrefStore {
  byTarget: Record<string, SavedModelPref>
  byProvider: Record<string, SavedModelPref>
}

export const MODEL_PREFS_STORAGE_KEY = 'studiolo:agent-model-prefs:v1'

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

export function loadModelPrefs(storage: StorageLike | null = getDefaultStorage()): ModelPrefStore {
  if (!storage) return { byTarget: {}, byProvider: {} }
  try {
    const raw = storage.getItem(MODEL_PREFS_STORAGE_KEY)
    if (!raw) return { byTarget: {}, byProvider: {} }
    const parsed = JSON.parse(raw) as Partial<ModelPrefStore> | null
    return {
      byTarget: parsed?.byTarget && typeof parsed.byTarget === 'object' ? { ...parsed.byTarget } : {},
      byProvider: parsed?.byProvider && typeof parsed.byProvider === 'object' ? { ...parsed.byProvider } : {},
    }
  } catch {
    return { byTarget: {}, byProvider: {} }
  }
}

function persistModelPrefs(store: ModelPrefStore, storage: StorageLike | null = getDefaultStorage()): void {
  if (!storage) return
  try {
    storage.setItem(MODEL_PREFS_STORAGE_KEY, JSON.stringify(store))
  } catch {
    // 隐私模式或存储配额受限时静默忽略
  }
}

/**
 * 保存指定节点与 Agent 的默认模型偏好；传空字符串代表清除记忆恢复节点默认模型。
 */
export function saveAgentModelPref(
  params: {
    nodeId?: string
    provider: AdapterProvider
    model: string
    effort?: string
    now?: number
  },
  storage: StorageLike | null = getDefaultStorage(),
): ModelPrefStore {
  const store = loadModelPrefs(storage)
  const cleanModel = String(params.model || '').trim()
  const targetKey = params.nodeId ? `${params.nodeId}::${params.provider}` : ''

  if (!cleanModel) {
    if (targetKey) delete store.byTarget[targetKey]
    delete store.byProvider[params.provider]
    persistModelPrefs(store, storage)
    return store
  }

  const entry: SavedModelPref = {
    model: cleanModel,
    ...(params.effort ? { effort: params.effort } : {}),
    updatedAt: params.now ?? Date.now(),
  }
  store.byProvider[params.provider] = entry
  if (targetKey) {
    store.byTarget[targetKey] = entry
  }
  persistModelPrefs(store, storage)
  return store
}

/**
 * 读取指定 Agent 最近一次选用的模型偏好（优先精确匹配节点，其次按 provider 兜底）。
 */
export function resolveSavedModelPref(
  nodeId: string | undefined,
  provider: AdapterProvider,
  storage: StorageLike | null = getDefaultStorage(),
): SavedModelPref | null {
  const store = loadModelPrefs(storage)
  if (nodeId) {
    const exact = store.byTarget[`${nodeId}::${provider}`]
    if (exact?.model) return exact
  }
  const byProv = store.byProvider[provider]
  return byProv?.model ? byProv : null
}
