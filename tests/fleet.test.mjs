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
import { highlightCode, inferLanguageFromPath } from '../src/services/syntaxHighlight.ts'
import { hasAnsiSequences, parseAnsiText } from '../src/services/ansiParser.ts'
import { parseMermaidDiagram } from '../src/services/diagramBuilder.ts'
import {
  computeHunkGaps,
  extractToolMiniDiff,
  parseDiffHunks,
  splitDiffPath,
  toSplitDiffRows,
} from '../src/services/diffHelpers.ts'
import { deleteCustomPrompt, loadCustomPrompts, saveCustomPrompt } from '../src/services/customPrompts.ts'
import { buildSessionHtmlReport } from '../src/services/htmlExport.ts'
import { resolveSavedModelPref, saveAgentModelPref } from '../src/services/modelPrefs.ts'
import {
  appendMessagePart,
  branchFromUserMessage,
  buildSessionMarkdown,
  extractMessageParts,
  mergeToolCallUpdate,
  searchSessionsAndMessages,
  switchMessageBranch,
} from '../src/services/chatHelpers.ts'

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
  assert.equal(hasRecordedTurnUsage(turnState, ['run-1']), true)
  assert.equal(hasRecordedTurnUsage(turnState, ['run-2']), true)

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

test('工具调用增量合并、对话编辑分叉切换、跨消息搜索与 Markdown 导出', () => {
  // 1. ToolCallUpdate 按 callId 原地合并增量输出与完成时长
  let tools = mergeToolCallUpdate(undefined, {
    callId: 'tc-1',
    name: 'shell',
    title: 'pytest -q',
    status: 'running',
    input: { command: 'pytest -q' },
  })
  assert.equal(tools.length, 1)
  assert.equal(tools[0].status, 'running')

  tools = mergeToolCallUpdate(tools, {
    callId: 'tc-1',
    name: 'shell',
    status: 'running',
    deltaOutput: 'line 1\n',
  })
  tools = mergeToolCallUpdate(tools, {
    callId: 'tc-1',
    name: 'shell',
    status: 'completed',
    deltaOutput: 'line 2\n',
    durationMs: 42,
  })
  assert.equal(tools.length, 1)
  assert.equal(tools[0].status, 'completed')
  assert.equal(tools[0].output, 'line 1\nline 2\n')
  assert.equal(tools[0].durationMs, 42)
  assert.deepEqual(tools[0].input, { command: 'pytest -q' })

  // 2. 用户编辑重发形成分支并可无损切回原分支
  const baseMsgs = [
    { id: 'u-1', role: 'user', nodeId: 'n1', provider: 'mock', text: '第一问', createdAt: 1 },
    { id: 'a-1', role: 'assistant', nodeId: 'n1', provider: 'mock', text: '第一答', createdAt: 2 },
  ]
  const branched = branchFromUserMessage(baseMsgs, 0, '改问角度 B', 3)
  assert.equal(branched.length, 1)
  assert.equal(branched[0].text, '改问角度 B')
  assert.equal(branched[0].activeBranchIndex, 1)
  assert.equal(branched[0].branches?.length, 2)

  const branchBWithReply = [
    ...branched,
    { id: 'a-2', role: 'assistant', nodeId: 'n1', provider: 'mock', text: '角度 B 回复', createdAt: 4 },
  ]
  const restoredA = switchMessageBranch(branchBWithReply, 0, 0)
  assert.equal(restoredA[0].text, '第一问')
  assert.equal(restoredA[1].text, '第一答')
  const restoredB = switchMessageBranch(restoredA, 0, 1)
  assert.equal(restoredB[0].text, '改问角度 B')
  assert.equal(restoredB[1].text, '角度 B 回复')

  // 3. 跨会话标题/正文搜寻 + Markdown 导出
  const sess = { sessionId: 's1', nodeId: 'n1', provider: 'mock', title: '重构认证模块', cwd: '/repo' }
  const hits = searchSessionsAndMessages(
    [{ key: 'n1::mock::s1', session: sess, nodeName: 'Mac-Mini' }],
    { 'n1::mock::s1': branchBWithReply },
    '角度 B',
  )
  assert.equal(hits.get('n1::mock::s1')?.matchedIn, 'message')
  assert.ok(hits.get('n1::mock::s1')?.snippet?.includes('角度 B'))

  const md = buildSessionMarkdown(sess, [
    baseMsgs[0],
    { ...baseMsgs[1], thought: '核对鉴权边界', toolCalls: tools, diffSummary: { filesChanged: 1, additions: 3, deletions: 1 } },
  ], 'Mac-Mini')
  assert.ok(md.includes('# 重构认证模块'))
  assert.ok(md.includes('核对鉴权边界'))
  assert.ok(md.includes('Tool** `shell` [OK] (42ms)'))
  assert.ok(md.includes('+3 / -1'))
})

