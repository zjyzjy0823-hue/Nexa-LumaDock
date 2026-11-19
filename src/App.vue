<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { invoke, isTauri } from '@tauri-apps/api/core'
import AuthGate from './components/auth/AuthGate.vue'
import ConfirmDialog from './components/ui/ConfirmDialog.vue'
import DesktopTitleBar from './components/desktop/DesktopTitleBar.vue'
import { desktopPlatform } from './desktop/platform'
import { scrollPageToTop } from './desktop/desktopInteractions'
import OpusShell from './components/layout/OpusShell.vue'
import OpusSegment from './components/ui/OpusSegment.vue'
import OpusIcon from './components/ui/OpusIcon.vue'
import OpusSyncBadge from './components/ui/OpusSyncBadge.vue'
import { libraryItems } from './components/layout/opusNavigation'
import OpusModulePage from './pages/OpusModulePage.vue'
import ChatPage from './pages/ChatPage.vue'
import SpacePage from './pages/SpacePage.vue'
import DashboardPage from './pages/DashboardPage.vue'
import TodayPage from './pages/TodayPage.vue'
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
import { useSpaceStore } from './stores/space'
import { useSchedulerStore } from './stores/scheduler'
import { nextWorkbenchTheme, useWorkbenchTheme, workbenchThemeLabel } from './composables/useWorkbenchTheme'
import type { WorkbenchTheme } from './composables/useWorkbenchTheme'
import { applyThemeToRoot, resolveThemeState } from './theme/registry'

type Page = 'Home' | 'Dashboard' | 'Websites' | 'Devices' | 'Agents' | 'Data' | 'Ledger' | 'Automation' | 'API' | 'Settings' | 'Space' | 'Chat'
const pagePaths: Record<Page, string> = {
  Home: '/', Dashboard: '/dashboard', Websites: '/websites', Devices: '/devices', Agents: '/agents',
  Data: '/data', Ledger: '/ledger', Automation: '/automation', API: '/api', Settings: '/settings', Space: '/space', Chat: '/chat',
}
const pageByPath = Object.fromEntries(Object.entries(pagePaths).map(([key, value]) => [value, key])) as Record<string, Page>
function pageFromLocation(): Page {
  const legacyHash = window.location.hash.slice(1).toLowerCase()
  const path = window.location.pathname.toLowerCase().replace(/\/+$/, '') || '/'
  return pageByPath[legacyHash] ?? pageByPath[path] ?? 'Home'
}

const currentPage = ref<Page>(pageFromLocation())
const android = desktopPlatform() === 'android'
const desktop = isTauri() && !android
const auth = useAuthStore()
const settings = useSettingsStore()
const { theme, rawThemeId, setTheme, bubbleStyle, reducedTransparency } = useWorkbenchTheme()
const systemDark = window.matchMedia('(prefers-color-scheme: dark)')
const prefersDark = ref(systemDark.matches)
const supportsBackdropFilter = typeof CSS !== 'undefined' && typeof CSS.supports === 'function'
  ? (CSS.supports('backdrop-filter', 'blur(1px)') || CSS.supports('-webkit-backdrop-filter', 'blur(1px)'))
  : true
const syncSettings = ref(new URLSearchParams(window.location.search).get('section') === 'sync')
const mobileMedia = window.matchMedia('(max-width: 700px)')
const mobile = ref(android || (mobileMedia.matches && !desktop))
const motionMedia = window.matchMedia('(prefers-reduced-motion: reduce)')
const storedMotion = localStorage.getItem('studiolo:reduced-motion')
const motionReduced = ref(storedMotion === null ? motionMedia.matches : storedMotion === 'true')
const libraryQuery = ref('')
const libraryDetailOpen = ref(false)
const hideMobileTabbar = ref(false)
watch(currentPage, page => {
  if (page !== 'Chat') hideMobileTabbar.value = false
})
const shellRef = ref<InstanceType<typeof OpusShell> | null>(null)
const storedPreviewMode = localStorage.getItem('studiolo:preview-mode')
const previewMode = ref<'light' | 'dark' | null>(
  storedPreviewMode === 'light' || storedPreviewMode === 'dark' ? storedPreviewMode : null
)
const mode = computed(() => {
  if (!auth.token) {
    if (previewMode.value) return previewMode.value
    return prefersDark.value ? 'dark' : 'light'
  }
  const appearance = settings.settings.appearance.theme
  return appearance === 'auto' || !appearance ? (prefersDark.value ? 'dark' : 'light') : appearance
})
const authReady = ref(false)
const authStartupError = ref('')
const desktopError = ref('')
let backendTimer: ReturnType<typeof setInterval> | undefined
let restoringSession = false
const currentComponent = computed(() => ({
  Home: TodayPage, Dashboard: DashboardPage,
  Websites: WebsitesPage, Devices: DevicesPage, Agents: AgentsPage,
  Data: DataPage, Ledger: LedgerPage, Automation: AutomationPage,
  API: ApiPage, Settings: SettingsPage, Space: OpusModulePage, Chat: OpusModulePage,
})[currentPage.value])
const pageRef = ref<{ openCreate?: (value?: string) => void; openCreateRecord?: () => void } | null>(null)
const settingsPageRef = ref<InstanceType<typeof SettingsPage> | null>(null)
const toast = ref('')
const toastKey = ref(0)
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
    useSpaceStore().reset()
    useSchedulerStore().reset()
  }
  if (current !== undefined && auth.token) void settings.load(auth.token).catch(() => {})
})
watch([rawThemeId, mode, motionReduced, reducedTransparency, bubbleStyle, () => settings.settings.appearance], ([requestedId, colorMode, reduced, noGlass, bStyle, appearance]) => {
  const resolved = resolveThemeState({
    requestedThemeId: requestedId,
    appearanceTheme: colorMode,
    primaryTheme: settings.settings.theme,
    systemPrefersDark: prefersDark.value,
    blurPx: appearance.blur ?? 26,
    transparencyPercent: appearance.transparency ?? 72,
    reducedMotion: reduced,
    reducedTransparency: noGlass,
    supportsBackdropFilter,
    bubbleStyle: bStyle,
  })
  applyThemeToRoot(document.documentElement, resolved)
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', resolved.themeColor)
}, { immediate: true })

