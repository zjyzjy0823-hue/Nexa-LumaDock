<script setup lang="ts">
import { Check, CircleHelp, Droplets, SlidersHorizontal, Sparkles } from 'lucide-vue-next'
import SettingsSection from './SettingsSection.vue'
import { accentOptions, backgroundOptions, themeOptions } from '../../mock/settings'
import type { AppearanceConfig } from '../../types/settings'

const props = defineProps<{ config: AppearanceConfig }>()
const emit = defineEmits<{ 'update:config': [config: AppearanceConfig] }>()

function update<K extends keyof AppearanceConfig>(key: K, value: AppearanceConfig[K]) {
  emit('update:config', { ...props.config, [key]: value })
}
const accent = () => accentOptions.find(item => item.id === props.config.accent)?.color ?? accentOptions[0]!.color
</script>

<template>
  <SettingsSection title="外观" description="调整 Nexa 的玻璃质感与环境光。">
    <div class="appearance-layout">
      <div class="appearance-main">
        <div class="settings-card">
          <div class="settings-card__heading"><span>主题</span><Sparkles :size="16" /></div>
          <div class="theme-options" role="group" aria-label="主题">
            <button v-for="theme in themeOptions" :key="theme.id" type="button" class="theme-option"
              :class="[`theme-option--${theme.id}`, { 'is-active': config.theme === theme.id }]"
              :aria-label="theme.label" :aria-pressed="config.theme === theme.id" @click="update('theme', theme.id)">
              <span class="theme-option__preview"><i /><i /></span>
              <strong>{{ theme.label }}</strong><small>{{ theme.detail }}</small>
              <Check v-if="config.theme === theme.id" class="theme-option__check" :size="14" />
            </button>
          </div>
        </div>

        <div class="settings-card appearance-adjustments">
          <div class="settings-card__heading"><span>玻璃效果</span><SlidersHorizontal :size="16" /></div>
          <label class="appearance-slider"><span><Droplets :size="15" />玻璃透明度<strong>{{ config.transparency }}%</strong></span><input :value="config.transparency" type="range" min="20" max="90" step="1" @input="update('transparency', Number(($event.target as HTMLInputElement).value))" /></label>
          <label class="appearance-slider"><span><CircleHelp :size="15" />模糊强度<strong>{{ config.blur }}px</strong></span><input :value="config.blur" type="range" min="0" max="32" step="1" @input="update('blur', Number(($event.target as HTMLInputElement).value))" /></label>
          <div class="appearance-color-heading">强调色</div>
          <div class="accent-options" role="group" aria-label="强调色">
            <button v-for="option in accentOptions" :key="option.id" type="button" class="accent-option"
              :class="{ 'is-active': config.accent === option.id }" :aria-label="option.label" :aria-pressed="config.accent === option.id"
              @click="update('accent', option.id)"><i :style="{ backgroundColor: option.color }" /><span>{{ option.label }}</span></button>
          </div>
        </div>

        <div class="settings-card">
          <div class="settings-card__heading">背景</div>
          <div class="background-options" role="group" aria-label="背景">
            <button v-for="option in backgroundOptions" :key="option.id" type="button" class="background-option"
              :class="{ 'is-active': config.background === option.id }" :aria-label="option.label" :aria-pressed="config.background === option.id"
              @click="update('background', option.id)">
              <span class="background-option__preview" :class="`background--${option.id}`"><i /></span>
              <span>{{ option.label }}</span>
            </button>
          </div>
        </div>
      </div>

      <div class="appearance-side">
        <div class="appearance-live-title">实时预览 <span>LIVE PREVIEW</span></div>
        <div class="appearance-preview" :class="[`background--${config.background}`, `appearance-preview--${config.theme}`]"
          :style="{ '--preview-accent': accent(), '--preview-blur': `${config.blur}px`, '--preview-opacity': `${config.transparency / 100}` }">
          <div class="appearance-preview__orb" />
          <div class="appearance-preview__panel"><div class="appearance-preview__top"><span class="appearance-preview__logo">✦</span><span class="appearance-preview__dots">•••</span></div><strong>Nexa</strong><small>Everything in its place.</small><div class="appearance-preview__line"><span /></div><div class="appearance-preview__tiles"><i /><i /><i /></div></div>
        </div>
        <p class="appearance-preview-note">选择会立即呈现在预览中。当前设置仅保存在本次会话。</p>
      </div>
    </div>
  </SettingsSection>
