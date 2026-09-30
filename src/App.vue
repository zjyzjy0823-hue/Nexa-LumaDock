<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { invoke, isTauri } from '@tauri-apps/api/core'
import AuthGate from './components/auth/AuthGate.vue'
import ConfirmDialog from './components/ui/ConfirmDialog.vue'
import Sidebar from './components/layout/Sidebar.vue'
import TopSearchBar from './components/layout/TopSearchBar.vue'
import DashboardPage from './pages/DashboardPage.vue'
import WebsitesPage from './pages/WebsitesPage.vue'
import DevicesPage from './pages/DevicesPage.vue'
import AgentsPage from './pages/AgentsPage.vue'
import DataPage from './pages/DataPage.vue'
import LedgerPage from './pages/LedgerPage.vue'
import AutomationPage from './pages/AutomationPage.vue'
import ApiPage from './pages/ApiPage.vue'
import SettingsPage from './pages/SettingsPage.vue'
import { ApiError } from './api/client'
import { useAuthStore } from './stores/auth'
import { useDashboardStore } from './stores/dashboard'
import { useWebsitesStore } from './stores/websites'
import { useDevicesStore } from './stores/devices'
import { useAgentsStore } from './stores/agents'
import { useSettingsStore } from './stores/settings'
import { useDataStore } from './stores/data'
import { useAutomationStore } from './stores/automation'
import { useLedgerStore } from './stores/ledger'

type Page = 'Home' | 'Websites' | 'Devices' | 'Agents' | 'Data' | 'Ledger' | 'Automation' | 'API' | 'Settings'
const pagePaths: Record<Page, string> = {
  Home: '/', Websites: '/websites', Devices: '/devices', Agents: '/agents',
  Data: '/data', Ledger: '/ledger', Automation: '/automation', API: '/api', Settings: '/settings',
}
const pageByPath = Object.fromEntries(Object.entries(pagePaths).map(([key, value]) => [value, key])) as Record<string, Page>
function pageFromLocation(): Page {
  const legacyHash = window.location.hash.slice(1).toLowerCase()
  const path = window.location.pathname.toLowerCase().replace(/\/+$/, '') || '/'
  return pageByPath[legacyHash] ?? pageByPath[path] ?? 'Home'
}

