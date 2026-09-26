<script setup lang="ts">
import { computed } from 'vue'
import { Activity, CheckCircle2, Clock3, Database, TrendingUp } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import type { DataOverview } from '../../mock/data'

const props = defineProps<{ totalRecords: number; overview: DataOverview }>()

const stats = computed(() => [
  { label: 'Total Records', value: props.totalRecords, detail: '全部数据条目', icon: Database, tone: 'blue' },
  { label: 'Active', value: props.overview.active, detail: '正在进行', icon: Activity, tone: 'mint' },
  { label: 'Completed', value: props.overview.completed, detail: '已完成事项', icon: CheckCircle2, tone: 'violet' },
  { label: 'Recent Activity', value: props.overview.recentActivity, detail: '本周更新', icon: Clock3, tone: 'amber' },
])

const chartPoints = computed(() => {
  const values = props.overview.trend
  if (!values.length) return []
  const low = Math.min(...values) - 4
  const span = Math.max(...values) - low + 4 || 1
  return values.map((value, index) => ({
    x: Math.round(index * 300 / Math.max(values.length - 1, 1)),
    y: Math.round(78 - (value - low) / span * 58),
  }))
})
const linePoints = computed(() => chartPoints.value.map(point => `${point.x},${point.y}`).join(' '))
const areaPath = computed(() => chartPoints.value.length
  ? `M 0 88 L ${chartPoints.value.map(point => `${point.x} ${point.y}`).join(' L ')} L 300 88 Z`
  : '')
const lastPoint = computed(() => chartPoints.value.at(-1))
</script>

<template>
  <GlassCard class="data-stats" title="数据概览">
    <template #action><span class="data-stats__period">最近 30 天</span></template>
    <div class="data-stats__grid">
      <div v-for="item in stats" :key="item.label" class="data-stats__metric" :class="`data-stats__metric--${item.tone}`">
        <span class="data-stats__metric-icon"><component :is="item.icon" :size="15" :stroke-width="1.9" /></span>
        <span class="data-stats__metric-label">{{ item.label }}</span>
        <strong>{{ item.value }}</strong>
        <small>{{ item.detail }}</small>
      </div>
    </div>
    <div class="data-stats__chart-head"><div><span>记录增长趋势</span><strong>持续增长 <TrendingUp :size="13" /></strong></div><span>+12.4%</span></div>
    <svg class="data-stats__chart" viewBox="0 0 300 90" preserveAspectRatio="none" role="img" aria-label="最近 30 天记录数量呈增长趋势">
      <defs><linearGradient id="data-stats-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#788fee" stop-opacity=".3" /><stop offset="1" stop-color="#788fee" stop-opacity="0" /></linearGradient></defs>
      <path v-for="y in [22, 48, 74]" :key="y" :d="`M 0 ${y} H 300`" class="data-stats__gridline" />
      <path :d="areaPath" fill="url(#data-stats-fill)" />
      <polyline :points="linePoints" fill="none" stroke="#708aea" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke" />
      <circle v-if="lastPoint" :cx="lastPoint.x" :cy="lastPoint.y" r="4.5" fill="#fff" stroke="#708aea" stroke-width="2.4" />
    </svg>
    <div class="data-stats__chart-labels"><span v-for="label in overview.trendLabels" :key="label">{{ label }}</span></div>
    <div class="data-stats__activity-head"><h3>最近动态</h3><span>实时同步</span></div>
    <div class="data-stats__activity-list">
      <div v-for="activity in overview.activities" :key="activity.id" class="data-stats__activity" :class="`data-stats__activity--${activity.tone}`">
        <span class="data-stats__activity-dot" />
        <div><strong>{{ activity.title }}</strong><span>{{ activity.detail }}</span></div>
        <time>{{ activity.time }}</time>
      </div>
    </div>
  </GlassCard>
</template>

