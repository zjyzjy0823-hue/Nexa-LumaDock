<script setup lang="ts">
import { computed } from 'vue'
import { Bell, HardDrive, Info, Palette, RefreshCw, ShieldCheck, UserRound } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { settingsNavigation } from '../../mock/settings'
import type { SettingsSectionId } from '../../types/settings'

const props = defineProps<{ active: SettingsSectionId; query?: string }>()
const emit = defineEmits<{ select: [id: SettingsSectionId] }>()
const icons = { UserRound, Palette, RefreshCw, HardDrive, ShieldCheck, Bell, Info }
const visibleNavigation = computed(() => settingsNavigation.filter(entry => entry.label.includes(props.query?.trim() ?? '')))

function onSelect(event: Event) {
  emit('select', (event.target as HTMLSelectElement).value as SettingsSectionId)
}
</script>

<template>
  <GlassCard class="settings-nav-card">
    <div class="settings-nav__heading">PREFERENCES</div>
    <nav class="settings-nav__list" aria-label="设置分区">
      <button v-for="item in visibleNavigation" :key="item.id"
        type="button" class="settings-nav__item" :class="{ 'is-active': active === item.id }"
        :aria-current="active === item.id ? 'page' : undefined" @click="emit('select', item.id)">
        <component :is="icons[item.icon as keyof typeof icons]" :size="17" :stroke-width="1.8" />
        <span>{{ item.label }}</span>
      </button>
      <p v-if="query && !visibleNavigation.length" class="settings-nav__empty">没有找到设置项</p>
    </nav>
    <label class="settings-nav__mobile">
      <span>设置类别</span>
      <select :value="active" @change="onSelect">
        <option v-for="item in settingsNavigation" :key="item.id" :value="item.id">{{ item.label }}</option>
      </select>
    </label>
    <div class="settings-nav__foot"><span class="settings-nav__foot-dot" />Nexa 0.1.0</div>
  </GlassCard>
</template>

<style scoped>
.settings-nav-card { height: auto; align-self: start; padding: 18px 12px 14px; }
.settings-nav-card :deep(.glass-card__body) { overflow: visible; }
.settings-nav__heading { padding: 2px 12px 13px; color: rgba(255,255,255,.7); font-size: 10px; font-weight: 760; letter-spacing: .16em; }
.settings-nav__list { display: grid; gap: 4px; }
.settings-nav__item { display: flex; align-items: center; gap: 12px; width: 100%; min-height: 43px; padding: 0 12px; border: 1px solid transparent; border-radius: 12px; color: rgba(255,255,255,.85); background: transparent; text-align: left; font-size: 13px; font-weight: 630; transition: background .2s, box-shadow .2s, transform .2s; }
.settings-nav__item:hover { background: rgba(255,255,255,.15); transform: translateX(2px); }
.settings-nav__item.is-active { color: #385587; border-color: rgba(255,255,255,.75); background: rgba(255,255,255,.77); box-shadow: 0 6px 17px rgba(42,65,121,.12), inset 0 1px 0 rgba(255,255,255,.9); }
.settings-nav__item svg { opacity: .9; }
.settings-nav__empty { margin: 8px 12px; color: rgba(255,255,255,.75); font-size: 12px; }
.settings-nav__mobile { display: none; }
.settings-nav__foot { display: flex; align-items: center; gap: 7px; margin: 15px 11px 0; padding-top: 14px; border-top: 1px solid rgba(255,255,255,.22); color: rgba(255,255,255,.64); font-size: 10px; }
.settings-nav__foot-dot { width: 6px; height: 6px; border-radius: 50%; background: #7ce0c4; box-shadow: 0 0 0 3px rgba(124,224,196,.15); }
@media (max-width: 880px) {
  .settings-nav-card { width: 100%; padding: 12px 16px; }
  .settings-nav__heading,.settings-nav__list,.settings-nav__foot { display: none; }
  .settings-nav__mobile { display: flex; align-items: center; gap: 12px; color: rgba(255,255,255,.82); font-size: 12px; font-weight: 660; }
  .settings-nav__mobile select { flex: 1; min-width: 0; height: 36px; padding: 0 11px; border: var(--glass-tile-border); border-radius: 10px; color: var(--text-primary); background: rgba(255,255,255,.77); font: inherit; }
}
</style>
