<script setup lang="ts">
import type { Component } from 'vue'
import {
  BellRing, Bot, CalendarClock, Cloud, Database, FileClock, HardDrive,
  MonitorUp, RefreshCw, ServerCog, ShieldCheck, Webhook, Workflow,
} from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import type { AutomationIcon, AutomationItem } from '../../mock/automation'

defineProps<{ automation: AutomationItem }>()
const emit = defineEmits<{ toggle: [id: string] }>()

const icons: Record<AutomationIcon, Component> = {
  backup: HardDrive, nas: RefreshCw, notification: BellRing, agent: Bot,
  server: ServerCog, calendar: CalendarClock, file: FileClock, webhook: Webhook,
  workflow: Workflow, shield: ShieldCheck, cloud: Cloud, database: Database,
}
</script>

<template>
  <GlassCard class="automation-card">
    <div class="automation-card__top">
      <span class="automation-card__icon" :class="`automation-card__icon--${automation.icon}`" aria-hidden="true">
        <component :is="icons[automation.icon]" :size="20" :stroke-width="1.8" />
      </span>
      <button
        class="automation-switch"
        :class="{ 'automation-switch--on': automation.enabled }"
        type="button"
        role="switch"
        :aria-checked="automation.enabled"
        :aria-label="`${automation.enabled ? '暂停' : '启动'}${automation.title}`"
        @click="emit('toggle', automation.id)"
      ><span /></button>
    </div>
    <div class="automation-card__heading">
      <h3>{{ automation.title }}</h3>
      <span class="automation-card__status" :class="{ 'automation-card__status--on': automation.enabled }"><i />{{ automation.enabled ? '运行中' : '已暂停' }}</span>
    </div>
    <p class="automation-card__description">{{ automation.description }}</p>
    <div class="automation-card__footer">
      <span><MonitorUp :size="13" :stroke-width="1.8" />{{ automation.trigger }}</span>
      <span>上次执行 · {{ automation.lastExecution }}</span>
    </div>
  </GlassCard>
</template>

<style scoped>
.automation-card { min-height: 175px; padding: 17px 18px 15px; border: var(--glass-tile-border); background: var(--glass-tile-background); box-shadow: var(--glass-tile-shadow); }
.automation-card :deep(.glass-card__body) { display: flex; flex-direction: column; overflow: visible; }
.automation-card__top { display: flex; align-items: flex-start; justify-content: space-between; }
.automation-card__icon { display: grid; width: 42px; height: 42px; place-items: center; border: 1px solid rgba(130,154,227,.15); border-radius: 13px; color: #6984dc; background: rgba(255,255,255,.57); box-shadow: inset 0 1px 0 rgba(255,255,255,.6); }
.automation-card__icon--nas,.automation-card__icon--cloud,.automation-card__icon--file { color: #3c9c94; }
.automation-card__icon--agent,.automation-card__icon--workflow,.automation-card__icon--webhook { color: #8a67c4; }
.automation-card__icon--notification,.automation-card__icon--calendar { color: #c78d4d; }
.automation-switch { display: flex; align-items: center; width: 36px; height: 21px; padding: 2px; border: 1px solid rgba(126,145,177,.19); border-radius: 999px; background: #c4cfdf; box-shadow: inset 0 2px 4px rgba(51,68,110,.12); transition: background .2s ease,box-shadow .2s ease; }
.automation-switch--on { background:linear-gradient(110deg,#77a5f5,#8b83e8); box-shadow:0 3px 9px rgba(100,124,216,.23); }
.automation-switch span { width: 15px; height: 15px; border-radius: 50%; background: #fff; box-shadow: 0 1px 4px rgba(31,42,89,.18); transition: transform .2s ease; }
.automation-switch--on span { transform: translateX(15px); }
.automation-card__heading { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.automation-card__heading h3 { margin: 0; color: #2e405f; font-size: 14px; font-weight: 720; letter-spacing: -.025em; }
.automation-card__status { display: inline-flex; align-items: center; gap: 5px; padding: 3px 7px; border: 1px solid rgba(163,178,207,.24); border-radius: 999px; color: #6d7b95; background: rgba(255,255,255,.58); font-size: 9px; font-weight: 650; white-space: nowrap; }
.automation-card__status i { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
.automation-card__status--on { color: #238f71; background: rgba(219,248,234,.82); }
.automation-card__description { margin: 5px 0 0; color: #405572; font-size: 11px; font-weight: 520; line-height: 1.45; }
.automation-card__footer { display: flex; align-items: center; justify-content: space-between; gap: 6px; margin-top: auto; padding-top: 12px; color: #4a5d79; font-size: 10px; font-weight: 570; }
.automation-card__footer span { display: inline-flex; align-items: center; gap: 4px; min-width: 0; white-space: nowrap; }
.automation-card__footer span:last-child { overflow: hidden; text-overflow: ellipsis; }
@media (max-width: 550px) { .automation-card { min-height: 165px; } }
</style>
