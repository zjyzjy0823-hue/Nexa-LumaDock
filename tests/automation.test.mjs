import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { build } from 'esbuild'
import { parse, compileScript } from '@vue/compiler-sfc'

const bundle = await build({ stdin: { contents: `export {useAutomationStore} from './src/stores/automation.ts'; export {useAuthStore} from './src/stores/auth.ts'; export {default as AutomationPage} from './src/pages/AutomationPage.vue'; export {createRenderer} from 'vue'; export {createPinia,setActivePinia} from 'pinia';`, resolveDir: process.cwd(), loader: 'ts' }, bundle: true, write: false, format: 'esm', platform: 'node', define: { 'import.meta.env.VITE_API_BASE_URL': '""' }, plugins: [{ name: 'vue', setup(build) {
  build.onLoad({ filter: /\.vue$/ }, async ({ path }) => {
    const { descriptor } = parse(await readFile(path, 'utf8'), { filename: path })
    return { contents: compileScript(descriptor, { id: path, inlineTemplate: true }).content, loader: 'ts' }
  })
} }] })
const { useAutomationStore, useAuthStore, AutomationPage, createRenderer, createPinia, setActivePinia } = await import('data:text/javascript;base64,' + Buffer.from(bundle.outputFiles[0].text).toString('base64'))
const definition = { id: 'automation-a', name: 'Real automation', workflowJson: [], triggerConfigJson: {}, enabled: true }
const runtime = { available: true, authority: 'core', nextRunAt: null, lastRunAt: null, lastResult: null }
const execution = { id: 'execution-a', workflowId: definition.id, status: 'queued', createdAt: '2030-01-01T00:00:00Z' }
const response = (value, status=200) => new Response(JSON.stringify(value), { status })
function store() { setActivePinia(createPinia()); return useAutomationStore() }

async function settle() { for (let i = 0; i < 10; i++) await new Promise(resolve => setImmediate(resolve)) }
function nodes(root) { return [root, ...(root.children ?? []).flatMap(nodes)] }
function text(root) { return (root.text ?? '') + (root.children ?? []).map(text).join('') }
async function mountPage(t, fetch) {
  const previous = Object.fromEntries(['fetch', 'localStorage', 'document', 'setInterval', 'clearInterval'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]))
  const polls = new Map(), body = { children: [] }
  Object.assign(globalThis, { fetch, localStorage: { getItem: () => null, removeItem() {} }, document: { addEventListener() {}, removeEventListener() {} },
    setInterval(callback) { const id = polls.size + 1; polls.set(id, callback); return id }, clearInterval(id) { polls.delete(id) } })
  function remove(node) { if (node.parent) { const siblings = node.parent.children; siblings.splice(siblings.indexOf(node), 1); node.parent = null } }
  const renderer = createRenderer({
    createElement: type => ({ type, children: [], props: {} }), createText: text => ({ text }), createComment: () => ({}),
    insert(node, parent, anchor) { remove(node); node.parent = parent; parent.children.splice(anchor ? parent.children.indexOf(anchor) : parent.children.length, 0, node) },
    remove, setText(node, value) { node.text = value }, setElementText(node, value) { node.text = value; node.children = [] },
    parentNode: node => node.parent, nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1],
    patchProp(node, key, _old, value) { node.props[key] = value },
    querySelector: () => body,
  })
  const pinia = createPinia(), automation = useAutomationStore(pinia), auth = useAuthStore(pinia)
  auth.token = 'FAKE_ONLY'
  const messages = [], root = { children: [] }, app = renderer.createApp(AutomationPage, { onAction: message => messages.push(message) })
  app.use(pinia)
  t.after(() => { app.unmount(); for (const [key, descriptor] of Object.entries(previous)) { if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key] } })
  app.mount(root); await settle()
  return { automation, root, messages, polls, async click(label, index = 0) {
    const button = nodes(root).filter(node => node.type === 'button' && text(node) === label)[index]
    assert.ok(button, `Button ${label} exists`); assert.ok(!button.props.disabled)
    await button.props.onClick(); await settle()
  } }
}

test('Core unavailable keeps definitions editable and clears runtime authority', async () => {
  globalThis.fetch = async (path, options) => path.endsWith('/automations') ? response([definition]) : options.method === 'PATCH' ? response({ ...definition, name: 'Offline edit' }) : response({ detail: 'Core unavailable' }, 503)
  const automation = store(); await automation.load('FAKE_ONLY', true)
  assert.equal(automation.loaded, true); assert.equal(automation.items.length, 1)
  assert.match(automation.runtimeError, /Core/); assert.deepEqual(automation.runtimes, {})
  await automation.update('FAKE_ONLY', definition.id, { name: 'Offline edit' })
  assert.equal(automation.items[0].name, 'Offline edit')
})

test('double click is blocked and request identity survives response loss', async () => {
  const automation = store(), keys=[]
  let release
  globalThis.fetch = async (path, options) => {
    keys.push(JSON.parse(options.body).request_id)
    await new Promise(resolve => { release = resolve })
    return keys.length === 1 ? response({ detail: 'Core unavailable' }, 503) : response(execution, 201)
  }
  const first = automation.run('FAKE_ONLY', definition.id)
  await assert.rejects(automation.run('FAKE_ONLY', definition.id), /操作正在进行/)
  release(); await assert.rejects(first, /Core/)
  const retry = automation.run('FAKE_ONLY', definition.id); release(); await retry
  assert.equal(keys.length, 2); assert.equal(keys[0], keys[1]); assert.equal(automation.executions.length, 1)
})

