import test from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'

const bundle = await build({ stdin: { contents: `export {useAutomationStore} from './src/stores/automation.ts'; export {automationService} from './src/services/automation.ts'; export {createPinia,setActivePinia} from 'pinia';`, resolveDir: process.cwd(), loader: 'ts' }, bundle: true, write: false, format: 'esm', platform: 'node', define: { 'import.meta.env.VITE_API_BASE_URL': '""' } })
const { useAutomationStore, createPinia, setActivePinia } = await import('data:text/javascript;base64,' + Buffer.from(bundle.outputFiles[0].text).toString('base64'))
const definition = { id: 'automation-a', name: 'Real automation', workflowJson: [], triggerConfigJson: {}, enabled: true }
const runtime = { available: true, authority: 'core', nextRunAt: null, lastRunAt: null, lastResult: null }
const execution = { id: 'execution-a', workflowId: definition.id, status: 'queued', createdAt: '2030-01-01T00:00:00Z' }
const response = (value, status=200) => new Response(JSON.stringify(value), { status })
function store() { setActivePinia(createPinia()); return useAutomationStore() }

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
