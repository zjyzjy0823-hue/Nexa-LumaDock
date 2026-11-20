/**
 * Fleet 聊天会话纯函数辅助库：
 * 包含工具调用增量合并、消息分支（编辑重发/切换分支）、跨会话消息检索与 Markdown 导出。
 */

import type {
  ChatMessage,
  ChatSession,
  DiffAnnotation,
  FleetWsEvent,
  MessageBranch,
  MessagePart,
  PastedTextBlock,
  ToolCallBadge,
  ToolCallStatus,
} from '../types/fleet'

/**
 * 将流式碎片按时间轴顺序追加到消息的 `parts` 序列中：
 * 相邻同类型 `thought` / `text` 自动合并，同一 `callId` 的工具调用保持首次出现位置不重复追加。
 */
export function appendMessagePart(
  existing: MessagePart[] | undefined,
  next: MessagePart,
): MessagePart[] {
  const list = existing ? existing.map(p => ({ ...p })) : []
  if (next.type === 'tool') {
    if (list.some(p => p.type === 'tool' && p.callId === next.callId)) {
      return list
    }
    list.push({ type: 'tool', callId: next.callId })
    return list
  }
  if (!next.text) return list
  const last = list[list.length - 1]
  if (last && last.type === next.type) {
    last.text += next.text
    return list
  }
  list.push({ type: next.type, text: next.text })
  return list
}

/**
 * 读取消息的时间轴碎片；老格式消息无 `parts` 时自动退化为 `[thought?, tools..., text?]`。
 */
export function extractMessageParts(
  msg: Pick<ChatMessage, 'parts' | 'thought' | 'toolCalls' | 'text'>,
): MessagePart[] {
  if (msg.parts?.length) return msg.parts
  const out: MessagePart[] = []
  if (msg.thought?.trim()) out.push({ type: 'thought', text: msg.thought })
  for (const tc of msg.toolCalls ?? []) {
    out.push({ type: 'tool', callId: tc.callId || tc.id })
  }
  if (msg.text) out.push({ type: 'text', text: msg.text })
  return out
}

/**
 * 归一化工具状态字符串为前端展示枚举。
 */
export function normalizeToolStatus(raw?: string): ToolCallStatus {
  const val = String(raw || '').trim().toLowerCase()
  if (val === 'error' || val === 'failed' || val === 'declined' || val === 'cancelled') {
    return 'error'
  }
  if (val === 'completed' || val === 'succeeded' || val === 'done') {
    return 'completed'
  }
  return 'running'
}

/**
 * 将入站 `ToolCallUpdate` 或兼容 `ToolCall` 事件合并至消息的工具调用列表中。
 * 同一 `callId` 会原地更新状态、追加流式输出（`deltaOutput`）并记录耗时。
 */