test('Core recovery restores live runtime and execution history', async () => {
  globalThis.fetch = async path => path.endsWith('/automations') ? response([definition]) : path.endsWith('/runtime') ? response(runtime) : response([execution])
  const automation = store(); await automation.load('FAKE_ONLY', true)
  assert.equal(automation.runtimeError, ''); assert.equal(automation.runtimes[definition.id].authority, 'core')
  assert.equal(automation.executions[0].id, execution.id)
  globalThis.fetch = async () => response({ detail: 'unavailable' }, 503)
  await automation.refreshRuntime('FAKE_ONLY')
  assert.deepEqual(automation.runtimes, {}); assert.equal(automation.items.length, 1)
})

test('session reset fences an outstanding history response', async () => {
  let release
  globalThis.fetch = async path => path.endsWith('/automations') ? response([definition]) : path.endsWith('/runtime') ? response(runtime) : (await new Promise(resolve => { release=resolve }), response([execution]))
  const automation = store(), pending = automation.load('FAKE_ONLY', true)
  while (!release) await new Promise(resolve => setTimeout(resolve, 1))
  automation.reset(); release(); await pending
  assert.deepEqual(automation.items, []); assert.deepEqual(automation.executions, []); assert.deepEqual(automation.runtimes, {})
})

test('simulation on an unselected automation is labelled and stays visible after polling', async t => {
  const second = { ...definition, id: 'automation-b', name: 'Simulation target' }
  const simulation = { ...execution, id: 'simulation-a', workflowId: second.id, triggerType: 'simulation', status: 'success', resultJson: { simulated: true }, attempt: 0 }
  const paths = []
  const ctx = await mountPage(t, async path => {
    paths.push(path)
    if (path.endsWith('/automations')) return response([definition, second])
    if (path.endsWith('/test-run')) return response(simulation, 201)
    if (path.endsWith('/runtime')) return response(runtime)
    assert.ok(path.endsWith('/executions?runtime=true'))
    return response(path.includes(second.id) ? [] : [execution])
  })
  await ctx.click('模拟测试', 1)
  function assertVisible() {
    assert.ok(nodes(ctx.root).some(node => node.type === 'h2' && text(node) === '执行记录 · Simulation target'))
    const row = nodes(ctx.root).find(node => node.type === 'tr' && text(node).includes('模拟成功'))
    assert.ok(row); assert.ok(nodes(row).some(node => node.type === 'small' && text(node) === '模拟'))
    assert.match(text(row), /未执行任何真实动作/)
  }
  assertVisible(); assert.match(ctx.messages.at(-1), /模拟测试完成/)
  ctx.polls.values().next().value(); await settle()
  assertVisible()
  assert.equal(paths.filter(path => path.endsWith('/test-run')).length, 1)
  assert.ok(ctx.automation.executions.some(item => item.id === execution.id))
  assert.equal(ctx.automation.executions.filter(item => item.id === simulation.id).length, 1)
})

test('run 422 errors reach both the action notification and inline alert in Chinese', async t => {
  const invalid = { ...definition, workflowJson: [{ kind: 'DO', action: { type: 'data.create', config: {} } }] }
  let failure = { detail: 'Definition is not executable' }
  const ctx = await mountPage(t, async path => path.endsWith('/automations') ? response([invalid]) : path.endsWith('/runtime') ? response(runtime) : path.endsWith('/run') ? response(failure, 422) : response([]))
  for (const body of [{ detail: 'Definition is not executable' }, { error: { code: 'request_error', message: 'Definition is not executable' } }, { detail: 'definition_not_executable' }]) {
    failure = body
    await ctx.click('立即运行')
    assert.equal(ctx.messages.at(-1), '此自动化暂时无法运行，请检查并完善执行动作配置后重试。')
    assert.equal(ctx.automation.error, ctx.messages.at(-1))
    assert.ok(nodes(ctx.root).some(node => node.props?.role === 'alert' && text(node).includes(ctx.messages.at(-1))))
    assert.equal(ctx.automation.loading, false); assert.deepEqual(ctx.automation.executions, [])
  }
})

test('simulation survives an in-flight refresh, is deduplicated, and clears on reset', async () => {
  const automation = store(), simulation = { ...execution, id: 'simulation-a', triggerType: 'simulation', status: 'success' }
  automation.items = [definition]
  let release
  globalThis.fetch = async path => path.endsWith('/test-run') ? response(simulation, 201) : path.endsWith('/runtime') ? response(runtime) : (await new Promise(resolve => { release = resolve }), response([execution]))
  const pending = automation.refreshRuntime('FAKE_ONLY')
  await automation.testRun('FAKE_ONLY', definition.id)
  release(); await pending
  assert.equal(automation.executions.filter(item => item.id === simulation.id).length, 1)
  globalThis.fetch = async path => response(path.endsWith('/runtime') ? runtime : [execution, simulation])
  await automation.refreshRuntime('FAKE_ONLY')
  assert.equal(automation.executions.filter(item => item.id === simulation.id).length, 1)
  globalThis.fetch = async () => response({ detail: 'Core unavailable' }, 503)
  await automation.refreshRuntime('FAKE_ONLY')
  assert.equal(automation.executions.filter(item => item.id === simulation.id).length, 1)
  assert.match(automation.runtimeError, /Core/); assert.deepEqual(automation.runtimes, {})
  automation.reset(); assert.deepEqual(automation.executions, [])
})
