<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Search, ChevronRight, Globe2, StickyNote, Workflow, Database } from 'lucide-vue-next'
import { useDashboardStore } from '../../stores/dashboard'
import { useAuthStore } from '../../stores/auth'
import TopActionControls from './TopActionControls.vue'

const props = defineProps<{ name?: string }>()
const auth = useAuthStore()
const displayName = computed(() => props.name ?? auth.user?.username ?? '访客')
const dashboard = useDashboardStore()

const emit = defineEmits<{ navigate: [section: string]; create: [kind: string] }>()
const toolbarRef = ref<HTMLElement | null>(null)
const actionControls = ref<{ closeMenus: () => void } | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const query = ref('')
const searchOpen = ref(false)
const now = ref(new Date())
let timeInterval: number | undefined
const homeCreateItems = [
  { label: '网站快捷方式', kind: '网站快捷方式', icon: Globe2 },
  { label: '数据集', kind: '数据集', icon: Database },
  { label: '自动化', kind: '自动化', icon: Workflow },
  { label: '便签', kind: '便签', icon: StickyNote },
]

const greeting = computed(() => {
  const hour = now.value.getHours()
  return hour < 12 ? '早上好' : hour < 18 ? '下午好' : '晚上好'
})
const date = computed(() => new Intl.DateTimeFormat('zh-CN', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }).format(now.value))
const details: Record<string, string> = {
  'quick-access': '网站与快捷方式', clock: '时钟与天气', device: '已连接的设备', agent: 'AI 活动',
  ledger: '余额与收支', system: '性能概览', collections: '结构化数据', automation: '定时流程', notes: '最近记录',
}
const sections = computed(() => dashboard.widgets.map(widget => ({
  label: widget.title, detail: details[widget.type] ?? '仪表盘组件', id: widget.id,
})))
const filteredSections = computed(() => {
  const search = query.value.trim().toLowerCase()
  return (search ? sections.value.filter(item => `${item.label} ${item.detail}`.toLowerCase().includes(search)) : sections.value.slice(0, 4)).slice(0, 6)
})

function closeMenus() {
  searchOpen.value = false
  actionControls.value?.closeMenus()
}
function openSearch() {
  actionControls.value?.closeMenus()
  searchOpen.value = true
}
function navigate(id: string) {
  emit('navigate', id)
  query.value = ''
  closeMenus()
  searchInput.value?.blur()
}
function onDocumentPointerDown(event: PointerEvent) {
  if (!toolbarRef.value?.contains(event.target as Node)) closeMenus()
}
function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeMenus()
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    searchInput.value?.focus()
    openSearch()
  }
}
onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown)
  document.addEventListener('keydown', onDocumentKeydown)
  timeInterval = window.setInterval(() => { now.value = new Date() }, 60_000)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
  if (timeInterval !== undefined) window.clearInterval(timeInterval)
})
</script>

<template>
  <header class="topbar">
    <div class="topbar__intro">
      <h1>{{ greeting }}，{{ displayName }}。</h1>
      <div class="topbar__date">{{ date }}</div>
      <p>让数字生活更有条理。</p>
    </div>

    <div ref="toolbarRef" class="topbar__tools">
      <div class="search-wrap">
        <div class="search-box" :class="{ 'search-box--active': searchOpen }">
          <Search :size="22" :stroke-width="1.8" />
          <input ref="searchInput" v-model="query" type="search" placeholder="搜索任何内容..." aria-label="搜索仪表盘" @focus="openSearch" @keydown.enter="filteredSections[0] && navigate(filteredSections[0].id)" />
          <kbd>Ctrl</kbd><kbd>K</kbd>
        </div>
        <div v-if="searchOpen" class="toolbar-popover search-results">
          <div class="popover-heading">{{ query ? '搜索结果' : '快速跳转' }}</div>
          <button v-for="item in filteredSections" :key="item.id" class="search-result" type="button" @click="navigate(item.id)">
            <span><strong>{{ item.label }}</strong><small>{{ item.detail }}</small></span><ChevronRight :size="15" />
          </button>
          <p v-if="!filteredSections.length" class="search-empty">没有找到相关内容。</p>
        </div>
      </div>

      <TopActionControls ref="actionControls" :create-items="homeCreateItems" @opened="searchOpen = false" @create="kind => emit('create', kind)" />
    </div>
  </header>