test('有序消息时间轴 parts、语法高亮、ANSI 解析与 Mermaid 矢量布局生成', () => {
  // 1. 有序时间轴 parts 归并与回退兼容
  let parts = appendMessagePart(undefined, { type: 'thought', text: '先检查 ' })
  parts = appendMessagePart(parts, { type: 'thought', text: '日志' })
  parts = appendMessagePart(parts, { type: 'tool', callId: 'c1' })
  parts = appendMessagePart(parts, { type: 'tool', callId: 'c1' })
  parts = appendMessagePart(parts, { type: 'text', text: '第一段总结 ' })
  parts = appendMessagePart(parts, { type: 'thought', text: '继续验证' })
  parts = appendMessagePart(parts, { type: 'text', text: '最终结论' })

  assert.deepEqual(
    parts.map(p => p.type),
    ['thought', 'tool', 'text', 'thought', 'text'],
  )
  assert.equal(parts[0].type === 'thought' && parts[0].text, '先检查 日志')
  assert.equal(parts[2].type === 'text' && parts[2].text, '第一段总结 ')

  const legacyFallback = extractMessageParts({ thought: 't', text: 'hi', toolCalls: [{ id: 't1', callId: 't1', name: 'read' }] })
  assert.deepEqual(legacyFallback.map(p => p.type), ['thought', 'tool', 'text'])

  // 2. 零依赖语法高亮（支持跨行块注释与后缀推断）
  assert.equal(inferLanguageFromPath('src/components/App.vue'), 'vue')
  const hl = highlightCode('/* multi\nline */\nexport const count = 42', 'ts')
  assert.equal(hl[0][0].kind, 'comment')
  assert.equal(hl[1][0].kind, 'comment')
  assert.equal(hl[2][0].kind, 'keyword')
  assert.ok(hl[2].some(s => s.kind === 'number' && s.text === '42'))

  // 3. ANSI 终端颜色解析
  const rawAnsi = '\u001b[1;32mPASS\u001b[0m \u001b[31mERR\u001b[0m'
  assert.equal(hasAnsiSequences(rawAnsi), true)
  const spans = parseAnsiText(rawAnsi)
  assert.equal(spans[0].text, 'PASS')
  assert.equal(spans[0].bold, true)
  assert.equal(spans[0].fg, '#16a34a')
  assert.equal(spans[2].text, 'ERR')
  assert.equal(spans[2].fg, '#dc2626')

  // 4. Mermaid 流程图与时序图安全 SVG 模型解析（含单行链式语法）
  const flow = parseMermaidDiagram('flowchart LR\nA[Read] --> B[Analyze] -->|ok| C(Done)')
  assert.ok(flow && flow.kind === 'flowchart')
  assert.equal(flow.nodes.length, 3)
  assert.deepEqual(flow.nodes.map(n => n.label), ['Read', 'Analyze', 'Done'])
  assert.equal(flow.edges.length, 2)
  assert.equal(flow.edges[1].label, 'ok')

  const seq = parseMermaidDiagram('sequenceDiagram\nClient->>Server: prompt')
  assert.ok(seq && seq.kind === 'sequence')
  assert.equal(seq.lifelines?.length, 2)
  assert.equal(seq.messages?.[0].label, 'prompt')

  assert.equal(parseMermaidDiagram('pie title Pets\n"Dogs": 30'), null)
})

test('按 Agent 保存模型与思考强度偏好并支持新对话自动延续及重置', () => {
  const mem = new Map()
  const storage = {
    getItem: k => mem.get(k) ?? null,
    setItem: (k, v) => { mem.set(k, v) },
  }

  assert.equal(resolveSavedModelPref('node-1', 'opencode', storage), null)

  saveAgentModelPref(
    { nodeId: 'node-1', provider: 'opencode', model: 'opencode-go/deepseek-v4.1-flash', effort: 'high', now: 1000 },
    storage,
  )
  assert.deepEqual(resolveSavedModelPref('node-1', 'opencode', storage), {
    model: 'opencode-go/deepseek-v4.1-flash',
    effort: 'high',
    updatedAt: 1000,
  })
  // 同 Agent 新节点（或新建其他对话）可按 provider 兜底复用上一次模型
  assert.equal(resolveSavedModelPref('node-2', 'opencode', storage)?.model, 'opencode-go/deepseek-v4.1-flash')
  // 不同 Agent 互不串台
  assert.equal(resolveSavedModelPref('node-1', 'codex', storage), null)

  // 选择不同节点上的同 Agent 新模型后，新节点优先采用精确节点偏好
  saveAgentModelPref(
    { nodeId: 'node-2', provider: 'opencode', model: 'opencode/gpt-5', now: 2000 },
    storage,
  )
  assert.equal(resolveSavedModelPref('node-1', 'opencode', storage)?.model, 'opencode-go/deepseek-v4.1-flash')
  assert.equal(resolveSavedModelPref('node-2', 'opencode', storage)?.model, 'opencode/gpt-5')

  // 切回“节点默认模型”（空字符串）应清除保存偏好
  saveAgentModelPref({ nodeId: 'node-2', provider: 'opencode', model: '' }, storage)
  assert.equal(resolveSavedModelPref('node-2', 'opencode', storage), null)
})

