<script setup lang="ts">
import { computed } from 'vue'
import GlassCard from '../ui/GlassCard.vue'
import type { ApiUsagePoint } from '../../types/api'

const props = defineProps<{ points: ApiUsagePoint[] }>()
const chart = computed(() => {
  const points = props.points
  if (!points.length) return { requests: '', errors: '', area: '', requestAxis: '0', errorAxis: '0', days: [] as { x: number; label: string }[] }
  const left = 32
  const right = 320
  const bottom = 133
  const height = 107
  const maxRequests = Math.ceil(Math.max(...points.map(point => point.requests)) / 500) * 500
  const maxErrors = Math.ceil(Math.max(...points.map(point => point.errors)) / 5) * 5
  const x = (index: number) => left + (right - left) * index / Math.max(1, points.length - 1)
  const requests = points.map((point, index) => `${x(index)},${bottom - point.requests / maxRequests * height}`).join(' ')
  const errors = points.map((point, index) => `${x(index)},${bottom - point.errors / maxErrors * height}`).join(' ')
  const area = `M ${left},${bottom} L ${requests.replaceAll(' ', ' L ')} L ${right},${bottom} Z`
  return { requests, errors, area, requestAxis: `${maxRequests / 1000}k`, errorAxis: String(maxErrors), days: points.map((point, index) => ({ x: x(index), label: point.day })) }
})
const latest = computed(() => props.points.at(-1))
</script>

<template>
  <GlassCard class="api-usage-chart" title="API 使用情况">
    <template #action><span class="api-usage-chart__range">最近 7 天</span></template>
    <div class="api-usage-chart__summary">
      <div><span class="api-usage-chart__dot api-usage-chart__dot--requests" />Requests <strong>{{ latest?.requests.toLocaleString() ?? '—' }}</strong></div>
      <div><span class="api-usage-chart__dot api-usage-chart__dot--errors" />Errors <strong>{{ latest?.errors ?? '—' }}</strong></div>
    </div>
    <svg class="api-usage-chart__plot" viewBox="0 0 350 164" role="img" aria-label="最近 7 天的 API 请求数和错误数趋势，左右两侧分别为独立刻度">
      <defs><linearGradient id="api-usage-area" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#8da5ef" stop-opacity=".52" /><stop offset="100%" stop-color="#8da5ef" stop-opacity=".02" /></linearGradient></defs>
      <line v-for="y in [26, 79, 133]" :key="y" x1="32" x2="320" :y1="y" :y2="y" class="api-usage-chart__grid" />
      <text x="0" y="30" class="api-usage-chart__axis">{{ chart.requestAxis }}</text><text x="13" y="137" class="api-usage-chart__axis">0</text>
      <text x="329" y="30" class="api-usage-chart__axis">{{ chart.errorAxis }}</text><text x="331" y="137" class="api-usage-chart__axis">0</text>
      <path v-if="points.length" :d="chart.area" fill="url(#api-usage-area)" />
      <polyline v-if="points.length" :points="chart.requests" class="api-usage-chart__line api-usage-chart__line--requests" />
      <polyline v-if="points.length" :points="chart.errors" class="api-usage-chart__line api-usage-chart__line--errors" />
      <text v-for="day in chart.days" :key="day.x" :x="day.x" y="157" text-anchor="middle" class="api-usage-chart__day">{{ day.label }}</text>
    </svg>
  </GlassCard>
</template>

<style scoped>
.api-usage-chart { min-height:261px; }
.api-usage-chart :deep(.glass-card__body) { overflow:visible; }
.api-usage-chart__range { padding:5px 8px; border:1px solid rgba(255,255,255,.4); border-radius:7px; color:rgba(255,255,255,.88); background:rgba(255,255,255,.14); font-size:9px; font-weight:650; white-space:nowrap; }
.api-usage-chart__summary { display:flex; gap:13px; margin:4px 0 8px; }
.api-usage-chart__summary div { display:flex; align-items:center; gap:5px; min-width:0; color:rgba(255,255,255,.78); font-size:9px; white-space:nowrap; }
.api-usage-chart__summary strong { margin-left:2px; color:white; font-size:12px; font-weight:740; }
.api-usage-chart__dot { width:6px; height:6px; flex:none; border-radius:50%; }
.api-usage-chart__dot--requests { background:#9bb1fa; }.api-usage-chart__dot--errors { background:#f3a5b2; }
.api-usage-chart__plot { display:block; width:100%; max-height:180px; overflow:visible; }
.api-usage-chart__grid { stroke:rgba(255,255,255,.27); stroke-width:1; stroke-dasharray:3 5; }
.api-usage-chart__axis,.api-usage-chart__day { fill:rgba(255,255,255,.69); font-family:inherit; font-size:9px; }
.api-usage-chart__line { fill:none; stroke-width:2.3; stroke-linecap:round; stroke-linejoin:round; vector-effect:non-scaling-stroke; filter:drop-shadow(0 2px 3px rgba(37,54,105,.15)); }
.api-usage-chart__line--requests { stroke:#b1c2ff; }.api-usage-chart__line--errors { stroke:#ffafbc; }
</style>
