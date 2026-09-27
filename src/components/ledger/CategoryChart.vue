<script setup lang="ts">
import { computed } from 'vue'
import GlassCard from '../ui/GlassCard.vue'
import type { SpendingCategory } from '../../types/ledger'

const props = defineProps<{ categories: SpendingCategory[] }>()
const total = computed(() => props.categories.reduce((sum, category) => sum + category.amount, 0))
const circumference = 2 * Math.PI * 69
const segments = computed(() => {
  let used = 0
  return props.categories.map(category => {
    const length = total.value ? category.amount / total.value * circumference : 0
    const segment = { ...category, dash: `${Math.max(length - 3, 0)} ${circumference}`, offset: -used, percent: total.value ? Math.round(category.amount / total.value * 100) : 0 }
    used += length
    return segment
  })
})
const money = (amount: number) => `¥${amount.toLocaleString('zh-CN')}`
</script>

<template>
  <GlassCard class="category-chart" title="分类分析">
    <template #action><span class="category-chart__period">本月支出</span></template>
    <div class="category-chart__content">
      <div class="category-chart__ring" role="img" :aria-label="`本月支出分类环形图，总计${money(total)}`">
        <svg viewBox="0 0 200 200" aria-hidden="true">
          <circle cx="100" cy="100" r="69" fill="none" stroke="rgba(255,255,255,.48)" stroke-width="28" />
          <circle v-for="segment in segments" :key="segment.id" cx="100" cy="100" r="69" fill="none" :stroke="segment.color" stroke-width="28" :stroke-dasharray="segment.dash" :stroke-dashoffset="segment.offset" transform="rotate(-90 100 100)" stroke-linecap="round" />
        </svg>
        <div class="category-chart__center"><span>总支出</span><strong>{{ money(total) }}</strong></div>
      </div>
      <div class="category-chart__legend">
        <div v-for="segment in segments" :key="segment.id" class="category-chart__item">
          <span class="category-chart__dot" :style="{ background: segment.color }" />
          <span class="category-chart__name">{{ segment.name }}</span>
          <strong>{{ money(segment.amount) }}</strong>
          <small>{{ segment.percent }}%</small>
        </div>
      </div>
    </div>
  </GlassCard>
</template>

<style scoped>
.category-chart { min-height:340px; }
.category-chart :deep(.glass-card__body) { display:flex; align-items:center; overflow:visible; }
.category-chart__period { padding:6px 9px; border:1px solid rgba(255,255,255,.37); border-radius:9px; color:rgba(255,255,255,.93); background:rgba(255,255,255,.15); box-shadow:inset 0 1px rgba(255,255,255,.22); font-size:10px; font-weight:700; white-space:nowrap; }
.category-chart__content { display:grid; grid-template-columns:minmax(130px,.9fr) minmax(150px,1fr); align-items:center; gap:10px; width:100%; padding:12px; border:var(--glass-tile-border); border-radius:15px; background:var(--ledger-tile-background,var(--glass-tile-background)); box-shadow:var(--glass-tile-shadow); backdrop-filter:blur(12px) saturate(120%); -webkit-backdrop-filter:blur(12px) saturate(120%); }
.category-chart__ring { position:relative; width:min(100%,205px); aspect-ratio:1; margin:auto; }
.category-chart__ring svg { display:block; width:100%; height:100%; filter:drop-shadow(0 8px 8px rgba(74,92,153,.13)); }
.category-chart__center { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:4px; color:#405879; font-size:11px; }
.category-chart__center strong { color:#273857; font-size:clamp(16px,1.6vw,21px); font-weight:750; letter-spacing:-.04em; font-variant-numeric:tabular-nums; }
.category-chart__legend { display:grid; gap:7px; }
.category-chart__item { display:grid; grid-template-columns:8px minmax(35px,1fr) auto 27px; align-items:center; gap:6px; min-height:24px; color:#304866; font-size:11px; }
.category-chart__dot { width:7px; height:7px; border-radius:50%; box-shadow:0 0 0 3px rgba(255,255,255,.35); }
.category-chart__name { white-space:nowrap; }
.category-chart__item strong { color:#2d4164; font-size:11px; font-weight:700; font-variant-numeric:tabular-nums; white-space:nowrap; }
.category-chart__item small { color:#526b8b; font-size:10px; text-align:right; font-variant-numeric:tabular-nums; }
@media (max-width:1250px) { .category-chart__content { grid-template-columns:1fr; gap:4px; } .category-chart__ring { width:165px; } .category-chart__legend { grid-template-columns:repeat(2,minmax(0,1fr)); gap:4px 10px; } .category-chart__item { grid-template-columns:8px minmax(30px,1fr) auto; } .category-chart__item small { display:none; } }
@media (max-width:850px) { .category-chart__content { grid-template-columns:minmax(130px,.9fr) minmax(150px,1fr); gap:10px; } .category-chart__ring { width:min(100%,205px); } .category-chart__legend { grid-template-columns:1fr; } .category-chart__item { grid-template-columns:8px minmax(35px,1fr) auto 27px; } .category-chart__item small { display:block; } }
@media (max-width:450px) { .category-chart__content { grid-template-columns:1fr; } .category-chart__ring { width:180px; } .category-chart__legend { grid-template-columns:repeat(2,minmax(0,1fr)); gap:5px 9px; } .category-chart__item { grid-template-columns:8px minmax(28px,1fr) auto; } .category-chart__item small { display:none; } }
</style>
