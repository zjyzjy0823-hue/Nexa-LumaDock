import test from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'

const bundle = await build({ entryPoints: ['src/services/diagnostics.ts'], bundle: true, write: false, platform: 'node', format: 'esm',
  define: { 'import.meta.env.VITE_API_BASE_URL': '""' } })
const { getDiagnostics, diagnosticsRows, diagnosticsText } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString('base64')}`)
const value = { appVersion: '0.6.1', mode: 'local', backend: 'healthy', database: { kind: 'sqlite', status: 'ok' }, workspaceId: 'workspace',
  core: { status: 'disconnected', url: null, workspaceId: null, clientId: null, tokenConfigured: false },
  sync: { pending: 2, rejected: 1, conflicts: 3, inFlight: 4, lastSuccessAt: null, lastError: null },
  protocol: { local: 3, core: null, compatible: null }, automation: { local: { scheduler: false, worker: false }, core: { scheduler: null, worker: null } } }

test('disconnected, counts and unknown protocol/runtime are visible', () => {
  const text = diagnosticsText(value)
  assert.match(text, /未连接/)
  assert.match(text, /Pending: 2 · Rejected: 1 · Conflicts: 3 · In Flight: 4/)
  assert.match(text, /Core: 未知 · 尚未验证/)
  assert.match(text, /Local Scheduler: OFF/)
  assert.match(text, /Core Worker: 未知/)
})

test('healthy and incompatible protocol are distinguished', () => {
  const healthy = structuredClone(value)
  healthy.core.status = 'connected'
  healthy.protocol = { local: 3, core: 3, compatible: true }
  healthy.automation.core = { scheduler: true, worker: true }
  assert.match(diagnosticsText(healthy), /已连接/)
  assert.match(diagnosticsText(healthy), /Core Worker: ON/)
  healthy.protocol = { local: 3, core: 4, compatible: false }
  assert.match(diagnosticsText(healthy), /不兼容/)
})

test('copy ignores unsolicited credential fields at every level', () => {
  const malicious = structuredClone(value)
  malicious.authorization = 'secret-authorization'
  malicious.core.clientToken = 'secret-token'
  malicious.sync.requestBody = { password: 'secret-password' }
  malicious.automation.core.cookie = 'secret-cookie'
  assert.doesNotMatch(diagnosticsText(malicious), /secret-|clientToken|authorization|password|cookie/)
  assert.equal(diagnosticsRows(malicious).length, 13)
})

test('diagnostics uses the existing authenticated local API path', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async (url, options) => {
    assert.equal(url, '/api/v1/settings/diagnostics')
    assert.equal(options.headers.Authorization, 'Bearer local-test-token')
    return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  try { assert.deepEqual(await getDiagnostics('local-test-token'), value) }
  finally { globalThis.fetch = original }
})
