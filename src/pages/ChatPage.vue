<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import AgentChatThread from '../components/chat/AgentChatThread.vue'
import CommandPaletteModal from '../components/chat/CommandPaletteModal.vue'
import DiffReviewDrawer from '../components/chat/DiffReviewDrawer.vue'
import FileViewerDrawer from '../components/chat/FileViewerDrawer.vue'
import TerminalDrawer from '../components/chat/TerminalDrawer.vue'
import WorkspaceTreeDrawer from '../components/chat/WorkspaceTreeDrawer.vue'
import { getPlatformIcon, getProviderMeta } from '../components/chat/providerMeta'
import OpusIcon from '../components/ui/OpusIcon.vue'
import { searchSessionsAndMessages } from '../services/chatHelpers'
import {
  readStoredWidth,
  saveStoredWidth,
  sharedChatOccupiedWidth,
  startColumnDrag,
} from '../composables/useResizableShell'
import { sessionKey, useFleetStore } from '../stores/fleet'
import type { AdapterProvider, AgentNode, ArtifactRef, ChatSession } from '../types/fleet'

const props = defineProps<{ mobile?: boolean }>()

const emit = defineEmits<{
  navigate: [page: string]
  action: [message: string]
}>()

const fleet = useFleetStore()

const TREE_DEFAULT_W = 244
const TREE_MIN_W = 128
const TREE_MAX_W = 440
const TREE_SNAP_CLOSE = 84
const workspace = ref<HTMLElement>()
const primaryThreadRef = ref<InstanceType<typeof AgentChatThread> | null>(null)
const treeOpen = ref(true)
const treeWidth = ref(readStoredWidth('studiolo:chat-tree-w', TREE_DEFAULT_W, TREE_MIN_W, TREE_MAX_W))
const rightMode = ref<'none' | 'split' | 'diff' | 'file' | 'tree' | 'terminal'>('none')
const lastWorkbenchTab = ref<'split' | 'diff' | 'file' | 'tree' | 'terminal'>('diff')
const diffFocusFile = ref<string | undefined>(undefined)
const autoCollapsedLeft = ref(false)
const selectedCheckpointId = ref<string>('')

watch(treeOpen, open => {
  if (open) autoCollapsedLeft.value = false
})
const showCommandPalette = ref(false)
const splitPercent = ref(readStoredWidth('studiolo:chat-split-percent', 50, 5, 95))
const isResizing = ref(false)
const treeQuery = ref('')
const actionsMenu = ref<HTMLDetailsElement>()
const renamingSessionKey = ref<string | null>(null)
const renameDraft = ref('')

function onActionsFocusOut(event: FocusEvent) {
  if (!(event.relatedTarget instanceof Node && actionsMenu.value?.contains(event.relatedTarget))) closeActions()
}

function closeActions() {
  if (actionsMenu.value) actionsMenu.value.open = false
}

// 标签页与分屏独立会话路由
const openTabKeys = ref<string[]>([])
const secondaryTabKey = ref<string>('')
watch(secondaryTabKey, key => { if (key) fleet.loadSessionHistory(key) })
const createInSplit = ref(false)

// 弹窗状态
const showNewSession = ref(false)
const newSessionNodeId = ref('')
const newSessionProvider = ref<AdapterProvider>('codex')
const newSessionCwd = ref('')
const newSessionWorktree = ref(false)

const showHandoff = ref(false)
const handoffTargetNode = ref('')
const handoffTargetProvider = ref<AdapterProvider>('codex')
const handoffSummary = ref('')
const handoffArtifact = ref<ArtifactRef | undefined>(undefined)

const showFanout = ref(false)
const fanoutTargets = ref<Array<{ nodeId: string; provider: AdapterProvider }>>([])
const fanoutPrompt = ref('')
const showMobilePicker = ref(false)

watch(
  [treeOpen, treeWidth, rightMode, () => props.mobile],
  () => {
    if (props.mobile) {
      sharedChatOccupiedWidth.value = 0
      return
    }
    const leftW = treeOpen.value ? treeWidth.value : 0
    const rightW = rightMode.value !== 'none' ? 220 : 0
    sharedChatOccupiedWidth.value = leftW + rightW
  },
  { immediate: true },
)

const basePageTitle = typeof document !== 'undefined' ? (document.title || 'Studiolo') : 'Studiolo'

function handleVisibilityChange() {
  if (typeof document !== 'undefined' && !document.hidden) {
    fleet.clearUnreadNotifyTitle()
  }
}

watch(
  () => fleet.unreadNotifyTitle,
  badge => {
    if (typeof document === 'undefined') return
    document.title = badge ? `${badge} · ${basePageTitle}` : basePageTitle
  },
  { immediate: true },
)

onUnmounted(() => {
  sharedChatOccupiedWidth.value = 0
  if (typeof window !== 'undefined') window.removeEventListener('keydown', handleGlobalKeydown)
  if (typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', handleVisibilityChange)
    document.title = basePageTitle
  }
})

function handleGlobalKeydown(ev: KeyboardEvent) {
  if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && ev.key.toLowerCase() === 'k') {
    ev.preventDefault()
    showCommandPalette.value = !showCommandPalette.value
    if (showCommandPalette.value && fleet.activeSessionKey && fleet.selectedNode?.status === 'online') {
      fleet.requestFilesList('', 80, fleet.activeSessionKey)
    }
  }
}

onMounted(async () => {
  if (typeof window !== 'undefined') window.addEventListener('keydown', handleGlobalKeydown)
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', handleVisibilityChange)
  await fleet.loadNodes()
  fleet.connectSocket()
  if (fleet.selectedNode?.allowedRoots?.length) {
    newSessionCwd.value = fleet.selectedNode.allowedRoots[0]
  }
})

// 当新会话激活时，自动纳入顶部标签页栏并清空历史检查点过滤
watch(
  () => fleet.activeSessionKey,
  key => {
    selectedCheckpointId.value = ''
    if (key && !openTabKeys.value.includes(key)) {
      openTabKeys.value = [...openTabKeys.value, key]
    }
  },
  { immediate: true },
)

const openTabs = computed(() =>
  openTabKeys.value
    .map(k => ({ key: k, session: fleet.sessionsByKey[k] }))
    .filter((entry): entry is { key: string; session: ChatSession } => Boolean(entry.session)),
)

const sortedNodes = computed(() => {
  const rank = (n: AgentNode) => {
    if (fleet.nodesWithApprovalPending.has(n.id)) return 0
    if (n.status === 'online') return 1
    return 2
  }
  return [...fleet.nodes].sort((a, b) => rank(a) - rank(b))
})

const selectedNodeAdapters = computed(() => {
  const node = fleet.selectedNode
  if (node?.adapters?.length) return node.adapters
  return fleet.availableProviders.map(p => ({
    provider: p,
    version: '',
    status: 'unavailable' as const,
    capabilities: [],
  }))
})

function readyAt(nodeId: string) {
  const node = fleet.nodes.find(n => n.id === nodeId && n.status === 'online')
  return node?.adapters.filter(a => a.status === 'ready') ?? []
}

function changeCreateNode() {
  const node = fleet.nodes.find(n => n.id === newSessionNodeId.value)
  newSessionCwd.value = node?.allowedRoots[0] ?? ''
  newSessionProvider.value = readyAt(newSessionNodeId.value)[0]?.provider ?? 'codex'
}

function leafPathName(fullPath: string): string {
  const parts = fullPath.replace(/\\/g, '/').split('/').filter(Boolean)
  return parts[parts.length - 1] || fullPath
}

