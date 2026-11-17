<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import OpusIcon from '../components/ui/OpusIcon.vue'
import TopBar from '../components/layout/TopBar.vue'
import DashboardRenderer from '../components/dashboard/DashboardRenderer.vue'
import { useWidgetLayout } from '../composables/useWidgetLayout'
import { useAuthStore } from '../stores/auth'
import { useDashboardStore } from '../stores/dashboard'
import { useDevicesStore } from '../stores/devices'
import { useAgentsStore } from '../stores/agents'

defineProps<{ mobile?: boolean }>()
const emit = defineEmits<{ navigate: [page: string]; create: [kind: string]; action: [message: string]; back: [] }>()
const auth = useAuthStore()
const dashboard = useDashboardStore()
const devices = useDevicesStore()
const agents = useAgentsStore()
let focusTimeout: ReturnType<typeof setTimeout> | undefined
let statusRefresh: ReturnType<typeof setInterval> | undefined

function showToast(message: string) {
  emit('action', message)
}

const { board, desktop, editing, activeWidget, scale, begin, keyAdjust, finish, resetWidget, resetAll } = useWidgetLayout(showToast)

function focusSection(id: string) {
  const section = document.getElementById(id)
  if (!section) return
  section.scrollIntoView({ behavior: 'smooth', block: 'center' })
  document.querySelectorAll('.widget--focused').forEach(node => node.classList.remove('widget--focused'))
  section.classList.add('widget--focused')
  if (focusTimeout) clearTimeout(focusTimeout)
  focusTimeout = setTimeout(() => section.classList.remove('widget--focused'), 1800)
}
onMounted(async () => {
  statusRefresh = setInterval(() => {
    if (!auth.token) return
    void devices.load(auth.token, true)
    void agents.load(auth.token)
    if (!editing.value && !dashboard.saving) void dashboard.load(auth.token).catch(() => {})
  }, 30_000)
  try {
    if (!auth.token) return
    await dashboard.load(auth.token)
  } catch {
    showToast('暂时无法同步，布局将保存在此浏览器。')
  }
})
onUnmounted(() => {
  if (focusTimeout) clearTimeout(focusTimeout)
  if (statusRefresh) clearInterval(statusRefresh)
})
</script>

<template>
  <div class="dashboard-main" :class="mobile ? 'mpage push' : undefined">
    <div v-if="mobile" class="navbar">
      <button class="icon-btn" type="button" aria-label="返回" @click="emit('back')"><OpusIcon name="chevL" /></button>
      <div class="t">自定义仪表盘</div>
      <span style="width:40px"></span>
    </div>
    <header v-else class="ph">
      <div><h1>自定义仪表盘</h1><div class="sub">自由调整旧版快捷组件与位置</div></div>
      <div class="actions">
        <button class="btn btn-ghost" type="button" @click="emit('navigate', 'Home')"><OpusIcon name="chevL" />返回「今天」</button>
        <button v-if="editing && desktop" type="button" class="btn btn-ghost" @click="resetAll"><OpusIcon name="sync" />恢复默认</button>
        <button v-if="desktop" type="button" class="btn" :class="editing ? 'btn-primary' : 'btn-ghost'" :aria-pressed="editing" @click="editing = !editing; finish(false)">
          <OpusIcon name="grid" />{{ editing ? '完成调整' : '调整布局' }}
        </button>
      </div>
    </header>
    <TopBar @navigate="focusSection" @create="kind => ['网站快捷方式', '数据集', '自动化'].includes(kind) ? emit('create', kind) : showToast(`${kind}功能即将推出。`)" />
    <div class="board-wrap">
      <p v-if="editing && desktop" class="faint" style="margin:0 0 10px;font-size:12.5px">拖动卡片上方移动，拖动右下角调整大小</p>
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
</template>

<style scoped>
.dashboard-main { min-width: 0; }
.board-wrap { position: relative; }
.board-measure { width: 100%; }
</style>
