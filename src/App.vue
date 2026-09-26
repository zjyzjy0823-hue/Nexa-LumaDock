<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import Sidebar from './components/layout/Sidebar.vue'
import TopSearchBar from './components/layout/TopSearchBar.vue'
import DashboardPage from './pages/DashboardPage.vue'
import WebsitesPage from './pages/WebsitesPage.vue'
import DevicesPage from './pages/DevicesPage.vue'
import AgentsPage from './pages/AgentsPage.vue'
import DataPage from './pages/DataPage.vue'
import LedgerPage from './pages/LedgerPage.vue'
import AutomationPage from './pages/AutomationPage.vue'

type Page = 'Home' | 'Websites' | 'Devices' | 'Agents' | 'Data' | 'Ledger' | 'Automation'
const pagePaths: Record<Page, string> = {
  Home: '/', Websites: '/websites', Devices: '/devices', Agents: '/agents',
  Data: '/data', Ledger: '/ledger', Automation: '/automation',
}
const pageByPath = Object.fromEntries(Object.entries(pagePaths).map(([key, value]) => [value, key])) as Record<string, Page>
function pageFromLocation(): Page {
  const legacyHash = window.location.hash.slice(1).toLowerCase()
  const path = window.location.pathname.toLowerCase().replace(/\/+$/, '') || '/'
  return pageByPath[legacyHash] ?? pageByPath[path] ?? 'Home'
}

const currentPage = ref<Page>(pageFromLocation())
const currentComponent = computed(() => ({
  Websites: WebsitesPage, Devices: DevicesPage, Agents: AgentsPage,
  Data: DataPage, Ledger: LedgerPage, Automation: AutomationPage,
})[currentPage.value as Exclude<Page, 'Home'>])
const pageRef = ref<{ openCreate: () => void } | null>(null)
const toast = ref('')
let toastTimer: ReturnType<typeof setTimeout> | undefined

function showToast(message: string) {
  toast.value = message
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 3000)
}
function navigate(page: string) {
  if (!(page in pagePaths)) { showToast('此页面正在准备中。'); return }
  const target = page as Page
  currentPage.value = target
  if (window.location.pathname !== pagePaths[target] || window.location.hash) {
    window.history.pushState({ page: target }, '', pagePaths[target])
  }
  window.scrollTo({ top: 0, behavior: 'instant' })
}
function onLocationChange() {
  currentPage.value = pageFromLocation()
  window.scrollTo({ top: 0, behavior: 'instant' })
}
async function create(kind: string) {
  const destination: Record<string, Page> = {
    website: 'Websites', device: 'Devices', agent: 'Agents',
    collection: 'Data', automation: 'Automation',
    '网站快捷方式': 'Websites', '数据集': 'Data', '自动化': 'Automation',
  }
  if (!destination[kind]) return
  navigate(destination[kind])
  await nextTick()
  pageRef.value?.openCreate?.()
}
onMounted(() => {
  window.addEventListener('popstate', onLocationChange)
  window.addEventListener('hashchange', onLocationChange)
})
onUnmounted(() => {
  window.removeEventListener('popstate', onLocationChange)
  window.removeEventListener('hashchange', onLocationChange)
  if (toastTimer) clearTimeout(toastTimer)
})
</script>

<template>
  <DashboardPage v-if="currentPage === 'Home'" @navigate="navigate" @create="create" />
  <div v-else class="workspace-shell nexa-shell">
    <Sidebar :active-item="currentPage" @select="navigate" />
    <main class="workspace-main">
      <TopSearchBar :current-page="currentPage" @navigate="navigate" @create="create" />
      <div class="workspace-content"><component :is="currentComponent" :key="currentPage" ref="pageRef" @action="showToast" /></div>
    </main>
    <Transition name="workspace-toast"><div v-if="toast" class="workspace-toast" role="status">✦ <span>{{ toast }}</span></div></Transition>
  </div>
</template>

<style scoped>
.workspace-main { min-width:0; }
.workspace-content { min-width:0; padding-bottom:12px; }
.workspace-toast { position:fixed; z-index:80; right:28px; bottom:25px; display:flex; gap:8px; align-items:center; max-width:min(360px,calc(100vw - 32px)); padding:12px 16px; border:1px solid rgba(255,255,255,.64); border-radius:14px; color:#314263; background:rgba(249,251,255,.9); box-shadow:0 15px 32px rgba(30,42,89,.22); backdrop-filter:blur(22px); font-size:12px; font-weight:630; }
.workspace-toast-enter-active,.workspace-toast-leave-active { transition:opacity .2s,transform .2s; }
.workspace-toast-enter-from,.workspace-toast-leave-to { opacity:0; transform:translateY(10px); }
@media (max-width:700px) { .workspace-main { margin-top:7px; } }
</style>
