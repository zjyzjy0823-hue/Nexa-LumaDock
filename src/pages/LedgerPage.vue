<script setup lang="ts">
import StatCard from '../components/ledger/StatCard.vue'
import FinanceChart from '../components/ledger/FinanceChart.vue'
import CategoryChart from '../components/ledger/CategoryChart.vue'
import TransactionList from '../components/ledger/TransactionList.vue'
import InsightCard from '../components/ledger/InsightCard.vue'
import { expenseTrends, ledgerInsights, ledgerStats, spendingCategories, transactions } from '../mock/ledger'
</script>

<template>
  <div class="ledger-page">
    <h1 class="visually-hidden">账本</h1>

    <section class="ledger-page__stats" aria-label="本月财务概览">
      <StatCard v-for="stat in ledgerStats" :key="stat.id" :stat="stat" />
    </section>

    <section class="ledger-page__charts" aria-label="支出分析">
      <FinanceChart :trends="expenseTrends" />
      <CategoryChart :categories="spendingCategories" />
    </section>

    <section class="ledger-page__details" aria-label="交易与洞察">
      <TransactionList :transactions="transactions" />
      <InsightCard :insights="ledgerInsights" />
    </section>
  </div>
</template>

<style scoped>
.ledger-page { --ledger-tile-background:linear-gradient(140deg,rgba(250,251,255,.56),rgba(235,239,255,.34)); --ledger-tile-hover-background:linear-gradient(140deg,rgba(250,251,255,.68),rgba(235,239,255,.47)); min-width:0; padding:0 2px 28px; }
.visually-hidden { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
.ledger-page__stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin:4px 0 16px; }
.ledger-page__charts,.ledger-page__details { display:grid; grid-template-columns:minmax(0,1.55fr) minmax(310px,1fr); gap:16px; margin-bottom:16px; }
@media (max-width:1250px) { .ledger-page__stats { grid-template-columns:repeat(2,minmax(0,1fr)); } .ledger-page__charts,.ledger-page__details { grid-template-columns:minmax(0,1.35fr) minmax(280px,1fr); } }
@media (max-width:1050px) { .ledger-page__charts,.ledger-page__details { grid-template-columns:1fr; } }
@media (max-width:550px) { .ledger-page__stats { gap:9px; } .ledger-page__charts,.ledger-page__details { gap:12px; margin-bottom:12px; } }
@media (max-width:370px) { .ledger-page__stats { grid-template-columns:1fr; } }
</style>