function normPath(pathStr: string): string {
  return pathStr.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

function sessionBelongsToRoot(sess: ChatSession, root: string): boolean {
  const sc = normPath(sess.cwd || '')
  const rc = normPath(root)
  if (!sc || !rc) return false
  return sc === rc || sc.startsWith(`${rc}/`)
}

const searchHits = computed(() => {
  const entries = fleet.allSessions.map(session => ({
    key: sessionKey(session.nodeId, session.provider, session.sessionId),
    session,
    nodeName: fleet.nodes.find(n => n.id === session.nodeId)?.name,
  }))
  return searchSessionsAndMessages(entries, fleet.messagesBySession, treeQuery.value)
})

function searchSnippetFor(sess: ChatSession): string | undefined {
  const key = sessionKey(sess.nodeId, sess.provider, sess.sessionId)
  return searchHits.value.get(key)?.snippet
}

function sessionsForNodeRoot(nodeId: string, root: string): ChatSession[] {
  const term = treeQuery.value.trim()
  return fleet.allSessions.filter(s => {
    if (s.nodeId !== nodeId || !sessionBelongsToRoot(s, root)) return false
    if (!term) return true
    return searchHits.value.has(sessionKey(s.nodeId, s.provider, s.sessionId))
  })
}

function orphanSessionsForNode(node: AgentNode): ChatSession[] {
  const term = treeQuery.value.trim()
  return fleet.allSessions.filter(s => {
    if (s.nodeId !== node.id) return false
    if (node.allowedRoots.some(r => sessionBelongsToRoot(s, r))) return false
    if (!term) return true
    return searchHits.value.has(sessionKey(s.nodeId, s.provider, s.sessionId))
  })
}

function matchesTreeFilter(node: AgentNode): boolean {
  const term = treeQuery.value.trim().toLowerCase()
  if (!term) return true
  if (node.name.toLowerCase().includes(term)) return true
  if (node.allowedRoots.some(r => r.toLowerCase().includes(term))) return true
  return fleet.allSessions.some(
    s => s.nodeId === node.id && searchHits.value.has(sessionKey(s.nodeId, s.provider, s.sessionId)),
  )
}

const visibleNodes = computed(() => sortedNodes.value.filter(matchesTreeFilter))

function nodeIndicatorStatus(nodeId: string, rawStatus: string) {
  if (fleet.nodesWithApprovalPending.has(nodeId)) return 'reconnecting'
  return rawStatus === 'online' ? 'online' : 'offline'
}

function nodeStatusText(nodeId: string, rawStatus: string) {
  if (fleet.nodesWithApprovalPending.has(nodeId)) return '待审批'
  return rawStatus === 'online' ? '在线' : rawStatus === 'revoked' ? '已吊销' : '离线'
}

function sessionDotClass(sess: ChatSession): string {
  const sKey = sessionKey(sess.nodeId, sess.provider, sess.sessionId)
  if (fleet.runningBySession[sKey]) return 'is-running'
  const hasPending = fleet.pendingApprovalsList.some(
    c => c.nodeId === sess.nodeId && c.sessionId === sess.sessionId,
  )
  if (hasPending) return 'is-approval'
  return 'is-ready'
}

function openSessionTab(sess: ChatSession) {
  const sKey = sessionKey(sess.nodeId, sess.provider, sess.sessionId)
  if (!openTabKeys.value.includes(sKey)) {
    openTabKeys.value = [...openTabKeys.value, sKey]
  }
  fleet.activateSession(sKey)
}

function closeSessionTab(sKey: string) {
  openTabKeys.value = openTabKeys.value.filter(k => k !== sKey)
  if (fleet.activeSessionKey === sKey) {
    const fallback = openTabKeys.value[openTabKeys.value.length - 1]
    if (fallback) fleet.activateSession(fallback)
    else fleet.activeSessionKey = ''
  }
}

function setRightPane(
  mode: 'none' | 'split' | 'diff' | 'file' | 'tree' | 'terminal',
  opts?: { focusFile?: string },
) {
  if (mode === 'none') {
    rightMode.value = 'none'
    if (autoCollapsedLeft.value && !props.mobile) {
      treeOpen.value = true
      autoCollapsedLeft.value = false
    }
    return
  }

  const wasOpen = rightMode.value !== 'none'
  if (!wasOpen && !props.mobile && treeOpen.value) {
    autoCollapsedLeft.value = true
    treeOpen.value = false
  }
  lastWorkbenchTab.value = mode

  if (mode === 'split' && !secondaryTabKey.value) {
    const alt = fleet.allSessions.find(
      s => sessionKey(s.nodeId, s.provider, s.sessionId) !== fleet.activeSessionKey,
    )
    if (alt) {
      secondaryTabKey.value = sessionKey(alt.nodeId, alt.provider, alt.sessionId)
    }
  } else if (mode === 'diff') {
    diffFocusFile.value = opts?.focusFile
    if (fleet.activeSessionKey) {
      fleet.requestSessionDiff(fleet.activeSessionKey, selectedCheckpointId.value || undefined)
    }
  } else if (mode === 'tree' && fleet.activeSessionKey) {
    fleet.requestWorkspaceTree('', fleet.activeSessionKey)
  } else if (mode === 'terminal' && fleet.activeSessionKey && !fleet.terminalBySession[fleet.activeSessionKey]) {
    fleet.openTerminal(fleet.activeSessionKey)
  }

  rightMode.value = mode
}

function openSessionInSplit(sess: ChatSession) {
  const sKey = sessionKey(sess.nodeId, sess.provider, sess.sessionId)
  secondaryTabKey.value = sKey
  setRightPane('split')
}

function toggleRightMode(target: 'split' | 'diff' | 'tree' | 'terminal' | 'file') {
  if (rightMode.value === target) {
    setRightPane('none')
    return
  }
  setRightPane(target)
}

function toggleWorkbenchDrawer() {
  if (rightMode.value !== 'none') {
    setRightPane('none')
    return
  }
  const hasFiles = Boolean(fleet.currentDiff?.files?.length)
  const preferred = lastWorkbenchTab.value === 'file' && !fleet.filePreviewBySession[fleet.activeSessionKey]
    ? (hasFiles ? 'diff' : 'tree')
    : lastWorkbenchTab.value
  setRightPane(preferred)
}

function openDiffPanel(focusFile?: string) {
  setRightPane('diff', { focusFile })
}

function openFilePreview(filePath: string, line?: number) {
  if (!fleet.activeSessionKey) {
    emit('action', '请先进入一个活跃会话再预览文件')
    return
  }
  fleet.requestFileContent(filePath, fleet.activeSessionKey, line)
  setRightPane('file')
}

function handleOpenSubagent(subSessionId: string) {
  const cur = fleet.currentSession
  if (!cur || !subSessionId) return
  const existingKey = sessionKey(cur.nodeId, cur.provider, subSessionId)
  if (fleet.sessionsByKey[existingKey]) {
    openSessionTab(fleet.sessionsByKey[existingKey])
    return
  }
  fleet.openSession({
    nodeId: cur.nodeId,
    provider: cur.provider,
    cwd: cur.cwd || undefined,
    sessionId: subSessionId,
    onOpened: k => {
      if (!openTabKeys.value.includes(k)) openTabKeys.value = [...openTabKeys.value, k]
      fleet.activateSession(k)
    },
  })
}

const paletteSessions = computed(() =>
  fleet.allSessions.map(s => ({
    key: sessionKey(s.nodeId, s.provider, s.sessionId),
    title: s.title,
    subtitle: `${fleet.nodes.find(n => n.id === s.nodeId)?.name || s.nodeId} · ${s.cwd || '-'}`,
    provider: getProviderMeta(s.provider).label,
  })),
)

const paletteFiles = computed(() => {
  const cur = fleet.currentSession
  if (fleet.activeSessionKey && fleet.filesCacheByTarget[fleet.activeSessionKey]?.length) {
    return fleet.filesCacheByTarget[fleet.activeSessionKey]
  }
  if (cur) {
    return fleet.filesCacheByTarget[`${cur.nodeId}::${cur.provider}`] ?? []
  }
  return []
})

const paletteCommands = [
  { id: 'new', label: '新建工作会话', description: '选择节点、Agent 引擎或创建 Git Worktree 沙箱', command: '__new_session__' },
  { id: 'diff', label: '打开变更审查面板', description: '查看当前会话 Git Diff 与逐文件/分块回滚', command: '__open_diff__' },
  { id: 'tree', label: '浏览工作区目录树', description: '按文件夹懒加载浏览并只读预览项目文件', command: '__open_tree__' },
  { id: 'terminal', label: '打开受控工作区终端', description: '在会话允许目录下执行交互式 Shell 命令', command: '__open_terminal__' },
  { id: 'split', label: '切换并排协同分屏', description: '同时对比两个模型或节点输出', command: '__toggle_split__' },
  { id: 'plan', label: '/plan 分步规划模板', description: '向输入框填入 /plan 模板', command: '/plan 请先分析涉及模块并列出分步方案，确认后再修改：' },
  { id: 'review', label: '/review 审查代码改动', description: '向输入框填入代码审查指令', command: '请审查当前工作区代码改动，指出潜在 Bug 与优化建议。' },
  { id: 'compact', label: '/compact 压缩当前上下文', description: '触发上游代理整理并压缩早期历史', command: '__compact__' },
  { id: 'undo', label: '/undo 回滚最近检查点', description: '还原上一轮产生的工作区修改', command: '__undo__' },
  { id: 'settings', label: 'Agent 与连接设置', description: '管理控制节点与令牌状态', command: '__settings__' },
]

const paletteMessageHits = computed(() => {
  const hits: Array<{ id: string; sessionKey: string; sessionTitle: string; snippet: string }> = []
  for (const [k, list] of Object.entries(fleet.messagesBySession)) {
    const title = fleet.sessionsByKey[k]?.title || k
    for (const m of list.slice(-10)) {
      if (m.role !== 'system' && m.text.trim()) {
        hits.push({
          id: m.id,
          sessionKey: k,
          sessionTitle: title,
          snippet: m.text.replace(/\s+/g, ' ').slice(0, 88),
        })
      }
    }
  }
  return hits.slice(-40)
})

function openPaletteModal() {
  showCommandPalette.value = true
  if (fleet.activeSessionKey && fleet.selectedNode?.status === 'online') {
    fleet.requestFilesList('', 80, fleet.activeSessionKey)
  }
}

function handlePaletteRunCommand(cmd: string) {
  if (cmd === '__new_session__') openCreateSession()
  else if (cmd === '__open_diff__') openDiffPanel()
  else if (cmd === '__open_tree__') toggleRightMode('tree')
  else if (cmd === '__open_terminal__') toggleRightMode('terminal')
  else if (cmd === '__toggle_split__') toggleRightMode('split')
  else if (cmd === '__compact__') handleCompactActive()
  else if (cmd === '__undo__' && fleet.activeSessionKey) fleet.revertCheckpoint(fleet.activeSessionKey)
  else if (cmd === '__settings__') emit('navigate', 'Agents')
  else primaryThreadRef.value?.insertFileReference(cmd.startsWith('/') ? cmd : ` ${cmd}`)
}

function selectCheckpointInDiff(cpId?: string) {
  selectedCheckpointId.value = cpId || ''
  if (fleet.activeSessionKey) {
    fleet.requestSessionDiff(fleet.activeSessionKey, cpId)
  }
}

function startRenameSession(sess: ChatSession) {
  renamingSessionKey.value = sessionKey(sess.nodeId, sess.provider, sess.sessionId)
  renameDraft.value = sess.title
  treeOpen.value = true
  void nextTick(() => {
    const input = workspace.value?.querySelector<HTMLInputElement>('.tree-rename-input')
    input?.focus()
    input?.select()
  })
}

function commitRenameSession(sKey: string) {
  if (renamingSessionKey.value !== sKey) return
  if (renameDraft.value.trim()) {
    fleet.renameSession(sKey, renameDraft.value)
    emit('action', '已更新会话名称')
  }
  renamingSessionKey.value = null
  renameDraft.value = ''
}

function cancelRenameSession() {
  renamingSessionKey.value = null
  renameDraft.value = ''
}

function handleDeleteSession(sKey: string) {
  fleet.deleteSession(sKey)
  openTabKeys.value = openTabKeys.value.filter(k => k !== sKey)
  if (secondaryTabKey.value === sKey) secondaryTabKey.value = ''
  emit('action', '已关闭并移除该会话')
}

function handleCompactActive() {
  if (!fleet.activeSessionKey) return
  fleet.compactSession(fleet.activeSessionKey)
}

function handleExportActive() {
  if (!fleet.activeSessionKey) return
  const md = fleet.exportSessionMarkdown(fleet.activeSessionKey)
  if (md) emit('action', '已导出会话记录为 Markdown 文件')
}

function handleExportHtml() {
  if (!fleet.activeSessionKey) return
  const html = fleet.exportSessionHtml(fleet.activeSessionKey)
  if (html) emit('action', '已导出会话记录为独立 HTML 报告')
}

async function handleToggleNotifications() {
  const ok = await fleet.toggleDesktopNotifications()
  if (fleet.notificationsEnabled && ok) {
    emit('action', '已开启后台审批与任务完成桌面通知')
  } else if (!fleet.notificationsEnabled) {
    emit('action', '已关闭桌面通知提醒')
  } else {
    emit('action', '浏览器未授予通知权限，将仅通过标签页标题提醒')
  }
}

function handleTreeDrag(event: PointerEvent) {
  if (event.button !== 0 || !event.isPrimary) return
  const previousWidth = treeWidth.value
  const available = workspace.value?.clientWidth
  const maxWidth = available && treeOpen.value && rightMode.value !== 'none'
    ? Math.min(TREE_MAX_W, Math.floor(available * .26))
    : TREE_MAX_W
  isResizing.value = true
  startColumnDrag({
    event,
    initialWidth: Math.min(previousWidth, maxWidth),
    min: Math.min(TREE_MIN_W, maxWidth),
    max: maxWidth,
    snapCollapseThreshold: TREE_SNAP_CLOSE,
    snapExpandThreshold: 108,
    onPreview(width, isClosed) {
      if (!isClosed) treeWidth.value = width
    },
    onCommit(width, isClosed) {
      if (isClosed) {
        treeOpen.value = false
      } else {
        treeOpen.value = true
        treeWidth.value = width
        saveStoredWidth('studiolo:chat-tree-w', width)
      }
    },
    onCancel() {
      treeWidth.value = previousWidth
    },
    onEnd() {
      isResizing.value = false
    },
  })
}

function resetTreeWidth() {
  treeOpen.value = true
  treeWidth.value = TREE_DEFAULT_W
  saveStoredWidth('studiolo:chat-tree-w', TREE_DEFAULT_W)
}

function handleRightDrag(event: PointerEvent) {
  if (event.button !== 0 || !event.isPrimary) return
  const main = workspace.value?.querySelector('.fleet-main')
  const peer = workspace.value?.querySelector('.fleet-right-pane')
  if (!main || !peer) return
  const total = main.clientWidth + peer.clientWidth
  const minimum = Math.min(120, Math.floor(total / 2))
  const previous = splitPercent.value
  isResizing.value = true
  startColumnDrag({
    event, initialWidth: peer.clientWidth, min: minimum, max: total - minimum, direction: -1,
    onPreview(width) { splitPercent.value = width / total * 100 },
    onCommit(width) {
      splitPercent.value = width / total * 100
      saveStoredWidth('studiolo:chat-split-percent', splitPercent.value)
    },
    onCancel() { splitPercent.value = previous },
    onEnd() { isResizing.value = false },
  })
}

function resetRightWidth() {
  splitPercent.value = 50
  saveStoredWidth('studiolo:chat-split-percent', 50)
}

function openCreateSession(node?: AgentNode, presetCwd?: string, presetProvider?: AdapterProvider, inSplit = false) {
  createInSplit.value = inSplit
  const targetNode = node ?? fleet.selectedNode
  newSessionNodeId.value = targetNode?.id ?? ''
  if (presetProvider) {
    newSessionProvider.value = presetProvider
  } else {
    const ready = targetNode?.adapters.find(a => a.status === 'ready')
    newSessionProvider.value = ready?.provider ?? fleet.selectedProvider
  }
  newSessionCwd.value = presetCwd ?? targetNode?.allowedRoots?.[0] ?? ''
  showNewSession.value = true
}

function submitNewSession() {
  const targetId = newSessionNodeId.value || fleet.selectedNode?.id
  if (!targetId) {
    emit('action', '请先选择在线节点')
    return
  }
  if (!createInSplit.value) {
    fleet.selectNode(targetId)
    fleet.selectProvider(newSessionProvider.value)
  }
  fleet.openSession({
    nodeId: targetId,
    provider: newSessionProvider.value,
    cwd: newSessionCwd.value.trim() || undefined,
    useWorktree: newSessionWorktree.value,
    onOpened: createInSplit.value ? key => { secondaryTabKey.value = key } : undefined,
  })
  showNewSession.value = false
  emit('action', `已请求创建 ${getProviderMeta(newSessionProvider.value).label} 会话`)
}

function openHandoffDialog(payload?: { summary: string; artifact?: ArtifactRef }) {
  const otherNode =
    fleet.nodes.find(n => n.id !== fleet.selectedNode?.id && n.status === 'online') ??
    fleet.selectedNode
  handoffTargetNode.value = otherNode?.id ?? ''
  handoffTargetProvider.value = otherNode?.adapters.find(a => a.status === 'ready')?.provider ?? 'codex'
  handoffSummary.value = payload?.summary ?? ''
  handoffArtifact.value = payload?.artifact
  showHandoff.value = true
}

function submitHandoff() {
  if (!handoffTargetNode.value || !handoffSummary.value.trim()) {
    emit('action', '请选择目标节点并填写交接摘要')
    return
  }
  fleet.sendHandoff({
    targetNodeId: handoffTargetNode.value,
    targetProvider: handoffTargetProvider.value,
    summary: handoffSummary.value.trim(),
    artifact: handoffArtifact.value,
  })
  showHandoff.value = false
  emit('action', '已通过 Fleet Relay 派发 @Handoff 任务')
}

function toggleFanoutTarget(nodeId: string, provider: AdapterProvider) {
  const idx = fanoutTargets.value.findIndex(
    t => t.nodeId === nodeId && t.provider === provider,
  )
  if (idx >= 0) {
    fanoutTargets.value = fanoutTargets.value.filter((_, i) => i !== idx)
  } else {
    fanoutTargets.value = [...fanoutTargets.value, { nodeId, provider }]
  }
}

function isFanoutChecked(nodeId: string, provider: AdapterProvider) {
  return fanoutTargets.value.some(t => t.nodeId === nodeId && t.provider === provider)
}

async function submitFanout() {
  if (fanoutTargets.value.length < 2 || !fanoutPrompt.value.trim()) {
    emit('action', '请勾选至少 2 个目标代理并输入群发指令')
    return
  }
  await fleet.sendFanout(fanoutTargets.value, fanoutPrompt.value, (key, index) => {
    if (index === 0) fleet.activateSession(key)
    if (index === 1) secondaryTabKey.value = key
  })
  showFanout.value = false
  fanoutPrompt.value = ''
  setRightPane('split')
  emit('action', `已同时向 ${fanoutTargets.value.length} 个 Agent 派发对比任务`)
}

function handleClearMemory() {
  fleet.clearSessionMemory()
  openTabKeys.value = []
  secondaryTabKey.value = ''
  fleet.connectSocket()
  emit('action', '已销毁内存中的会话正文与 E2EE 密钥')
}
</script>

<template>
  <!-- 移动端保持紧凑单手视图 + 顶部并发多标签条 -->
  <div v-if="mobile" class="chatpage">
    <div class="mchat-head">
      <header class="mchat-bar">
        <button type="button" class="mpill" @click="showMobilePicker = !showMobilePicker">
          <span class="conn" :class="fleet.wsState === 'online' ? 'online' : 'reconnecting'" />
          <span>{{ fleet.selectedNode?.name || '选择节点' }} · {{ getProviderMeta(fleet.selectedProvider).label }}</span>
          <OpusIcon name="chevD" />
        </button>
        <span class="spacer" />
        <button type="button" class="icon-btn" title="新建会话" @click="openCreateSession()"><OpusIcon name="plus" /></button>
        <button type="button" class="icon-btn" title="@Handoff" @click="openHandoffDialog()"><OpusIcon name="send" /></button>
      </header>

      <div v-if="openTabs.length > 1" class="m-tabs-row">
        <button
          v-for="tab in openTabs"
          :key="tab.key"
          type="button"
          class="m-tab-chip"
          :aria-pressed="fleet.activeSessionKey === tab.key"
          @click="fleet.activateSession(tab.key)"
        >
          <span class="tree-dot" :class="sessionDotClass(tab.session)" />
          <span>{{ tab.session.title }}</span>
        </button>
      </div>

      <div v-if="showMobilePicker" class="mchat-drawer card">
        <div class="mchat-sec">控制节点</div>
        <div class="mchat-chips">
          <button
            v-for="n in sortedNodes"
            :key="n.id"
            type="button"
            class="chip"
            :aria-pressed="fleet.selectedNode?.id === n.id"
            @click="fleet.selectNode(n.id)"
          >
            <span class="conn" :class="nodeIndicatorStatus(n.id, n.status)" />
            <span>{{ n.name }}</span>
          </button>
          <button type="button" class="chip" @click="emit('navigate', 'Agents')">+ 管理节点</button>
        </div>
        <div class="mchat-sec">可用引擎</div>
        <div class="mchat-chips">
          <button
            v-for="ad in selectedNodeAdapters"
            :key="ad.provider"
            type="button"
            class="chip"
            :aria-pressed="fleet.selectedProvider === ad.provider"
            @click="fleet.selectProvider(ad.provider); showMobilePicker = false"
          >
            <OpusIcon :name="getProviderMeta(ad.provider).icon" />
            <span>{{ getProviderMeta(ad.provider).label }}</span>
          </button>
        </div>
      </div>

      <div class="mbanner" :class="{ show: fleet.wsState !== 'online' || fleet.pendingApprovalsList.length > 0, warn: true }">
        <OpusIcon name="alert" />
        <span v-if="fleet.pendingApprovalsList.length">有 {{ fleet.pendingApprovalsList.length }} 项待批准工具调用</span>
        <span v-else>Fleet Relay 状态：{{ fleet.wsState }}</span>
      </div>
    </div>

    <AgentChatThread
      class="mchat-thread"
      :mobile="true"
      @action="emit('action', $event)"
      @open-handoff="openHandoffDialog"
    />
  </div>

  <!-- 桌面端：四层节点树（可自由拖拽） + 多标签主对话区 + 可选右分屏/沙箱抽屉（可自由拖拽） -->
  <div v-else ref="workspace" class="fleet-workspace" :class="{ 'is-resizing': isResizing, 'both-panes': treeOpen && rightMode !== 'none' }">
    <!-- 左栏：Orca 式 四层树（节点 -> allowedRoots 目录 -> Git Worktree -> 会话） -->
    <template v-if="treeOpen">
      <aside class="fleet-tree-pane pane-side" :style="{ width: `${treeWidth}px` }">
        <div class="tree-top">
          <div class="tree-top-actions">
            <strong>节点与会话</strong>
            <button type="button" class="icon-btn" title="刷新在线状态" @click="fleet.loadNodes(); fleet.connectSocket()">
              <OpusIcon name="sync" />
            </button>
            <button type="button" class="icon-btn" title="拉取选中节点历史会话" @click="fleet.requestSessionsList()">
              <OpusIcon name="history" />
            </button>
            <button type="button" class="icon-btn" title="管理控制节点与已添加智能体" @click="emit('navigate', 'Agents')">
              <OpusIcon name="settings" />
            </button>
            <button type="button" class="icon-btn" title="新建隔离会话" @click="openCreateSession()">
              <OpusIcon name="plus" />
            </button>
          </div>
          <div class="tree-search">
            <OpusIcon name="search" />
            <input v-model="treeQuery" type="search" placeholder="筛选节点、会话或消息正文…" aria-label="筛选节点、会话或消息正文" />
          </div>
        </div>

        <div class="tree-body">
          <div v-for="node in visibleNodes" :key="node.id" class="tree-node-group">
            <!-- Level 1: 主机节点 -->
            <div
              class="tree-node-hdr"
              :class="{ 'is-selected': fleet.selectedNode?.id === node.id }"
              @click="fleet.selectNode(node.id)"
            >
              <OpusIcon :name="getPlatformIcon(node.platform)" />
              <span class="tree-node-name">{{ node.name }}</span>
              <span class="conn" :class="nodeIndicatorStatus(node.id, node.status)">
                {{ nodeStatusText(node.id, node.status) }}
              </span>
              <button
                type="button"
                class="tree-mini-btn"
                title="在此节点新建会话"
                @click.stop="openCreateSession(node)"
              >+</button>
            </div>

            <!-- Level 2: allowedRoots 目录 -->
            <div v-if="node.allowedRoots.length" class="tree-roots">
              <div v-for="root in node.allowedRoots" :key="root" class="tree-root-block">
                <div class="tree-root-hdr" :title="root">
                  <OpusIcon name="file" />
                  <span class="tree-root-name">{{ leafPathName(root) }}</span>
                  <button
                    type="button"
                    class="tree-mini-btn"
                    title="在此目录打开会话"
                    @click.stop="openCreateSession(node, root)"
                  >+</button>
                </div>

                <!-- Level 3 & 4: Worktree 分支与并行会话 -->
                <div class="tree-branch-list">
                  <div
                    v-for="sess in sessionsForNodeRoot(node.id, root)"
                    :key="sess.sessionId"
                    class="tree-sess-row"
                    :class="{ 'is-active': fleet.activeSessionKey === sessionKey(sess.nodeId, sess.provider, sess.sessionId) }"
                    @click="openSessionTab(sess)"
                  >
                    <span class="tree-dot" :class="sessionDotClass(sess)" />
                    <div class="tree-sess-meta">
                      <input
                        v-if="renamingSessionKey === sessionKey(sess.nodeId, sess.provider, sess.sessionId)"
                        v-model="renameDraft"
                        type="text"
                        class="input tree-rename-input"
                        aria-label="输入新会话名称"
                        @click.stop
                        @keydown.enter.prevent="commitRenameSession(sessionKey(sess.nodeId, sess.provider, sess.sessionId))"
                        @keydown.esc.prevent="cancelRenameSession"
                        @blur="commitRenameSession(sessionKey(sess.nodeId, sess.provider, sess.sessionId))"
                      />
                      <template v-else>
                        <div class="tree-sess-title">{{ sess.title }}</div>
                        <div v-if="searchSnippetFor(sess)" class="tree-sess-hit">{{ searchSnippetFor(sess) }}</div>
                      </template>
                      <div v-if="sess.worktreePath" class="tree-sess-wt">
                        <OpusIcon name="branch" />
                        <span>{{ leafPathName(sess.worktreePath) }}</span>
                      </div>
                    </div>
                    <span class="tree-eng">{{ getProviderMeta(sess.provider).shortCode }}</span>
                    <button
                      type="button"
                      class="tree-mini-btn tree-split-trigger"
                      title="重命名会话"
                      aria-label="重命名会话"
                      @click.stop="startRenameSession(sess)"
                    ><OpusIcon name="pencil" /></button>
                    <button
                      type="button"
                      class="tree-mini-btn tree-split-trigger"
                      title="在右侧分屏并行查看"
                      @click.stop="openSessionInSplit(sess)"
                    >⊞</button>
                    <button
                      type="button"
                      class="tree-mini-btn tree-split-trigger"
                      title="关闭并删除会话"
                      aria-label="删除会话"
                      @click.stop="handleDeleteSession(sessionKey(sess.nodeId, sess.provider, sess.sessionId))"
                    >×</button>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="tree-empty-roots">节点离线或未上报 allowedRoots</div>

            <!-- 未命中白名单前自动建立的通用会话 -->
            <div v-if="orphanSessionsForNode(node).length" class="tree-roots">
              <div class="tree-branch-list">
                <div
                  v-for="sess in orphanSessionsForNode(node)"
                  :key="sess.sessionId"
                  class="tree-sess-row"
                  :class="{ 'is-active': fleet.activeSessionKey === sessionKey(sess.nodeId, sess.provider, sess.sessionId) }"
                  @click="openSessionTab(sess)"
                >
                  <span class="tree-dot" :class="sessionDotClass(sess)" />
                  <div class="tree-sess-meta">
                    <input
                      v-if="renamingSessionKey === sessionKey(sess.nodeId, sess.provider, sess.sessionId)"
                      v-model="renameDraft"
                      type="text"
                      class="input tree-rename-input"
                      aria-label="输入新会话名称"
                      @click.stop
                      @keydown.enter.prevent="commitRenameSession(sessionKey(sess.nodeId, sess.provider, sess.sessionId))"
                      @keydown.esc.prevent="cancelRenameSession"
                      @blur="commitRenameSession(sessionKey(sess.nodeId, sess.provider, sess.sessionId))"
                    />
                    <template v-else>
                      <div class="tree-sess-title">{{ sess.title }}</div>
                      <div v-if="searchSnippetFor(sess)" class="tree-sess-hit">{{ searchSnippetFor(sess) }}</div>
                    </template>
                  </div>
                  <span class="tree-eng">{{ getProviderMeta(sess.provider).shortCode }}</span>
                  <button
                    type="button"
                    class="tree-mini-btn tree-split-trigger"
                    title="重命名会话"
                    aria-label="重命名会话"
                    @click.stop="startRenameSession(sess)"
                  ><OpusIcon name="pencil" /></button>
                  <button
                    type="button"
                    class="tree-mini-btn tree-split-trigger"
                    title="在右侧分屏并行查看"
                    @click.stop="openSessionInSplit(sess)"
                  >⊞</button>
                  <button
                    type="button"
                    class="tree-mini-btn tree-split-trigger"
                    title="关闭并删除会话"
                    aria-label="删除会话"
                    @click.stop="handleDeleteSession(sessionKey(sess.nodeId, sess.provider, sess.sessionId))"
                  >×</button>
                </div>
              </div>
            </div>
          </div>

          <div v-if="!fleet.nodes.length" class="tree-empty-state">
            <p class="faint">尚未注册任何控制节点。</p>
            <button type="button" class="btn btn-primary btn-sm" @click="emit('navigate', 'Agents')">签发 sn_live_ 凭证</button>
          </div>
        </div>

      </aside>

      <div
        class="col-resizer"
        data-tauri-drag-region="false"
        title="左右拖动调节节点树宽度（向左拉过阈值自动折叠，双击还原）"
        @pointerdown="handleTreeDrag"
        @dblclick="resetTreeWidth"
      />
    </template>

    <!-- 中央：多标签协调与主对话画布 -->
    <section class="fleet-main chat" :style="{ flexGrow: rightMode !== 'none' ? 100 - splitPercent : 1 }">
      <header class="chat-tabs-h">
        <div class="tabs-scroll">
          <button
            v-if="!treeOpen"
            type="button"
            class="btn btn-subtle btn-sm"
            title="展开节点与会话树"
            @click="treeOpen = true"
          >
            <OpusIcon name="panel" />
            <span>节点树</span>
          </button>

          <button
            v-for="tab in openTabs"
            :key="tab.key"
            type="button"
            class="chat-tab"
            :class="{ 'is-active': fleet.activeSessionKey === tab.key }"
            @click="fleet.activateSession(tab.key)"
          >
            <span class="tree-dot" :class="sessionDotClass(tab.session)" />
            <span class="chat-tab-label">{{ tab.session.title }}</span>
            <span class="chat-tab-eng">{{ getProviderMeta(tab.session.provider).shortCode }}</span>
            <span
              class="chat-tab-close"
              role="button"
              aria-label="关闭标签"
              @click.stop="closeSessionTab(tab.key)"
            >×</span>
          </button>

          <div v-if="!openTabs.length" class="chat-empty-tab">
            <span>{{ fleet.selectedNode ? `${fleet.selectedNode.name} · ${getProviderMeta(fleet.selectedProvider).label}` : 'Agent Fleet' }}</span>
          </div>

          <button type="button" class="icon-btn" title="新建工作会话" @click="openCreateSession()">
            <OpusIcon name="plus" />
          </button>
        </div>

        <div class="tabs-actions">
          <button
            type="button"
            class="btn btn-sm btn-ghost"
            title="全局命令与文件跳转 (Ctrl+K)"
            @click="openPaletteModal"
          >
            <OpusIcon name="command" />
            <span>搜索</span>
          </button>
          <button
            v-if="fleet.currentSession"
            type="button"
            class="btn btn-sm"
            :class="rightMode !== 'none' ? 'btn-primary' : 'btn-ghost'"
            title="展开或收起右侧工作台（评审 · 目录 · 终端 · 分屏）"
            @click="toggleWorkbenchDrawer"
          >
            <OpusIcon name="panel" />
            <span>工作台</span>
            <span v-if="fleet.currentDiff?.summary?.filesChanged" class="diff-count-dot num">
              {{ fleet.currentDiff.summary.filesChanged }}
            </span>
          </button>
          <details ref="actionsMenu" class="session-actions"
            @focusout="onActionsFocusOut"
            @keydown.esc="closeActions(); actionsMenu?.querySelector('summary')?.focus()">
            <summary class="icon-btn" title="更多会话操作" aria-label="更多会话操作"><OpusIcon name="more" /></summary>
            <div class="action-list" @click="closeActions">
              <button v-if="fleet.currentSession" type="button" @click="primaryThreadRef?.openThreadSearch()"><OpusIcon name="search" />搜索本对话 (Ctrl+F)</button>
              <button type="button" @click="handleToggleNotifications">
                <OpusIcon name="bell" />
                <span>{{ fleet.notificationsEnabled ? '后台桌面通知：已开启' : '开启后台桌面通知' }}</span>
              </button>
              <button v-if="fleet.currentSession" type="button" @click="startRenameSession(fleet.currentSession)"><OpusIcon name="pencil" />重命名当前会话</button>
              <button v-if="fleet.currentSession" type="button" @click="handleCompactActive"><OpusIcon name="layers" />压缩历史上下文</button>
              <button v-if="fleet.currentSession" type="button" @click="handleExportActive"><OpusIcon name="download" />导出为 Markdown</button>
              <button v-if="fleet.currentSession" type="button" @click="handleExportHtml"><OpusIcon name="external" />导出为独立 HTML 报告</button>
              <button v-if="fleet.currentSession" type="button" @click="handleDeleteSession(fleet.activeSessionKey)"><OpusIcon name="x" />删除当前会话</button>
              <button type="button" @click="showFanout = true"><OpusIcon name="layers" />群发任务</button>
              <button type="button" @click="openHandoffDialog()"><OpusIcon name="send" />交接会话</button>
              <button type="button" @click="handleClearMemory"><OpusIcon name="trash" />清除内存会话</button>
            </div>
          </details>
        </div>
      </header>

      <div
        class="conn-banner"
        :class="{
          show: fleet.wsState !== 'online' || fleet.pendingApprovalsList.length > 0 || Boolean(fleet.lastError),
          warn: fleet.wsState !== 'online' || fleet.pendingApprovalsList.length > 0 || Boolean(fleet.lastError),
        }"
      >
        <OpusIcon name="alert" />
        <span v-if="fleet.pendingApprovalsList.length">
          有 {{ fleet.pendingApprovalsList.length }} 项敏感工具调用等待人工审批，批准前不会自动执行。
        </span>
        <span v-else-if="fleet.lastError">{{ fleet.lastError }}</span>
        <span v-else>Fleet WebSocket 通道：{{ fleet.wsState }}</span>
      </div>

      <AgentChatThread
        ref="primaryThreadRef"
        :session-key="fleet.activeSessionKey || undefined"
        @action="emit('action', $event)"
        @open-handoff="openHandoffDialog"
        @open-diff="openDiffPanel"
        @open-file="openFilePreview"
        @open-subagent="handleOpenSubagent"
        @clear-session="openCreateSession()"
      />
    </section>

    <!-- 右侧统一工作台抽屉（评审 Diff / 目录 / 预览 / 终端 / 分屏 Tab 切换） -->
    <template v-if="rightMode !== 'none'">
      <div
        class="col-resizer"
        data-tauri-drag-region="false"
        title="左右拖动调整右侧工作台宽度（双击还原）"
        @pointerdown="handleRightDrag"
        @dblclick="resetRightWidth"
      />

      <aside class="fleet-right-pane" :style="{ flexGrow: splitPercent }">
        <div class="wb-tabs-bar" role="tablist" aria-label="右侧工作台视图切换">
          <div class="wb-tabs-list">
            <button
              v-if="fleet.currentSession"
              type="button"
              role="tab"
              :aria-selected="rightMode === 'diff'"
              class="wb-tab-btn"
              :class="{ 'is-active': rightMode === 'diff' }"
              @click="setRightPane('diff')"
            >
              <OpusIcon name="branch" />
              <span>评审</span>
              <span v-if="fleet.currentDiff?.summary?.filesChanged" class="wb-tab-badge num">
                {{ fleet.currentDiff.summary.filesChanged }}
              </span>
            </button>
            <button
              v-if="fleet.currentSession"
              type="button"
              role="tab"
              :aria-selected="rightMode === 'tree'"
              class="wb-tab-btn"
              :class="{ 'is-active': rightMode === 'tree' }"
              @click="setRightPane('tree')"
            >
              <OpusIcon name="layers" />
              <span>目录</span>
            </button>
            <button
              v-if="fleet.activeSessionKey && (rightMode === 'file' || fleet.filePreviewBySession[fleet.activeSessionKey])"
              type="button"
              role="tab"
              :aria-selected="rightMode === 'file'"
              class="wb-tab-btn"
              :class="{ 'is-active': rightMode === 'file' }"
              @click="setRightPane('file')"
            >
              <OpusIcon name="file" />
              <span>预览</span>
            </button>
            <button
              v-if="fleet.currentSession"
              type="button"
              role="tab"
              :aria-selected="rightMode === 'terminal'"
              class="wb-tab-btn"
              :class="{ 'is-active': rightMode === 'terminal' }"
              @click="setRightPane('terminal')"
            >
              <OpusIcon name="terminal" />
              <span>终端</span>
            </button>
            <button
              type="button"
              role="tab"
              :aria-selected="rightMode === 'split'"
              class="wb-tab-btn"
              :class="{ 'is-active': rightMode === 'split' }"
              @click="setRightPane('split')"
            >
              <OpusIcon name="grid" />
              <span>分屏</span>
            </button>
          </div>
          <button
            type="button"
            class="icon-btn wb-close-btn"
            aria-label="关闭工作台面板"
            title="关闭工作台"
            @click="setRightPane('none')"
          >
            <OpusIcon name="x" />
          </button>
        </div>

        <div class="wb-pane-body">
          <template v-if="rightMode === 'split'">
            <div class="right-hdr">
              <select v-model="secondaryTabKey" class="input right-select" aria-label="选择并排对照会话">
                <option value="">选择另一台机器或代理会话…</option>
                <option
                  v-for="s in fleet.allSessions"
                  :key="sessionKey(s.nodeId, s.provider, s.sessionId)"
                  :value="sessionKey(s.nodeId, s.provider, s.sessionId)"
                >
                  {{ fleet.nodes.find(n => n.id === s.nodeId)?.name || s.nodeId }} · {{ getProviderMeta(s.provider).label }} · {{ s.title }}
                </option>
              </select>
              <button type="button" class="icon-btn" title="在右侧新建会话" @click="openCreateSession(undefined, undefined, undefined, true)"><OpusIcon name="plus" /></button>
            </div>
            <AgentChatThread
              v-if="secondaryTabKey"
              :session-key="secondaryTabKey"
              @action="emit('action', $event)"
              @open-handoff="openHandoffDialog"
              @open-diff="openDiffPanel"
              @open-file="openFilePreview"
              @open-subagent="handleOpenSubagent"
              @clear-session="openCreateSession(undefined, undefined, undefined, true)"
            />
            <div v-else class="right-empty">
              <p class="faint">选择已有会话，或点右上角的加号新建会话。</p>
            </div>
          </template>

          <DiffReviewDrawer
            v-else-if="rightMode === 'diff'"
            :embedded="true"
            :session-key="fleet.activeSessionKey"
            :diff="fleet.currentDiff"
            :checkpoints="fleet.currentCheckpoints"
            :selected-checkpoint-id="selectedCheckpointId || undefined"
            :focus-file-path="diffFocusFile"
            :is-worktree="Boolean(fleet.currentSession?.worktreePath)"
            @refresh="fleet.requestSessionDiff(fleet.activeSessionKey, selectedCheckpointId || undefined)"
            @close="setRightPane('none')"
            @revert-latest="fleet.revertCheckpoint(fleet.activeSessionKey, $event)"
            @revert-files="(paths, cpId) => fleet.revertFiles(fleet.activeSessionKey, paths, cpId)"
            @revert-hunk="(fp, patch) => fleet.revertDiffHunk(fleet.activeSessionKey, fp, patch)"
            @commit-changes="(msg, paths) => fleet.commitWorkspaceChanges(fleet.activeSessionKey, msg, paths)"
            @select-checkpoint="selectCheckpointInDiff"
            @open-file="openFilePreview"
            @merge-worktree="fleet.mergeSessionWorktree(fleet.activeSessionKey)"
            @ask-about-file="primaryThreadRef?.insertFileReference($event)"
            @comment-line="txt => primaryThreadRef?.insertFileReference(txt)"
          />

          <FileViewerDrawer
            v-else-if="rightMode === 'file'"
            :preview="fleet.activeSessionKey ? fleet.filePreviewBySession[fleet.activeSessionKey] ?? null : null"
            @close="fleet.closeFilePreview(); setRightPane('none')"
            @refresh="openFilePreview($event)"
            @cite-lines="primaryThreadRef?.insertFileReference($event)"
            @ask-about-file="primaryThreadRef?.insertFileReference($event)"
          />

          <WorkspaceTreeDrawer
            v-else-if="rightMode === 'tree'"
            :session-key="fleet.activeSessionKey"
            @close="setRightPane('none')"
            @open-file="openFilePreview($event)"
            @cite-file="primaryThreadRef?.insertFileReference($event)"
          />

          <TerminalDrawer
            v-else-if="rightMode === 'terminal'"
            :session-key="fleet.activeSessionKey"
            @close="setRightPane('none')"
          />
        </div>
      </aside>
    </template>

    <CommandPaletteModal
      :open="showCommandPalette"
      :sessions="paletteSessions"
      :files="paletteFiles"
      :commands="paletteCommands"
      :message-hits="paletteMessageHits"
      @close="showCommandPalette = false"
      @select-session="fleet.activateSession($event)"
      @open-file="openFilePreview($event)"
      @run-command="handlePaletteRunCommand"
    />

    <!-- 新建会话弹窗 -->
    <div v-if="showNewSession" class="modal-scrim" @click.self="showNewSession = false">
      <div class="modal-card card">
        <h3>新建工作会话</h3>
        <div class="field">
          <label>目标机器节点</label>
          <select v-model="newSessionNodeId" @change="changeCreateNode" class="input">
            <option v-for="n in sortedNodes" :key="n.id" :value="n.id">{{ n.name }} ({{ nodeStatusText(n.id, n.status) }})</option>
          </select>
        </div>
        <div class="field">
          <label>执行代理引擎</label>
          <select v-model="newSessionProvider" class="input">
            <option v-for="ad in readyAt(newSessionNodeId)" :key="ad.provider" :value="ad.provider">{{ getProviderMeta(ad.provider).label }}</option>
          </select>
        </div>
        <div class="field">
          <label>工作目录（须在节点 allowedRoots 内）</label>
          <input v-model="newSessionCwd" class="input" placeholder="例如 /Users/you/Projects/Studiolo" />
          <div v-if="fleet.nodes.find(n => n.id === newSessionNodeId)?.allowedRoots.length" class="mchat-chips">
            <button
              v-for="r in fleet.nodes.find(n => n.id === newSessionNodeId)?.allowedRoots"
              :key="r"
              type="button"
              class="chip"
              @click="newSessionCwd = r"
            >
              {{ leafPathName(r) }}
            </button>
          </div>
        </div>
        <label class="toggle-row">
          <input v-model="newSessionWorktree" type="checkbox" />
          <span>自动创建隔离 Git Worktree（`.studiolo-worktrees/`）防止并发冲突</span>
        </label>
        <div class="modal-foot">
          <button type="button" class="btn btn-ghost" @click="showNewSession = false">取消</button>
          <button type="button" class="btn btn-primary" :disabled="!readyAt(newSessionNodeId).some(a => a.provider === newSessionProvider)" @click="submitNewSession">启动会话</button>
        </div>
      </div>
    </div>

    <!-- @Handoff 跨端转交弹窗 -->
    <div v-if="showHandoff" class="modal-scrim" @click.self="showHandoff = false">
      <div class="modal-card card">
        <h3>@Handoff 跨节点任务转交</h3>
        <div class="field">
          <label>目标机器节点</label>
          <select v-model="handoffTargetNode" @change="handoffTargetProvider = readyAt(handoffTargetNode)[0]?.provider ?? 'codex'" class="input">
            <option v-for="n in fleet.nodes" :key="n.id" :value="n.id">{{ n.name }} ({{ n.status }})</option>
          </select>
        </div>
        <div class="field">
          <label>目标 Agent</label>
          <select v-model="handoffTargetProvider" class="input">
            <option v-for="ad in readyAt(handoffTargetNode)" :key="ad.provider" :value="ad.provider">{{ getProviderMeta(ad.provider).label }}</option>
          </select>
        </div>
        <div class="field">
          <label>交接任务摘要</label>
          <textarea v-model="handoffSummary" class="input" rows="4" placeholder="描述请目标 Agent 接力审阅、构建或测试的内容…" />
        </div>
        <div v-if="handoffArtifact" class="faint" style="font-size:12px">
          将随 E2EE 密钥信封一并转交附件：<b>{{ handoffArtifact.fileName }}</b>
        </div>
        <div class="modal-foot">
          <button type="button" class="btn btn-ghost" @click="showHandoff = false">取消</button>
          <button type="button" class="btn btn-primary" :disabled="!readyAt(handoffTargetNode).some(a => a.provider === handoffTargetProvider)" @click="submitHandoff">派发转交</button>
        </div>
      </div>
    </div>

    <!-- 群发对比 (Fan-out) 弹窗 -->
    <div v-if="showFanout" class="modal-scrim" @click.self="showFanout = false">
      <div class="modal-card card">
        <h3>群发对比 (Fan-out)</h3>
        <p class="faint" style="font-size:12.5px;margin:0">同时向多台主机或不同 Agent 发送同一需求，自动开启右侧分屏对照。</p>
        <div class="fanout-grid">
          <template v-for="n in fleet.nodes" :key="n.id">
            <label v-for="ad in readyAt(n.id)" :key="`${n.id}-${ad.provider}`" class="toggle-row">
              <input
                type="checkbox"
                :checked="isFanoutChecked(n.id, ad.provider)"
                @change="toggleFanoutTarget(n.id, ad.provider)"
              />
              <span>{{ n.name }} · {{ getProviderMeta(ad.provider).label }}</span>
            </label>
          </template>
        </div>
        <textarea v-model="fanoutPrompt" class="input" rows="3" placeholder="输入并行对比的任务指令…" />
        <div class="modal-foot">
          <button type="button" class="btn btn-ghost" @click="showFanout = false">取消</button>
          <button type="button" class="btn btn-primary" :disabled="fanoutTargets.length < 2 || !fanoutPrompt.trim()" @click="submitFanout">并行派发</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.fleet-workspace {
  display: flex;
  height: 100%;
  min-height: 0;
  min-width: 0;
}
.both-panes .fleet-tree-pane { max-width: 26%; }
.fleet-workspace > .fleet-right-pane { flex-basis: 0; min-width: 120px; overflow: hidden; container-type: inline-size; }
.fleet-workspace:has(.fleet-right-pane) .fleet-main { min-width: 120px; }
.fleet-workspace { overflow: hidden; }
.fleet-tree-pane { overflow-x: clip; }
@starting-style {
  .fleet-workspace > .fleet-tree-pane, .fleet-workspace > .fleet-right-pane { width: 0 !important; }
}
.fleet-tree-pane, .fleet-right-pane { transition: width 180ms ease-out; }
.is-resizing .fleet-tree-pane, .is-resizing .fleet-right-pane { transition: none; }
.tree-top-actions .icon-btn { width: 23px; flex: none; }
.tree-top-actions strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-right: auto; font-size: 13px; }
.session-actions { position: relative; }
.session-actions summary { list-style: none; cursor: pointer; }
.session-actions summary::-webkit-details-marker { display: none; }
.action-list {
  position: absolute; top: calc(100% + 6px); right: 0; z-index: 35;
  display: grid; width: max-content; padding: 5px; border: 1px solid var(--line);
  border-radius: var(--r-md); background: var(--solid); box-shadow: var(--shadow-2);
}
.action-list button { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: var(--r-sm); }
.action-list button:hover, .action-list button:focus-visible { background: var(--surface-2); }
.action-list button:last-child { border-top: 1px solid var(--line); }


