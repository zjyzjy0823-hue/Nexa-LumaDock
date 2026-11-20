<script setup lang="ts">
import { computed, ref } from 'vue'
import { localDateKey } from '../../services/localTime'
import { formatTokenCount } from '../../services/tokenUsage'
import type { RecordedTokenUsage } from '../../services/recordedTokenUsage'
import type { FleetUsageDay } from '../../types/fleet'

const props = defineProps<{
  dates: string[]
  records: ReadonlyMap<string, RecordedTokenUsage>
  report: FleetUsageDay[] | null
}>()
const number = new Intl.NumberFormat('zh-CN')
const segments = [
  { key: 'cached', label: '输入（命中缓存）' },
  { key: 'otherInput', label: '输入（其余）' },
  { key: 'output', label: '输出' },
  { key: 'other', label: '未细分' },
] as const
const activeDate = ref('')

const days = computed(() => {
  const byDate = new Map<string, FleetUsageDay>(props.dates.map(date => [date, {
    date, requests: 0, tokens: 0, cached: 0, otherInput: 0, output: 0, other: 0,
  }]))
  if (props.report) {
    for (const day of props.report) {
      if (byDate.has(day.date)) byDate.set(day.date, day)
    }
    return [...byDate.values()]
  }
  for (const record of props.records.values()) {
    const day = byDate.get(localDateKey(new Date(record.recordedAt).toISOString()))
    if (!day) continue
    day.requests += 1
    day.tokens += record.total
    for (const { key } of segments) day[key] += record[key]
  }
  return [...byDate.values()]
})

function plotScale(peak: number) {
  const half = Math.max(1, peak / 2)
  const unit = 10 ** Math.floor(Math.log10(half))
  const step = ([1, 2, 2.5, 5, 10].find(value => value * unit >= half) ?? 10) * unit
  return Math.ceil(step) * 2
}

const maxRequests = computed(() => plotScale(Math.max(0, ...days.value.map(day => day.requests))))
const maxTokens = computed(() => plotScale(Math.max(0, ...days.value.map(day => day.tokens))))
const totalRequests = computed(() => days.value.reduce((sum, day) => sum + day.requests, 0))
const totalTokens = computed(() => days.value.reduce((sum, day) => sum + day.tokens, 0))
const shownSegments = computed(() => segments.filter(({ key }) => key !== 'other' || days.value.some(day => day.other > 0)))

const requestLine = computed(() => {
  const points = days.value.map((day, i) => ({
    x: ((i + 0.5) * 100) / days.value.length,
    y: 100 - (day.requests / maxRequests.value) * 100,
  }))
  const first = points[0]
  const last = points.at(-1)
  if (!first || !last) return ''

  // Use a shared tangent on both sides of each point, without overshooting peaks or troughs.
  const tangents = points.map((point, i) => {
    const before = points[i - 1]
    const after = points[i + 1]
    if (!before || !after) return 0
    const left = (point.y - before.y) / (point.x - before.x)
    const right = (after.y - point.y) / (after.x - point.x)
    return left * right > 0 ? 2 * left * right / (left + right) : 0
  })
  let path = `M 0 ${first.y} H ${first.x}`
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1]!
    const b = points[i]!
    const step = (b.x - a.x) / 3
    path += ` C ${a.x + step} ${a.y + tangents[i - 1]! * step}, ${b.x - step} ${b.y - tangents[i]! * step}, ${b.x} ${b.y}`
  }
  return `${path} H 100`
})

function dateLabel(date: string) {
  const [, month, day] = date.split('-')
  return `${Number(month)}/${Number(day)}`
}

function showDate(index: number) {
  const last = days.value.length - 1
  if (!index || index === last || last <= 6) return true
  const step = Math.ceil(last / 5)
  return index % step === 0 && last - index > step / 2
}
</script>

