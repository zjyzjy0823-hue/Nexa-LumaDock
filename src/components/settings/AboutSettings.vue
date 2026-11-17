<script setup lang="ts">
import { ArrowUpRight, BookOpen, FileText, Github, RefreshCw } from 'lucide-vue-next'
import ActionButton from '../ui/ActionButton.vue'
import SettingRow from './SettingRow.vue'
import SettingsSection from './SettingsSection.vue'
import DiagnosticsSettings from './DiagnosticsSettings.vue'
import StudioloMark from '../ui/StudioloMark.vue'
import type { AboutInfo } from '../../types/settings'

defineProps<{ info: AboutInfo }>()
const emit = defineEmits<{ action: [message: string] }>()
</script>

<template>
  <SettingsSection title="关于" description="Studiolo 的版本信息与相关资源。">
    <div class="settings-card about-hero">
      <span class="logo" style="width:44px;height:44px;border-radius:13px" aria-hidden="true"><StudioloMark style="width:22px;height:22px" /></span>
      <div><strong>{{ info.product }}</strong><p>Your digital space, beautifully connected.</p></div>
    </div>
    <div class="settings-card settings-card--rows">
      <SettingRow label="版本"><strong class="about-value mono">{{ info.version }}</strong></SettingRow>
      <SettingRow label="构建"><strong class="about-value mono">{{ info.build }}</strong></SettingRow>
      <SettingRow label="检查更新" description="检查是否有可用的新版本"><ActionButton variant="secondary" size="sm" @click="emit('action', '自动检查更新尚未实现。')"><RefreshCw :size="14" />检查更新</ActionButton></SettingRow>
    </div>
    <div class="settings-card settings-card--rows">
      <button class="row about-row" type="button" @click="emit('action', 'GitHub 链接将在正式发布时提供。')"><Github :size="16" /><span class="grow">GitHub</span><ArrowUpRight :size="14" /></button>
      <button class="row about-row" type="button" @click="emit('action', '使用文档将在正式发布时提供。')"><BookOpen :size="16" /><span class="grow">Documentation</span><ArrowUpRight :size="14" /></button>
      <button class="row about-row" type="button" @click="emit('action', '许可证信息将在正式发布时提供。')"><FileText :size="16" /><span class="grow">Licenses</span><ArrowUpRight :size="14" /></button>
    </div>
    <DiagnosticsSettings />
  </SettingsSection>
</template>

<style scoped>
.about-hero { display: flex; align-items: center; gap: 14px; }
.about-hero strong { color: var(--text); font-size: 18px; font-weight: 700; }
.about-hero p { margin: 2px 0 0; color: var(--text-3); font-size: 12.5px; }
.about-value { color: var(--text); font-size: 13px; font-weight: 600; }
.about-row { padding: 13px 16px; border-radius: 0; font-size: 13.5px; }
.about-row + .about-row { border-top: 1px solid var(--line); }
</style>
