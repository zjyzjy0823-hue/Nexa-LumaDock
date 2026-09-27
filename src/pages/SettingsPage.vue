<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { RotateCcw } from 'lucide-vue-next'
import ActionButton from '../components/ui/ActionButton.vue'
import Input from '../components/ui/Input.vue'
import Modal from '../components/ui/Modal.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import TopActionControls from '../components/layout/TopActionControls.vue'
import AccountSettings from '../components/settings/AccountSettings.vue'
import AppearanceSettings from '../components/settings/AppearanceSettings.vue'
import SyncSettings from '../components/settings/SyncSettings.vue'
import StorageSettings from '../components/settings/StorageSettings.vue'
import SecuritySettings from '../components/settings/SecuritySettings.vue'
import NotificationSettings from '../components/settings/NotificationSettings.vue'
import AboutSettings from '../components/settings/AboutSettings.vue'
import SettingsNav from '../components/settings/SettingsNav.vue'
import {
  aboutInfo, appearanceInitial, notificationInitial, profileInitial, securityInitial,
  settingsNavigation, storageInitial, syncInitial,
} from '../mock/settings'
import type {
  AppearanceConfig, NotificationConfig, SecurityConfig, SettingsSectionId,
  StorageInfo, SyncConfig, UserProfile,
} from '../types/settings'
import '../components/settings/settings.css'

const emit = defineEmits<{ action: [message: string]; navigate: [page: string] }>()

const activeSection = ref<SettingsSectionId>('account')
const searchQuery = ref('')
const profile = ref<UserProfile>({ ...profileInitial })
const appearance = ref<AppearanceConfig>({ ...appearanceInitial })
const syncConfig = ref<SyncConfig>({ ...syncInitial })
const storage = ref<StorageInfo>({ ...storageInitial, segments: storageInitial.segments.map(item => ({ ...item })) })
const security = ref<SecurityConfig>({ ...securityInitial })
const notifications = ref<NotificationConfig>({ events: { ...notificationInitial.events }, channels: { ...notificationInitial.channels } })
const avatarUrl = ref('')
const passwordOpen = ref(false)
const syncing = ref(false)
const passwordDraft = ref({ current: '', next: '', confirm: '' })
let syncTimer: ReturnType<typeof setTimeout> | undefined

