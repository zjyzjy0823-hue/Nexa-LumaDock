import test from 'node:test'
import assert from 'node:assert/strict'
import { parseRecordJson } from '../src/utils/recordJson.ts'

test('record content preserves nested data and the requested QA metadata', () => {
  const value = { qaOrigin: 'mac-offline', qaRun: 'NEXA-QA-FINAL-20261004', nested: { values: [false, 2, null, '中文'] } }
  assert.deepEqual(parseRecordJson(JSON.stringify(value)), value)
})

test('blank record content retains the existing empty object default', () => {
  assert.deepEqual(parseRecordJson('  '), {})
})

test('malformed content and non-object JSON are rejected before saving', () => {
  for (const value of ['{', '{"a":}', '[1]', 'null', '42', 'true', '"text"']) {
    assert.throws(() => parseRecordJson(value), /JSON/)
  }
})