<template>
  <div class="usage-chart">
    <header class="plot-totals">
      <div><i class="total-swatch token-otherInput"></i><strong>Tokens</strong><span class="num">{{ totalRequests ? number.format(totalTokens) : '—' }}</span></div>
      <div><i class="total-swatch request-swatch"></i><strong>已记录请求</strong><span class="num">{{ totalRequests ? number.format(totalRequests) : '—' }}</span></div>
    </header>
    <div class="usage-plot" @mouseleave="activeDate = ''">
      <div class="plot-axis" aria-hidden="true">
        <span>{{ totalRequests ? formatTokenCount(maxTokens) : '' }}</span>
        <span>{{ totalRequests ? formatTokenCount(maxTokens / 2) : '' }}</span>
        <span>0</span>
      </div>
      <div class="plot-area">
        <div class="plot-rules" aria-hidden="true"><i></i><i></i><i></i></div>
        <template v-if="totalRequests">
          <div class="plot-bars" aria-hidden="true">
            <div v-for="(day, index) in days" :key="day.date" class="plot-column">
              <span v-if="day.tokens" class="token-stack"
                :style="{ height: `${day.tokens / maxTokens * 100}%`, animationDelay: `${index * 14}ms` }">
                <i v-for="{ key } in shownSegments" v-show="day[key]" :key="key" :class="`token-${key}`"
                  :style="{ flexBasis: `${day[key] / day.tokens * 100}%` }"></i>
              </span>
            </div>
          </div>
          <svg class="request-line" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <path class="request-area-underlay" :d="requestLine" vector-effect="non-scaling-stroke" />
            <path class="request-area-stroke" :d="requestLine" vector-effect="non-scaling-stroke" />
          </svg>
          <div class="plot-days">
            <button v-for="(day, index) in days" :key="day.date" type="button" class="plot-column plot-day"
              :class="{ 'is-active': activeDate === day.date }" :tabindex="day.requests ? 0 : -1"
              :aria-label="`${day.date}，${day.requests ? `${number.format(day.tokens)} Tokens，${number.format(day.requests)} 次已记录请求` : '无记录'}`"
              @mouseenter="activeDate = day.date" @focus="activeDate = day.date" @blur="activeDate = ''"
              @click="activeDate = day.date" @keydown.esc="activeDate = ''">
              <span v-if="activeDate === day.date" class="usage-tooltip" aria-hidden="true"
                :style="{ '--cursor': `${(index + 0.5) / days.length * 100}%` }">
                <span class="tooltip-title"><b>{{ day.date }}</b><strong v-if="day.requests" class="num">{{ number.format(day.tokens) }} Tokens</strong></span>
                <template v-if="day.requests">
                  <span class="tooltip-row"><i class="request-swatch"></i><span>已记录请求</span><b class="num">{{ number.format(day.requests) }}</b></span>
                  <span v-for="{ key, label } in shownSegments" :key="key" class="tooltip-row">
                    <i :class="`token-${key}`"></i><span>{{ label }}</span><b class="num">{{ number.format(day[key]) }}</b>
                  </span>
                </template>
                <span v-else>无记录</span>
              </span>
            </button>
          </div>
        </template>
        <p v-else class="usage-empty">这段时间暂无实测用量</p>
      </div>
      <div class="plot-axis plot-axis-requests" aria-hidden="true">
        <span>{{ totalRequests ? formatTokenCount(maxRequests) : '' }}</span>
        <span>{{ totalRequests ? formatTokenCount(maxRequests / 2) : '' }}</span>
        <span>0</span>
      </div>
      <div class="plot-dates" aria-hidden="true">
        <span v-for="(day, index) in days" v-show="showDate(index)" :key="day.date"
          :style="{ left: `${(index + 0.5) / days.length * 100}%` }">{{ dateLabel(day.date) }}</span>
      </div>
    </div>
    <div v-if="totalRequests" class="token-legend" aria-label="Token 分类">
      <span v-for="{ key, label } in shownSegments" :key="key"><i :class="`token-${key}`"></i>{{ label }}</span>
    </div>
  </div>
</template>