function selectSection(id: SettingsSectionId) {
  activeSection.value = id
  searchQuery.value = ''
}
function selectFirstSearchResult() {
  const match = settingsNavigation.find(item => item.label.includes(searchQuery.value.trim()))
  if (match) selectSection(match.id)
}
function resetSettings() {
  profile.value = { ...profileInitial }
  appearance.value = { ...appearanceInitial }
  syncConfig.value = { ...syncInitial }
  storage.value = { ...storageInitial, segments: storageInitial.segments.map(item => ({ ...item })) }
  security.value = { ...securityInitial }
  notifications.value = { events: { ...notificationInitial.events }, channels: { ...notificationInitial.channels } }
  if (avatarUrl.value) URL.revokeObjectURL(avatarUrl.value)
  avatarUrl.value = ''
  emit('action', '设置已恢复为演示默认值。')
}
function updateAvatar(file: File) {
  if (avatarUrl.value) URL.revokeObjectURL(avatarUrl.value)
  avatarUrl.value = URL.createObjectURL(file)
  emit('action', '头像预览已更新。')
}
function updatePassword() {
  if (!passwordDraft.value.current || passwordDraft.value.next.length < 8 || passwordDraft.value.next !== passwordDraft.value.confirm) {
    emit('action', '请输入原密码，并确认至少 8 位的新密码。')
    return
  }
  passwordOpen.value = false
  passwordDraft.value = { current: '', next: '', confirm: '' }
  emit('action', '密码修改演示已完成，尚未连接账户服务。')
}
function syncNow() {
  if (syncing.value) return
  syncing.value = true
  syncTimer = setTimeout(() => {
    syncConfig.value = { ...syncConfig.value, lastSynced: '刚刚' }
    syncing.value = false
    emit('action', '演示数据已同步。')
  }, 600)
}
function clearCache() {
  const cache = storage.value.segments.find(item => item.id === 'cache')
  if (!cache?.bytes) { emit('action', '缓存已经清理。'); return }
  storage.value = {
    ...storage.value,
    usedGb: Math.max(0, Number((storage.value.usedGb - cache.bytes).toFixed(1))),
    segments: storage.value.segments.map(item => item.id === 'cache' ? { ...item, bytes: 0, display: '0 MB' } : item),
  }
  emit('action', '本地演示缓存已清理。')
}
function snapshot() {
  return {
    product: 'Nexa', version: aboutInfo.version, exportedAt: new Date().toISOString(),
    profile: profile.value, appearance: appearance.value, sync: syncConfig.value,
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
function exportData() { downloadSnapshot('nexa-settings.json'); emit('action', '设置数据已导出到本地。') }
function backupData() { downloadSnapshot(`nexa-backup-${new Date().toISOString().slice(0, 10)}.json`); emit('action', '本地备份已创建。') }
async function importData(file: File) {
  try {
    const data = JSON.parse(await file.text()) as Record<string, unknown>
    if (data.product !== 'Nexa' || !data.profile || !data.appearance || !data.sync || !data.security || !data.notifications) throw new Error('Invalid settings file')
    profile.value = { ...profileInitial, ...(data.profile as UserProfile) }
    appearance.value = { ...appearanceInitial, ...(data.appearance as AppearanceConfig) }
    syncConfig.value = { ...syncInitial, ...(data.sync as SyncConfig) }
    security.value = { ...securityInitial, ...(data.security as SecurityConfig) }
    const incoming = data.notifications as NotificationConfig
    notifications.value = { events: { ...notificationInitial.events, ...incoming.events }, channels: { ...notificationInitial.channels, ...incoming.channels } }
    emit('action', '设置数据已导入到当前会话。')
  } catch {
    emit('action', '无法读取设置文件，请使用 Nexa 导出的 JSON 文件。')
  }
}

onUnmounted(() => {
  if (syncTimer) clearTimeout(syncTimer)
  if (avatarUrl.value) URL.revokeObjectURL(avatarUrl.value)
})
</script>

<template>
  <div class="settings-page">
    <PageHeader title="设置" eyebrow="">
      <template #actions>
        <div class="settings-header-tools">
          <div class="settings-search"><Input v-model="searchQuery" type="search" aria-label="搜索设置" placeholder="搜索设置..." @keydown.enter="selectFirstSearchResult" /></div>
          <TopActionControls :create-items="[]" :show-create="false" />
          <ActionButton variant="secondary" size="sm" class="settings-reset" aria-label="恢复默认" @click="resetSettings"><RotateCcw :size="14" /><span>恢复默认</span></ActionButton>
        </div>
      </template>
    </PageHeader>

    <div class="settings-layout">
      <SettingsNav :active="activeSection" :query="searchQuery" @select="selectSection" />
      <div class="settings-content" :key="activeSection">
        <AccountSettings v-if="activeSection === 'account'" :profile="profile" :avatar-url="avatarUrl" @update:profile="profile = $event" @avatar="updateAvatar" @password="passwordOpen = true" @logout="emit('action', '演示账户尚未连接登录服务。')" />
        <AppearanceSettings v-else-if="activeSection === 'appearance'" :config="appearance" @update:config="appearance = $event" />
        <SyncSettings v-else-if="activeSection === 'sync'" :config="syncConfig" :syncing="syncing" @update:config="syncConfig = $event" @sync="syncNow" />
        <StorageSettings v-else-if="activeSection === 'storage'" :info="storage" @clear="clearCache" @export="exportData" @import="importData" @backup="backupData" />
        <SecuritySettings v-else-if="activeSection === 'security'" :config="security" @update:config="security = $event" @password="passwordOpen = true" @action="emit('action', $event)" @navigate="emit('navigate', $event)" />
        <NotificationSettings v-else-if="activeSection === 'notifications'" :config="notifications" @update:config="notifications = $event" />
        <AboutSettings v-else :info="aboutInfo" @action="emit('action', $event)" />
      </div>
    </div>

    <Modal :open="passwordOpen" title="修改密码" description="输入当前密码并设置新密码。演示模式不会修改真实账户。" @close="passwordOpen = false">
      <form id="settings-password-form" class="settings-password-form" @submit.prevent="updatePassword">
        <label class="settings-field"><span>当前密码</span><Input v-model="passwordDraft.current" type="password" autocomplete="current-password" aria-label="当前密码" required /></label>
        <label class="settings-field"><span>新密码</span><Input v-model="passwordDraft.next" type="password" autocomplete="new-password" aria-label="新密码" required :maxlength="72" /></label>
        <label class="settings-field"><span>确认新密码</span><Input v-model="passwordDraft.confirm" type="password" autocomplete="new-password" aria-label="确认新密码" required :maxlength="72" /></label>
      </form>
      <template #footer><ActionButton variant="secondary" @click="passwordOpen = false">取消</ActionButton><ActionButton type="submit" form="settings-password-form">确认修改</ActionButton></template>
    </Modal>
  </div>
</template>

<style scoped>
.settings-page { min-width: 0; padding-bottom: 25px; animation: glass-page-rise .4s ease backwards; }
.settings-page :deep(.page-header__copy h1),.settings-page :deep(.glass-card__header),.settings-page :deep(.settings-nav__heading),.settings-page :deep(.settings-section__description) { animation: glass-content-fade .3s ease backwards; }
.settings-page :deep(.page-header) { margin-top: 4px; margin-bottom: 19px; }
.settings-header-tools { display: flex; align-items: center; gap: 10px; }
.settings-search { width: clamp(175px,20vw,255px); }
.settings-header-tools :deep(.glass-input) { min-height: 40px; border-color: rgba(255,255,255,.37); border-radius: 12px; background: rgba(219,231,255,.28); color: white; backdrop-filter: blur(var(--glass-blur)); }
.settings-header-tools :deep(.glass-input input) { color: white; }
.settings-header-tools :deep(.glass-input input::placeholder) { color: rgba(255,255,255,.75); }
.settings-header-tools :deep(.topbar__icon-button) { width: 40px; height: 40px; }
.settings-header-tools :deep(.topbar__icon-button svg) { width: 21px; height: 21px; }
.settings-reset { min-height: 40px; border-color: rgba(255,255,255,.41); background: rgba(255,255,255,.63); }
.settings-layout { display: grid; grid-template-columns: 205px minmax(0,1fr); align-items: start; gap: 16px; min-width: 0; }
.settings-content { min-width: 0; animation: glass-page-rise .35s ease backwards; }
.settings-password-form { display: grid; gap: 14px; }
@media (max-width: 880px) { .settings-layout { grid-template-columns: 1fr; gap: 13px; } }
@media (max-width: 700px) { .settings-page :deep(.page-header__actions) { width: 100%; } .settings-header-tools { width: 100%; } .settings-search { flex: 1; width: auto; min-width: 0; } }
@media (max-width: 420px) { .settings-header-tools { gap: 6px; } .settings-reset { padding: 0 9px; } .settings-reset span { display: none; } }
@media (prefers-reduced-motion: reduce) { .settings-page,.settings-content,.settings-page :deep(.page-header__copy h1),.settings-page :deep(.glass-card__header),.settings-page :deep(.settings-nav__heading),.settings-page :deep(.settings-section__description) { animation: none; } }
</style>
