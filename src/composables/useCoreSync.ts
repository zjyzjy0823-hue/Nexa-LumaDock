import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ApiError } from '../api/client'
import { connectCore, disconnectCore, getCoreConnection, testCoreConnection } from '../api/core'
import type { CoreConnection, CoreConnectionTest, CoreConnectRequest } from '../api/core'
import { getSyncStatus, runSync } from '../api/sync'
import type { SyncRunResult, SyncStatus } from '../api/sync'
import { coreSyncRequestError, syncErrorMessage } from '../services/coreSyncErrors'
import { useAuthStore } from '../stores/auth'
import { confirmAction } from './useConfirm'

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
  onUnmounted(() => { alive = false })

  async function errorMessage(error: unknown) {
    if (error instanceof ApiError && error.status === 401) {
      // Core login/Client failures can also return 401. Only auth.restore can
      // decide whether the Local JWT has expired; do not log out a valid user.
      try { await auth.restore() } catch { /* existing restore logs out expired sessions */ }
    }
    return coreSyncRequestError(error)
  }

  async function refresh(clearErrors = true) {
    if (!auth.token || connectionLoading.value || syncLoading.value) return
    const token = auth.token
    connectionLoading.value = syncLoading.value = true
    if (clearErrors) connectionError.value = syncError.value = ''
    const results = await Promise.allSettled([getCoreConnection(token), getSyncStatus(token)])
    if (!alive || token !== auth.token) return
    const [core, sync] = results
    if (core.status === 'fulfilled') {
      connection.value = core.value
      if (!core.value.connected) connectionTest.value = null
    } else connectionError.value = await errorMessage(core.reason)
    if (sync.status === 'fulfilled') syncStatus.value = sync.value
    else syncError.value = await errorMessage(sync.reason)
    connectionLoading.value = syncLoading.value = false
  }

  async function perform(kind: NonNullable<typeof action.value>, task: (token: string) => Promise<void>) {
    if (busy.value || !auth.token) return
    const token = auth.token
    action.value = kind
    if (kind === 'sync') syncError.value = ''
    else connectionError.value = ''
    try { await task(token) }
    catch (error) {
      const message = await errorMessage(error)
      if (alive && token === auth.token) {
        if (kind === 'sync') syncError.value = message
        else connectionError.value = message
        notify(message)
      }
    } finally {
      if (alive && token === auth.token) {
        await refresh(false)
        action.value = null
      }
    }
  }

  async function connect(payload: CoreConnectRequest) {
    if (connection.value?.connected) return
    await perform('connect', async token => {
      const result = await connectCore(token, payload)
      if (!alive || token !== auth.token) return
      connection.value = result
      connectionTest.value = null
      syncResult.value = null
      notify('Core 已连接。')
    })
  }

  async function test() {
    await perform('test', async token => {
      const result = await testCoreConnection(token)
      if (!alive || token !== auth.token) return
      connectionTest.value = result
      notify({ connected: '连接正常', disconnected: '尚未连接', unreachable: '无法访问 Core', unauthorized: 'Core Client 凭证无效，需要重新连接或修复' }[result.status])
    })
  }

  async function disconnect() {
    await perform('disconnect', async token => {
      if (!await confirmAction('断开连接只移除这台设备保存的 Core 连接信息，不会删除本地数据，也不会自动撤销 Core 上的 Client。')) return
      if (!alive || token !== auth.token) return
      const result = await disconnectCore(token)
      if (!alive || token !== auth.token) return
      connection.value = result
      connectionTest.value = null
      syncResult.value = null
      notify('Core 已断开，本地数据保留。')
    })
  }

  async function sync() {
    if (!connection.value?.connected) return
    syncResult.value = null
    await perform('sync', async token => {
      const result = await runSync(token)
      if (!alive || token !== auth.token) return
      syncResult.value = result
      if (result.status === 'error') {
        syncError.value = syncErrorMessage(result.lastError)
        if (result.lastError === 'unauthorized') connectionTest.value = { connected: false, status: 'unauthorized' }
      }
      notify(result.status === 'ok' ? `同步完成：上传 ${result.pushed} 项，接收 ${result.pulled} 项。` : `同步未完成：${syncError.value}`)
    })
  }

  onMounted(() => refresh())
  return { connection, connectionTest, syncStatus, syncResult, connectionLoading, syncLoading, action, busy, connectionError, syncError, refresh, connect, test, disconnect, sync }
}