export function mergeToolCallUpdate(
  existing: ToolCallBadge[] | undefined,
  evt: Pick<
    FleetWsEvent,
    | 'callId'
    | 'name'
    | 'title'
    | 'detail'
    | 'status'
    | 'input'
    | 'output'
    | 'deltaOutput'
    | 'error'
    | 'durationMs'
    | 'subagentSessionId'
    | 'media'
  >,
): ToolCallBadge[] {
  const list = [...(existing ?? [])]
  const key = evt.callId || `legacy-${evt.name || 'tool'}`
  const matchIdx = evt.callId
    ? list.findIndex(item => item.callId === evt.callId || item.id === evt.callId)
    : -1

  if (matchIdx === -1) {
    const status: ToolCallStatus = evt.status
      ? normalizeToolStatus(evt.status)
      : (evt.detail ? 'completed' : 'running')
    const created: ToolCallBadge = {
      id: key,
      callId: evt.callId,
      name: evt.name || 'tool',
      title: evt.title || evt.detail || evt.name || 'tool',
      detail: evt.detail,
      status,
      input: evt.input,
      output: evt.output ?? evt.deltaOutput ?? '',
      error: evt.error,
      durationMs: evt.durationMs,
      subagentSessionId: evt.subagentSessionId,
      ...(evt.media?.length ? { media: evt.media } : {}),
      startedAt: Date.now(),
    }
    list.push(created)
    return list
  }

  const prev = list[matchIdx]
  const nextStatus: ToolCallStatus = evt.status ? normalizeToolStatus(evt.status) : (prev.status ?? 'running')
  const nextOutput = evt.output !== undefined
    ? evt.output
    : evt.deltaOutput
      ? `${prev.output ?? ''}${evt.deltaOutput}`
      : prev.output

  list[matchIdx] = {
    ...prev,
    name: evt.name || prev.name,
    title: evt.title ?? evt.detail ?? prev.title,
    detail: evt.detail ?? prev.detail,
    status: nextStatus,
    input: evt.input !== undefined ? evt.input : prev.input,
    output: nextOutput,
    error: evt.error !== undefined ? evt.error : prev.error,
    durationMs: evt.durationMs ?? prev.durationMs,
    subagentSessionId: evt.subagentSessionId ?? prev.subagentSessionId,
    media: evt.media?.length ? evt.media : prev.media,
  }
  return list
}

/**
 * 为历史消息创建新分支（支持用户编辑历史消息重发，或重新生成助手回复）。
 * 返回截断至目标消息并切换至新分支的消息数组。
 */
export function branchFromUserMessage(
  messages: ChatMessage[],
  userMsgIndex: number,
  nextUserText: string,
  now = Date.now(),
): ChatMessage[] {
  if (userMsgIndex < 0 || userMsgIndex >= messages.length) return messages
  const target = messages[userMsgIndex]
  if (target.role !== 'user') return messages

  const existingBranches: MessageBranch[] = target.branches
    ? target.branches.map(b => ({ ...b, tailMessages: [...b.tailMessages] }))
    : [
        {
          userText: target.text,
          tailMessages: messages.slice(userMsgIndex + 1),
          createdAt: target.createdAt,
        },
      ]

  const activeIdx = target.activeBranchIndex ?? 0
  if (existingBranches[activeIdx]) {
    existingBranches[activeIdx] = {
      ...existingBranches[activeIdx],
      userText: target.text,
      tailMessages: messages.slice(userMsgIndex + 1),
    }
  }

  const cleanNext = nextUserText.trim()
  const newBranch: MessageBranch = {
    userText: cleanNext,
    tailMessages: [],
    createdAt: now,
  }
  const allBranches = [...existingBranches, newBranch]
  const nextTarget: ChatMessage = {
    ...target,
    text: cleanNext,
    branches: allBranches,
    activeBranchIndex: allBranches.length - 1,
  }

  return [...messages.slice(0, userMsgIndex), nextTarget]
}

/**
 * 在同一消息的多个历史分支间无损切换，自动保留当前分支后续消息状态。
 */
export function switchMessageBranch(
  messages: ChatMessage[],
  anchorIndex: number,
  targetBranchIndex: number,
): ChatMessage[] {
  if (anchorIndex < 0 || anchorIndex >= messages.length) return messages
  const anchor = messages[anchorIndex]
  const branches = anchor.branches
  if (!branches || targetBranchIndex < 0 || targetBranchIndex >= branches.length) {
    return messages
  }

  const nextBranches = branches.map(b => ({ ...b, tailMessages: [...b.tailMessages] }))
  const curIdx = anchor.activeBranchIndex ?? 0
  if (nextBranches[curIdx]) {
    nextBranches[curIdx] = {
      ...nextBranches[curIdx],
      userText: anchor.text,
      tailMessages: messages.slice(anchorIndex + 1),
    }
  }

  const chosen = nextBranches[targetBranchIndex]
  const updatedAnchor: ChatMessage = {
    ...anchor,
    text: chosen.userText,
    branches: nextBranches,
    activeBranchIndex: targetBranchIndex,
  }

  return [...messages.slice(0, anchorIndex), updatedAnchor, ...chosen.tailMessages]
}

