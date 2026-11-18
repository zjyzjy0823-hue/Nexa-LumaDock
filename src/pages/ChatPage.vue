<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import AgentChatThread from '../components/chat/AgentChatThread.vue'
import { getPlatformIcon, getProviderMeta } from '../components/chat/providerMeta'
import OpusIcon from '../components/ui/OpusIcon.vue'
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
const treeOpen = ref(true)
const treeWidth = ref(readStoredWidth('studiolo:chat-tree-w', TREE_DEFAULT_W, TREE_MIN_W, TREE_MAX_W))
const rightMode = ref<'none' | 'split'>('none')
const splitPercent = ref(readStoredWidth('studiolo:chat-split-percent', 50, 5, 95))
const isResizing = ref(false)
const treeQuery = ref('')
const actionsMenu = ref<HTMLDetailsElement>()

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

onUnmounted(() => {
  sharedChatOccupiedWidth.value = 0
})

onMounted(async () => {
  await fleet.loadNodes()
  fleet.connectSocket()
  if (fleet.selectedNode?.allowedRoots?.length) {
    newSessionCwd.value = fleet.selectedNode.allowedRoots[0]
  }
})

// 当新会话激活时，自动纳入顶部标签页栏
watch(
  () => fleet.activeSessionKey,
  key => {
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

function sessionsForNodeRoot(nodeId: string, root: string): ChatSession[] {
  const term = treeQuery.value.trim().toLowerCase()
  return fleet.allSessions.filter(s => {
    if (s.nodeId !== nodeId || !sessionBelongsToRoot(s, root)) return false
    if (!term) return true
    return `${s.title} ${s.cwd} ${s.provider}`.toLowerCase().includes(term)
  })
}

function orphanSessionsForNode(node: AgentNode): ChatSession[] {
  const term = treeQuery.value.trim().toLowerCase()
  return fleet.allSessions.filter(s => {
    if (s.nodeId !== node.id) return false
    if (node.allowedRoots.some(r => sessionBelongsToRoot(s, r))) return false
    if (!term) return true
    return `${s.title} ${s.cwd} ${s.provider}`.toLowerCase().includes(term)
  })
}

function matchesTreeFilter(node: AgentNode): boolean {
  const term = treeQuery.value.trim().toLowerCase()
  if (!term) return true
  if (node.name.toLowerCase().includes(term)) return true
  if (node.allowedRoots.some(r => r.toLowerCase().includes(term))) return true
  return fleet.allSessions.some(
    s => s.nodeId === node.id && `${s.title} ${s.cwd} ${s.provider}`.toLowerCase().includes(term),
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

function openSessionInSplit(sess: ChatSession) {
  const sKey = sessionKey(sess.nodeId, sess.provider, sess.sessionId)
  secondaryTabKey.value = sKey
  rightMode.value = 'split'
}

function toggleRightMode(target: 'split') {
  if (rightMode.value === target) {
    rightMode.value = 'none'
    return
  }
  if (target === 'split' && !secondaryTabKey.value) {
    const alt = fleet.allSessions.find(
      s => sessionKey(s.nodeId, s.provider, s.sessionId) !== fleet.activeSessionKey,
    )
    if (alt) {
      secondaryTabKey.value = sessionKey(alt.nodeId, alt.provider, alt.sessionId)
    }
  }
  rightMode.value = target
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
  rightMode.value = 'split'
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
            <button type="button" class="icon-btn" title="管理节点凭证 (sn_live_)" @click="emit('navigate', 'Agents')">
              <OpusIcon name="settings" />
            </button>
            <button type="button" class="icon-btn" title="新建隔离会话" @click="openCreateSession()">
              <OpusIcon name="plus" />
            </button>
          </div>
          <div class="tree-search">
            <OpusIcon name="search" />
            <input v-model="treeQuery" type="search" placeholder="筛选节点、目录或会话…" aria-label="筛选节点或会话" />
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
                      <div class="tree-sess-title">{{ sess.title }}</div>
                      <div v-if="sess.worktreePath" class="tree-sess-wt">
                        <OpusIcon name="branch" />
                        <span>{{ leafPathName(sess.worktreePath) }}</span>
                      </div>
                    </div>
                    <span class="tree-eng">{{ getProviderMeta(sess.provider).shortCode }}</span>
                    <button
                      type="button"
                      class="tree-mini-btn tree-split-trigger"
                      title="在右侧分屏并行查看"
                      @click.stop="openSessionInSplit(sess)"
                    >⊞</button>
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
                  <span class="tree-sess-title">{{ sess.title }}</span>
                  <span class="tree-eng">{{ getProviderMeta(sess.provider).shortCode }}</span>
                  <button
                    type="button"
                    class="tree-mini-btn tree-split-trigger"
                    title="在右侧分屏并行查看"
                    @click.stop="openSessionInSplit(sess)"
                  >⊞</button>
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
    <section class="fleet-main chat" :style="{ flexGrow: rightMode === 'split' ? 100 - splitPercent : 1 }">
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
            class="btn btn-sm"
            :class="rightMode === 'split' ? 'btn-primary' : 'btn-ghost'"
            title="在右侧开启并排协同分屏"
            @click="toggleRightMode('split')"
          >
            <OpusIcon name="grid" />
            <span>分屏</span>
          </button>
          <details ref="actionsMenu" class="session-actions"
            @focusout="onActionsFocusOut"
            @keydown.esc="closeActions(); actionsMenu?.querySelector('summary')?.focus()">
            <summary class="icon-btn" title="更多会话操作" aria-label="更多会话操作"><OpusIcon name="more" /></summary>
            <div class="action-list" @click="closeActions">
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
        :session-key="fleet.activeSessionKey || undefined"
        @action="emit('action', $event)"
        @open-handoff="openHandoffDialog"
      />
    </section>

    <!-- 右侧可自由拖动的并排分屏 / 沙箱通道检查器 -->
    <template v-if="rightMode !== 'none'">
      <div
        class="col-resizer"
        data-tauri-drag-region="false"
        title="左右拖动调整右侧栏宽度（双击还原）"
        @pointerdown="handleRightDrag"
        @dblclick="resetRightWidth"
      />

      <aside v-if="rightMode === 'split'" class="fleet-right-pane" :style="{ flexGrow: splitPercent }">
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
          <button type="button" class="icon-btn" title="关闭并排分屏" @click="rightMode = 'none'">
            <OpusIcon name="x" />
          </button>
        </div>
        <AgentChatThread
          v-if="secondaryTabKey"
          :session-key="secondaryTabKey"
          @action="emit('action', $event)"
          @open-handoff="openHandoffDialog"
        />
        <div v-else class="right-empty">
          <p class="faint">选择已有会话，或点右上角的加号新建会话。</p>
        </div>
      </aside>

    </template>

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

/* 右侧并排分屏 / 沙箱通道栏 */
.fleet-right-pane {
  flex: none;
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
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
</style>
