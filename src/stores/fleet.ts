/**
 * Studiolo Fleet 状态容器（纯内存多设备会话总线，聊天正文与 E2EE 密钥绝不落盘）。
 */

import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { downloadAndDecryptBlob, encryptAndUploadFile } from '../services/blobTransfer'
import {
  buildFleetWsUrl,
  createFleetNode,
  deleteFleetNode,
  getApiBaseUrl,
  listFleetNodes,
  revokeFleetNode,
  rotateFleetNodeToken,
} from '../services/fleet'
import type {
  AdapterProvider,
  AgentNode,
  ApprovalDecision,
  ArtifactRef,
  ChatMessage,
  ChatSession,
  FleetConnectionState,
  FleetWsEvent,
  FleetModel,
  RunOptions,
  NodePlatform,
  NodeTokenOut,
  PermissionRequestCard,
  SessionTokenUsage,
} from '../types/fleet'
import {
  applyTokenUsageEvent,
  estimateTurnUsageFallback,
  hasRecordedTurnUsage,
  toSessionTokenSummary,
  type SessionTokenState,
  type TokenUsageInput,
} from '../services/tokenUsage'
import { useAuthStore } from './auth'

const MAX_MESSAGES_PER_SESSION = 200
const RECONNECT_DELAYS_MS = [1000, 2000, 4000, 8000, 15000]

export function sessionKey(nodeId: string, provider: AdapterProvider, sessionId: string): string {
  return `${nodeId}::${provider}::${sessionId}`
}

