import { computed, onScopeDispose, shallowRef, watch, type Ref } from 'vue'
import type { TokenUsageInput } from './tokenUsage'

interface TokenCounts {
  sequence: number
  cached: number
  otherInput: number
  output: number
  other: number
  total: number
}

export interface RecordedTokenUsage extends Omit<TokenCounts, 'sequence'> {
  recordedAt: number
}

interface RecordedRun {
  recordedAt: number
  requestKey?: string
  whole?: TokenCounts
  parts: Record<string, TokenCounts>
}

const prefix = 'studiolo:recorded-token-usage:'
const retentionMs = 45 * 86_400_000

function count(value: unknown): number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : 0
}

function measuredUsage(event: TokenUsageInput, sequence: number): TokenCounts | null {
  if (event.source !== 'exact') return null
  const cumulative = event.scope === 'cumulative'
  // Only explicit per-turn fields are safe to attribute to a date in a cumulative snapshot.
  const input = count(cumulative ? event.lastInputTokens : event.inputTokens)
  const cached = count(cumulative ? event.lastCachedInputTokens : event.cachedInputTokens)
  const output = count(cumulative ? event.lastOutputTokens : event.outputTokens)
  const otherInput = Math.max(0, input - cached)
  const breakdown = cached + otherInput + output
  const total = Math.max(breakdown, count(cumulative ? event.lastTotalTokens : event.totalTokens))
  if (!total) return null
  return { sequence: count(sequence), cached, otherInput, output, other: total - breakdown, total }
}

function validCounts(value: TokenCounts) {
  return value && [value.sequence, value.cached, value.otherInput, value.output, value.other, value.total].every(part => part === count(part))
    && value.total > 0 && value.total === value.cached + value.otherInput + value.output + value.other
}

function readRecord(raw: string | null): RecordedRun | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as RecordedRun | null
    if (!value || !count(value.recordedAt) || value.recordedAt < Date.now() - retentionMs || value.recordedAt > 8.64e15) return null
    if (!value.parts || (value.whole && !validCounts(value.whole))) return null
    const parts = Object.values(value.parts)
    if ((!value.whole && !parts.length) || !parts.every(validCounts)) return null
    return value
  } catch {
    return null
  }
}

function summarizeRun(run: RecordedRun): RecordedTokenUsage {
  // Whole-turn totals and per-message totals can describe the same usage.
  const all = run.whole ? [run.whole] : Object.values(run.parts)
  const totals = { recordedAt: run.recordedAt, cached: 0, otherInput: 0, output: 0, other: 0, total: 0 }
  for (const item of all) {
    totals.cached += item.cached
    totals.otherInput += item.otherInput
    totals.output += item.output
    totals.other += item.other
    totals.total += item.total
  }
  return totals
}

export function useRecordedTokenUsage(scope: Readonly<Ref<string>>) {
  const runs = shallowRef<ReadonlyMap<string, RecordedRun>>(new Map())
  const entries = computed<ReadonlyMap<string, RecordedTokenUsage>>(() => new Map(
    [...runs.value].map(([key, run]) => [key, summarizeRun(run)]),
  ))
  const storagePrefix = () => `${prefix}${scope.value}:`

  watch(scope, next => {
    const records = new Map<string, RecordedRun>()
    if (next) {
      try {
        const keyPrefix = storagePrefix()
        for (const key of Object.keys(localStorage)) {
          if (!key.startsWith(keyPrefix)) continue
          const record = readRecord(localStorage.getItem(key))
          if (record) records.set(key, record)
          else localStorage.removeItem(key)
        }
      } catch {
        // A WebView with unavailable storage still records for the current session.
      }
    }
    runs.value = records
  }, { immediate: true, flush: 'sync' })

  function onStorage(event: StorageEvent) {
    if (!scope.value) return
    if (event.key === null) {
      runs.value = new Map()
      return
    }
    if (!event.key.startsWith(storagePrefix())) return
    const current = new Map(runs.value)
    const record = readRecord(event.newValue)
    if (record) current.set(event.key, record)
    else current.delete(event.key)
    runs.value = current
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('storage', onStorage)
    onScopeDispose(() => window.removeEventListener('storage', onStorage))
  }

  function record(session: string, event: TokenUsageInput, sequence = 0) {
    const run = event.runId || event.requestId
    if (!scope.value || typeof run !== 'string' || !run) return
    const sample = measuredUsage(event, sequence)
    if (!sample) return

    const keyFor = (id: string) => storagePrefix() + JSON.stringify([session, id])
    const requestKey = event.requestId ? keyFor(event.requestId) : undefined
    const records = new Map(runs.value)
    const aliasedKey = !event.runId && requestKey
      ? [...records].find(([, entry]) => entry.requestKey === requestKey)?.[0]
      : undefined
    const key = aliasedKey ?? keyFor(run)
    const fallbackKey = requestKey && requestKey !== key && records.has(requestKey) ? requestKey : undefined
    const previous = records.get(key) ?? (fallbackKey ? records.get(fallbackKey) : undefined)
    const part = event.scope !== 'cumulative' && typeof event.messageId === 'string' && event.messageId
      ? JSON.stringify(event.messageId) : ''
    const last = part ? previous?.parts[part] : previous?.whole
    if (last && sample.sequence && sample.sequence < last.sequence) return
    if (last) sample.sequence = Math.max(sample.sequence, last.sequence)
    const updated = {
      recordedAt: previous?.recordedAt ?? Date.now(),
      requestKey: requestKey ?? previous?.requestKey,
      whole: part ? previous?.whole : sample,
      parts: part ? { ...previous?.parts, [part]: sample } : previous?.parts ?? {},
    }

    try {
      localStorage.setItem(key, JSON.stringify(updated))
      if (fallbackKey) localStorage.removeItem(fallbackKey)
    } catch {
      // Keep the current value available to the dashboard if it cannot be written.
    }
    if (fallbackKey) records.delete(fallbackKey)
    records.set(key, updated)
    runs.value = records
  }

  return { entries, record }
}
