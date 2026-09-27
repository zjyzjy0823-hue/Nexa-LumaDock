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
    <div class="settings-card">
      <div class="settings-card__heading"><span>事件提醒</span><Bell :size="17" /></div>
      <SettingRow v-for="event in notificationEventOptions" :key="event.id" :label="event.label" :description="event.description"><Toggle :model-value="config.events[event.id]" :aria-label="event.label" @update:model-value="updateEvent(event.id, $event)" /></SettingRow>
    </div>
    <div class="settings-card">
      <div class="settings-card__heading">通知渠道</div>
      <div class="notification-channels">
        <div v-for="channel in notificationChannelOptions" :key="channel.id" class="notification-channel"><div class="settings-icon-tile"><component :is="icons[channel.id]" :size="17" /></div><span>{{ channel.label }}</span><Toggle :model-value="config.channels[channel.id]" :aria-label="`${channel.label} 通知`" @update:model-value="updateChannel(channel.id, $event)" /></div>
      </div>
    </div>
  </SettingsSection>
</template>

<style scoped>
.settings-card__heading svg { color: #899bcc; }
.notification-channels { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px; }
.notification-channel { display: flex; align-items: center; gap: 10px; min-width: 0; padding: 10px; border: 1px solid rgba(150,174,218,.16); border-radius: 12px; color: var(--text-primary); background: rgba(255,255,255,.36); font-size: 11px; font-weight: 680; }
.notification-channel .settings-icon-tile { width: 31px; height: 31px; border-radius: 9px; }
.notification-channel :deep(.glass-toggle) { margin-left: auto; }
@media (max-width: 560px) { .notification-channels { grid-template-columns: 1fr; } }
</style>
