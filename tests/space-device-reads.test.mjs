import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { compileScript, parse } from '@vue/compiler-sfc'
import { build } from 'esbuild'

const bundle = await build({
  stdin: {
    contents: `
      export { createPinia, disposePinia } from 'pinia'
      export { createSSRApp } from 'vue'
      export { renderToString } from 'vue/server-renderer'
      export { default as SpacePage } from './src/pages/SpacePage.vue'
      export { useAuthStore } from './src/stores/auth.ts'
      export { useFleetStore } from './src/stores/fleet.ts'
      export { useSpaceStore } from './src/stores/space.ts'
      export { setApiBaseUrl } from './src/services/fleetUrl.ts'
      export { downloadEntryBlob, downloadSpaceBlobChunk, fetchSpaceEntries, fetchSpaceEntryDetail } from './src/services/spaceApi.ts'
    `,
    resolveDir: process.cwd(),
  },
  bundle: true, write: false, platform: 'node', format: 'esm',
  define: { 'process.env.NODE_ENV': '"production"' },
  plugins: [{
    name: 'vue',
    setup(builder) {
      builder.onLoad({ filter: /\.vue$/ }, async ({ path }) => {
        const { descriptor } = parse(await readFile(path, 'utf8'), { filename: path })
        return { contents: compileScript(descriptor, { id: path, inlineTemplate: true }).content, loader: 'ts' }
      })
    },
  }],
})
const {
  createPinia, disposePinia, createSSRApp, renderToString, SpacePage, useAuthStore, useFleetStore, useSpaceStore, setApiBaseUrl,
  downloadEntryBlob, downloadSpaceBlobChunk, fetchSpaceEntries, fetchSpaceEntryDetail,
} = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`)

const localOrigin = 'http://127.0.0.1:4100'
const coreOrigin = 'https://core.example'
const standardPath = '/api/v1/spaces'
const devicePath = '/api/v1/core/space-reads/spaces'
const pairing = {
  connected: true, coreUrl: coreOrigin, clientId: 'client', workspaceId: 'workspace',
  installationId: 'installation', clientName: 'Sidecar', platform: 'macos', appVersion: '0.8.0', connectedAt: '2026-10-02T01:00:00Z',
}
const space = {
  id: '7c8e7809-9e85-4421-8925-fe2145d280d9', name: 'Core notes', tier: 'standard',
  entryCount: 1, usedBytes: 4, quotaBytes: 1024,
}
const entry = {
  id: '37bdda79-dc98-4158-9e27-26942f2ec733', spaceId: space.id, tier: 'standard', entryType: 'file',
  fileName: 'notes.txt', revision: 1, sizeBytes: 4, tags: [],
}
const entryPath = `/${space.id}/entries/${entry.id}`
const reply = (value, status = 200) => Response.json(value, { status })

async function fixture(t, handler = () => { throw new Error('Unexpected request') }) {
  setApiBaseUrl(localOrigin)
  const saved = new Map([['studiolo:access-token', 'local-jwt']])
  let replicaOpens = 0
  const globals = {
    localStorage: { getItem: key => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value), removeItem: key => saved.delete(key) },
    indexedDB: { open: () => { replicaOpens++; throw new Error('Replica opened') } },
  }
  for (const [key, value] of Object.entries(globals)) {
    const previous = Object.getOwnPropertyDescriptor(globalThis, key)
    Object.defineProperty(globalThis, key, { value, configurable: true })
    t.after(() => previous ? Object.defineProperty(globalThis, key, previous) : delete globalThis[key])
  }
  const calls = []
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    if (url === localOrigin + '/api/v1/auth/me') return reply({ id: 1, created_at: '2026-01-01' })
    calls.push({ url, method: options.method ?? 'GET', auth: options.headers.Authorization })
    return handler(url, options)
  })
  const pinia = createPinia()
  t.after(() => disposePinia(pinia))
  const auth = useAuthStore(pinia)
  await auth.restore()
  assert.ok(auth.replicaAccount)
  auth.workstation = true
  auth.coreConnection = { ...pairing }
  const store = useSpaceStore(pinia)
  return { auth, store, pinia, fleet: useFleetStore(pinia), calls, replicaOpens: () => replicaOpens }
}

test('paired Local without a Core user session uses the device route and stays on that route after a metadata refresh', async t => {
  const { auth, store, fleet } = await fixture(t, url => {
    if (url === coreOrigin + '/api/v1/auth/login') return reply({ access_token: 'core-user-jwt' })
    if (url === coreOrigin + '/api/v1/workspace') return reply({ id: pairing.workspaceId })
    assert.fail(`Unexpected request: ${url}`)
  })
  const deviceRoute = store.route
  assert.deepEqual(deviceRoute, { kind: 'device-read', origin: localOrigin, token: 'local-jwt' })
  assert.equal(store.deviceReadOnly, true)
  assert.equal(store.coreSignInRequired, false)
  assert.equal(store.available, true)
  assert.equal(store.usingReplica, false)
  auth.coreConnection = { ...pairing }
  assert.equal(store.route, deviceRoute)

  await fleet.signInToCoreFleet('owner', 'password')
  assert.deepEqual(store.route, { kind: 'user', origin: coreOrigin, token: 'core-user-jwt' })
  assert.equal(store.deviceReadOnly, false)
  assert.equal(store.usingReplica, true)
  store.localView = true
  assert.deepEqual(store.route, { kind: 'user', origin: localOrigin, token: 'local-jwt' })
  store.localView = false
  auth.coreConnection = { connected: false }
  assert.deepEqual(store.route, { kind: 'user', origin: localOrigin, token: 'local-jwt' })
})

test('device reads use Local JWT and proxy paths, with no replica, draft, or write access', async t => {
  const { store, calls, replicaOpens } = await fixture(t, url => {
    const parsed = new URL(url)
    if (parsed.pathname === devicePath) return reply([space])
    if (parsed.pathname === devicePath + `/${space.id}`) return reply(space)
    if (parsed.pathname === devicePath + `/${space.id}/entries`) return reply([entry])
    if (parsed.pathname === devicePath + entryPath) return reply(entry)
    if (parsed.pathname === devicePath + entryPath + '/download') return new Response('file')
    if (parsed.pathname === devicePath + `/${space.id}/blobs/blob/chunks/1`) return new Response(Uint8Array.of(1, 2))
    assert.fail(`Unexpected request: ${url}`)
  })
  await store.loadSpaces()
  assert.deepEqual(store.capabilities, {
    enabled: true, tiers: ['standard'], protectedAvailable: false,
    maxFileBytes: 0, defaultQuotaBytes: 0, defaultChunkSize: 0,
  })
  assert.deepEqual(store.entries, [entry])
  await store.selectEntry(entry.id)
  assert.deepEqual(store.selectedEntryDetail, entry)
  assert.deepEqual(await fetchSpaceEntries(store.route, space.id, { search: 'a & b', entryType: 'file' }), [entry])
  const blob = await downloadEntryBlob(store.route, space.id, entry.id)
  assert.equal(await blob.text(), 'file')
  assert.deepEqual(await downloadSpaceBlobChunk(store.route, space.id, 'blob', 1), Uint8Array.of(1, 2))

  const requestsBeforeWrites = calls.length
  const denied = [
    () => store.createSpace({ name: 'Draft', tier: 'standard' }),
    () => store.createEntry({ title: 'Draft', entryType: 'text' }),
    () => store.createEntry({ title: 'File', entryType: 'file', file: new File(['draft'], 'draft.txt') }),
    () => store.updateStandardEntry(entry, 'Edit', 'draft', []),
    () => store.deleteCurrentEntry(),
    () => store.archiveSpace(space.id),
    () => store.issueToken({ name: 'test', scopes: ['read'] }),
    () => store.revokeToken('token'),
    () => store.loadTokensAndAudit(),
    () => store.loadConflicts(),
    () => store.resolveConflict({ current: entry }, 'core'),
    () => store.retrySpaceQueue(),
    () => store.importLocalStandardSpaces(),
    () => store.pinEncryptedEntry(),
    () => store.unpinEncryptedEntry(entry.id),
    () => downloadEntryBlob(store.route, space.id, entry.id, 'password'),
  ]
  for (const action of denied) await assert.rejects(action, { message: '设备只读：登录 Core 后可编辑' })
  await store.syncPending()
  assert.equal(calls.length, requestsBeforeWrites)
  assert.equal(replicaOpens(), 0)
  assert.equal(store.pendingCount, 0)
  assert.deepEqual(calls.map(call => call.url), [
    devicePath, devicePath + `/${space.id}/entries`, devicePath + `/${space.id}`,
    devicePath + entryPath, devicePath + `/${space.id}/entries?search=a+%26+b&entryType=file`,
    devicePath + entryPath + '/download', devicePath + `/${space.id}/blobs/blob/chunks/1`,
  ].map(path => localOrigin + path))
  assert.ok(calls.every(call => call.auth === 'Bearer local-jwt' && call.method === 'GET'))
})

test('user paths still use the original endpoint and requested revision', async t => {
  const { auth, store, calls } = await fixture(t, () => reply(entry))
  auth.coreConnection = { connected: false }
  await fetchSpaceEntryDetail(store.route, space.id, entry.id, 2)
  assert.deepEqual(calls, [{ url: localOrigin + standardPath + entryPath + '?revision=2', method: 'GET', auth: 'Bearer local-jwt' }])
})

test('the device page renders the Core login entry and download with management controls hidden', async t => {
  const { pinia, store } = await fixture(t, url => {
    if (url.endsWith(entryPath)) return reply(entry)
    if (url.endsWith('/entries')) return reply([entry])
    return reply(url.endsWith(space.id) ? space : [space])
  })
  await store.loadSpaces()
  await store.selectEntry(entry.id)
  const page = createSSRApp(SpacePage, { mobile: false })
  page.use(pinia)
  const html = await renderToString(page)
  assert.match(html, /设备只读 · 登录 Core 后可编辑/)
  assert.match(html, /<button[^>]+aria-expanded="false"[^>]*>登录 Core<\/button>/)
  assert.match(html, /notes\.txt/)
  assert.match(html, /下载/)
  const buttons = [...html.matchAll(/<button\b[\s\S]*?<\/button>/g)].map(match => match[0]).join('\n')
  assert.doesNotMatch(buttons, /新建|写文本|传文件|编辑|删除|导入本机普通空间|Token|审计|冲突|离线副本/)
})

for (const status of [401, 403, 404, 409, 502]) {
  test(`device list failure ${status} updates the route appropriately`, async t => {
    const { auth, store, calls, replicaOpens } = await fixture(t, () => reply({ detail: 'Core unavailable' }, status))
    await store.loadSpaces()
    assert.equal(store.coreSignInRequired, status !== 502)
    assert.equal(store.deviceReadOnly, status === 502)
    assert.equal(store.available, status === 502)
    assert.equal(store.error, status === 502 ? 'Core unavailable' : '')
    assert.equal(store.offline, false)
    assert.equal(store.usingReplica, false)
    assert.equal(replicaOpens(), 0)
    assert.equal(calls.length, 1)
    auth.coreConnection = { ...pairing, clientId: 'new-client' }
    assert.equal(store.deviceReadOnly, true)
  })
}

test('device authorization revocation clears an already loaded view', async t => {
  const { store } = await fixture(t, url => {
    if (url.endsWith(entryPath)) return reply({ detail: 'Core authorization required' }, 401)
    if (url.endsWith('/entries')) return reply([entry])
    return reply(url.endsWith(space.id) ? space : [space])
  })
  await store.loadSpaces()
  assert.deepEqual(store.entries, [entry])
  await store.selectEntry(entry.id)
  assert.equal(store.coreSignInRequired, true)
  assert.deepEqual(store.spaces, [])
  assert.deepEqual(store.entries, [])
  assert.equal(store.selectedEntryDetail, null)
})

test('an unavailable space clears its open entries without requiring a Core login', async t => {
  let removed = false
  const { store } = await fixture(t, url => {
    if (url.endsWith(entryPath)) return reply(entry)
    if (url.endsWith('/entries')) return removed ? reply({ detail: 'Not found' }, 404) : reply([entry])
    return reply(url.endsWith(space.id) ? space : [space])
  })
  await store.loadSpaces()
  await store.selectEntry(entry.id)
  assert.deepEqual(store.selectedEntryDetail, entry)
  removed = true
  await store.refreshCurrentSpace()
  assert.equal(store.deviceReadOnly, true)
  assert.deepEqual(store.entries, [])
  assert.equal(store.selectedEntryDetail, null)
})

test('returning to the device view discards a previously started download', async t => {
  let complete
  const response = new Promise(resolve => { complete = resolve })
  const { store } = await fixture(t, () => response)
  const download = store.downloadStandardEntry(entry)
  store.localView = true
  store.localView = false
  complete(new Response('file'))
  await download
})

for (const change of ['rebind', 'disconnect', 'logout']) {
  test(`discards in-flight device reads on ${change}`, async t => {
    let complete
    const response = new Promise(resolve => { complete = resolve })
    const { auth, store } = await fixture(t, () => response)
    const pending = store.loadSpaces()
    const originalRoute = store.route
    if (change === 'rebind') auth.coreConnection = { ...pairing, clientId: 'new-client' }
    else if (change === 'disconnect') auth.coreConnection = { connected: false }
    else auth.logout()
    assert.notEqual(store.route, originalRoute)
    complete(reply([space]))
    await pending
    assert.deepEqual(store.spaces, [])
    assert.deepEqual(store.entries, [])
    assert.equal(store.loading, false)
  })
}
