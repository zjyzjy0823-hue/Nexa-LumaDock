import test from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'

// Bundle the real Vue composable and its dependencies for Node; no alternate
// HTTP implementation or browser-only test dependency is needed.
const bundle = await build({
  stdin: { contents: `
    export { useCoreSync } from './src/composables/useCoreSync.ts'
    export { useAuthStore } from './src/stores/auth.ts'
    export { resolveConfirmation, confirmation } from './src/composables/useConfirm.ts'
    export { coreSyncRequestError, syncErrorMessage } from './src/services/coreSyncErrors.ts'
    export { ApiError } from './src/api/client.ts'
    export { createRenderer } from 'vue'
    export { createPinia } from 'pinia'
  `, resolveDir: process.cwd() },
  bundle: true, write: false, platform: 'node', format: 'esm',
  define: { 'import.meta.env.VITE_API_BASE_URL': '""', 'process.env.NODE_ENV': '"production"' },
})
const { useCoreSync, useAuthStore, resolveConfirmation, confirmation, coreSyncRequestError,
  syncErrorMessage, ApiError, createRenderer, createPinia } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`)

const metadata = { connected: true, coreUrl: 'http://127.0.0.1:8000', clientId: 'client', workspaceId: 'workspace', installationId: 'installation', clientName: 'Nexa Windows', platform: 'windows', appVersion: '0.5.6', connectedAt: '2026-10-02T01:00:00Z' }
const status = { pending: 3, conflicts: 0, inFlight: 0, rejected: 0, cursor: 0, queueSeeded: true, lastSuccessAt: null, lastError: null }
const reply = (value, code = 200) => new Response(JSON.stringify(value), { status: code, headers: { 'Content-Type': 'application/json' } })
async function settle() { for (let i = 0; i < 12; i++) await new Promise(resolve => setImmediate(resolve)) }

async function mount(handler) {
  const previous = { fetch: globalThis.fetch, localStorage: globalThis.localStorage }
  const saved = new Map()
  globalThis.localStorage = { getItem: key => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value), removeItem: key => saved.delete(key) }
  const calls = []
  globalThis.fetch = async (path, options) => {
    calls.push({ path, options })
    assert.equal(options.headers.Authorization, 'Bearer local-test-token')
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
  return { state, auth, calls, messages, saved, unmount: () => app.unmount(), close() { app.unmount(); globalThis.fetch = previous.fetch; globalThis.localStorage = previous.localStorage } }
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
})