function setReducedMotion(value: boolean) {
  motionReduced.value = value
  localStorage.setItem('studiolo:reduced-motion', String(value))
}
function updateSystemMotion(event: MediaQueryListEvent) {
  if (localStorage.getItem('studiolo:reduced-motion') === null) motionReduced.value = event.matches
}
function updateSystemTheme(event: MediaQueryListEvent) {
  prefersDark.value = event.matches
}
function updateMobile(event: MediaQueryListEvent) {
  mobile.value = android || (event.matches && !desktop)
  if (!mobile.value) libraryDetailOpen.value = false
}

function showToast(message: string) {
  toast.value = message
  toastKey.value++
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 3000)
}
async function toggleColorMode() {
  const next = mode.value === 'dark' ? 'light' : 'dark'
  if (!auth.token) {
    previewMode.value = next
    localStorage.setItem('studiolo:preview-mode', next)
    showToast(`已预览${next === 'dark' ? '深色' : '浅色'}模式`)
    return
  }
  try {
    await settings.update(auth.token, { theme: next, appearance: { ...settings.settings.appearance, theme: next } })
    previewMode.value = next
    localStorage.setItem('studiolo:preview-mode', next)
    showToast(`已切换为${next === 'dark' ? '深色' : '浅色'}模式`)
  } catch (error) {
    showToast(error instanceof Error ? error.message : '切换失败')
  }
}
function setThemeWithToast(next: WorkbenchTheme) {
  if (next === theme.value) return
  setTheme(next)
  showToast(`已切换为 ${workbenchThemeLabel(next)} 主题`)
}
function toggleWorkbenchTheme() {
  setThemeWithToast(nextWorkbenchTheme(theme.value))
}
function setReducedMotionWithToast(value: boolean) {
  setReducedMotion(value)
  showToast(value ? '已开启减弱动画' : '已开启完整动画')
}
async function navigate(page: string, section?: 'sync', back = false) {
  if (!Object.hasOwn(pagePaths, page)) return
  const target = page as Page
  const toSync = target === 'Settings' && section === 'sync'
  const url = pagePaths[target] + (toSync ? '?section=sync' : '')
  if (currentPage.value === target && syncSettings.value === toSync) return
  const pushed = target === 'Settings' || target === 'Space' || target === 'Agents' || target === 'API' || target === 'Dashboard'
  const update = async () => {
    currentPage.value = target
    syncSettings.value = toSync
    libraryDetailOpen.value = false
    if (!libraryItems.some(item => item.page === target)) libraryQuery.value = ''
    if (window.location.pathname + window.location.search !== url || window.location.hash) {
      window.history.pushState({ page: target }, '', url)
    }
    await nextTick()
    scrollPageToTop()
    document.querySelector('.main')?.scrollTo(0, 0)
    document.querySelector('.mpage')?.scrollTo(0, 0)
  }
  if (document.startViewTransition && !motionReduced.value) {
    const transition = document.startViewTransition({ update, types: mobile.value ? [back ? 'backward' : pushed ? 'forward' : 'tab'] : [] })
    await transition.updateCallbackDone
  } else await update()
}
function onLocationChange() {
  const target = pageFromLocation()
  const toSync = new URLSearchParams(window.location.search).get('section') === 'sync'
  if (target === currentPage.value && toSync === syncSettings.value) return
  const update = async () => {
    currentPage.value = target
    syncSettings.value = toSync
    libraryDetailOpen.value = false
    await nextTick()
    document.querySelector('.main, .mpage')?.scrollTo(0, 0)
  }
  if (mobile.value && document.startViewTransition && !motionReduced.value) {
    document.startViewTransition({ update, types: ['backward'] })
  } else void update()
}
async function openSyncSettings() {
  await navigate('Settings', 'sync')
  settingsPageRef.value?.selectSection('sync')
}
function back() {
  if (window.history.state?.page) window.history.back()
  else void navigate('Home', undefined, true)
}
async function restoreSession() {
  if (restoringSession) return
  restoringSession = true
  authReady.value = false
  authStartupError.value = ''
  try { await auth.bootstrap() }
  catch (error) {
    authStartupError.value = error instanceof ApiError && (error.status === 0 || error.status >= 500)
      ? '无法连接到 Studiolo 后端，请确认服务已启动。'
      : error instanceof Error ? error.message : '无法连接到 Studiolo 后端。'
  } finally { authReady.value = true; restoringSession = false }
}
async function checkDesktopBackend() {
  if (!isTauri()) return
  try {
    const status = await invoke<string>('backend_status')
    desktopError.value = status === 'ready' || status === 'starting' ? '' : status
    if (status === 'ready' && !authReady.value) await restoreSession()
  } catch {
    desktopError.value = '无法读取 Studiolo Backend 状态。请重新启动 Studiolo。'
  }
}
async function create(kind: string, value?: string) {
  const destination: Record<string, Page> = {
    ledger: 'Ledger', website: 'Websites', device: 'Devices', agent: 'Agents',
    collection: 'Data', record: 'Data', automation: 'Automation',
    '网站快捷方式': 'Websites', '数据集': 'Data', '自动化': 'Automation',
  }
  if (!destination[kind]) return
  if (kind === 'record' && auth.token) await useDataStore().load(auth.token).catch(() => {})
  await navigate(destination[kind])
  await nextTick()
  if (kind === 'record') pageRef.value?.openCreateRecord?.()
  else pageRef.value?.openCreate?.(value)
}
onMounted(async () => {
  window.addEventListener('popstate', onLocationChange)
  window.addEventListener('hashchange', onLocationChange)
  systemDark.addEventListener('change', updateSystemTheme)
  mobileMedia.addEventListener('change', updateMobile)
  motionMedia.addEventListener('change', updateSystemMotion)
  if (desktop) {
    await checkDesktopBackend()
    backendTimer = setInterval(checkDesktopBackend, 2000)
  } else {
    await restoreSession()
  }
})
onUnmounted(() => {
  window.removeEventListener('popstate', onLocationChange)
  window.removeEventListener('hashchange', onLocationChange)
  systemDark.removeEventListener('change', updateSystemTheme)
  mobileMedia.removeEventListener('change', updateMobile)
  motionMedia.removeEventListener('change', updateSystemMotion)
  if (toastTimer) clearTimeout(toastTimer)
  if (backendTimer) clearInterval(backendTimer)
})
</script>

