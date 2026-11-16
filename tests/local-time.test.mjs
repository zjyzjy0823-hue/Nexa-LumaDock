import test from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { spawnSync } from 'node:child_process'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

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
