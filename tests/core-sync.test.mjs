import test from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'

// Bundle the real Vue composable and its dependencies for Node; no alternate
// HTTP implementation or browser-only test dependency is needed.
const bundle = await build({
  stdin: { contents: `
    export { useCoreSync, CORE_SYNC_STATUS_POLL_INTERVAL_MS } from './src/composables/useCoreSync.ts'
    export { useAuthStore } from './src/stores/auth.ts'
    export { resolveConfirmation, confirmation } from './src/composables/useConfirm.ts'
    export { coreSyncRequestError, syncErrorMessage, syncStatusDisplay } from './src/services/coreSyncErrors.ts'
    export { ApiError } from './src/api/client.ts'
    export { createRenderer } from 'vue'
    export { createPinia } from 'pinia'
  `, resolveDir: process.cwd() },
  bundle: true, write: false, platform: 'node', format: 'esm',
  define: { 'import.meta.env.VITE_API_BASE_URL': '""', 'process.env.NODE_ENV': '"production"' },
})
const { useCoreSync, CORE_SYNC_STATUS_POLL_INTERVAL_MS, useAuthStore, resolveConfirmation, confirmation, coreSyncRequestError,
  syncErrorMessage, syncStatusDisplay, ApiError, createRenderer, createPinia } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`)

const metadata = { connected: true, coreUrl: 'http://127.0.0.1:8000', clientId: 'client', workspaceId: 'workspace', installationId: 'installation', clientName: 'Nexa Windows', platform: 'windows', appVersion: '0.5.6', connectedAt: '2026-10-02T01:00:00Z' }
const status = { enabled: true, running: false, connected: true, blocked: false, pending: 3, conflicts: 0, inFlight: 0, rejected: 0, cursor: 0, queueSeeded: true, lastAttemptAt: null, lastSuccessAt: null, nextRetryAt: null, lastError: null }
const reply = (value, code = 200) => new Response(JSON.stringify(value), { status: code, headers: { 'Content-Type': 'application/json' } })
async function settle() { for (let i = 0; i < 12; i++) await new Promise(resolve => setImmediate(resolve)) }

async function mount(handler) {
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
  let state
  const app = renderer.createApp({ setup() { state = useCoreSync(message => messages.push(message)); return () => null } })
  app.use(pinia)
  app.mount({})
  await settle()
  let unmounted = false
  const unmount = () => { if (!unmounted) { unmounted = true; app.unmount() } }
  return { state, auth, calls, messages, saved, timers, advance, unmount, close() { unmount(); Object.assign(globalThis, previous) } }
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