export interface SessionSearchHit {
  sessionKey: string
  matchedIn: 'meta' | 'message'
  snippet?: string
}

/**
 * 跨会话标题、目录、节点及当前内存消息正文检索匹配会话。
 */
export function searchSessionsAndMessages(
  sessions: Array<{ key: string; session: ChatSession; nodeName?: string }>,
  messagesBySession: Record<string, ChatMessage[]>,
  rawQuery: string,
): Map<string, SessionSearchHit> {
  const q = rawQuery.trim().toLowerCase()
  const hits = new Map<string, SessionSearchHit>()
  if (!q) return hits

  for (const item of sessions) {
    const { key, session, nodeName } = item
    const metaHay = `${session.title} ${session.provider} ${session.cwd} ${nodeName || ''}`.toLowerCase()
    if (metaHay.includes(q)) {
      hits.set(key, { sessionKey: key, matchedIn: 'meta' })
      continue
    }
    const msgs = messagesBySession[key] ?? []
    for (let i = msgs.length - 1; i >= 0; i--) {
      const m = msgs[i]
      const text = `${m.text || ''}\n${m.thought || ''}`
      const pos = text.toLowerCase().indexOf(q)
      if (pos >= 0) {
        const start = Math.max(0, pos - 16)
        const end = Math.min(text.length, pos + q.length + 32)
        const snippet = `${start > 0 ? '…' : ''}${text.slice(start, end).replace(/\s+/g, ' ')}${end < text.length ? '…' : ''}`
        hits.set(key, { sessionKey: key, matchedIn: 'message', snippet })
        break
      }
    }
  }
  return hits
}

/**
 * 将当前会话完整消息（含思考过程、工具调用日志、Git 变更统计与产物清单）导出为纯净 Markdown。
 */
export function buildSessionMarkdown(
  session: ChatSession,
  messages: ChatMessage[],
  nodeName?: string,
): string {
  const lines: string[] = [
    `# ${session.title || session.sessionId}`,
    '',
    `- **节点**：${nodeName || session.nodeId}`,
    `- **模型运行时**：\`${session.provider}\``,
    `- **工作目录**：\`${session.worktreePath || session.cwd || '-'}\``,
    `- **会话 ID**：\`${session.sessionId}\``,
    `- **导出时间**：${new Date().toISOString()}`,
    '',
    '---',
    '',
  ]

  for (const msg of messages) {
    const roleLabel = msg.role === 'user' ? 'User' : msg.role === 'assistant' ? `Assistant (${msg.provider})` : 'System'
    lines.push(`## ${roleLabel}`)
    lines.push('')
    if (msg.parts?.length) {
      const toolMap = new Map((msg.toolCalls ?? []).map(tc => [tc.callId || tc.id, tc]))
      for (const part of msg.parts) {
        if (part.type === 'thought' && part.text.trim()) {
          lines.push('<details>')
          lines.push('<summary>思考过程 / Thought</summary>')
          lines.push('')
          lines.push(part.text.trim())
          lines.push('')
          lines.push('</details>')
          lines.push('')
        } else if (part.type === 'tool') {
          const tc = toolMap.get(part.callId)
          if (tc) {
            const st = tc.status === 'error' ? 'FAILED' : tc.status === 'running' ? 'RUNNING' : 'OK'
            const dur = tc.durationMs !== undefined ? ` (${tc.durationMs}ms)` : ''
            lines.push(`- **Tool** \`${tc.name}\` [${st}]${dur}: ${tc.title || tc.detail || ''}`)
            if (tc.output?.trim()) {
              lines.push('')
              lines.push('```text')
              lines.push(tc.output.trim())
              lines.push('```')
            }
            if (tc.error?.trim()) lines.push(`  > Error: ${tc.error.trim()}`)
            lines.push('')
          }
        } else if (part.type === 'text' && part.text.trim()) {
          lines.push(part.text.trim())
          lines.push('')
        }
      }
    } else {
      if (msg.thought?.trim()) {
        lines.push('<details>')
        lines.push('<summary>思考过程 / Thought</summary>')
        lines.push('')
        lines.push(msg.thought.trim())
        lines.push('')
        lines.push('</details>')
        lines.push('')
      }
      if (msg.toolCalls?.length) {
        for (const tc of msg.toolCalls) {
          const st = tc.status === 'error' ? 'FAILED' : tc.status === 'running' ? 'RUNNING' : 'OK'
          const dur = tc.durationMs !== undefined ? ` (${tc.durationMs}ms)` : ''
          lines.push(`- **Tool** \`${tc.name}\` [${st}]${dur}: ${tc.title || tc.detail || ''}`)
          if (tc.output?.trim()) {
            lines.push('')
            lines.push('```text')
            lines.push(tc.output.trim())
            lines.push('```')
          }
          if (tc.error?.trim()) {
            lines.push(`  > Error: ${tc.error.trim()}`)
          }
        }
        lines.push('')
      }
      if (msg.text?.trim()) {
        lines.push(msg.text.trim())
        lines.push('')
      }
    }
    if (msg.diffSummary?.filesChanged) {
      lines.push(
        `> Git 变更快照：${msg.diffSummary.filesChanged} 个文件 (+${msg.diffSummary.additions} / -${msg.diffSummary.deletions})`,
      )
      lines.push('')
    }
    if (msg.artifacts?.length) {
      for (const art of msg.artifacts) {
        lines.push(`- **附件**：\`${art.fileName}\` (${art.plaintextSize} bytes)`)
      }
      lines.push('')
    }
  }
  return lines.join('\n')
}