</template>

<style scoped>
.appearance-layout { display: grid; grid-template-columns: minmax(0,1.6fr) minmax(220px,.85fr); gap: 15px; align-items: start; }
.appearance-main,.appearance-side { min-width: 0; }
.settings-card__heading svg { color: #8899c3; }
.theme-options { display: grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap: 10px; }
.theme-option { position: relative; display: flex; flex-direction: column; align-items: flex-start; min-width: 0; padding: 9px; border: 1px solid rgba(151,172,214,.27); border-radius: 12px; color: var(--text-primary); background: rgba(255,255,255,.45); text-align: left; transition: transform .2s,border-color .2s,box-shadow .2s; }
.theme-option:hover { transform: translateY(-2px); }
.theme-option.is-active { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(102,137,237,.12); }
.theme-option__preview { position: relative; display: block; width: 100%; height: 57px; overflow: hidden; border-radius: 8px; background: linear-gradient(130deg,#b7d8fd,#d5d8ff 55%,#f7cfde); }
.theme-option__preview i { position: absolute; display: block; border: 1px solid rgba(255,255,255,.75); border-radius: 5px; background: rgba(255,255,255,.52); }
.theme-option__preview i:first-child { inset: 9px auto 9px 10px; width: 21%; }
.theme-option__preview i:last-child { inset: 9px 10px 9px 37%; }
.theme-option--dark .theme-option__preview { background: linear-gradient(135deg,#222951,#464075,#ad7ea7); }
.theme-option--dark .theme-option__preview i { border-color: rgba(255,255,255,.26); background: rgba(50,57,100,.6); }
.theme-option--auto .theme-option__preview { background: linear-gradient(100deg,#d5e6ff 0 50%,#383865 50%); }
.theme-option--auto .theme-option__preview i:last-child { background: rgba(68,64,111,.6); }
.theme-option strong { margin-top: 8px; font-size: 11px; white-space: nowrap; }
.theme-option small { margin-top: 2px; color: var(--text-secondary); font-size: 10px; white-space: nowrap; }
.theme-option__check { position: absolute; top: 13px; right: 13px; padding: 1px; border-radius: 50%; color: white; background: var(--accent); }
.appearance-adjustments { margin-top: 13px; }
.appearance-slider { display: grid; gap: 9px; margin-bottom: 15px; }
.appearance-slider > span { display: flex; align-items: center; gap: 7px; color: var(--text-primary); font-size: 11px; font-weight: 640; }
.appearance-slider > span svg { color: #8194bf; }
.appearance-slider strong { margin-left: auto; color: var(--text-secondary); font-size: 10px; font-weight: 640; }
.appearance-slider input { width: 100%; height: 7px; margin: 0; accent-color: var(--accent); cursor: pointer; }
.appearance-color-heading { margin-top: 17px; padding-top: 15px; border-top: 1px solid var(--line); color: var(--text-primary); font-size: 11px; font-weight: 680; }
.accent-options { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.accent-option { display: flex; align-items: center; gap: 6px; padding: 5px 7px; border: 1px solid transparent; border-radius: 9px; color: var(--text-secondary); background: transparent; font-size: 10px; }
.accent-option:hover,.accent-option.is-active { border-color: rgba(132,157,206,.28); color: var(--text-primary); background: rgba(255,255,255,.7); }
.accent-option i { display: block; width: 18px; height: 18px; border: 2px solid white; border-radius: 50%; box-shadow: 0 2px 6px rgba(35,54,101,.14); }
.background-options { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 8px; }
.background-option { min-width: 0; padding: 5px; border: 1px solid transparent; border-radius: 11px; color: var(--text-secondary); background: transparent; font-size: 10px; text-align: left; }
.background-option:hover,.background-option.is-active { border-color: rgba(117,146,217,.46); color: var(--text-primary); background: rgba(255,255,255,.55); }
.background-option__preview { display: block; height: 45px; margin-bottom: 5px; overflow: hidden; border: 1px solid rgba(255,255,255,.6); border-radius: 7px; }
.background-option__preview i { display: block; width: 38px; height: 38px; margin: 17px 0 0 39%; border-radius: 50%; background: rgba(255,255,255,.22); filter: blur(8px); }
.background--sky { background: radial-gradient(circle at 78% 15%,rgba(255,234,240,.85),transparent 40%),linear-gradient(135deg,#90c1ef,#aca6e7 57%,#e2aed1); }
.background--aurora { background: radial-gradient(circle at 70% 25%,rgba(141,255,213,.62),transparent 42%),linear-gradient(135deg,#4f76bd,#8785d6 59%,#e7acd5); }
.background--minimal { background: linear-gradient(135deg,#d7e4f4,#e8eaf6 60%,#f8ecf4); }
.background--custom { background: radial-gradient(circle at 76% 17%,rgba(251,203,177,.7),transparent 43%),linear-gradient(135deg,#5f8ec8,#9f8ad4 58%,#cfc6eb); }
.appearance-live-title { display: flex; align-items: center; justify-content: space-between; margin: 3px 1px 11px; color: white; font-size: 12px; font-weight: 700; }
.appearance-live-title span { color: rgba(255,255,255,.65); font-size: 9px; letter-spacing: .14em; }
.appearance-preview { position: relative; display: grid; min-height: 300px; overflow: hidden; place-items: center; padding: 18px; border: 1px solid rgba(255,255,255,.65); border-radius: 20px; box-shadow: 0 12px 27px rgba(39,56,103,.16); }
.appearance-preview__orb { position: absolute; top: 4%; right: -18%; width: 70%; aspect-ratio: 1; border-radius: 50%; background: rgba(255,255,255,.36); filter: blur(32px); }
.appearance-preview__panel { position: relative; width: min(100%,230px); padding: 15px; border: 1px solid rgba(255,255,255,.72); border-radius: 17px; color: #283a62; background: rgba(255,255,255,var(--preview-opacity)); box-shadow: 0 12px 29px rgba(24,39,87,.17), inset 0 1px 0 rgba(255,255,255,.75); backdrop-filter: blur(var(--preview-blur)); -webkit-backdrop-filter: blur(var(--preview-blur)); }
.appearance-preview--dark .appearance-preview__panel { border-color: rgba(255,255,255,.33); color: white; background: rgba(31,37,78,var(--preview-opacity)); }
.appearance-preview__top { display: flex; justify-content: space-between; color: var(--preview-accent); }
.appearance-preview__logo { display: grid; width: 25px; height: 25px; place-items: center; border-radius: 8px; color: white; background: var(--preview-accent); }
.appearance-preview__dots { color: rgba(98,118,155,.65); letter-spacing: 2px; }
.appearance-preview__panel strong { display: block; margin-top: 20px; font-size: 17px; letter-spacing: -.04em; }
.appearance-preview__panel small { display: block; margin-top: 3px; opacity: .66; font-size: 10px; }
.appearance-preview__line { height: 7px; margin-top: 20px; border-radius: 7px; background: rgba(138,157,197,.18); }
.appearance-preview__line span { display: block; width: 64%; height: 100%; border-radius: inherit; background: var(--preview-accent); }
.appearance-preview__tiles { display: grid; grid-template-columns: repeat(3,1fr); gap: 6px; margin-top: 12px; }
.appearance-preview__tiles i { height: 27px; border: 1px solid rgba(255,255,255,.43); border-radius: 7px; background: rgba(255,255,255,.39); }
.appearance-preview-note { margin: 10px 2px 0; color: rgba(255,255,255,.7); font-size: 10px; line-height: 1.5; }
@media (max-width: 1100px) { .appearance-layout { grid-template-columns: 1fr; } .appearance-preview { min-height: 240px; } }
@media (max-width: 560px) { .theme-options { gap: 6px; } .theme-option { padding: 6px; } .theme-option__preview { height: 43px; } .theme-option strong { font-size: 10px; } .theme-option small { display: none; } .background-options { grid-template-columns: repeat(2,minmax(0,1fr)); } }
</style>
