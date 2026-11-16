import test from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { spawnSync } from 'node:child_process'
import { mkdtempSync, readFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { parse, compileScript } from '@vue/compiler-sfc'

// The API sends UTC; the ledger UI groups by the viewer's calendar. These cases
// pin one instant and check what each zone must see.
const dir = mkdtempSync(path.join(tmpdir(), 'nexa-localtime-'))
const bundle = path.join(dir, 'localTime.mjs')
await build({
  entryPoints: ['src/services/localTime.ts'],
  bundle: true,
  format: 'esm',
  outfile: bundle,
  logLevel: 'silent',
})

// Run the real page's setup/save functions with its real Pinia stores. Only the
// store's final write is replaced, so this checks both create and edit payloads.
const saveBundle = path.join(dir, 'ledgerSave.mjs')
await build({
  stdin: { contents: `
    import LedgerPage from './src/pages/LedgerPage.vue'
    import { useLedgerStore } from './src/stores/ledger.ts'
    import { useAuthStore } from './src/stores/auth.ts'
    import { createPinia } from 'pinia'
    import { createRenderer } from 'vue'
    export async function save(date, editing) {
      globalThis.localStorage = { getItem: () => null, removeItem() {} }
      const pinia = createPinia()
      const store = useLedgerStore(pinia), auth = useAuthStore(pinia)
      let state, payload
      const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode() {}, nextSibling() {} })
      const app = renderer.createApp({ setup() {
        state = LedgerPage.setup({}, { expose() {}, emit() {} })
        return () => null
      } })
      app.use(pinia).mount({})
      auth.token = 'FAKE_ONLY'
      store.createTransaction = async (_token, data) => { payload = data }
      store.updateTransaction = async (_token, _id, data) => { payload = data }
      state.draft.value.occurred_at = date
      state.editingTransaction.value = editing ? { id: 'transaction' } : null
      await state.saveTransaction()
      app.unmount()
      return payload
    }
  `, resolveDir: process.cwd(), loader: 'ts' },
  bundle: true, format: 'esm', platform: 'node', outfile: saveBundle,
  define: { 'import.meta.env.VITE_API_BASE_URL': '""' }, logLevel: 'silent',
  plugins: [{ name: 'vue-script', setup(builder) {
    builder.onLoad({ filter: /\.vue$/ }, ({ path: filename }) => {
      const { descriptor } = parse(readFileSync(filename, 'utf8'), { filename })
      return { contents: compileScript(descriptor, { id: filename }).content, loader: 'ts' }
    })
  } }],
})

for (const tz of ['Asia/Shanghai', 'America/Los_Angeles', 'Pacific/Auckland']) {
  for (const editing of [false, true]) {
    test(`ledger ${editing ? 'edit' : 'create'} payload preserves selected local noon in ${tz}`, () => {
      const script = `import { save } from ${JSON.stringify(saveBundle)};
        const dates = ['2026-11-01', '2026-03-01', '2026-03-08'];
        const results = [];
        for (const date of dates) {
          const payload = await save(date, ${editing});
          const instant = new Date(payload.occurred_at);
          results.push({ selected: date, payload, date: [instant.getFullYear(), String(instant.getMonth() + 1).padStart(2, '0'), String(instant.getDate()).padStart(2, '0')].join('-'), hour: instant.getHours() });
        }
        process.stdout.write(JSON.stringify(results))`
      const result = spawnSync(process.execPath, ['--input-type=module', '-e', script], {
        env: { ...process.env, TZ: tz }, encoding: 'utf8',
      })
      assert.equal(result.status, 0, result.stderr)
      for (const entry of JSON.parse(result.stdout)) {
        assert.match(entry.payload.occurred_at, /(?:Z|[+-]\d{2}:\d{2})$/)
        assert.equal(entry.date, entry.selected)
        assert.equal(entry.hour, 12)
      }
    })
  }
}

const CASES = [
  {
    tz: 'Asia/Shanghai',
    iso: '2026-10-31T16:30:00+00:00', // 2026-11-01 00:30 本地
    expected: { date: '2026-11-01', month: '2026-11', day: '01' },
  },
  {
    tz: 'Pacific/Auckland',
    iso: '2026-10-31T23:00:00+00:00', // 2026-11-01 12:00 NZDT
    expected: { date: '2026-11-01', month: '2026-11', day: '01' },
  },
  {
    tz: 'America/New_York',
    iso: '2026-10-31T23:00:00+00:00', // 2026-10-31 19:00 EDT
    expected: { date: '2026-10-31', month: '2026-10', day: '31' },
  },
]

function keysIn(zone, iso) {
  const script = `import { localDateKey, localMonthKey, localDayKey } from ${JSON.stringify(bundle)};
process.stdout.write(JSON.stringify({ date: localDateKey(${JSON.stringify(iso)}), month: localMonthKey(${JSON.stringify(iso)}), day: localDayKey(${JSON.stringify(iso)}) }))`
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', script], {
    env: { ...process.env, TZ: zone },
    encoding: 'utf8',
  })
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout)
}

for (const { tz, iso, expected } of CASES) {
  test(`calendar keys follow ${tz}`, () => {
    assert.deepEqual(keysIn(tz, iso), expected)
  })
}

test('slicing the raw UTC string would have been wrong', () => {
  const utcSlice = '2026-10-31T16:30:00+00:00'.slice(0, 7)
  assert.equal(utcSlice, '2026-10')
  assert.equal(keysIn('Asia/Shanghai', '2026-10-31T16:30:00+00:00').month, '2026-11')
})

test('unparseable input falls back to the text slice', () => {
  const script = `import { localMonthKey } from ${JSON.stringify(bundle)};
process.stdout.write(localMonthKey('not-a-date'))`
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', script], { encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.stdout, 'not-a-d')
})
