<script setup lang="ts">
import type { Component } from 'vue'
import { BellRing, Bot, CalendarClock, FileClock, ServerCog, Webhook } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import type { AutomationIcon, TriggerItem } from '../../mock/automation'

defineProps<{ triggers: TriggerItem[]; selectedId: string }>()
const emit = defineEmits<{ select: [id: string] }>()
const icons: Partial<Record<AutomationIcon, Component>> = {
  notification: BellRing, calendar: CalendarClock, file: FileClock,
  webhook: Webhook, agent: Bot, server: ServerCog,
}
</script>

<template>
  <GlassCard class="trigger-library">
    <div class="trigger-library__heading"><span class="trigger-library__eyebrow">TRIGGER LIBRARY</span><h2>触发器库</h2><p>选择事件，快速定义工作流的起点</p></div>
    <div class="trigger-library__grid">
      <button v-for="trigger in triggers" :key="trigger.id" class="trigger-tile" :class="{ 'trigger-tile--selected': trigger.id === selectedId }" type="button" :aria-pressed="trigger.id === selectedId" @click="emit('select', trigger.id)">
        <span class="trigger-tile__icon"><component :is="icons[trigger.icon]" :size="17" :stroke-width="1.8" /></span>
        <span class="trigger-tile__copy"><strong>{{ trigger.title }}</strong><small>{{ trigger.description }}</small></span>
      </button>
    </div>
  </GlassCard>
</template>

<style scoped>
.trigger-library { min-height: 280px; }
.trigger-library :deep(.glass-card__body) { overflow: visible; }
.trigger-library__eyebrow { color: rgba(255,255,255,.7); font-size: 9px; font-weight: 760; letter-spacing: .14em; }
.trigger-library__heading h2 { margin: 5px 0 0; color: #fff; font-size: 16px; letter-spacing: -.03em; text-shadow: 0 1px 8px rgba(27,42,84,.3); }
.trigger-library__heading p { margin: 4px 0 0; color: rgba(255,255,255,.76); font-size: 10px; }
.trigger-library__grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 8px; margin-top: 16px; }
.trigger-tile { display: flex; align-items: center; gap: 8px; min-width: 0; min-height: 55px; padding: 7px 8px; border: var(--glass-tile-border); border-radius: 12px; color: #435473; background: var(--glass-tile-background); box-shadow: var(--glass-tile-shadow); backdrop-filter: blur(12px) saturate(125%); -webkit-backdrop-filter: blur(12px) saturate(125%); text-align: left; transition: transform .2s, box-shadow .2s, background .2s; }
.trigger-tile:hover { transform: scale(1.02); background: var(--glass-tile-hover-background); box-shadow: var(--glass-tile-hover-shadow); }
.trigger-tile--selected { border-color: rgba(164,191,255,.85); background: rgba(196,212,255,.65); }
.trigger-tile__icon { display: grid; width: 31px; height: 31px; flex: none; place-items: center; border-radius: 9px; color: #6e86d5; background: rgba(255,255,255,.57); }
.trigger-tile--selected .trigger-tile__icon { color: #fff; background: linear-gradient(135deg,#7a9cf0,#9b83df); }
.trigger-tile__copy { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.trigger-tile__copy strong { overflow: hidden; color: #435473; font-size: 10px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.trigger-tile__copy small { overflow: hidden; color: #536683; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
@media (max-width: 430px) { .trigger-library__grid { grid-template-columns: 1fr; } }
</style>