<style scoped>
.usage-chart {
  --request-color: #000;
  --usage-cached: #d8d8d8;
  --usage-input: #7d7d7d;
  --usage-output: #202020;
  --usage-other: #999;
  --usage-surface: #fff;
  --usage-grid: #ddd;
  --usage-baseline: #c8c8c8;
  --usage-axis: #666;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
  min-height: 230px;
  padding: 14px clamp(10px, 1.1cqi, 16px) 12px;
  border-radius: var(--r-sm);
  background: var(--usage-surface);
  color: var(--request-color);
}
.plot-totals { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 6px 15px; font-size: 12px; }
.plot-totals div { display: flex; align-items: center; gap: 6px; }
.plot-totals strong { font-weight: 650; }
.plot-totals span { color: var(--usage-axis); }
.total-swatch { width: 8px; height: 8px; flex: none; border-radius: 2px; }
.request-swatch { background: var(--request-color); }
.total-swatch.request-swatch { width: 11px; height: 2px; }
.usage-plot {
  display: grid;
  flex: 1;
  grid-template: minmax(105px, 1fr) 14px / max-content minmax(0, 1fr) max-content;
  gap: 7px 9px;
  min-width: 0;
}
.plot-axis { display: flex; flex-direction: column; justify-content: space-between; margin-block: -5px; text-align: right; }
.plot-axis-requests { text-align: left; }
.plot-axis, .plot-dates { color: var(--usage-axis); font-size: 10px; line-height: 12px; font-variant-numeric: tabular-nums; }
.plot-area { position: relative; min-width: 0; }
.plot-rules, .request-line, .plot-days, .plot-bars { position: absolute; inset: 0; }
.plot-rules { display: flex; flex-direction: column; justify-content: space-between; }
.plot-rules i { border-top: 1px solid var(--usage-grid); }
.plot-rules i:last-child { border-color: var(--usage-baseline); }
.request-line {
  width: 100%;
  height: 100%;
  overflow: visible;
  pointer-events: none;
  shape-rendering: geometricPrecision;
  animation: request-reveal 460ms var(--ease-out);
}
.request-area-underlay, .request-area-stroke { fill: none; stroke-linejoin: round; stroke-linecap: round; }
.request-area-underlay { stroke: var(--usage-surface); stroke-width: 3.5; }
.request-area-stroke { stroke: var(--request-color); stroke-width: 2; }
.plot-days, .plot-bars { display: flex; }
.plot-column { display: flex; justify-content: center; align-items: end; flex: 1; min-width: 0; padding: 0; }
.plot-day { border-radius: 2px; background: transparent; }
.plot-day:focus-visible { outline: 1px solid var(--request-color); outline-offset: -1px; }
.plot-day.is-active::before { content: ''; height: 100%; border-left: 1px dashed var(--usage-baseline); position: absolute; }
.token-stack {
  display: flex;
  flex-direction: column;
  width: 62%;
  max-width: 30px;
  border-radius: 3px 3px 0 0;
  overflow: hidden;
  transform-origin: bottom;
  animation: usage-rise 460ms var(--ease-out) both;
}
.token-cached { background: var(--usage-cached); }
.token-otherInput { background: var(--usage-input); }
.token-output { background: var(--usage-output); }
.token-other { background: var(--usage-other); }
@keyframes usage-rise { from { transform: scaleY(0); opacity: .45; } to { transform: scaleY(1); opacity: 1; } }
@keyframes request-reveal { from { clip-path: inset(-4px 100% -4px -4px); } to { clip-path: inset(-4px); } }
[data-motion="reduced"] .request-line, [data-motion="reduced"] .token-stack { animation: none; }
@media (prefers-reduced-motion: reduce) { .request-line, .token-stack { animation: none; } }
.plot-dates { position: relative; grid-column: 2; }
.plot-dates span { position: absolute; transform: translateX(-50%); }
.usage-tooltip {
  position: absolute;
  z-index: 2;
  top: 8px;
  left: clamp(107px, var(--cursor), calc(100% - 107px));
  transform: translateX(-50%);
  display: grid;
  gap: 5px;
  width: min(206px, calc(100% - 8px));
  padding: 9px;
  border: 1px solid var(--usage-grid);
  border-radius: var(--r-sm);
  background: var(--usage-surface);
  box-shadow: 0 4px 14px rgba(0, 0, 0, .12);
  color: var(--usage-axis);
  font-size: 11px;
  text-align: left;
  pointer-events: none;
}
.tooltip-title, .tooltip-row { display: flex; align-items: center; gap: 5px; }
.tooltip-title { justify-content: space-between; color: var(--request-color); }
.tooltip-row b { margin-inline-start: auto; color: var(--request-color); font-weight: 500; }
.token-legend { display: flex; flex-wrap: wrap; gap: 6px 12px; }
.token-legend span { display: inline-flex; align-items: center; gap: 5px; }
.tooltip-row i, .token-legend i { width: 7px; height: 7px; border-radius: 2px; flex: none; }
.token-legend, .usage-empty { color: var(--usage-axis); font-size: 11px; }
.usage-empty { position: absolute; inset: 0; display: grid; place-items: center; margin: 0; }
</style>
