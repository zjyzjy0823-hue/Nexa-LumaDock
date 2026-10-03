import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ApiError } from '../api/client'
import { connectCore, disconnectCore, getCoreConnection, testCoreConnection } from '../api/core'
import type { CoreConnection, CoreConnectionTest, CoreConnectRequest } from '../api/core'
import { getSyncStatus, runSync } from '../api/sync'
import type { SyncRunResult, SyncStatus } from '../api/sync'
import { coreSyncRequestError, syncErrorMessage } from '../services/coreSyncErrors'
import { useAuthStore } from '../stores/auth'
import { confirmAction } from './useConfirm'

// This timer only reads Local status. The Local Backend owns all sync cycles,
// retries and scheduling, including when this settings component is unmounted.
export const CORE_SYNC_STATUS_POLL_INTERVAL_MS = 5_000

export function useCoreSync(notify: (message: string) => void) {
  const auth = useAuthStore()
  const connection = ref<CoreConnection | null>(null)
  const connectionTest = ref<CoreConnectionTest | null>(null)
  const syncStatus = ref<SyncStatus | null>(null)
  const syncResult = ref<SyncRunResult | null>(null)
  const connectionLoading = ref(false)
  const syncLoading = ref(false)
  const action = ref<'connect' | 'test' | 'disconnect' | 'sync' | null>(null)
  const connectionError = ref('')
  const syncError = ref('')
  const busy = computed(() => !!action.value || connectionLoading.value || syncLoading.value)
  let alive = true
  let mounted = false
  let sessionGeneration = 0
  let pollGeneration = 0
  let pollTimer: ReturnType<typeof setTimeout> | null = null
  let pollController: AbortController | null = null
  type Session = { token: string; generation: number }
  const current = (requestSession: Session) => alive && requestSession.generation === sessionGeneration && requestSession.token === auth.token
  const session = (): Session | null => auth.token ? { token: auth.token, generation: sessionGeneration } : null

  function stopPolling() {
    if (pollTimer !== null) clearTimeout(pollTimer)
    pollTimer = null
    pollGeneration += 1
    pollController?.abort()
    pollController = null
  }

  function schedulePoll() {
    if (!alive || !mounted || !auth.token || pollTimer !== null) return
    pollTimer = setTimeout(() => { pollTimer = null; void pollStatus() }, CORE_SYNC_STATUS_POLL_INTERVAL_MS)
  }

  async function pollStatus() {
    const requestSession = session()
    if (!requestSession || !alive || !mounted) return
    if (connectionLoading.value || syncLoading.value) { schedulePoll(); return }
    const generation = ++pollGeneration
    const controller = new AbortController()
    pollController = controller
    try {
      const result = await getSyncStatus(requestSession.token, controller.signal)
      if (current(requestSession) && generation === pollGeneration) {
        if (action.value !== 'sync' && !result.lastError && result.lastSuccessAt && result.lastSuccessAt !== syncStatus.value?.lastSuccessAt) {
          syncError.value = ''
          if (syncResult.value?.status === 'error') syncResult.value = null
          if (connectionTest.value?.status === 'unauthorized' || connectionTest.value?.status === 'unreachable') connectionTest.value = null
        }
        syncStatus.value = result
      }
    } catch {
      // A status display failure must not replace durable sync diagnostics or
      // repeatedly notify the user. Manual actions retain their error handling.
    } finally {
      if (current(requestSession) && generation === pollGeneration) {
        pollController = null
        schedulePoll()
      }
    }
  }

  async function errorMessage(error: unknown, requestSession: Session) {
    if (current(requestSession) && error instanceof ApiError && error.status === 401) {
      // Core login/Client failures can also return 401. Only auth.restore can
      // decide whether the Local JWT has expired; do not log out a valid user.
      try { await auth.restore() } catch { /* existing restore logs out expired sessions */ }
    }
    return coreSyncRequestError(error)
  }

  async function refresh(clearErrors = true) {
    const requestSession = session()
    if (!requestSession || connectionLoading.value || syncLoading.value) return
    stopPolling()
    connectionLoading.value = syncLoading.value = true
    if (clearErrors) connectionError.value = syncError.value = ''
    try {
      const results = await Promise.allSettled([getCoreConnection(requestSession.token), getSyncStatus(requestSession.token)])
      if (!current(requestSession)) return
      const [core, sync] = results
      if (core.status === 'fulfilled') {
        connection.value = core.value
        if (!core.value.connected) connectionTest.value = null
      } else {
        const message = await errorMessage(core.reason, requestSession)
        if (current(requestSession)) connectionError.value = message
      }
      if (!current(requestSession)) return
      if (sync.status === 'fulfilled') syncStatus.value = sync.value
      else {
        const message = await errorMessage(sync.reason, requestSession)
        if (current(requestSession)) syncError.value = message
      }
    } finally {
      if (current(requestSession)) {
        connectionLoading.value = syncLoading.value = false
        schedulePoll()
      }
    }
  }

  async function perform(kind: NonNullable<typeof action.value>, task: (requestSession: Session) => Promise<void>) {
    const requestSession = session()
    if (busy.value || !requestSession) return
    action.value = kind
    if (kind === 'sync') syncError.value = ''
    else connectionError.value = ''
    try { await task(requestSession) }
    catch (error) {
      if (!current(requestSession)) return
      const message = await errorMessage(error, requestSession)
      if (current(requestSession)) {
        if (kind === 'sync') syncError.value = message
        else connectionError.value = message
        notify(message)
      }
    } finally {
      if (current(requestSession)) {
        await refresh(false)
        if (current(requestSession)) action.value = null
      }
    }
  }

  async function connect(payload: CoreConnectRequest) {
    if (connection.value?.connected) return
    await perform('connect', async requestSession => {
      const result = await connectCore(requestSession.token, payload)
      if (!current(requestSession)) return
      connection.value = result
      connectionTest.value = null
      syncResult.value = null
      notify('Core 已连接，将在后台自动同步。')
    })
  }

  async function test() {
    await perform('test', async requestSession => {
      const result = await testCoreConnection(requestSession.token)
      if (!current(requestSession)) return
      connectionTest.value = result
      notify({ connected: '连接正常', disconnected: '尚未连接', unreachable: '无法访问 Core', unauthorized: 'Core Client 凭证无效，需要重新连接或修复' }[result.status])
    })
  }

  async function disconnect() {
    await perform('disconnect', async requestSession => {
      if (!await confirmAction('断开连接只移除这台设备保存的 Core 连接信息，不会删除本地数据，也不会自动撤销 Core 上的 Client。')) return
      if (!current(requestSession)) return
      const result = await disconnectCore(requestSession.token)
      if (!current(requestSession)) return
      connection.value = result
      connectionTest.value = null
      syncResult.value = null
      notify('Core 已断开，本地数据保留。')
    })
  }

  async function sync() {
    if (busy.value || !auth.token || !connection.value?.connected) return
    syncResult.value = null
    await perform('sync', async requestSession => {
      const result = await runSync(requestSession.token)
      if (!current(requestSession)) return
      syncResult.value = result
      if (result.status === 'error') {
        syncError.value = syncErrorMessage(result.lastError)
        if (result.lastError === 'unauthorized') connectionTest.value = { connected: false, status: 'unauthorized' }
      }
      notify(result.status === 'ok' ? `同步完成：上传 ${result.pushed} 项，接收 ${result.pulled} 项。` : `同步未完成：${syncError.value}`)
    })
  }

  watch(() => auth.token, () => {
    sessionGeneration += 1
    stopPolling()
    connection.value = null
    connectionTest.value = null
    syncStatus.value = null
    syncResult.value = null
    connectionLoading.value = syncLoading.value = false
    action.value = null
    connectionError.value = syncError.value = ''
    if (mounted && alive && auth.token) void refresh()
  }, { flush: 'sync' })
  onMounted(() => { mounted = true; void refresh() })
  onUnmounted(() => { alive = mounted = false; sessionGeneration += 1; stopPolling() })
  return { connection, connectionTest, syncStatus, syncResult, connectionLoading, syncLoading, action, busy, connectionError, syncError, refresh, connect, test, disconnect, sync }
}