/* 左侧四层节点项目树 */
.fleet-tree-pane {
  flex: none;
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}
.tree-top {
  display: grid;
  gap: 8px;
  padding: 10px 10px 8px;
  border-bottom: 1px solid var(--line);
}
.tree-search {
  position: relative;
  display: flex;
  align-items: center;
}
.tree-search .i {
  position: absolute;
  left: 9px;
  width: 14px;
  height: 14px;
  color: var(--text-3);
  pointer-events: none;
}
.tree-search input {
  min-width: 0;
  width: 100%;
  height: 30px;
  padding: 0 10px 0 28px;
  border-radius: var(--r-sm);
  border: 1px solid var(--line);
  background: var(--solid);
  font-size: 12px;
  outline: 0;
}
.tree-search input:focus { border-color: var(--accent-line); }
.tree-top-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 2px;
}

.tree-body {
  grid-template-columns: minmax(0, 1fr);
  overflow-x: hidden;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px 8px;
  display: grid;
  gap: 12px;
  align-content: start;
}
.tree-node-group, .tree-root-block, .tree-branch-list, .tree-top { min-width: 0; grid-template-columns: minmax(0, 1fr); }
.tree-node-group {
  display: grid;
  gap: 6px;
}
.tree-node-hdr {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: var(--r-sm);
  background: var(--surface-3);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.tree-node-hdr.is-selected {
  background: var(--solid);
  box-shadow: inset 0 0 0 1px var(--line-strong);
}
.tree-node-hdr .i { width: 14px; height: 14px; color: var(--text-2); flex: none; }
.tree-node-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tree-mini-btn {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: var(--r-xs);
  color: var(--text-3);
  font-size: 13px;
  flex: none;
}
.tree-mini-btn:hover { background: var(--surface-3); color: var(--text); }

.tree-roots {
  padding-left: 6px;
  min-width: 0;
  grid-template-columns: minmax(0, 1fr);
  display: grid;
  gap: 8px;
}
.tree-root-block {
  display: grid;
  gap: 4px;
}
.tree-root-hdr {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 6px;
  font-size: 12px;
  font-weight: 550;
  color: var(--text-2);
}
.tree-root-hdr .i { width: 13px; height: 13px; color: var(--text-3); flex: none; }
.tree-root-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tree-empty-roots {
  padding: 2px 12px;
  font-size: 11px;
  color: var(--text-3);
}
.tree-branch-list {
  margin-left: 11px;
  padding-left: 8px;
  border-left: 1px solid var(--line);
  display: grid;
  gap: 3px;
}
.tree-sess-row {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 7px;
  border-radius: var(--r-sm);
  font-size: 12px;
  color: var(--text-2);
  cursor: pointer;
}
.tree-sess-row:hover {
  background: var(--surface-3);
  color: var(--text);
}
.tree-sess-row.is-active {
  background: var(--solid);
  color: var(--text);
  box-shadow: inset 2px 0 0 var(--accent), var(--shadow-1);
}
.tree-split-trigger { opacity: 0; transition: opacity 120ms; }
.tree-sess-row:hover .tree-split-trigger { opacity: 1; }
.tree-sess-meta {
  flex: 1;
  min-width: 0;
}
.tree-sess-title {
  font-weight: 550;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tree-sess-wt {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 10.5px;
  color: var(--warn);
}
.tree-sess-wt .i { width: 11px; height: 11px; }
.tree-sess-hit {
  margin-top: 2px;
  font-size: 11px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.tree-rename-input {
  width: 100%;
  height: 24px;
  padding: 2px 6px;
  font-size: 12px;
}
.diff-count-dot {
  padding: 0 5px;
  border-radius: 999px;
  font-size: 10.5px;
  background: var(--accent-soft);
  color: var(--accent);
}
.tree-eng {
  font-size: 10px;
  font-weight: 650;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--surface-3);
  color: var(--text-3);
  flex: none;
}

.tree-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-3);
  flex: none;
}
.tree-dot.is-ready { background: var(--ok); }
.tree-dot.is-running { background: var(--ok); box-shadow: 0 0 0 3px var(--ok-soft); }
.tree-dot.is-approval { background: var(--warn); box-shadow: 0 0 0 3px var(--warn-soft); }