</template>

<style scoped>
.topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; height: 142px; padding: 31px 0 0 20px; color: #fff; }
.topbar__intro { min-width: 0; text-shadow: 0 2px 12px rgba(40,54,96,.2); }
h1 { margin: 0; color: #fff; font-size: clamp(30px, 2.5vw, 38px); font-weight: 400; line-height: 1.15; letter-spacing: -.045em; white-space: nowrap; }
.topbar__date { margin-top: 9px; color: rgba(255,255,255,.94); font-size: 17px; font-weight: 450; line-height: 1.2; }
.topbar__intro p { margin: 4px 0 0; color: rgba(255,255,255,.58); font-size: 14px; font-weight: 450; }
.topbar__tools { display: flex; align-items: center; gap: 14px; padding-top: 0; }
.search-wrap { position: relative; }
.search-box {
  display: flex;
  align-items: center;
  gap: 10px;
  width: clamp(240px, 23vw, 338px);
  height: 47px;
  padding: 0 14px;
  color: #fff;
  border: 1px solid rgba(255,255,255,.19);
  border-radius: 15px;
  background: rgba(185,205,245,.19);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.09);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  transition: background .2s, box-shadow .2s;
}
.search-box--active, .search-box:hover { background: rgba(211,225,255,.28); box-shadow: 0 8px 24px rgba(17,30,73,.12), inset 0 1px 0 rgba(255,255,255,.13); }
.search-box svg { flex: none; }
.search-box input { width: 100%; min-width: 0; padding: 0; color: #fff; border: 0; outline: 0; background: none; font-size: 12px; }
.search-box input::placeholder { color: rgba(255,255,255,.76); }
.search-box input::-webkit-search-cancel-button { display: none; }
.search-box kbd { flex: none; display: grid; min-width: 24px; height: 25px; place-items: center; padding: 0 6px; border: 1px solid rgba(255,255,255,.17); border-radius: 6px; color: rgba(255,255,255,.75); background: rgba(202,218,255,.12); font-size: 11px; font-family: inherit; }
.search-box kbd + kbd { margin-left: -7px; }
.toolbar-popover { position: absolute; z-index: 30; top: calc(100% + 10px); right: 0; width: 280px; padding: 12px; color: #fff; border: 1px solid rgba(255,255,255,.28); border-radius: 18px; background: rgba(43,59,103,.92); box-shadow: 0 20px 45px rgba(20,31,67,.35), inset 0 1px 0 rgba(255,255,255,.12); backdrop-filter: blur(28px); }
.popover-heading { display: flex; justify-content: space-between; padding: 4px 7px 10px; color: rgba(255,255,255,.6); font-size: 10px; font-weight: 700; letter-spacing: .12em; }
.popover-heading span { color: #a7d9ff; }
.search-results { left: 0; right: auto; width: max(280px, 100%); }
.search-result, .create-item { display: flex; align-items: center; width: 100%; text-align: left; color: rgba(255,255,255,.82); border: 0; border-radius: 10px; background: transparent; transition: background .2s; }
.search-result { justify-content: space-between; padding: 9px 8px; }
.search-result:hover, .create-item:hover { background: rgba(255,255,255,.13); }
.search-result span { display: flex; flex-direction: column; gap: 3px; }
.search-result strong { color: #fff; font-size: 12px; }
.search-result small { color: rgba(255,255,255,.62); font-size: 10px; }
.search-empty { margin: 8px; color: rgba(255,255,255,.72); font-size: 11px; }
@media (max-width: 1150px) { .topbar { gap: 12px; padding-left: 4px; } .search-box { width: 220px; } }
@media (max-width: 800px) { .topbar { height: auto; min-height: 0; padding: 24px 4px; flex-wrap: wrap; gap: 18px; } .topbar__tools { width: 100%; } .search-wrap { flex: 1; } .search-box { width: 100%; } }
@media (max-width: 420px) { h1 { font-size: 29px; } .topbar__tools { gap: 7px; } .topbar__date { font-size: 15px; } .search-box kbd { display: none; } }
</style>