export interface GroupedToolRun {
  type: 'tool-group'
  id: string
  callIds: string[]
  tools: ToolCallBadge[]
  summaryLabel: string
  totalDurationMs: number
  hasRunning: boolean
  hasError: boolean
}

export type GroupedMessagePart =
  | { type: 'thought'; text: string }
  | { type: 'text'; text: string }
  | { type: 'tool'; callId: string; tool: ToolCallBadge }
  | GroupedToolRun

function classifyToolKind(name: string): 'read' | 'edit' | 'cmd' | 'search' | 'subagent' | 'other' {
  const n = name.toLowerCase()
  if (n.includes('subagent') || n.includes('agent') || n.includes('delegate') || n.includes('task')) return 'subagent'
  if (n.includes('edit') || n.includes('write') || n.includes('patch') || n.includes('replace') || n.includes('create')) return 'edit'
  if (n.includes('bash') || n.includes('shell') || n.includes('command') || n.includes('exec') || n.includes('run')) return 'cmd'
  if (n.includes('grep') || n.includes('search') || n.includes('glob') || n.includes('find') || n.includes('list')) return 'search'
  if (n.includes('read') || n.includes('view') || n.includes('cat') || n.includes('file')) return 'read'
  return 'other'
}

/**
 * 将消息时间轴中的连续多步工具调用聚合成紧凑的 Work Run（>= 2 个连续 tool 时折叠分组），
 * 减少长工具流刷屏并保留单步工具和错误/运行中状态可见性。
 */
