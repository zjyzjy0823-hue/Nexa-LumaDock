<script setup lang="ts">
import { Gauge, Lightbulb, Sparkles, TrendingUp } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import type { InsightTone, LedgerInsight } from '../../mock/ledger'

defineProps<{ insights: LedgerInsight[] }>()

const icons = { violet: TrendingUp, blue: Lightbulb, amber: Gauge } satisfies Record<InsightTone, unknown>
</script>

<template>
  <GlassCard class="insight-card" title="AI 洞察">
    <template #action><span class="insight-card__spark"><Sparkles :size="15" />NEXA INSIGHT</span></template>
    <p class="insight-card__intro">根据本月账本，为你整理值得关注的变化。</p>
    <div class="insight-card__items">
      <div v-for="insight in insights" :key="insight.id" class="insight-card__item" :class="`insight-card__item--${insight.tone}`">
        <span class="insight-card__icon"><component :is="icons[insight.tone]" :size="17" :stroke-width="1.9" /></span>
        <span class="insight-card__copy"><strong>{{ insight.title }}</strong><small>{{ insight.detail }}</small></span>
      </div>
    </div>
  </GlassCard>
</template>

<style scoped>
.insight-card { min-height:398px; }
.insight-card :deep(.glass-card__body) { overflow:visible; }
.insight-card__spark { display:inline-flex; align-items:center; gap:5px; color:rgba(255,255,255,.88); font-size:9px; font-weight:790; letter-spacing:.09em; white-space:nowrap; }
.insight-card__intro { margin:1px 0 12px; color:rgba(255,255,255,.88); font-size:11px; line-height:1.5; text-shadow:0 1px 8px rgba(24,36,78,.25); }
.insight-card__items { display:grid; gap:9px; }
.insight-card__item { display:flex; align-items:flex-start; gap:10px; min-height:80px; padding:12px; border:var(--glass-tile-border); border-radius:13px; background:var(--ledger-tile-background,var(--glass-tile-background)); box-shadow:var(--glass-tile-shadow); backdrop-filter:blur(12px) saturate(120%); -webkit-backdrop-filter:blur(12px) saturate(120%); transition:background .2s,transform .2s; }
.insight-card__item:hover { background:var(--ledger-tile-hover-background,var(--glass-tile-hover-background)); transform:translateY(-2px); }
.insight-card__item--violet { --insight-color:#9373d7; --insight-background:rgba(179,153,236,.19); }
.insight-card__item--blue { --insight-color:#6285d5; --insight-background:rgba(142,175,240,.18); }
.insight-card__item--amber { --insight-color:#d99b4d; --insight-background:rgba(242,198,130,.19); }
.insight-card__icon { display:grid; width:31px; height:31px; flex:none; place-items:center; color:var(--insight-color); border:1px solid rgba(255,255,255,.76); border-radius:9px; background:var(--insight-background); }
.insight-card__copy { display:grid; gap:4px; min-width:0; }
.insight-card__copy strong { color:#2d4162; font-size:11px; font-weight:740; line-height:1.35; }
.insight-card__copy small { color:#4d6482; font-size:10px; line-height:1.45; }
@media (max-width:1050px) { .insight-card { min-height:unset; } .insight-card__items { grid-template-columns:repeat(3,minmax(0,1fr)); } .insight-card__item { min-height:112px; } }
@media (max-width:650px) { .insight-card__items { grid-template-columns:1fr; } .insight-card__item { min-height:unset; } }
</style>
