import test from 'node:test'
import assert from 'node:assert/strict'

import { jobRefKey, sanitizeNotificationText } from '../src/services/schedulerHelpers.ts'

test('JobRef 复合键按 ownerType / ownerInstanceId / ownerProfile / nativeJobId 严格隔离防碰撞', () => {
  const k1 = jobRefKey({
    ownerType: 'hermes',
    ownerInstanceId: 'node-1',
    ownerProfile: 'default',
    nativeJobId: 'daily-1',
  })
  const k2 = jobRefKey({
    ownerType: 'hermes',
    ownerInstanceId: 'node-1',
    ownerProfile: 'research',
    nativeJobId: 'daily-1',
  })
  const k3 = jobRefKey({
    ownerType: 'openclaw',
    ownerInstanceId: 'node-1',
    ownerProfile: 'default',
    nativeJobId: 'daily-1',
  })
  assert.notEqual(k1, k2)
  assert.notEqual(k1, k3)
  assert.notEqual(k2, k3)
})

test('通知脱敏器拦截 Studiolo Token、API Key 与 Bearer 凭据', () => {
  const cleaned = sanitizeNotificationText(
    '触发失败：sv_live_secret12345678 / ss_live_normal12345678 / sk-abc1234567890123 / Bearer my-secret-jwt-token',
  )
  assert.ok(!cleaned.includes('sv_live_'))
  assert.ok(!cleaned.includes('ss_live_'))
  assert.ok(!cleaned.includes('sk-abc'))
  assert.ok(!cleaned.includes('my-secret-jwt-token'))
  assert.ok(cleaned.includes('[REDACTED_TOKEN]'))
  assert.ok(cleaned.includes('[REDACTED_API_KEY]'))
})
