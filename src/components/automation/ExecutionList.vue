<script setup lang="ts">
import { Check, Clock3, X } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import type { ExecutionItem } from '../../mock/automation'

defineProps<{ executions: ExecutionItem[] }>()
</script>

<template>
  <GlassCard class="execution-panel">
    <div class="execution-panel__heading"><div><span class="execution-panel__eyebrow">ACTIVITY LOG</span><h2>执行记录</h2></div><span class="execution-panel__count">最近 {{ executions.length }} 次</span></div>
    <div class="execution-list">
      <div v-for="item in executions" :key="item.id" class="execution-row">
        <span class="execution-row__icon" :class="`execution-row__icon--${item.status}`"><Check v-if="item.status === 'success'" :size="15" /><X v-else :size="15" /></span>
        <div class="execution-row__copy"><strong>{{ item.title }}</strong><small>{{ item.description }}</small></div>
        <div class="execution-row__meta"><span :class="`execution-row__status--${item.status}`">{{ item.status === 'success' ? '成功' : '失败' }}</span><time><Clock3 :size="11" />{{ item.time }}</time></div>
      </div>
    </div>
  </GlassCard>
</template>

<style scoped>
.execution-panel { min-height: 280px; }
.execution-panel :deep(.glass-card__body) { overflow: visible; }
.execution-panel__heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; }
.execution-panel__eyebrow { color: var(--workbench-muted); font-size: 9px; font-weight: 760; letter-spacing: .14em; }
.execution-panel__heading h2 { margin: 5px 0 0; color: var(--workbench-text); font-size: 16px; letter-spacing: -.03em; text-shadow: none; }
.execution-panel__count { padding-bottom: 2px; color: var(--workbench-muted); font-size: 10px; }
.execution-list { display: grid; gap: 7px; margin-top: 12px; }
.execution-row { display: flex; align-items: center; gap: 10px; min-height: 49px; padding: 7px 9px; border: var(--glass-tile-border); border-radius: 12px; background: var(--glass-tile-background); box-shadow: var(--glass-tile-shadow); backdrop-filter: var(--workbench-material); -webkit-backdrop-filter: var(--workbench-material); }
.execution-row__icon { display: grid; width: 28px; height: 28px; flex: none; place-items: center; border-radius: 9px; color: var(--workbench-good); background: var(--workbench-muted-surface); }
.execution-row__icon--failed { color: var(--workbench-danger); background: var(--workbench-muted-surface); }
.execution-row__copy { display: flex; flex: 1; flex-direction: column; gap: 3px; min-width: 0; }
.execution-row__copy strong { overflow: hidden; color: var(--workbench-text); font-size: 12px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.execution-row__copy small { overflow: hidden; color: var(--workbench-muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.execution-row__meta { display: flex; align-items: flex-end; flex-direction: column; gap: 3px; white-space: nowrap; }
.execution-row__meta > span { font-size: 10px; font-weight: 700; }
.execution-row__status--success { color: var(--workbench-good); }
.execution-row__status--failed { color: var(--workbench-danger); }
.execution-row__meta time { display: flex; align-items: center; gap: 3px; color: var(--workbench-muted); font-size: 10px; }
@media (max-width: 460px) { .execution-row__copy small { max-width: 175px; } }
</style>
