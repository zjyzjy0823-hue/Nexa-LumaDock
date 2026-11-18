/**
 * Studiolo 会话级 Token 用量归一化、纯内存累加与文本估算辅助函数。
 */

import type { SessionTokenUsage, TokenUsageSource } from '../types/fleet'

export interface TokenUsageInput {
  runId?: string
  requestId?: string
  messageId?: string
  scope?: 'turn' | 'cumulative' | string
  inputTokens?: number
  cachedInputTokens?: number
  outputTokens?: number
  reasoningTokens?: number
  totalTokens?: number
  lastInputTokens?: number
  lastCachedInputTokens?: number
  lastOutputTokens?: number
  lastReasoningTokens?: number
  lastTotalTokens?: number
  contextWindow?: number
  model?: string
  source?: TokenUsageSource | string
}

export interface TurnTokenEntry {
  inputTokens: number
  cachedInputTokens: number
  outputTokens: number
  reasoningTokens: number
  totalTokens: number
  source: TokenUsageSource
  model?: string
}

export interface SessionTokenState {
  cumulativeTotals: TurnTokenEntry | null
  cumulativeTurnIds: Record<string, true>
  recordedRunKeys?: Record<string, true>
  byTurn: Record<string, TurnTokenEntry>
  lastTurn: TurnTokenEntry | null
  contextWindow?: number
  model?: string
  updatedAt: number
}

function clampToken(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 0
  return Math.max(0, Math.round(value))
}

function normalizeSource(value: unknown): TokenUsageSource {
  return value === 'exact' ? 'exact' : 'estimated'
}

/**
 * 近似估算文本 Token 数量（非 ASCII / CJK 字符按 ~1 token，ASCII 按每 4 字符 ~1 token）。
 */
export function estimateTextTokens(text: string): number {
  const clean = text.trim()
  if (!clean) return 0
  let nonAscii = 0
  for (let i = 0; i < clean.length; i += 1) {
    if (clean.charCodeAt(i) > 127) nonAscii += 1
  }
  const asciiChars = clean.length - nonAscii
  return Math.max(1, nonAscii + Math.ceil(asciiChars / 4))
}

export function resolveTurnUsageKey(event: Pick<TokenUsageInput, 'messageId' | 'runId' | 'requestId'>): string {
  return event.messageId || event.runId || event.requestId || ''
}

export function hasRecordedTurnUsage(state: SessionTokenState | undefined, turnKeys: Array<string | undefined>): boolean {
  if (!state) return false
  for (const key of turnKeys) {
    if (!key) continue
    if (state.byTurn[key] || state.cumulativeTurnIds[key] || state.recordedRunKeys?.[key]) return true
  }
  return false
}

/**
 * 将单条 `TokenUsage`（`turn` 幂等覆盖或 `cumulative` 会话快照）并入会话内存状态。
 */
export function applyTokenUsageEvent(
  current: SessionTokenState | undefined,
  event: TokenUsageInput,
  now = Date.now(),
): SessionTokenState {
  const base: SessionTokenState = current
    ? {
        cumulativeTotals: current.cumulativeTotals,
        cumulativeTurnIds: { ...current.cumulativeTurnIds },
        recordedRunKeys: { ...(current.recordedRunKeys ?? {}) },
        byTurn: { ...current.byTurn },
        lastTurn: current.lastTurn,
        contextWindow: current.contextWindow,
        model: current.model,
        updatedAt: now,
      }
    : {
        cumulativeTotals: null,
        cumulativeTurnIds: {},
        recordedRunKeys: {},
        byTurn: {},
        lastTurn: null,
        updatedAt: now,
      }

  const inputTokens = clampToken(event.inputTokens)
  const cachedInputTokens = clampToken(event.cachedInputTokens)
  const outputTokens = clampToken(event.outputTokens)
  const reasoningTokens = clampToken(event.reasoningTokens)
  const totalRaw = clampToken(event.totalTokens)
  const totalTokens = totalRaw > 0 ? totalRaw : inputTokens + outputTokens
  const source = normalizeSource(event.source)
  const model = event.model?.trim() || base.model

  if (typeof event.contextWindow === 'number' && Number.isFinite(event.contextWindow) && event.contextWindow > 0) {
    base.contextWindow = Math.round(event.contextWindow)
  }
  if (model) base.model = model

  const entry: TurnTokenEntry = {
    inputTokens,
    cachedInputTokens,
    outputTokens,
    reasoningTokens,
    totalTokens,
    source,
    model,
  }

  if (event.scope === 'cumulative') {
    base.cumulativeTotals = entry
    const turnKey = event.runId || event.requestId || `cum-${Object.keys(base.cumulativeTurnIds).length + 1}`
    base.cumulativeTurnIds[turnKey] = true

    const lastInp = event.lastInputTokens !== undefined ? clampToken(event.lastInputTokens) : inputTokens
    const lastCached = event.lastCachedInputTokens !== undefined ? clampToken(event.lastCachedInputTokens) : cachedInputTokens
    const lastOut = event.lastOutputTokens !== undefined ? clampToken(event.lastOutputTokens) : outputTokens
    const lastReas = event.lastReasoningTokens !== undefined ? clampToken(event.lastReasoningTokens) : reasoningTokens
    const lastTotRaw = event.lastTotalTokens !== undefined ? clampToken(event.lastTotalTokens) : 0
    const lastTot = lastTotRaw > 0 ? lastTotRaw : lastInp + lastOut
    base.lastTurn = {
      inputTokens: lastInp,
      cachedInputTokens: lastCached,
      outputTokens: lastOut,
      reasoningTokens: lastReas,
      totalTokens: lastTot,
      source,
      model,
    }
    return base
  }

  const dedupKeys = [event.messageId, event.runId, event.requestId].filter(Boolean) as string[]
  if (!event.messageId && dedupKeys.some(k => Boolean(base.cumulativeTurnIds[k]))) {
    return base
  }

  const turnKey = resolveTurnUsageKey(event) || `turn-${Object.keys(base.byTurn).length + 1}`
  base.byTurn[turnKey] = entry
  if (event.runId) base.recordedRunKeys![event.runId] = true
  if (event.requestId) base.recordedRunKeys![event.requestId] = true
  base.lastTurn = entry
  return base
}