export function createRequestId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `req-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
}

export const useFleetStore = defineStore('fleet', () => {
  const auth = useAuthStore()

  // ---------------- 节点元信息（允许从 Core REST 刷新，不包含聊天正文） ----------------
  const nodes = ref<AgentNode[]>([])
  const nodesLoading = ref(false)
  const lastError = ref<string | null>(null)

  // ---------------- 实时连接状态 ----------------
  const wsState = ref<FleetConnectionState>('disconnected')
  let socket: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempt = 0
  let intentionalClose = false
  let activeConnectToken: string | null = null

  // ---------------- 纯内存会话/消息/审批/产物状态 ----------------
  const selectedNodeId = ref<string>('')
  const selectedProvider = ref<AdapterProvider>('codex')
  const activeSessionKey = ref<string>('')
  const sessionsByKey = ref<Record<string, ChatSession>>({})
  const messagesBySession = ref<Record<string, ChatMessage[]>>({})
  const pendingApprovalsByCall = ref<Record<string, PermissionRequestCard>>({})
  const runningBySession = ref<Record<string, string>>({}) // sessionKey -> active runId
  const composerDrafts = ref<Record<string, { text: string; files: File[] }>>({})
  const runSettings = ref<Record<string, RunOptions>>({})
  const catalogs = ref<Record<string, { models: FleetModel[]; message?: string }>>({})
  const tokenUsageStateBySession = ref<Record<string, SessionTokenState>>({})
  const imagePreviewByArtifactId = ref<Record<string, string>>({})
  const pendingRunPrompts = new Map<string, { text: string; model?: string }>()
  const autoPulledNodes = new Set<string>()
  const sentRequestIds = new Set<string>()
  const pendingOpenQueue: Array<{
    nodeId: string
    provider: AdapterProvider
    requestId: string
    onOpened?: (key: string) => void
    options?: RunOptions
    initialPrompt?: string
    initialAttachments?: ArtifactRef[]
  }> = []

  // ---------------- Computed Views ----------------
  const selectedNode = computed(
    () => nodes.value.find(n => n.id === selectedNodeId.value) ?? nodes.value[0] ?? null,
  )

  const availableProviders = computed<AdapterProvider[]>(() => {
    const node = selectedNode.value
    if (!node || !node.adapters.length) {
      return ['codex', 'opencode', 'hermes', 'antigravity', 'dsh', 'openclaw', 'mock']
    }
    return node.adapters.map(a => a.provider)
  })

  const sessionsForCurrentNode = computed<ChatSession[]>(() => {
    const nid = selectedNode.value?.id
    if (!nid) return []
    return Object.values(sessionsByKey.value).filter(s => s.nodeId === nid)
  })

  const allSessions = computed<ChatSession[]>(() => Object.values(sessionsByKey.value))

  const currentSession = computed<ChatSession | null>(
    () => (activeSessionKey.value ? sessionsByKey.value[activeSessionKey.value] ?? null : null),
  )

  const currentMessages = computed<ChatMessage[]>(
    () => (activeSessionKey.value ? messagesBySession.value[activeSessionKey.value] ?? [] : []),
  )

  const pendingApprovalsList = computed<PermissionRequestCard[]>(() =>
    Object.values(pendingApprovalsByCall.value).filter(c => c.decision === 'pending'),
  )

  const nodesWithApprovalPending = computed(() => {
    const set = new Set<string>()
    for (const card of pendingApprovalsList.value) {
      set.add(card.nodeId)
    }
    return set
  })

  const currentIsStreaming = computed<boolean>(
    () => Boolean(activeSessionKey.value && runningBySession.value[activeSessionKey.value]),
  )

  const tokenUsageBySession = computed<Record<string, SessionTokenUsage>>(() => {
    const out: Record<string, SessionTokenUsage> = {}
    for (const [k, state] of Object.entries(tokenUsageStateBySession.value)) {
      const summary = toSessionTokenSummary(state)
      if (summary) out[k] = summary
    }
    return out
  })

  // ---------------- 内存清理（登出 / 切换工作区时必须彻底销毁正文与密钥） ----------------
  function clearSessionMemory() {
    disconnectSocket()
    sessionsByKey.value = {}
    messagesBySession.value = {}
    pendingApprovalsByCall.value = {}
    runningBySession.value = {}
    activeSessionKey.value = ''
    sentRequestIds.clear()
    composerDrafts.value = {}
    runSettings.value = {}
    catalogs.value = {}
    tokenUsageStateBySession.value = {}
    for (const url of Object.values(imagePreviewByArtifactId.value)) {
      if (typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function') {
        try { URL.revokeObjectURL(url) } catch { /* ignore */ }
      }
    }
    imagePreviewByArtifactId.value = {}
    pendingRunPrompts.clear()
    autoPulledNodes.clear()
    pendingOpenQueue.length = 0
  }

  function disconnectSocket() {
    intentionalClose = true
    activeConnectToken = null
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (socket) {
      try {
        socket.close(1000, 'client_disconnect')
      } catch {
        // 忽略已关闭连接错误
      }
      socket = null
    }
    wsState.value = 'disconnected'
  }

  // 当用户登出或 JWT 变更时立即清空所有内存会话与 E2EE 密钥
  watch(
    () => auth.token,
    (nextToken, prevToken) => {
      if (!nextToken || nextToken !== prevToken) {
        clearSessionMemory()
        nodes.value = []
      }
    },
  )

  // ---------------- REST Node Lifecycle ----------------
  async function loadNodes() {
    if (!auth.token) return
    nodesLoading.value = true
    lastError.value = null
    try {
      const fetched = await listFleetNodes(auth.token)
      nodes.value = fetched
      if (!selectedNodeId.value || !fetched.some(n => n.id === selectedNodeId.value)) {
        const firstOnline = fetched.find(n => n.status === 'online') ?? fetched[0]
        if (firstOnline) {
          selectedNodeId.value = firstOnline.id
          syncProviderForNode(firstOnline)
        }
      }
    } catch (err) {
      lastError.value = err instanceof Error ? err.message : '加载节点列表失败'
    } finally {
      nodesLoading.value = false
    }
  }

  function syncProviderForNode(node: AgentNode) {
    if (!node.adapters.length) return
    const currentOk = node.adapters.some(
      a => a.provider === selectedProvider.value && a.status === 'ready',
    )
    if (!currentOk) {
      const ready = node.adapters.find(a => a.status === 'ready') ?? node.adapters[0]
      if (ready) selectedProvider.value = ready.provider
    }
  }

  async function registerNode(payload: {
    name: string
    platform: NodePlatform
    hostname?: string | null
  }): Promise<NodeTokenOut> {
    if (!auth.token) throw new Error('尚未登录')
    const res = await createFleetNode(auth.token, payload)
    nodes.value = [res.node, ...nodes.value.filter(n => n.id !== res.node.id)]
    if (!selectedNodeId.value) selectedNodeId.value = res.node.id
    return res
  }

  async function rotateNode(nodeId: string): Promise<NodeTokenOut> {
    if (!auth.token) throw new Error('尚未登录')
    const res = await rotateFleetNodeToken(auth.token, nodeId)
    nodes.value = nodes.value.map(n => (n.id === nodeId ? res.node : n))
    return res
  }

  async function revokeNode(nodeId: string): Promise<AgentNode> {
    if (!auth.token) throw new Error('尚未登录')
    const updated = await revokeFleetNode(auth.token, nodeId)
    nodes.value = nodes.value.map(n => (n.id === nodeId ? updated : n))
    return updated
  }

  async function removeNode(nodeId: string): Promise<void> {
    if (!auth.token) throw new Error('尚未登录')
    await deleteFleetNode(auth.token, nodeId)
    nodes.value = nodes.value.filter(n => n.id !== nodeId)
    if (selectedNodeId.value === nodeId) {
      selectedNodeId.value = nodes.value[0]?.id ?? ''
    }
  }

  // ---------------- WebSocket 连接与首帧认证 ----------------
  function connectSocket() {
    const token = auth.token
    if (!token) return
    if (
      socket &&
      activeConnectToken === token &&
      (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)
    ) {
      return
    }

    intentionalClose = false
    activeConnectToken = token
    wsState.value = reconnectAttempt > 0 ? 'reconnecting' : 'connecting'

    const wsUrl = buildFleetWsUrl()
    const ws = new WebSocket(wsUrl)
    socket = ws

    ws.onopen = () => {
      if (socket !== ws) return
      // 首帧发送认证 JWT（避免泄漏到 URL），待服务端回传 FleetSnapshot 验证握手成功后再转 online
      ws.send(JSON.stringify({ type: 'auth', token }))
    }

    ws.onmessage = event => {
      if (socket !== ws) return
      try {
        const frame = JSON.parse(String(event.data)) as FleetWsEvent
        handleWsEvent(frame)
      } catch {
        // 忽略非法 JSON 帧
      }
    }

    ws.onclose = ev => {
      if (socket !== ws) return
      socket = null
      if (intentionalClose || ev.code === 4401) {
        wsState.value = 'disconnected'
        if (ev.code === 4401) {
          lastError.value = 'Fleet 会话认证失败或登录已过期'
        }
        return
      }
      wsState.value = 'reconnecting'
      const delay = RECONNECT_DELAYS_MS[Math.min(reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)]
      reconnectAttempt += 1
      reconnectTimer = setTimeout(() => {
        if (!intentionalClose && auth.token) connectSocket()
      }, delay)
    }

    ws.onerror = () => {
      if (wsState.value === 'connecting') {
        wsState.value = 'reconnecting'
      }
    }
  }

  function sendWsCommand(frame: Record<string, unknown>): boolean {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      connectSocket()
      lastError.value = '正在建立到 Core Relay 的连接，请稍候重试'
      return false
    }
    socket.send(JSON.stringify(frame))
    return true
  }

  function appendMessage(sKey: string, msg: ChatMessage) {
    const prev = messagesBySession.value[sKey] ?? []
    const next = prev.length >= MAX_MESSAGES_PER_SESSION
      ? [...prev.slice(prev.length - MAX_MESSAGES_PER_SESSION + 1), msg]
      : [...prev, msg]
    messagesBySession.value = { ...messagesBySession.value, [sKey]: next }
  }

  function ensureStreamingAssistantMessage(
    sKey: string,
    nodeId: string,
    provider: AdapterProvider,
    runId?: string,
    requestId?: string,
  ): ChatMessage {
    const list = [...(messagesBySession.value[sKey] ?? [])]
    let idx = list.findIndex(
      m => m.role === 'assistant' && m.streaming && (!runId || m.runId === runId),
    )
    if (idx === -1 && requestId) {
      idx = list.findIndex(m => m.role === 'assistant' && m.requestId === requestId)
    }
    if (idx === -1) {
      const created: ChatMessage = {
        id: `msg-${createRequestId()}`,
        role: 'assistant',
        runId,
        requestId,
        nodeId,
        provider,
        text: '',
        thought: '',
        streaming: true,
        toolCalls: [],
        approvals: [],
        artifacts: [],
        createdAt: Date.now(),
      }
      list.push(created)
      messagesBySession.value = { ...messagesBySession.value, [sKey]: list.slice(-MAX_MESSAGES_PER_SESSION) }
      return created
    }
    return list[idx]
  }

  function updateAssistantMessage(
    sKey: string,
    nodeId: string,
    provider: AdapterProvider,
    runId: string | undefined,
    requestId: string | undefined,
    mutator: (msg: ChatMessage) => ChatMessage,
  ) {
    ensureStreamingAssistantMessage(sKey, nodeId, provider, runId, requestId)
    const list = [...(messagesBySession.value[sKey] ?? [])]
    let idx = list.findIndex(
      m => m.role === 'assistant' && m.streaming && (!runId || m.runId === runId),
    )
    if (idx === -1 && requestId) {
      idx = list.findIndex(m => m.role === 'assistant' && m.requestId === requestId)
    }
    if (idx === -1) {
      idx = list.length - 1
    }
    if (idx >= 0) {
      list[idx] = mutator(list[idx])
      messagesBySession.value = { ...messagesBySession.value, [sKey]: list }
    }
  }

  function autoPullSessionsForNode(node: AgentNode) {
    if (node.status !== 'online' || autoPulledNodes.has(node.id)) return
    const hasSessions = Object.values(sessionsByKey.value).some(s => s.nodeId === node.id)
    if (hasSessions) {
      autoPulledNodes.add(node.id)
      return
    }
    const readyAdapter = node.adapters.find(a => a.status === 'ready') ?? node.adapters[0]
    if (!readyAdapter || !readyAdapter.capabilities.includes('history')) return
    autoPulledNodes.add(node.id)
    requestSessionsList(node.id, readyAdapter.provider)
  }

  // ---------------- 事件归并（WS 增量 & 控制帧） ----------------
  function handleWsEvent(frame: FleetWsEvent) {
    const etype = frame.type

    if (etype === 'FleetSnapshot' && Array.isArray(frame.nodes)) {
      reconnectAttempt = 0
      wsState.value = 'online'
      lastError.value = null
      const onlineMap = new Map(frame.nodes.map(item => [((item as unknown as { nodeId?: string }).nodeId ?? item.id), item]))
      nodes.value = nodes.value.map(existing => {
        const live = onlineMap.get(existing.id)
        if (!live) {
          autoPulledNodes.delete(existing.id)
          return existing.status === 'revoked' ? existing : { ...existing, status: 'offline' }
        }
        return {
          ...existing,
          status: 'online',
          adapters: live.adapters ?? existing.adapters,
          allowedRoots: live.allowedRoots ?? existing.allowedRoots,
          transferEndpoints: live.transferEndpoints ?? existing.transferEndpoints,
        }
      })
      for (const n of nodes.value) {
        if (n.status === 'online') autoPullSessionsForNode(n)
      }
      return
    }

    if (etype === 'NodePresence' && frame.nodeId) {
      const liveStatus = (frame as unknown as { status?: string }).status ?? 'offline'
      if (liveStatus !== 'online') autoPulledNodes.delete(frame.nodeId)
      nodes.value = nodes.value.map(n => {
        if (n.id !== frame.nodeId) return n
        return {
          ...n,
          status: liveStatus,
          adapters: ((frame as unknown as { adapters?: AgentNode['adapters'] }).adapters) ?? n.adapters,
          allowedRoots: ((frame as unknown as { allowedRoots?: string[] }).allowedRoots) ?? n.allowedRoots,
          transferEndpoints: ((frame as unknown as { transferEndpoints?: AgentNode['transferEndpoints'] }).transferEndpoints) ?? n.transferEndpoints,
        }
      })
      const liveNode = nodes.value.find(n => n.id === frame.nodeId)
      if (liveNode && liveStatus === 'online') autoPullSessionsForNode(liveNode)
      return
    }

    if (frame.requestId && ['Failed', 'NodeUnavailable', 'Error'].includes(etype)) {
      const index = pendingOpenQueue.findIndex(p => p.requestId === frame.requestId)
      if (index >= 0) {
        pendingOpenQueue.splice(index, 1)
        lastError.value = frame.message || '无法创建会话'
        return
      }
    }
    const nodeId = frame.nodeId ?? selectedNode.value?.id ?? ''
    const provider = (frame.provider ?? selectedProvider.value) as AdapterProvider

    if (etype === 'ModelsSnapshot' && nodeId && Array.isArray(frame.models)) {
      catalogs.value[`${nodeId}::${provider}`] = { models: frame.models, message: frame.message }
      return
    }

    if (etype === 'SessionsSnapshot' && nodeId && Array.isArray(frame.sessions)) {
      const next = { ...sessionsByKey.value }
      for (const s of frame.sessions) {
        if (!s.sessionId) continue
        const p = (s.provider || provider) as AdapterProvider
        const k = sessionKey(nodeId, p, s.sessionId)
        next[k] = {
          sessionId: s.sessionId,
          nodeId,
          provider: p,
          title: s.title || s.sessionId,
          cwd: s.cwd || '',
        }
      }
      sessionsByKey.value = next
      return
    }

    if (etype === 'SessionOpened' && nodeId && frame.sessionId) {
      const k = sessionKey(nodeId, provider, frame.sessionId)
      sessionsByKey.value = {
        ...sessionsByKey.value,
        [k]: {
          sessionId: frame.sessionId,
          nodeId,
          provider,
          title: frame.title || `${provider} · ${frame.sessionId.slice(0, 8)}`,
          cwd: frame.cwd || '',
          worktreePath: frame.worktreePath ?? null,
        },
      }
      if (!messagesBySession.value[k]) {
        messagesBySession.value = { ...messagesBySession.value, [k]: [] }
      }
      const queuedIdx = pendingOpenQueue.findIndex(
        item => item.requestId === frame.requestId && item.nodeId === nodeId && item.provider === provider,
      )
      if (queuedIdx >= 0 && !pendingOpenQueue[queuedIdx].onOpened) activeSessionKey.value = k
      if (queuedIdx >= 0) {
        const [item] = pendingOpenQueue.splice(queuedIdx, 1)
        item.onOpened?.(k)
        if (item.options) runSettings.value[k] = { ...item.options }
        if (item.initialPrompt) {
          void sendPromptToSession(k, item.initialPrompt, item.initialAttachments ?? [], item.options)
        }
      }
      return
    }

    if (etype === 'SessionHistory' && nodeId && frame.sessionId && Array.isArray(frame.messages)) {
      const k = sessionKey(nodeId, provider, frame.sessionId)
      if (messagesBySession.value[k]?.length) return
      const hydrated: ChatMessage[] = frame.messages.map((m, idx) => ({
        id: `hist-${idx}-${Date.now()}`,
        role: m.role === 'user' ? 'user' : 'assistant',
        nodeId,
        provider,
        text: m.text ?? '',
        streaming: false,
        createdAt: Date.now(),
      }))
      messagesBySession.value = { ...messagesBySession.value, [k]: hydrated.slice(-MAX_MESSAGES_PER_SESSION) }
      return
    }

    // 以下事件均绑定到具体的 (nodeId, provider, sessionId)
    const sid = frame.sessionId
    const sKey = sid && nodeId
      ? (frame.provider ? sessionKey(nodeId, provider, sid) : Object.keys(sessionsByKey.value).find(
          k => k.endsWith(`::${sid}`) && k.startsWith(`${nodeId}::`),
        ) ?? sessionKey(nodeId, provider, sid))
      : activeSessionKey.value

    if (!sKey || !nodeId) {
      if (etype === 'Failed' || etype === 'NodeUnavailable' || etype === 'Error') {
        lastError.value = frame.message || '节点操作失败'
      }
      return
    }

    const effProvider = sessionsByKey.value[sKey]?.provider ?? provider

    if (etype === 'Accepted') {
      const rid = frame.runId || frame.requestId || createRequestId()
      if (frame.requestId && frame.runId && frame.runId !== frame.requestId) {
        const promptMeta = pendingRunPrompts.get(`${sKey}::${frame.requestId}`)
        if (promptMeta) pendingRunPrompts.set(`${sKey}::${frame.runId}`, promptMeta)
      }
      runningBySession.value = { ...runningBySession.value, [sKey]: rid }
      ensureStreamingAssistantMessage(sKey, nodeId, effProvider, rid, frame.requestId)
      return
    }

    if (etype === 'TokenUsage') {
      tokenUsageStateBySession.value = {
        ...tokenUsageStateBySession.value,
        [sKey]: applyTokenUsageEvent(tokenUsageStateBySession.value[sKey], frame),
      }
      return
    }

    if (etype === 'ThoughtDelta' && frame.text) {
      updateAssistantMessage(sKey, nodeId, effProvider, frame.runId, frame.requestId, msg => ({
        ...msg,
        thought: (msg.thought ?? '') + frame.text,
      }))
      return
    }

    if (etype === 'TextDelta' && frame.text) {
      updateAssistantMessage(sKey, nodeId, effProvider, frame.runId, frame.requestId, msg => ({
        ...msg,
        text: msg.text + frame.text,
      }))
      return
    }

    if (etype === 'ToolCall' && frame.name) {
      updateAssistantMessage(sKey, nodeId, effProvider, frame.runId, frame.requestId, msg => ({
        ...msg,
        toolCalls: [
          ...(msg.toolCalls ?? []),
          { id: `${Date.now()}-${Math.random()}`, name: frame.name!, detail: frame.detail },
        ],
      }))
      return
    }

    if (etype === 'PermissionRequest' && frame.callId) {
      const card: PermissionRequestCard = {
        callId: frame.callId,
        nodeId,
        sessionId: sid ?? sessionsByKey.value[sKey]?.sessionId ?? '',
        provider: effProvider,
        title: frame.title || '需要节点执行确认',
        command: frame.command || '',
        risk: frame.risk || 'medium',
        decision: 'pending',
        createdAt: Date.now(),
      }
      pendingApprovalsByCall.value = { ...pendingApprovalsByCall.value, [card.callId]: card }
      updateAssistantMessage(sKey, nodeId, effProvider, frame.runId, frame.requestId, msg => ({
        ...msg,
        approvals: [...(msg.approvals ?? []), card],
      }))
      return
    }

    if (etype === 'ArtifactOffered' && frame.artifact) {
      const artifact = frame.artifact
      updateAssistantMessage(sKey, nodeId, effProvider, frame.runId, frame.requestId, msg => ({
        ...msg,
        artifacts: [...(msg.artifacts ?? []), artifact],
      }))
      return
    }

    if (etype === 'Completed') {
      updateAssistantMessage(sKey, nodeId, effProvider, frame.runId, frame.requestId, msg => ({
        ...msg,
        streaming: false,
      }))
      const promptMeta =
        (frame.runId ? pendingRunPrompts.get(`${sKey}::${frame.runId}`) : undefined) ??
        (frame.requestId ? pendingRunPrompts.get(`${sKey}::${frame.requestId}`) : undefined)
      if (frame.usage && typeof frame.usage === 'object') {
        tokenUsageStateBySession.value = {
          ...tokenUsageStateBySession.value,
          [sKey]: applyTokenUsageEvent(tokenUsageStateBySession.value[sKey], {
            ...(frame.usage as TokenUsageInput),
            runId: frame.runId,
            requestId: frame.requestId,
          }),
        }
      } else if (!hasRecordedTurnUsage(tokenUsageStateBySession.value[sKey], [frame.runId, frame.requestId])) {
        const list = messagesBySession.value[sKey] ?? []
        const targetMsg = [...list].reverse().find(m =>
          m.role === 'assistant'
          && ((frame.runId && m.runId === frame.runId) || (frame.requestId && m.requestId === frame.requestId) || !m.streaming),
        )
        const promptText = promptMeta?.text ?? ''
        const replyText = targetMsg?.text ?? ''
        const thoughtText = targetMsg?.thought ?? ''
        if (promptText || replyText || thoughtText) {
          tokenUsageStateBySession.value = {
            ...tokenUsageStateBySession.value,
            [sKey]: applyTokenUsageEvent(
              tokenUsageStateBySession.value[sKey],
              estimateTurnUsageFallback(promptText, thoughtText, replyText, {
                model: promptMeta?.model || runSettings.value[sKey]?.model,
                runId: frame.runId,
                requestId: frame.requestId,
              }),
            ),
          }
        }
      }
      if (frame.runId) pendingRunPrompts.delete(`${sKey}::${frame.runId}`)
      if (frame.requestId) pendingRunPrompts.delete(`${sKey}::${frame.requestId}`)
      const copy = { ...runningBySession.value }
      delete copy[sKey]
      runningBySession.value = copy
      return
    }

    if (etype === 'Failed' || etype === 'NodeUnavailable' || etype === 'Error') {
      const errText = frame.message || frame.code || '执行失败'
      lastError.value = errText
      updateAssistantMessage(sKey, nodeId, effProvider, frame.runId, frame.requestId, msg => ({
        ...msg,
        streaming: false,
        error: errText,
      }))
      if (frame.runId) pendingRunPrompts.delete(`${sKey}::${frame.runId}`)
      if (frame.requestId) pendingRunPrompts.delete(`${sKey}::${frame.requestId}`)
      const copy = { ...runningBySession.value }
      delete copy[sKey]
      runningBySession.value = copy
    }
  }

  // ---------------- 会话控制动作 ----------------
  function selectNode(nodeId: string) {
    selectedNodeId.value = nodeId
    const found = nodes.value.find(n => n.id === nodeId)
    if (found) syncProviderForNode(found)
    const firstSess = Object.entries(sessionsByKey.value).find(([, s]) => s.nodeId === nodeId)?.[0]
    activeSessionKey.value = firstSess ?? ''
  }

  function selectProvider(provider: AdapterProvider) {
    selectedProvider.value = provider
    const nid = selectedNode.value?.id
    if (!nid) return
    const match = Object.entries(sessionsByKey.value).find(
      ([, s]) => s.nodeId === nid && s.provider === provider,
    )?.[0]
    activeSessionKey.value = match ?? ''
  }

  function requestSessionsList(nodeId?: string, provider?: AdapterProvider) {
    const nid = nodeId ?? selectedNode.value?.id
    const prov = provider ?? selectedProvider.value
    if (!nid) return
    sendWsCommand({
      type: 'sessions.list',
      nodeId: nid,
      provider: prov,
      requestId: createRequestId(),
    })
  }

  function openSession(options: {
    nodeId?: string
    provider?: AdapterProvider
    cwd?: string
    sessionId?: string
    requestId?: string
    onOpened?: (key: string) => void
    useWorktree?: boolean
  } = {}) {
    const nid = options.nodeId ?? selectedNode.value?.id
    if (!nid) throw new Error('请先选择控制节点')
    const node = nodes.value.find(n => n.id === nid)
    const prov = options.provider ?? selectedProvider.value
    const cwd = options.cwd ?? node?.allowedRoots[0] ?? ''
    const requestId = options.requestId ?? createRequestId()
    if (!pendingOpenQueue.some(p => p.requestId === requestId)) pendingOpenQueue.push({ nodeId: nid, provider: prov, requestId, onOpened: options.onOpened })
    const sent = sendWsCommand({
      type: 'session.open',
      nodeId: nid,
      provider: prov,
      ...(cwd ? { cwd } : {}),
      ...(options.sessionId ? { sessionId: options.sessionId } : {}),
      useWorktree: Boolean(options.useWorktree),
      requestId,
    })
    if (!sent) {
      const i = pendingOpenQueue.findIndex(p => p.requestId === requestId)
      if (i >= 0) pendingOpenQueue.splice(i, 1)
      throw new Error(lastError.value || '节点连接不可用')
    }
  }

  function activateSession(sKey: string) {
    activeSessionKey.value = sKey
    const sess = sessionsByKey.value[sKey]
    if (sess) {
      selectedNodeId.value = sess.nodeId
      selectedProvider.value = sess.provider
      loadSessionHistory(sKey)
    }
  }

  function loadSessionHistory(sKey: string) {
    const sess = sessionsByKey.value[sKey]
    if (sess && !messagesBySession.value[sKey]?.length) {
      sendWsCommand({ type: 'session.history', nodeId: sess.nodeId, provider: sess.provider,
        sessionId: sess.sessionId, limit: 50, requestId: createRequestId() })
    }
  }

  async function sendPromptToSession(
    sKey: string,
    text: string,
    attachments: ArtifactRef[] = [],
    options?: RunOptions,
  ) {
    const sess = sessionsByKey.value[sKey]
    if (!sess) throw new Error('目标会话不存在')
    const reqId = createRequestId()
    if (sentRequestIds.has(reqId)) return
    sentRequestIds.add(reqId)

    const sent = sendWsCommand({
      type: 'prompt.send',
      options,
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      text,
      attachments: attachments.length ? attachments : undefined,
      requestId: reqId,
    })
    if (!sent) throw new Error(lastError.value || '节点连接不可用')
    pendingRunPrompts.set(`${sKey}::${reqId}`, { text, model: options?.model })

    appendMessage(sKey, {
      id: `user-${reqId}`,
      role: 'user',
      requestId: reqId,
      nodeId: sess.nodeId,
      provider: sess.provider,
      text,
      artifacts: attachments.length ? attachments : undefined,
      createdAt: Date.now(),
    })
  }

  async function uploadFilesWithPreview(files: File[]): Promise<ArtifactRef[]> {
    const uploadedRefs: ArtifactRef[] = []
    if (!files.length || !auth.token) return uploadedRefs
    const apiBaseUrl = getApiBaseUrl()
    const nextPreviews: Record<string, string> = {}
    for (const file of files) {
      const ref = await encryptAndUploadFile({ file, token: auth.token, apiBaseUrl })
      uploadedRefs.push(ref)
      if (
        file.type.startsWith('image/')
        && typeof URL !== 'undefined'
        && typeof URL.createObjectURL === 'function'
      ) {
        nextPreviews[ref.artifactId] = URL.createObjectURL(file)
      }
    }
    if (Object.keys(nextPreviews).length) {
      imagePreviewByArtifactId.value = { ...imagePreviewByArtifactId.value, ...nextPreviews }
    }
    return uploadedRefs
  }

  async function sendPromptToSpecificSession(sKey: string, text: string, files: File[] = [], options?: RunOptions) {
    const clean = text.trim()
    if (!clean && !files.length) return
    const uploadedRefs = await uploadFilesWithPreview(files)
    await sendPromptToSession(sKey, clean || '[发送了加密文件附件]', uploadedRefs, options)
  }

  async function sendPrompt(text: string, files: File[] = [], options?: RunOptions) {
    const clean = text.trim()
    if (!clean && !files.length) return
    const nid = selectedNode.value?.id
    if (!nid) throw new Error('当前没有可用的节点')
    const targetKey = activeSessionKey.value
    const prov = selectedProvider.value

    const uploadedRefs = await uploadFilesWithPreview(files)

    if (targetKey && sessionsByKey.value[targetKey]) {
      await sendPromptToSession(targetKey, clean || '[发送了加密文件附件]', uploadedRefs, options)
      return
    }

    // 尚无活跃会话时，自动为当前节点 + Provider 打开会话并在 SessionOpened 后发出首条消息
    const requestId = createRequestId()
    pendingOpenQueue.push({
      requestId, options,
      nodeId: nid,
      provider: prov,
      initialPrompt: clean || '[发送了加密文件附件]',
      initialAttachments: uploadedRefs.length ? uploadedRefs : undefined,
    })
    openSession({ nodeId: nid, provider: prov, requestId })
  }

  function cancelSessionRun(sKey?: string) {
    const targetKey = sKey || activeSessionKey.value
    if (!targetKey) return
    const sess = sessionsByKey.value[targetKey]
    const runId = runningBySession.value[targetKey]
    if (!sess) return
    sendWsCommand({
      type: 'prompt.cancel',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      ...(runId ? { runId } : {}),
      requestId: createRequestId(),
    })
  }

  function cancelActiveRun() {
    cancelSessionRun(activeSessionKey.value)
  }

  function respondPermission(callId: string, decision: ApprovalDecision) {
    const card = pendingApprovalsByCall.value[callId]
    if (!card) return
    const updatedCard: PermissionRequestCard = { ...card, decision }
    pendingApprovalsByCall.value = { ...pendingApprovalsByCall.value, [callId]: updatedCard }

    const sKey = sessionKey(card.nodeId, card.provider, card.sessionId)
    const list = messagesBySession.value[sKey]
    if (list) {
      messagesBySession.value = {
        ...messagesBySession.value,
        [sKey]: list.map(m =>
          m.approvals?.some(a => a.callId === callId)
            ? {
                ...m,
                approvals: m.approvals.map(a => (a.callId === callId ? updatedCard : a)),
              }
            : m,
        ),
      }
    }

    sendWsCommand({
      type: 'permission.respond',
      nodeId: card.nodeId,
      provider: card.provider,
      callId,
      decision,
    })
  }

  function sendHandoff(options: {
    targetNodeId: string
    targetProvider: AdapterProvider
    targetSessionId?: string
    summary: string
    artifact?: ArtifactRef
  }) {
    const targetKey = options.targetSessionId
      ? sessionKey(options.targetNodeId, options.targetProvider, options.targetSessionId)
      : Object.entries(sessionsByKey.value).find(
          ([, s]) => s.nodeId === options.targetNodeId && s.provider === options.targetProvider,
        )?.[0]

    const sid = options.targetSessionId ?? (targetKey ? sessionsByKey.value[targetKey]?.sessionId : undefined)
    if (!sid) {
      const requestId = createRequestId()
      pendingOpenQueue.push({
        requestId,
        nodeId: options.targetNodeId,
        provider: options.targetProvider,
        initialPrompt: options.summary,
        initialAttachments: options.artifact ? [options.artifact] : undefined,
      })
      openSession({ nodeId: options.targetNodeId, provider: options.targetProvider, requestId })
      return
    }

    const reqId = createRequestId()
    sendWsCommand({
      type: 'handoff.send',
      nodeId: options.targetNodeId,
      provider: options.targetProvider,
      sessionId: sid,
      summary: options.summary,
      ...(options.artifact ? { artifact: options.artifact } : {}),
      requestId: reqId,
    })
    if (targetKey) {
      appendMessage(targetKey, {
        id: `handoff-${reqId}`,
        role: 'user',
        requestId: reqId,
        nodeId: options.targetNodeId,
        provider: options.targetProvider,
        text: `@Handoff · ${options.summary}`,
        artifacts: options.artifact ? [options.artifact] : undefined,
        createdAt: Date.now(),
      })
      activeSessionKey.value = targetKey
    }
  }

  /**
   * 群发对比（Fan-out）：同时向多个在线（nodeId, provider）派发同一指令，便于并行横向对比。
   */
  async function sendFanout(
    targets: Array<{ nodeId: string; provider: AdapterProvider }>,
    text: string,
    onTarget?: (key: string, index: number) => void,
  ) {
    const clean = text.trim()
    if (!clean) return
    for (const [index, target] of targets.entries()) {
      const existingEntry = Object.entries(sessionsByKey.value).find(
        ([, s]) => s.nodeId === target.nodeId && s.provider === target.provider,
      )
      if (existingEntry) {
        onTarget?.(existingEntry[0], index)
        await sendPromptToSession(existingEntry[0], clean)
      } else {
        const requestId = createRequestId()
        pendingOpenQueue.push({ ...target, requestId, initialPrompt: clean, onOpened: onTarget ? key => onTarget(key, index) : undefined })
        openSession({ ...target, requestId })
      }
    }
  }

  async function downloadArtifactToBrowser(artifact: ArtifactRef) {
    if (!auth.token) throw new Error('尚未登录')
    const { blob, transport, fileName } = await downloadAndDecryptBlob({
      artifact,
      token: auth.token,
      apiBaseUrl: getApiBaseUrl(),
    })
    const url = URL.createObjectURL(blob)
    try {
      const a = document.createElement('a')
      a.href = url
      a.download = fileName
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
    } finally {
      URL.revokeObjectURL(url)
    }
    return transport
  }

  return {
    nodes,
    nodesLoading,
    lastError,
    wsState,
    selectedNodeId,
    selectedNode,
    selectedProvider,
    availableProviders,
    activeSessionKey,
    sessionsByKey,
    allSessions,
    sessionsForCurrentNode,
    currentSession,
    messagesBySession,
    currentMessages,
    pendingApprovalsList,
    nodesWithApprovalPending,
    runningBySession,
    currentIsStreaming,
    clearSessionMemory,
    loadNodes,
    registerNode,
    rotateNode,
    revokeNode,
    removeNode,
    connectSocket,
    disconnectSocket,
    handleWsEvent,
    selectNode,
    selectProvider,
    composerDrafts,
    runSettings,
    catalogs,
    tokenUsageBySession,
    imagePreviewByArtifactId,
    requestModels(nodeId: string, provider: AdapterProvider) {
      return sendWsCommand({ type: 'models.list', nodeId, provider, requestId: createRequestId() })
    },
    requestSessionsList,
    openSession,
    activateSession,
    loadSessionHistory,
    sendPromptToSpecificSession,
    sendPrompt,
    cancelSessionRun,
    cancelActiveRun,
    respondPermission,
    sendHandoff,
    sendFanout,
    downloadArtifactToBrowser,
  }
})
