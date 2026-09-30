<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { RotateCcw, SlidersHorizontal } from 'lucide-vue-next'
import Sidebar from '../components/layout/Sidebar.vue'
import TopBar from '../components/layout/TopBar.vue'
import DashboardRenderer from '../components/dashboard/DashboardRenderer.vue'
import { useWidgetLayout } from '../composables/useWidgetLayout'
import { useAuthStore } from '../stores/auth'
import { useDashboardStore } from '../stores/dashboard'
import { useDevicesStore } from '../stores/devices'
import { useAgentsStore } from '../stores/agents'
import { scrollPageToTop } from '../desktop/desktopInteractions'

const emit = defineEmits<{ navigate: [page: string]; create: [kind: string] }>()
const auth = useAuthStore()
const dashboard = useDashboardStore()
const devices = useDevicesStore()
const agents = useAgentsStore()
const activeItem = ref('Home')
const toast = ref('')
let toastTimeout: ReturnType<typeof setTimeout> | undefined
let focusTimeout: ReturnType<typeof setTimeout> | undefined
let statusRefresh: ReturnType<typeof setInterval> | undefined

function showToast(message: string) {
  toast.value = message
  if (toastTimeout) clearTimeout(toastTimeout)
  toastTimeout = setTimeout(() => { toast.value = '' }, 3200)
}

const { board, desktop, editing, activeWidget, scale, begin, keyAdjust, finish, resetWidget, resetAll } = useWidgetLayout(showToast)
const destinationPages = ['Websites', 'Devices', 'Agents', 'Data', 'Ledger', 'Automation', 'API', 'Settings']

function focusSection(id: string) {
  const section = document.getElementById(id)
  if (!section) return
  section.scrollIntoView({ behavior: 'smooth', block: 'center' })
  document.querySelectorAll('.widget--focused').forEach(node => node.classList.remove('widget--focused'))
  section.classList.add('widget--focused')
  if (focusTimeout) clearTimeout(focusTimeout)
  focusTimeout = setTimeout(() => section.classList.remove('widget--focused'), 1800)
}
function selectNav(item: string) {
  activeItem.value = item
  if (item === 'Home') scrollPageToTop('smooth')
  else if (destinationPages.includes(item)) emit('navigate', item)
}
onMounted(async () => {
  statusRefresh = setInterval(() => {
    if (!auth.token) return
    void devices.load(auth.token, true)
    void agents.load(auth.token)
  }, 30_000)
  try {
    if (!auth.token) return
    await dashboard.load(auth.token)
  } catch {
    showToast('暂时无法同步，布局将保存在此浏览器。')
  }
})
onUnmounted(() => {
  if (toastTimeout) clearTimeout(toastTimeout)
  if (focusTimeout) clearTimeout(focusTimeout)
  if (statusRefresh) clearInterval(statusRefresh)
})
</script>

<template>
  <div class="dashboard-shell nexa-shell">
    <Sidebar :active-item="activeItem" @select="selectNav" />
    <main class="dashboard-main">
      <TopBar @navigate="focusSection" @create="kind => ['网站快捷方式', '数据集', '自动化'].includes(kind) ? emit('create', kind) : showToast(`${kind}功能即将推出。`)" />
      <div class="board-wrap">
        <div class="dashboard-layout-toolbar">
          <span v-if="editing && desktop" class="layout-hint">拖动卡片上方移动，拖动右下角调整大小</span>
          <button v-if="editing && desktop" type="button" class="layout-button layout-button--reset" @click="resetAll"><RotateCcw :size="15" />恢复默认</button>
          <button v-if="desktop" type="button" class="layout-button" :class="{ 'layout-button--active': editing }" :aria-pressed="editing" @click="editing = !editing; finish(false)">
            <SlidersHorizontal :size="16" />{{ editing ? '完成调整' : '调整布局' }}
          </button>
        </div>
        <div class="dashboard-scroll" data-desktop-scroll>
        <div ref="board" class="board-measure">
          <DashboardRenderer
            :widgets="dashboard.widgets"
            :editing="editing"
            :active-widget="activeWidget"
            :desktop="desktop"
            :scale="scale"
            @move-start="(id, event) => begin(id, 'move', event)"
            @resize-start="(id, event) => begin(id, 'resize', event)"
            @move-key="(id, event) => keyAdjust(id, 'move', event)"
            @resize-key="(id, event) => keyAdjust(id, 'resize', event)"
            @reset="resetWidget"
            @action="showToast"
          />
        </div>
        </div>
      </div>
    </main>
    <Transition name="toast"><div v-if="toast" class="dashboard-toast" role="status"><span class="dashboard-toast__mark">✦</span>{{ toast }}</div></Transition>
  </div>
</template>

<style scoped>
.dashboard-main { min-width: 0; }
.board-wrap { position: relative; }
.board-measure { width: 100%; }
.dashboard-layout-toolbar { position: absolute; z-index: 20; top: -37px; right: 0; display: flex; align-items: center; gap: 8px; }
.layout-hint { margin-right: 3px; color: rgba(255,255,255,.94); font-size: 12px; text-shadow: 0 1px 5px rgba(30,40,80,.4); white-space: nowrap; }
.layout-button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; min-height: 29px; padding: 4px 10px; border: 1px solid rgba(255,255,255,.48); border-radius: 10px; background: rgba(94,121,183,.43); box-shadow: 0 4px 15px rgba(23,40,91,.1); color: white; font-size: 12px; font-weight: 570; white-space: nowrap; backdrop-filter: blur(13px); }
.layout-button:hover, .layout-button--active { background: rgba(102,137,237,.7); }
.layout-button--reset { background: rgba(94,121,183,.28); }
.dashboard-toast { position: fixed; z-index: 50; right: 30px; bottom: 24px; display: flex; align-items: center; gap: 8px; max-width: min(350px, calc(100vw - 32px)); padding: 12px 17px; color: #fff; border: 1px solid rgba(255,255,255,.35); border-radius: 15px; background: rgba(45,61,105,.87); box-shadow: 0 15px 40px rgba(18,31,71,.26); backdrop-filter: blur(20px); font-size: 12px; font-weight: 610; }
.dashboard-toast__mark { color: #b9d9ff; font-size: 15px; }
.toast-enter-active, .toast-leave-active { transition: opacity .2s, transform .2s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(10px); }
@media (max-width: 1279px) {
  .dashboard-layout-toolbar { position: static; justify-content: flex-end; margin: -36px 0 8px; }
  .layout-hint, .layout-button--reset { display: none; }
}
@media (max-width: 700px) {
  .dashboard-layout-toolbar { margin: 0 0 10px; }
}
</style>
