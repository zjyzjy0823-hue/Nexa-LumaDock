<script setup lang="ts">
import { computed, ref } from 'vue'
import OpusIcon from '../ui/OpusIcon.vue'
import OpusSegment from '../ui/OpusSegment.vue'
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
  <section class="card mat finance-chart">
    <h2 class="card-h">
      <OpusIcon name="ledger" /> 支出趋势 · {{ activeTrend.caption }}
      <span class="spacer"></span>
      <OpusSegment role="group" aria-label="支出趋势时间范围">
        <button v-for="trend in trends" :key="trend.id" type="button" :aria-pressed="period === trend.id" @click="period = trend.id">{{ trend.label }}</button>
      </OpusSegment>
    </h2>
    <div class="finance-chart__canvas">
      <svg viewBox="0 0 620 258" preserveAspectRatio="xMidYMid meet" role="img" :aria-label="`${activeTrend.label}支出趋势折线图`">
        <defs>
          <linearGradient id="ledgerTrendFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="var(--accent)" stop-opacity=".26" /><stop offset="100%" stop-color="var(--accent)" stop-opacity="0" /></linearGradient>
        </defs>
        <g v-for="tick in chart.ticks" :key="tick.y"><line x1="56" x2="601" :y1="tick.y" :y2="tick.y" class="finance-chart__grid" /><text x="43" :y="tick.y + 4" text-anchor="end" class="finance-chart__axis num">{{ axisMoney(tick.value) }}</text></g>
        <path v-if="chart.area" :d="chart.area" fill="url(#ledgerTrendFill)" />
        <path v-if="chart.line" :d="chart.line" fill="none" stroke="var(--accent)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
        <circle v-for="(point, index) in chart.points" :key="index" :cx="point.x" :cy="point.y" r="3.6" fill="var(--solid)" stroke="var(--accent)" stroke-width="2" />
        <text v-for="item in chart.xLabels" :key="item.index" :x="item.x" y="245" :text-anchor="item.index === 0 ? 'start' : item.index === chart.points.length - 1 ? 'end' : 'middle'" class="finance-chart__axis">{{ item.label }}</text>
      </svg>
    </div>
  </section>
</template>

<style scoped>
.finance-chart { min-height: 320px; }
.finance-chart__canvas { width: 100%; min-height: 244px; margin-top: 8px; padding: 12px 8px 4px; border-radius: var(--r-md); background: var(--solid); box-shadow: var(--shadow-1); }
.finance-chart__canvas svg { display: block; width: 100%; height: auto; min-height: 244px; overflow: visible; }
.finance-chart__grid { stroke: var(--line); stroke-dasharray: 4 6; }
.finance-chart__axis { fill: var(--text-3); font-family: inherit; font-size: 11px; font-weight: 550; }
@media (max-width: 650px) { .finance-chart .card-h { flex-wrap: wrap; } }
@media (max-width: 420px) { .finance-chart__canvas, .finance-chart__canvas svg { min-height: 205px; } }
</style>