const currentPage = ref<Page>(pageFromLocation())
const auth = useAuthStore()
const authReady = ref(false)
const authStartupError = ref('')
const desktopError = ref('')
let backendTimer: ReturnType<typeof setInterval> | undefined
let restoringSession = false
const currentComponent = computed(() => ({
  Websites: WebsitesPage, Devices: DevicesPage, Agents: AgentsPage,
  Data: DataPage, Ledger: LedgerPage, Automation: AutomationPage,
  API: ApiPage, Settings: SettingsPage,
})[currentPage.value as Exclude<Page, 'Home'>])
const pageRef = ref<{ openCreate: () => void } | null>(null)
const toast = ref('')
let toastTimer: ReturnType<typeof setTimeout> | undefined
watch(() => auth.user?.id, (current, previous) => {
  if (previous !== undefined && current !== previous) {
    useDashboardStore().reset()
    useWebsitesStore().reset()
    useDevicesStore().reset()
    useAgentsStore().reset()
    useSettingsStore().reset()
    useDataStore().reset()
    useAutomationStore().reset()
    useLedgerStore().reset()
  }
})

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
async function restoreSession() {
  if (restoringSession) return
  restoringSession = true
  authReady.value = false
  authStartupError.value = ''
  try { if (auth.token) await auth.restore() }
  catch (error) {
    if (auth.token) authStartupError.value = error instanceof ApiError && (error.status === 0 || error.status >= 500)
      ? '无法连接到 Nexa 后端，请确认服务已启动。'
      : error instanceof Error ? error.message : '无法连接到 Nexa 后端。'
  } finally { authReady.value = true; restoringSession = false }
}
async function checkDesktopBackend() {
  if (!isTauri()) return
  try {
    const status = await invoke<string>('backend_status')
    desktopError.value = status === 'ready' || status === 'starting' ? '' : status
    if (status === 'ready' && !authReady.value) await restoreSession()
  } catch {
    desktopError.value = '无法读取 Nexa Backend 状态。请重新启动 Nexa。'
  }
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
onMounted(async () => {
  window.addEventListener('popstate', onLocationChange)
  window.addEventListener('hashchange', onLocationChange)
  if (isTauri()) {
    await checkDesktopBackend()
    backendTimer = setInterval(checkDesktopBackend, 2000)
  } else {
    await restoreSession()
  }
})
onUnmounted(() => {
  window.removeEventListener('popstate', onLocationChange)
  window.removeEventListener('hashchange', onLocationChange)
  if (toastTimer) clearTimeout(toastTimer)
  if (backendTimer) clearInterval(backendTimer)
})
</script>

<template>
  <ConfirmDialog />
  <div v-if="desktopError" class="auth-loading auth-loading--error"><section class="auth-error-panel" role="alert"><p>{{ desktopError }}</p><button type="button" @click="checkDesktopBackend">重试检查</button></section></div>
  <div v-else-if="!authReady" class="auth-loading" role="status">正在打开 Nexa…</div>
  <div v-else-if="authStartupError" class="auth-loading auth-loading--error"><section class="auth-error-panel" role="alert"><p>{{ authStartupError }}</p><button type="button" @click="restoreSession">重试连接</button></section></div>
  <AuthGate v-else-if="!auth.user" />
  <DashboardPage v-else-if="currentPage === 'Home'" @navigate="navigate" @create="create" />
  <div v-else class="workspace-shell nexa-shell">
    <Sidebar :active-item="currentPage" @select="navigate" />
    <main class="workspace-main">
      <TopSearchBar v-if="currentPage !== 'API' && currentPage !== 'Settings'" :current-page="currentPage" @navigate="navigate" @create="create" />
      <div class="workspace-content"><component :is="currentComponent" :key="currentPage" ref="pageRef" @action="showToast" @navigate="navigate" /></div>
    </main>
  </div>
  <Transition name="workspace-toast"><div v-if="toast" class="workspace-toast" role="status">✦ <span>{{ toast }}</span></div></Transition>
</template>

<style scoped>
.auth-loading { display:grid; min-height:100dvh; place-items:center; color:white; background:#1c2a5e url('/nexa-wallpaper.png') center/cover; font-size:14px; }
.auth-loading--error { align-content:center; gap:14px; }
.auth-loading--error p { margin:0; }
.auth-error-panel { display:grid; justify-items:center; gap:18px; width:min(520px,calc(100vw - 40px)); padding:28px; border:var(--glass-card-border); border-radius:var(--radius-xl); background:var(--glass-dialog-background); color:var(--text-primary); box-shadow:var(--shadow-glass); backdrop-filter:var(--glass-overlay-filter); -webkit-backdrop-filter:var(--glass-overlay-filter); line-height:1.7; text-align:center; }
.auth-loading--error button { padding:9px 16px; border:var(--glass-tile-border); border-radius:9px; color:#30436c; background:var(--glass-tile-background); cursor:pointer; }
.workspace-main { min-width:0; }
.workspace-content { min-width:0; padding-bottom:12px; }
.workspace-toast { position:fixed; z-index:80; right:28px; bottom:25px; display:flex; gap:8px; align-items:center; max-width:min(360px,calc(100vw - 32px)); padding:12px 16px; border:1px solid rgba(255,255,255,.64); border-radius:14px; color:#314263; background:rgba(249,251,255,.9); box-shadow:0 15px 32px rgba(30,42,89,.22); backdrop-filter:blur(22px); font-size:12px; font-weight:630; }
.workspace-toast-enter-active,.workspace-toast-leave-active { transition:opacity .2s,transform .2s; }
.workspace-toast-enter-from,.workspace-toast-leave-to { opacity:0; transform:translateY(10px); }
@media (max-width:700px) { .workspace-main { margin-top:7px; } }
</style>
