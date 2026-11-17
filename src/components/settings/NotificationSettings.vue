<script setup lang="ts">
import { Bell, Mail, Monitor, Radio, Webhook } from 'lucide-vue-next'
import Toggle from '../ui/Toggle.vue'
import SettingRow from './SettingRow.vue'
import SettingsSection from './SettingsSection.vue'
import { notificationChannelOptions, notificationEventOptions } from '../../mock/settings'
import type { NotificationChannel, NotificationConfig, NotificationEvent } from '../../types/settings'

const props = defineProps<{ config: NotificationConfig }>()
const emit = defineEmits<{ 'update:config': [config: NotificationConfig] }>()
const icons = { desktop: Monitor, email: Mail, telegram: Radio, webhook: Webhook }

function updateEvent(id: NotificationEvent, enabled: boolean) {
  emit('update:config', { ...props.config, events: { ...props.config.events, [id]: enabled } })
}
function updateChannel(id: NotificationChannel, enabled: boolean) {
  emit('update:config', { ...props.config, channels: { ...props.config.channels, [id]: enabled } })
}
</script>

<template>
  <SettingsSection title="通知" description="选择重要事件与接收通知的渠道。">
    <div class="settings-card settings-card--rows">
      <div class="notification-head"><Bell :size="16" /><span>事件提醒</span></div>
      <SettingRow v-for="event in notificationEventOptions" :key="event.id" :label="event.label" :description="event.description"><Toggle :model-value="config.events[event.id]" :aria-label="event.label" @update:model-value="updateEvent(event.id, $event)" /></SettingRow>
    </div>
    <div class="settings-card">
      <div class="settings-card__heading">通知渠道</div>
      <p class="faint" style="margin:0 0 12px;font-size:12.5px">通知投递尚未实现：渠道开关会保存偏好，但本版本不会真的发送通知。</p>
      <div class="notification-channels">
        <div v-for="channel in notificationChannelOptions" :key="channel.id" class="notification-channel"><div class="settings-icon-tile" style="width:30px;height:30px;border-radius:8px"><component :is="icons[channel.id]" :size="15" /></div><span>{{ channel.label }}</span><Toggle :model-value="config.channels[channel.id]" disabled :aria-label="`${channel.label} 通知（未启用）`" style="margin-left:auto" /></div>
      </div>
    </div>
  </SettingsSection>
</template>

<style scoped>
.notification-head { display: flex; align-items: center; gap: 8px; padding: 14px 16px; border-bottom: 1px solid var(--line); font-size: 14px; font-weight: 600; color: var(--text); }
.notification-head svg { color: var(--accent); }
.notification-channels { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.notification-channel { display: flex; align-items: center; gap: 10px; min-width: 0; padding: 10px 12px; border-radius: var(--r-md); color: var(--text); background: var(--surface-3); font-size: 13px; font-weight: 550; }
@media (max-width: 560px) { .notification-channels { grid-template-columns: 1fr; } }
</style>
