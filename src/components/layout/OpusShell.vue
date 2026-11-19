<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Wifi, WifiOff } from 'lucide-vue-next'
import { desktopPlatform } from '../../desktop/platform'
import type { WorkbenchTheme } from '../../composables/useWorkbenchTheme'
import DesktopTitleBar from '../desktop/DesktopTitleBar.vue'
import { useCoreSync } from '../../composables/useCoreSync'
import {
  readStoredWidth,
  saveStoredWidth,
  sharedChatOccupiedWidth,
  startColumnDrag,
} from '../../composables/useResizableShell'
import { useAutomationStore } from '../../stores/automation'
import { useAuthStore } from '../../stores/auth'
import { useFleetStore } from '../../stores/fleet'
import AgentChatThread from '../chat/AgentChatThread.vue'
import { getProviderMeta } from '../chat/providerMeta'
import { version } from '../../../package.json'
import OpusSegment from '../ui/OpusSegment.vue'
import OpusIcon from '../ui/OpusIcon.vue'
import OpusSyncBadge from '../ui/OpusSyncBadge.vue'
import OpusQuickAdd from './OpusQuickAdd.vue'
import { footer, libraryItems, mobileTabs, navigation } from './opusNavigation'

interface ToastItem {
  id: number
  text: string
  out: boolean
}

const props = defineProps<{ page: string; mobile: boolean; hideMobileTabbar?: boolean; toast: string; toastKey?: number; theme: WorkbenchTheme; mode: string; reducedMotion?: boolean }>()
const emit = defineEmits<{ navigate: [page: string]; create: [kind: string]; action: [message: string]; syncSettings: []; back: []; toggleMode: []; toggleTheme: []; setTheme: [theme: WorkbenchTheme]; toggleReducedMotion: [] }>()
const auth = useAuthStore()
const automation = useAutomationStore()
const fleet = useFleetStore()
const attentionTasks = computed(() => automation.items.filter(item => {
  if (!item.enabled) return false
  const last = automation.runtimeExecutions.find(run => run.workflowId === item.id)
  return !last || last.status === 'failed'
}).length)
const { connection, syncStatus, syncError, busy, refresh, sync } = useCoreSync(message => emit('action', message))
const platform = desktopPlatform()
const mac = platform === 'macos' || /Mac/i.test(navigator.platform)
const ctrl = mac ? '⌘' : 'Ctrl'

const SIDEBAR_EXPANDED_W = 232
const DOCK_DEFAULT_W = 380
const DOCK_MIN_W = 280
const DOCK_MAX_W = 560

function readStoredCollapsed(): boolean | null {
  try {
    const raw = localStorage.getItem('studiolo:sidebar-collapsed')
    if (raw === '1') return true
    if (raw === '0') return false
  } catch {
    // 忽略存储受限环境错误
  }
  return null
}

const windowEl = ref<HTMLElement | null>(null)
const windowWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)
const dockWidth = ref(readStoredWidth('studiolo:dock-width', DOCK_DEFAULT_W, DOCK_MIN_W, DOCK_MAX_W))
const manualCollapsed = ref<boolean | null>(readStoredCollapsed())
const autoCollapsed = ref(false)
const isResizing = ref(false)
const dockOpen = ref(false)

function recomputeAutoCollapse() {
  const minMainNeeded = props.page === 'Chat' ? 460 : 560
  const hysteresis = autoCollapsed.value ? 26 : 0
  const extraW = (props.page === 'Chat' ? sharedChatOccupiedWidth.value : 0) + (dockOpen.value ? dockWidth.value : 0)
  const remaining = windowWidth.value - SIDEBAR_EXPANDED_W - extraW
  const tightWindow = windowWidth.value < (autoCollapsed.value ? 926 : 900)
  const tightContent = remaining < (minMainNeeded + hysteresis)
  const shouldCollapse = tightWindow || tightContent
  autoCollapsed.value = shouldCollapse
  // 当空间恢复充足时，清除此前为适应窄屏自动生成的临时展开/收起状态，确保空间充足时恢复正常宽度
  if (!shouldCollapse && manualCollapsed.value === false) {
    manualCollapsed.value = null
  }
}