test('Split Diff 拆分对齐、工具局部 Diff 提取、自定义模板管理与 XSS 安全 HTML 导出', () => {
  // 1. Diff Hunk & Split 对齐
  const patch = [
    'diff --git a/src/a.ts b/src/a.ts',
    '--- a/src/a.ts',
    '+++ b/src/a.ts',
    '@@ -1,3 +1,3 @@',
    ' const a = 1',
    '-const b = 2',
    '+const b = 3',
    ' export { a, b }',
  ].join('\n')
  const hunks = parseDiffHunks(patch)
  assert.equal(hunks.length, 1)
  const rows = toSplitDiffRows(hunks[0])
  assert.equal(rows[1].leftKind, 'del')
  assert.equal(rows[1].leftText, 'const b = 2')
  assert.equal(rows[1].rightKind, 'add')
  assert.equal(rows[1].rightText, 'const b = 3')

  // 2. 工具卡片局部 Diff 提取
  const mini = extractToolMiniDiff('edit', { filePath: 'src/a.ts', oldString: 'old()', newString: 'new()' })
  assert.ok(mini && mini.filePath === 'src/a.ts')
  assert.equal(mini.lines[0].kind, 'del')
  assert.equal(mini.lines[1].kind, 'add')

  // 3. 自定义斜杠模板 CRUD
  const mem = new Map()
  const storage = { getItem: k => mem.get(k) ?? null, setItem: (k, v) => { mem.set(k, v) } }
  const saved = saveCustomPrompt({ trigger: 'audit', title: '安全审计', template: '审计 {{file}}' }, storage)
  assert.equal(saved.length, 1)
  assert.equal(saved[0].trigger, '/audit')
  assert.equal(loadCustomPrompts(storage).length, 1)
  assert.equal(deleteCustomPrompt(saved[0].id, storage).length, 0)

  // 4. HTML 报告导出严格转义恶意脚本
  const html = buildSessionHtmlReport(
    { sessionId: 's1', nodeId: 'n1', provider: 'mock', title: '<script>alert(1)</script>', cwd: '/repo' },
    [{ id: 'm1', role: 'assistant', nodeId: 'n1', provider: 'mock', text: '<img src=x onerror=alert(1)>', createdAt: 1 }],
    'Mac-Mini',
  )
  assert.ok(html.includes('&lt;script&gt;alert(1)&lt;/script&gt;'))
  assert.equal(html.includes('<img src=x onerror='), false)

  // 5. 路径语言徽章拆分与 Hunk 上下文间隙计算
  const meta = splitDiffPath('agent-node/agent_node/daemon.py')
  assert.equal(meta.fileName, 'daemon.py')
  assert.equal(meta.dirName, 'agent-node/agent_node')
  assert.equal(meta.badge, 'PY')

  const multiPatch = [
    '@@ -18,4 +18,5 @@',
    ' from a import b',
    '+from c import d',
    ' e()',
    '@@ -28,3 +29,4 @@',
    ' f()',
    '+g()',
    ' h()',
  ].join('\n')
  const mh = parseDiffHunks(multiPatch)
  const gaps = computeHunkGaps(mh, 40)
  assert.equal(gaps.beforeFirst?.startNewLine, 1)
  assert.equal(gaps.beforeFirst?.endNewLine, 17)
  assert.equal(gaps.between[0]?.startNewLine, 23)
  assert.equal(gaps.between[0]?.endNewLine, 28)
  assert.equal(gaps.between[0]?.oldDelta, -1)
  assert.equal(gaps.afterLast?.startNewLine, 33)
  assert.equal(gaps.afterLast?.endNewLine, 40)
})
