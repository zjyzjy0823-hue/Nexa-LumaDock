import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { Ref } from 'vue'
import { ApiError } from '../api/client'
import { getSyncConflict, getSyncConflicts, resolveSyncConflict } from '../api/sync'
import type { ConflictStrategy, SyncConflict } from '../api/sync'
import { conflictConfirmation, conflictRequestError } from '../services/conflictPresentation'
import { ledgerService } from '../services/ledger'
import { websiteService } from '../services/websites'
import { dataService } from '../services/data'
import { useAuthStore } from '../stores/auth'
import { confirmAction } from './useConfirm'

export function useSyncConflicts(open: Ref<boolean>, notify: (message: string) => void, onResolved: () => void | Promise<void>) {
  const auth = useAuthStore()
  const conflicts = ref<SyncConflict[]>([])
  const selected = ref<SyncConflict | null>(null)
  const references = ref<Record<string, string>>({})
  const listLoading = ref(false)
  const detailLoading = ref(false)
  const resolving = ref(false)
  const error = ref('')
  const busy = computed(() => listLoading.value || detailLoading.value || resolving.value)
  let alive = true
  let mounted = false
  let sessionGeneration = 0
  let detailGeneration = 0
  let listController: AbortController | null = null
  let detailController: AbortController | null = null
  type Session = { token: string; generation: number }
  const session = (): Session | null => auth.token && open.value && alive ? { token: auth.token, generation: sessionGeneration } : null
  const current = (value: Session) => alive && open.value && value.token === auth.token && value.generation === sessionGeneration

  async function report(cause: unknown, value: Session) {
    if (!current(value)) return
    if (cause instanceof ApiError && cause.status === 401) {
      try { await auth.restore() } catch { /* auth.restore checks the Local session */ }
    }
    if (current(value)) error.value = conflictRequestError(cause)
  }

  async function select(id: string, clearError = true) {
    const value = session()
    if (!value || resolving.value) return
    detailController?.abort()
    const controller = new AbortController()
    detailController = controller
    const generation = ++detailGeneration
    selected.value = null
    detailLoading.value = true
    if (clearError) error.value = ''
    try {
      const result = await getSyncConflict(value.token, id, controller.signal)
      if (current(value) && generation === detailGeneration) selected.value = result
    } catch (cause) {
      if (current(value) && generation === detailGeneration) await report(cause, value)
    } finally {
      if (current(value) && generation === detailGeneration) {
        detailLoading.value = false
        detailController = null
      }
    }
  }

  async function refresh(clearError = true) {
    const value = session()
    if (!value || listLoading.value || resolving.value) return
    listLoading.value = true
    if (clearError) error.value = ''
    const previousId = selected.value?.id
    const controller = new AbortController()
    listController = controller
    try {
      const result = await getSyncConflicts(value.token, controller.signal)
      if (!current(value)) return
      conflicts.value = result.conflicts
      const types = new Set(result.conflicts.map(conflict => conflict.entityType))
      const parents = await Promise.allSettled([
        types.has('ledger.transaction') ? ledgerService.categories(value.token) : Promise.resolve([]),
        types.has('website') ? websiteService.categories(value.token) : Promise.resolve([]),
        types.has('data.record') ? dataService.list(value.token) : Promise.resolve([]),
      ])
      if (!current(value)) return
      // Parent lookup failure should not prevent viewing/handling the conflict.
      references.value = Object.fromEntries(parents.flatMap(result => result.status === 'fulfilled' ? result.value.map(item => [item.id, item.name]) : []))
      const id = result.conflicts.find(conflict => conflict.id === previousId)?.id ?? result.conflicts[0]?.id
      if (id) await select(id, clearError)
      else { selected.value = null; detailController?.abort(); detailGeneration += 1; detailLoading.value = false }
    } catch (cause) { await report(cause, value) }
    finally { if (current(value)) { listLoading.value = false; listController = null } }
  }

  async function resolve(strategy: ConflictStrategy) {
    const value = session()
    const conflict = selected.value
    if (!value || !conflict || busy.value) return
    resolving.value = true
    error.value = ''
    try {
      if (!await confirmAction(conflictConfirmation(conflict, strategy))) return
      if (!current(value)) return
      await resolveSyncConflict(value.token, conflict.id, strategy, conflict.remoteRevision)
      if (!current(value)) return
      conflicts.value = conflicts.value.filter(item => item.id !== conflict.id)
      selected.value = null
      notify(strategy === 'local' ? '已保留最新本机版本，后台将自动同步；若 Core 再次更改，会重新显示冲突。' : '已使用 Core 版本，本机修改和后续编辑已放弃。')
      // Refresh the status immediately; scheduling and pushing remain Backend-owned.
      await onResolved()
      if (!current(value)) return
      resolving.value = false
      await refresh(false)
    } catch (cause) {
      if (!current(value)) return
      await report(cause, value)
      if (!current(value)) return
      resolving.value = false
      if (cause instanceof ApiError && (cause.status === 409 || cause.status === 404)) await refresh(false)
    } finally { if (current(value)) resolving.value = false }
  }

  function reset() {
    sessionGeneration += 1
    detailGeneration += 1
    listController?.abort()
    detailController?.abort()
    listController = detailController = null
    conflicts.value = []
    selected.value = null
    references.value = {}
    listLoading.value = detailLoading.value = resolving.value = false
    error.value = ''
  }
  watch([open, () => auth.token], () => { reset(); if (mounted && alive && open.value && auth.token) void refresh() }, { flush: 'sync' })
  onMounted(() => { mounted = true; if (open.value) void refresh() })
  onUnmounted(() => { alive = mounted = false; reset() })
  return { conflicts, selected, references, listLoading, detailLoading, resolving, error, busy, refresh, select, resolve }
}
