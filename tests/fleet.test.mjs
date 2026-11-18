import test from 'node:test'
import assert from 'node:assert/strict'

import {
  NONCE_BYTES,
  decodeBase64Url,
  decryptChunk,
  downloadAndDecryptBlob,
  encodeBase64Url,
  encryptAndUploadFile,
  encryptChunk,
  generateFileKey,
  sha256Hex,
} from '../src/services/blobTransfer.ts'
import { buildFleetWsUrl } from '../src/services/fleetUrl.ts'
import {
  applyTokenUsageEvent,
  estimateTurnUsageFallback,
  formatTokenCount,
  hasRecordedTurnUsage,
  toSessionTokenSummary,
} from '../src/services/tokenUsage.ts'
import { isSafeMarkdownHref, parseMarkdownBlocks, parseMarkdownInlines } from '../src/services/markdownBlocks.ts'

test('AES-256-GCM 分块加解密、Base64URL 编解码与防篡改校验', async () => {
  const key = generateFileKey()
  assert.equal(key.byteLength, 32)
  const keyB64 = encodeBase64Url(key)
  assert.deepEqual(decodeBase64Url(keyB64), key)

  const plaintext = new TextEncoder().encode('Studiolo 跨设备文件总线 · 测试正文 #01')
  const aadContext = 'blob-aad-context-1'
  const cipher = await encryptChunk(key, aadContext, 0, plaintext)
  assert.equal(cipher.byteLength, NONCE_BYTES + plaintext.byteLength + 16)

  const decrypted = await decryptChunk(key, aadContext, 0, cipher)
  assert.deepEqual(decrypted, plaintext)

  // 篡改密文或分块序号 AAD 必须抛出解密校验异常
  const tampered = cipher.slice()
  tampered[tampered.byteLength - 1] ^= 0xff
  await assert.rejects(() => decryptChunk(key, aadContext, 0, tampered))
  await assert.rejects(() => decryptChunk(key, aadContext, 1, cipher))
})

test('WebSocket URL 构造绝不携带 token 查询参数', () => {
  assert.equal(buildFleetWsUrl('https://studiolo.example.com/', ''), 'wss://studiolo.example.com/ws/fleet/client')
  assert.equal(buildFleetWsUrl('http://127.0.0.1:48197', ''), 'ws://127.0.0.1:48197/ws/fleet/client')
  assert.equal(buildFleetWsUrl('', 'https://app.studiolo.org'), 'wss://app.studiolo.org/ws/fleet/client')
  assert.equal(buildFleetWsUrl('https://core.local').includes('token='), false)
})

