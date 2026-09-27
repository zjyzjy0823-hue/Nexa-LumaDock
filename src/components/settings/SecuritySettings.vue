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
    <div class="settings-card security-hero"><div class="settings-icon-tile"><ShieldCheck :size="20" /></div><div><strong>账户安全</strong><p>关键操作在你的掌控之中。</p></div><span>PROTECTED</span></div>
    <div class="settings-card">
      <SettingRow label="修改密码" description="定期更新密码可保护账户"><ActionButton variant="secondary" size="sm" @click="emit('password')"><KeyRound :size="14" />修改</ActionButton></SettingRow>
      <SettingRow label="Two-Factor Authentication" description="登录时增加一道安全验证"><Toggle :model-value="config.twoFactor" aria-label="双重身份验证" @update:model-value="update('twoFactor', $event)" /></SettingRow>
      <SettingRow label="登录 Session" :description="`${config.activeSessions} 个活跃会话`"><button type="button" class="security-row-link" @click="emit('action', '会话管理将在连接服务后开放。')"><MonitorSmartphone :size="15" />查看<ArrowUpRight :size="13" /></button></SettingRow>
      <SettingRow label="Trusted Devices" :description="`${config.trustedDevices} 台受信任设备`"><button type="button" class="security-row-link" @click="emit('action', '受信任设备管理将在连接服务后开放。')"><Laptop :size="15" />管理<ArrowUpRight :size="13" /></button></SettingRow>
      <SettingRow label="API Tokens" :description="`${config.apiTokens} 个活跃密钥`"><button type="button" class="security-row-link" @click="emit('navigate', 'API')"><Fingerprint :size="15" />前往 API<ArrowUpRight :size="13" /></button></SettingRow>
    </div>
    <div class="settings-card security-remote"><div class="security-remote__title"><div class="settings-icon-tile"><LockKeyhole :size="18" /></div><div><strong>Remote Control Permission</strong><span>远程控制权限</span></div></div><SettingRow label="Require confirmation" description="每次远程控制前要求确认"><Toggle :model-value="config.requireRemoteConfirmation" aria-label="远程控制前要求确认" @update:model-value="update('requireRemoteConfirmation', $event)" /></SettingRow></div>
  </SettingsSection>
</template>

<style scoped>
.security-hero { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.security-hero strong { color: var(--text-primary); font-size: 13px; }
.security-hero p { margin: 4px 0 0; color: var(--text-secondary); font-size: 11px; }
.security-hero > span { margin-left: auto; color: #53a48f; font-size: 9px; font-weight: 760; letter-spacing: .12em; }
.security-row-link { display: inline-flex; align-items: center; gap: 5px; padding: 5px 2px; border: 0; color: #5977c0; background: none; font-size: 11px; font-weight: 690; white-space: nowrap; }
.security-row-link:hover { color: var(--accent-deep); }
.security-remote { margin-top: 14px; }
.security-remote__title { display: flex; align-items: center; gap: 11px; margin-bottom: 17px; }
.security-remote__title > div:last-child { display: flex; flex-direction: column; gap: 3px; }
.security-remote__title strong { color: var(--text-primary); font-size: 12px; }
.security-remote__title span { color: var(--text-secondary); font-size: 10px; }
@media (max-width: 560px) { .security-hero > span { display: none; } .security-row-link { font-size: 10px; } }
</style>