<style scoped>
.data-stats { height:auto; min-height:475px; }
.data-stats__period { color:rgba(255,255,255,.8); font-size:10px; }
.data-stats__grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; }
.data-stats__metric { display:grid; grid-template-columns:25px minmax(0,1fr); align-items:center; gap:3px 7px; min-width:0; min-height:70px; padding:10px; border:var(--glass-tile-border); border-radius:12px; background:linear-gradient(140deg,rgba(250,251,255,.56),rgba(235,239,255,.34)); box-shadow:var(--glass-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); --metric:#6b86e4; }
.data-stats__metric--mint { --metric:#3ead95; }
.data-stats__metric--violet { --metric:#956fd7; }
.data-stats__metric--amber { --metric:#d39d4c; }
.data-stats__metric-icon { display:grid; width:25px; height:25px; grid-row:span 2; place-items:center; border-radius:8px; color:var(--metric); background:color-mix(in srgb,var(--metric) 13%,white); }
.data-stats__metric-label { overflow:hidden; color:#596c89; font-size:10px; font-weight:650; text-overflow:ellipsis; white-space:nowrap; }
.data-stats__metric strong { grid-column:2; color:#2b3c59; font-size:20px; line-height:1; font-weight:750; }
.data-stats__metric small { grid-column:2; color:#6e7f99; font-size:9px; white-space:nowrap; }
.data-stats__chart-head { display:flex; justify-content:space-between; align-items:end; gap:10px; margin-top:18px; }
.data-stats__chart-head div { display:flex; flex-direction:column; gap:5px; }
.data-stats__chart-head div > span { color:#fff; font-size:12px; font-weight:690; text-shadow:0 1px 8px rgba(20,33,71,.25); }
.data-stats__chart-head strong { display:flex; align-items:center; gap:4px; color:#55a88e; font-size:10px; font-weight:650; }
.data-stats__chart-head > span { color:#55a88e; font-size:12px; font-weight:740; }
.data-stats__chart { display:block; width:100%; height:82px; margin-top:5px; overflow:visible; }
.data-stats__gridline { fill:none; stroke:rgba(118,145,190,.16); stroke-dasharray:3 5; stroke-width:1; }
.data-stats__chart-labels { display:flex; justify-content:space-between; margin-top:1px; color:rgba(255,255,255,.72); font-size:9px; }
.data-stats__activity-head { display:flex; justify-content:space-between; align-items:center; gap:8px; margin-top:17px; padding-top:13px; border-top:1px solid rgba(128,151,193,.19); }
.data-stats__activity-head h3 { margin:0; color:#fff; font-size:12px; text-shadow:0 1px 8px rgba(20,33,71,.25); }
.data-stats__activity-head > span { color:rgba(255,255,255,.72); font-size:9px; }
.data-stats__activity-list { display:grid; gap:2px; margin-top:6px; }
.data-stats__activity { display:flex; align-items:center; gap:9px; min-height:34px; }
.data-stats__activity-dot { width:7px; height:7px; flex:none; border-radius:50%; background:#708aea; box-shadow:0 0 0 4px rgba(112,138,234,.13); }
.data-stats__activity--violet .data-stats__activity-dot { background:#a17add; box-shadow:0 0 0 4px rgba(161,122,221,.13); }
.data-stats__activity--rose .data-stats__activity-dot { background:#cf86a3; box-shadow:0 0 0 4px rgba(207,134,163,.13); }
.data-stats__activity--mint .data-stats__activity-dot { background:#54b49b; box-shadow:0 0 0 4px rgba(84,180,155,.13); }
.data-stats__activity--cyan .data-stats__activity-dot { background:#5aa9c2; box-shadow:0 0 0 4px rgba(90,169,194,.13); }
.data-stats__activity--amber .data-stats__activity-dot { background:#d39d4c; box-shadow:0 0 0 4px rgba(211,157,76,.13); }
.data-stats__activity div { display:flex; flex:1; flex-direction:column; gap:2px; min-width:0; }
.data-stats__activity strong { overflow:hidden; color:rgba(255,255,255,.96); font-size:10px; text-overflow:ellipsis; white-space:nowrap; }
.data-stats__activity div span { overflow:hidden; color:rgba(255,255,255,.73); font-size:9px; text-overflow:ellipsis; white-space:nowrap; }
.data-stats__activity time { flex:none; color:rgba(255,255,255,.7); font-size:9px; }
@media (max-width:420px) { .data-stats__metric { padding:8px; } .data-stats__metric-label { font-size:9px; } }
</style>