watch(
  [windowWidth, dockWidth, dockOpen, sharedChatOccupiedWidth, () => props.page],
  recomputeAutoCollapse,
  { immediate: true },
)

const collapsed = computed(() =>
  manualCollapsed.value !== null ? manualCollapsed.value : autoCollapsed.value,
)

function toggleSidebar() {
  const next = !collapsed.value
  // 手动点按切换后：若与当前自动判断结果一致则交回自动控制，否则持久记住点按状态
  manualCollapsed.value = next === autoCollapsed.value ? null : next
  try {
    if (manualCollapsed.value === null) localStorage.removeItem('studiolo:sidebar-collapsed')
    else localStorage.setItem('studiolo:sidebar-collapsed', manualCollapsed.value ? '1' : '0')
  } catch {
    // 忽略存储受限环境错误
  }
}

function handleDockDrag(event: PointerEvent) {
  if (event.button !== 0 || !event.isPrimary) return
  const previousWidth = dockWidth.value
  isResizing.value = true
  startColumnDrag({
    event,
    initialWidth: dockWidth.value,
    min: DOCK_MIN_W,
    max: DOCK_MAX_W,
    direction: -1,
    onPreview(width) {
      dockWidth.value = width
    },
    onCommit(width) {
      dockWidth.value = width
      saveStoredWidth('studiolo:dock-width', width)
    },
    onCancel() {
      dockWidth.value = previousWidth
    },
    onEnd() {
      isResizing.value = false
    },
  })
}

function resetDockWidth() {
  dockWidth.value = DOCK_DEFAULT_W
  saveStoredWidth('studiolo:dock-width', DOCK_DEFAULT_W)
}

watch(dockOpen, open => {
  if (open && auth.token) {
    void fleet.loadNodes()
    fleet.connectSocket()
  }
})
const panelOpen = ref(false)
const palette = ref<HTMLDialogElement>()
const query = ref('')
const commandIndex = ref(0)
const add = ref('')
const toasts = ref<ToastItem[]>([])
let toastSeq = 0
const navGroups = [...navigation, { section: '', items: footer }]
const activeGroup = computed(() => navGroups.find(group => group.items.some(item => item.page === props.page)))
const activeItem = computed(() => activeGroup.value?.items.find(item => item.page === props.page))
const inLibrary = computed(() => libraryItems.some(item => item.page === props.page))
const savedLibrary = ref('Ledger')
const mobileActive = ref('Home')
watch(() => props.page, page => {
  if (inLibrary.value) {
    savedLibrary.value = page
    mobileActive.value = 'Ledger'
  } else if (mobileTabs.some(tab => tab.page === page)) {
    mobileActive.value = page
  }
}, { immediate: true })

function pushToast(text: string) {
  if (!text) return
  const id = ++toastSeq
  for (const item of toasts.value) item.out = true
  toasts.value.push({ id, text, out: false })
  if (toasts.value.length > 3) toasts.value.shift()
  window.setTimeout(() => {
    const target = toasts.value.find(item => item.id === id)
    if (target) target.out = true
    window.setTimeout(() => {
      toasts.value = toasts.value.filter(item => item.id !== id)
    }, 360)
  }, 2600)
}
watch([() => props.toast, () => props.toastKey], ([text]) => {
  if (text) pushToast(text)
})

