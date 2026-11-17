<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { Sparkles } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { useAuthStore } from '../../stores/auth'
import { useAgentsStore } from '../../stores/agents'

const auth = useAuthStore()
const store = useAgentsStore()
let pollTimer: ReturnType<typeof setInterval> | undefined
const counts = computed(() => ({ running: store.agents.filter(item => item.status === 'running').length,
  idle: store.agents.filter(item => item.status === 'idle').length,
  offline: store.agents.filter(item => item.status === 'offline' || item.status === 'disabled').length,
  enabled: store.agents.filter(item => item.enabled).length }))
const agentSnapshots = computed(() => store.agents.slice(0, 3).map(agent => ({
  id: agent.id, name: agent.name, model: agent.model,
  status: agent.status === 'running' ? '运行中' : agent.status === 'disabled' ? '已停用' : agent.status === 'offline' ? '离线' : agent.status === 'error' ? '错误' : '空闲',
  enabled: agent.enabled,
  latestTask: agent.tasks[0]?.title,
  activity: Array.from({ length: 7 }, (_, index) => {
    const day = new Date(); day.setHours(0, 0, 0, 0); day.setDate(day.getDate() - (6 - index))
    return Math.min(100, agent.tasks.filter(task => new Date(task.createdAt).toDateString() === day.toDateString()).length * 25)
  }),
})))
onMounted(() => {
  if (auth.token) void store.load(auth.token)
  pollTimer = setInterval(() => { if (auth.token) void store.load(auth.token, true) }, 30_000)
})
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })

function activityPoints(values: number[]) {
  return values.map((value, index) => `${(index * 88) / Math.max(values.length - 1, 1)},${25 - value * .22}`).join(' ')
}
</script>

<template>
  <GlassCard title="智能体" class="agents-card">
    <template #action><span class="view-all">{{ store.loadedAt ? `${store.agents.length} 个 · 运行 ${counts.running} · 空闲 ${counts.idle} · 离线 ${counts.offline} · 启用 ${counts.enabled}` : '—' }}</span></template>

    <div class="agent-list">
      <p v-if="store.error" class="widget-empty" role="alert">数据加载失败 <button type="button" @click="auth.token && store.load(auth.token, true)">重试</button></p>
      <p v-else-if="!agentSnapshots.length" class="widget-empty">{{ !store.loadedAt ? '正在加载智能体…' : '还没有智能体' }}</p>
      <div v-for="agent in agentSnapshots" :key="agent.id" class="agent-row" :class="{ 'agent-row--running': agent.status === '运行中' }">
        <span class="agent-avatar agent-avatar--browser" aria-hidden="true"><Sparkles :size="23" :stroke-width="1.8" /></span>
        <span class="agent-identity">
          <strong>{{ agent.name }}</strong>
          <small>{{ agent.latestTask || agent.model }} <span aria-hidden="true">·</span> <em :class="{ 'running-text': agent.status === '运行中' }">{{ agent.status }}</em></small>
        </span>
        <i class="agent-status-dot" :class="{ 'agent-status-dot--running': agent.status === '运行中' }" :aria-label="agent.status" />
        <svg v-if="agent.activity.some(value => value > 0)" class="agent-sparkline" viewBox="0 0 88 27" preserveAspectRatio="none" :aria-label="`${agent.name} 最近的任务`" role="img"><polyline :points="activityPoints(agent.activity)" /></svg>
      </div>
    </div>
  </GlassCard>
</template>

<style scoped>
.agents-card { min-width: 0; padding: 17px 18px 10px; }
.agents-card :deep(.glass-card__title) { color: var(--workbench-text); font-size: 20px; font-weight: 500; }
.agents-card :deep(.glass-card__header) { margin-bottom: 10px; }
.agents-card :deep(.glass-card__title)::after { content: '›'; display: inline-block; margin-left: 12px; font-size: 26px; font-weight: 300; line-height: .5; vertical-align: -1px; }
.view-all { color: var(--workbench-text); font-size: 13px; white-space: nowrap; }
.agent-list { display: grid; gap: 3px; }
.widget-empty { align-self: center; margin: 28px 0; color: var(--workbench-text); font-size: 12px; text-align: center; }
.agent-row { display: grid; grid-template-columns: 48px minmax(0,1fr) 9px 90px; align-items: center; gap: 8px; min-width: 0; height: 58px; padding: 5px 11px; border: 1px solid var(--workbench-line); border-radius: 15px; background: var(--workbench-solid); box-shadow: inset 0 1px rgba(255,255,255,.5); transition: transform .2s ease, background .2s ease; }
.agent-row:hover { transform: translateX(2px); background: var(--workbench-soft); }
.agent-row--running { background: var(--workbench-solid); }
.agent-avatar { display: grid; width: 46px; height: 46px; place-items: center; overflow: hidden; border: 2px solid var(--workbench-line); border-radius: 50%; box-shadow: 0 2px 9px rgba(40,53,91,.17); }
.agent-avatar--lili { color: var(--workbench-text); background: var(--workbench-solid); }
.agent-avatar--coding { color: var(--workbench-muted); background: var(--workbench-solid); }
.agent-avatar--browser { color: var(--workbench-text); background: var(--workbench-solid); }
.lili-photo { width: 100%; height: 100%; object-fit: cover; object-position: center 22%; }
.agent-identity { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.agent-identity strong,.agent-identity small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-identity strong { color: var(--workbench-text); font-size: 15px; font-weight: 650; line-height: 1.15; letter-spacing: -.025em; }
.agent-identity small { color: var(--workbench-muted); font-size: 13px; line-height: 1.18; }
.agent-identity small span { color: var(--workbench-muted); }
.agent-identity em { color: var(--workbench-muted); font-style: normal; }
.agent-identity .running-text { color: var(--workbench-good); }
.agent-status-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--workbench-solid); }
.agent-status-dot--running { background: var(--workbench-muted-surface); }
.agent-sparkline { width: 90px; height: 28px; overflow: visible; }
.agent-sparkline polyline { fill: none; stroke: #537aff; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; filter: drop-shadow(0 1px 2px rgba(80,105,239,.25)); }
.agent-row:not(.agent-row--running) .agent-sparkline polyline { stroke: #9785ee; opacity: .85; }
@container (max-width: 340px) {
  .agent-row { grid-template-columns: 38px minmax(0, 1fr) 8px; gap: 6px; padding-inline: 7px; }
  .agent-avatar { width: 36px; height: 36px; }
  .agent-sparkline { display: none; }
  .agent-identity strong { font-size: 12px; }
  .agent-identity small { font-size: 10px; }
  .view-all { font-size: 11px; }
}
@container (max-height: 230px) {
  .agents-card { padding: 12px 13px 9px; }
  .agents-card :deep(.glass-card__header) { margin-bottom: 6px; }
  .agent-row { height: 42px; }
  .agent-avatar { width: 34px; height: 34px; }
  .agent-list { gap: 3px; }
}
@media (max-width: 470px) { .agent-row { grid-template-columns: 41px minmax(0,1fr) 8px 67px; gap: 6px; padding-inline: 7px; } .agent-avatar { width: 40px; height: 40px; } .agent-sparkline { width: 67px; } .agent-identity strong { font-size: 13px; } .agent-identity small { font-size: 11px; } }
</style>