/**
 * 当底层 CLI 适配器未主动推送 `TokenUsage` 时，基于本轮用户提问与助手输出生成估算记录。
 */
export function estimateTurnUsageFallback(
  promptText: string,
  assistantThought: string,
  assistantText: string,
  options: { model?: string; runId?: string; requestId?: string; contextWindow?: number } = {},
): TokenUsageInput {
  const inputTokens = estimateTextTokens(promptText)
  const reasoningTokens = estimateTextTokens(assistantThought)
  const replyTokens = estimateTextTokens(assistantText)
  const outputTokens = reasoningTokens + replyTokens
  return {
    runId: options.runId,
    requestId: options.requestId,
    scope: 'turn',
    inputTokens,
    cachedInputTokens: 0,
    outputTokens,
    reasoningTokens,
    totalTokens: inputTokens + outputTokens,
    contextWindow: options.contextWindow,
    model: options.model,
    source: 'estimated',
  }
}

export function toSessionTokenSummary(state: SessionTokenState | undefined): SessionTokenUsage | null {
  if (!state) return null
  const turnEntries = Object.values(state.byTurn)
  const entries = state.cumulativeTotals ? [state.cumulativeTotals, ...turnEntries] : turnEntries
  if (!entries.length) return null

  let totalInputTokens = 0
  let totalCachedTokens = 0
  let totalOutputTokens = 0
  let totalReasoningTokens = 0
  let totalTokens = 0
  let hasExact = false
  let hasEstimated = false

  for (const item of entries) {
    totalInputTokens += item.inputTokens
    totalCachedTokens += item.cachedInputTokens
    totalOutputTokens += item.outputTokens
    totalReasoningTokens += item.reasoningTokens
    totalTokens += item.totalTokens
    if (item.source === 'exact') hasExact = true
    else hasEstimated = true
  }

  const cumCount = Object.keys(state.cumulativeTurnIds).length
  const turns = cumCount + turnEntries.length
  const last = state.lastTurn ?? entries[entries.length - 1]
  const source: SessionTokenUsage['source'] = hasExact && hasEstimated ? 'mixed' : hasExact ? 'exact' : 'estimated'

  return {
    totalInputTokens,
    totalCachedTokens,
    totalOutputTokens,
    totalReasoningTokens,
    totalTokens,
    lastInputTokens: last?.inputTokens ?? 0,
    lastOutputTokens: last?.outputTokens ?? 0,
    lastTurnTokens: last?.totalTokens ?? 0,
    contextWindow: state.contextWindow,
    turns,
    model: state.model,
    source,
    updatedAt: state.updatedAt,
  }
}

/**
 * 格式化紧凑 Token 显示（< 1,000 显示原值，>= 1,000 显示 k / M 缩写）。
 */
export function formatTokenCount(count: number): string {
  const n = clampToken(count)
  if (n < 1000) return String(n)
  if (n < 1_000_000) {
    const k = n / 1000
    return `${(k >= 100 ? k.toFixed(0) : k.toFixed(1)).replace(/\.0$/, '')}k`
  }
  const m = n / 1_000_000
  return `${m.toFixed(1).replace(/\.0$/, '')}M`
}
