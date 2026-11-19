<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import OpusSegment from '../components/ui/OpusSegment.vue'
import OpusIcon from '../components/ui/OpusIcon.vue'
import {
  chatBubbleStyleOptions,
  useWorkbenchTheme,
  workbenchThemeOptions,
  type ChatBubbleStyle,
} from '../composables/useWorkbenchTheme'
import Modal from '../components/ui/Modal.vue'
import AccountSettings from '../components/settings/AccountSettings.vue'
import SyncSettings from '../components/settings/SyncSettings.vue'
import AgentsSettings from '../components/settings/AgentsSettings.vue'
import StorageSettings from '../components/settings/StorageSettings.vue'
import SecuritySettings from '../components/settings/SecuritySettings.vue'
import NotificationSettings from '../components/settings/NotificationSettings.vue'
import AboutSettings from '../components/settings/AboutSettings.vue'
import { isAndroidLocal } from '../desktop/androidLocal'
import { useAuthStore } from '../stores/auth'
import { useSettingsStore, defaultSettings } from '../stores/settings'
import type { SyncStatus } from '../api/sync'
import { settingsService } from '../services/settings'
import { aboutInfo, settingsNavigation } from '../mock/settings'
import type {
  AppearanceConfig, NotificationConfig, SecurityConfig, SettingsSectionId,
  StorageInfo, SyncConfig, UserProfile,
} from '../types/settings'
import '../components/settings/settings.css'

const emit = defineEmits<{ action: [message: string]; navigate: [page: string]; 'update:reducedMotion': [value: boolean]; back: [] }>()

const props = defineProps<{ openSync?: boolean; mobile?: boolean; reducedMotion?: boolean; syncStatus?: SyncStatus | null; syncLabel?: string }>()
const sections = [
  { id: 'appearance', label: '外观' }, { id: 'sync', label: '同步' }, { id: 'agents', label: 'Agent 与连接' }, { id: 'account', label: '账户与设备' },
  { id: 'security', label: '隐私与安全' }, { id: 'storage', label: '存储' }, { id: 'notifications', label: '通知' }, { id: 'about', label: '关于' },
] as const
function sectionFromSearch(): SettingsSectionId | null {
  if (typeof window === 'undefined') return null
  const value = new URLSearchParams(window.location.search).get('section')
  return sections.some(item => item.id === value) ? (value as SettingsSectionId) : null
}
function writeSectionUrl(id: SettingsSectionId | null) {
  if (typeof window === 'undefined' || window.location.pathname.toLowerCase().replace(/\/+$/, '') !== '/settings') return
  const nextUrl = id && (props.mobile || id !== 'appearance') ? `/settings?section=${id}` : '/settings'
  if (window.location.pathname + window.location.search !== nextUrl) {
    window.history.replaceState(window.history.state, '', nextUrl)
  }
}
const activeSection = ref<SettingsSectionId>(props.openSync ? 'sync' : sectionFromSearch() ?? 'appearance')
const mobileDetail = ref<SettingsSectionId | null>(props.openSync ? 'sync' : sectionFromSearch())
watch(() => props.openSync, open => {
  selectSection(open ? 'sync' : 'appearance')
  mobileDetail.value = open ? 'sync' : null
})
const { theme, setTheme, bubbleStyle, setBubbleStyle } = useWorkbenchTheme()
const themes = workbenchThemeOptions
const bubbleStyles = chatBubbleStyleOptions
const modes = [{ id: 'auto', label: '跟随系统' }, { id: 'light', label: '浅色' }, { id: 'dark', label: '深色' }] as const
const searchQuery = ref('')
const showTools = ref(false)
const auth = useAuthStore()
const store = useSettingsStore()
const androidLocal = isAndroidLocal()
const mobileSections = computed(() => sections.filter(section =>
  section.id !== 'appearance' && (store.loaded || section.id === 'sync')))