const syncKind = computed<'offline' | 'conflict' | 'pending' | 'synced'>(() => {
  if (!syncStatus.value?.connected) return 'offline'
  if (syncStatus.value.conflicts) return 'conflict'
  if (syncStatus.value.running || syncStatus.value.pending || syncStatus.value.inFlight || !syncStatus.value.lastSuccessAt) return 'pending'
  return 'synced'
})
const queued = computed(() => (syncStatus.value?.pending ?? 0) + (syncStatus.value?.inFlight ?? 0))
const syncLabel = computed(() => {
  const state = syncStatus.value
  if (!state) return syncError.value || '正在读取同步状态'
  if (!state.connected) return '离线 · 本机可用'
  if (state.blocked || state.lastError) return '同步需要处理'
  if (state.conflicts) return `${state.conflicts} 个冲突`
  if (state.running) return '正在同步'
  if (queued.value) return `${queued.value} 项待同步`
  return state.lastSuccessAt ? '已同步' : '等待首次同步'
})
const fleetLocalOnline = computed(() => !syncStatus.value?.connected && fleet.wsState === 'online')
const coreLabel = computed(() => {
  if (syncStatus.value?.connected) {
    return connection.value?.connected ? `Core · ${connection.value.coreUrl}` : 'Core'
  }
  if (fleetLocalOnline.value) return '本地 Fleet 在线（未启用远程 Core 同步）'
  return 'Core 不可达'
})
const commandGroups = [
  { label: '跳转', items: [
    ...navGroups.flatMap(group => [...group.items]).map(item => ({ ...item, hint: '', run: () => go(item.page) })),
    { page: 'Agents', label: 'Agent 配置', icon: 'settings', hint: '身份与权限', run: () => go('Agents') },
    { page: 'Dashboard', label: '自定义仪表盘', icon: 'grid', hint: '调整布局', run: () => go('Dashboard') },
  ] },
  { label: '操作', items: [
    { page: 'ledger', label: '记一笔', icon: 'ledger', hint: '在「账本」新增', run: () => emit('create', 'ledger') },
    { page: 'website', label: '收藏网站', icon: 'globe', hint: '快速添加链接', run: () => emit('create', 'website') },
    { page: 'record', label: '新建数据记录', icon: 'data', hint: '数据集合', run: () => emit('create', 'record') },
    { page: 'device', label: '添加设备', icon: 'device', hint: '客户端绑定', run: () => emit('create', 'device') },
    { page: 'agent', label: '添加智能体', icon: 'sparkle', hint: 'Agent 运行时', run: () => emit('create', 'agent') },
    { page: 'automation', label: '新建自动化任务', icon: 'tasks', hint: '定时与触发', run: () => emit('create', 'automation') },
    { page: 'dock', label: '切换 Agent 侧板', icon: 'sidebar', hint: `${ctrl} J`, run: () => { dockOpen.value = !dockOpen.value } },
    { page: 'sync', label: '立即同步', icon: 'sync', hint: '推送待同步队列', run: () => sync() },
    { page: 'syncSettings', label: '处理冲突与同步设置', icon: 'alert', hint: 'Core 连接', run: () => openSyncSettings() },
  ] },
  { label: '外观', items: [
    { page: 'mode', label: '切换深色 / 浅色', icon: 'moon', hint: '外观模式', run: () => emit('toggleMode') },
    { page: 'theme', label: '切换主题（Liquid Glass / 纸墨 / 纯白）', icon: 'layers', hint: '工作台主题', run: () => emit('toggleTheme') },
  ] },
] as const
const commands = computed(() => {
  const term = query.value.trim().toLowerCase()
  return commandGroups.flatMap(group => group.items.filter(item =>
    [item.label, item.page, group.label, item.hint].some(label => label.toLowerCase().includes(term)),
  ).map((item, index) => ({ ...item, group: index === 0 ? group.label : '' })))
})
function runCommand(index: number) {
  const command = commands.value[index]
  if (!command) return
  palette.value?.close()
  void command.run()
}
async function moveCommand(step: number) {
  if (!commands.value.length) return
  commandIndex.value = (commandIndex.value + step + commands.value.length) % commands.value.length
  await nextTick()
  palette.value?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' })
}
function go(page: string) {
  palette.value?.close()
  panelOpen.value = false
  add.value = ''
  emit('navigate', page)
}
function openPalette() {
  query.value = ''
  commandIndex.value = 0
  palette.value?.showModal()
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    add.value = ''
    panelOpen.value = false
  }
  if (props.mobile || !(event.ctrlKey || event.metaKey)) return
  if (event.key.toLowerCase() === 'k') {
    event.preventDefault()
    openPalette()
  }
  if (event.key.toLowerCase() === 'j') {
    event.preventDefault()
    dockOpen.value = !dockOpen.value
  }
  const target = event.target instanceof Element ? event.target : null
  const editable = !!target?.closest('input, textarea, select, [contenteditable="true"]')
  if (event.key.toLowerCase() === 'b' && !editable) {
    event.preventDefault()
    toggleSidebar()
  }
}
function dismissSync(event: PointerEvent) {
  if (panelOpen.value && event.target instanceof Element && !event.target.closest('.sync-panel, .sync-pill, .sb-item, .mpill')) {
    panelOpen.value = false
  }
}
function openSyncSettings() {
  panelOpen.value = false
  emit('syncSettings')
}
async function refreshState() {
  await refresh()
  emit('action', '已刷新同步与页面状态')
}
function logoutAccount() {
  emit('action', '已退出登录')
  auth.logout()
}
defineExpose({ openDock: () => { dockOpen.value = true } })
let resizeObserver: ResizeObserver | null = null
onMounted(() => {
  document.addEventListener('keydown', keydown)
  document.addEventListener('pointerdown', dismissSync)
  if (typeof ResizeObserver !== 'undefined' && windowEl.value) {
    resizeObserver = new ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width
      if (width && width > 0) windowWidth.value = width
    })
    resizeObserver.observe(windowEl.value)
  }
})
onUnmounted(() => {
  document.removeEventListener('keydown', keydown)
  document.removeEventListener('pointerdown', dismissSync)
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <div class="opus-shell" :data-platform="mac ? 'mac' : 'win'">
    <template v-if="mobile">
      <div class="screen">
        <div class="glass-wallpaper" aria-hidden="true"></div>
        <div class="mview">
          <slot :sync-status="syncStatus" :sync-label="syncLabel" :sync-kind="syncKind" :open-sync="openSyncSettings" :open-add="(kind: string) => add = kind" :in-library="inLibrary" />
        </div>
        <nav v-if="!hideMobileTabbar" class="tabbar" aria-label="主导航">
          <template v-for="tab in mobileTabs" :key="tab.page">
            <div v-if="tab.page === '+'" class="tab-add"><button type="button" aria-label="快速新增" :aria-expanded="!!add" @click="add = add ? '' : 'tx'"><OpusIcon name="plus" /></button></div>
            <button v-else class="tab" type="button" :aria-current="mobileActive === tab.page ? 'page' : undefined" @click="go(tab.page === 'Ledger' ? savedLibrary : tab.page)">
              <span class="ico"><OpusIcon :name="tab.icon" /></span>{{ tab.label }}
              <span v-if="tab.page === 'Home' && syncStatus?.conflicts" class="badge">{{ syncStatus.conflicts }}</span><span v-if="tab.page === 'Chat' && fleet.pendingApprovalsList.length" class="badge">{{ fleet.pendingApprovalsList.length }}</span><span v-if="tab.page === 'Automation' && attentionTasks" class="badge">{{ attentionTasks }}</span>
            </button>
          </template>
        </nav>
        <OpusQuickAdd :kind="add" :offline="syncKind === 'offline'" @change="add = $event" @create="add = ''; emit('create', $event)" @action="emit('action', $event)" />
        <div class="toast-host mtoast"><div v-for="item in toasts" :key="item.id" class="toast" :class="{ out: item.out }" role="status">{{ item.text }}</div></div>
      </div>
    </template>
    <div v-else class="stage">
      <div
        ref="windowEl"
        class="window"
        :class="{ 'nav-collapsed': collapsed, 'dock-open': dockOpen, 'is-resizing': isResizing }"
        :style="{ '--dock-w': `${dockWidth}px` }"
      >
        <div class="glass-wallpaper" aria-hidden="true"></div>
        <DesktopTitleBar
          v-if="platform !== 'macos'"
          authenticated
          :workstation="auth.workstation"
          :theme="theme"
          :mode="mode"
          :reduced-motion="reducedMotion"
          :sidebar-collapsed="collapsed"
          :dock-open="dockOpen"
          :sync-connected="!!syncStatus?.connected"
          @navigate="go"
          @create="emit('create', $event)"
          @open-palette="openPalette"
          @toggle-sidebar="toggleSidebar"
          @toggle-dock="dockOpen = !dockOpen"
          @sync="sync"
          @open-sync-settings="openSyncSettings"
          @set-theme="emit('setTheme', $event)"
          @toggle-mode="emit('toggleMode')"
          @toggle-reduced-motion="emit('toggleReducedMotion')"
          @back="emit('back')"
          @refresh="refreshState"
          @logout="logoutAccount"
          @action="emit('action', $event)"
        />
        <div v-else class="titlebar" data-tauri-drag-region>
          <div class="tb-left opus-mac" data-tauri-drag-region>
            <button class="icon-btn" type="button" aria-label="折叠侧栏" title="折叠侧栏" :aria-pressed="collapsed" @click="toggleSidebar"><OpusIcon name="panel" /></button>
          </div>
          <div class="tb-mid" data-tauri-drag-region>
            <div class="crumbs" data-tauri-drag-region><template v-if="activeGroup?.section"><span>{{ activeGroup.section }}</span><OpusIcon name="chevR" /></template><b>{{ activeItem?.label ?? (page === 'Agents' ? 'Agent 配置' : '仪表盘') }}</b></div>
            <button class="cmdk" type="button" aria-label="搜索或执行命令" @click="openPalette"><OpusIcon name="search" /><span>搜索或执行命令</span><span class="kbd">{{ ctrl }}</span><span class="kbd">K</span></button>
          </div>
          <div class="tb-right">
            <button class="sync-pill" type="button" aria-label="同步状态" :aria-expanded="panelOpen" @click="panelOpen = !panelOpen"><OpusSyncBadge :kind="syncKind" :label="syncLabel" /></button>
            <button class="icon-btn" type="button" aria-label="Agent 侧板" :title="'Agent 侧板（' + ctrl + ' J）'" :aria-pressed="dockOpen" @click="dockOpen = !dockOpen"><OpusIcon name="sidebar" /></button>
          </div>
        </div>
        <div class="win-body">
          <nav class="sidebar" aria-label="主导航">
            <div class="sidebar-scroll">
              <template v-for="group in navigation" :key="group.section">
                <div v-if="group.section" class="nav-sec">{{ group.section }}</div>
                <button v-for="item in group.items" :key="item.page" class="nav-item" type="button" :title="item.label" :aria-current="page === item.page ? 'page' : undefined" @click="go(item.page)">
                  <OpusIcon :name="item.icon" /><span class="label">{{ item.label }}</span>
                  <span v-if="item.page === 'Chat' && fleet.pendingApprovalsList.length" class="nav-badge-dot" :title="`有 ${fleet.pendingApprovalsList.length} 项待审批命令`" />
                  <OpusIcon v-if="item.page === 'Space'" name="lock" class="lockmark" /><span v-if="item.page === 'Automation' && attentionTasks" class="count" style="color:var(--danger)">●</span>
                </button>
              </template>
              <div class="nav-foot">
                <button v-for="item in footer" :key="item.page" class="nav-item" type="button" :title="item.label" :aria-current="page === item.page ? 'page' : undefined" @click="go(item.page)"><OpusIcon :name="item.icon" /><span class="label">{{ item.label }}</span><span v-if="item.page === 'Settings' && syncStatus?.conflicts" class="count alert">{{ syncStatus.conflicts }}</span></button>
                <button
                  class="nav-item nav-item--collapse"
                  type="button"
                  :aria-label="collapsed ? '展开侧栏' : '收起侧栏'"
                  :title="`${collapsed ? '展开侧栏' : '收起为单图标侧栏'}（${ctrl} B）`"
                  :aria-pressed="collapsed"
                  @click="toggleSidebar"
                >
                  <OpusIcon name="panel" /><span class="label">{{ collapsed ? '展开侧栏' : '收起侧栏' }}</span>
                </button>
              </div>
            </div>
            <button
              type="button"
              class="sidebar-edge-toggle"
              data-tauri-drag-region="false"
              :aria-label="collapsed ? '展开左侧导航栏' : '收起为单图标侧栏'"
              :title="`${collapsed ? '点击展开左侧导航栏' : '点击收起为单图标侧栏'}（${ctrl} B）`"
              :aria-pressed="collapsed"
              @click="toggleSidebar"
            />
          </nav>
          <main id="main" class="main" tabindex="-1" data-desktop-scroll>
            <slot :sync-status="syncStatus" :sync-label="syncLabel" :sync-kind="syncKind" :open-sync="openSyncSettings" :open-add="(kind: string) => add = kind" :in-library="false" />
          </main>
          <aside class="dock" aria-label="Agent 侧板" :inert="!dockOpen">
            <div
              v-if="dockOpen"
              class="col-resizer col-resizer--left"
              data-tauri-drag-region="false"
              title="左右拖拽调整侧板宽度（双击还原）"
              @pointerdown="handleDockDrag"
              @dblclick="resetDockWidth"
            />
            <div v-if="dockOpen" class="dock-inner">
              <div class="dock-h">
                <select
                  v-if="fleet.nodes.length"
                  class="input"
                  style="height:28px;font-size:12px;max-width:128px;padding:0 8px"
                  :value="fleet.selectedNode?.id || ''"
                  aria-label="选择控制节点"
                  @change="fleet.selectNode(($event.target as HTMLSelectElement).value)"
                >
                  <option v-for="n in fleet.nodes" :key="n.id" :value="n.id">{{ n.name }}</option>
                </select>
                <OpusSegment role="group" aria-label="选择 Agent">
                  <button
                    v-for="prov in fleet.availableProviders.slice(0, 2)"
                    :key="prov"
                    type="button"
                    :aria-pressed="fleet.selectedProvider === prov"
                    @click="fleet.selectProvider(prov)"
                  >{{ getProviderMeta(prov).label }}</button>
                </OpusSegment>
                <span class="spacer"></span>
                <button class="icon-btn" type="button" aria-label="在 Agent 页打开" title="在 Agent 页打开" @click="go('Chat')"><OpusIcon name="external" /></button>
                <button class="icon-btn" type="button" aria-label="关闭 Agent 侧板" @click="dockOpen = false"><OpusIcon name="x" /></button>
              </div>
              <AgentChatThread compact @action="emit('action', $event)" @open-handoff="go('Chat')" />
            </div>
          </aside>
        </div>
        <footer class="statusbar">
          <button
            class="sb-item"
            type="button"
            aria-haspopup="true"
            aria-controls="sync-panel"
            :aria-expanded="panelOpen"
            :title="coreLabel"
            :aria-label="'连接状态：' + (syncStatus?.connected ? 'Core 在线' : fleetLocalOnline ? '本地 Fleet 在线' : 'Core 离线')"
            @click="panelOpen = !panelOpen"
          >
            <Wifi v-if="syncStatus?.connected" :size="13" :stroke-width="2" style="color:var(--ok)" />
            <Wifi v-else-if="fleetLocalOnline" :size="13" :stroke-width="2" style="color:var(--ok)" />
            <WifiOff v-else :size="13" :stroke-width="2" style="color:var(--danger)" />
            <span>{{ syncStatus?.connected ? 'Core' : fleetLocalOnline ? '本地 · Fleet' : 'Core' }}</span>
          </button>
          <span class="spacer"></span>
          <span class="sb-item faint">v{{ version }}</span>
        </footer>
        <div id="sync-panel" class="sync-panel" :hidden="!panelOpen">
          <h3>同步</h3>
          <div class="faint" style="font-size:12.5px">{{ syncStatus?.lastSuccessAt ? '最近同步 ' + new Date(syncStatus.lastSuccessAt).toLocaleString() : syncLabel }}</div>
          <div class="queue">
            <div v-if="queued" class="row"><span class="tile-icon" style="width:26px;height:26px"><OpusIcon name="sync" /></span><span class="grow"><div class="title" style="font-size:12.5px">{{ queued }} 项待同步</div><div class="sub">更改已保存在本机，联网后同步到 Core</div></span><OpusSyncBadge kind="pending" label="排队中" /></div>
            <div v-if="syncStatus?.conflicts" class="row"><span class="tile-icon" style="width:26px;height:26px"><OpusIcon name="alert" /></span><span class="grow"><div class="title" style="font-size:12.5px">{{ syncStatus.conflicts }} 个冲突待处理</div><div class="sub">需要确认保留本机或 Core 版本</div></span><button type="button" class="btn btn-sm btn-danger" @click="openSyncSettings">处理冲突</button></div>
            <div v-if="!queued && !syncStatus?.conflicts" class="cleared" style="padding:20px"><OpusIcon :name="syncKind === 'offline' ? 'wifiOff' : 'checks'" />{{ syncKind === 'offline' ? '离线：所有更改都已保存在本机' : '所有更改均已同步' }}</div>
          </div>
          <div style="display:flex;gap:8px;align-items:center"><span class="faint" style="font-size:11.5px;flex:1">共享空间只同步密文，这里不显示内容名称。</span><button type="button" class="btn btn-ghost btn-sm" @click="openSyncSettings">同步设置</button><button type="button" class="btn btn-primary btn-sm" :disabled="!syncStatus?.connected || busy || syncStatus.running" @click="sync"><OpusIcon name="sync" />立即同步</button></div>
        </div>
        <div class="toast-host desk"><div v-for="item in toasts" :key="item.id" class="toast" :class="{ out: item.out }" role="status">{{ item.text }}</div></div>
      </div>
      <dialog ref="palette" class="dlg palette" aria-label="命令面板" closedby="any">
        <div class="pal-input"><OpusIcon name="search" /><input v-model="query" placeholder="跳转到页面、执行操作、搜索记录…" autocomplete="off" autofocus role="combobox" aria-expanded="true" aria-controls="pal-list" :aria-activedescendant="commands.length ? 'pal-choice-' + commandIndex : undefined" @input="commandIndex = 0" @keydown.down.prevent="moveCommand(1)" @keydown.up.prevent="moveCommand(-1)" @keydown.enter.prevent="runCommand(commandIndex)"><span class="kbd">Esc</span></div>
        <div id="pal-list" class="pal-list" role="listbox">
          <template v-for="(item, index) in commands" :key="item.page">
            <div v-if="item.group" class="pal-group">{{ item.group }}</div>
            <button :id="'pal-choice-' + index" class="pal-item" type="button" role="option" :aria-selected="index === commandIndex" @click="runCommand(index)"><OpusIcon :name="item.icon" />{{ item.label }}<span v-if="item.hint" class="hint">{{ item.hint }}</span></button>
          </template>
          <div v-if="!commands.length" class="cleared" style="padding:30px">没有匹配的命令</div>
        </div>
      </dialog>
    </div>
  </div>
</template>
