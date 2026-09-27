<script setup lang="ts">
import { ArrowDownLeft, ArrowUpRight, ChartNoAxesCombined, Wallet } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import type { LedgerStat, LedgerStatIcon } from '../../types/ledger'

defineProps<{ stat: LedgerStat }>()

const icons = {
  income: ArrowDownLeft,
  expense: ArrowUpRight,
  balance: Wallet,
  budget: ChartNoAxesCombined,
} satisfies Record<LedgerStatIcon, unknown>
</script>

<template>
  <GlassCard class="ledger-stat" :class="`ledger-stat--${stat.tone}`">
    <div class="ledger-stat__top">
      <span class="ledger-stat__label">{{ stat.label }}</span>
      <span class="ledger-stat__icon"><component :is="icons[stat.id]" :size="18" :stroke-width="1.8" /></span>
    </div>
    <strong class="ledger-stat__value">{{ stat.value }}</strong>
    <div class="ledger-stat__footer">
      <span>{{ stat.detail }}</span>
      <span v-if="stat.progress !== undefined" class="ledger-stat__progress" role="progressbar" :aria-valuenow="stat.progress" aria-valuemin="0" aria-valuemax="100" aria-label="月预算使用率"><i :style="{ width: `${stat.progress}%` }" /></span>
    </div>
  </GlassCard>
</template>

<style scoped>
.ledger-stat { min-height: 145px; }
.ledger-stat :deep(.glass-card__body) { display:flex; flex-direction:column; overflow:visible; }
.ledger-stat--blue { --ledger-stat-color:#6888e3; }
.ledger-stat--mint { --ledger-stat-color:#40aa9b; }
.ledger-stat--violet { --ledger-stat-color:#9478de; }
.ledger-stat--amber { --ledger-stat-color:#d9a04d; }
.ledger-stat__top { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }
.ledger-stat__label { color:rgba(255,255,255,.9); font-size:12px; font-weight:650; text-shadow:0 1px 8px rgba(25,38,76,.22); }
.ledger-stat__icon { display:grid; width:34px; height:34px; flex:none; place-items:center; color:#fff; border:1px solid rgba(255,255,255,.55); border-radius:11px; background:color-mix(in srgb,var(--ledger-stat-color) 43%,transparent); box-shadow:inset 0 1px 0 rgba(255,255,255,.25); }
.ledger-stat__value { margin-top:8px; color:#fff; font-size:clamp(26px,2.5vw,33px); font-weight:750; line-height:1.05; letter-spacing:-.045em; text-shadow:0 3px 14px rgba(33,47,96,.22); font-variant-numeric:tabular-nums; }
.ledger-stat__footer { display:flex; align-items:center; gap:12px; margin-top:auto; padding-top:10px; color:rgba(255,255,255,.76); font-size:11px; white-space:nowrap; text-shadow:0 1px 8px rgba(25,38,76,.22); }
.ledger-stat__progress { display:block; width:68px; height:5px; overflow:hidden; margin-left:auto; border-radius:99px; background:rgba(255,255,255,.34); }
.ledger-stat__progress i { display:block; height:100%; border-radius:inherit; background:#fff; }
</style>
