<script setup lang="ts">
import { ArrowUpRight, Fingerprint, KeyRound, Laptop, LockKeyhole, MonitorSmartphone, ShieldCheck } from 'lucide-vue-next'
import ActionButton from '../ui/ActionButton.vue'
import Toggle from '../ui/Toggle.vue'
import SettingRow from './SettingRow.vue'
import SettingsSection from './SettingsSection.vue'
import type { SecurityConfig } from '../../types/settings'

const props = defineProps<{ config: SecurityConfig }>()
const emit = defineEmits<{
  'update:config': [config: SecurityConfig]
  password: []
  action: [message: string]
  navigate: [page: string]
}>()

function update<K extends keyof SecurityConfig>(key: K, value: SecurityConfig[K]) {
  emit('update:config', { ...props.config, [key]: value })
}
</script>

<template>
  <SettingsSection title="安全" description="保护账户、访问会话与远程控制权限。">
    <div class="settings-card security-hero"><div class="settings-icon-tile"><ShieldCheck :size="18" /></div><div><strong>账户安全</strong><p>关键操作在你的掌控之中。</p></div><span class="chip" style="margin-left:auto;color:var(--ok);background:var(--ok-soft)">已保护</span></div>
    <div class="settings-card settings-card--rows">
      <SettingRow label="修改密码" description="定期更新密码可保护账户"><ActionButton variant="secondary" size="sm" @click="emit('password')"><KeyRound :size="14" />修改</ActionButton></SettingRow>
      <SettingRow label="双重身份验证" description="双重身份验证尚未提供"><Toggle :model-value="false" disabled aria-label="双重身份验证尚未提供" /></SettingRow>
      <SettingRow label="登录会话" :description="`${config.activeSessions} 个活跃会话`"><button type="button" class="btn btn-sm btn-subtle" @click="emit('action', '会话管理将在连接服务后开放。')"><MonitorSmartphone :size="14" />查看<ArrowUpRight :size="13" /></button></SettingRow>
      <SettingRow label="受信任设备" :description="`${config.trustedDevices} 台受信任设备`"><button type="button" class="btn btn-sm btn-subtle" @click="emit('action', '受信任设备管理将在连接服务后开放。')"><Laptop :size="14" />管理<ArrowUpRight :size="13" /></button></SettingRow>
      <SettingRow label="API 令牌" :description="`${config.apiTokens} 个活跃密钥`"><button type="button" class="btn btn-sm btn-subtle" @click="emit('navigate', 'API')"><Fingerprint :size="14" />前往 API<ArrowUpRight :size="13" /></button></SettingRow>
    </div>
    <div class="settings-card settings-card--rows">
      <div class="security-remote__title"><div class="settings-icon-tile"><LockKeyhole :size="17" /></div><div><strong>远程控制权限</strong><span>每次远程操作前确认</span></div></div>
      <SettingRow label="要求确认" description="每次远程控制前要求确认"><Toggle :model-value="config.requireRemoteConfirmation" aria-label="远程控制前要求确认" @update:model-value="update('requireRemoteConfirmation', $event)" /></SettingRow>
    </div>
  </SettingsSection>
</template>

<style scoped>
.security-hero { display: flex; align-items: center; gap: 12px; }
.security-hero strong { color: var(--text); font-size: 14px; font-weight: 600; }
.security-hero p { margin: 2px 0 0; color: var(--text-3); font-size: 12.5px; }
.security-remote__title { display: flex; align-items: center; gap: 12px; padding: 14px 16px; border-bottom: 1px solid var(--line); }
.security-remote__title > div:last-child { display: flex; flex-direction: column; gap: 2px; }
.security-remote__title strong { color: var(--text); font-size: 14px; font-weight: 600; }
.security-remote__title span { color: var(--text-3); font-size: 12px; }
</style>
