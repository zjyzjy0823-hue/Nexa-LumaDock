import { onUnmounted, ref, watch, type Ref } from 'vue'

export interface SessionOrganization {
  placement: 'active' | 'settled' | 'snoozed' | 'archived'
  pinned?: boolean
  until?: number
  changedAt: number
}

function readOrganization(key: string): Record<string, SessionOrganization> {
  try {
    const raw = JSON.parse(localStorage.getItem(key) ?? '{}')
    return Object.fromEntries(Object.entries(raw ?? {}).filter(([, value]) => {
      const row = value as SessionOrganization | null
      return row && ['active', 'settled', 'snoozed', 'archived'].includes(row.placement)
        && Number.isFinite(row.changedAt) && (row.placement !== 'snoozed' || Number.isFinite(row.until))
    })) as Record<string, SessionOrganization>
  } catch {
    return {}
  }
}

export function useSessionOrganization(scope: Readonly<Ref<string>>) {
  const rows = ref<Record<string, SessionOrganization>>({})
  const now = ref(Date.now())
  let expiry: ReturnType<typeof setTimeout> | undefined
  const storageKey = () => scope.value ? `studiolo:fleet:organization:${scope.value}` : ''

  watch(scope, () => {
    const key = storageKey()
    rows.value = key ? readOrganization(key) : {}
  }, { immediate: true, flush: 'sync' })

  watch(rows, () => {
    clearTimeout(expiry)
    now.value = Date.now()
    const next = Math.min(...Object.values(rows.value)
      .filter(row => row.placement === 'snoozed' && row.until! > now.value)
      .map(row => row.until!))
    if (Number.isFinite(next)) {
      expiry = setTimeout(() => { rows.value = { ...rows.value } }, Math.min(next - now.value, 2_147_483_647))
    }
  }, { immediate: true })

  function set(key: string, value?: SessionOrganization) {
    const target = storageKey()
    const next = target ? { ...readOrganization(target), ...rows.value } : { ...rows.value }
    if (value) next[key] = value
    else delete next[key]
    rows.value = next
    if (target) {
      try { localStorage.setItem(target, JSON.stringify(next)) } catch { /* Keep the current list usable. */ }
    }
  }

  function get(key: string): SessionOrganization {
    const row = rows.value[key]
    if (row && (row.placement !== 'snoozed' || row.until! > now.value)) return row
    return { placement: 'active', pinned: row?.pinned, changedAt: 0 }
  }

  onUnmounted(() => clearTimeout(expiry))
  return { rows, get, set }
}