<template>
  <ConfirmDialog />
  <div :class="desktop ? 'desktop-app' : undefined">
  <div v-if="(desktopError || !authReady || authStartupError || !auth.user) && desktopPlatform() === 'macos'" class="macos-titlebar-inset" data-tauri-drag-region aria-hidden="true" />
  <div :class="desktop ? 'desktop-body' : undefined">
  <template v-if="desktopError || !authReady || authStartupError || !auth.user">
    <div :class="!mobile && desktopPlatform() !== 'macos' ? 'opus-auth-shell' : undefined">
      <template v-if="!mobile && desktopPlatform() !== 'macos'">
        <div class="glass-wallpaper" aria-hidden="true"></div>
        <DesktopTitleBar :theme="theme" :mode="mode" :reduced-motion="motionReduced" :workstation="auth.workstation" :setup-required="auth.setupRequired"
          @set-theme="setThemeWithToast" @toggle-mode="toggleColorMode"
          @toggle-reduced-motion="setReducedMotionWithToast(!motionReduced)" @action="showToast" />
      </template>
      <div :class="!mobile && desktopPlatform() !== 'macos' ? 'opus-auth-body' : undefined">
        <div v-if="desktopError" class="auth-loading auth-loading--error"><section class="auth-error-panel" role="alert"><p>{{ desktopError }}</p><button type="button" @click="checkDesktopBackend">重试检查</button></section></div>
        <div v-else-if="!authReady" class="auth-loading" role="status">正在打开 Studiolo…</div>
        <div v-else-if="authStartupError" class="auth-loading auth-loading--error"><section class="auth-error-panel" role="alert"><p>{{ authStartupError }}</p><button type="button" @click="restoreSession">重试连接</button><button v-if="android" type="button" @click="auth.clearAndroidCore(); authStartupError = ''">更换 Core 服务器</button></section></div>
        <AuthGate v-else />
      </div>
    </div>
  </template>
  <OpusShell v-else ref="shellRef" :page="currentPage" :mobile="mobile" :hide-mobile-tabbar="hideMobileTabbar" :toast="toast" :toast-key="toastKey" :theme="theme" :mode="mode" :reduced-motion="motionReduced"
    @navigate="navigate" @create="create" @action="showToast" @sync-settings="openSyncSettings" @back="back" @toggle-mode="toggleColorMode" @toggle-theme="toggleWorkbenchTheme" @set-theme="setThemeWithToast" @toggle-reduced-motion="setReducedMotionWithToast(!motionReduced)">
    <template #default="{ syncStatus, syncLabel, syncKind, openSync, openAdd, inLibrary }">
      <TodayPage v-if="currentPage === 'Home'" :mobile="mobile" :sync-status="syncStatus" :sync-label="syncLabel" :sync-kind="syncKind" @navigate="navigate" @action="showToast" @create="create" @add="openAdd" @sync="openSync" @ask-agent="shellRef?.openDock()" />
      <ChatPage v-else-if="currentPage === 'Chat'" :mobile="mobile" @navigate="navigate" @action="showToast" @mobile-fullscreen="hideMobileTabbar = $event" />
      <SpacePage v-else-if="currentPage === 'Space'" :mobile="mobile" @action="showToast" @back="back" />
      <div v-else-if="inLibrary" :class="libraryDetailOpen ? 'opus-subpage-host' : 'mpage'">
        <template v-if="!libraryDetailOpen">
          <div class="mhead"><h1>资料</h1><span class="spacer"></span><button class="mpill" type="button" @click="openSync"><OpusSyncBadge :kind="syncKind" :label="syncLabel" /></button></div>
          <div class="msearch"><OpusIcon name="search" /><input v-model="libraryQuery" placeholder="搜索账本、网站、记录…" aria-label="搜索"></div>
          <button class="vault-entry mat" type="button" @click="navigate('Space')">
            <span class="lk"><OpusIcon name="lock" /></span>
            <span style="flex:1;min-width:0"><div style="font-weight:650;font-size:15px">共享空间</div><div class="faint" style="font-size:12.5px">普通随时看 · 机密按次输密 · 极密 E2EE</div></span><OpusIcon name="chevR" />
          </button>
          <OpusSegment class="mseg" role="group" aria-label="资料类型"><button v-for="item in libraryItems" :key="item.page" type="button" :aria-pressed="currentPage === item.page" @click="navigate(item.page)">{{ item.label }}</button></OpusSegment>
        </template>
        <component :is="currentComponent" :key="currentPage" ref="pageRef" mobile :search="libraryQuery" @action="showToast" @mobile-detail="libraryDetailOpen = $event" />
      </div>
      <SettingsPage v-else-if="currentPage === 'Settings'" ref="settingsPageRef" :sync-status="syncStatus" :sync-label="syncLabel" :mobile="mobile" :reduced-motion="motionReduced" :open-sync="syncSettings" @update:reduced-motion="setReducedMotion" @action="showToast" @navigate="navigate" @back="back" />
      <DataPage v-else-if="currentPage === 'Data'" ref="pageRef" @action="showToast" />
      <div v-else :class="mobile ? 'opus-subpage-host' : 'page'">
        <component :is="currentComponent" :key="currentPage" ref="pageRef" :mobile="mobile" @action="showToast" @navigate="navigate" @back="back" />
      </div>
    </template>
  </OpusShell>
  </div>
  </div>
  <div v-if="toast && !auth.user" class="auth-toast" role="status">{{ toast }}</div>
</template>

<style scoped>
.auth-loading { display:grid; min-height:100dvh; place-items:center; color:var(--text); background:var(--bg); font-size:14px; }
.auth-loading--error { align-content:center; gap:14px; }
.auth-loading--error p { margin:0; }
.auth-error-panel { display:grid; justify-items:center; gap:18px; width:min(520px,calc(100vw - 40px)); padding:28px; border-radius:var(--r-xl); background:var(--solid); color:var(--text); box-shadow:var(--shadow-pop); line-height:1.7; text-align:center; }
.auth-loading--error button { padding:9px 16px; border-radius:var(--r-sm); color:var(--text); background:var(--surface-3); cursor:pointer; }
.auth-toast { position:fixed; right:24px; bottom:24px; color:var(--inv); background:var(--text); padding:9px 14px; border-radius:var(--r-md); box-shadow:var(--shadow-pop); font-size:13px; }
</style>