const profile = computed<UserProfile>(() => ({ username: auth.user?.username ?? '', email: '', timezone: store.settings.deploymentTimezone ?? '未知', language: store.settings.language }))
const appearance = computed<AppearanceConfig>(() => ({ ...defaultSettings.appearance, ...store.settings.appearance } as AppearanceConfig))
function setMode(mode: AppearanceConfig['theme']) {
  return saveSettings({ theme: mode === 'auto' ? 'system' : mode, appearance: { ...appearance.value, theme: mode } })
}
function toggleBlur() {
  return saveSettings({ appearance: { ...appearance.value, blur: appearance.value.blur > 0 ? 0 : 26 } })
}
const security = computed<SecurityConfig>(() => ({ ...defaultSettings.security, ...store.settings.security } as SecurityConfig))
const notifications = computed<NotificationConfig>(() => store.settings.notifications)
const storage = ref<StorageInfo>({ usedGb: 0, totalGb: 0, segments: [] })
const avatarUrl = computed(() => auth.user?.avatar ?? '')
const passwordOpen = ref(false)
const passwordDraft = ref({ current: '', next: '', confirm: '' })
const saving = ref(false)
onMounted(() => { if (auth.token) store.load(auth.token).catch(() => {}) })
async function saveSettings(payload: Parameters<typeof store.update>[1]) {
  if (!auth.token) return
  saving.value = true
  try { await store.update(auth.token, payload); emit('action', '设置已保存。'); return true }
  catch (error) { emit('action', error instanceof Error ? error.message : '保存失败'); return false }
  finally { saving.value = false }
}
async function updateProfile(value: UserProfile) {
  if (!auth.token) return
  try {
    if (value.username !== profile.value.username) auth.user = await settingsService.account(auth.token, { username: value.username })
    return await saveSettings({ language: value.language })
  } catch (error) { emit('action', error instanceof Error ? error.message : '账户保存失败'); return false }
}
async function updateAvatar(url: string) {
  if (!auth.token) return
  try { auth.user = await settingsService.account(auth.token, { avatar: url.trim() || null }); emit('action', '头像已保存。') }
  catch (error) { emit('action', error instanceof Error ? error.message : '头像保存失败') }
}

function runViewTransition(update: () => Promise<void> | void, types: string[]) {
  if (props.mobile && typeof document !== 'undefined' && document.startViewTransition && document.documentElement?.dataset.motion !== 'reduced') {
    document.startViewTransition({ update, types })
  } else {
    void update()
  }
}

function selectSection(id: SettingsSectionId) {
  activeSection.value = id
  if (props.mobile) mobileDetail.value = id
  writeSectionUrl(props.mobile ? id : (id === 'appearance' ? null : id))
  searchQuery.value = ''
}
function openMobileSection(id: SettingsSectionId) {
  runViewTransition(async () => {
    activeSection.value = id
    mobileDetail.value = id
    writeSectionUrl(id)
    await nextTick()
  }, ['forward'])
}
function mobileBack() {
  if (mobileDetail.value) {
    runViewTransition(async () => {
      mobileDetail.value = null
      activeSection.value = 'appearance'
      writeSectionUrl(null)
      await nextTick()
    }, ['backward'])
  } else {
    emit('back')
  }
}
defineExpose({ selectSection })
function selectFirstSearchResult() {
  const match = settingsNavigation.find(item => item.label.includes(searchQuery.value.trim()))
  if (match) selectSection(match.id)
}
function resetSettings() {
  const { timezone: _timezone, deploymentTimezone: _deploymentTimezone, ...editable } = structuredClone(defaultSettings)
  saveSettings(editable)
}
async function updatePassword() {
  if (!passwordDraft.value.current || passwordDraft.value.next.length < 8 || passwordDraft.value.next !== passwordDraft.value.confirm) {
    emit('action', '请输入原密码，并确认至少 8 位的新密码。')
    return
  }
  if (!auth.token) return
  try {
    await settingsService.password(auth.token, passwordDraft.value.current, passwordDraft.value.next)
    passwordOpen.value = false
    passwordDraft.value = { current: '', next: '', confirm: '' }
    emit('action', '密码已修改。')
  } catch (error) { emit('action', error instanceof Error ? error.message : '密码修改失败') }
}
function clearCache() { emit('action', '没有可清理的缓存。') }
function snapshot() {
  return {
    product: 'Studiolo', version: aboutInfo.version, exportedAt: new Date().toISOString(),
    profile: profile.value, appearance: appearance.value, sync: store.settings.sync,
    security: security.value, notifications: notifications.value,
  }
}
function downloadSnapshot(filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot(), null, 2)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function exportData() { downloadSnapshot('studiolo-settings.json'); emit('action', '设置数据已导出到本地。') }
function backupData() { downloadSnapshot(`studiolo-backup-${new Date().toISOString().slice(0, 10)}.json`); emit('action', '本地备份已创建。') }
async function importData(file: File) {
  try {
    const data = JSON.parse(await file.text()) as Record<string, unknown>
    if ((data.product !== 'Studiolo' && data.product !== 'Nexa') || !data.profile || !data.appearance || !data.sync || !data.security || !data.notifications) throw new Error('Invalid settings file')
    if (!await updateProfile(data.profile as UserProfile)) throw new Error('Profile import failed')
    if (!await saveSettings({ appearance: data.appearance as AppearanceConfig, sync: data.sync as SyncConfig,
      security: data.security as SecurityConfig, notifications: data.notifications as NotificationConfig })) throw new Error('Settings import failed')
    emit('action', '设置已导入并保存。')
  } catch {
    emit('action', '无法读取设置文件，请使用 Studiolo 导出的 JSON 文件。')
  }
}
const mobileDetailLabel = computed(() => sections.find(item => item.id === mobileDetail.value)?.label ?? '设置')
</script>

