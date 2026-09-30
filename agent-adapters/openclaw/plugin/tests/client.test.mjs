import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { executeTool, resolveCredential, invocationId } from '../dist/client.js'
import catalog from '../dist/catalog.json' with { type: 'json' }
import entry from '../dist/index.js'
import { getToolPluginMetadata } from 'openclaw/plugin-sdk/tool-plugin'

process.env.NEXA_TEST_TOKEN = 'na_live_test-secret-must-not-be-logged'
const config = { serverUrl: 'http://127.0.0.1:17800', agentTokenEnv: 'NEXA_TEST_TOKEN' }
const ok = () => Response.json({ status: 'ok', replayed: false, data: { entityId: 'entity' } })

test('official SDK registers all static typed tools and safe status executes', async () => {
  const metadata = getToolPluginMetadata(entry)
  assert.equal(metadata.id, 'nexa-tools')
  assert.equal(metadata.tools.length, 30)
  const tools = []
  entry.register({ pluginConfig: config, registerTool: tool => tools.push(tool) })
  assert.equal(tools.length, 30)
  const original = globalThis.fetch
  try {
    globalThis.fetch = async (url, options) => {
      assert.ok(url.endsWith('/catalog'))
      assert.equal(options.headers.Authorization, 'Bearer ' + process.env.NEXA_TEST_TOKEN)
      return Response.json({ connected: true, agentName: 'SDK Agent', dataScopes: [], version: '0.5.5' })
    }
    const result = await tools.find(t => t.name === 'nexa_status').execute('sdk-call', {})
    assert.equal(result.details.agentName, 'SDK Agent')
    assert.ok(!JSON.stringify(result).includes('na_live_'))
  } finally { globalThis.fetch = original }
})

test('every typed tool maps to a strict static schema', () => {
  assert.equal(catalog.length, 29)
  for (const tool of catalog) {
    assert.equal(tool.parameters.additionalProperties, false)
    assert.equal(tool.parameters.type, 'object')
    assert.equal(tool.toolName, 'nexa_' + tool.action.replaceAll('.', '_'))
    assert.ok(!('userId' in tool.parameters.properties))
    assert.ok(!('actionId' in tool.parameters.properties))
  }
  const transaction = catalog.find(t => t.action === 'ledger.transaction.create')
  assert.ok(transaction.parameters.required.includes('occurredAt'))
  assert.ok(transaction.parameters.properties.categoryId)
})

test('all tools use Agent Action endpoint, writes have UUID and reads no actionId', async () => {
  for (const tool of catalog) {
    await executeTool(tool.action, tool.effect, { example: 1 }, config, tool.toolName, async (url, options) => {
      assert.equal(url, 'http://127.0.0.1:17800/api/agent/actions/execute')
      assert.equal(options.headers.Authorization, 'Bearer ' + process.env.NEXA_TEST_TOKEN)
      const body = JSON.parse(options.body)
      assert.equal(body.action, tool.action)
      assert.deepEqual(body.arguments, { example: 1 })
      if (tool.effect === 'read') assert.ok(!('actionId' in body))
      else assert.match(body.actionId, /^[0-9a-f-]{36}$/)
      return ok()
    })
  }
})

for (const failure of ['network', '5xx', 'response-lost']) {
  test(`${failure} retries preserve the entire body/actionId`, async () => {
    const bodies = []
    const result = await executeTool('ledger.transaction.create', 'write', { amount: '38.00' }, config, failure, async (_url, options) => {
      bodies.push(options.body)
      if (bodies.length === 1) {
        if (failure === '5xx') return new Response('internal secret', { status: 503 })
        throw new Error('secret path and token')
      }
      return Response.json({ status: 'ok', replayed: failure === 'response-lost' })
    })
    assert.equal(bodies.length, 2)
    assert.equal(bodies[0], bodies[1])
    if (failure === 'response-lost') assert.equal(result.replayed, true)
  })
}

for (const [status, code] of [[401, 'unauthorized'], [403, 'permission_denied'], [409, 'idempotency_conflict']]) {
  test(`${status} surfaces safe errors without retry or bypass`, async () => {
    let calls = 0
    await assert.rejects(executeTool('website.create', 'write', {}, config, undefined, async () => {
      calls++
      return Response.json({ detail: { code, token: process.env.NEXA_TEST_TOKEN, traceback: 'secret path' } }, { status })
    }), error => {
      assert.equal(error.code, code)
      assert.ok(!String(error).includes(process.env.NEXA_TEST_TOKEN))
      assert.ok(!String(error).includes('secret path'))
      return true
    })
    assert.equal(calls, 1)
  })
}

test('independent logical calls get independent IDs, re-entry uses same ID', () => {
  assert.equal(invocationId('stable'), invocationId('stable'))
  assert.notEqual(invocationId('new-a'), invocationId('new-b'))
})

test('explicit shared adapter file reuses credentials and errors never leak secrets', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'nexa-plugin-'))
  try {
    const path = join(directory, 'config.json')
    await writeFile(path, JSON.stringify({ serverUrl: 'http://localhost:17800', agentToken: process.env.NEXA_TEST_TOKEN }))
    const credential = await resolveCredential({ adapterConfigPath: path })
    assert.equal(credential.agentToken, process.env.NEXA_TEST_TOKEN)
    await writeFile(path, 'bad-secret-file')
    await assert.rejects(resolveCredential({ adapterConfigPath: path }), e => e.code === 'configuration_error' && !String(e).includes(path))
  } finally { await rm(directory, { recursive: true, force: true }) }
})

test('status returns only catalog and rejects insecure remote/embedded credentials', async () => {
  const status = await executeTool('status', 'read', {}, config, undefined, async (url, options) => {
    assert.ok(url.endsWith('/catalog'))
    assert.equal(options.method, 'GET')
    return Response.json({ connected: true, agentName: 'Agent', dataScopes: [], version: '0.5.5' })
  })
  assert.ok(!JSON.stringify(status).includes('na_live_'))
  for (const serverUrl of ['http://remote.example', 'https://user:password@example.com', 'https://example.com?token=secret']) {
    await assert.rejects(resolveCredential({ ...config, serverUrl }), e => e.code === 'configuration_error')
  }
})

test('unknown server errors and terminal network failures never print credentials', async () => {
  let calls = 0
  await assert.rejects(executeTool('website.create', 'write', {}, config, 'failure', async () => {
    calls++
    throw new Error(process.env.NEXA_TEST_TOKEN)
  }), e => e.code === 'unavailable' && !String(e).includes(process.env.NEXA_TEST_TOKEN))
  assert.equal(calls, 3)
})
