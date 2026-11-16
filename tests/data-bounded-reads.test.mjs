import test from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { readFileSync } from 'node:fs'
import { parse, compileScript } from '@vue/compiler-sfc'

// Exercise the real page setup, widgets, stores and HTTP client. Only the DOM
// host and backend are replaced; timers make the debounce boundary deterministic.
const bundle = await build({
  stdin: { contents: `
    export { default as DataTable } from './src/components/data/DataTable.vue'
    export { default as DataPage } from './src/pages/DataPage.vue'
    export { default as NotesWidget } from './src/components/widgets/NotesWidget.vue'
    export { default as CollectionsWidget } from './src/components/widgets/CollectionsWidget.vue'
    export { useDataStore } from './src/stores/data.ts'
    export { useAuthStore } from './src/stores/auth.ts'
    export { dataService } from './src/services/data.ts'
    export { createRenderer, nextTick, h, reactive } from 'vue'
    export { createPinia } from 'pinia'
  `, resolveDir: process.cwd(), loader: 'ts' },
  bundle: true, write: false, platform: 'node', format: 'esm',
  define: { 'import.meta.env.VITE_API_BASE_URL': '""', 'process.env.NODE_ENV': '"production"' },
  plugins: [{ name: 'vue-script', setup(builder) {
    builder.onLoad({ filter: /\.vue$/ }, ({ path: filename }) => {
      const { descriptor } = parse(readFileSync(filename, 'utf8'), { filename })
      return { contents: compileScript(descriptor, { id: filename, inlineTemplate: /\/(DataTable|GlassCard|ActionButton|StatusBadge)\.vue$/.test(filename) }).content, loader: 'ts' }
    })
  } }],
})
const { DataTable, DataPage, NotesWidget, CollectionsWidget, useDataStore, useAuthStore, dataService, createRenderer, createPinia, nextTick, h, reactive } =
  await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`)

const summary = id => ({ id, name: `集合 ${id}`, description: '', icon: 'custom', tone: 'blue', recordCount: 80, createdAt: '2026-11-01T00:00:00Z', updatedAt: '2026-11-02T00:00:00Z' })
const record = (id, collectionId = 'a') => ({ id, collectionId, name: `记录 ${id}`, status: 'active', category: 'work', createdAt: '2026-11-01T00:00:00Z', updatedAt: '2026-11-02T00:00:00Z' })
const page = (items = [record('r1')], extra = {}) => ({ items, nextCursor: 'cursor-a', hasMore: true, total: 80, matchedCount: 80, ...extra })
const overview = { totalCollections: 9, totalRecords: 900, active: 600, completed: 300, recentRecords: [{ ...record('recent'), collectionName: '远端集合' }] }
const reply = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
async function settle() { for (let i = 0; i < 8; i++) await new Promise(resolve => setImmediate(resolve)) }

async function mount(handler, component = null) {
  const previous = Object.fromEntries(['fetch', 'localStorage', 'document', 'setTimeout', 'clearTimeout'].map(key => [key, globalThis[key]]))
  const calls = [], messages = [], timers = new Map()
  let time = 0, timerId = 0, state
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  globalThis.document = { createElement: () => ({}), addEventListener() {}, removeEventListener() {} }
  globalThis.setTimeout = (callback, delay) => { const id = ++timerId; timers.set(id, { callback, at: time + delay }); return id }
  globalThis.clearTimeout = id => timers.delete(id)
  globalThis.fetch = async (path, options) => {
    assert.equal(options.headers.Authorization, 'Bearer bounded-test-token')
    const call = { path, options, url: new URL(path, 'http://local'), method: options.method ?? 'GET' }
    calls.push(call)
    return handler(call)
  }
  const pinia = createPinia(), auth = useAuthStore(pinia), store = useDataStore(pinia)
  auth.token = 'bounded-test-token'
  const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
  const app = renderer.createApp({ setup() {
    if (component) state = component.setup({}, { expose() {}, emit: (_event, message) => messages.push(message) })
    return () => null
  } })
  app.use(pinia).mount({})
  await settle()
  return { store, auth, state, calls, messages, timers,
    async advance(ms) {
      time += ms
      for (const [id, timer] of [...timers]) if (timer.at <= time) { timers.delete(id); timer.callback() }
      await settle()
    },
    close() { app.unmount(); pinia._s.clear(); Object.assign(globalThis, previous) },
  }
}
function defaultHandler(call) {
  if (call.url.pathname === '/api/v1/data/collections') return reply([summary('a'), summary('b')])
  if (call.url.pathname === '/api/v1/data/overview') return reply(overview)
  if (call.url.pathname.endsWith('/records')) {
    const id = call.url.pathname.split('/').at(-2)
    return reply(page([record(`${id}-first`, id)]))
  }
  throw new Error(`Unexpected request: ${call.path}`)
}
const recordCalls = ctx => ctx.calls.filter(call => call.method === 'GET' && call.url.pathname.endsWith('/records'))

test('collection summaries load without records or record-page requests and retain the cache', async () => {
  const ctx = await mount(defaultHandler)
  try {
    await ctx.store.load(ctx.auth.token)
    assert.equal(ctx.calls.length, 1)
    assert.equal(ctx.calls[0].url.searchParams.get('include_records'), 'false')
    assert.equal('records' in ctx.store.items[0], false)
    assert.equal(ctx.store.items[0].recordCount, 80)
    assert.deepEqual(ctx.store.pages, {})
    await ctx.store.load(ctx.auth.token)
    assert.equal(ctx.calls.length, 1)
  } finally { ctx.close() }
})

test('collection switching resets cursors including returning to a previously paged collection', async () => {
  const ctx = await mount(defaultHandler, DataPage)
  try {
    await ctx.state.loadMoreRecords()
    await settle()
    assert.equal(recordCalls(ctx).at(-1).url.searchParams.get('cursor'), 'cursor-a')
    ctx.state.selectedId.value = 'b'
    await settle()
    assert.equal(recordCalls(ctx).at(-1).url.pathname, '/api/v1/data/collections/b/records')
    assert.equal(recordCalls(ctx).at(-1).url.searchParams.get('cursor'), '')
    assert.deepEqual(ctx.state.visibleRecords.value.map(item => item.id), ['b-first'])
    ctx.state.selectedId.value = 'a'
    await settle()
    assert.equal(recordCalls(ctx).at(-1).url.searchParams.get('cursor'), '')
    assert.deepEqual(ctx.state.visibleRecords.value.map(item => item.id), ['a-first'])
    for (const call of recordCalls(ctx)) {
      assert.equal(call.url.searchParams.get('page'), 'true')
      assert.equal(call.url.searchParams.get('limit'), '50')
      assert.equal(call.url.searchParams.get('include_data_json'), 'false')
    }
  } finally { ctx.close() }
})

test('load more appends unique records, prevents duplicate requests and stops at the final page', async () => {
  let finishMore
  const ctx = await mount(call => {
    if (call.url.pathname.endsWith('/records') && call.url.searchParams.get('cursor')) return new Promise(resolve => { finishMore = resolve })
    return defaultHandler(call)
  })
  try {
    await ctx.store.loadRecords(ctx.auth.token, 'a')
    const more = ctx.store.loadMoreRecords(ctx.auth.token, 'a')
    await ctx.store.loadMoreRecords(ctx.auth.token, 'a')
    assert.equal(recordCalls(ctx).length, 2)
    finishMore(reply(page([record('a-first'), record('r2')], { nextCursor: null, hasMore: false })))
    await more
    assert.deepEqual(ctx.store.pages.a.items.map(item => item.id), ['a-first', 'r2'])
    assert.equal(ctx.store.pages.a.items[0].statusTone, 'info')
    assert.equal(ctx.store.pages.a.total, 80)
    await ctx.store.loadMoreRecords(ctx.auth.token, 'a')
    assert.equal(recordCalls(ctx).length, 2)
  } finally { ctx.close() }
})

test('search debounces 250ms and sends the same encoded server query to summaries and first record page', async () => {
  const ctx = await mount(defaultHandler, DataPage)
  try {
    await ctx.store.loadMoreRecords(ctx.auth.token, 'a')
    const before = ctx.calls.length
    ctx.state.query.value = 'first'
    await nextTick()
    await ctx.advance(200)
    assert.equal(ctx.calls.length, before)
    ctx.state.query.value = '  中文 & task  '
    await nextTick()
    await ctx.advance(249)
    assert.equal(ctx.calls.length, before)
    await ctx.advance(1)
    const calls = ctx.calls.slice(before)
    assert.equal(calls.length, 2)
    for (const call of calls) assert.equal(call.url.searchParams.get('q'), '中文 & task')
    assert.equal(recordCalls(ctx).at(-1).url.searchParams.get('cursor'), '')
    assert.equal(ctx.state.visibleCollections.value.length, 2, 'the client must keep server results even when names do not contain the query')
    assert.equal(ctx.state.visibleRecords.value.length, 1)
    await ctx.store.loadMoreRecords(ctx.auth.token, 'a')
    assert.equal(recordCalls(ctx).at(-1).url.searchParams.get('q'), '中文 & task')
    ctx.state.query.value = ''
    await nextTick(); await ctx.advance(250)
    assert.equal(recordCalls(ctx).at(-1).url.searchParams.get('q'), '')
    assert.equal(recordCalls(ctx).at(-1).url.searchParams.get('cursor'), '')
  } finally { ctx.close() }
})

test('overview drives total, active, completed and recent activity independently of loaded pages', async () => {
  const ctx = await mount(defaultHandler, DataPage)
  try {
    assert.equal(ctx.state.totalRecords.value, 900)
    assert.equal(ctx.state.dataOverview.value.active, 600)
    assert.equal(ctx.state.dataOverview.value.completed, 300)
    assert.equal(ctx.state.dataOverview.value.recentActivity, 1)
    assert.equal(ctx.state.dataOverview.value.activities[0].id, 'recent')
    ctx.store.pages = {}
    ctx.store.items = []
    assert.equal(ctx.state.totalRecords.value, 900)
    assert.equal(ctx.state.dataOverview.value.active, 600)
    assert.equal(ctx.calls.find(call => call.url.pathname.endsWith('/overview')).url.searchParams.get('recent_limit'), '4')
  } finally { ctx.close() }
})

test('NotesWidget loads only overview and CollectionsWidget displays summary recordCount', async () => {
  let ctx = await mount(defaultHandler, NotesWidget)
  try {
    assert.equal(ctx.calls.length, 1)
    assert.equal(ctx.calls[0].url.pathname, '/api/v1/data/overview')
    assert.equal(ctx.state.records.value[0].collection, '远端集合')
    assert.equal(ctx.state.records.value[0].id, 'recent')
  } finally { ctx.close() }
  ctx = await mount(defaultHandler, CollectionsWidget)
  try {
    assert.equal(ctx.calls.length, 1)
    assert.equal(ctx.calls[0].url.searchParams.get('include_records'), 'false')
    assert.equal(ctx.state.recordCount.value, 160)
    assert.equal('records' in ctx.state.items.value[0], false)
  } finally { ctx.close() }
})

for (const method of ['createRecord', 'updateRecord', 'removeRecord']) {
  test(`${method} refreshes the collection first page, overview and server summary counts`, async () => {
    let written = false
    const ctx = await mount(call => {
      if (call.method !== 'GET') { written = true; return reply({ ...record('a-first'), dataJson: { preserved: true } }) }
      if (written && call.url.pathname === '/api/v1/data/collections') return reply([{ ...summary('a'), recordCount: 456 }])
      if (written && call.url.pathname === '/api/v1/data/overview') return reply({ ...overview, totalRecords: 1234 })
      if (written && call.url.pathname.endsWith('/records')) return reply(page([record('after-write')], { total: 456, matchedCount: 7, nextCursor: null, hasMore: false }))
      return defaultHandler(call)
    })
    try {
      await ctx.store.load(ctx.auth.token)
      await ctx.store.loadRecords(ctx.auth.token, 'a', { q: 'work' })
      await ctx.store.loadMoreRecords(ctx.auth.token, 'a')
      const before = ctx.calls.length
      const payload = { name: 'saved', status: 'done', category: 'work', data_json: { preserved: true } }
      if (method === 'createRecord') await ctx.store.createRecord(ctx.auth.token, 'a', payload)
      else if (method === 'updateRecord') await ctx.store.updateRecord(ctx.auth.token, 'a-first', payload)
      else await ctx.store.removeRecord(ctx.auth.token, 'a-first')
      const calls = ctx.calls.slice(before)
      assert.equal(calls.length, 4)
      assert.equal(ctx.store.items[0].recordCount, 456)
      assert.equal(ctx.store.overview.totalRecords, 1234)
      assert.deepEqual(ctx.store.pages.a.items.map(item => item.id), ['after-write'])
      assert.equal(ctx.store.pages.a.matchedCount, 7)
      const request = calls.find(call => call.method === 'GET' && call.url.pathname.endsWith('/records'))
      assert.equal(request.url.searchParams.get('cursor'), '')
      assert.equal(request.url.searchParams.get('q'), 'work')
      assert.equal(calls.find(call => call.url.pathname.endsWith('/collections')).url.searchParams.get('include_records'), 'false')
    } finally { ctx.close() }
  })
}

test('editing fetches complete dataJson before opening the dialog and preserves it on save', async () => {
  let finishDetail, saved
  const ctx = await mount(call => {
    if (call.method === 'GET' && call.url.pathname === '/api/v1/data/records/a-first') return new Promise(resolve => { finishDetail = resolve })
    if (call.method === 'PATCH') { saved = JSON.parse(call.options.body); return reply({ ...record('a-first'), dataJson: saved.data_json }) }
    return defaultHandler(call)
  }, DataPage)
  try {
    const opening = ctx.state.openRecord(ctx.state.visibleRecords.value[0])
    assert.equal(ctx.state.createOpen.value, false)
    const dataJson = { nested: { values: [1, false, '中文'] } }
    finishDetail(reply({ ...record('a-first'), dataJson }))
    await opening
    assert.equal(ctx.state.createOpen.value, true)
    assert.deepEqual(JSON.parse(ctx.state.draftJson.value), dataJson)
    await ctx.state.createCollection()
    assert.deepEqual(saved.data_json, dataJson)
    assert.equal(ctx.state.createOpen.value, false)
  } finally { ctx.close() }
})

test('a failed record detail request keeps the editor closed', async () => {
  const ctx = await mount(call => call.url.pathname === '/api/v1/data/records/a-first' ? reply({ detail: '记录不存在' }, 404) : defaultHandler(call), DataPage)
  try {
    await ctx.state.openRecord(ctx.state.visibleRecords.value[0])
    assert.equal(ctx.state.createOpen.value, false)
    assert.deepEqual(ctx.messages, ['记录不存在'])
  } finally { ctx.close() }
})

test('legacy collection list remains usable and record reads default to bounded pages', async () => {
  const ctx = await mount(call => reply(call.url.searchParams.get('page') === 'true' ? page() : []))
  try {
    await dataService.list(ctx.auth.token)
    await dataService.listRecords(ctx.auth.token, 'a')
    const result = await dataService.listRecords(ctx.auth.token, 'a', { limit: 2, includeDataJson: true, q: 'a & b', cursor: 'a+b/=' })
    assert.equal(ctx.calls[0].path, '/api/v1/data/collections')
    assert.equal(ctx.calls[1].url.pathname, '/api/v1/data/collections/a/records')
    assert.equal(ctx.calls[1].url.searchParams.get('page'), 'true')
    assert.equal(ctx.calls[1].url.searchParams.get('limit'), '50')
    assert.equal(ctx.calls[1].url.searchParams.get('include_data_json'), 'false')
    assert.equal(ctx.calls[2].url.searchParams.get('cursor'), 'a+b/=')
    assert.equal(ctx.calls[2].url.searchParams.get('include_data_json'), 'true')
    assert.equal(ctx.calls[2].url.searchParams.get('limit'), '2')
    assert.equal(result.total, 80)
  } finally { ctx.close() }
})

test('new search/reset responses supersede late summary, page and overview responses', async () => {
  const pending = []
  const ctx = await mount(call => new Promise(resolve => pending.push({ call, resolve })))
  try {
    const oldList = ctx.store.load(ctx.auth.token, true, 'old')
    const oldPage = ctx.store.loadRecords(ctx.auth.token, 'a', { q: 'old' })
    const oldOverview = ctx.store.loadOverview(ctx.auth.token)
    const newList = ctx.store.load(ctx.auth.token, true, 'new')
    const newPage = ctx.store.loadRecords(ctx.auth.token, 'a', { q: 'new' })
    const newOverview = ctx.store.loadOverview(ctx.auth.token, true)
    pending[3].resolve(reply([summary('new')]))
    pending[4].resolve(reply(page([record('new')], { nextCursor: null, hasMore: false })))
    pending[5].resolve(reply(overview))
    await Promise.all([newList, newPage, newOverview])
    pending[0].resolve(reply([summary('old')]))
    pending[1].resolve(reply(page([record('old')])) )
    pending[2].resolve(reply({ ...overview, totalRecords: 1 }))
    await Promise.all([oldList, oldPage, oldOverview])
    assert.equal(ctx.store.items[0].id, 'new')
    assert.deepEqual(ctx.store.pages.a.items.map(item => item.id), ['new'])
    assert.equal(ctx.store.pages.a.q, 'new')
    assert.equal(ctx.store.overview.totalRecords, 900)
  } finally { ctx.close() }
})

for (const action of ['invalidate', 'reset']) {
  test(`${action} clears page and overview state and ignores all in-flight responses`, async () => {
    let deferred = false
    const pending = []
    const ctx = await mount(call => deferred ? new Promise(resolve => pending.push({ call, resolve })) : defaultHandler(call))
    try {
      await Promise.all([ctx.store.load(ctx.auth.token), ctx.store.loadRecords(ctx.auth.token, 'a'), ctx.store.loadOverview(ctx.auth.token)])
      deferred = true
      const requests = [ctx.store.load(ctx.auth.token, true), ctx.store.loadMoreRecords(ctx.auth.token, 'a'), ctx.store.loadOverview(ctx.auth.token, true)]
      ctx.store[action]()
      assert.deepEqual(ctx.store.pages, {})
      assert.equal(ctx.store.overview, null)
      assert.equal(ctx.store.loaded, false)
      for (const entry of pending) entry.resolve(defaultHandler(entry.call))
      await Promise.all(requests)
      assert.deepEqual(ctx.store.pages, {})
      assert.equal(ctx.store.overview, null)
      assert.equal(ctx.store.loaded, false)
      assert.equal(ctx.store.loading, false)
      assert.equal(ctx.store.overviewLoading, false)
      if (action === 'reset') assert.deepEqual(ctx.store.items, [])
    } finally { ctx.close() }
  })
}

test('record page errors remain retryable without losing already loaded records', async () => {
  let fail = true
  const ctx = await mount(call => {
    if (fail && call.url.searchParams.get('cursor')) return reply({ detail: '分页加载失败' }, 500)
    return defaultHandler(call)
  })
  try {
    await ctx.store.loadRecords(ctx.auth.token, 'a')
    await assert.rejects(ctx.store.loadMoreRecords(ctx.auth.token, 'a'), /分页加载失败/)
    assert.equal(ctx.store.pages.a.items.length, 1)
    assert.equal(ctx.store.pages.a.error, '分页加载失败')
    assert.equal(ctx.store.pages.a.loading, false)
    fail = false
    await ctx.store.loadMoreRecords(ctx.auth.token, 'a')
    assert.equal(ctx.store.pages.a.error, '')
    assert.equal(ctx.store.pages.a.items.length, 1)
  } finally { ctx.close() }
})


test('DataTable renders server totals, matched counts and a working disabled-while-loading load-more control', async () => {
  const ctx = await mount(defaultHandler)
  const element = (tag, text = '') => ({ tag, text, props: {}, children: [] })
  const renderer = createRenderer({
    createElement: tag => element(tag), createText: text => element('#text', text), createComment: () => element('#comment'),
    insert(node, parent, anchor = null) {
      if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1)
      const index = anchor ? parent.children.indexOf(anchor) : -1
      parent.children.splice(index < 0 ? parent.children.length : index, 0, node)
      node.parent = parent
    },
    remove(node) { if (node.parent) node.parent.children.splice(node.parent.children.indexOf(node), 1) },
    setText(node, text) { node.text = text }, setElementText(node, text) { node.text = text; node.children = [] },
    parentNode: node => node.parent, nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] ?? null,
    patchProp(node, key, _old, value) { node.props[key] = value },
  })
  const props = reactive({ collection: summary('a'), records: [{ ...record('r1'), statusTone: 'info' }], total: 777, matchedCount: 12, hasMore: true, loading: false, error: '' })
  let more = 0, retries = 0
  const root = element('root')
  const app = renderer.createApp({ render: () => h(DataTable, { ...props, onLoadMore: () => more++, onRetry: () => retries++ }) })
  const all = node => [node, ...node.children.flatMap(all)]
  const text = node => node.text + node.children.map(text).join('')
  const button = label => all(root).find(node => node.tag === 'button' && text(node) === label)
  try {
    app.mount(root)
    assert.match(text(root), /显示 1 \/ 777 条记录/)
    assert.match(text(root), /匹配 12 条/)
    assert.equal(button('加载更多').props.disabled, false)
    button('加载更多').props.onClick()
    assert.equal(more, 1)
    props.loading = true
    await nextTick()
    assert.equal(button('加载更多').props.disabled, true)
    assert.ok(all(root).some(node => node.props.role === 'status'))
    props.loading = false; props.error = '读取失败'
    await nextTick()
    button('重试').props.onClick()
    assert.equal(retries, 1)
    props.hasMore = false
    await nextTick()
    assert.equal(button('加载更多'), undefined)
  } finally { app.unmount(); ctx.close() }
})
