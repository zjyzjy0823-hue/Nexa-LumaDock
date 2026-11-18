/**
 * Fleet 聊天会话纯函数辅助库：
 * 包含工具调用增量合并、消息分支（编辑重发/切换分支）、跨会话消息检索与 Markdown 导出。
 */

import type {
  ChatMessage,
  ChatSession,
  FleetWsEvent,
  MessageBranch,
  MessagePart,
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
