import test from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'

// Bundle the real Vue composable and its dependencies for Node; no alternate
// HTTP implementation or browser-only test dependency is needed.
const bundle = await build({
  stdin: { contents: `
    export { useCoreSync, CORE_SYNC_STATUS_POLL_INTERVAL_MS } from './src/composables/useCoreSync.ts'
    export { useSyncConflicts } from './src/composables/useSyncConflicts.ts'
    export { getSyncStatus } from './src/api/sync.ts'
    export { conflictFields, conflictTitle, conflictEntityLabel, conflictConfirmation, conflictRequestError, detectedTime } from './src/services/conflictPresentation.ts'
    export { useAuthStore } from './src/stores/auth.ts'
    export { resolveConfirmation, confirmation } from './src/composables/useConfirm.ts'
    export { coreSyncRequestError, syncErrorMessage, syncStatusDisplay } from './src/services/coreSyncErrors.ts'
    export { ApiError } from './src/api/client.ts'
    export { createRenderer, ref } from 'vue'
    export { createPinia } from 'pinia'
  `, resolveDir: process.cwd() },
  bundle: true, write: false, platform: 'node', format: 'esm',
  define: { 'import.meta.env.VITE_API_BASE_URL': '""', 'process.env.NODE_ENV': '"production"' },
})
const { useCoreSync, CORE_SYNC_STATUS_POLL_INTERVAL_MS, useAuthStore, resolveConfirmation, confirmation, coreSyncRequestError,
  syncErrorMessage, syncStatusDisplay, ApiError, createRenderer, createPinia, ref, useSyncConflicts, getSyncStatus,
  conflictFields, conflictTitle, conflictEntityLabel, conflictConfirmation, conflictRequestError, detectedTime } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`)

const metadata = { connected: true, coreUrl: 'http://127.0.0.1:8000', clientId: 'client', workspaceId: 'workspace', installationId: 'installation', clientName: 'Nexa Windows', platform: 'windows', appVersion: '0.5.6', connectedAt: '2026-10-02T01:00:00Z' }
const status = { enabled: true, running: false, connected: true, blocked: false, pending: 3, conflicts: 0, inFlight: 0, rejected: 0, cursor: 0, queueSeeded: true, lastAttemptAt: null, lastSuccessAt: null, nextRetryAt: null, lastError: null }
const reply = (value, code = 200) => new Response(JSON.stringify(value), { status: code, headers: { 'Content-Type': 'application/json' } })
async function settle() { for (let i = 0; i < 12; i++) await new Promise(resolve => setImmediate(resolve)) }

async function mount(handler, conflictsMode = false) {
  const previous = { fetch: globalThis.fetch, localStorage: globalThis.localStorage, setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout }
  let time = 0
  let timerId = 0
  const timers = new Map()
  globalThis.setTimeout = (callback, delay) => {
    const id = ++timerId
    timers.set(id, { callback, at: time + delay })
    return id
  }
  globalThis.clearTimeout = id => timers.delete(id)
  async function advance(ms) {
    const target = time + ms
    while (true) {
      const due = [...timers].filter(([, timer]) => timer.at <= target).sort((a, b) => a[1].at - b[1].at)[0]
      if (!due) break
      time = due[1].at
      timers.delete(due[0])
      due[1].callback()
      await settle()
    }
    time = target
  }
  const saved = new Map()
  globalThis.localStorage = { getItem: key => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value), removeItem: key => saved.delete(key) }
  const calls = []
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options })
    assert.match(options.headers.Authorization, /^Bearer local-test-token(?:-next)?$/)
    return handler(path, options)
  }
  const renderer = createRenderer({ insert() {}, remove() {}, createElement: () => ({}), createText: () => ({}), createComment: () => ({}), setText() {}, setElementText() {}, parentNode: () => null, nextSibling: () => null, patchProp() {} })
  const pinia = createPinia()
  const auth = useAuthStore(pinia)
  auth.token = 'local-test-token'
  const messages = []
  const statusRefreshes = []
  const open = ref(conflictsMode)
  let state
  const app = renderer.createApp({ setup() {
    state = conflictsMode ? useSyncConflicts(open, message => messages.push(message), async () => { statusRefreshes.push(await getSyncStatus(auth.token)) }) : useCoreSync(message => messages.push(message))
    return () => null
  } })
  app.use(pinia)
  app.mount({})
  await settle()
  let unmounted = false
  const unmount = () => { if (!unmounted) { unmounted = true; app.unmount() } }
  return { state, auth, calls, messages, saved, timers, advance, unmount, open, statusRefreshes, close() { unmount(); resolveConfirmation(false); Object.assign(globalThis, previous) } }
}

test('disconnected entry loads Local outbox and cannot run sync', async () => {
  const ctx = await mount(path => reply(path.endsWith('/connection') ? { connected: false } : status))
  try {
    assert.equal(ctx.state.connection.value.connected, false)
    assert.equal(ctx.state.syncStatus.value.pending, 3)
    await ctx.state.sync()
    assert.equal(ctx.calls.length, 2)
    assert.equal(ctx.saved.size, 0)
  } finally { ctx.close() }
})

test('connect, test, manual sync and confirmed disconnect use the Local API', async () => {
  let connected = false
  let synced = false
  let finishRun
  const ctx = await mount((path, options) => {
    if (path.endsWith('/connect')) { connected = true; return reply(metadata) }
    if (path.endsWith('/test')) return reply({ connected: true, status: 'connected' })
    if (path.endsWith('/run')) return new Promise(resolve => { finishRun = () => { synced = true; resolve(reply({ ...status, status: 'ok', pushed: 3, pulled: 2, pending: 0, cursor: 5, workspaceRevision: 5 })) } })
    if (path.endsWith('/connection')) {
      if (options.method === 'DELETE') connected = false
      return reply(connected ? metadata : { connected: false })
    }
    return reply({ ...status, pending: synced ? 0 : 3, lastSuccessAt: synced ? '2026-10-02T02:00:00Z' : null })
  })
  try {
    await ctx.state.connect({ coreUrl: metadata.coreUrl, username: 'test-user', password: 'temporary-test-only', clientName: metadata.clientName, platform: 'windows', appVersion: '0.5.6' })
    assert.equal(ctx.state.connection.value.connected, true)
    await ctx.state.connect({})
    assert.equal(ctx.calls.filter(call => call.path.endsWith('/connect')).length, 1)
    await ctx.state.test()
    assert.equal(ctx.state.connectionTest.value.status, 'connected')
    const running = ctx.state.sync()
    assert.equal(ctx.state.action.value, 'sync')
    await ctx.state.sync()
    assert.equal(ctx.calls.filter(call => call.path.endsWith('/run')).length, 1)
    finishRun()
    await running
    assert.equal(ctx.state.syncStatus.value.pending, 0)
    assert.ok(ctx.state.syncStatus.value.lastSuccessAt)
    assert.match(ctx.messages.at(-1), /上传 3 项，接收 2 项/)
    let disconnecting = ctx.state.disconnect()
    assert.match(confirmation.value.message, /不会删除本地数据，也不会自动撤销/)
    resolveConfirmation(false)
    await disconnecting
    assert.equal(ctx.calls.filter(call => call.options.method === 'DELETE').length, 0)
    disconnecting = ctx.state.disconnect()
    resolveConfirmation(true)
    await disconnecting
    assert.equal(ctx.state.connection.value.connected, false)
    assert.equal(ctx.saved.size, 0)
  } finally { ctx.close() }
})

test('offline sync is an error, refreshes pending, and can be retried', async () => {
  let offline = true
  const ctx = await mount(path => {
    if (path.endsWith('/connection')) return reply(metadata)
    if (path.endsWith('/run')) return reply({ ...status, status: offline ? 'error' : 'ok', lastError: offline ? 'unreachable' : null, pushed: offline ? 0 : 3, pulled: 0, workspaceRevision: null })
    return reply(status)
  })
  try {
    await ctx.state.sync()
    assert.equal(ctx.state.syncResult.value.status, 'error')
    assert.equal(ctx.state.syncStatus.value.pending, 3)
    assert.match(ctx.state.syncError.value, /无法连接 Core/)
    assert.ok(!ctx.messages.some(message => message.startsWith('同步完成')))
    offline = false
    await ctx.state.sync()
    assert.equal(ctx.state.syncResult.value.status, 'ok')
    assert.equal(ctx.state.syncError.value, '')
  } finally { ctx.close() }
})

test('invalid Client stays connected; Core login 401 does not log out Local user', async () => {
  const ctx = await mount(path => {
    if (path.endsWith('/connect')) return reply({ detail: 'Core login failed' }, 401)
    if (path.endsWith('/me')) return reply({ id: 1, username: 'local-user' })
    return reply(path.endsWith('/connection') ? { connected: false } : status)
  })
  try {
    await ctx.state.connect({})
    assert.equal(ctx.auth.token, 'local-test-token')
    assert.match(ctx.state.connectionError.value, /用户名或密码/)
  } finally { ctx.close() }
  const invalid = await mount(path => reply(path.endsWith('/test') ? { connected: false, status: 'unauthorized' } : path.endsWith('/connection') ? metadata : status))
  try {
    await invalid.state.test()
    assert.equal(invalid.state.connection.value.connected, true)
    assert.equal(invalid.state.connectionTest.value.status, 'unauthorized')
    assert.ok(!invalid.calls.some(call => call.options.method === 'DELETE' || call.path.endsWith('/connect')))
  } finally { invalid.close() }
})

test('expired Local JWT uses existing auth restore/logout', async () => {
  const ctx = await mount(path => path.endsWith('/run') || path.endsWith('/me') ? reply({ detail: 'Invalid token' }, 401) : reply(path.endsWith('/connection') ? metadata : status))
  try { await ctx.state.sync(); assert.equal(ctx.auth.token, null) } finally { ctx.close() }
})

test('request errors and sync error codes never expose arbitrary response data', () => {
  for (const code of [0, 401, 409, 422, 500, 502]) assert.ok(coreSyncRequestError(new ApiError(code, 'private response body')).length > 0)
  assert.ok(!coreSyncRequestError(new ApiError(502, 'private response body')).includes('private'))
  assert.ok(!syncErrorMessage('private response body').includes('private'))
  assert.match(syncErrorMessage('protocol_mismatch'), /协议不兼容/)
  assert.match(syncErrorMessage('timeout'), /超时/)
  for (const code of ['__proto__', 'constructor', 'toString']) {
    assert.equal(syncErrorMessage(code), '同步失败（未知错误）')
    assert.equal(typeof coreSyncRequestError(new ApiError(502, code)), 'string')
  }
})

test('low frequency polling only reads Local status and updates background progress', async () => {
  let currentStatus = status
  const ctx = await mount(path => reply(path.endsWith('/connection') ? metadata : currentStatus))
  try {
    assert.equal(CORE_SYNC_STATUS_POLL_INTERVAL_MS, 5_000)
    assert.equal(ctx.calls.length, 2)
    await ctx.advance(CORE_SYNC_STATUS_POLL_INTERVAL_MS - 1)
    assert.equal(ctx.calls.length, 2)
    currentStatus = { ...status, running: true, pending: 2, inFlight: 1, lastAttemptAt: '2026-10-02T02:00:00Z' }
    await ctx.advance(1)
    assert.equal(ctx.state.syncStatus.value.running, true)
    assert.equal(ctx.state.syncStatus.value.inFlight, 1)
    assert.equal(ctx.state.busy.value, false)
    currentStatus = { ...status, pending: 0, lastSuccessAt: '2026-10-02T02:00:01Z' }
    await ctx.advance(3 * CORE_SYNC_STATUS_POLL_INTERVAL_MS)
    assert.equal(ctx.calls.length, 6)
    assert.equal(ctx.state.syncStatus.value.pending, 0)
    for (const call of ctx.calls.slice(2)) {
      assert.equal(call.path, '/api/v1/sync/status')
      assert.ok(!call.options.method || call.options.method === 'GET')
    }
    assert.deepEqual(ctx.messages, [])
  } finally { ctx.close() }
})

test('status polling failures are quiet and recovery clears a stale manual error', async () => {
  let currentStatus = { ...status, lastError: 'unreachable', nextRetryAt: '2026-10-02T02:00:05Z' }
  let failPoll = false
  const ctx = await mount(path => {
    if (path.endsWith('/connection')) return reply(metadata)
    if (path.endsWith('/run')) return reply({ ...status, status: 'error', lastError: 'unreachable', pushed: 0, pulled: 0, workspaceRevision: null })
    if (failPoll) return reply({ detail: 'private response body nc_live_do_not_show' }, 503)
    return reply(currentStatus)
  })
  try {
    await ctx.state.sync()
    assert.match(ctx.state.syncError.value, /无法连接 Core/)
    const messageCount = ctx.messages.length
    failPoll = true
    await ctx.advance(3 * CORE_SYNC_STATUS_POLL_INTERVAL_MS)
    assert.equal(ctx.state.syncStatus.value.pending, 3)
    assert.equal(ctx.state.syncStatus.value.lastError, 'unreachable')
    assert.equal(ctx.messages.length, messageCount)
    assert.equal(ctx.state.connectionError.value, '')
    failPoll = false
    currentStatus = { ...status, pending: 0, lastSuccessAt: '2026-10-02T02:00:30Z' }
    await ctx.advance(CORE_SYNC_STATUS_POLL_INTERVAL_MS)
    assert.equal(ctx.state.syncStatus.value.pending, 0)
    assert.equal(ctx.state.syncError.value, '')
    assert.equal(ctx.state.syncResult.value, null)
    assert.equal(ctx.messages.length, messageCount)
  } finally { ctx.close() }
})

test('polling never overlaps and unmount aborts the request and timer', async () => {
  let statusReads = 0
  let finishPoll
  let pollSignal
  const ctx = await mount((path, options) => {
    if (path.endsWith('/connection')) return reply(metadata)
    if (++statusReads === 1) return reply(status)
    pollSignal = options.signal
    // Ignore abort in this fake transport to verify the stale result guard too.
    return new Promise(resolve => { finishPoll = resolve })
  })
  try {
    await ctx.advance(CORE_SYNC_STATUS_POLL_INTERVAL_MS)
    assert.equal(statusReads, 2)
    assert.equal(pollSignal.aborted, false)
    await ctx.advance(10 * CORE_SYNC_STATUS_POLL_INTERVAL_MS)
    assert.equal(statusReads, 2)
    ctx.unmount()
    assert.equal(pollSignal.aborted, true)
    assert.equal(ctx.timers.size, 0)
    finishPoll(reply({ ...status, pending: 99 }))
    await settle()
    await ctx.advance(10 * CORE_SYNC_STATUS_POLL_INTERVAL_MS)
    assert.equal(statusReads, 2)
    assert.equal(ctx.state.syncStatus.value.pending, 3)
    assert.deepEqual(ctx.messages, [])
  } finally { ctx.close() }
})

test('auth session changes reload state and discard old responses even when the same token returns', async () => {
  const initialReplies = new Map()
  const ctx = await mount((path, options) => {
    if (!initialReplies.has(path)) return new Promise(resolve => { initialReplies.set(path, resolve) })
    const next = options.headers.Authorization.endsWith('-next')
    return reply(path.endsWith('/connection') ? { ...metadata, clientName: next ? 'Next session' : 'Current session' } : { ...status, pending: next ? 8 : 1 })
  })
  try {
    assert.equal(ctx.state.syncStatus.value, null)
    ctx.auth.token = 'local-test-token-next'
    await settle()
    assert.equal(ctx.state.syncStatus.value.pending, 8)
    ctx.auth.token = 'local-test-token'
    await settle()
    assert.equal(ctx.state.syncStatus.value.pending, 1)
    for (const [path, resolve] of initialReplies) resolve(reply(path.endsWith('/connection') ? { ...metadata, clientName: 'Stale session' } : { ...status, pending: 99 }))
    await settle()
    assert.equal(ctx.state.connection.value.clientName, 'Current session')
    assert.equal(ctx.state.syncStatus.value.pending, 1)
    assert.equal(ctx.state.busy.value, false)
    assert.equal(ctx.timers.size, 1)
    ctx.auth.logout()
    assert.equal(ctx.state.connection.value, null)
    assert.equal(ctx.state.syncStatus.value, null)
    assert.equal(ctx.timers.size, 0)
    const calls = ctx.calls.length
    await ctx.advance(10 * CORE_SYNC_STATUS_POLL_INTERVAL_MS)
    assert.equal(ctx.calls.length, calls)
  } finally { ctx.close() }
})

test('changing auth aborts an in-flight poll and ignores its late status', async () => {
  let originalStatusReads = 0
  let finishPoll
  let pollSignal
  const ctx = await mount((path, options) => {
    if (path.endsWith('/connection')) return reply(metadata)
    if (options.headers.Authorization.endsWith('-next')) return reply({ ...status, pending: 7 })
    if (++originalStatusReads === 1) return reply(status)
    pollSignal = options.signal
    return new Promise(resolve => { finishPoll = resolve })
  })
  try {
    await ctx.advance(CORE_SYNC_STATUS_POLL_INTERVAL_MS)
    ctx.auth.token = 'local-test-token-next'
    assert.equal(pollSignal.aborted, true)
    await settle()
    assert.equal(ctx.state.syncStatus.value.pending, 7)
    finishPoll(reply({ ...status, pending: 99, blocked: true, lastError: 'unauthorized' }))
    await settle()
    assert.equal(ctx.state.syncStatus.value.pending, 7)
    assert.equal(ctx.state.syncStatus.value.blocked, false)
    assert.equal(ctx.timers.size, 1)
    assert.deepEqual(ctx.messages, [])
  } finally { ctx.close() }
})

test('manual sync can join a backend cycle and late errors cannot affect a new session', async () => {
  let finishRun
  const ctx = await mount(path => {
    if (path.endsWith('/connection')) return reply(metadata)
    if (path.endsWith('/run')) return new Promise(resolve => { finishRun = resolve })
    return reply({ ...status, running: true })
  })
  try {
    assert.equal(ctx.state.syncStatus.value.running, true)
    assert.equal(ctx.state.busy.value, false)
    const syncing = ctx.state.sync()
    await ctx.state.sync()
    assert.equal(ctx.calls.filter(call => call.path.endsWith('/run')).length, 1)
    await ctx.advance(CORE_SYNC_STATUS_POLL_INTERVAL_MS)
    assert.ok(ctx.calls.at(-1).path.endsWith('/status'))
    ctx.auth.token = 'local-test-token-next'
    await settle()
    finishRun(reply({ detail: 'Invalid token from the previous session' }, 401))
    await syncing
    assert.equal(ctx.auth.token, 'local-test-token-next')
    assert.equal(ctx.state.syncResult.value, null)
    assert.equal(ctx.state.syncError.value, '')
    assert.equal(ctx.state.action.value, null)
    assert.deepEqual(ctx.messages, [])
    assert.ok(!ctx.calls.some(call => call.path.endsWith('/me')))
  } finally { ctx.close() }
})

for (const result of ['expired', 'success']) {
  test(`late auth restore ${result} cannot log out or overwrite a replacement session`, async () => {
    let finishRestore
    const ctx = await mount(path => path.endsWith('/me') ? new Promise(resolve => { finishRestore = resolve }) : reply(path.endsWith('/connection') ? metadata : status))
    try {
      const restoring = ctx.auth.restore().catch(() => {})
      ctx.auth.token = 'local-test-token-next'
      ctx.auth.user = { id: 2, username: 'new-local-user' }
      await settle()
      finishRestore(result === 'expired' ? reply({ detail: 'Invalid token' }, 401) : reply({ id: 1, username: 'old-local-user' }))
      await restoring
      assert.equal(ctx.auth.token, 'local-test-token-next')
      assert.equal(ctx.auth.user.id, 2)
    } finally { ctx.close() }
  })
}

test('automatic status labels preserve Local safety and show only safe errors', () => {
  const display = values => syncStatusDisplay({ ...status, ...values }, Date.parse('2026-10-02T02:00:30Z'))
  assert.deepEqual(display({ pending: 0, lastSuccessAt: '2026-10-02T02:00:01Z' }), { label: '已同步', detail: '刚刚', tone: 'success' })
  assert.match(display({ running: true }).label, /正在同步/)
  assert.equal(display({}).label, '等待同步')
  const offline = display({ inFlight: 2, lastError: 'unreachable' })
  assert.equal(offline.label, 'Core 离线')
  assert.match(offline.detail, /5 个更改已安全保存在本机/)
  assert.equal(display({ lastError: 'timeout' }).label, 'Core 离线')
  assert.match(display({ connected: false }).detail, /安全保存在本机/)
  assert.match(display({ conflicts: 2 }).detail, /2 个同步冲突/)
  assert.match(display({ rejected: 1 }).detail, /1 个更改已被拒绝/)
  assert.match(display({ blocked: true, lastError: 'unauthorized' }).detail, /凭证无效/)
  assert.match(display({ blocked: true, lastError: 'workspace_binding_conflict' }).detail, /Core 身份/)
  assert.equal(display({ blocked: true, lastError: 'private response body nc_live_secret' }).detail, '同步失败（未知错误）')
  assert.ok(!display({ lastError: 'private response body nc_live_secret' }).detail.includes('nc_live'))
})

const conflict = {
  id: 'conflict-1', entityType: 'ledger.transaction', entityId: 'coffee-1',
  local: { type: 'expense', amount: '38.00', categoryId: 'category-1', description: 'Coffee', merchant: 'Starbucks', note: 'Local note', occurredAt: '2026-10-03T08:30:00+08:00' },
  localDeleted: false,
  remote: { type: 'expense', amount: '42.00', categoryId: 'category-1', description: 'Coffee', merchant: 'Starbucks', note: 'Core note', occurredAt: '2026-10-03T08:35:00+08:00' },
  remoteRevision: 6, remoteDeleted: false, createdAt: '2026-10-03T00:30:00Z', detectedAt: '2026-10-03T00:36:00Z', updatedAt: '2026-10-03T00:36:00Z', hasPendingTail: true,
}
function conflictHandler(overrides = {}) {
  return (path, options) => {
    if (overrides[path]) return overrides[path](options)
    if (path === '/api/v1/sync/conflicts') return reply({ conflicts: [conflict] })
    if (path === `/api/v1/sync/conflicts/${conflict.id}`) return reply(conflict)
    if (path === '/api/v1/ledger/categories') return reply([{ id: 'category-1', name: '餐饮' }])
    if (path === '/api/v1/sync/status') return reply({ ...status, conflicts: 0 })
    throw new Error(`Unexpected request: ${path}`)
  }
}

test('Conflict Center loads persistent conflicts/detail and readable parent names without triggering sync', async () => {
  const ctx = await mount(conflictHandler(), true)
  try {
    assert.equal(ctx.state.conflicts.value.length, 1)
    assert.equal(ctx.state.selected.value.local.amount, '38.00')
    assert.equal(ctx.state.selected.value.remoteRevision, 6)
    assert.equal(ctx.state.references.value['category-1'], '餐饮')
    assert.equal(ctx.calls.filter(call => call.path.endsWith('/run')).length, 0)
    assert.equal(ctx.timers.size, 0)
    ctx.open.value = false
    assert.equal(ctx.state.selected.value, null)
    ctx.open.value = true
    await settle()
    assert.equal(ctx.state.conflicts.value.length, 1)
    assert.equal(ctx.state.selected.value.id, conflict.id)
  } finally { ctx.close() }
})

for (const strategy of ['local', 'remote']) {
  test(`Conflict Center ${strategy} requires confirmation, prevents duplicate submits and immediately refreshes status`, async () => {
    let resolved = false
    let finishResolve
    const path = `/api/v1/sync/conflicts/${conflict.id}/resolve`
    const ctx = await mount(conflictHandler({
      '/api/v1/sync/conflicts': () => reply({ conflicts: resolved ? [] : [conflict] }),
      [path]: options => new Promise(resolve => { finishResolve = () => { resolved = true; resolve(reply({ id: conflict.id, strategy, status: 'resolved', remoteRevision: 6, mutationId: strategy === 'local' ? 'new-mutation' : null, resolvedAt: '2026-10-03T00:40:00Z' })) } }),
    }), true)
    try {
      const choosing = ctx.state.resolve(strategy)
      assert.equal(ctx.state.resolving.value, true)
      assert.match(confirmation.value.message, strategy === 'remote' ? /后续编辑.*将被放弃/ : /当前最新本机数据/)
      assert.equal(ctx.calls.filter(call => call.path === path).length, 0)
      const selectedBefore = ctx.state.selected.value
      await ctx.state.select('another-conflict')
      await ctx.state.refresh()
      assert.equal(ctx.state.selected.value, selectedBefore)
      await ctx.state.resolve(strategy)
      resolveConfirmation(true)
      await settle()
      assert.equal(ctx.calls.filter(call => call.path === path).length, 1)
      const request = ctx.calls.find(call => call.path === path)
      assert.equal(request.options.method, 'POST')
      assert.deepEqual(JSON.parse(request.options.body), { strategy, expectedRemoteRevision: 6 })
      finishResolve()
      await choosing
      assert.equal(ctx.state.conflicts.value.length, 0)
      assert.equal(ctx.state.selected.value, null)
      assert.equal(ctx.state.resolving.value, false)
      assert.equal(ctx.statusRefreshes.length, 1)
      assert.equal(ctx.statusRefreshes[0].conflicts, 0)
      assert.equal(ctx.messages.length, 1)
      assert.equal(ctx.calls.filter(call => call.path.endsWith('/run')).length, 0)
    } finally { ctx.close() }
  })
  test(`cancel ${strategy} resolution preserves conflict and sends no mutation`, async () => {
    const ctx = await mount(conflictHandler(), true)
    try {
      const choosing = ctx.state.resolve(strategy)
      resolveConfirmation(false)
      await choosing
      assert.equal(ctx.state.selected.value.id, conflict.id)
      assert.equal(ctx.state.resolving.value, false)
      assert.equal(ctx.calls.filter(call => call.path.endsWith('/resolve')).length, 0)
      assert.deepEqual(ctx.statusRefreshes, [])
      assert.deepEqual(ctx.messages, [])
    } finally { ctx.close() }
  })
}

test('stale resolution refetches revision 7 and requires a new explicit confirmation', async () => {
  let revision = 6
  const ctx = await mount(conflictHandler({
    '/api/v1/sync/conflicts': () => reply({ conflicts: [{ ...conflict, remoteRevision: revision }] }),
    [`/api/v1/sync/conflicts/${conflict.id}`]: () => reply({ ...conflict, remoteRevision: revision, remote: { ...conflict.remote, amount: '44.00' } }),
    [`/api/v1/sync/conflicts/${conflict.id}/resolve`]: () => { revision = 7; return reply({ detail: 'conflict_snapshot_changed' }, 409) },
  }), true)
  try {
    const choosing = ctx.state.resolve('local')
    resolveConfirmation(true)
    await choosing
    assert.equal(ctx.state.selected.value.remoteRevision, 7)
    assert.match(ctx.state.error.value, /Core 版本已更新/)
    assert.equal(ctx.calls.filter(call => call.path.endsWith('/resolve')).length, 1)
    assert.equal(confirmation.value, null)
    assert.deepEqual(ctx.messages, [])
    const chooseAgain = ctx.state.resolve('local')
    assert.ok(confirmation.value)
    assert.equal(ctx.calls.filter(call => call.path.endsWith('/resolve')).length, 1)
    resolveConfirmation(false)
    await chooseAgain
  } finally { ctx.close() }
})

test('token change during conflict confirmation cannot resolve the previous session', async () => {
  const ctx = await mount(conflictHandler(), true)
  try {
    const choosing = ctx.state.resolve('remote')
    ctx.auth.token = 'local-test-token-next'
    resolveConfirmation(true)
    await choosing
    await settle()
    assert.equal(ctx.calls.filter(call => call.path.endsWith('/resolve')).length, 0)
    assert.deepEqual(ctx.messages, [])
    assert.deepEqual(ctx.statusRefreshes, [])
  } finally { ctx.close() }
})

test('closing Conflict Center aborts and ignores late detail from the previous view', async () => {
  let finishDetail
  let detailSignal
  const ctx = await mount(conflictHandler({
    [`/api/v1/sync/conflicts/${conflict.id}`]: options => { detailSignal = options.signal; return new Promise(resolve => { finishDetail = resolve }) },
  }), true)
  try {
    assert.equal(ctx.state.detailLoading.value, true)
    ctx.open.value = false
    assert.equal(detailSignal.aborted, true)
    finishDetail(reply(conflict))
    await settle()
    assert.equal(ctx.state.selected.value, null)
    assert.deepEqual(ctx.state.conflicts.value, [])
    assert.deepEqual(ctx.state.references.value, {})
    assert.equal(ctx.state.busy.value, false)
  } finally { ctx.close() }
})

test('late successful resolution cannot notify or overwrite a replacement auth session', async () => {
  let finishResolve
  const ctx = await mount(conflictHandler({
    [`/api/v1/sync/conflicts/${conflict.id}/resolve`]: () => new Promise(resolve => { finishResolve = resolve }),
  }), true)
  try {
    const choosing = ctx.state.resolve('local')
    resolveConfirmation(true)
    await settle()
    ctx.auth.token = 'local-test-token-next'
    await settle()
    finishResolve(reply({ id: conflict.id, strategy: 'local', status: 'resolved', remoteRevision: 6, mutationId: 'new-mutation', resolvedAt: '2026-10-03T00:40:00Z' }))
    await choosing
    assert.equal(ctx.state.selected.value.remoteRevision, 6)
    assert.equal(ctx.state.conflicts.value.length, 1)
    assert.deepEqual(ctx.messages, [])
    assert.deepEqual(ctx.statusRefreshes, [])
  } finally { ctx.close() }
})

test('parent lookup failure keeps conflicts actionable and never renders its arbitrary error body', async () => {
  const ctx = await mount(conflictHandler({ '/api/v1/ledger/categories': () => reply({ detail: 'private token nc_live_secret' }, 500) }), true)
  try {
    assert.equal(ctx.state.selected.value.id, conflict.id)
    assert.equal(ctx.state.busy.value, false)
    assert.deepEqual(ctx.state.references.value, {})
    assert.equal(ctx.state.error.value, '')
  } finally { ctx.close() }
})

test('Conflict Center loads website and collection parent names for the current session only', async () => {
  let finishParents
  let firstSession = true
  const websiteConflict = { ...conflict, id: 'website-conflict', entityType: 'website', local: { name: 'GitHub', categoryId: 'web-category' }, remote: { name: 'GitHub Core', categoryId: 'web-category' } }
  const recordConflict = { ...conflict, id: 'record-conflict', entityType: 'data.record', local: { name: 'Task', collectionId: 'collection-1' }, remote: { name: 'Core Task', collectionId: 'collection-1' } }
  const ctx = await mount((path, options) => {
    if (path === '/api/v1/sync/conflicts') return reply({ conflicts: [websiteConflict, recordConflict] })
    if (path === '/api/v1/website-categories') return reply([{ id: 'web-category', name: firstSession ? '旧用户开发分类' : '开发' }])
    if (path === '/api/v1/data/collections') {
      if (firstSession) return new Promise(resolve => { finishParents = resolve })
      return reply([{ id: 'collection-1', name: 'Tasks', records: [] }])
    }
    if (path === '/api/v1/sync/conflicts/website-conflict') return reply(websiteConflict)
    if (path === '/api/v1/sync/conflicts/record-conflict') return reply(recordConflict)
    throw new Error(`Unexpected request: ${path}`)
  }, true)
  try {
    firstSession = false
    ctx.auth.token = 'local-test-token-next'
    await settle()
    assert.deepEqual(ctx.state.references.value, { 'web-category': '开发', 'collection-1': 'Tasks' })
    finishParents(reply([{ id: 'collection-1', name: '旧用户集合', records: [] }]))
    await settle()
    assert.deepEqual(ctx.state.references.value, { 'web-category': '开发', 'collection-1': 'Tasks' })
    await ctx.state.select('record-conflict')
    assert.equal(conflictFields(ctx.state.selected.value, ctx.state.references.value).find(field => field.key === 'collectionId').local, 'Tasks')
  } finally { ctx.close() }
})

test('choosing another conflict ignores an older detail response even when the request finishes later', async () => {
  let finishOldDetail
  let oldSignal
  let deferOld = false
  const other = { ...conflict, id: 'conflict-2', local: { ...conflict.local, description: 'Tea' } }
  const ctx = await mount(conflictHandler({
    '/api/v1/sync/conflicts': () => reply({ conflicts: [conflict, other] }),
    [`/api/v1/sync/conflicts/${conflict.id}`]: options => {
      if (!deferOld) return reply(conflict)
      oldSignal = options.signal
      return new Promise(resolve => { finishOldDetail = resolve })
    },
    '/api/v1/sync/conflicts/conflict-2': () => reply(other),
  }), true)
  try {
    deferOld = true
    const old = ctx.state.select(conflict.id)
    await ctx.state.select(other.id)
    assert.equal(oldSignal.aborted, true)
    assert.equal(ctx.state.selected.value.id, other.id)
    finishOldDetail(reply(conflict))
    await old
    assert.equal(ctx.state.selected.value.id, other.id)
    assert.equal(ctx.state.busy.value, false)
  } finally { ctx.close() }
})

test('conflict resolution controlled errors are readable and arbitrary server bodies stay private', async () => {
  assert.match(conflictRequestError(new ApiError(409, 'collection_not_found')), /关联集合/)
  assert.match(conflictRequestError(new ApiError(409, 'invalid_conflict_snapshot')), /快照无效/)
  for (const code of [0, 401, 404, 409, 422, 500]) {
    const text = conflictRequestError(new ApiError(code, 'traceback bearer nc_live_secret password'))
    assert.doesNotMatch(text, /nc_live|traceback|bearer|password/)
  }
  const ctx = await mount(conflictHandler({ [`/api/v1/sync/conflicts/${conflict.id}/resolve`]: () => reply({ detail: 'bearer nc_live_secret traceback password' }, 500) }), true)
  try {
    const choosing = ctx.state.resolve('remote')
    resolveConfirmation(true)
    await choosing
    assert.match(ctx.state.error.value, /本机数据已保留/)
    assert.doesNotMatch(ctx.state.error.value, /nc_live|traceback|bearer|password/)
    assert.equal(ctx.state.selected.value.id, conflict.id)
  } finally { ctx.close() }
})

test('six entity presentations use readable field labels, names, diff highlights and collapsed JSON metadata', () => {
  const transaction = conflictFields(conflict, { 'category-1': '餐饮' })
  assert.equal(conflictTitle(conflict), 'Coffee')
  assert.equal(transaction.find(field => field.key === 'amount').local, '¥38.00')
  assert.equal(transaction.find(field => field.key === 'amount').remote, '¥42.00')
  assert.equal(transaction.find(field => field.key === 'amount').different, true)
  assert.equal(transaction.find(field => field.key === 'merchant').different, false)
  assert.equal(transaction.find(field => field.key === 'categoryId').local, '餐饮')
  const samples = [
    ['ledger.category', { name: '餐饮', type: 'expense', icon: 'coffee' }, ['名称', '类型', '图标']],
    ['website.category', { name: '开发', order: 1 }, ['名称', '排序']],
    ['website', { name: 'GitHub', url: 'https://github.com', favorite: true, categoryId: 'category-1' }, ['名称', 'URL', '收藏', '分类']],
    ['data.collection', { name: 'Tasks', description: 'Work', icon: 'custom', tone: 'blue' }, ['名称', '描述', '图标', '颜色']],
    ['data.record', { name: 'Plan', status: 'active', category: 'Work', collectionId: 'collection-1', dataJson: { b: 2, a: 1 } }, ['名称', '状态', '分类', '所属集合', '记录内容']],
  ]
  for (const [entityType, payload, labels] of samples) {
    const value = { ...conflict, entityType, local: payload, remote: { ...payload } }
    const fields = conflictFields(value, { 'category-1': '开发', 'collection-1': 'Tasks' })
    assert.ok(labels.every(label => fields.some(field => field.label === label)))
    assert.ok(fields.every(field => !field.different))
    assert.notEqual(conflictEntityLabel(entityType), '同步数据')
  }
  const record = { ...conflict, entityType: 'data.record', local: samples.at(-1)[1], remote: { ...samples.at(-1)[1], dataJson: { a: 1, b: 2 } } }
  const jsonField = conflictFields(record).find(field => field.key === 'dataJson')
  assert.equal(jsonField.json, true)
  assert.match(jsonField.local, /\n/)
  assert.equal(jsonField.different, false)
  assert.equal(detectedTime('2026-10-03T00:36:00Z', Date.parse('2026-10-03T00:36:10Z')), '刚刚检测到')
})

test('delete and absent Core presentations/confirmations describe tombstones, restore and dependent-tail loss', () => {
  const remoteDeleted = { ...conflict, remote: null, remoteDeleted: true }
  assert.ok(conflictFields(remoteDeleted).every(field => field.remote === '已删除'))
  assert.match(conflictConfirmation(remoteDeleted, 'local'), /恢复 Core 中已删除的数据/)
  assert.match(conflictConfirmation(remoteDeleted, 'remote'), /后续编辑.*将被放弃.*本机也将删除/)
  const localDeleted = { ...conflict, localDeleted: true }
  assert.ok(conflictFields(localDeleted).every(field => field.local === '已删除'))
  assert.match(conflictConfirmation(localDeleted, 'local'), /本机删除操作/)
  const absent = { ...conflict, remote: null, remoteDeleted: false, remoteRevision: 0 }
  assert.ok(conflictFields(absent).every(field => field.remote === 'Core 中不存在'))
  assert.match(conflictConfirmation(absent, 'remote'), /Core 中不存在此数据，本机也将删除/)
})
