<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useLedgerStore } from '../stores/ledger'
import { useAuthStore } from '../stores/auth'
import type { LedgerStat, ExpenseTrend, SpendingCategory, Transaction, LedgerInsight, LedgerTransaction, LedgerCategory } from '../types/ledger'
import StatCard from '../components/ledger/StatCard.vue'
import FinanceChart from '../components/ledger/FinanceChart.vue'
import CategoryChart from '../components/ledger/CategoryChart.vue'
import TransactionList from '../components/ledger/TransactionList.vue'
import InsightCard from '../components/ledger/InsightCard.vue'
const store = useLedgerStore(), auth = useAuthStore()
const localDate = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}` }
const emit = defineEmits<{ action: [message: string] }>()
const transactionOpen = ref(false), categoryOpen = ref(false)
const editingTransaction = ref<LedgerTransaction | null>(null), editingCategory = ref<LedgerCategory | null>(null)
const draft = ref({ type: 'expense' as 'income' | 'expense', amount: '', category_id: '', description: '', occurred_at: localDate(), merchant: '', note: '' })
const categoryDraft = ref({ name: '', type: 'expense' as 'income' | 'expense', icon: 'shopping' })
const formError = ref('')
onMounted(() => { if (auth.token) store.load(auth.token).catch(() => {}) })
const money = (value: string | number) => `${Number(value) < 0 ? '−' : ''}¥${Math.abs(Number(value)).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const ledgerStats = computed<LedgerStat[]>(() => [
  { id: 'income', label: 'Monthly Income', value: money(store.summary?.income ?? 0), detail: '本月总收入', tone: 'mint' },
  { id: 'expense', label: 'Monthly Expense', value: money(store.summary?.expense ?? 0), detail: '本月总支出', tone: 'blue' },
  { id: 'balance', label: 'Balance', value: money(store.summary?.balance ?? 0), detail: '本月收支结余', tone: 'violet' },
  { id: 'budget', label: 'Transactions', value: String(store.items.filter(item => item.occurredAt.slice(0, 7) === store.month).length), detail: '本月交易笔数', tone: 'amber' },
])
const currentTransactions = computed(() => store.items.filter(item => item.occurredAt.slice(0, 7) === store.month))
const transactions = computed<Transaction[]>(() => currentTransactions.value.map(item => ({ id: item.id, description: item.description,
  detail: item.note || item.merchant, category: item.categoryName ?? '未分类', date: item.occurredAt.slice(0, 10),
  amount: Number(item.amount) * (item.type === 'expense' ? -1 : 1), icon: item.type === 'income' ? 'income' : 'shopping' })))
const spendingCategories = computed<SpendingCategory[]>(() => (store.summary?.categories ?? []).map((entry, index) => ({ ...entry, amount: Number(entry.amount), color: ['#728df1', '#9a82e7', '#70c5d8', '#eda6b7', '#f2c47c', '#9eb2cb'][index % 6]! })))
const expenseTrends = computed<ExpenseTrend[]>(() => {
  const monthly = (store.summary?.monthlyTrend ?? []).filter(item => item.month <= store.month)
  const daily = new Map<string, number>()
  for (const item of currentTransactions.value) if (item.type === 'expense') { const day = item.occurredAt.slice(8, 10); daily.set(day, (daily.get(day) ?? 0) + Number(item.amount)) }
  return [
    { id: '30d', label: '30天', caption: '本月每日支出', labels: [...daily.keys()].sort().map(day => `${day}日`), values: [...daily.keys()].sort().map(day => daily.get(day) ?? 0) },
    { id: '6m', label: '6个月', caption: '近 6 个月每月支出', labels: monthly.slice(-6).map(item => item.month), values: monthly.slice(-6).map(item => Number(item.expense)) },
    { id: 'year', label: '年度', caption: '近 12 个月每月支出', labels: monthly.slice(-12).map(item => item.month), values: monthly.slice(-12).map(item => Number(item.expense)) },
  ]
})
const ledgerInsights = computed<LedgerInsight[]>(() => {
  const top = [...spendingCategories.value].sort((a, b) => b.amount - a.amount)[0]
  if (!top) return [{ id: 'empty', title: '本月暂无支出', detail: '添加交易后可查看分类统计。', tone: 'blue' }]
  const share = Math.round(top.amount / Number(store.summary?.expense || 1) * 100)
  return [{ id: 'top', title: `最大支出分类：${top.name}`, detail: `占本月支出的 ${share}%（${money(top.amount)}）。`, tone: 'blue' }]
})
function openTransaction(id?: string) {
  editingTransaction.value = store.items.find(item => item.id === id) ?? null
  const item = editingTransaction.value
  draft.value = { type: item?.type ?? 'expense', amount: item?.amount ?? '', category_id: item?.categoryId ?? '', description: item?.description ?? '',
    occurred_at: item?.occurredAt.slice(0, 10) ?? localDate(), merchant: item?.merchant ?? '', note: item?.note ?? '' }
  formError.value = ''; transactionOpen.value = true
}
async function saveTransaction() {
  if (!auth.token) return
  try {
    const payload = { ...draft.value, category_id: draft.value.category_id || null, occurred_at: `${draft.value.occurred_at}T12:00:00` }
    if (editingTransaction.value) await store.updateTransaction(auth.token, editingTransaction.value.id, payload)
    else await store.createTransaction(auth.token, payload)
    transactionOpen.value = false; emit('action', '交易已保存。')
  } catch (error) { formError.value = error instanceof Error ? error.message : '保存失败' }
}
async function removeTransaction(id: string) { if (!auth.token || !confirm('删除这笔交易？')) return; try { await store.removeTransaction(auth.token, id) } catch (error) { emit('action', error instanceof Error ? error.message : '删除失败') } }
function openCategory(item?: LedgerCategory) { editingCategory.value = item ?? null; categoryDraft.value = { name: item?.name ?? '', type: item?.type ?? 'expense', icon: item?.icon ?? 'shopping' }; formError.value = ''; categoryOpen.value = true }
async function saveCategory() { if (!auth.token) return; try { if (editingCategory.value) await store.updateCategory(auth.token, editingCategory.value.id, categoryDraft.value); else await store.createCategory(auth.token, categoryDraft.value); categoryOpen.value = false } catch (error) { formError.value = error instanceof Error ? error.message : '保存失败' } }
async function removeCategory(id: string) { if (!auth.token || !confirm('删除此分类？相关交易将保留为未分类。')) return; try { await store.removeCategory(auth.token, id) } catch (error) { emit('action', error instanceof Error ? error.message : '删除失败') } }
function changeMonth() { if (auth.token) store.load(auth.token, true).catch(() => {}) }
</script>

<template>
  <div class="ledger-page">
    <h1 class="visually-hidden">账本</h1>
    <div><label>月份 <input v-model="store.month" type="month" @change="changeMonth" /></label> <button type="button" @click="openTransaction()">新增交易</button> <button type="button" @click="openCategory()">新增分类</button></div>
    <p v-if="store.loading" role="status">正在加载账本…</p>
    <p v-if="store.error" role="alert">{{ store.error }} <button type="button" @click="auth.token && store.load(auth.token, true).catch(() => {})">重试</button></p>

    <section v-if="store.loaded" class="ledger-page__stats" aria-label="本月财务概览">
      <StatCard v-for="stat in ledgerStats" :key="stat.id" :stat="stat" />
    </section>

    <section v-if="store.loaded" class="ledger-page__charts" aria-label="支出分析">
      <FinanceChart :trends="expenseTrends" />
      <CategoryChart :categories="spendingCategories" />
    </section>

    <section v-if="store.loaded" class="ledger-page__details" aria-label="交易与洞察">
      <TransactionList :transactions="transactions" @edit="openTransaction" @remove="removeTransaction" />
      <InsightCard :insights="ledgerInsights" />
    </section>
    <div v-if="store.loaded && !currentTransactions.length">本月还没有交易，添加一笔开始记账。</div>
    <section v-if="store.loaded"><h2>分类</h2><div v-for="item in store.categories" :key="item.id">{{ item.name }} · {{ item.type === 'income' ? '收入' : '支出' }} <button type="button" @click="openCategory(item)">编辑</button> <button type="button" @click="removeCategory(item.id)">删除</button></div></section>
    <Teleport to="body"><div v-if="transactionOpen" class="ledger-modal-backdrop"><div class="ledger-modal" role="dialog" aria-modal="true"><h2>{{ editingTransaction ? '编辑' : '新增' }}交易</h2><form @submit.prevent="saveTransaction"><label>类型<select v-model="draft.type"><option value="expense">支出</option><option value="income">收入</option></select></label><label>金额<input v-model="draft.amount" type="number" min="0.01" step="0.01" required /></label><label>分类<select v-model="draft.category_id"><option value="">未分类</option><option v-for="item in store.categories.filter(entry => entry.type === draft.type)" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><label>描述<input v-model="draft.description" required /></label><label>日期<input v-model="draft.occurred_at" type="date" required /></label><label>商户<input v-model="draft.merchant" /></label><label>备注<input v-model="draft.note" /></label><p v-if="formError" role="alert">{{ formError }}</p><button type="button" @click="transactionOpen = false">取消</button><button type="submit">保存</button></form></div></div></Teleport>
    <Teleport to="body"><div v-if="categoryOpen" class="ledger-modal-backdrop"><div class="ledger-modal" role="dialog" aria-modal="true"><h2>{{ editingCategory ? '编辑' : '新增' }}分类</h2><form @submit.prevent="saveCategory"><label>名称<input v-model="categoryDraft.name" required /></label><label>类型<select v-model="categoryDraft.type"><option value="expense">支出</option><option value="income">收入</option></select></label><p v-if="formError" role="alert">{{ formError }}</p><button type="button" @click="categoryOpen = false">取消</button><button type="submit">保存</button></form></div></div></Teleport>
  </div>
</template>

<style scoped>
.ledger-page { --ledger-tile-background:linear-gradient(140deg,rgba(250,251,255,.56),rgba(235,239,255,.34)); --ledger-tile-hover-background:linear-gradient(140deg,rgba(250,251,255,.68),rgba(235,239,255,.47)); min-width:0; padding:0 2px 28px; }
.visually-hidden { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
.ledger-page__stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin:4px 0 16px; }
.ledger-modal-backdrop { position:fixed; inset:0; z-index:120; display:grid; place-items:center; background:rgba(24,39,83,.4); }
.ledger-modal { width:min(420px,calc(100vw - 32px)); max-height:90vh; overflow:auto; padding:24px; border:1px solid rgba(255,255,255,.7); border-radius:16px; background:#f3f6ff; color:#263b5d; }
.ledger-modal form { display:grid; gap:10px; }.ledger-modal label { display:grid; gap:4px; }.ledger-modal input,.ledger-modal select { min-height:36px; padding:6px; }
.ledger-page__charts,.ledger-page__details { display:grid; grid-template-columns:minmax(0,1.55fr) minmax(310px,1fr); gap:16px; margin-bottom:16px; }
@media (max-width:1250px) { .ledger-page__stats { grid-template-columns:repeat(2,minmax(0,1fr)); } .ledger-page__charts,.ledger-page__details { grid-template-columns:minmax(0,1.35fr) minmax(280px,1fr); } }
@media (max-width:1050px) { .ledger-page__charts,.ledger-page__details { grid-template-columns:1fr; } }
@media (max-width:550px) { .ledger-page__stats { gap:9px; } .ledger-page__charts,.ledger-page__details { gap:12px; margin-bottom:12px; } }
@media (max-width:370px) { .ledger-page__stats { grid-template-columns:1fr; } }
</style>