test('浏览器端加密上传 + LAN 不可达自动降级 Core 下载解密端到端闭环', async () => {
  const originalFetch = globalThis.fetch
  const storedChunks = new Map()
  let initPayloadSeen = null

  globalThis.fetch = async (url, options = {}) => {
    const u = String(url)
    if (u.endsWith('/api/v1/fleet/artifacts/init')) {
      initPayloadSeen = JSON.parse(options.body)
      return new Response(
        JSON.stringify({
          blob: {
            id: 'blob-demo-1',
            workspaceId: 'ws-1',
            uploaderKind: 'user',
            uploaderId: '1',
            purpose: 'fleet_artifact',
            digest: initPayloadSeen.digest,
            ciphertextSize: initPayloadSeen.ciphertextSize,
            chunkSize: initPayloadSeen.chunkSize,
            chunkCount: initPayloadSeen.chunkCount,
            storageRole: 'core',
            storageLocation: '',
            manifest: initPayloadSeen.manifest,
            committedAt: null,
            expiresAt: null,
            createdAt: new Date().toISOString(),
          },
          endpoints: [
            { kind: 'core', url: '/api/v1/fleet/artifacts/blob-demo-1', priority: 90, label: 'Core' },
          ],
        }),
        { status: 201, headers: { 'Content-Type': 'application/json' } },
      )
    }
    if (u.includes('/chunks/') && options.method === 'PUT') {
      const idx = Number(u.split('/chunks/')[1])
      const bytes = new Uint8Array(options.body)
      const digest = await sha256Hex(bytes)
      assert.equal(digest, options.headers['X-Chunk-Sha256'])
      storedChunks.set(idx, bytes)
      return new Response(JSON.stringify({ ok: true }), { status: 200 })
    }
    if (u.endsWith('/commit')) {
      return new Response(JSON.stringify({ id: 'blob-demo-1' }), { status: 200 })
    }
    if (u.endsWith('/endpoints')) {
      return new Response(
        JSON.stringify({
          blob: {
            id: 'blob-demo-1',
            chunkCount: storedChunks.size,
          },
          endpoints: [
            { kind: 'lan', url: 'http://192.168.199.99:49100/artifacts/blob-demo-1', priority: 10, label: 'LAN' },
            { kind: 'core', url: '/api/v1/fleet/artifacts/blob-demo-1', priority: 90, label: 'Core' },
          ],
        }),
        { status: 200 },
      )
    }
    if (u.startsWith('http://192.168.199.99')) {
      throw new Error('ECONNREFUSED simulated LAN unreachable')
    }
    if (u.includes('/api/v1/fleet/artifacts/blob-demo-1/chunks/')) {
      const idx = Number(u.split('/chunks/')[1])
      return new Response(storedChunks.get(idx), { status: 200 })
    }
    throw new Error(`Unexpected fetch: ${u}`)
  }

  try {
    const raw = new Uint8Array(9000)
    for (let i = 0; i < raw.length; i += 1) raw[i] = i % 251
    const file = new File([raw], 'report.tar.gz', { type: 'application/gzip' })

    const ref = await encryptAndUploadFile({
      file,
      token: 'jwt-test',
      apiBaseUrl: 'http://127.0.0.1:48197',
      chunkSize: 4096,
    })

    assert.equal(ref.chunkCount, 3)
    assert.ok(ref.keyB64)
    // 核实提交给后端初始化接口的 JSON 绝不包含密钥明文
    assert.equal(JSON.stringify(initPayloadSeen).includes(ref.keyB64), false)

    const result = await downloadAndDecryptBlob({
      artifact: ref,
      token: 'jwt-test',
      apiBaseUrl: 'http://127.0.0.1:48197',
    })
    assert.equal(result.transport, 'core')
    assert.equal(result.fileName, 'report.tar.gz')
    const outBytes = new Uint8Array(await result.blob.arrayBuffer())
    assert.deepEqual(outBytes, raw)
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('Token 用量累加支持按轮次幂等更新、累计快照防重以及无遥测回退估算', () => {
  // 1. 按 messageId / turn 幂等更新（OpenCode SSE 多次推送同一消息不重复累加）
  let turnState = applyTokenUsageEvent(undefined, {
    runId: 'run-1',
    messageId: 'msg-1',
    scope: 'turn',
    inputTokens: 500,
    cachedInputTokens: 200,
    outputTokens: 60,
    reasoningTokens: 10,
    totalTokens: 560,
    source: 'exact',
  })
  turnState = applyTokenUsageEvent(turnState, {
    runId: 'run-1',
    messageId: 'msg-1',
    scope: 'turn',
    inputTokens: 500,
    cachedInputTokens: 200,
    outputTokens: 120,
    reasoningTokens: 25,
    totalTokens: 620,
    source: 'exact',
  })
  turnState = applyTokenUsageEvent(turnState, {
    runId: 'run-2',
    messageId: 'msg-2',
    scope: 'turn',
    inputTokens: 640,
    cachedInputTokens: 450,
    outputTokens: 180,
    totalTokens: 820,
    contextWindow: 128000,
    source: 'exact',
  })
  const turnSummary = toSessionTokenSummary(turnState)
  assert.ok(turnSummary)
  assert.equal(turnSummary.turns, 2)
  assert.equal(turnSummary.totalTokens, 1440)
  assert.equal(turnSummary.totalCachedTokens, 650)
  assert.equal(turnSummary.lastTurnTokens, 820)
  assert.equal(turnSummary.contextWindow, 128000)
  assert.equal(turnSummary.source, 'exact')

  // 2. Codex cumulative 快照：同一会话多次更新不叠加，仅按最近一轮算上下文占用，并防止 Completed 重复回退
  let codexState = applyTokenUsageEvent(undefined, {
    runId: 'turn-1',
    scope: 'cumulative',
    inputTokens: 900,
    cachedInputTokens: 300,
    outputTokens: 200,
    totalTokens: 1100,
    lastInputTokens: 900,
    lastOutputTokens: 200,
    lastTotalTokens: 1100,
    contextWindow: 200000,
    source: 'exact',
  })
  codexState = applyTokenUsageEvent(codexState, {
    runId: 'turn-2',
    scope: 'cumulative',
    inputTokens: 2100,
    cachedInputTokens: 1200,
    outputTokens: 420,
    totalTokens: 2520,
    lastInputTokens: 1200,
    lastOutputTokens: 220,
    lastTotalTokens: 1420,
    contextWindow: 200000,
    source: 'exact',
  })
  assert.equal(hasRecordedTurnUsage(codexState, ['turn-2']), true)
  const codexSummary = toSessionTokenSummary(codexState)
  assert.ok(codexSummary)
  assert.equal(codexSummary.turns, 2)
  assert.equal(codexSummary.totalTokens, 2520)
  assert.equal(codexSummary.lastTurnTokens, 1420)

  // 3. 回退估算与紧凑格式化
  const est = estimateTurnUsageFallback('请检查项目状态', '先扫描 git', '当前工作区干净。', { runId: 'run-est' })
  const estState = applyTokenUsageEvent(undefined, est)
  const estSummary = toSessionTokenSummary(estState)
  assert.ok(estSummary && estSummary.totalTokens > 0)
  assert.equal(estSummary.source, 'estimated')
  assert.equal(formatTokenCount(850), '850')
  assert.equal(formatTokenCount(1420), '1.4k')
  assert.equal(formatTokenCount(128000), '128k')
  assert.equal(formatTokenCount(1_250_000), '1.3M')
})

test('Markdown 块级与行内 AST 解析支持代码围栏、表格及危险协议过滤', () => {
  assert.equal(isSafeMarkdownHref('https://studiolo.local/docs'), 'https://studiolo.local/docs')
  assert.equal(isSafeMarkdownHref('mailto:dev@studiolo.local'), 'mailto:dev@studiolo.local')
  assert.equal(isSafeMarkdownHref('javascript:alert(1)'), null)
  assert.equal(isSafeMarkdownHref('data:text/html,<script>1</script>'), null)

  const inlines = parseMarkdownInlines('点击 [恶意](javascript:alert(1)) 与 [官网](https://example.com) 及 `npm run build`')
  assert.equal(inlines.some(t => t.type === 'link' && t.href.startsWith('javascript:')), false)
  assert.equal(inlines.some(t => t.type === 'link' && t.href === 'https://example.com/' && t.text === '官网'), true)
  assert.equal(inlines.some(t => t.type === 'code' && t.text === 'npm run build'), true)

  const md = [
    '## 状态总结',
    '',
    '> 仅驻留内存',
    '',
    '| 指标 | 值 |',
    '| --- | --- |',
    '| 用例 | **100%** |',
    '',
    '```ts',
    'const ok = true',
  ].join('\n')

  const blocks = parseMarkdownBlocks(md)
  assert.equal(blocks[0].type, 'heading')
  assert.equal(blocks[1].type, 'blockquote')
  assert.equal(blocks[2].type, 'table')
  if (blocks[2].type === 'table') {
    assert.equal(blocks[2].headers.length, 2)
    assert.equal(blocks[2].rows[0][1][0].type, 'bold')
  }
  assert.equal(blocks[3].type, 'code')
  if (blocks[3].type === 'code') {
    assert.equal(blocks[3].lang, 'ts')
    assert.equal(blocks[3].streamingOpen, true)
    assert.equal(blocks[3].code, 'const ok = true')
  }
})
