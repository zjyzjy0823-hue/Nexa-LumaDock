<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { Sparkles } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { useAuthStore } from '../../stores/auth'
import { useAgentsStore } from '../../stores/agents'

const auth = useAuthStore()
const store = useAgentsStore()
const agentSnapshots = computed(() => store.agents.slice(0, 3).map(agent => ({
  id: agent.id, name: agent.name, model: agent.model,
  status: agent.status === 'running' ? '运行中' : agent.status === 'offline' ? '已暂停' : '待连接',
  activity: Array.from({ length: 7 }, (_, index) => {
    const day = new Date(); day.setHours(0, 0, 0, 0); day.setDate(day.getDate() - (6 - index))
    return Math.min(100, agent.tasks.filter(task => new Date(task.createdAt).toDateString() === day.toDateString()).length * 25)
  }),
})))
onMounted(() => { if (auth.token) void store.load(auth.token) })

function activityPoints(values: number[]) {
  return values.map((value, index) => `${(index * 88) / Math.max(values.length - 1, 1)},${25 - value * .22}`).join(' ')
}
</script>

<template>
  <GlassCard title="智能体" class="agents-card">
    <template #action><span class="view-all">查看全部 ({{ store.agents.length }})</span></template>

    <div class="agent-list">
      <p v-if="!agentSnapshots.length" class="widget-empty">{{ store.loading ? '正在加载智能体…' : store.error || '暂无智能体，前往智能体页添加。' }}</p>
      <div v-for="agent in agentSnapshots" :key="agent.id" class="agent-row" :class="{ 'agent-row--running': agent.status === '运行中' }">
        <span class="agent-avatar agent-avatar--browser" aria-hidden="true"><Sparkles :size="23" :stroke-width="1.8" /></span>
        <span class="agent-identity">
          <strong>{{ agent.name }}</strong>
          <small>{{ agent.model }} <span aria-hidden="true">·</span> <em :class="{ 'running-text': agent.status === '运行中' }">{{ agent.status }}</em></small>
        </span>
        <i class="agent-status-dot" :class="{ 'agent-status-dot--running': agent.status === '运行中' }" :aria-label="agent.status" />
        <svg class="agent-sparkline" viewBox="0 0 88 27" preserveAspectRatio="none" :aria-label="`${agent.name} 最近的活动`" role="img"><polyline :points="activityPoints(agent.activity)" /></svg>
      </div>
    </div>
  </GlassCard>
</template>

<style scoped>
.agents-card { min-width: 0; padding: 17px 18px 10px; }
.agents-card :deep(.glass-card__title) { color: #fff; font-size: 20px; font-weight: 500; }
.agents-card :deep(.glass-card__header) { margin-bottom: 10px; }
.agents-card :deep(.glass-card__title)::after { content: '›'; display: inline-block; margin-left: 12px; font-size: 26px; font-weight: 300; line-height: .5; vertical-align: -1px; }
.view-all { color: rgba(255,255,255,.9); font-size: 13px; white-space: nowrap; }
.agent-list { display: grid; gap: 3px; }
.widget-empty { align-self: center; margin: 28px 0; color: rgba(255,255,255,.9); font-size: 12px; text-align: center; }
.agent-row { display: grid; grid-template-columns: 48px minmax(0,1fr) 9px 90px; align-items: center; gap: 8px; min-width: 0; height: 58px; padding: 5px 11px; border: 1px solid rgba(255,255,255,.37); border-radius: 15px; background: linear-gradient(105deg,rgba(248,249,255,.72),rgba(238,239,255,.61)); box-shadow: inset 0 1px rgba(255,255,255,.5); transition: transform .2s ease, background .2s ease; }
.agent-row:hover { transform: translateX(2px); background: rgba(255,255,255,.81); }
.agent-row--running { background: linear-gradient(105deg,rgba(250,250,255,.82),rgba(241,244,255,.66)); }
.agent-avatar { display: grid; width: 46px; height: 46px; place-items: center; overflow: hidden; border: 2px solid rgba(255,255,255,.63); border-radius: 50%; box-shadow: 0 2px 9px rgba(40,53,91,.17); }
.agent-avatar--lili { color: white; background: #565e87; }
.agent-avatar--coding { color: #a4a6b1; background: radial-gradient(circle at 50% 50%,#2d2f34 0 47%,#8f929c 49% 57%,#d2d5e4 59% 100%); }
.agent-avatar--browser { color: #eaf8ff; background: radial-gradient(circle at 50% 49%,#c2eaff 0 21%,#258be6 24% 58%,#98bdff 60% 100%); }
.lili-photo { width: 100%; height: 100%; object-fit: cover; object-position: center 22%; }
.agent-identity { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.agent-identity strong,.agent-identity small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-identity strong { color: #171b27; font-size: 15px; font-weight: 650; line-height: 1.15; letter-spacing: -.025em; }
.agent-identity small { color: #404558; font-size: 13px; line-height: 1.18; }
.agent-identity small span { color: #838ba0; }
.agent-identity em { color: #50576b; font-style: normal; }
.agent-identity .running-text { color: #16833f; }
.agent-status-dot { width: 9px; height: 9px; border-radius: 50%; background: #8993a9; }
.agent-status-dot--running { background: #179d54; }
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