<template>
  <div class="settings-page" :class="mobile ? 'mpage push' : 'page'">
    <div v-if="mobile" class="navbar">
      <button class="icon-btn" type="button" aria-label="返回" @click="mobileBack"><OpusIcon name="chevL" /></button>
      <div class="t">{{ mobileDetail ? mobileDetailLabel : '设置' }}</div>
      <span style="width:40px"></span>
    </div>
    <header v-else class="ph"><div><h1>设置</h1></div><div class="actions"><button class="icon-btn" type="button" aria-label="设置选项" :aria-expanded="showTools" @click="showTools = !showTools"><OpusIcon name="more" /></button></div></header>

    <div v-if="showTools && !mobile" class="toolbar card mat enter" style="margin-bottom:14px;border-radius:var(--r-lg)">
      <div class="search"><OpusIcon name="search" /><input v-model="searchQuery" class="input" type="search" placeholder="搜索设置" aria-label="搜索设置" @keydown.enter="selectFirstSearchResult"></div>
      <span class="spacer"></span>
      <button class="btn btn-sm btn-ghost" type="button" @click="resetSettings">恢复默认</button>
    </div>
    <p v-if="store.loading && !store.loaded" class="faint" role="status">正在加载设置…</p>
    <p v-if="store.error" class="notice danger" role="alert">{{ store.error }} <button class="btn btn-sm btn-ghost" type="button" @click="auth.token && store.load(auth.token, true).catch(() => {})">重试</button></p>

    <template v-if="mobile && (store.loaded || androidLocal)">
      <template v-if="!mobileDetail || (!store.loaded && mobileDetail !== 'sync')">
        <template v-if="store.loaded">
        <div class="sec-t" style="margin-top:4px">主题</div>
        <OpusSegment class="mseg" role="group" aria-label="主题"><button v-for="item in themes" :key="item.id" type="button" :aria-pressed="theme === item.id" @click="setTheme(item.id)">{{ item.shortTitle }}</button></OpusSegment>
        <div class="sec-t">对话气泡样式</div>
        <div class="m-bubble-style-list mat-solid">
          <button
            v-for="bs in bubbleStyles"
            :key="bs.id"
            type="button"
            class="m-bubble-opt"
            :aria-pressed="bubbleStyle === bs.id"
            @click="setBubbleStyle(bs.id)"
          >
            <div class="m-bopt-main">
              <div class="m-bopt-top">
                <span class="m-bopt-title">{{ bs.title }}</span>
                <span class="m-bopt-badge">{{ bs.badge }}</span>
              </div>
              <div class="m-bopt-desc">{{ bs.description }}</div>
            </div>
            <OpusIcon v-if="bubbleStyle === bs.id" name="check" class="m-bopt-check" />
          </button>
        </div>
        <div class="kvl mat-solid">
          <div><span>外观模式</span><select class="input" style="width:auto;border:0;background:transparent;text-align:right" aria-label="外观模式" :value="appearance.theme" @change="setMode(($event.target as HTMLSelectElement).value as AppearanceConfig['theme'])"><option v-for="item in modes" :key="item.id" :value="item.id">{{ item.label }}</option></select></div>
          <div><span>减少透明度（关闭模糊）</span><button class="switch" type="button" role="switch" aria-label="减少透明度" :aria-checked="appearance.blur === 0" @click="toggleBlur"></button></div>
          <div><span>减少动态效果</span><button class="switch" type="button" role="switch" aria-label="减少动态效果" :aria-checked="!!reducedMotion" @click="emit('update:reducedMotion', !reducedMotion)"></button></div>
        </div>
        <p class="faint" style="font-size:12.5px;margin:0 4px 12px">低端设备可关闭模糊；玻璃材质只用于导航、卡片和弹层，列表与输入保持实体。</p>
        </template>
        <div v-if="store.loaded" class="sec-t">同步</div>
        <div class="kvl mat-solid">
          <div><span>Core</span><button type="button" class="conn" :class="syncStatus?.connected ? 'online' : 'offline'" @click="openMobileSection('sync')">{{ syncLabel }}</button></div>
          <div><span>待同步</span><span>{{ (syncStatus?.pending ?? 0) + (syncStatus?.inFlight ?? 0) }} 项</span></div>
          <div v-if="syncStatus?.conflicts"><span>冲突</span><button type="button" class="btn btn-sm btn-danger" @click="openMobileSection('sync')">{{ syncStatus.conflicts }} 个待处理</button></div>
        </div>
        <div v-if="store.loaded" class="sec-t">更多设置</div>
        <nav class="mlist mat-solid" aria-label="设置类别">
          <button v-for="item in mobileSections" :key="item.id" class="mrow" type="button" @click="openMobileSection(item.id)"><span class="grow"><span class="title">{{ item.label }}</span></span><span v-if="item.id === 'sync' && syncStatus?.conflicts" class="chip" style="color:var(--danger);background:var(--danger-soft)">{{ syncStatus.conflicts }} 冲突</span><OpusIcon name="chevR" /></button>
          <button v-if="store.loaded" class="mrow" type="button" @click="resetSettings"><span class="grow"><span class="title">恢复默认设置</span></span></button>
        </nav>
      </template>
      <div v-else class="settings-content" :inert="saving">
        <AccountSettings v-if="mobileDetail === 'account'" :profile="profile" :avatar-url="avatarUrl" :workstation="auth.workstation" @update:profile="updateProfile" @avatar="updateAvatar" @password="passwordOpen = true" />
        <SyncSettings v-else-if="mobileDetail === 'sync'" @action="emit('action', $event)" />
        <AgentsSettings v-else-if="mobileDetail === 'agents'" @navigate="emit('navigate', $event)" />
        <StorageSettings v-else-if="mobileDetail === 'storage'" :info="storage" @clear="clearCache" @export="exportData" @import="importData" @backup="backupData" />
        <SecuritySettings v-else-if="mobileDetail === 'security'" :config="security" @update:config="saveSettings({ security: $event })" @password="passwordOpen = true" @action="emit('action', $event)" @navigate="emit('navigate', $event)" />
        <NotificationSettings v-else-if="mobileDetail === 'notifications'" :config="notifications" @update:config="saveSettings({ notifications: $event })" />
        <AboutSettings v-else :info="aboutInfo" @action="emit('action', $event)" />
        <div v-if="mobileDetail === 'account'" class="mbtns" style="margin-top:12px">
          <button class="btn btn-ghost" type="button" @click="emit('navigate', 'Devices')">设备管理</button>
          <button v-if="!auth.workstation" class="btn btn-danger" type="button" @click="auth.logout()"><OpusIcon name="logout" />退出登录</button>
        </div>
      </div>
    </template>

    <div v-else-if="store.loaded" class="settings">
      <nav class="set-nav" aria-label="设置类别"><button v-for="item in sections" :key="item.id" class="nav-item" type="button" :aria-current="activeSection === item.id ? 'page' : undefined" @click="selectSection(item.id)"><span>{{ item.label }}</span><span v-if="item.id === 'sync' && syncStatus?.conflicts" class="count alert">{{ syncStatus.conflicts }}</span></button></nav>
      <div class="settings-content" :inert="saving">
        <template v-if="activeSection === 'appearance'">
          <section class="set-sec"><h2>主题</h2><div class="theme-cards">
            <button v-for="item in themes" :key="item.id" class="theme-card" type="button" :aria-pressed="theme === item.id" @click="setTheme(item.id)"><div class="pv" :class="item.id"><i style="left:8px;top:8px;bottom:8px;width:40px"></i><i style="left:56px;top:8px;right:8px;height:40px"></i><i style="left:56px;top:56px;right:8px;bottom:8px"></i></div><div class="nm">{{ item.title }}</div><div class="ds">{{ item.description }}</div></button>
          </div></section>
          <section class="set-sec"><h2>对话气泡样式</h2><div class="bubble-style-cards">
            <button
              v-for="bs in bubbleStyles"
              :key="bs.id"
              class="theme-card bubble-style-card"
              type="button"
              :aria-pressed="bubbleStyle === bs.id"
              @click="setBubbleStyle(bs.id as ChatBubbleStyle)"
            >
              <div class="bpv" :class="`bpv--${bs.id}`">
                <span class="bpv-user" />
                <span class="bpv-agent">
                  <i class="bpv-tool" />
                  <i class="bpv-line1" />
                  <i class="bpv-line2" />
                </span>
              </div>
              <div class="nm">
                <span>{{ bs.title }}</span>
                <span class="bs-badge">{{ bs.badge }}</span>
              </div>
              <div class="ds">{{ bs.description }}</div>
            </button>
          </div></section>
          <section class="set-sec"><h2>显示</h2><div class="mat-solid" style="border-radius:var(--r-lg)">
            <div class="set-row"><div class="grow"><div class="t">外观模式</div><div class="d">跟随系统或手动选择</div></div><OpusSegment><button v-for="item in modes" :key="item.id" type="button" :aria-pressed="appearance.theme === item.id" @click="setMode(item.id)">{{ item.label }}</button></OpusSegment></div>
            <div class="set-row"><div class="grow"><div class="t">减少透明度</div><div class="d">关闭模糊，玻璃材质改为不透明表面；低性能设备可开启</div></div><button class="switch" type="button" role="switch" aria-label="减少透明度" :aria-checked="appearance.blur === 0" @click="toggleBlur"></button></div>
            <div class="set-row"><div class="grow"><div class="t">减少动态效果</div><div class="d">去掉位移与缩放，只保留淡入淡出与颜色变化</div></div><button class="switch" type="button" role="switch" aria-label="减少动态效果" :aria-checked="!!reducedMotion" @click="emit('update:reducedMotion', !reducedMotion)"></button></div>
          </div></section>
          <section class="set-sec"><h2>同步</h2><div class="mat-solid" style="border-radius:var(--r-lg)">
            <div class="set-row"><div class="grow"><div class="t">Core 服务器</div><div class="d">{{ syncLabel }}</div></div><button type="button" class="btn btn-ghost btn-sm" @click="selectSection('sync')">同步设置</button></div>
            <div class="set-row"><div class="grow"><div class="t">冲突中心</div><div class="d">{{ syncStatus?.conflicts ?? 0 }} 个冲突待处理</div></div><button type="button" class="btn btn-ghost btn-sm" @click="selectSection('sync')">查看</button></div>
          </div></section>
        </template>
        <AccountSettings v-else-if="activeSection === 'account'" :profile="profile" :avatar-url="avatarUrl" :workstation="auth.workstation" @update:profile="updateProfile" @avatar="updateAvatar" @password="passwordOpen = true" />
        <SyncSettings v-else-if="activeSection === 'sync'" @action="emit('action', $event)" />
        <AgentsSettings v-else-if="activeSection === 'agents'" @navigate="emit('navigate', $event)" />
        <StorageSettings v-else-if="activeSection === 'storage'" :info="storage" @clear="clearCache" @export="exportData" @import="importData" @backup="backupData" />
        <SecuritySettings v-else-if="activeSection === 'security'" :config="security" @update:config="saveSettings({ security: $event })" @password="passwordOpen = true" @action="emit('action', $event)" @navigate="emit('navigate', $event)" />
        <NotificationSettings v-else-if="activeSection === 'notifications'" :config="notifications" @update:config="saveSettings({ notifications: $event })" />
        <AboutSettings v-else :info="aboutInfo" @action="emit('action', $event)" />
        <div v-if="activeSection === 'account'" class="btn-row"><button class="btn btn-ghost" type="button" @click="emit('navigate', 'Devices')">设备</button><button v-if="!auth.workstation" class="btn btn-danger" type="button" @click="auth.logout()"><OpusIcon name="logout" />退出登录</button></div>
      </div>
    </div>

    <Modal :open="passwordOpen" title="修改密码" description="输入当前密码并设置新密码。" @close="passwordOpen = false">
      <form id="settings-password-form" @submit.prevent="updatePassword">
        <div class="field"><label for="pw-cur">当前密码</label><input id="pw-cur" v-model="passwordDraft.current" class="input" type="password" autocomplete="current-password" aria-label="当前密码" required data-initial-focus /></div>
        <div class="field"><label for="pw-next">新密码</label><input id="pw-next" v-model="passwordDraft.next" class="input" type="password" autocomplete="new-password" aria-label="新密码" required :maxlength="72" /></div>
        <div class="field"><label for="pw-confirm">确认新密码</label><input id="pw-confirm" v-model="passwordDraft.confirm" class="input" type="password" autocomplete="new-password" aria-label="确认新密码" required :maxlength="72" /></div>
      </form>
      <template #footer><button class="btn btn-ghost" type="button" @click="passwordOpen = false">取消</button><button class="btn btn-primary" type="submit" form="settings-password-form">确认修改</button></template>
    </Modal>
  </div>
