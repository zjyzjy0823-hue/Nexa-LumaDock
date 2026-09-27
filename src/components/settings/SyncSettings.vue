<script setup lang="ts">
import { CheckCircle2, Cloud, RefreshCw } from 'lucide-vue-next'
import ActionButton from '../ui/ActionButton.vue'
import Input from '../ui/Input.vue'
import Toggle from '../ui/Toggle.vue'
import SettingRow from './SettingRow.vue'
import SettingsSection from './SettingsSection.vue'
import { syncModeOptions } from '../../mock/settings'
import type { SyncConfig } from '../../types/settings'

const props = defineProps<{ config: SyncConfig; syncing?: boolean }>()
const emit = defineEmits<{ 'update:config': [config: SyncConfig]; sync: [] }>()

function update<K extends keyof SyncConfig>(key: K, value: SyncConfig[K]) {
  emit('update:config', { ...props.config, [key]: value })
}
</script>

<template>
  <SettingsSection title="同步" description="选择数据在各设备之间保持最新的方式。">
    <div class="settings-card">
      <div class="settings-card__heading"><span>同步模式</span><Cloud :size="17" /></div>
      <div class="sync-mode-options" role="group" aria-label="同步模式">
        <button v-for="mode in syncModeOptions" :key="mode.id" type="button" class="sync-mode"
          :class="{ 'is-active': config.mode === mode.id }" :aria-pressed="config.mode === mode.id" @click="update('mode', mode.id)">
          <span class="sync-mode__check"><CheckCircle2 :size="15" /></span><strong>{{ mode.label }}</strong><small>{{ mode.detail }}</small>
        </button>
      </div>
      <label class="settings-field sync-server"><span>服务器地址</span><Input :model-value="config.serverUrl" type="url" aria-label="服务器地址" placeholder="https://nexa.example.com" @update:model-value="update('serverUrl', $event)" /></label>
    </div>
    <div class="settings-card">
      <SettingRow label="自动同步" description="有更新时自动保持数据一致"><Toggle :model-value="config.automatic" aria-label="自动同步" @update:model-value="update('automatic', $event)" /></SettingRow>
      <SettingRow label="移动网络同步" description="使用移动网络时继续同步"><Toggle :model-value="config.cellular" aria-label="移动网络同步" @update:model-value="update('cellular', $event)" /></SettingRow>
      <SettingRow label="同步状态" description="自动同步服务尚未启用"><span class="sync-status">未启用</span></SettingRow>
    </div>
    <div class="settings-button-row"><ActionButton :disabled="syncing" @click="emit('sync')"><RefreshCw :size="15" :class="{ 'sync-spin': syncing }" />{{ syncing ? '刷新中…' : '刷新设置' }}</ActionButton></div>
  </SettingsSection>
</template>

<style scoped>
.settings-card__heading svg { color: #899bcc; }
.sync-mode-options { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 10px; }
.sync-mode { display: flex; flex-direction: column; align-items: flex-start; min-width: 0; min-height: 94px; padding: 12px; border: 1px solid rgba(148,169,213,.29); border-radius: 12px; color: var(--text-primary); background: rgba(255,255,255,.45); text-align: left; transition: transform .2s,border-color .2s,box-shadow .2s; }
.sync-mode:hover { transform: translateY(-2px); }
.sync-mode.is-active { border-color: var(--accent); background: rgba(255,255,255,.78); box-shadow: 0 0 0 2px rgba(102,137,237,.1); }
.sync-mode__check { color: #a8b3c7; }
.sync-mode.is-active .sync-mode__check { color: var(--accent-deep); }
.sync-mode strong { margin-top: 6px; font-size: 11px; }
.sync-mode small { margin-top: 3px; color: var(--text-secondary); font-size: 10px; }
.sync-server { margin-top: 21px; }
.sync-status { display: inline-flex; align-items: center; gap: 6px; color: #379d85; font-size: 11px; font-weight: 670; }
.sync-status span { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.sync-spin { animation: sync-rotate 1s linear infinite; }
@keyframes sync-rotate { to { transform: rotate(360deg); } }
@media (max-width: 560px) { .sync-mode-options { gap: 6px; } .sync-mode { min-height: 85px; padding: 8px; } .sync-mode small { font-size: 9px; } }
</style>