.tree-empty-state {
  display: grid;
  gap: 8px;
  padding: 12px;
  border-radius: var(--r-md);
  background: var(--solid);
  box-shadow: var(--shadow-1);
}
.tree-empty-state p { margin: 0; font-size: 12px; }

/* 中央多标签 + 对话主区域 */
.fleet-main {
  display: flex;
  flex-direction: column;
  container-type: inline-size;
  flex: 1 1 0%;
  min-width: 0;
  min-height: 0;
  grid-template-columns: minmax(0, 1fr);
  overflow: hidden;
}
.chat-tabs-h, .conn-banner { flex: none; }
@container (max-width: 530px) {
  .tabs-actions > button span { display: none; }
}
.chat-tabs-h {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 8px;
  padding: 7px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  min-width: 0;
}
.tabs-scroll {
  display: flex;
  align-items: center;
  gap: 5px;
  flex: 1 1 140px;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
}
.chat-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 8px 0 10px;
  border-radius: var(--r-sm);
  font-size: 12px;
  color: var(--text-2);
  max-width: 210px;
  flex: none;
}
.chat-tab:hover { background: var(--surface-3); color: var(--text); }
.chat-tab.is-active {
  background: var(--solid);
  color: var(--text);
  font-weight: 600;
  box-shadow: var(--shadow-1);
}
.chat-tab-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chat-tab-eng {
  font-size: 10px;
  color: var(--text-3);
}
.chat-tab-close {
  font-size: 13px;
  line-height: 1;
  color: var(--text-3);
  padding: 0 2px;
}
.chat-tab-close:hover { color: var(--text); }
.chat-empty-tab {
  font-size: 13px;
  font-weight: 600;
  padding: 0 6px;
  color: var(--text);
}
.tabs-actions {
  display: flex;
  align-items: center;
  gap: 5px;
  flex: none;
}