</template>

<style scoped>
.settings-content { min-width: 0; }
.bubble-style-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(188px, 1fr));
  gap: 10px;
}
.bubble-style-card .nm {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.bs-badge {
  font-size: 10.5px;
  font-weight: 550;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--surface-3);
  color: var(--text-3);
}
.bpv {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  height: 76px;
  padding: 8px 10px;
  margin-bottom: 8px;
  border-radius: 10px;
  background: var(--bg);
  border: 1px solid var(--line);
  overflow: hidden;
}
.bpv-user {
  align-self: flex-end;
  width: 58%;
  height: 15px;
  border-radius: 9px 9px 3px 9px;
  background: var(--surface-3);
}
.bpv-agent {
  display: grid;
  gap: 4px;
  width: 88%;
  padding: 5px 7px;
  border-radius: 8px;
}
.bpv-tool {
  display: block;
  width: 48%;
  height: 5px;
  border-radius: 3px;
  background: var(--surface-3);
}
.bpv-line1,
.bpv-line2 {
  display: block;
  height: 5px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--text-3) 35%, transparent);
}
.bpv-line1 { width: 92%; }
.bpv-line2 { width: 66%; }
.bpv--minimal .bpv-agent { padding-left: 2px; background: transparent; }
.bpv--claude .bpv-user { border: 1px solid var(--line-strong); border-radius: 9px; }
.bpv--claude .bpv-agent { padding-left: 7px; border-left: 2px solid var(--line-strong); border-radius: 0; }
.bpv--lobe .bpv-user { background: var(--text); border-radius: 7px; }
.bpv--lobe .bpv-agent { background: var(--surface-2); border-radius: 7px; }
.bpv--antd .bpv-user { background: var(--accent-soft); border: 1px solid var(--accent-line); border-radius: 6px; }
.bpv--antd .bpv-agent { background: var(--solid); border: 1px solid var(--line-strong); border-radius: 6px; }
.bpv--timeline .bpv-user { width: 100%; border-radius: 5px; border-left: 2.5px solid var(--accent); }
.bpv--timeline .bpv-agent { border-left: 2px solid var(--line-strong); border-radius: 0; padding-left: 8px; }

.m-bubble-style-list {
  border-radius: 20px;
  overflow: hidden;
  margin-bottom: 12px;
}
.m-bubble-opt {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 11px 14px;
  border: 0;
  background: transparent;
  color: var(--text);
  text-align: left;
  cursor: pointer;
}
.m-bubble-opt + .m-bubble-opt {
  border-top: 1px solid var(--line);
}
.m-bubble-opt:active {
  background: var(--surface-3);
}
.m-bopt-main {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 3px;
}
.m-bopt-top {
  display: flex;
  align-items: center;
  gap: 7px;
}
.m-bopt-title {
  font-size: 14.5px;
  font-weight: 600;
}
.m-bopt-badge {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--surface-3);
  color: var(--text-3);
}
.m-bopt-desc {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.4;
}
.m-bopt-check {
  width: 16px;
  height: 16px;
  color: var(--accent);
  flex: none;
}
</style>
