<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import AgentChatThread from '../components/chat/AgentChatThread.vue'
import CommandPaletteModal from '../components/chat/CommandPaletteModal.vue'
import DiffReviewDrawer from '../components/chat/DiffReviewDrawer.vue'
import FileViewerDrawer from '../components/chat/FileViewerDrawer.vue'
import SideChatDrawer from '../components/chat/SideChatDrawer.vue'
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
import { chatBubbleStyleLabel, chatBubbleStyleOptions, useWorkbenchTheme } from '../composables/useWorkbenchTheme'
import type { AdapterProvider, AgentNode, ArtifactRef, ChatSession } from '../types/fleet'

const props = defineProps<{ mobile?: boolean }>()

const emit = defineEmits<{
  navigate: [page: string]
  action: [message: string]
  mobileFullscreen: [fullscreen: boolean]
}>()

const fleet = useFleetStore()
const { bubbleStyle, setBubbleStyle } = useWorkbenchTheme()

function cycleBubbleStyle() {
  const idx = chatBubbleStyleOptions.findIndex(o => o.id === bubbleStyle.value)
  const next = chatBubbleStyleOptions[(idx + 1) % chatBubbleStyleOptions.length]
  setBubbleStyle(next.id)
  emit('action', `对话气泡样式已切换为「${next.title}」`)
}

const TREE_DEFAULT_W = 244
const TREE_MIN_W = 128
const TREE_MAX_W = 440
const TREE_SNAP_CLOSE = 84
const workspace = ref<HTMLElement>()
const primaryThreadRef = ref<InstanceType<typeof AgentChatThread> | null>(null)
const treeOpen = ref(true)
const treeWidth = ref(readStoredWidth('studiolo:chat-tree-w', TREE_DEFAULT_W, TREE_MIN_W, TREE_MAX_W))
type RightPaneMode = 'none' | 'split' | 'diff' | 'file' | 'tree' | 'terminal' | 'side' | 'subagent'
const rightMode = ref<RightPaneMode>('none')
const lastWorkbenchTab = ref<Exclude<RightPaneMode, 'none'>>('diff')
const sideChatSessionKey = ref<string>('')
const focusedSubagentKey = ref<string>('')
const mobileWorkbench = ref<'none' | 'diff' | 'tree' | 'file' | 'terminal'>('none')
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
const pinnedTabKeys = ref<string[]>([])
const tabContextMenu = ref<{ key: string; x: number; y: number } | null>(null)
const treeFilterMode = ref<'all' | 'running' | 'approval' | 'diff'>('all')
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
const mobileView = ref<'inbox' | 'thread'>('inbox')
const mobileNodeFilter = ref<string>('all')
const mobileStatusFilter = ref<'all' | 'running' | 'diff'>('all')
const mobileInboxQuery = ref('')
const mobileSearchOpen = ref(false)
const mobileSearchInputRef = ref<HTMLInputElement | null>(null)
const mobileFilterMenuOpen = ref(false)
const mobileFilterSub = ref<'node' | 'status' | null>(null)
const mobileSessionSheetRef = ref<HTMLDialogElement | null>(null)
const mobileRenameDraft = ref('')
const mobileRenaming = ref(false)

const mobileHasActiveFilter = computed(() =>
  mobileNodeFilter.value !== 'all' || mobileStatusFilter.value !== 'all',
)

const mobileActiveFilterLabel = computed(() => {
  const parts: string[] = []
  if (mobileNodeFilter.value !== 'all') {
    const n = fleet.nodes.find(item => item.id === mobileNodeFilter.value)
    if (n) parts.push(n.name)
  }
  if (mobileStatusFilter.value === 'running') parts.push('运行中')
  else if (mobileStatusFilter.value === 'diff') parts.push('有改动')
  return parts.join(' · ')
})

function toggleMobileSearch() {
  mobileFilterMenuOpen.value = false
  mobileSearchOpen.value = !mobileSearchOpen.value
  if (!mobileSearchOpen.value) {
    mobileInboxQuery.value = ''
  } else {
    void nextTick(() => mobileSearchInputRef.value?.focus())
  }
}

function toggleMobileFilterMenu() {
  mobileFilterMenuOpen.value = !mobileFilterMenuOpen.value
  if (!mobileFilterMenuOpen.value) {
    mobileFilterSub.value = null
  }
}

function closeMobileFilterMenu() {
  mobileFilterMenuOpen.value = false
  mobileFilterSub.value = null
}

function toggleMobileFilterSub(sub: 'node' | 'status') {
  mobileFilterSub.value = mobileFilterSub.value === sub ? null : sub
}

function resetMobileFilters() {
  mobileNodeFilter.value = 'all'
  mobileStatusFilter.value = 'all'
}

watch(
  [() => props.mobile, mobileView],
  ([isMob, view]) => {
    emit('mobileFullscreen', Boolean(isMob && view === 'thread'))
  },
  { immediate: true },
)

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
  emit('mobileFullscreen', false)
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
    return
  }
  // Ctrl/Cmd + 1~9 快速切换已打开会话标签
  if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && !ev.shiftKey && /^[1-9]$/.test(ev.key)) {
    const idx = Number(ev.key) - 1
    const targetTab = openTabs.value[idx]
    if (targetTab) {
      ev.preventDefault()
      fleet.activateSession(targetTab.key)
    }
  }
}

function dismissTabMenu() {
  tabContextMenu.value = null
}

function openTabContextMenu(key: string, ev: MouseEvent) {
  ev.preventDefault()
  tabContextMenu.value = { key, x: ev.clientX, y: ev.clientY }
}

function togglePinTab(key: string) {
  if (pinnedTabKeys.value.includes(key)) {
    pinnedTabKeys.value = pinnedTabKeys.value.filter(k => k !== key)
  } else {
    pinnedTabKeys.value = [...pinnedTabKeys.value, key]
  }
  dismissTabMenu()
}

function closeOtherTabs(keepKey: string) {
  openTabKeys.value = openTabKeys.value.filter(k => k === keepKey || pinnedTabKeys.value.includes(k))
  if (!openTabKeys.value.includes(fleet.activeSessionKey)) {
    fleet.activateSession(keepKey)
  }
  dismissTabMenu()
}

function closeRightTabs(anchorKey: string) {
  const idx = openTabKeys.value.indexOf(anchorKey)
  if (idx >= 0) {
    openTabKeys.value = openTabKeys.value.filter((k, i) => i <= idx || pinnedTabKeys.value.includes(k))
    if (!openTabKeys.value.includes(fleet.activeSessionKey)) {
      fleet.activateSession(anchorKey)
    }
  }
  dismissTabMenu()
}

function resolveAllowedSessionCwd(node: AgentNode | null | undefined, candidateCwd?: string): string {
  if (!node) return candidateCwd || ''
  if (
    candidateCwd &&
    (!node.allowedRoots?.length ||
      node.allowedRoots.some(r => sessionBelongsToRoot({ cwd: candidateCwd } as ChatSession, r)))
  ) {
    return candidateCwd
  }
  return node.allowedRoots?.[0] ?? ''
}

