<script setup lang="ts">
import { ArrowDown, ArrowUp, ChevronDown } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { ledgerSnapshot } from '../../data/operations'

const money = (amount: number, digits = 0) =>
  new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: ledgerSnapshot.currency,
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(amount)
</script>

<template>
  <GlassCard title="账本" class="ledger-card">
    <template #action>
      <button class="period" type="button" aria-label="当前周期：本月">
        本月 <ChevronDown :size="14" />
      </button>
    </template>

    <div class="balance-panel">
      <div class="balance-copy">
        <span class="balance-label">总余额</span>
        <strong class="balance">{{ money(ledgerSnapshot.balance, 2) }}</strong>
        <span class="balance-change"><ArrowUp :size="15" /> <b>{{ ledgerSnapshot.changePercent }}%</b><span>较上月</span></span>
      </div>
      <div class="bars" role="img" aria-label="本月余额增长">
        <span v-for="(bar, index) in ledgerSnapshot.trend" :key="index" :style="{ height: `${bar}%` }" />
      </div>
    </div>

    <div class="summary-row">
      <div class="summary">
        <span class="summary-label">收入</span>
        <strong><ArrowUp :size="15" class="income-arrow" />{{ money(ledgerSnapshot.income, 2) }}</strong>
      </div>
      <div class="summary">
        <span class="summary-label">支出</span>
        <strong><ArrowDown :size="15" class="expense-arrow" />{{ money(ledgerSnapshot.expense, 2) }}</strong>
      </div>
    </div>
  </GlassCard>
</template>

<style scoped>
.ledger-card{padding:17px 15px 10px}
.ledger-card :deep(.glass-card__header){margin-bottom:10px}
.ledger-card :deep(.glass-card__title){color:#fff;font-size:20px;font-weight:500}
.ledger-card :deep(.glass-card__title)::before{content:'';display:inline-block;width:28px;height:28px;margin-right:9px;background:url('/ledger-icon.png') center / contain no-repeat;vertical-align:-7px;filter:drop-shadow(0 1px 3px rgba(41,69,134,.34))}
.ledger-card :deep(.glass-card__title)::after{content:'›';display:inline-block;margin-left:12px;font-size:26px;font-weight:300;line-height:.5;vertical-align:-1px}
.period{display:inline-flex;align-items:center;gap:7px;padding:6px 10px;border:1px solid rgba(255,255,255,.37);border-radius:10px;background:rgba(255,255,255,.15);box-shadow:inset 0 1px rgba(255,255,255,.22);color:rgba(255,255,255,.94);font:inherit;font-size:13px;white-space:nowrap;cursor:pointer}
.period:hover{background:rgba(255,255,255,.27)}
.period:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.balance-panel{display:flex;align-items:end;justify-content:space-between;gap:10px;min-height:107px;padding:10px 12px 11px;border:1px solid rgba(255,255,255,.35);border-radius:14px;background:linear-gradient(105deg,rgba(255,255,255,.72),rgba(236,237,255,.52));box-shadow:inset 0 1px rgba(255,255,255,.44)}
.balance-copy{min-width:0;display:flex;flex-direction:column;align-items:flex-start}
.balance-label{color:#485469;font-size:14px;white-space:nowrap}
.balance{margin-top:2px;color:#171b24;font-size:clamp(27px,2.22vw,35px);font-weight:730;letter-spacing:-.045em;line-height:1.15;white-space:nowrap;font-variant-numeric:tabular-nums}
.balance-change{display:inline-flex;align-items:center;gap:5px;margin-top:6px;color:#19a262;font-size:14px;white-space:nowrap}
.balance-change b{font-weight:720}
.balance-change span{margin-left:5px;color:#465267;font-weight:450}
.bars{display:flex;align-items:end;justify-content:space-between;gap:9px;width:38%;min-width:105px;height:76px;padding:0 2px 1px}
.bars span{flex:1;min-width:5px;border-radius:5px 5px 2px 2px;background:linear-gradient(180deg,#a993ff,#7ac4ff);box-shadow:0 0 12px rgba(135,169,255,.27)}
.bars span:nth-child(even){background:linear-gradient(180deg,#818aff,#7fd4ff)}
.summary-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;margin-top:5px}
.summary{min-width:0;min-height:63px;padding:9px 17px;border:1px solid rgba(255,255,255,.35);border-radius:13px;background:rgba(255,255,255,.33)}
.summary-label{display:block;color:#5f697b;font-size:14px}
.summary strong{display:flex;align-items:center;gap:7px;margin-top:5px;color:#1d202b;font-size:16px;font-weight:670;white-space:nowrap;font-variant-numeric:tabular-nums}
.income-arrow{color:#22bb70;flex:none}.expense-arrow{color:#ff4e68;flex:none}
@container (max-height: 230px) {
  .ledger-card { padding: 12px 13px 8px; }
  .ledger-card :deep(.glass-card__header) { margin-bottom: 6px; }
  .balance-panel { min-height: 84px; padding: 7px 9px; }
  .balance-label, .balance-change, .summary-label { font-size: 11px; }
  .balance { font-size: 24px; }
  .balance-change { margin-top: 2px; }
  .balance-change span { margin-left: 1px; }
  .bars { height: 51px; min-width: 75px; gap: 5px; }
  .summary { min-height: 48px; padding: 5px 8px; }
  .summary strong { margin-top: 3px; font-size: 13px; gap: 3px; }
}
@container (max-width: 280px) {
  .bars { display: none; }
  .balance-change span { display: none; }
}
@media(max-width:450px){.balance{font-size:27px}.bars{gap:5px;min-width:68px}.summary{padding-inline:8px}.summary strong{font-size:13px}}
</style>
