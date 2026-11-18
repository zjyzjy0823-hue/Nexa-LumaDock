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
  AgentModeOption,
  AgentNode,
  ApprovalDecision,
  ArtifactRef,
  ChatMessage,
  ChatSession,
  CheckpointInfo,
  DiffFileEntry,
  FilePreviewState,
  FleetConnectionState,
  FleetWsEvent,
  FleetModel,
  McpServerInfo,
  MessageFormRequest,
  QueuedPromptItem,
  RunOptions,
  NodePlatform,
  NodeTokenOut,
  PermissionRequestCard,
  SessionDiffState,
  SessionTokenUsage,
  TerminalSessionState,
  TodoItem,
  WorkspaceRule,
  WorkspaceTreeEntry,
} from '../types/fleet'
import { buildSessionHtmlReport } from '../services/htmlExport'
import {
  appendMessagePart,
  branchFromUserMessage,
  buildSessionMarkdown,
  mergeToolCallUpdate,
  switchMessageBranch,
} from '../services/chatHelpers'
import {
  applyTokenUsageEvent,
  estimateTurnUsageFallback,
  hasRecordedTurnUsage,
  toSessionTokenSummary,
  type SessionTokenState,
  type TokenUsageInput,
} from '../services/tokenUsage'
import { resolveSavedModelPref, saveAgentModelPref } from '../services/modelPrefs'
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
  const agentsByTarget = ref<Record<string, AgentModeOption[]>>({})
  const mcpByTarget = ref<Record<string, McpServerInfo[]>>({})
  const rulesByTarget = ref<Record<string, WorkspaceRule[]>>({})
  const filePreviewBySession = ref<Record<string, FilePreviewState>>({})
  const fileTextCacheBySession = ref<Record<string, Record<string, string[]>>>({})
  const silentFileReadRequests = new Set<string>()
  const pendingFormsById = ref<Record<string, MessageFormRequest>>({})
  const treeCacheByTarget = ref<Record<string, WorkspaceTreeEntry[]>>({})
  const trustPatternsByNode = ref<Record<string, string[]>>({})
  const terminalBySession = ref<Record<string, TerminalSessionState>>({})
  const bookmarkedIdsBySession = ref<Record<string, string[]>>({})
  const notificationsEnabled = ref(
    typeof window !== 'undefined' && typeof Notification !== 'undefined' && Notification.permission === 'granted',
  )
  const unreadNotifyTitle = ref('')
  const tokenUsageStateBySession = ref<Record<string, SessionTokenState>>({})
  const todosBySession = ref<Record<string, TodoItem[]>>({})
  const diffBySession = ref<Record<string, SessionDiffState>>({})
  const checkpointsBySession = ref<Record<string, CheckpointInfo[]>>({})
  const filesCacheByTarget = ref<Record<string, string[]>>({})
  const queuedPromptsBySession = ref<Record<string, QueuedPromptItem[]>>({})
  const imagePreviewByArtifactId = ref<Record<string, string>>({})
  const pendingRunPrompts = new Map<string, { text: string; model?: string }>()
  const autoPulledNodes = new Set<string>()
  const sentRequestIds = new Set<string>()
  const steerSessionKeys = new Set<string>()
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

  const currentTodos = computed<TodoItem[]>(() =>
    activeSessionKey.value ? todosBySession.value[activeSessionKey.value] ?? [] : [],
  )

  const currentDiff = computed<SessionDiffState | null>(() =>
    activeSessionKey.value ? diffBySession.value[activeSessionKey.value] ?? null : null,
  )

  const currentCheckpoints = computed<CheckpointInfo[]>(() =>
    activeSessionKey.value ? checkpointsBySession.value[activeSessionKey.value] ?? [] : [],
  )

  const currentQueue = computed<QueuedPromptItem[]>(() =>
    activeSessionKey.value ? queuedPromptsBySession.value[activeSessionKey.value] ?? [] : [],
  )

  // ---------------- 内存清理（登出 / 切换工作区时必须彻底销毁正文与密钥） ----------------
  function clearSessionMemory() {
    disconnectSocket()
    sessionsByKey.value = {}
    messagesBySession.value = {}
    pendingApprovalsByCall.value = {}
    runningBySession.value = {}
    activeSessionKey.value = ''
    sentRequestIds.clear()
    steerSessionKeys.clear()
    composerDrafts.value = {}
    runSettings.value = {}
    catalogs.value = {}
    agentsByTarget.value = {}
    mcpByTarget.value = {}
    rulesByTarget.value = {}
    filePreviewBySession.value = {}
    fileTextCacheBySession.value = {}
    silentFileReadRequests.clear()
    pendingFormsById.value = {}
    treeCacheByTarget.value = {}
    trustPatternsByNode.value = {}
    terminalBySession.value = {}
    bookmarkedIdsBySession.value = {}
    unreadNotifyTitle.value = ''
    tokenUsageStateBySession.value = {}
    todosBySession.value = {}
    diffBySession.value = {}
    checkpointsBySession.value = {}
    filesCacheByTarget.value = {}
    queuedPromptsBySession.value = {}
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
      if (activeSessionKey.value) {
        subscribeSession(activeSessionKey.value)
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
      applyDefaultModelPref(`${nodeId}::${provider}`, nodeId, provider)
      for (const [k, s] of Object.entries(sessionsByKey.value)) {
        if (s.nodeId === nodeId && s.provider === provider) {
          applyDefaultModelPref(k, nodeId, provider)
        }
      }
      return
    }

    if (etype === 'AgentsSnapshot' && nodeId && Array.isArray(frame.agents)) {
      agentsByTarget.value = { ...agentsByTarget.value, [`${nodeId}::${provider}`]: frame.agents }
      return
    }

    if (etype === 'McpSnapshot' && nodeId && Array.isArray(frame.servers)) {
      mcpByTarget.value = { ...mcpByTarget.value, [`${nodeId}::${provider}`]: frame.servers }
      return
    }

    if (etype === 'RulesSnapshot' && nodeId && Array.isArray(frame.rules)) {
      const target = frame.sessionId ? sessionKey(nodeId, provider, frame.sessionId) : `${nodeId}::${provider}`
      rulesByTarget.value = {
        ...rulesByTarget.value,
        [`${nodeId}::${provider}`]: frame.rules,
        [target]: frame.rules,
      }
      return
    }

    if (etype === 'FilesSnapshot' && nodeId && Array.isArray(frame.files)) {
      const filePaths = (frame.files as unknown[]).filter((x): x is string => typeof x === 'string')
      const nextCache = {
        ...filesCacheByTarget.value,
        [`${nodeId}::${provider}`]: filePaths,
      }
      if (frame.sessionId) {
        nextCache[sessionKey(nodeId, provider, frame.sessionId)] = filePaths
      }
      filesCacheByTarget.value = nextCache
      return
    }

    if (etype === 'FilesTreeSnapshot' && nodeId && Array.isArray(frame.entries)) {
      const relDir = frame.relDir || ''
      const scopeKey = frame.sessionId
        ? `${nodeId}::${provider}::${frame.sessionId}::${relDir}`
        : `${nodeId}::${provider}::${relDir}`
      treeCacheByTarget.value = {
        ...treeCacheByTarget.value,
        [scopeKey]: frame.entries,
        [`${nodeId}::${provider}::${relDir}`]: frame.entries,
      }
      return
    }

    if (etype === 'TrustPolicySnapshot' && nodeId && Array.isArray(frame.patterns)) {
      trustPatternsByNode.value = {
        ...trustPatternsByNode.value,
        [nodeId]: frame.patterns,
      }
      return
    }

    if (etype === 'SessionsSnapshot' && nodeId && Array.isArray(frame.sessions)) {
      const next = { ...sessionsByKey.value }
      const added: Array<{ k: string; p: AdapterProvider }> = []
      for (const s of frame.sessions) {
        if (!s.sessionId) continue
        const p = (s.provider || provider) as AdapterProvider
        const k = sessionKey(nodeId, p, s.sessionId)
        next[k] = {
          ...(next[k] ?? {}),
          sessionId: s.sessionId,
          nodeId,
          provider: p,
          title: s.title || s.sessionId,
          cwd: s.cwd || '',
        }
        added.push({ k, p })
      }
      sessionsByKey.value = next
      for (const item of added) {
        applyDefaultModelPref(item.k, nodeId, item.p)
      }
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
        if (!runSettings.value[k]?.model && runSettings.value[k]?.model !== '') {
          applyDefaultModelPref(k, nodeId, provider)
        }
        if (item.initialPrompt) {
          void sendPromptToSession(k, item.initialPrompt, item.initialAttachments ?? [], item.options ?? runSettings.value[k])
        }
      } else {
        applyDefaultModelPref(k, nodeId, provider)
      }
      return
    }

    if (etype === 'SessionHistory' && nodeId && frame.sessionId && Array.isArray(frame.messages)) {
      const k = sessionKey(nodeId, provider, frame.sessionId)
      if (messagesBySession.value[k]?.length) return
      const hydrated: ChatMessage[] = frame.messages.map((m, idx) => {
        const mappedTools = Array.isArray(m.toolCalls) && m.toolCalls.length
          ? m.toolCalls.map((tc, tIdx) => ({
              id: tc.callId || tc.id || `hist-tc-${idx}-${tIdx}`,
              callId: tc.callId,
              name: tc.name || 'tool',
              title: tc.title || tc.detail || tc.name,
              detail: tc.detail,
              status: tc.status || 'completed',
              input: tc.input,
              output: tc.output,
              error: tc.error,
              durationMs: tc.durationMs,
              subagentSessionId: tc.subagentSessionId,
            }))
          : undefined
        const mappedParts = Array.isArray(m.parts) && m.parts.length
          ? m.parts.reduce<import('../types/fleet').MessagePart[]>((acc, p) => {
              if (p.type === 'thought' && p.text) return appendMessagePart(acc, { type: 'thought', text: p.text })
              if (p.type === 'text' && p.text) return appendMessagePart(acc, { type: 'text', text: p.text })
              if (p.type === 'tool' && (p.callId || p.id)) return appendMessagePart(acc, { type: 'tool', callId: p.callId || p.id! })
              return acc
            }, [])
          : undefined
        return {
          id: `hist-${idx}-${Date.now()}`,
          role: m.role === 'user' ? 'user' : 'assistant',
          nodeId,
          provider,
          text: m.text ?? '',
          ...(m.thought ? { thought: m.thought } : {}),
          ...(mappedTools ? { toolCalls: mappedTools } : {}),
          ...(mappedParts?.length ? { parts: mappedParts } : {}),
          streaming: false,
          createdAt: Date.now(),
        }
      })
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

    if (etype === 'SessionStreamReplay' && sid && Array.isArray(frame.events)) {
      if (frame.active && frame.events.length) {
        // 断线/刷新重连时先清理该会话未闭合的半截流式占位，避免回放重放重复拼接
        const prevMsgs = messagesBySession.value[sKey] ?? []
        const trimmed = prevMsgs.filter(m => !(m.role === 'assistant' && m.streaming))
        if (trimmed.length !== prevMsgs.length) {
          messagesBySession.value = { ...messagesBySession.value, [sKey]: trimmed }
        }
        for (const sub of frame.events) {
          handleWsEvent({ ...sub, nodeId, provider: effProvider, sessionId: sid })
        }
      }
      return
    }

    if (etype === 'FileContentSnapshot' && frame.path) {
      if (!frame.isBinary && typeof frame.content === 'string') {
        const lines = frame.content.replace(/\r\n/g, '\n').split('\n')
        fileTextCacheBySession.value = {
          ...fileTextCacheBySession.value,
          [sKey]: {
            ...(fileTextCacheBySession.value[sKey] ?? {}),
            [frame.path]: lines,
          },
        }
      }
      if (frame.requestId && silentFileReadRequests.has(frame.requestId)) {
        silentFileReadRequests.delete(frame.requestId)
        return
      }
      const existing = filePreviewBySession.value[sKey]
      filePreviewBySession.value = {
        ...filePreviewBySession.value,
        [sKey]: {
          path: frame.path,
          language: frame.language || '',
          content: frame.content || '',
          lineCount: frame.lineCount || 0,
          truncated: Boolean(frame.truncated),
          sizeBytes: frame.sizeBytes || 0,
          isBinary: Boolean(frame.isBinary),
          loading: false,
          highlightLine: existing?.path === frame.path ? existing.highlightLine : undefined,
          updatedAt: Date.now(),
        },
      }
      return
    }

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
      const deltaText = frame.text
      updateAssistantMessage(sKey, nodeId, effProvider, frame.runId, frame.requestId, msg => ({
        ...msg,
        thought: (msg.thought ?? '') + deltaText,
        parts: appendMessagePart(msg.parts, { type: 'thought', text: deltaText }),
      }))
      return
    }

    if (etype === 'TextDelta' && frame.text) {
      const deltaText = frame.text
      updateAssistantMessage(sKey, nodeId, effProvider, frame.runId, frame.requestId, msg => ({
        ...msg,
        text: msg.text + deltaText,
        parts: appendMessagePart(msg.parts, { type: 'text', text: deltaText }),
      }))
      return
    }

    if ((etype === 'ToolCall' || etype === 'ToolCallUpdate') && (frame.name || frame.callId)) {
      const callKey = frame.callId || `legacy-${frame.name || 'tool'}`
      updateAssistantMessage(sKey, nodeId, effProvider, frame.runId, frame.requestId, msg => ({
        ...msg,
        toolCalls: mergeToolCallUpdate(msg.toolCalls, frame),
        parts: appendMessagePart(msg.parts, { type: 'tool', callId: callKey }),
      }))
      return
    }

    if (etype === 'FormRequest' && frame.formId) {
      const formCard: MessageFormRequest = {
        formId: frame.formId,
        nodeId,
        sessionId: sid ?? sessionsByKey.value[sKey]?.sessionId ?? '',
        provider: effProvider,
        title: frame.title || '需要补充确认信息',
        fields: Array.isArray(frame.fields) ? frame.fields : [],
        status: 'pending',
        createdAt: Date.now(),
      }
      pendingFormsById.value = { ...pendingFormsById.value, [formCard.formId]: formCard }
      updateAssistantMessage(sKey, nodeId, effProvider, frame.runId, frame.requestId, msg => {
        const prev = msg.forms ?? []
        const exists = prev.some(f => f.formId === formCard.formId)
        return {
          ...msg,
          forms: exists ? prev.map(f => (f.formId === formCard.formId ? formCard : f)) : [...prev, formCard],
        }
      })
      notifyBackgroundEvent('Studiolo 智能体提问', formCard.title)
      return
    }

    if (etype === 'FormResolved' && frame.formId) {
      const nextStatus = frame.cancelled ? 'cancelled' : 'submitted'
      const cur = pendingFormsById.value[frame.formId]
      if (cur) {
        pendingFormsById.value = { ...pendingFormsById.value, [frame.formId]: { ...cur, status: nextStatus } }
      }
      const list = messagesBySession.value[sKey]
      if (list) {
        messagesBySession.value = {
          ...messagesBySession.value,
          [sKey]: list.map(m =>
            m.forms?.some(f => f.formId === frame.formId)
              ? { ...m, forms: m.forms.map(f => (f.formId === frame.formId ? { ...f, status: nextStatus } : f)) }
              : m,
          ),
        }
      }
      return
    }

    if (etype === 'WorktreeMerged') {
      const count = Array.isArray(frame.mergedFiles) ? frame.mergedFiles.length : 0
      const detail = count > 0 ? frame.mergedFiles!.join(', ') : (frame.message || '无待合并改动')
      appendMessage(sKey, {
        id: `sys-wt-${Date.now()}`,
        role: 'system',
        nodeId,
        provider: effProvider,
        text: count > 0 ? `Worktree 合并完成：已将 ${count} 个文件改动合回主工作区（${detail}）` : detail,
        createdAt: Date.now(),
      })
      requestSessionDiff(sKey)
      return
    }

    if (etype === 'GitCommitted') {
      appendMessage(sKey, {
        id: `sys-gc-${Date.now()}`,
        role: 'system',
        nodeId,
        provider: effProvider,
        text: `已创建 Git 提交 ${frame.commitHash || ''}：${frame.message || ''}`,
        createdAt: Date.now(),
      })
      requestSessionDiff(sKey)
      return
    }

    if (etype === 'TerminalOpened' && frame.terminalId) {
      terminalBySession.value = {
        ...terminalBySession.value,
        [sKey]: {
          terminalId: frame.terminalId,
          sessionId: sid ?? '',
          cwd: frame.cwd || '',
          output: '',
          closed: false,
        },
      }
      return
    }

    if (etype === 'TerminalOutput' && frame.terminalId && typeof frame.data === 'string') {
      const cur = terminalBySession.value[sKey]
      if (cur && cur.terminalId === frame.terminalId) {
        const combined = `${cur.output}${frame.data}`
        terminalBySession.value = {
          ...terminalBySession.value,
          [sKey]: {
            ...cur,
            output: combined.length > 80000 ? combined.slice(combined.length - 80000) : combined,
          },
        }
      }
      return
    }

    if (etype === 'TerminalClosed' && frame.terminalId) {
      const cur = terminalBySession.value[sKey]
      if (cur && cur.terminalId === frame.terminalId) {
        terminalBySession.value = {
          ...terminalBySession.value,
          [sKey]: {
            ...cur,
            closed: true,
            exitCode: frame.exitCode,
          },
        }
      }
      return
    }

    if (etype === 'TodoUpdated' && Array.isArray(frame.items)) {
      todosBySession.value = { ...todosBySession.value, [sKey]: frame.items }
      if (sessionsByKey.value[sKey]) {
        sessionsByKey.value = {
          ...sessionsByKey.value,
          [sKey]: {
            ...sessionsByKey.value[sKey],
            todoCount: frame.items.filter(t => t.status !== 'completed' && t.status !== 'cancelled').length,
          },
        }
      }
      return
    }

    if (etype === 'CheckpointCreated' && frame.checkpointId) {
      const cpInfo: CheckpointInfo = {
        checkpointId: frame.checkpointId,
        sessionId: sid ?? sessionsByKey.value[sKey]?.sessionId ?? '',
        runId: frame.runId,
        requestId: frame.requestId,
        summary: frame.summary ?? { filesChanged: 0, additions: 0, deletions: 0 },
        createdAt: Date.now(),
      }
      checkpointsBySession.value = {
        ...checkpointsBySession.value,
        [sKey]: [...(checkpointsBySession.value[sKey] ?? []), cpInfo],
      }
      const list = [...(messagesBySession.value[sKey] ?? [])]
      const targetIdx = list.findIndex(
        m => m.role === 'assistant' && ((frame.runId && m.runId === frame.runId) || (frame.requestId && m.requestId === frame.requestId)),
      )
      const fallbackIdx = targetIdx >= 0 ? targetIdx : [...list].reverse().findIndex(m => m.role === 'assistant')
      const resolvedIdx = targetIdx >= 0 ? targetIdx : (fallbackIdx >= 0 ? list.length - 1 - fallbackIdx : -1)
      if (resolvedIdx >= 0) {
        list[resolvedIdx] = {
          ...list[resolvedIdx],
          checkpointId: frame.checkpointId,
          diffSummary: cpInfo.summary,
        }
        messagesBySession.value = { ...messagesBySession.value, [sKey]: list }
      }
      return
    }

    if (etype === 'DiffSnapshot') {
      const files = Array.isArray(frame.files)
        ? (frame.files.filter(x => typeof x === 'object' && x !== null) as DiffFileEntry[])
        : []
      const summary = frame.summary ?? {
        filesChanged: files.length,
        additions: files.reduce((acc, f) => acc + (f.additions || 0), 0),
        deletions: files.reduce((acc, f) => acc + (f.deletions || 0), 0),
      }
      diffBySession.value = {
        ...diffBySession.value,
        [sKey]: {
          files,
          summary,
          isGitRepo: frame.isGitRepo,
          cwd: frame.cwd,
          perTurn: frame.perTurn,
          updatedAt: Date.now(),
        },
      }
      if (fileTextCacheBySession.value[sKey]) {
        const nextTexts = { ...fileTextCacheBySession.value }
        delete nextTexts[sKey]
        fileTextCacheBySession.value = nextTexts
      }
      if (sessionsByKey.value[sKey]) {
        sessionsByKey.value = {
          ...sessionsByKey.value,
          [sKey]: { ...sessionsByKey.value[sKey], hasDiff: files.length > 0 },
        }
      }
      return
    }

    if (etype === 'CheckpointReverted' && frame.checkpointId) {
      const list = checkpointsBySession.value[sKey] ?? []
      checkpointsBySession.value = {
        ...checkpointsBySession.value,
        [sKey]: list.map(c => (c.checkpointId === frame.checkpointId ? { ...c, reverted: true } : c)),
      }
      const restored = frame.restoredFiles?.length ? frame.restoredFiles.join(', ') : '工作区快照'
      appendMessage(sKey, {
        id: `sys-rev-${Date.now()}`,
        role: 'system',
        nodeId,
        provider: effProvider,
        text: `已回滚检查点 ${frame.checkpointId}：已恢复 ${restored}`,
        createdAt: Date.now(),
      })
      return
    }

    if (etype === 'SessionRenamed' && frame.title) {
      if (sessionsByKey.value[sKey]) {
        sessionsByKey.value = {
          ...sessionsByKey.value,
          [sKey]: { ...sessionsByKey.value[sKey], title: frame.title },
        }
      }
      return
    }

    if (etype === 'SessionDeleted') {
      const nextSessions = { ...sessionsByKey.value }
      delete nextSessions[sKey]
      sessionsByKey.value = nextSessions
      const nextMsgs = { ...messagesBySession.value }
      delete nextMsgs[sKey]
      messagesBySession.value = nextMsgs
      const nextTodos = { ...todosBySession.value }
      delete nextTodos[sKey]
      todosBySession.value = nextTodos
      const nextDiffs = { ...diffBySession.value }
      delete nextDiffs[sKey]
      diffBySession.value = nextDiffs
      const nextCps = { ...checkpointsBySession.value }
      delete nextCps[sKey]
      checkpointsBySession.value = nextCps
      const nextQueues = { ...queuedPromptsBySession.value }
      delete nextQueues[sKey]
      queuedPromptsBySession.value = nextQueues
      const nextRunning = { ...runningBySession.value }
      delete nextRunning[sKey]
      runningBySession.value = nextRunning
      const nextPreviews = { ...filePreviewBySession.value }
      delete nextPreviews[sKey]
      filePreviewBySession.value = nextPreviews
      const nextTextCache = { ...fileTextCacheBySession.value }
      delete nextTextCache[sKey]
      fileTextCacheBySession.value = nextTextCache
      const nextTerms = { ...terminalBySession.value }
      delete nextTerms[sKey]
      terminalBySession.value = nextTerms
      const nextBm = { ...bookmarkedIdsBySession.value }
      delete nextBm[sKey]
      bookmarkedIdsBySession.value = nextBm
      if (activeSessionKey.value === sKey) {
        const sibling = Object.keys(nextSessions).find(k => nextSessions[k].nodeId === nodeId)
        activeSessionKey.value = sibling ?? Object.keys(nextSessions)[0] ?? ''
      }
      return
    }

    if (etype === 'SessionCompacted') {
      appendMessage(sKey, {
        id: `sys-cmp-${Date.now()}`,
        role: 'system',
        nodeId,
        provider: effProvider,
        text: frame.supported
          ? (frame.message || '已触发上游代理压缩会话历史上下文。')
          : (frame.message || '当前适配器暂不支持服务端上下文压缩。'),
        createdAt: Date.now(),
      })
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
      notifyBackgroundEvent('Studiolo 待执行审批', card.command || card.title)
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
      steerSessionKeys.delete(sKey)
      notifyBackgroundEvent(
        'Studiolo 任务已完成',
        sessionsByKey.value[sKey]?.title || '代理回复已就绪',
      )
      void drainNextQueuedPrompt(sKey)
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
      notifyBackgroundEvent('Studiolo 任务异常', errText)
      if (steerSessionKeys.has(sKey)) {
        steerSessionKeys.delete(sKey)
        void drainNextQueuedPrompt(sKey)
      }
    }
  }

  // ---------------- 会话控制动作 ----------------
  function selectNode(nodeId: string) {
    selectedNodeId.value = nodeId
    const found = nodes.value.find(n => n.id === nodeId)
    if (found) syncProviderForNode(found)
    const firstSess = Object.entries(sessionsByKey.value).find(([, s]) => s.nodeId === nodeId)?.[0]
    activeSessionKey.value = firstSess ?? ''
    if (firstSess && sessionsByKey.value[firstSess]) {
      const s = sessionsByKey.value[firstSess]
      applyDefaultModelPref(firstSess, s.nodeId, s.provider)
    } else if (found) {
      applyDefaultModelPref(`${found.id}::${selectedProvider.value}`, found.id, selectedProvider.value)
    }
  }

  function selectProvider(provider: AdapterProvider) {
    selectedProvider.value = provider
    const nid = selectedNode.value?.id
    if (!nid) return
    const match = Object.entries(sessionsByKey.value).find(
      ([, s]) => s.nodeId === nid && s.provider === provider,
    )?.[0]
    activeSessionKey.value = match ?? ''
    if (match) applyDefaultModelPref(match, nid, provider)
    else applyDefaultModelPref(`${nid}::${provider}`, nid, provider)
  }

  function applyDefaultModelPref(settingKey: string, nodeId: string, provider: AdapterProvider) {
    if (!settingKey || !nodeId) return
    const existing = runSettings.value[settingKey]
    if (existing && existing.model !== undefined) return
    const saved = resolveSavedModelPref(nodeId, provider)
    if (!saved?.model) return
    const cat = catalogs.value[`${nodeId}::${provider}`]
    if (cat?.models?.length) {
      const matched = cat.models.find(m => m.id === saved.model && !m.unavailable)
      if (!matched) return
    }
    runSettings.value = {
      ...runSettings.value,
      [settingKey]: {
        ...(existing ?? {}),
        model: saved.model,
        ...(saved.effort ? { effort: saved.effort } : {}),
      },
    }
  }

  function setModelPreference(
    nodeId: string | undefined,
    provider: AdapterProvider,
    model: string,
    effort?: string,
    settingKey?: string,
  ) {
    saveAgentModelPref({ nodeId, provider, model, effort })
    const cleanModel = model.trim()
    const targetDraftKey = nodeId ? `${nodeId}::${provider}` : ''
    const keysToUpdate = Array.from(new Set([settingKey, targetDraftKey].filter((k): k is string => Boolean(k))))
    if (!keysToUpdate.length) return
    const next = { ...runSettings.value }
    for (const k of keysToUpdate) {
      next[k] = {
        ...(next[k] ?? {}),
        model: cleanModel,
        effort: cleanModel && effort ? effort : undefined,
      }
    }
    runSettings.value = next
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
      applyDefaultModelPref(sKey, sess.nodeId, sess.provider)
      loadSessionHistory(sKey)
      subscribeSession(sKey)
      if (!diffBySession.value[sKey]) {
        requestSessionDiff(sKey)
      }
    }
  }

  function subscribeSession(sKey: string) {
    const sess = sessionsByKey.value[sKey]
    if (!sess || wsState.value !== 'online') return false
    return sendWsCommand({
      type: 'session.subscribe',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      requestId: createRequestId(),
    })
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
    appendUser = true,
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

    if (appendUser) {
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
  }

  async function drainNextQueuedPrompt(sKey: string) {
    const queue = queuedPromptsBySession.value[sKey]
    if (!queue?.length || runningBySession.value[sKey]) return
    const [nextItem, ...rest] = queue
    queuedPromptsBySession.value = { ...queuedPromptsBySession.value, [sKey]: rest }
    try {
      await sendPromptToSpecificSession(sKey, nextItem.text, nextItem.files ?? [], nextItem.options)
    } catch (err) {
      lastError.value = err instanceof Error ? err.message : '排队消息发送失败'
    }
  }

  function enqueuePrompt(sKey: string, text: string, files: File[] = [], options?: RunOptions): QueuedPromptItem | null {
    const clean = text.trim()
    if (!clean && !files.length) return null
    const item: QueuedPromptItem = {
      id: createRequestId(),
      text: clean || '[发送了加密文件附件]',
      files: files.length ? [...files] : undefined,
      options: options ? { ...options } : undefined,
      createdAt: Date.now(),
    }
    queuedPromptsBySession.value = {
      ...queuedPromptsBySession.value,
      [sKey]: [...(queuedPromptsBySession.value[sKey] ?? []), item],
    }
    return item
  }

  function removeQueuedPrompt(sKey: string, queueId: string) {
    const list = queuedPromptsBySession.value[sKey] ?? []
    queuedPromptsBySession.value = {
      ...queuedPromptsBySession.value,
      [sKey]: list.filter(i => i.id !== queueId),
    }
  }

  function updateQueuedPrompt(sKey: string, queueId: string, nextText: string) {
    const clean = nextText.trim()
    if (!clean) {
      removeQueuedPrompt(sKey, queueId)
      return
    }
    const list = queuedPromptsBySession.value[sKey] ?? []
    queuedPromptsBySession.value = {
      ...queuedPromptsBySession.value,
      [sKey]: list.map(i => (i.id === queueId ? { ...i, text: clean } : i)),
    }
  }

  function steerQueuedPrompt(sKey: string, queueId: string) {
    const list = queuedPromptsBySession.value[sKey] ?? []
    const idx = list.findIndex(i => i.id === queueId)
    if (idx < 0) return
    const target = list[idx]
    const reordered = [target, ...list.filter(i => i.id !== queueId)]
    queuedPromptsBySession.value = { ...queuedPromptsBySession.value, [sKey]: reordered }
    if (runningBySession.value[sKey]) {
      steerSessionKeys.add(sKey)
      cancelSessionRun(sKey)
    } else {
      void drainNextQueuedPrompt(sKey)
    }
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

  function requestFilesList(query = '', limit = 60, sKey?: string) {
    const key = sKey || activeSessionKey.value
    const sess = key ? sessionsByKey.value[key] : null
    const nid = sess?.nodeId ?? selectedNode.value?.id
    const prov = sess?.provider ?? selectedProvider.value
    if (!nid) return false
    return sendWsCommand({
      type: 'files.list',
      nodeId: nid,
      provider: prov,
      ...(sess ? { sessionId: sess.sessionId, cwd: sess.worktreePath || sess.cwd } : {}),
      query,
      limit,
      requestId: createRequestId(),
    })
  }

  function requestSessionDiff(sKey?: string, checkpointId?: string) {
    const key = sKey || activeSessionKey.value
    const sess = key ? sessionsByKey.value[key] : null
    if (!sess) return false
    return sendWsCommand({
      type: 'session.diff',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      ...(sess.worktreePath || sess.cwd ? { cwd: sess.worktreePath || sess.cwd } : {}),
      ...(checkpointId ? { checkpointId } : {}),
      requestId: createRequestId(),
    })
  }

  function revertCheckpoint(sKey: string, checkpointId?: string) {
    const sess = sessionsByKey.value[sKey]
    if (!sess) return false
    return sendWsCommand({
      type: 'checkpoint.revert',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      ...(checkpointId ? { checkpointId } : {}),
      requestId: createRequestId(),
    })
  }

  function requestAgents(nodeId: string, provider: AdapterProvider) {
    return sendWsCommand({ type: 'agents.list', nodeId, provider, requestId: createRequestId() })
  }

  function requestMcpServers(nodeId: string, provider: AdapterProvider) {
    return sendWsCommand({ type: 'mcp.list', nodeId, provider, requestId: createRequestId() })
  }

  function requestRules(sKey?: string) {
    const key = sKey || activeSessionKey.value
    const sess = key ? sessionsByKey.value[key] : null
    const nid = sess?.nodeId ?? selectedNode.value?.id
    const prov = sess?.provider ?? selectedProvider.value
    if (!nid) return false
    return sendWsCommand({
      type: 'rules.list',
      nodeId: nid,
      provider: prov,
      ...(sess ? { sessionId: sess.sessionId, cwd: sess.worktreePath || sess.cwd } : {}),
      requestId: createRequestId(),
    })
  }

  function requestFileContent(path: string, sKey?: string, highlightLine?: number) {
    const key = sKey || activeSessionKey.value
    const sess = key ? sessionsByKey.value[key] : null
    const clean = path.trim()
    if (!sess || !clean) return false
    filePreviewBySession.value = {
      ...filePreviewBySession.value,
      [key]: {
        path: clean,
        language: filePreviewBySession.value[key]?.path === clean ? filePreviewBySession.value[key].language : '',
        content: filePreviewBySession.value[key]?.path === clean ? filePreviewBySession.value[key].content : '',
        lineCount: filePreviewBySession.value[key]?.path === clean ? filePreviewBySession.value[key].lineCount : 0,
        truncated: false,
        sizeBytes: 0,
        isBinary: false,
        loading: true,
        highlightLine,
        updatedAt: Date.now(),
      },
    }
    return sendWsCommand({
      type: 'file.read',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      ...(sess.worktreePath || sess.cwd ? { cwd: sess.worktreePath || sess.cwd } : {}),
      path: clean,
      requestId: createRequestId(),
    })
  }

  function requestDiffFileContext(path: string, sKey?: string, force = false) {
    const key = sKey || activeSessionKey.value
    const sess = key ? sessionsByKey.value[key] : null
    const clean = path.trim()
    if (!sess || !clean) return false
    if (!force && fileTextCacheBySession.value[key]?.[clean]) return true
    const reqId = createRequestId()
    silentFileReadRequests.add(reqId)
    return sendWsCommand({
      type: 'file.read',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      ...(sess.worktreePath || sess.cwd ? { cwd: sess.worktreePath || sess.cwd } : {}),
      path: clean,
      requestId: reqId,
    })
  }

  function closeFilePreview(sKey?: string) {
    const key = sKey || activeSessionKey.value
    if (!key || !filePreviewBySession.value[key]) return
    const copy = { ...filePreviewBySession.value }
    delete copy[key]
    filePreviewBySession.value = copy
  }

  function revertFiles(sKey: string, paths: string[], checkpointId?: string) {
    const sess = sessionsByKey.value[sKey]
    if (!sess || !paths.length) return false
    return sendWsCommand({
      type: 'files.revert',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      paths,
      ...(checkpointId ? { checkpointId } : {}),
      requestId: createRequestId(),
    })
  }

  function mergeSessionWorktree(sKey?: string) {
    const key = sKey || activeSessionKey.value
    const sess = key ? sessionsByKey.value[key] : null
    if (!sess?.worktreePath) return false
    return sendWsCommand({
      type: 'worktree.merge',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      requestId: createRequestId(),
    })
  }

  function replyForm(formId: string, answer?: Record<string, unknown>, cancelled = false) {
    const form = pendingFormsById.value[formId]
    if (!form) return false
    const nextStatus = cancelled ? 'cancelled' : 'submitted'
    const updated: MessageFormRequest = { ...form, status: nextStatus, ...(answer ? { answer } : {}) }
    pendingFormsById.value = { ...pendingFormsById.value, [formId]: updated }
    const sKey = sessionKey(form.nodeId, form.provider, form.sessionId)
    const list = messagesBySession.value[sKey]
    if (list) {
      messagesBySession.value = {
        ...messagesBySession.value,
        [sKey]: list.map(m =>
          m.forms?.some(f => f.formId === formId)
            ? { ...m, forms: m.forms.map(f => (f.formId === formId ? updated : f)) }
            : m,
        ),
      }
    }
    return sendWsCommand({
      type: 'form.reply',
      nodeId: form.nodeId,
      provider: form.provider,
      sessionId: form.sessionId,
      formId,
      ...(answer ? { answer } : {}),
      cancelled,
      requestId: createRequestId(),
    })
  }

  function compactSession(sKey: string) {
    const sess = sessionsByKey.value[sKey]
    if (!sess) return false
    return sendWsCommand({
      type: 'session.compact',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      requestId: createRequestId(),
    })
  }

  function renameSession(sKey: string, title: string) {
    const sess = sessionsByKey.value[sKey]
    const clean = title.trim()
    if (!sess || !clean) return false
    sessionsByKey.value = {
      ...sessionsByKey.value,
      [sKey]: { ...sess, title: clean },
    }
    return sendWsCommand({
      type: 'session.rename',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      title: clean,
      requestId: createRequestId(),
    })
  }

  function deleteSession(sKey: string) {
    const sess = sessionsByKey.value[sKey]
    if (!sess) return false
    return sendWsCommand({
      type: 'session.delete',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      requestId: createRequestId(),
    })
  }

  async function editMessageAndBranch(
    sKey: string,
    userMsgIndex: number,
    nextUserText: string,
    options?: RunOptions,
  ) {
    const list = messagesBySession.value[sKey]
    if (!list) return
    const clean = nextUserText.trim()
    if (!clean) return
    const nextList = branchFromUserMessage(list, userMsgIndex, clean)
    messagesBySession.value = { ...messagesBySession.value, [sKey]: nextList }
    await sendPromptToSession(sKey, clean, [], options ?? runSettings.value[sKey], false)
  }

  async function regenerateAssistantMessage(sKey: string, assistantMsgIndex: number, options?: RunOptions) {
    const list = messagesBySession.value[sKey]
    if (!list || assistantMsgIndex <= 0) return
    let userIdx = assistantMsgIndex - 1
    while (userIdx >= 0 && list[userIdx].role !== 'user') {
      userIdx -= 1
    }
    if (userIdx < 0) return
    const userPrompt = list[userIdx].text
    await editMessageAndBranch(sKey, userIdx, userPrompt, options)
  }

  function switchBranch(sKey: string, anchorIndex: number, targetBranchIndex: number) {
    const list = messagesBySession.value[sKey]
    if (!list) return
    messagesBySession.value = {
      ...messagesBySession.value,
      [sKey]: switchMessageBranch(list, anchorIndex, targetBranchIndex),
    }
  }

  function forkSessionFromMessage(sKey: string, upToIndex: number, followUpPrompt?: string) {
    const sess = sessionsByKey.value[sKey]
    const list = messagesBySession.value[sKey] ?? []
    if (!sess) return
    const sliced = list.slice(0, Math.max(1, upToIndex + 1)).map(m => ({
      ...m,
      streaming: false,
    }))
    const requestId = createRequestId()
    const summaryContext = sliced
      .slice(-6)
      .map(m => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.text.slice(0, 400)}`)
      .join('\n')
    const forkPrompt = followUpPrompt?.trim()
      ? `基于以下分支上下文继续：\n${summaryContext}\n\n---\n${followUpPrompt.trim()}`
      : undefined

    openSession({
      nodeId: sess.nodeId,
      provider: sess.provider,
      cwd: sess.cwd || undefined,
      requestId,
      onOpened(newKey) {
        messagesBySession.value = {
          ...messagesBySession.value,
          [newKey]: [
            ...sliced,
            {
              id: `sys-fork-${Date.now()}`,
              role: 'system',
              nodeId: sess.nodeId,
              provider: sess.provider,
              text: `已从「${sess.title}」分叉出独立会话窗口`,
              createdAt: Date.now(),
            },
          ],
        }
        if (sessionsByKey.value[newKey]) {
          sessionsByKey.value = {
            ...sessionsByKey.value,
            [newKey]: { ...sessionsByKey.value[newKey], title: `${sess.title} (分支)` },
          }
        }
        activeSessionKey.value = newKey
        if (forkPrompt) {
          void sendPromptToSession(newKey, forkPrompt, [], runSettings.value[sKey], false)
        }
      },
    })
  }

  function exportSessionMarkdown(sKey?: string): string {
    const key = sKey || activeSessionKey.value
    const sess = key ? sessionsByKey.value[key] : null
    if (!sess) return ''
    const msgs = messagesBySession.value[key] ?? []
    const nodeName = nodes.value.find(n => n.id === sess.nodeId)?.name
    const md = buildSessionMarkdown(sess, msgs, nodeName)
    if (typeof document !== 'undefined' && typeof Blob !== 'undefined') {
      const blob = new Blob([md], { type: 'text/markdown;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      try {
        const a = document.createElement('a')
        a.href = url
        const safeTitle = (sess.title || sess.sessionId).replace(/[^A-Za-z0-9._\-\u4e00-\u9fff]+/g, '_')
        a.download = `${safeTitle}.md`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
      } finally {
        URL.revokeObjectURL(url)
      }
    }
    return md
  }

  function exportSessionHtml(sKey?: string): string {
    const key = sKey || activeSessionKey.value
    const sess = key ? sessionsByKey.value[key] : null
    if (!sess) return ''
    const msgs = messagesBySession.value[key] ?? []
    const nodeName = nodes.value.find(n => n.id === sess.nodeId)?.name
    const html = buildSessionHtmlReport(sess, msgs, nodeName)
    if (typeof document !== 'undefined' && typeof Blob !== 'undefined') {
      const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      try {
        const a = document.createElement('a')
        a.href = url
        const safeTitle = (sess.title || sess.sessionId).replace(/[^A-Za-z0-9._\-\u4e00-\u9fff]+/g, '_')
        a.download = `${safeTitle}.html`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
      } finally {
        URL.revokeObjectURL(url)
      }
    }
    return html
  }

  function requestWorkspaceTree(relDir = '', sKey?: string) {
    const key = sKey || activeSessionKey.value
    const sess = key ? sessionsByKey.value[key] : null
    const nid = sess?.nodeId ?? selectedNode.value?.id
    const prov = sess?.provider ?? selectedProvider.value
    if (!nid) return false
    return sendWsCommand({
      type: 'files.tree',
      nodeId: nid,
      provider: prov,
      ...(sess ? { sessionId: sess.sessionId, cwd: sess.worktreePath || sess.cwd } : {}),
      relDir,
      requestId: createRequestId(),
    })
  }

  function revertDiffHunk(sKey: string, path: string, hunkPatch: string) {
    const sess = sessionsByKey.value[sKey]
    if (!sess || !path || !hunkPatch) return false
    return sendWsCommand({
      type: 'diff.revert_hunk',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      path,
      patch: hunkPatch,
      requestId: createRequestId(),
    })
  }

  function commitWorkspaceChanges(sKey: string, message: string, paths?: string[]) {
    const sess = sessionsByKey.value[sKey]
    const cleanMsg = message.trim()
    if (!sess || !cleanMsg) return false
    return sendWsCommand({
      type: 'git.commit',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      message: cleanMsg,
      ...(paths?.length ? { paths } : {}),
      requestId: createRequestId(),
    })
  }

  function requestTrustPolicies(nodeId?: string) {
    const nid = nodeId || selectedNode.value?.id
    if (!nid) return false
    return sendWsCommand({ type: 'trust.list', nodeId: nid, requestId: createRequestId() })
  }

  function addTrustPattern(nodeId: string, pattern: string) {
    const clean = pattern.trim()
    if (!nodeId || !clean) return false
    return sendWsCommand({ type: 'trust.add', nodeId, pattern: clean, requestId: createRequestId() })
  }

  function removeTrustPattern(nodeId: string, pattern: string) {
    if (!nodeId || !pattern) return false
    return sendWsCommand({ type: 'trust.remove', nodeId, pattern, requestId: createRequestId() })
  }

  function openTerminal(sKey?: string) {
    const key = sKey || activeSessionKey.value
    const sess = key ? sessionsByKey.value[key] : null
    if (!sess) return false
    return sendWsCommand({
      type: 'terminal.open',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      ...(sess.worktreePath || sess.cwd ? { cwd: sess.worktreePath || sess.cwd } : {}),
      requestId: createRequestId(),
    })
  }

  function sendTerminalInput(sKey: string, data: string) {
    const sess = sessionsByKey.value[sKey]
    const term = terminalBySession.value[sKey]
    if (!sess || !term || term.closed) return false
    return sendWsCommand({
      type: 'terminal.input',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      terminalId: term.terminalId,
      data,
    })
  }

  function closeTerminal(sKey?: string) {
    const key = sKey || activeSessionKey.value
    const sess = key ? sessionsByKey.value[key] : null
    const term = key ? terminalBySession.value[key] : null
    if (!sess || !term) return false
    return sendWsCommand({
      type: 'terminal.close',
      nodeId: sess.nodeId,
      provider: sess.provider,
      sessionId: sess.sessionId,
      terminalId: term.terminalId,
    })
  }

  function toggleMessageBookmark(sKey: string, msgId: string) {
    if (!sKey || !msgId) return
    const cur = bookmarkedIdsBySession.value[sKey] ?? []
    const exists = cur.includes(msgId)
    bookmarkedIdsBySession.value = {
      ...bookmarkedIdsBySession.value,
      [sKey]: exists ? cur.filter(id => id !== msgId) : [...cur, msgId],
    }
  }

  async function toggleDesktopNotifications(): Promise<boolean> {
    if (typeof window === 'undefined' || typeof Notification === 'undefined') return false
    if (notificationsEnabled.value) {
      notificationsEnabled.value = false
      return false
    }
    if (Notification.permission === 'granted') {
      notificationsEnabled.value = true
      return true
    }
    if (Notification.permission === 'denied') {
      return false
    }
    try {
      const res = await Notification.requestPermission()
      notificationsEnabled.value = res === 'granted'
      return notificationsEnabled.value
    } catch {
      return false
    }
  }

  function notifyBackgroundEvent(title: string, body: string) {
    if (typeof document === 'undefined') return
    if (document.hidden) {
      unreadNotifyTitle.value = title
      if (notificationsEnabled.value && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        try {
          new Notification(title, { body: body.slice(0, 120) })
        } catch {
          // 浏览器禁止桌面弹窗时静默降级
        }
      }
    }
  }

  function clearUnreadNotifyTitle() {
    unreadNotifyTitle.value = ''
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
    agentsByTarget,
    mcpByTarget,
    rulesByTarget,
    filePreviewBySession,
    fileTextCacheBySession,
    pendingFormsById,
    treeCacheByTarget,
    trustPatternsByNode,
    terminalBySession,
    bookmarkedIdsBySession,
    notificationsEnabled,
    unreadNotifyTitle,
    tokenUsageBySession,
    todosBySession,
    currentTodos,
    diffBySession,
    currentDiff,
    checkpointsBySession,
    currentCheckpoints,
    filesCacheByTarget,
    queuedPromptsBySession,
    currentQueue,
    imagePreviewByArtifactId,
    requestModels(nodeId: string, provider: AdapterProvider) {
      return sendWsCommand({ type: 'models.list', nodeId, provider, requestId: createRequestId() })
    },
    requestAgents,
    requestMcpServers,
    requestRules,
    requestFileContent,
    requestDiffFileContext,
    closeFilePreview,
    revertFiles,
    mergeSessionWorktree,
    replyForm,
    subscribeSession,
    applyDefaultModelPref,
    setModelPreference,
    requestSessionsList,
    openSession,
    activateSession,
    loadSessionHistory,
    sendPromptToSpecificSession,
    sendPrompt,
    enqueuePrompt,
    removeQueuedPrompt,
    updateQueuedPrompt,
    steerQueuedPrompt,
    requestFilesList,
    requestSessionDiff,
    revertCheckpoint,
    compactSession,
    renameSession,
    deleteSession,
    editMessageAndBranch,
    regenerateAssistantMessage,
    switchBranch,
    forkSessionFromMessage,
    exportSessionMarkdown,
    exportSessionHtml,
    requestWorkspaceTree,
    revertDiffHunk,
    commitWorkspaceChanges,
    requestTrustPolicies,
    addTrustPattern,
    removeTrustPattern,
    openTerminal,
    sendTerminalInput,
    closeTerminal,
    toggleMessageBookmark,
    toggleDesktopNotifications,
    clearUnreadNotifyTitle,
    cancelSessionRun,
    cancelActiveRun,
    respondPermission,
    sendHandoff,
    sendFanout,
    downloadArtifactToBrowser,
  }
})