/* 右侧并排分屏 / 统一工作台面板 */
.fleet-right-pane {
  flex: none;
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
}
.wb-tabs-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 5px 8px 5px 10px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  flex: none;
}
.wb-tabs-list {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow-x: auto;
  scrollbar-width: none;
}
.wb-tab-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 9px;
  border: 0;
  border-radius: var(--r-sm);
  background: transparent;
  color: var(--text-3);
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;
  cursor: pointer;
}
.wb-tab-btn:hover { background: var(--surface-3); color: var(--text); }
.wb-tab-btn.is-active {
  background: var(--solid);
  color: var(--text);
  font-weight: 600;
  box-shadow: var(--shadow-1);
}
.wb-tab-btn .i { width: 13px; height: 13px; }
.wb-tab-badge {
  padding: 0 5px;
  border-radius: 999px;
  font-size: 10px;
  background: var(--accent-soft);
  color: var(--accent);
}
.wb-close-btn { width: 26px; height: 26px; flex: none; }
.wb-pane-body {
  flex: 1;
  min-height: 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.wb-pane-body > * {
  flex: 1 1 0;
  min-height: 0;
}
.wb-pane-body > .right-hdr {
  flex: none;
}
.right-hdr {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
}
.right-hdr .spacer { flex: 1; }
.right-title { font-size: 13px; font-weight: 650; }
.right-select {
  flex: 1;
  min-width: 0;
  height: 28px;
  font-size: 12px;
  padding: 0 8px;
}
.right-empty {
  padding: 28px 18px;
  text-align: center;
  font-size: 12.5px;
}
.root-list { display: grid; gap: 5px; }
.root-path {
  display: block;
  padding: 6px 8px;
  border-radius: var(--r-xs);
  background: var(--surface-2);
  font-size: 11.5px;
  word-break: break-all;
}
.kv-pill { padding: 6px 10px; border-radius: var(--r-sm); background: var(--surface-2); }

/* 弹窗 */
.modal-scrim {
  position: fixed;
  inset: 0;
  z-index: 120;
  display: grid;
  place-items: center;
  background: var(--scrim);
  padding: 20px;
}
.modal-card {
  width: min(480px, 100%);
  display: grid;
  gap: 14px;
  background: var(--solid);
  box-shadow: var(--shadow-pop);
}
.modal-card h3 { margin: 0; font-size: 16px; }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; }
.toggle-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--text-2);
}
.fanout-grid { display: grid; gap: 6px; max-height: 180px; overflow: auto; }

/* 移动端 */
.chatpage {
  grid-template-rows: auto minmax(0, 1fr);
}
.mchat-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
}
.mchat-bar .spacer { flex: 1; }
.m-tabs-row {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  padding: 6px 12px;
  border-bottom: 1px solid var(--line);
  scrollbar-width: none;
}
.m-tab-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: var(--r-pill);
  font-size: 12px;
  background: var(--surface-2);
  color: var(--text-2);
  white-space: nowrap;
  flex: none;
}
.m-tab-chip[aria-pressed="true"] {
  background: var(--solid);
  color: var(--text);
  font-weight: 600;
  box-shadow: var(--shadow-1);
}
.mchat-drawer {
  position: absolute;
  top: 52px;
  left: 12px;
  right: 12px;
  z-index: 40;
  display: grid;
  gap: 8px;
  background: var(--solid);
  box-shadow: var(--shadow-pop);
}
.mchat-thread { min-height: 0; }
.mchat-sec { font-size: 11.5px; font-weight: 600; color: var(--text-3); }
.mchat-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.tabs-actions .is-notify-on {
  color: var(--accent);
  background: var(--accent-soft);
}
</style>
