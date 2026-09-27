<script setup lang="ts">
import { ArrowUpRight, BookOpen, FileText, Github, RefreshCw, Sparkles } from 'lucide-vue-next'
import ActionButton from '../ui/ActionButton.vue'
import SettingRow from './SettingRow.vue'
import SettingsSection from './SettingsSection.vue'
import type { AboutInfo } from '../../types/settings'

defineProps<{ info: AboutInfo }>()
const emit = defineEmits<{ action: [message: string] }>()
</script>

<template>
  <SettingsSection title="关于" description="Nexa 的版本信息与相关资源。">
    <div class="settings-card about-hero"><div class="about-logo"><Sparkles :size="29" /></div><div><strong>{{ info.product }}</strong><p>Your digital space, beautifully connected.</p></div></div>
    <div class="settings-card">
      <SettingRow label="Version"><strong class="about-value">{{ info.version }}</strong></SettingRow>
      <SettingRow label="Build"><strong class="about-value">{{ info.build }}</strong></SettingRow>
      <SettingRow label="Check for Updates" description="检查是否有可用的新版本"><ActionButton variant="secondary" size="sm" @click="emit('action', '自动检查更新尚未实现。')"><RefreshCw :size="14" />检查更新</ActionButton></SettingRow>
    </div>
    <div class="settings-card about-links">
      <button type="button" @click="emit('action', 'GitHub 链接将在正式发布时提供。')"><Github :size="17" /><span>GitHub</span><ArrowUpRight :size="14" /></button>
      <button type="button" @click="emit('action', '使用文档将在正式发布时提供。')"><BookOpen :size="17" /><span>Documentation</span><ArrowUpRight :size="14" /></button>
      <button type="button" @click="emit('action', '许可证信息将在正式发布时提供。')"><FileText :size="17" /><span>Licenses</span><ArrowUpRight :size="14" /></button>
    </div>
  </SettingsSection>
</template>

<style scoped>
.about-hero { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; }
.about-logo { display: grid; width: 60px; height: 60px; flex: none; place-items: center; border: 1px solid rgba(255,255,255,.8); border-radius: 18px; color: white; background: linear-gradient(135deg,#6b94ef,#a589e4); box-shadow: 0 9px 21px rgba(96,112,206,.21), inset 0 1px 0 rgba(255,255,255,.38); }
.about-hero strong { color: var(--text-primary); font-size: 22px; font-weight: 730; letter-spacing: -.04em; }
.about-hero p { margin: 3px 0 0; color: var(--text-secondary); font-size: 11px; }
.about-value { color: var(--text-primary); font-size: 12px; font-weight: 690; }
.about-links { display: grid; gap: 4px; margin-top: 14px; }
.about-links button { display: flex; align-items: center; gap: 11px; width: 100%; padding: 11px 6px; border: 0; border-bottom: 1px solid var(--line); color: #5874b9; background: transparent; text-align: left; font-size: 12px; font-weight: 660; }
.about-links button:last-child { border-bottom: 0; }
.about-links button:hover { color: var(--accent-deep); }
.about-links button svg:last-child { margin-left: auto; }
</style>
