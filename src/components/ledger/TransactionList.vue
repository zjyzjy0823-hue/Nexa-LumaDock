<script setup lang="ts">
import { Bot, Cloud, Coffee, Download, Laptop, ShoppingBag } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import type { Transaction, TransactionIcon } from '../../types/ledger'

defineProps<{ transactions: Transaction[] }>()
const emit = defineEmits<{ edit: [id: string]; remove: [id: string] }>()

const icons = {
  software: Bot,
  cloud: Cloud,
  server: Laptop,
  income: Download,
  dining: Coffee,
  shopping: ShoppingBag,
} satisfies Record<TransactionIcon, unknown>

function money(amount: number) {
  return `${amount > 0 ? '+' : '−'}¥${Math.abs(amount).toLocaleString('zh-CN')}`
}

function shortDate(date: string) {
  const [, month, day] = date.split('-')
  return `${month}月${day}日`
}
</script>

<template>
  <GlassCard class="transaction-list" title="最近交易">
    <template #action><span class="transaction-list__count">{{ transactions.length }} 笔记录</span></template>
    <div class="transaction-list__table" role="table" aria-label="最近交易列表">
      <div class="transaction-list__head" role="row"><span role="columnheader">描述</span><span role="columnheader">分类</span><span role="columnheader">日期</span><span role="columnheader">金额</span><span role="columnheader">操作</span></div>
      <div v-for="transaction in transactions" :key="transaction.id" class="transaction-list__row" role="row">
        <div class="transaction-list__description" role="cell"><span class="transaction-list__icon" :class="{ 'transaction-list__icon--income': transaction.amount > 0 }"><component :is="icons[transaction.icon]" :size="17" :stroke-width="1.8" /></span><span><strong>{{ transaction.description }}</strong><small>{{ transaction.detail }}</small></span></div>
        <span class="transaction-list__category" role="cell">{{ transaction.category }}</span>
        <time class="transaction-list__date" role="cell" :datetime="transaction.date">{{ shortDate(transaction.date) }}</time>
        <strong class="transaction-list__amount" :class="{ 'transaction-list__amount--income': transaction.amount > 0 }" role="cell">{{ money(transaction.amount) }}</strong>
        <span><button type="button" @click="emit('edit', transaction.id)">编辑</button> <button type="button" @click="emit('remove', transaction.id)">删除</button></span>
      </div>
    </div>
  </GlassCard>
</template>

<style scoped>
.transaction-list { min-height:398px; }
.transaction-list :deep(.glass-card__body) { overflow:visible; }
.transaction-list__count { color:var(--workbench-muted); font-size:11px; font-weight:600; }
.transaction-list__table { display:grid; gap:6px; }
.transaction-list__head,.transaction-list__row { display:grid; grid-template-columns:minmax(150px,1.8fr) minmax(65px,.75fr) minmax(75px,.8fr) minmax(90px,.75fr) 65px; align-items:center; gap:10px; }
.transaction-list__head { min-height:28px; padding:0 15px; color:var(--workbench-text); font-size:10px; font-weight:730; text-shadow:none; }
.transaction-list__head span:last-child { text-align:right; }
.transaction-list__row { min-height:55px; padding:6px 15px; border:var(--glass-tile-border); border-radius:12px; background:var(--ledger-tile-background,var(--glass-tile-background)); box-shadow:var(--glass-tile-shadow); backdrop-filter:var(--workbench-material); -webkit-backdrop-filter:var(--workbench-material); color:var(--workbench-text); font-size:11px; transition:background .18s,transform .18s; }
.transaction-list__row:hover { transform:translateX(2px); background:var(--ledger-tile-hover-background,var(--glass-tile-hover-background)); }
.transaction-list__description { display:flex; align-items:center; gap:10px; min-width:0; }
.transaction-list__icon { display:grid; width:32px; height:32px; flex:none; place-items:center; color:var(--workbench-accent); border:1px solid var(--workbench-line); border-radius:10px; background:var(--workbench-muted-surface); }
.transaction-list__icon--income { color:var(--workbench-good); background:var(--workbench-good-soft); }
.transaction-list__description strong,.transaction-list__description small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.transaction-list__description strong { color:var(--workbench-muted); font-size:11px; font-weight:700; }
.transaction-list__description small { margin-top:3px; color:var(--workbench-accent); font-size:10px; }
.transaction-list__category { display:inline-flex; align-items:center; justify-content:center; justify-self:start; min-width:49px; min-height:23px; padding:0 8px; border:1px solid var(--workbench-line); border-radius:8px; background:var(--workbench-solid); color:var(--workbench-muted); font-size:10px; font-weight:620; }
.transaction-list__date { color:var(--workbench-text); font-variant-numeric:tabular-nums; }
.transaction-list__amount { color:var(--workbench-accent); font-size:12px; font-weight:710; text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
.transaction-list__amount--income { color:var(--workbench-good); }
@media (max-width:600px) { .transaction-list__head,.transaction-list__row { grid-template-columns:minmax(105px,1fr) 60px 65px 76px; gap:6px; } .transaction-list__head,.transaction-list__row { padding-inline:9px; } .transaction-list__description { gap:6px; } .transaction-list__icon { width:27px; height:27px; } }
@media (max-width:420px) { .transaction-list__head { display:none; } .transaction-list__row { grid-template-columns:minmax(0,1fr) auto; row-gap:2px; padding-block:9px; } .transaction-list__description { grid-column:1; grid-row:1 / span 2; } .transaction-list__category { grid-column:2; grid-row:1; justify-self:end; } .transaction-list__date { grid-column:2; grid-row:2; text-align:right; font-size:10px; } .transaction-list__amount { grid-column:2; grid-row:3; } }
</style>
