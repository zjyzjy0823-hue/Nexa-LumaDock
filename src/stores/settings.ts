import { defineStore } from 'pinia'
import { ref } from 'vue'
import { settingsService } from '../services/settings'
import type { SettingsPayload } from '../types/settings'

export const defaultSettings: SettingsPayload = {
  theme: 'system', language: 'zh-CN', timezone: 'Asia/Shanghai',
  notifications: { events: { agentComplete: true, deviceOffline: true, automationFailure: true, budgetAlert: false, securityAlert: true }, channels: { desktop: true, email: false, telegram: false, webhook: false } },
  appearance: { theme: 'auto', transparency: 62, blur: 18, accent: 'blue', background: 'sky' },
  sync: { mode: 'local', serverUrl: '', automatic: false, cellular: false, lastSynced: '尚未同步' },
  security: { twoFactor: false, requireRemoteConfirmation: true, trustedDevices: 0, activeSessions: 1, apiTokens: 0 },
}

function normalize(value: SettingsPayload): SettingsPayload {
  return { ...defaultSettings, ...value,
    notifications: { events: { ...defaultSettings.notifications.events, ...value.notifications?.events }, channels: { ...defaultSettings.notifications.channels, ...value.notifications?.channels } },
    appearance: { ...defaultSettings.appearance, ...value.appearance }, sync: { ...defaultSettings.sync, ...value.sync }, security: { ...defaultSettings.security, ...value.security } }
}

export const useSettingsStore = defineStore('settings', () => {
  const settings = ref<SettingsPayload>(structuredClone(defaultSettings))
  const loading = ref(false), loaded = ref(false), error = ref('')
  let sequence = 0
  async function load(token: string, force = false) {
    if ((loaded.value || loading.value) && !force) return
    const current = ++sequence; loading.value = true; error.value = ''
    try { const result = await settingsService.get(token); if (current === sequence) { settings.value = normalize(result); loaded.value = true } }
    catch (cause) { if (current === sequence) error.value = cause instanceof Error ? cause.message : '加载设置失败'; throw cause }
    finally { if (current === sequence) loading.value = false }
  }
  async function update(token: string, payload: Partial<SettingsPayload>) {
    if (loading.value) throw new Error('操作正在进行中')
    const current = sequence
    loading.value = true; error.value = ''
    try { const result = await settingsService.update(token, payload); if (current === sequence) settings.value = normalize(result) }
    catch (cause) { if (current === sequence) error.value = cause instanceof Error ? cause.message : '保存设置失败'; throw cause }
    finally { if (current === sequence) loading.value = false }
  }
  function reset() { ++sequence; settings.value = structuredClone(defaultSettings); loading.value = false; loaded.value = false; error.value = '' }
  return { settings, loading, loaded, error, load, update, reset }
})
