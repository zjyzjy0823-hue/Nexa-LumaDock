<script setup lang="ts">
import { computed, ref } from 'vue'
import GlassCard from '../ui/GlassCard.vue'
import type { ExpensePeriod, ExpenseTrend } from '../../types/ledger'

const props = defineProps<{ trends: ExpenseTrend[] }>()
const period = ref<ExpensePeriod>(props.trends[0]?.id ?? '30d')
const activeTrend = computed(() => props.trends.find(trend => trend.id === period.value) ?? props.trends[0]!)

const chart = computed(() => {
  const values = activeTrend.value.values
  const peak = Math.max(...values, 1)
  const step = peak <= 250 ? 50 : peak <= 1000 ? 200 : 500
  const ceiling = Math.ceil(peak * 1.15 / step) * step
  const left = 56
  const right = 601
  const top = 24
  const bottom = 213
  const points = values.map((value, index) => ({
    x: left + index * (right - left) / Math.max(values.length - 1, 1),
    y: bottom - value / ceiling * (bottom - top),
  }))
  const line = points.map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ')
  const area = points.length ? `${line} L ${points[points.length - 1]!.x.toFixed(1)} ${bottom} L ${left} ${bottom} Z` : ''
  const ticks = Array.from({ length: 5 }, (_, index) => ({
    value: ceiling * (4 - index) / 4,
    y: top + index * (bottom - top) / 4,
  }))
  const xLabels = activeTrend.value.labels
    .map((label, index) => ({ label, index, x: points[index]?.x ?? left }))
    .filter(item => values.length <= 6 || item.index % 3 === 0 || item.index === values.length - 1)
  return { line, area, ticks, xLabels, points }
})

function axisMoney(value: number) {
  return value >= 1000 ? `¥${(value / 1000).toFixed(value % 1000 === 0 ? 0 : 1)}k` : `¥${value}`
}
</script>

<template>
  <GlassCard class="finance-chart" title="支出趋势">
    <template #action>
      <div class="finance-chart__periods" role="group" aria-label="支出趋势时间范围">
        <button v-for="trend in trends" :key="trend.id" type="button" :class="{ active: period === trend.id }" :aria-pressed="period === trend.id" @click="period = trend.id">{{ trend.label }}</button>
      </div>
    </template>
    <div class="finance-chart__intro"><span class="finance-chart__eyebrow">EXPENSE TREND</span><span>{{ activeTrend.caption }}</span></div>
    <div class="finance-chart__canvas">
      <svg viewBox="0 0 620 258" preserveAspectRatio="xMidYMid meet" role="img" :aria-label="`${activeTrend.label}支出趋势折线图`">
        <defs>
          <linearGradient id="ledgerTrendStroke" x1="0" x2="1" y1="0" y2="0"><stop offset="0%" stop-color="#7ec5ef" /><stop offset="52%" stop-color="#7f97ec" /><stop offset="100%" stop-color="#a784e8" /></linearGradient>
          <linearGradient id="ledgerTrendFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#8d9deb" stop-opacity=".36" /><stop offset="100%" stop-color="#8d9deb" stop-opacity="0" /></linearGradient>
        </defs>
        <g v-for="tick in chart.ticks" :key="tick.y"><line x1="56" x2="601" :y1="tick.y" :y2="tick.y" class="finance-chart__grid" /><text x="43" :y="tick.y + 4" text-anchor="end" class="finance-chart__axis">{{ axisMoney(tick.value) }}</text></g>
        <path v-if="chart.area" :d="chart.area" fill="url(#ledgerTrendFill)" />
        <path v-if="chart.line" :d="chart.line" fill="none" stroke="url(#ledgerTrendStroke)" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" />
        <circle v-for="(point, index) in chart.points" :key="index" :cx="point.x" :cy="point.y" r="3.6" fill="#fff" stroke="#849be9" stroke-width="2" />
        <text v-for="item in chart.xLabels" :key="item.index" :x="item.x" y="245" :text-anchor="item.index === 0 ? 'start' : item.index === chart.points.length - 1 ? 'end' : 'middle'" class="finance-chart__axis">{{ item.label }}</text>
      </svg>
    </div>
  </GlassCard>
</template>

<style scoped>
.finance-chart { min-height:340px; }
.finance-chart :deep(.glass-card__body) { overflow:visible; }
.finance-chart__periods { display:flex; gap:3px; padding:3px; border:1px solid rgba(255,255,255,.37); border-radius:11px; background:rgba(255,255,255,.15); box-shadow:inset 0 1px rgba(255,255,255,.22); }
.finance-chart__periods button { min-width:47px; padding:6px 9px; color:rgba(255,255,255,.84); border:0; border-radius:8px; background:transparent; font-size:11px; font-weight:650; white-space:nowrap; transition:background .18s,color .18s,box-shadow .18s; }
.finance-chart__periods button:hover { color:#3f5b91; background:rgba(255,255,255,.58); }
.finance-chart__periods button.active { color:#3f5b91; background:rgba(255,255,255,.76); box-shadow:0 2px 8px rgba(50,73,122,.11); }
.finance-chart__intro { display:flex; align-items:center; gap:10px; color:rgba(255,255,255,.88); font-size:11px; text-shadow:0 1px 8px rgba(24,36,78,.25); }
.finance-chart__eyebrow { color:rgba(255,255,255,.95); font-size:9px; font-weight:800; letter-spacing:.13em; }
.finance-chart__canvas { width:100%; min-height:244px; margin-top:8px; border:var(--glass-tile-border); border-radius:15px; background:var(--ledger-tile-background,var(--glass-tile-background)); box-shadow:var(--glass-tile-shadow); backdrop-filter:blur(12px) saturate(120%); -webkit-backdrop-filter:blur(12px) saturate(120%); }
.finance-chart__canvas svg { display:block; width:100%; height:auto; min-height:244px; overflow:visible; }
.finance-chart__grid { stroke:rgba(74,98,148,.31); stroke-dasharray:4 6; }
.finance-chart__axis { fill:#3d5578; font-family:inherit; font-size:11px; font-weight:650; }
@media (max-width:650px) { .finance-chart :deep(.glass-card__header) { align-items:flex-start; flex-direction:column; } .finance-chart__periods { align-self:flex-start; } }
@media (max-width:420px) { .finance-chart { padding:15px; } .finance-chart__canvas { min-height:205px; } .finance-chart__canvas svg { min-height:205px; } }
</style>