function quickCreateSession(ev?: MouseEvent) {
  if (ev?.shiftKey) {
    openCreateSession()
    return
  }
  const node =
    (fleet.selectedNode?.status === 'online' ? fleet.selectedNode : null) ??
    fleet.nodes.find(n => n.status === 'online') ??
    fleet.selectedNode
  if (!node || node.status !== 'online') {
    openCreateSession()
    return
  }
  const prevSess = fleet.currentSession
  const sourceKey = fleet.activeSessionKey || undefined
  const preferredProv = prevSess?.provider ?? fleet.selectedProvider
  const readyAdapter =
    node.adapters.find(a => a.provider === preferredProv && a.status === 'ready') ??
    node.adapters.find(a => a.status === 'ready')
  if (!readyAdapter) {
    openCreateSession(node)
    return
  }
  const sameNodeCwd = prevSess?.nodeId === node.id ? prevSess?.cwd : undefined
  const cwd = resolveAllowedSessionCwd(node, sameNodeCwd) || undefined
  fleet.activeSessionKey = ''
  fleet.openSession({
    nodeId: node.id,
    provider: readyAdapter.provider,
    cwd,
    inheritFromKey: sourceKey,
    onOpened: k => {
      if (!openTabKeys.value.includes(k)) {
        openTabKeys.value = [...openTabKeys.value, k]
      }
      fleet.activateSession(k)
    },
  })
  emit('action', `已创建 ${getProviderMeta(readyAdapter.provider).label} 新会话`)
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

function sessionMatchesStateFilter(sess: ChatSession): boolean {
  if (treeFilterMode.value === 'all') return true
  const k = sessionKey(sess.nodeId, sess.provider, sess.sessionId)
  if (treeFilterMode.value === 'running') return Boolean(fleet.runningBySession[k])
  if (treeFilterMode.value === 'approval') {
    return fleet.pendingApprovalsList.some(c => c.nodeId === sess.nodeId && c.sessionId === sess.sessionId)
  }
  if (treeFilterMode.value === 'diff') {
    return Boolean(sess.hasDiff || fleet.diffBySession[k]?.files?.length)
  }
  return true
}

function sessionsForNodeRoot(nodeId: string, root: string): ChatSession[] {
  const term = treeQuery.value.trim()
  return fleet.allSessions.filter(s => {
    if (s.nodeId !== nodeId || !sessionBelongsToRoot(s, root)) return false
    if (!sessionMatchesStateFilter(s)) return false
    if (!term) return true
    return searchHits.value.has(sessionKey(s.nodeId, s.provider, s.sessionId))
  })
}

function orphanSessionsForNode(node: AgentNode): ChatSession[] {
  const term = treeQuery.value.trim()
  return fleet.allSessions.filter(s => {
    if (s.nodeId !== node.id) return false
    if (node.allowedRoots.some(r => sessionBelongsToRoot(s, r))) return false
    if (!sessionMatchesStateFilter(s)) return false
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
  if (pinnedTabKeys.value.includes(sKey)) return
  openTabKeys.value = openTabKeys.value.filter(k => k !== sKey)
  if (fleet.activeSessionKey === sKey) {
    const fallback = openTabKeys.value[openTabKeys.value.length - 1]
    if (fallback) fleet.activateSession(fallback)
    else fleet.activeSessionKey = ''
  }
}

const backgroundApprovals = computed(() =>
  fleet.pendingApprovalsList.filter(
    c => sessionKey(c.nodeId, c.provider, c.sessionId) !== fleet.activeSessionKey,
  ),
)

function jumpToApprovalSession(nodeId: string, provider: AdapterProvider, sessionId: string) {
  const k = sessionKey(nodeId, provider, sessionId)
  if (!openTabKeys.value.includes(k)) openTabKeys.value = [...openTabKeys.value, k]
  fleet.activateSession(k)
}

function setRightPane(
  mode: RightPaneMode,
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
  const narrowViewport = (workspace.value?.clientWidth ?? window.innerWidth) < 1180
  if (!wasOpen && !props.mobile && treeOpen.value && narrowViewport) {
    autoCollapsedLeft.value = true
    treeOpen.value = false
  }
  if (mode !== 'side' && mode !== 'subagent') {
    lastWorkbenchTab.value = mode
  }

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

function toggleRightMode(target: Exclude<RightPaneMode, 'none'>) {
  if (rightMode.value === target) {
    setRightPane('none')
    return
  }
  setRightPane(target)
}

function openMobileWorkbench(mode: 'diff' | 'tree' | 'file' | 'terminal') {
  if (!fleet.activeSessionKey) {
    emit('action', '请先进入一个活跃会话')
    return
  }
  mobileWorkbench.value = mode
  if (mode === 'diff') fleet.requestSessionDiff(fleet.activeSessionKey)
  else if (mode === 'tree') fleet.requestWorkspaceTree('', fleet.activeSessionKey)
  else if (mode === 'terminal' && !fleet.terminalBySession[fleet.activeSessionKey]) {
    fleet.openTerminal(fleet.activeSessionKey)
  }
}

async function handleOpenSideChat(question?: string) {
  const parentKey = fleet.activeSessionKey
  if (!parentKey) {
    emit('action', '请先进入一个活跃会话再开启 /btw 侧边问答')
    return
  }
  setRightPane('side')
  const key = await fleet.openOrSendSideChat(parentKey, question)
  if (key) sideChatSessionKey.value = key
}

function promoteSideToMain(sKey: string) {
  if (!sKey) return
  if (!openTabKeys.value.includes(sKey)) openTabKeys.value = [...openTabKeys.value, sKey]
  fleet.activateSession(sKey)
  setRightPane('none')
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
  if (props.mobile) {
    diffFocusFile.value = focusFile
    openMobileWorkbench('diff')
    return
  }
  setRightPane('diff', { focusFile })
}

function openFilePreview(filePath: string, line?: number) {
  if (!fleet.activeSessionKey) {
    emit('action', '请先进入一个活跃会话再预览文件')
    return
  }
  fleet.requestFileContent(filePath, fleet.activeSessionKey, line)
  if (props.mobile) {
    mobileWorkbench.value = 'file'
    return
  }
  setRightPane('file')
}

function handleOpenSubagent(subSessionId: string) {
  const cur = fleet.currentSession
  if (!cur || !subSessionId) return
  const existingKey = sessionKey(cur.nodeId, cur.provider, subSessionId)
  if (fleet.sessionsByKey[existingKey]) {
    if (!props.mobile) {
      focusedSubagentKey.value = existingKey
      fleet.loadSessionHistory(existingKey)
      setRightPane('subagent')
    } else {
      openSessionTab(fleet.sessionsByKey[existingKey])
    }
    return
  }
  fleet.openSession({
    nodeId: cur.nodeId,
    provider: cur.provider,
    cwd: cur.cwd || undefined,
    sessionId: subSessionId,
    onOpened: k => {
      if (!props.mobile) {
        focusedSubagentKey.value = k
        fleet.loadSessionHistory(k)
        setRightPane('subagent')
      } else {
        if (!openTabKeys.value.includes(k)) openTabKeys.value = [...openTabKeys.value, k]
        fleet.activateSession(k)
      }
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
    // 优先继承当前活跃会话/当前选中的可用引擎，而非总是回退到节点首个引擎
    const preferredProv = fleet.currentSession?.provider ?? fleet.selectedProvider
    const preferredReady = targetNode?.adapters.find(a => a.provider === preferredProv && a.status === 'ready')
    const firstReady = targetNode?.adapters.find(a => a.status === 'ready')
    newSessionProvider.value = preferredReady?.provider ?? firstReady?.provider ?? preferredProv
  }
  const sameNodeCwd = fleet.currentSession?.nodeId === targetNode?.id ? fleet.currentSession?.cwd : undefined
  newSessionCwd.value = presetCwd ?? resolveAllowedSessionCwd(targetNode, sameNodeCwd)
  showNewSession.value = true
}

function submitNewSession() {
  const targetId = newSessionNodeId.value || fleet.selectedNode?.id
  if (!targetId) {
    emit('action', '请先选择在线节点')
    return
  }
  const targetNode = fleet.nodes.find(n => n.id === targetId)
  const sourceSessionKey = fleet.activeSessionKey || undefined
  const resolvedCwd = resolveAllowedSessionCwd(targetNode, newSessionCwd.value.trim()) || undefined
  if (!createInSplit.value) {
    fleet.activeSessionKey = ''
  }
  fleet.openSession({
    nodeId: targetId,
    provider: newSessionProvider.value,
    cwd: resolvedCwd,
    useWorktree: newSessionWorktree.value,
    inheritFromKey: sourceSessionKey,
    onOpened: createInSplit.value
      ? key => { secondaryTabKey.value = key }
      : key => {
          if (!openTabKeys.value.includes(key)) {
            openTabKeys.value = [...openTabKeys.value, key]
          }
          fleet.activateSession(key)
        },
  })
  showNewSession.value = false
  if (props.mobile) {
    mobileView.value = 'thread'
  }
  emit('action', `已请求创建 ${getProviderMeta(newSessionProvider.value).label} 会话`)
}

const mobileOnlineCount = computed(() => fleet.nodes.filter(n => n.status === 'online').length)

const mobileOtherApprovalsCount = computed(() =>
  fleet.pendingApprovalsList.filter(item => sessionKey(item.nodeId, item.provider, item.sessionId) !== fleet.activeSessionKey).length,
)

const mobileBackgroundApprovals = computed(() =>
  fleet.pendingApprovalsList
    .filter(item => sessionKey(item.nodeId, item.provider, item.sessionId) !== fleet.activeSessionKey)
    .map(card => {
      const key = sessionKey(card.nodeId, card.provider, card.sessionId)
      return {
        card,
        key,
        sessionTitle: fleet.sessionsByKey[key]?.title || getProviderMeta(card.provider).label,
      }
    }),
)

const mobileInboxSessions = computed(() => {
  const term = mobileInboxQuery.value.trim().toLowerCase()
  const rows = fleet.allSessions
    .filter(sess => {
      if (mobileNodeFilter.value !== 'all' && sess.nodeId !== mobileNodeFilter.value) return false
      const k = sessionKey(sess.nodeId, sess.provider, sess.sessionId)
      if (mobileStatusFilter.value === 'running' && !fleet.runningBySession[k]) return false
      if (mobileStatusFilter.value === 'diff' && !(sess.hasDiff || fleet.diffBySession[k]?.files?.length)) return false
      if (term) {
        const nodeName = fleet.nodes.find(n => n.id === sess.nodeId)?.name ?? ''
        const hay = `${sess.title} ${nodeName} ${sess.provider} ${sess.cwd || ''}`.toLowerCase()
        if (!hay.includes(term)) return false
      }
      return true
    })
    .map(sess => {
      const key = sessionKey(sess.nodeId, sess.provider, sess.sessionId)
      const nodeName = fleet.nodes.find(n => n.id === sess.nodeId)?.name ?? sess.nodeId
      const hasApproval = fleet.pendingApprovalsList.some(a => sessionKey(a.nodeId, a.provider, a.sessionId) === key)
      const isRunning = Boolean(fleet.runningBySession[key])
      const unread = fleet.unreadCountBySession[key] ?? 0
      const diff = fleet.diffBySession[key]
      const diffCount = diff?.summary?.filesChanged ?? (sess.hasDiff ? 1 : 0)
      const branchName = diff?.branch || (sess.worktreePath ? leafPathName(sess.worktreePath) : '')
      const dirLabel = sess.cwd ? leafPathName(sess.cwd) : ''
      const msgs = fleet.messagesBySession[key] ?? []
      const lastAt = msgs.length ? msgs[msgs.length - 1].createdAt : 0
      return { key, session: sess, nodeName, hasApproval, isRunning, unread, diffCount, branchName, dirLabel, lastAt }
    })

  rows.sort((a, b) => {
    if (a.hasApproval !== b.hasApproval) return a.hasApproval ? -1 : 1
    if (a.isRunning !== b.isRunning) return a.isRunning ? -1 : 1
    if ((a.unread > 0) !== (b.unread > 0)) return a.unread > 0 ? -1 : 1
    return b.lastAt - a.lastAt
  })
  return rows
})

function formatShortTime(ts?: number): string {
  if (!ts) return ''
  const diffSec = Math.max(0, Math.floor((Date.now() - ts) / 1000))
  if (diffSec < 60) return '刚刚'
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} 分钟前`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} 小时前`
  const d = new Date(ts)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

function mobileOpenSession(key: string) {
  fleet.activateSession(key)
  fleet.markSessionRead(key)
  mobileView.value = 'thread'
}

function mobileBackToInbox() {
  mobileWorkbench.value = 'none'
  closeMobileSessionSheet()
  mobileView.value = 'inbox'
}

function mobileQuickNewSession() {
  const targetNode =
    (mobileNodeFilter.value !== 'all'
      ? fleet.nodes.find(n => n.id === mobileNodeFilter.value && n.status === 'online')
      : null) ??
    (fleet.selectedNode?.status === 'online' ? fleet.selectedNode : null) ??
    fleet.nodes.find(n => n.status === 'online')
  if (!targetNode) {
    emit('action', '暂无在线节点，请先配置节点')
    emit('navigate', 'Agents')
    return
  }
  const prevSess = fleet.currentSession
  const sourceKey = fleet.activeSessionKey || undefined
  const preferredProv = prevSess?.provider ?? fleet.selectedProvider
  const readyAdapter =
    targetNode.adapters.find(a => a.provider === preferredProv && a.status === 'ready') ??
    targetNode.adapters.find(a => a.status === 'ready')
  if (!readyAdapter) {
    openCreateSession(targetNode)
    return
  }
  const sameNodeCwd = prevSess?.nodeId === targetNode.id ? prevSess?.cwd : undefined
  const cwd = resolveAllowedSessionCwd(targetNode, sameNodeCwd) || undefined
  closeMobileSessionSheet()
  fleet.activeSessionKey = ''
  fleet.openSession({
    nodeId: targetNode.id,
    provider: readyAdapter.provider,
    cwd,
    inheritFromKey: sourceKey,
    onOpened: k => {
      if (!openTabKeys.value.includes(k)) {
        openTabKeys.value = [...openTabKeys.value, k]
      }
      fleet.activateSession(k)
    },
  })
  mobileView.value = 'thread'
  emit('action', `已创建 ${getProviderMeta(readyAdapter.provider).label} 新会话`)
}

function openMobileSessionSheet() {
  mobileRenaming.value = false
  mobileRenameDraft.value = fleet.currentSession?.title || ''
  mobileSessionSheetRef.value?.showModal?.()
}

function closeMobileSessionSheet() {
  mobileRenaming.value = false
  mobileSessionSheetRef.value?.close?.()
}

function commitMobileRename() {
  if (!fleet.activeSessionKey || !mobileRenameDraft.value.trim()) {
    mobileRenaming.value = false
    return
  }
  fleet.renameSession(fleet.activeSessionKey, mobileRenameDraft.value.trim())
  mobileRenaming.value = false
  emit('action', '已更新会话名称')
}

function mobileDeleteActiveSession() {
  if (!fleet.activeSessionKey) return
  const key = fleet.activeSessionKey
  closeMobileSessionSheet()
  handleDeleteSession(key)
  mobileView.value = 'inbox'
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
  <!-- 移动端（方案 B · 收件箱列表 → 全屏沉浸对话页，类似 Happy / Orca Mobile） -->
  <div v-if="mobile" class="mchat-root">
    <!-- 第一层：会话与审批收件箱（极简顶栏图标工具条 + 带状态微动画的会话卡片） -->
    <div v-if="mobileView === 'inbox'" class="mpage m-inbox-page">
      <div class="m-inbox-toolbar">
        <div class="m-inbox-toolbar-left">
          <button
            type="button"
            class="m-tool-ic-btn"
            :class="{ 'is-active': mobileSearchOpen || Boolean(mobileInboxQuery) }"
            aria-label="搜索会话"
            title="搜索会话"
            @click="toggleMobileSearch"
          >
            <OpusIcon name="search" />
          </button>
          <div class="m-filter-anchor">
            <button
              type="button"
              class="m-tool-ic-btn"
              :class="{ 'is-active': mobileHasActiveFilter || mobileFilterMenuOpen }"
              aria-label="筛选节点与状态"
              :aria-expanded="mobileFilterMenuOpen"
              title="筛选与更多"
              @click="toggleMobileFilterMenu"
            >
              <OpusIcon name="filter" />
              <span v-if="mobileHasActiveFilter" class="m-tool-dot" />
            </button>

            <!-- 顶部筛选二级菜单浮层 -->
            <div v-if="mobileFilterMenuOpen" class="m-filter-backdrop" @click="closeMobileFilterMenu" />
            <div v-if="mobileFilterMenuOpen" class="m-filter-dropdown" role="menu" aria-label="筛选菜单">
              <!-- 一级：控制节点（可展开二级） -->
              <button
                type="button"
                class="m-fmenu-item"
                :class="{ 'is-open': mobileFilterSub === 'node' }"
                @click="toggleMobileFilterSub('node')"
              >
                <OpusIcon name="server" class="m-fmenu-ic" />
                <span class="m-fmenu-lbl">控制节点</span>
                <span class="m-fmenu-val">
                  {{ mobileNodeFilter === 'all' ? '全部' : (fleet.nodes.find(n => n.id === mobileNodeFilter)?.name || '节点') }}
                </span>
                <OpusIcon name="chevR" class="m-fmenu-chev" />
              </button>
              <div v-if="mobileFilterSub === 'node'" class="m-fmenu-sub" role="group" aria-label="选择节点">
                <button
                  type="button"
                  class="m-fmenu-subitem"
                  :class="{ 'is-selected': mobileNodeFilter === 'all' }"
                  @click="mobileNodeFilter = 'all'; closeMobileFilterMenu()"
                >
                  <span>全部节点 ({{ mobileOnlineCount }} 在线)</span>
                  <OpusIcon v-if="mobileNodeFilter === 'all'" name="check" class="m-fmenu-check" />
                </button>
                <button
                  v-for="n in sortedNodes"
                  :key="n.id"
                  type="button"
                  class="m-fmenu-subitem"
                  :class="{ 'is-selected': mobileNodeFilter === n.id }"
                  @click="mobileNodeFilter = n.id; fleet.selectNode(n.id); closeMobileFilterMenu()"
                >
                  <span class="conn" :class="nodeIndicatorStatus(n.id, n.status)" />
                  <span class="m-fmenu-subtxt">{{ n.name }}</span>
                  <OpusIcon v-if="mobileNodeFilter === n.id" name="check" class="m-fmenu-check" />
                </button>
                <button
                  type="button"
                  class="m-fmenu-subitem is-link"
                  @click="closeMobileFilterMenu(); emit('navigate', 'Agents')"
                >
                  <OpusIcon name="plus" class="m-fmenu-ic" />
                  <span>管理控制节点</span>
                </button>
              </div>

              <!-- 一级：会话状态（可展开二级） -->
              <button
                type="button"
                class="m-fmenu-item"
                :class="{ 'is-open': mobileFilterSub === 'status' }"
                @click="toggleMobileFilterSub('status')"
              >
                <OpusIcon name="tasks" class="m-fmenu-ic" />
                <span class="m-fmenu-lbl">会话状态</span>
                <span class="m-fmenu-val">
                  {{ mobileStatusFilter === 'all' ? '全部' : mobileStatusFilter === 'running' ? '运行中' : '有改动' }}
                </span>
                <OpusIcon name="chevR" class="m-fmenu-chev" />
              </button>
              <div v-if="mobileFilterSub === 'status'" class="m-fmenu-sub" role="group" aria-label="选择状态">
                <button
                  type="button"
                  class="m-fmenu-subitem"
                  :class="{ 'is-selected': mobileStatusFilter === 'all' }"
                  @click="mobileStatusFilter = 'all'; closeMobileFilterMenu()"
                >
                  <span>全部状态</span>
                  <OpusIcon v-if="mobileStatusFilter === 'all'" name="check" class="m-fmenu-check" />
                </button>
                <button
                  type="button"
                  class="m-fmenu-subitem"
                  :class="{ 'is-selected': mobileStatusFilter === 'running' }"
                  @click="mobileStatusFilter = 'running'; closeMobileFilterMenu()"
                >
                  <span>运行中</span>
                  <OpusIcon v-if="mobileStatusFilter === 'running'" name="check" class="m-fmenu-check" />
                </button>
                <button
                  type="button"
                  class="m-fmenu-subitem"
                  :class="{ 'is-selected': mobileStatusFilter === 'diff' }"
                  @click="mobileStatusFilter = 'diff'; closeMobileFilterMenu()"
                >
                  <span>有代码改动</span>
                  <OpusIcon v-if="mobileStatusFilter === 'diff'" name="check" class="m-fmenu-check" />
                </button>
              </div>

              <div class="m-fmenu-sep" />

              <button
                type="button"
                class="m-fmenu-item"
                @click="closeMobileFilterMenu(); openCreateSession()"
              >
                <OpusIcon name="plus" class="m-fmenu-ic" />
                <span class="m-fmenu-lbl">自定义目录 / Worktree</span>
              </button>
              <button
                type="button"
                class="m-fmenu-item"
                @click="closeMobileFilterMenu(); showFanout = true"
              >
                <OpusIcon name="layers" class="m-fmenu-ic" />
                <span class="m-fmenu-lbl">多模型并发对比</span>
              </button>
              <button
                v-if="mobileHasActiveFilter"
                type="button"
                class="m-fmenu-item is-reset"
                @click="resetMobileFilters(); closeMobileFilterMenu()"
              >
                <OpusIcon name="sync" class="m-fmenu-ic" />
                <span class="m-fmenu-lbl">重置筛选条件</span>
              </button>
            </div>
          </div>
          <button
            v-if="mobileHasActiveFilter"
            type="button"
            class="m-active-filter-chip"
            aria-label="清空当前筛选"
            @click="resetMobileFilters"
          >
            <span>{{ mobileActiveFilterLabel }}</span>
            <OpusIcon name="x" />
          </button>
        </div>
        <div class="m-inbox-toolbar-icons">
          <button
            type="button"
            class="m-tool-ic-btn is-primary"
            aria-label="快速新建对话"
            title="快速新建对话"
            @click="mobileQuickNewSession"
          >
            <OpusIcon name="plus" />
          </button>
        </div>
      </div>

      <!-- 按需展开的紧凑搜索栏 -->
      <div v-if="mobileSearchOpen || mobileInboxQuery" class="msearch m-inbox-search">
        <OpusIcon name="search" />
        <input
          ref="mobileSearchInputRef"
          v-model="mobileInboxQuery"
          placeholder="搜索会话、目录或节点…"
          aria-label="搜索会话"
        />
        <button
          type="button"
          class="m-search-clear"
          aria-label="关闭搜索"
          @click="mobileInboxQuery = ''; mobileSearchOpen = false"
        >
          <OpusIcon name="x" />
        </button>
      </div>

      <!-- 离线提示条 -->
      <div v-if="fleet.wsState !== 'online'" class="mbanner show warn">
        <OpusIcon name="alert" />
        <span>Fleet Relay 状态：{{ fleet.wsState }}</span>
      </div>

      <!-- 待审批优先收件箱（单手拇指秒批） -->
      <section v-if="fleet.pendingApprovalsList.length" class="m-inbox-approvals" aria-label="待审批请求">
        <div class="sec-t" style="margin-top:4px">
          <span>待审批 ({{ fleet.pendingApprovalsList.length }})</span>
          <span class="spacer" />
          <span>高优先级</span>
        </div>
        <div
          v-for="card in fleet.pendingApprovalsList"
          :key="card.callId"
          class="m-approval-card"
        >
          <div class="m-appr-top">
            <OpusIcon name="shield" class="m-appr-ic" />
            <div class="m-appr-copy">
              <strong>{{ card.title }}</strong>
              <span>{{ fleet.sessionsByKey[sessionKey(card.nodeId, card.provider, card.sessionId)]?.title || getProviderMeta(card.provider).label }}</span>
            </div>
            <button
              type="button"
              class="btn btn-ghost btn-sm"
              @click="mobileOpenSession(sessionKey(card.nodeId, card.provider, card.sessionId))"
            >查看</button>
          </div>
          <code v-if="card.command" class="m-appr-cmd">{{ card.command }}</code>
          <div class="m-appr-actions">
            <button type="button" class="btn btn-danger" @click="fleet.respondPermission(card.callId, 'deny')">拒绝</button>
            <button type="button" class="btn btn-primary" @click="fleet.respondPermission(card.callId, 'allow_once')">允许一次</button>
          </div>
        </div>
      </section>

      <!-- 会话列表卡片（去头像绿点、去右箭头、精简副标题、角落带动画状态徽章） -->
      <div v-if="mobileInboxSessions.length" class="mlist mat-solid m-inbox-list">
        <button
          v-for="item in mobileInboxSessions"
          :key="item.key"
          type="button"
          class="mrow m-inbox-row"
          @click="mobileOpenSession(item.key)"
        >
          <span
            class="m-sess-avatar"
            :class="[
              getProviderMeta(item.session.provider).accentClass,
              { 'is-running': item.isRunning, 'is-approval': item.hasApproval },
            ]"
          >
            <OpusIcon :name="getProviderMeta(item.session.provider).icon" />
          </span>
          <span class="grow">
            <span class="m-sess-top">
              <span class="title">{{ item.session.title }}</span>
              <span v-if="item.lastAt" class="m-sess-time num">{{ formatShortTime(item.lastAt) }}</span>
            </span>
            <span class="m-sess-bottom">
              <span class="m-sess-sub-mini">
                <span>{{ item.nodeName }}</span>
                <template v-if="item.branchName || item.dirLabel"> · {{ item.branchName || item.dirLabel }}</template>
                <span v-if="item.diffCount > 0" class="m-sess-diff-num num"> · {{ item.diffCount }} 改动</span>
              </span>
              <span
                v-if="item.hasApproval || item.isRunning || item.unread > 0"
                class="m-sess-state-pill"
                :class="item.hasApproval ? 'is-approval' : item.isRunning ? 'is-running' : 'is-unread'"
              >
                <span v-if="item.isRunning" class="m-state-spinner" aria-hidden="true" />
                <OpusIcon v-else-if="item.hasApproval" name="shield" class="m-state-ic is-pulse" />
                <OpusIcon v-else name="check" class="m-state-ic is-pop" />
                <span>{{ item.hasApproval ? '待审批' : item.isRunning ? '运行中' : '已完成' }}</span>
              </span>
            </span>
          </span>
        </button>
      </div>

      <!-- 空状态引导卡片 -->
      <div v-else class="mcard mat-solid m-inbox-empty">
        <div class="m-empty-ic"><OpusIcon name="chat" /></div>
        <h3>{{ mobileInboxQuery || mobileHasActiveFilter ? '没有匹配的会话' : '开始你的 Agent 任务' }}</h3>
        <p class="faint">
          {{ mobileInboxQuery || mobileHasActiveFilter ? '换个关键词或清空筛选条件看看。' : '连接家中 Mac、桌面或云端节点，随时在手机上跟进代码、评审 Diff 与审批命令。' }}
        </p>
        <div class="m-empty-actions">
          <button v-if="mobileHasActiveFilter" type="button" class="btn btn-primary" @click="resetMobileFilters">
            <span>重置筛选</span>
          </button>
          <button v-else type="button" class="btn btn-primary" @click="mobileQuickNewSession">
            <OpusIcon name="plus" />
            <span>快速开始对话</span>
          </button>
          <button type="button" class="btn btn-ghost" @click="openCreateSession()">
            <span>选择目录 / Worktree</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 第二层：全屏沉浸对话页（自动隐藏底部主 TabBar，最大化对话与键盘视野） -->
    <div v-else class="m-thread-shell">
      <header class="m-thread-bar">
        <button
          type="button"
          class="m-bar-btn m-back-btn"
          aria-label="返回会话列表"
          @click="mobileBackToInbox"
        >
          <OpusIcon name="chevL" />
          <span v-if="mobileOtherApprovalsCount" class="m-wb-dot num">{{ mobileOtherApprovalsCount }}</span>
        </button>

        <button
          type="button"
          class="m-thread-title-btn"
          aria-haspopup="dialog"
          @click="openMobileSessionSheet"
        >
          <span class="m-tt-main">{{ fleet.currentSession?.title || `新对话 · ${getProviderMeta(fleet.selectedProvider).label}` }}</span>
          <span class="m-tt-sub">
            <span class="conn" :class="fleet.wsState === 'online' ? 'online' : 'reconnecting'" />
            <span>{{ fleet.selectedNode?.name || '未选节点' }}</span>
            <template v-if="fleet.currentDiff?.branch"> · {{ fleet.currentDiff.branch }}</template>
            <template v-else-if="fleet.currentSession?.cwd"> · {{ leafPathName(fleet.currentSession.cwd) }}</template>
            <OpusIcon name="chevD" class="m-tt-chev" />
          </span>
        </button>

        <div class="m-thread-actions">
          <button
            type="button"
            class="m-bar-btn"
            aria-label="新建会话"
            title="新建会话"
            @click="mobileQuickNewSession"
          >
            <OpusIcon name="plus" />
          </button>
          <button
            type="button"
            class="m-bar-btn m-wb-trigger"
            aria-label="打开工作台（Diff / 文件 / 终端）"
            title="工作台（代码评审 · 目录 · 终端）"
            :disabled="!fleet.currentSession"
            @click="openMobileWorkbench(fleet.currentDiff?.files?.length ? 'diff' : 'tree')"
          >
            <OpusIcon name="panel" />
            <span v-if="fleet.currentDiff?.summary?.filesChanged" class="m-wb-dot num">
              {{ fleet.currentDiff.summary.filesChanged }}
            </span>
          </button>
        </div>
      </header>

      <!-- 后台其他会话待审批横幅 -->
      <div v-if="mobileBackgroundApprovals.length" class="m-bg-approval-bar">
        <OpusIcon name="shield" class="bga-ic" />
        <span class="m-bga-copy">
          <strong>{{ mobileBackgroundApprovals[0].sessionTitle }}</strong> 待审批
        </span>
        <button
          type="button"
          class="btn btn-primary btn-sm"
          @click="mobileOpenSession(mobileBackgroundApprovals[0].key)"
        >前往审批</button>
      </div>

      <AgentChatThread
        class="mchat-thread"
        :mobile="true"
        @action="emit('action', $event)"
        @open-handoff="openHandoffDialog"
        @open-diff="openDiffPanel"
        @open-file="openFilePreview"
        @open-subagent="handleOpenSubagent"
      />
    </div>

    <!-- 移动端会话与节点控制底部抽屉（原生 <dialog> + 滚动隔离） -->
    <dialog ref="mobileSessionSheetRef" class="msheet-dlg" aria-label="会话与节点设置" closedby="any">
      <div class="msheet-panel">
        <div class="msheet-grab" aria-hidden="true" />
        <div class="msheet-hdr">
          <h3>会话与节点</h3>
          <button type="button" class="icon-btn" aria-label="关闭" @click="closeMobileSessionSheet">
            <OpusIcon name="x" />
          </button>
        </div>

        <div v-if="fleet.currentSession" class="msheet-sec">
          <div class="msheet-label">当前会话名称</div>
          <div v-if="mobileRenaming" class="msheet-rename-row">
            <input
              v-model="mobileRenameDraft"
              class="input"
              placeholder="输入会话名称"
              @keydown.enter.prevent="commitMobileRename"
            />
            <button type="button" class="btn btn-primary" @click="commitMobileRename">保存</button>
          </div>
          <button v-else type="button" class="msheet-row" @click="mobileRenaming = true">
            <OpusIcon name="pencil" />
            <span class="msheet-row-text">{{ fleet.currentSession.title }}</span>
            <span class="faint">重命名</span>
          </button>
        </div>

        <div class="msheet-sec">
          <div class="msheet-label">控制节点</div>
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
            <button type="button" class="chip" @click="closeMobileSessionSheet(); emit('navigate', 'Agents')">+ 管理节点</button>
          </div>
        </div>

        <div class="msheet-sec">
          <div class="msheet-label">代理引擎</div>
          <div class="mchat-chips">
            <button
              v-for="ad in selectedNodeAdapters"
              :key="ad.provider"
              type="button"
              class="chip"
              :aria-pressed="fleet.selectedProvider === ad.provider"
              @click="fleet.selectProvider(ad.provider)"
            >
              <OpusIcon :name="getProviderMeta(ad.provider).icon" />
              <span>{{ getProviderMeta(ad.provider).label }}</span>
            </button>
          </div>
        </div>

        <div class="msheet-sec">
          <div class="msheet-label">对话气泡样式</div>
          <div class="mchat-chips">
            <button
              v-for="opt in chatBubbleStyleOptions"
              :key="opt.id"
              type="button"
              class="chip"
              :aria-pressed="bubbleStyle === opt.id"
              @click="setBubbleStyle(opt.id)"
            >
              <span>{{ opt.title }}</span>
            </button>
          </div>
        </div>

        <div class="msheet-sec">
          <div class="msheet-label">会话操作</div>
          <div class="msheet-actions">
            <button type="button" class="msheet-row" @click="closeMobileSessionSheet(); openCreateSession()">
              <OpusIcon name="plus" />
              <span class="msheet-row-text">自定义目录 / Worktree 新建</span>
            </button>
            <button
              v-if="fleet.currentSession"
              type="button"
              class="msheet-row"
              @click="closeMobileSessionSheet(); openMobileWorkbench(fleet.currentDiff?.files?.length ? 'diff' : 'tree')"
            >
              <OpusIcon name="panel" />
              <span class="msheet-row-text">打开工作台（Diff · 目录 · 终端）</span>
            </button>
            <button type="button" class="msheet-row" @click="closeMobileSessionSheet(); openHandoffDialog()">
              <OpusIcon name="send" />
              <span class="msheet-row-text">@Handoff 跨节点转交</span>
            </button>
            <button v-if="fleet.currentSession" type="button" class="msheet-row" @click="closeMobileSessionSheet(); handleCompactActive()">
              <OpusIcon name="layers" />
              <span class="msheet-row-text">压缩会话上下文 (/compact)</span>
            </button>
            <button v-if="fleet.currentSession" type="button" class="msheet-row" @click="closeMobileSessionSheet(); handleExportActive()">
              <OpusIcon name="file" />
              <span class="msheet-row-text">导出 Markdown 记录</span>
            </button>
            <button type="button" class="msheet-row" @click="fleet.toggleSoundCues()">
              <OpusIcon name="sparkle" />
              <span class="msheet-row-text">后台完成 / 审批提示音</span>
              <span class="faint">{{ fleet.soundEnabled ? '已开启' : '已关闭' }}</span>
            </button>
            <button v-if="fleet.currentSession" type="button" class="msheet-row is-danger" @click="mobileDeleteActiveSession">
              <OpusIcon name="x" />
              <span class="msheet-row-text">删除当前会话</span>
            </button>
          </div>
        </div>
      </div>
    </dialog>

    <!-- 移动端全屏工作台 Sheet（Diff 评审 / 目录 / 代码预览 / 受控终端） -->
    <div v-if="mobileWorkbench !== 'none'" class="m-wb-sheet">
      <div class="wb-tabs-bar" role="tablist" aria-label="移动端工作台切换">
        <div class="wb-tabs-list">
          <button
            type="button"
            role="tab"
            :aria-selected="mobileWorkbench === 'diff'"
            class="wb-tab-btn"
            :class="{ 'is-active': mobileWorkbench === 'diff' }"
            @click="openMobileWorkbench('diff')"
          >
            <OpusIcon name="branch" />
            <span>评审</span>
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="mobileWorkbench === 'tree'"
            class="wb-tab-btn"
            :class="{ 'is-active': mobileWorkbench === 'tree' }"
            @click="openMobileWorkbench('tree')"
          >
            <OpusIcon name="layers" />
            <span>目录</span>
          </button>
          <button
            v-if="fleet.activeSessionKey && fleet.filePreviewBySession[fleet.activeSessionKey]"
            type="button"
            role="tab"
            :aria-selected="mobileWorkbench === 'file'"
            class="wb-tab-btn"
            :class="{ 'is-active': mobileWorkbench === 'file' }"
            @click="mobileWorkbench = 'file'"
          >
            <OpusIcon name="file" />
            <span>预览</span>
          </button>
          <button
            type="button"
            role="tab"
            :aria-selected="mobileWorkbench === 'terminal'"
            class="wb-tab-btn"
            :class="{ 'is-active': mobileWorkbench === 'terminal' }"
            @click="openMobileWorkbench('terminal')"
          >
            <OpusIcon name="terminal" />
            <span>终端</span>
          </button>
        </div>
        <button type="button" class="icon-btn wb-close-btn" aria-label="关闭工作台" @click="mobileWorkbench = 'none'">
          <OpusIcon name="x" />
        </button>
      </div>
      <div class="wb-pane-body">
        <DiffReviewDrawer
          v-if="mobileWorkbench === 'diff'"
          :embedded="true"
          :session-key="fleet.activeSessionKey"
          :diff="fleet.currentDiff"
          :checkpoints="fleet.currentCheckpoints"
          :focus-file-path="diffFocusFile"
          :is-worktree="Boolean(fleet.currentSession?.worktreePath)"
          @refresh="fleet.requestSessionDiff(fleet.activeSessionKey)"
          @close="mobileWorkbench = 'none'"
          @revert-latest="fleet.revertCheckpoint(fleet.activeSessionKey, $event)"
          @revert-files="(paths, cpId) => fleet.revertFiles(fleet.activeSessionKey, paths, cpId)"
          @revert-hunk="(fp, patch) => fleet.revertDiffHunk(fleet.activeSessionKey, fp, patch)"
          @commit-changes="(msg, paths) => fleet.commitWorkspaceChanges(fleet.activeSessionKey, msg, paths)"
          @open-file="openFilePreview"
          @merge-worktree="fleet.mergeSessionWorktree(fleet.activeSessionKey)"
          @action="emit('action', $event)"
        />
        <WorkspaceTreeDrawer
          v-else-if="mobileWorkbench === 'tree'"
          :session-key="fleet.activeSessionKey"
          @close="mobileWorkbench = 'none'"
          @open-file="openFilePreview($event)"
          @open-external="fp => fleet.openExternalTarget(fp, 'editor', fleet.activeSessionKey)"
        />
        <FileViewerDrawer
          v-else-if="mobileWorkbench === 'file'"
          :preview="fleet.activeSessionKey ? fleet.filePreviewBySession[fleet.activeSessionKey] ?? null : null"
          @close="mobileWorkbench = 'none'"
          @refresh="openFilePreview($event)"
          @save-file="(fp, content) => { fleet.saveWorkspaceFile(fp, content, fleet.activeSessionKey); emit('action', '已保存文件修改') }"
          @request-blame="fp => fleet.requestFileBlame(fp, fleet.activeSessionKey)"
          @open-external="fp => fleet.openExternalTarget(fp, 'editor', fleet.activeSessionKey)"
        />
        <TerminalDrawer
          v-else-if="mobileWorkbench === 'terminal'"
          :session-key="fleet.activeSessionKey"
          @close="mobileWorkbench = 'none'"
        />
      </div>
    </div>
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
          <div class="tree-filter-pills" role="group" aria-label="按状态筛选会话">
            <button
              v-for="f in [
                { id: 'all', label: '全部' },
                { id: 'running', label: '运行中' },
                { id: 'approval', label: '待审批' },
                { id: 'diff', label: '有改动' },
              ] as const"
              :key="f.id"
              type="button"
              class="tree-filter-pill"
              :class="{ 'is-active': treeFilterMode === f.id }"
              @click="treeFilterMode = f.id"
            >{{ f.label }}</button>
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
                    <span class="tree-eng" :title="getProviderMeta(sess.provider).label">
                      <OpusIcon :name="getProviderMeta(sess.provider).icon" class="tree-eng-ic" />
                    </span>
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
                  <span class="tree-eng" :title="getProviderMeta(sess.provider).label">
                    <OpusIcon :name="getProviderMeta(sess.provider).icon" class="tree-eng-ic" />
                  </span>
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
            :class="{
              'is-active': fleet.activeSessionKey === tab.key,
              'is-pinned': pinnedTabKeys.includes(tab.key),
            }"
            @click="fleet.activateSession(tab.key); dismissTabMenu()"
            @auxclick.middle.prevent="closeSessionTab(tab.key)"
            @contextmenu="openTabContextMenu(tab.key, $event)"
          >
            <OpusIcon v-if="pinnedTabKeys.includes(tab.key)" name="pin" class="tab-pin-ic" />
            <span v-else class="tree-dot" :class="sessionDotClass(tab.session)" />
            <span class="chat-tab-label">{{ tab.session.title }}</span>
            <span v-if="fleet.unreadCountBySession[tab.key]" class="tab-unread-dot num">
              {{ fleet.unreadCountBySession[tab.key] }}
            </span>
            <span class="chat-tab-eng" :title="getProviderMeta(tab.session.provider).label">
              <OpusIcon :name="getProviderMeta(tab.session.provider).icon" class="tree-eng-ic" />
            </span>
            <span
              v-if="!pinnedTabKeys.includes(tab.key)"
              class="chat-tab-close"
              role="button"
              aria-label="关闭标签"
              @click.stop="closeSessionTab(tab.key)"
            >×</span>
          </button>

          <div v-if="!openTabs.length" class="chat-empty-tab">
            <span>{{ fleet.selectedNode ? `${fleet.selectedNode.name} · ${getProviderMeta(fleet.selectedProvider).label}` : 'Agent Fleet' }}</span>
          </div>

          <div class="new-tab-split">
            <button
              type="button"
              class="icon-btn"
              title="秒开新会话（自动继承当前节点/引擎/目录/模型，Shift+点击打开高级选项）"
              aria-label="快速新建工作会话"
              @click="quickCreateSession($event)"
            >
              <OpusIcon name="plus" />
            </button>
            <button
              type="button"
              class="icon-btn new-tab-more"
              title="高级新建会话（切换节点、目录或创建 Git Worktree 沙箱）"
              aria-label="高级新建会话设置"
              @click="openCreateSession()"
            >
              <OpusIcon name="chevD" />
            </button>
          </div>
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
              <button v-if="fleet.currentSession" type="button" @click="handleOpenSideChat()"><OpusIcon name="sparkle" />侧边问答 (/btw)</button>
              <button v-if="fleet.currentSession" type="button" @click="primaryThreadRef?.openThreadSearch()"><OpusIcon name="search" />搜索本对话 (Ctrl+F)</button>
              <button type="button" @click="handleToggleNotifications">
                <OpusIcon name="bell" />
                <span>{{ fleet.notificationsEnabled ? '后台桌面通知：已开启' : '开启后台桌面通知' }}</span>
              </button>
              <button type="button" @click="fleet.toggleSoundCues(); emit('action', fleet.soundEnabled ? '已开启完成与审批轻提示音' : '已关闭提示音')">
                <OpusIcon name="sparkle" />
                <span>{{ fleet.soundEnabled ? '任务轻提示音：已开启' : '开启任务轻提示音' }}</span>
              </button>
              <button type="button" @click="fleet.toggleSendShortcut(); emit('action', fleet.sendShortcut === 'ctrl-enter' ? '已切换为 Ctrl+Enter 发送（Enter 换行）' : '已切换为 Enter 直接发送')">
                <OpusIcon name="command" />
                <span>发送键：{{ fleet.sendShortcut === 'ctrl-enter' ? 'Ctrl+Enter' : 'Enter' }}</span>
              </button>
              <button type="button" @click="cycleBubbleStyle">
                <OpusIcon name="sparkle" />
                <span>气泡样式：{{ chatBubbleStyleLabel(bubbleStyle) }}</span>
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
        <button
          v-if="fleet.lastError && !fleet.pendingApprovalsList.length && fleet.wsState === 'online'"
          type="button"
          class="conn-banner-close"
          aria-label="关闭错误提示"
          title="关闭提示"
          @click="fleet.lastError = null"
        >
          <OpusIcon name="x" />
        </button>
      </div>

      <div
        v-if="backgroundApprovals.length"
        class="bg-approval-strip"
        role="region"
        aria-label="后台会话待审批汇总"
      >
        <OpusIcon name="shield" class="bga-ic" />
        <span class="bga-text">
          <strong>后台待审批 ({{ backgroundApprovals.length }})</strong>
          <code>{{ backgroundApprovals[0].command || backgroundApprovals[0].title }}</code>
        </span>
        <div class="bga-actions">
          <button
            type="button"
            class="btn btn-primary btn-sm"
            @click="fleet.respondPermission(backgroundApprovals[0].callId, 'allow_once')"
          >允许一次</button>
          <button
            type="button"
            class="btn btn-ghost btn-sm"
            @click="fleet.respondPermission(backgroundApprovals[0].callId, 'deny')"
          >拒绝</button>
          <button
            type="button"
            class="btn btn-subtle btn-sm"
            @click="jumpToApprovalSession(backgroundApprovals[0].nodeId, backgroundApprovals[0].provider, backgroundApprovals[0].sessionId)"
          >查看</button>
        </div>
      </div>

      <AgentChatThread
        ref="primaryThreadRef"
        :session-key="fleet.activeSessionKey || undefined"
        @action="emit('action', $event)"
        @open-handoff="openHandoffDialog"
        @open-diff="openDiffPanel"
        @open-file="openFilePreview"
        @open-subagent="handleOpenSubagent"
        @open-side-chat="handleOpenSideChat"
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
            <button
              v-if="fleet.currentSession"
              type="button"
              role="tab"
              :aria-selected="rightMode === 'side'"
              class="wb-tab-btn"
              :class="{ 'is-active': rightMode === 'side' }"
              title="不污染主上下文的临时侧边问答 (/btw)"
              @click="handleOpenSideChat()"
            >
              <OpusIcon name="sparkle" />
              <span>/btw</span>
            </button>
            <button
              v-if="focusedSubagentKey"
              type="button"
              role="tab"
              :aria-selected="rightMode === 'subagent'"
              class="wb-tab-btn"
              :class="{ 'is-active': rightMode === 'subagent' }"
              @click="setRightPane('subagent')"
            >
              <OpusIcon name="bot" />
              <span>子代理</span>
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
            @action="emit('action', $event)"
          />

          <FileViewerDrawer
            v-else-if="rightMode === 'file'"
            :preview="fleet.activeSessionKey ? fleet.filePreviewBySession[fleet.activeSessionKey] ?? null : null"
            @close="fleet.closeFilePreview(); setRightPane('none')"
            @refresh="openFilePreview($event)"
            @cite-lines="primaryThreadRef?.insertFileReference($event)"
            @ask-about-file="primaryThreadRef?.insertFileReference($event)"
            @save-file="(fp, content) => { fleet.saveWorkspaceFile(fp, content, fleet.activeSessionKey); emit('action', '已保存文件修改至远程工作区') }"
            @request-blame="fp => fleet.requestFileBlame(fp, fleet.activeSessionKey)"
            @open-external="fp => { fleet.openExternalTarget(fp, 'editor', fleet.activeSessionKey); emit('action', '已请求在宿主机外部编辑器打开') }"
          />

          <WorkspaceTreeDrawer
            v-else-if="rightMode === 'tree'"
            :session-key="fleet.activeSessionKey"
            @close="setRightPane('none')"
            @open-file="openFilePreview($event)"
            @cite-file="primaryThreadRef?.insertFileReference($event)"
            @open-external="(fp, target) => { fleet.openExternalTarget(fp, target, fleet.activeSessionKey); emit('action', '已请求在宿主机打开工作区') }"
          />

          <TerminalDrawer
            v-else-if="rightMode === 'terminal'"
            :session-key="fleet.activeSessionKey"
            @close="setRightPane('none')"
          />

          <SideChatDrawer
            v-else-if="rightMode === 'side'"
            mode="side"
            :embedded="true"
            :session-key="sideChatSessionKey"
            @close="setRightPane('none')"
            @promote-to-main="promoteSideToMain"
            @action="emit('action', $event)"
            @open-diff="openDiffPanel"
            @open-file="openFilePreview"
            @open-subagent="handleOpenSubagent"
          />

          <SideChatDrawer
            v-else-if="rightMode === 'subagent'"
            mode="subagent"
            :embedded="true"
            :session-key="focusedSubagentKey"
            @close="setRightPane('none')"
            @promote-to-main="promoteSideToMain"
            @action="emit('action', $event)"
            @open-diff="openDiffPanel"
            @open-file="openFilePreview"
            @open-subagent="handleOpenSubagent"
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

    <!-- 标签页右键轻菜单（固定 / 关闭其他 / 关闭右侧） -->
    <div v-if="tabContextMenu" class="tab-ctx-backdrop" @click="dismissTabMenu" @contextmenu.prevent="dismissTabMenu">
      <div
        class="tab-ctx-menu"
        :style="{ left: `${tabContextMenu.x}px`, top: `${tabContextMenu.y}px` }"
        @click.stop
      >
        <button type="button" @click="togglePinTab(tabContextMenu.key)">
          <OpusIcon name="pin" />
          <span>{{ pinnedTabKeys.includes(tabContextMenu.key) ? '取消固定标签' : '固定标签（防误关）' }}</span>
        </button>
        <button type="button" @click="closeOtherTabs(tabContextMenu.key)">
          <OpusIcon name="x" />
          <span>关闭其他标签</span>
        </button>
        <button type="button" @click="closeRightTabs(tabContextMenu.key)">
          <OpusIcon name="chevR" />
          <span>关闭右侧标签</span>
        </button>
      </div>
    </div>
  </div>

  <!-- 桌面与移动端共用弹窗（新建会话 / @Handoff / 群发对比） -->
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
          <select v-if="readyAt(newSessionNodeId).length" v-model="newSessionProvider" class="input">
            <option v-for="ad in readyAt(newSessionNodeId)" :key="ad.provider" :value="ad.provider">{{ getProviderMeta(ad.provider).label }}</option>
          </select>
          <p v-else class="faint" style="margin:0;font-size:12.5px">当前节点暂无就绪的代理引擎，请确认本地 CLI / 服务运行且鉴权正常。</p>
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
.tab-unread-dot {
  display: inline-grid;
  place-items: center;
  min-width: 15px;
  height: 15px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--accent);
  color: var(--accent-ink, #fff);
  font-size: 10px;
  font-weight: 650;
}
.bg-approval-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 12px;
  border-bottom: 1px solid color-mix(in srgb, var(--warn) 32%, var(--line));
  background: color-mix(in srgb, var(--warn-soft) 60%, var(--solid));
  font-size: 12px;
  flex: none;
}
.bga-ic {
  width: 14px;
  height: 14px;
  color: var(--warn);
  flex: none;
}
.bga-text {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
}
.bga-text code {
  font-family: var(--mono);
  font-size: 11.5px;
  color: var(--text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bga-actions {
  display: flex;
  align-items: center;
  gap: 5px;
  flex: none;
}
.m-wb-trigger {
  position: relative;
}
.m-wb-dot {
  position: absolute;
  top: 2px;
  right: 2px;
  min-width: 14px;
  height: 14px;
  padding: 0 3px;
  border-radius: 999px;
  background: var(--accent);
  color: var(--accent-ink, #fff);
  font-size: 9.5px;
  line-height: 14px;
  font-weight: 650;
}
.m-wb-sheet {
  position: fixed;
  inset: env(safe-area-inset-top, 0px) 0 0 0;
  z-index: 60;
  display: flex;
  flex-direction: column;
  background: var(--solid);
  color: var(--text);
  isolation: isolate;
}
.m-wb-sheet .wb-tabs-bar {
  padding: 8px 10px;
  background: var(--solid);
}
.m-wb-sheet .wb-tab-btn {
  min-height: 36px;
  padding: 0 12px;
  font-size: 13.5px;
}
.m-wb-sheet .wb-close-btn {
  width: 38px;
  height: 38px;
}
.m-wb-sheet .wb-pane-body {
  background: var(--bg);
}
.conn-banner-close {
  margin-left: auto;
  display: inline-grid;
  place-items: center;
  width: 22px;
  height: 22px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: inherit;
  opacity: 0.72;
  cursor: pointer;
  flex: none;
}
.conn-banner-close:hover {
  opacity: 1;
  background: color-mix(in srgb, currentColor 12%, transparent);
}
.conn-banner-close .i {
  width: 12px;
  height: 12px;
}
.chat-tab {
  max-width: 156px;
}
.chat-tab.is-active {
  flex: none;
  max-width: 220px;
}
.tab-pin-ic {
  width: 11px;
  height: 11px;
  color: var(--accent);
  flex: none;
}
.new-tab-split {
  display: inline-flex;
  align-items: center;
  flex: none;
}
.new-tab-more {
  width: 20px;
  margin-left: -4px;
  opacity: 0.65;
}
.new-tab-more:hover {
  opacity: 1;
}
.tree-filter-pills {
  display: flex;
  gap: 4px;
  padding-top: 2px;
}
.tree-filter-pill {
  flex: 1;
  padding: 2px 4px;
  border: 1px solid transparent;
  border-radius: var(--r-xs);
  background: transparent;
  color: var(--text-3);
  font-size: 10.5px;
  cursor: pointer;
  white-space: nowrap;
}
.tree-filter-pill:hover {
  background: var(--surface-3);
  color: var(--text-2);
}
.tree-filter-pill.is-active {
  background: var(--solid);
  border-color: var(--line);
  color: var(--text);
  font-weight: 560;
}
.tab-ctx-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
}
.tab-ctx-menu {
  position: fixed;
  display: grid;
  gap: 2px;
  padding: 5px;
  min-width: 156px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-md);
  background: var(--solid);
  box-shadow: var(--shadow-2);
}
.tab-ctx-menu button {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 6px 10px;
  border: 0;
  border-radius: var(--r-xs);
  background: transparent;
  color: var(--text);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.tab-ctx-menu button:hover {
  background: var(--surface-2);
}
.tab-ctx-menu button .i {
  width: 12px;
  height: 12px;
  color: var(--text-3);
}
.tree-eng,
.chat-tab-eng {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.tree-eng-ic {
  width: 12px;
  height: 12px;
  color: var(--text-2);
  flex: none;
}

/* ---------- 移动端方案 B：极简图标工具栏 + 动效状态收件箱 + 全屏沉浸对话 ---------- */
.mchat-root {
  position: absolute;
  inset: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--bg);
}
.m-inbox-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 2px 13px;
}
.m-inbox-toolbar-left {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.m-inbox-title {
  margin: 0;
  font-size: 24px;
  font-weight: 720;
  letter-spacing: -0.02em;
  line-height: 1.15;
  color: var(--text);
}
.m-inbox-count {
  display: inline-grid;
  place-items: center;
  min-width: 22px;
  height: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--surface-3);
  color: var(--text-3);
  font-size: 11.5px;
  font-weight: 600;
}
.m-active-filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 9px;
  border: 1px solid var(--accent-line);
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-weight: 560;
  cursor: pointer;
}
.m-active-filter-chip .i { width: 12px; height: 12px; }
.m-inbox-toolbar-icons {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: none;
}
.m-tool-ic-btn {
  position: relative;
  display: inline-grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--text-2);
  cursor: pointer;
  transition: background-color var(--dur-1), color var(--dur-1), scale var(--dur-1);
}
.m-tool-ic-btn .i { width: 17px; height: 17px; }
.m-tool-ic-btn:active { scale: .93; }
.m-tool-ic-btn.is-active {
  background: var(--accent-soft);
  color: var(--accent);
}
.m-tool-ic-btn.is-primary {
  background: var(--accent);
  color: var(--accent-ink);
}
.m-tool-dot {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
}
.m-filter-anchor {
  position: relative;
  display: inline-flex;
}
.m-filter-backdrop {
  position: fixed;
  inset: 0;
  z-index: 35;
}
.m-filter-dropdown {
  position: absolute;
  top: calc(100% + 8px);
  left: -44px;
  z-index: 40;
  width: 224px;
  padding: 6px;
  border: 1px solid var(--line-strong);
  border-radius: 16px;
  background: var(--solid);
  box-shadow: var(--shadow-pop);
  display: grid;
  gap: 2px;
}
.m-fmenu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 36px;
  padding: 0 10px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--text);
  font-size: 13px;
  font-weight: 520;
  text-align: left;
  cursor: pointer;
}
.m-fmenu-item:active,
.m-fmenu-item.is-open {
  background: var(--surface-2);
}
.m-fmenu-item.is-reset {
  color: var(--accent);
}
.m-fmenu-ic {
  width: 14px;
  height: 14px;
  color: var(--text-3);
  flex: none;
}
.m-fmenu-lbl {
  flex: 1;
  min-width: 0;
}
.m-fmenu-val {
  max-width: 82px;
  font-size: 11.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.m-fmenu-chev {
  width: 12px;
  height: 12px;
  color: var(--text-3);
  flex: none;
  transition: transform var(--dur-1) var(--ease-out);
}
.m-fmenu-item.is-open .m-fmenu-chev {
  transform: rotate(90deg);
  color: var(--text);
}
.m-fmenu-sub {
  display: grid;
  gap: 2px;
  margin: 2px 0 4px 12px;
  padding: 4px;
  border-left: 1.5px solid var(--line-strong);
}
.m-fmenu-subitem {
  display: flex;
  align-items: center;
  gap: 7px;
  width: 100%;
  min-height: 32px;
  padding: 0 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-2);
  font-size: 12.5px;
  text-align: left;
  cursor: pointer;
}
.m-fmenu-subitem:active {
  background: var(--surface-2);
}
.m-fmenu-subitem.is-selected {
  background: var(--accent-soft);
  color: var(--text);
  font-weight: 560;
}
.m-fmenu-subitem.is-link {
  color: var(--text-3);
}
.m-fmenu-subtxt {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.m-fmenu-check {
  width: 13px;
  height: 13px;
  color: var(--accent);
  flex: none;
  margin-left: auto;
}
.m-fmenu-sep {
  height: 1px;
  margin: 4px 6px;
  background: var(--line);
}
.m-inbox-search {
  margin-bottom: 10px;
}
.m-inbox-search input {
  padding-right: 40px;
}
.m-search-clear {
  position: absolute;
  right: 6px;
  top: 50%;
  translate: 0 -50%;
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
}
.m-search-clear .i { position: static; translate: none; width: 14px; height: 14px; }

.m-inbox-approvals {
  display: grid;
  gap: 8px;
  margin-bottom: 14px;
}
.m-approval-card {
  display: grid;
  gap: 10px;
  padding: 13px 14px;
  border-radius: 20px;
  background: color-mix(in srgb, var(--warn-soft) 75%, var(--solid));
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--warn) 35%, transparent);
}
.m-appr-top {
  display: flex;
  align-items: center;
  gap: 10px;
}
.m-appr-ic { width: 18px; height: 18px; color: var(--warn); flex: none; }
.m-appr-copy {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 2px;
}
.m-appr-copy strong {
  font-size: 14px;
  font-weight: 650;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.m-appr-copy span {
  font-size: 12px;
  color: var(--text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.m-appr-cmd {
  display: block;
  padding: 8px 10px;
  border-radius: 12px;
  background: var(--solid);
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  word-break: break-all;
}
.m-appr-actions {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}
.m-appr-actions .btn {
  min-height: 42px;
  justify-content: center;
  border-radius: 13px;
  font-size: 14px;
}

.m-inbox-scroll-chips {
  display: flex;
  align-items: center;
  gap: 6px;
  overflow-x: auto;
  overscroll-behavior-x: contain;
  scrollbar-width: none;
  margin: 0 -16px 10px;
  padding: 2px 16px;
}
.m-inbox-scroll-chips::-webkit-scrollbar { display: none; }
.m-inbox-scroll-chips .chip {
  flex: none;
  min-height: 34px;
  padding: 0 12px;
  font-size: 13px;
}

.m-inbox-subbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}
.m-status-seg {
  display: inline-flex;
  padding: 3px;
  border-radius: 12px;
  background: var(--surface-3);
  gap: 2px;
}
.m-status-seg button {
  min-height: 30px;
  padding: 0 11px;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 560;
  cursor: pointer;
}
.m-status-seg button[aria-pressed="true"] {
  background: var(--solid);
  color: var(--text);
  box-shadow: var(--shadow-1);
}
.m-fanout-link {
  border: 0;
  background: transparent;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 550;
  padding: 6px 8px;
  border-radius: 8px;
  cursor: pointer;
}
.m-fanout-link:active { background: var(--surface-3); }

.m-inbox-list {
  margin-bottom: 14px;
}
.m-inbox-row {
  min-height: 82px;
  padding: 16px 16px;
  gap: 14px;
}
.m-inbox-row .title {
  font-size: 15.5px;
  font-weight: 600;
  line-height: 1.35;
}
.m-sess-avatar {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 13px;
  background: var(--surface-2);
  color: var(--text);
  flex: none;
}
.m-sess-avatar .i { width: 22px; height: 22px; }
.m-sess-avatar.oc-opencode {
  background: #141416;
  color: #eeeeee;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, .08);
}
.m-sess-avatar.is-approval {
  background: var(--warn-soft);
  color: var(--warn);
}
.m-sess-avatar.is-running:not(.oc-opencode) {
  background: var(--accent-soft);
  color: var(--accent);
}
.m-sess-top {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.m-sess-time {
  flex: none;
  font-size: 11.5px;
  color: var(--text-3);
}
.m-sess-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 6px;
  min-width: 0;
}
.m-sess-sub-mini {
  flex: 1;
  min-width: 0;
  font-size: 12.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.m-sess-diff-num {
  color: var(--ok);
}
.m-sess-state-pill {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 560;
  padding: 2px 7px;
  border-radius: 999px;
  line-height: 1.3;
}
.m-sess-state-pill.is-done {
  color: var(--text-3);
  background: var(--surface-2);
}
.m-sess-state-pill.is-unread {
  color: var(--ok);
  background: var(--ok-soft);
}
.m-sess-state-pill.is-running {
  color: var(--accent);
  background: var(--accent-soft);
}
.m-sess-state-pill.is-approval {
  color: var(--warn);
  background: var(--warn-soft);
}
.m-state-ic {
  width: 11px;
  height: 11px;
  flex: none;
}
.m-state-spinner {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1.6px solid color-mix(in srgb, currentColor 25%, transparent);
  border-top-color: currentColor;
  animation: m-state-spin .85s linear infinite;
  flex: none;
}
.m-state-ic.is-pulse {
  animation: m-state-pulse 1.6s ease-in-out infinite;
}
.m-state-ic.is-pop {
  animation: m-state-breathe 2.2s ease-in-out infinite;
}
@keyframes m-state-spin {
  to { transform: rotate(360deg); }
}
@keyframes m-state-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: .55; transform: scale(.88); }
}
@keyframes m-state-breathe {
  0%, 100% { opacity: 1; }
  50% { opacity: .6; }
}
:global([data-motion="reduced"]) .m-state-spinner,
:global([data-motion="reduced"]) .m-state-ic.is-pulse,
:global([data-motion="reduced"]) .m-state-ic.is-pop {
  animation: none;
}

.m-inbox-empty {
  display: grid;
  justify-items: center;
  text-align: center;
  gap: 10px;
  padding: 28px 18px;
}
.m-empty-ic {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border-radius: 18px;
  background: var(--accent-soft);
  color: var(--accent);
}
.m-empty-ic .i { width: 24px; height: 24px; }
.m-inbox-empty h3 { margin: 2px 0 0; font-size: 17px; }
.m-inbox-empty p { margin: 0; font-size: 13px; line-height: 1.55; max-width: 280px; }
.m-empty-actions {
  display: grid;
  gap: 8px;
  width: 100%;
  max-width: 260px;
  margin-top: 6px;
}
.m-empty-actions .btn {
  min-height: 44px;
  justify-content: center;
  border-radius: 14px;
  font-size: 14.5px;
}

/* 第二层：全屏沉浸对话页 */
.m-thread-shell {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--bg);
}
.m-thread-bar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 54px;
  padding: 7px 12px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--bg) 92%, var(--solid));
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  z-index: 5;
}
.m-bar-btn {
  position: relative;
  display: inline-grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 0;
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--text-2);
  cursor: pointer;
  flex: none;
  transition: background-color var(--dur-1), color var(--dur-1), scale var(--dur-1);
}
.m-bar-btn:active { background: var(--surface-3); color: var(--text); scale: .93; }
.m-bar-btn:disabled { opacity: .4; cursor: default; }
.m-bar-btn .i { width: 16.5px; height: 16.5px; }
.m-bar-btn .m-wb-dot {
  top: -3px;
  right: -3px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  font-size: 10px;
  line-height: 16px;
  box-shadow: 0 0 0 2px var(--bg);
}
.m-thread-title-btn {
  flex: 1;
  min-width: 0;
  display: grid;
  justify-items: start;
  gap: 2px;
  padding: 3px 6px 3px 2px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.m-thread-title-btn:active { background: var(--surface-2); }
.m-tt-main {
  max-width: 100%;
  font-size: 14.5px;
  font-weight: 650;
  letter-spacing: -0.01em;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.m-tt-sub {
  max-width: 100%;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.m-tt-sub .conn {
  width: 6px;
  height: 6px;
}
.m-tt-chev { width: 10px; height: 10px; flex: none; opacity: .65; }
.m-thread-actions {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex: none;
}
.m-bg-approval-bar {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--warn-soft);
  border-bottom: 1px solid color-mix(in srgb, var(--warn) 30%, transparent);
  font-size: 12.5px;
}
.m-bga-copy {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.m-thread-shell .mchat-thread {
  flex: 1;
  min-height: 0;
}

/* 原生 <dialog> 移动端底部 Sheet */
.msheet-dlg {
  margin: auto 0 0 0;
  padding: 0;
  width: 100%;
  max-width: 100%;
  max-height: 82dvh;
  border: 0;
  border-radius: 24px 24px 0 0;
  background: var(--solid);
  color: var(--text);
  box-shadow: var(--shadow-pop);
}
.msheet-panel {
  display: grid;
  gap: 14px;
  padding: 10px 16px calc(22px + env(safe-area-inset-bottom));
}
.msheet-grab {
  width: 36px;
  height: 4px;
  margin: 0 auto;
  border-radius: 999px;
  background: var(--line-strong);
}
.msheet-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.msheet-hdr h3 { margin: 0; font-size: 16px; font-weight: 680; }
.msheet-sec { display: grid; gap: 8px; }
.msheet-label { font-size: 12px; font-weight: 600; color: var(--text-3); }
.msheet-rename-row { display: flex; gap: 8px; }
.msheet-rename-row .input { flex: 1; height: 40px; }
.msheet-actions {
  display: grid;
  border-radius: 16px;
  overflow: hidden;
  background: var(--surface-2);
}
.msheet-row {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 46px;
  padding: 0 14px;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: 14px;
  text-align: left;
  cursor: pointer;
}
.msheet-row + .msheet-row { border-top: 1px solid var(--line); }
.msheet-row:active { background: var(--surface-3); }
.msheet-row .i { width: 16px; height: 16px; color: var(--text-2); flex: none; }
.msheet-row-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.msheet-row.is-danger,
.msheet-row.is-danger .i { color: var(--danger); }

@media (max-width: 700px) {
  .modal-card {
    width: calc(100vw - 24px);
    max-height: calc(100dvh - 32px);
    overflow-y: auto;
    overscroll-behavior: contain;
  }
  .modal-foot .btn {
    min-height: 40px;
    padding: 0 16px;
  }
}
</style>