export function groupMessageParts(
  msg: Pick<ChatMessage, 'parts' | 'thought' | 'toolCalls' | 'text'>,
): GroupedMessagePart[] {
  const raw = extractMessageParts(msg)
  const toolMap = new Map((msg.toolCalls ?? []).map(tc => [tc.callId || tc.id, tc]))
  const out: GroupedMessagePart[] = []

  let toolBucket: Array<{ callId: string; tool: ToolCallBadge }> = []

  const flushBucket = () => {
    if (!toolBucket.length) return
    if (toolBucket.length === 1) {
      out.push({ type: 'tool', callId: toolBucket[0].callId, tool: toolBucket[0].tool })
      toolBucket = []
      return
    }
    const counts = { read: 0, edit: 0, cmd: 0, search: 0, subagent: 0, other: 0 }
    let totalDurationMs = 0
    let hasRunning = false
    let hasError = false
    for (const item of toolBucket) {
      const k = item.tool.subagentSessionId ? 'subagent' : classifyToolKind(item.tool.name)
      counts[k] += 1
      if (typeof item.tool.durationMs === 'number' && !Number.isNaN(item.tool.durationMs)) {
        totalDurationMs += item.tool.durationMs
      }
      if (item.tool.status === 'running') hasRunning = true
      if (item.tool.status === 'error') hasError = true
    }
    const parts: string[] = []
    if (counts.read) parts.push(`读取 ${counts.read}`)
    if (counts.search) parts.push(`检索 ${counts.search}`)
    if (counts.edit) parts.push(`修改 ${counts.edit}`)
    if (counts.cmd) parts.push(`命令 ${counts.cmd}`)
    if (counts.subagent) parts.push(`子代理 ${counts.subagent}`)
    if (counts.other) parts.push(`工具 ${counts.other}`)

    out.push({
      type: 'tool-group',
      id: `grp-${toolBucket[0].callId}-${toolBucket.length}`,
      callIds: toolBucket.map(x => x.callId),
      tools: toolBucket.map(x => x.tool),
      summaryLabel: parts.join(' · ') || `${toolBucket.length} 项操作`,
      totalDurationMs,
      hasRunning,
      hasError,
    })
    toolBucket = []
  }

  for (const part of raw) {
    if (part.type === 'tool') {
      const tc = toolMap.get(part.callId)
      if (tc) toolBucket.push({ callId: part.callId, tool: tc })
      continue
    }
    flushBucket()
    if (part.type === 'thought' && part.text) {
      out.push({ type: 'thought', text: part.text })
    } else if (part.type === 'text' && part.text) {
      out.push({ type: 'text', text: part.text })
    }
  }
  flushBucket()
  return out
}

/**
 * 为分叉会话生成结构化前情上下文种子，确保新开启的上游 Agent 承接原会话历史而不失忆。
 */
export function buildForkContextSeed(
  messages: ChatMessage[],
  sourceTitle: string,
  maxChars = 6000,
): string {
  const relevant = messages.filter(m => m.role !== 'system' && (m.text?.trim() || m.toolCalls?.length))
  if (!relevant.length) return ''
  const chunks: string[] = []
  let used = 0
  for (let i = relevant.length - 1; i >= 0; i -= 1) {
    const m = relevant[i]
    const role = m.role === 'user' ? 'User' : 'Assistant'
    const body = (m.text || '').trim().slice(0, 1200)
    const toolsNote = m.toolCalls?.length
      ? ` [已调用工具: ${m.toolCalls.slice(0, 6).map(t => t.name).join(', ')}]`
      : ''
    const line = `${role}: ${body}${toolsNote}`
    if (used + line.length > maxChars && chunks.length > 0) break
    chunks.unshift(line)
    used += line.length + 2
  }
  return `[分支上下文 · 继承自「${sourceTitle}」]\n以下是分叉节点前的对话记录，请以此为上下文继续处理后续指令：\n\n${chunks.join('\n\n')}`
}

/**
 * 将所有未解决的 Diff 行内批注按文件聚合成单次结构化评审修正 Prompt，避免逐条零散发送。
 */
export function buildDiffAnnotationsPrompt(annotations: DiffAnnotation[]): string {
  const unresolved = annotations.filter(a => !a.resolved && a.comment.trim())
  if (!unresolved.length) return ''
  const byFile = new Map<string, DiffAnnotation[]>()
  for (const item of unresolved) {
    const list = byFile.get(item.filePath) ?? []
    list.push(item)
    byFile.set(item.filePath, list)
  }
  const sections: string[] = [
    `请根据以下 ${unresolved.length} 条代码评审批注一次性修订工作区改动，修订完成后逐条说明改动结果：`,
  ]
  for (const [filePath, list] of byFile.entries()) {
    const sorted = [...list].sort((a, b) => a.lineNo - b.lineNo)
    sections.push(`\n### @${filePath}`)
    for (const item of sorted) {
      const code = item.codeSnippet.trim().slice(0, 100)
      sections.push(`- **L${item.lineNo}**${code ? ` (\`${code}\`)` : ''}: ${item.comment.trim()}`)
    }
  }
  return sections.join('\n')
}

export const LARGE_PASTE_CHAR_THRESHOLD = 1200
export const LARGE_PASTE_LINE_THRESHOLD = 30

/**
 * 判断剪贴板粘贴纯文本是否应自动收纳为紧凑的「粘贴文本块芯片」，避免撑爆输入框。
 */
export function shouldConvertToPastedBlock(text: string): boolean {
  if (!text) return false
  if (text.length >= LARGE_PASTE_CHAR_THRESHOLD) return true
  const lines = text.split(/\r\n|\r|\n/).length
  return lines >= LARGE_PASTE_LINE_THRESHOLD
}

export function createPastedTextBlock(text: string, id: string): PastedTextBlock {
  const normalized = text.replace(/\r\n/g, '\n')
  const lines = normalized.split('\n')
  const firstNonEmpty = lines.find(l => l.trim())?.trim() ?? '粘贴文本'
  const title = firstNonEmpty.length > 26 ? `${firstNonEmpty.slice(0, 26)}…` : firstNonEmpty
  return {
    id,
    title,
    content: normalized,
    lineCount: lines.length,
    charCount: normalized.length,
  }
}

/**
 * 文件路径模糊子序列匹配打分（例如 `act` 命中 `AgentChatThread.vue`），越小越靠前，未命中返回 null。
 */
export function fuzzyMatchFileScore(query: string, filePath: string): number | null {
  const q = query.trim().toLowerCase()
  if (!q) return 0
  const norm = filePath.replace(/\\/g, '/')
  const baseName = norm.split('/').pop() || norm
  const lowBase = baseName.toLowerCase()
  const lowFull = norm.toLowerCase()

  if (lowBase.startsWith(q)) return 0
  const baseIdx = lowBase.indexOf(q)
  if (baseIdx >= 0) return 10 + baseIdx
  const fullIdx = lowFull.indexOf(q)
  if (fullIdx >= 0) return 25 + Math.min(fullIdx, 40)

  const scoreSubseq = (target: string, penalty: number): number | null => {
    const low = target.toLowerCase()
    let qi = 0
    let score = 60 + penalty
    let prev = -2
    for (let i = 0; i < low.length; i += 1) {
      if (low[i] === q[qi]) {
        if (i === prev + 1) score -= 2
        else if (i === 0 || '/_-.'.includes(target[i - 1]) || (target[i] >= 'A' && target[i] <= 'Z')) score -= 3
        prev = i
        qi += 1
        if (qi === q.length) return Math.max(30, score + Math.floor(target.length / 8))
      }
    }
    return null
  }

  return scoreSubseq(baseName, 0) ?? scoreSubseq(norm, 18)
}

/**
 * 判断错误信息是否属于模型限额、配额耗尽或模型不可用类错误，以便在错误卡片上提供「一键换模型重试」。
 */
export function isQuotaOrModelError(errorText?: string): boolean {
  const txt = String(errorText || '').toLowerCase()
  if (!txt) return false
  return /(usage limit|rate limit|quota|insufficient|credit|429|free usage|model.*not found|model.*unavailable|subscribe|switch model|额度|限流|配额)/i.test(txt)
}

/**
 * 解析带文件路径的代码块语言标记，如 `ts:src/stores/fleet.ts` -> `{ lang: 'ts', filePath: 'src/stores/fleet.ts' }`。
 */
export function parseCodeBlockLang(rawLang?: string): { lang: string; filePath?: string } {
  const raw = String(rawLang || '').trim()
  if (!raw) return { lang: '' }
  const colonIdx = raw.indexOf(':')
  if (colonIdx > 0 && colonIdx < raw.length - 1) {
    const head = raw.slice(0, colonIdx).trim()
    const tail = raw.slice(colonIdx + 1).trim()
    if (tail && !tail.includes('://') && /[/.]/.test(tail)) {
      return { lang: head, filePath: tail }
    }
  }
  return { lang: raw }
}

/**
 * 根据当前工作区 Git Diff 自动拟定一条简洁规范的中文 Conventional Commit 提交说明。
 */
export function suggestCommitMessageFromDiff(
  files: Array<{ path: string; status?: string; additions?: number; deletions?: number }>,
): string {
  if (!files.length) return ''
  const paths = files.map(f => f.path.replace(/\\/g, '/'))
  const allDocs = paths.every(p => /\.md$/i.test(p) || p.startsWith('docs/'))
  const allTests = paths.every(p => /(?:^|\/)tests?\/|\.test\.|\.spec\./i.test(p))
  const allStyles = paths.every(p => /\.(?:css|scss|less)$/i.test(p))
  const allNew = files.every(f => (f.status || '').toUpperCase().startsWith('A') || (f.deletions ?? 0) === 0)

  const prefix = allDocs ? 'docs' : allTests ? 'test' : allStyles ? 'style' : allNew ? 'feat' : 'feat'
  const topNames = paths.slice(0, 2).map(p => p.split('/').pop() || p)
  const scopeHint = topNames.join('、')
  if (paths.length === 1) {
    return `${prefix}: 更新 ${scopeHint}`
  }
  if (paths.length <= 3) {
    return `${prefix}: 更新 ${scopeHint} 等 ${paths.length} 个文件`
  }
  const topDir = paths[0].includes('/') ? paths[0].split('/').slice(0, 2).join('/') : paths[0]
  return `${prefix}: 优化 ${topDir} 等 ${paths.length} 个文件变更`
}

export function redactSessionTitleCredentials(title: string): string {
  return title
    .replace(/\b(?:sk-(?:proj-|ant-|or-v1-)?[\w-]{16,}|gh[pousr]_[\w]{20,}|github_pat_[\w]{20,}|AIza[\w-]{30,})\b/g, '[密钥已隐藏]')
    .replace(/((?:api[ _-]?key|access[ _-]?token|authorization|密钥)\s*[:=：]\s*(?:Bearer\s+)?["'`]?)[\w+./=-]{12,}/gi, '$1[密钥已隐藏]')
}

/**
 * 从用户首句提炼简洁可读的乐观会话标题。
 */
export function deriveOptimisticSessionTitle(text: string): string {
  const clean = redactSessionTitleCredentials(text)
    .replace(/^\[附加上下文\][\s\S]*?\n\n/, '')
    .replace(/^\[Plan Mode\][^\n]*\n+/, '')
    .replace(/^\[重新生成上一轮回答\][^\n]*\n+/, '')
    .replace(/\s+/g, ' ')
    .trim()
  if (!clean) return ''
  return clean.length > 22 ? `${clean.slice(0, 22)}…` : clean
}

export function isGenericSessionTitle(title?: string): boolean {
  const t = String(title || '').trim()
  if (!t) return true
  return /^(?:codex|opencode|hermes|antigravity|dsh|openclaw|mock)\s*(?:·|\()\s*.+$/i.test(t)
    || /^(?:new session|untitled|新建会话|新会话|新对话|ses_[a-z0-9]+|oc-[a-z0-9]+)$/i.test(t)
}
