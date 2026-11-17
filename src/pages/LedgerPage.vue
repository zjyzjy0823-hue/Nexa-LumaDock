<script setup lang="ts">
import { localDateKey, localDayKey, localMonthKey } from '../services/localTime'
import { confirmAction } from '../composables/useConfirm'
import OpusSegment from '../components/ui/OpusSegment.vue'
import OpusIcon from '../components/ui/OpusIcon.vue'
import Modal from '../components/ui/Modal.vue'
import { computed, onMounted, ref } from 'vue'
import { useLedgerStore } from '../stores/ledger'
import { useAuthStore } from '../stores/auth'
import type { ExpenseTrend, SpendingCategory, LedgerTransaction, LedgerCategory } from '../types/ledger'
import FinanceChart from '../components/ledger/FinanceChart.vue'

const store = useLedgerStore(), auth = useAuthStore()
const localDate = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}` }
const props = defineProps<{ mobile?: boolean; search?: string }>()
const emit = defineEmits<{ action: [message: string] }>()
const transactionOpen = ref(false), categoryOpen = ref(false)
const editingTransaction = ref<LedgerTransaction | null>(null), editingCategory = ref<LedgerCategory | null>(null)
const draft = ref({ type: 'expense' as 'income' | 'expense', amount: '', category_id: '', description: '', occurred_at: localDate(), merchant: '', note: '' })
const categoryDraft = ref({ name: '', type: 'expense' as 'income' | 'expense', icon: 'shopping' })
const formError = ref('')
const flashId = ref<string | null>(null)
let flashTimer: ReturnType<typeof setTimeout> | undefined
onMounted(() => { if (auth.token) store.load(auth.token).catch(() => {}) })
const money = (value: string | number) => `${Number(value) < 0 ? '−' : ''}¥${Math.abs(Number(value)).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const optionsOpen = ref(false)
const showTrends = ref(false)
const currentTransactions = computed(() => store.items.filter(item => localMonthKey(item.occurredAt) === store.month))
const transactions = computed(() => currentTransactions.value.filter(item =>
  [item.description, item.merchant, item.categoryName].some(value => value?.toLowerCase().includes(props.search?.trim().toLowerCase() ?? '')),
))
const thisMonth = localMonthKey(new Date().toISOString())
const previousMonth = localMonthKey(new Date(new Date().getFullYear(), new Date().getMonth() - 1, 15).toISOString())
const expenseAmount = computed(() => Number(store.summary?.expense ?? 0))
const incomeAmount = computed(() => Number(store.summary?.income ?? 0))
const expenseRatio = computed(() => incomeAmount.value > 0 ? Math.round((expenseAmount.value / incomeAmount.value) * 100) : 0)
const categoryTotal = computed(() => Math.max(1, spendingCategories.value.reduce((sum, item) => sum + item.amount, 0)))

function selectMonth(month: string) {
  store.month = month
  changeMonth()
}
function markFlash(id: string | undefined) {
  if (!id) return
  flashId.value = id
  if (flashTimer) clearTimeout(flashTimer)
  flashTimer = setTimeout(() => { flashId.value = null }, 1300)
}
const spendingCategories = computed<SpendingCategory[]>(() => (store.summary?.categories ?? []).map((entry, index) => ({ ...entry, amount: Number(entry.amount), color: ['var(--series-1, #6564ed)', '#24a483', '#ec935f', '#dd6e91', 'var(--series-5, #78a9e6)', '#8e9d64'][index % 6]! })))
const expenseTrends = computed<ExpenseTrend[]>(() => {
  const monthly = (store.summary?.monthlyTrend ?? []).filter(item => item.month <= store.month)
  const daily = new Map<string, number>()
  for (const item of currentTransactions.value) if (item.type === 'expense') { const day = localDayKey(item.occurredAt); daily.set(day, (daily.get(day) ?? 0) + Number(item.amount)) }
  return [
    { id: '30d', label: '30天', caption: '本月每日支出', labels: [...daily.keys()].sort().map(day => `${day}日`), values: [...daily.keys()].sort().map(day => daily.get(day) ?? 0) },
    { id: '6m', label: '6个月', caption: '近 6 个月每月支出', labels: monthly.slice(-6).map(item => item.month), values: monthly.slice(-6).map(item => Number(item.expense)) },
    { id: 'year', label: '年度', caption: '近 12 个月每月支出', labels: monthly.slice(-12).map(item => item.month), values: monthly.slice(-12).map(item => Number(item.expense)) },
  ]
})
defineExpose({ openCreate: (value?: string) => {
  openTransaction()
  const match = value?.match(/^(.+?)\s*[¥￥]?\s*(\d+(?:\.\d{1,2})?)\s*(元|块)?$/)
  if (match) {
    draft.value.description = match[1]!.trim()
    draft.value.amount = match[2]!
  }
} })
function openTransaction(id?: string) {
  editingTransaction.value = store.items.find(item => item.id === id) ?? null
  const item = editingTransaction.value
  draft.value = { type: item?.type ?? 'expense', amount: item?.amount ?? '', category_id: item?.categoryId ?? '', description: item?.description ?? '',
    occurred_at: item ? localDateKey(item.occurredAt) : localDate(), merchant: item?.merchant ?? '', note: item?.note ?? '' }
  formError.value = ''; transactionOpen.value = true
}
async function saveTransaction() {
  if (!auth.token) return
  try {
    const payload = { ...draft.value, category_id: draft.value.category_id || null, occurred_at: new Date(`${draft.value.occurred_at}T12:00:00`).toISOString() }
    const before = new Set(store.items.map(item => item.id))
    if (editingTransaction.value) {
      await store.updateTransaction(auth.token, editingTransaction.value.id, payload)
      markFlash(editingTransaction.value.id)
    } else {
      await store.createTransaction(auth.token, payload)
      markFlash(store.items.find(item => !before.has(item.id))?.id)
    }
    transactionOpen.value = false; emit('action', '交易已保存。')
  } catch (error) { formError.value = error instanceof Error ? error.message : '保存失败' }
}
async function removeTransaction(id: string) { if (!auth.token || !(await confirmAction('删除这笔交易？'))) return; try { await store.removeTransaction(auth.token, id) } catch (error) { emit('action', error instanceof Error ? error.message : '删除失败') } }
function openCategory(item?: LedgerCategory) { editingCategory.value = item ?? null; categoryDraft.value = { name: item?.name ?? '', type: item?.type ?? 'expense', icon: item?.icon ?? 'shopping' }; formError.value = ''; categoryOpen.value = true }
async function saveCategory() { if (!auth.token) return; try { if (editingCategory.value) await store.updateCategory(auth.token, editingCategory.value.id, categoryDraft.value); else await store.createCategory(auth.token, categoryDraft.value); categoryOpen.value = false } catch (error) { formError.value = error instanceof Error ? error.message : '保存失败' } }
async function removeCategory(id: string) { if (!auth.token || !(await confirmAction('删除此分类？相关交易将保留为未分类。'))) return; try { await store.removeCategory(auth.token, id) } catch (error) { emit('action', error instanceof Error ? error.message : '删除失败') } }
function changeMonth() { if (auth.token) store.load(auth.token, true).catch(() => {}) }
</script>

<template>
  <div class="ledger-page">
    <header v-if="!mobile" class="ph"><div><h1>账本</h1><div class="sub">{{ store.month }} · 个人账本 · 时区 {{ Intl.DateTimeFormat().resolvedOptions().timeZone }}</div></div>
      <div class="actions">
        <OpusSegment><button type="button" :aria-pressed="store.month === thisMonth && !showTrends" @click="showTrends = false; selectMonth(thisMonth)">本月</button><button type="button" :aria-pressed="store.month === previousMonth && !showTrends" @click="showTrends = false; selectMonth(previousMonth)">上月</button><button type="button" :aria-pressed="showTrends" @click="showTrends = !showTrends">趋势</button></OpusSegment>
        <button class="icon-btn" type="button" aria-label="账本选项" :aria-expanded="optionsOpen" @click="optionsOpen = !optionsOpen"><OpusIcon name="more" /></button>
        <button class="btn btn-primary" type="button" @click="openTransaction()"><OpusIcon name="plus" />记一笔</button>
      </div>
    </header>
    <div v-if="optionsOpen" class="card mat ledger-options enter" style="margin-bottom:14px">
      <div class="ledger-options__bar">
        <label class="ledger-options__month"><span>月份</span><input v-model="store.month" class="input" type="month" @change="changeMonth"></label>
        <button class="btn btn-ghost btn-sm" type="button" @click="openCategory()"><OpusIcon name="plus" />新增分类</button>
      </div>
      <div v-if="store.categories.length" class="list" style="margin-top:8px">
        <div v-for="item in store.categories" :key="item.id" class="row"><span class="grow"><span class="title">{{ item.name }}</span><span class="sub">{{ item.type === 'income' ? '收入' : '支出' }}</span></span><button class="btn btn-sm btn-subtle" type="button" @click="openCategory(item)">编辑</button><button class="btn btn-sm btn-danger" type="button" @click="removeCategory(item.id)">删除</button></div>
      </div>
    </div>
    <p v-if="store.loading" class="faint" role="status">正在加载账本…</p>
    <div v-if="store.error" class="notice danger" role="alert">{{ store.error }} <button class="btn btn-sm btn-ghost" type="button" @click="auth.token && store.load(auth.token, true).catch(() => {})">重试</button></div>
    <template v-if="mobile">
      <div class="mlist mat-solid">
        <div v-for="item in transactions" :key="item.id" class="mrow" :class="{ enter: flashId === item.id }">
          <span class="tile-icon"><OpusIcon name="receipt" /></span><button class="grow" style="text-align:left;min-width:0" type="button" @click="openTransaction(item.id)"><div class="title">{{ item.description }}</div><div class="sub">{{ item.categoryName ?? '未分类' }} · {{ localDateKey(item.occurredAt) }}</div></button>
          <span class="end"><span class="num" :class="{ 'amt-pos': item.type === 'income' }" style="font-weight:650">{{ money(Number(item.amount) * (item.type === 'income' ? 1 : -1)) }}</span><button class="btn btn-sm btn-danger" type="button" @click="removeTransaction(item.id)">删除</button></span>
        </div>
        <div v-if="!transactions.length" class="mrow faint">暂无记录</div>
      </div>
      <button class="btn btn-ghost" type="button" @click="optionsOpen = !optionsOpen">账本选项</button>
    </template>
    <template v-else>
      <div class="stats4">
        <div class="card mat"><div class="l">支出</div><div class="v num">{{ money(store.summary?.expense ?? 0) }}</div></div>
        <div class="card mat"><div class="l">收入</div><div class="v num amt-pos">{{ money(store.summary?.income ?? 0) }}</div></div>
        <div class="card mat"><div class="l">结余</div><div class="v num">{{ money(store.summary?.balance ?? 0) }}</div></div>
        <div class="card mat">
          <div class="l">{{ incomeAmount > 0 ? '支出 / 收入比' : '交易笔数' }}</div>
          <div class="v num">{{ incomeAmount > 0 ? `${expenseRatio}%` : currentTransactions.length }}</div>
          <div class="meter" style="margin:8px 0 0"><i v-if="incomeAmount > 0" :style="{ width: Math.min(100, expenseRatio) + '%' }"></i></div>
        </div>
      </div>
      <FinanceChart v-if="showTrends" :trends="expenseTrends" />
      <div v-else class="bento">
        <section class="card mat s8">
          <h2 class="card-h"><OpusIcon name="receipt" /> 流水<span class="spacer"></span><span class="faint" style="font-weight:400">{{ transactions.length }} 笔</span></h2>
          <div style="overflow:auto"><table class="tbl"><thead><tr><th>项目</th><th>分类</th><th>时间</th><th class="r">金额</th><th></th></tr></thead>
            <tbody>
              <tr v-for="item in transactions" :key="item.id" :class="{ flash: flashId === item.id }"><td><button type="button" style="display:inline-flex;align-items:center;gap:10px" @click="openTransaction(item.id)"><span class="tile-icon" style="width:28px;height:28px"><OpusIcon name="receipt" /></span>{{ item.description }}</button></td><td class="muted">{{ item.categoryName ?? '未分类' }}</td><td class="muted">{{ localDateKey(item.occurredAt) }}</td><td class="r num" style="font-weight:600" :class="{ 'amt-pos': item.type === 'income' }">{{ money(Number(item.amount) * (item.type === 'income' ? 1 : -1)) }}</td><td class="r"><button class="btn btn-sm btn-danger" type="button" @click="removeTransaction(item.id)">删除</button></td></tr>
              <tr v-if="!transactions.length"><td colspan="5" class="faint">本月暂无记录</td></tr>
            </tbody>
          </table></div>
        </section>
        <section class="card mat s4">
          <h2 class="card-h"><OpusIcon name="layers" /> 分类</h2>
          <div class="cat-bar"><i v-for="item in spendingCategories" :key="item.id" :style="{ '--c': item.color, flex: item.amount }"></i></div>
          <div class="kv"><div v-for="item in spendingCategories" :key="item.id"><span :style="{ width:'8px', height:'8px', borderRadius:'2px', background:item.color }"></span>{{ item.name }}<span class="num muted">{{ money(item.amount) }} · {{ Math.round(item.amount / categoryTotal * 100) }}%</span></div></div>
          <div v-if="!spendingCategories.length" class="faint" style="font-size:12.5px">暂无分类支出</div>
        </section>
      </div>
    </template>

    <Modal :open="transactionOpen" :title="`${editingTransaction ? '编辑' : '新增'}交易`" @close="transactionOpen = false">
      <form id="ledger-tx-form" @submit.prevent="saveTransaction">
        <div class="field-grid">
          <div class="field"><label for="tx-type">类型</label><select id="tx-type" v-model="draft.type" class="input"><option value="expense">支出</option><option value="income">收入</option></select></div>
          <div class="field"><label for="tx-amount">金额</label><input id="tx-amount" v-model="draft.amount" class="input" type="number" min="0.01" step="0.01" required data-initial-focus /></div>
        </div>
        <div class="field-grid">
          <div class="field"><label for="tx-cat">分类</label><select id="tx-cat" v-model="draft.category_id" class="input"><option value="">未分类</option><option v-for="item in store.categories.filter(entry => entry.type === draft.type)" :key="item.id" :value="item.id">{{ item.name }}</option></select></div>
          <div class="field"><label for="tx-date">日期</label><input id="tx-date" v-model="draft.occurred_at" class="input" type="date" required /></div>
        </div>
        <div class="field"><label for="tx-desc">描述</label><input id="tx-desc" v-model="draft.description" class="input" required /></div>
        <div class="field-grid">
          <div class="field"><label for="tx-merchant">商户</label><input id="tx-merchant" v-model="draft.merchant" class="input" /></div>
          <div class="field"><label for="tx-note">备注</label><input id="tx-note" v-model="draft.note" class="input" /></div>
        </div>
        <p v-if="formError" class="dlg-error" role="alert">{{ formError }}</p>
      </form>
      <template #footer>
        <button class="btn btn-ghost" type="button" @click="transactionOpen = false">取消</button>
        <button class="btn btn-primary" type="submit" form="ledger-tx-form">保存</button>
      </template>
    </Modal>

    <Modal :open="categoryOpen" :title="`${editingCategory ? '编辑' : '新增'}分类`" @close="categoryOpen = false">
      <form id="ledger-cat-form" @submit.prevent="saveCategory">
        <div class="field"><label for="cat-name">名称</label><input id="cat-name" v-model="categoryDraft.name" class="input" required data-initial-focus /></div>
        <div class="field"><label for="cat-type">类型</label><select id="cat-type" v-model="categoryDraft.type" class="input"><option value="expense">支出</option><option value="income">收入</option></select></div>
        <p v-if="formError" class="dlg-error" role="alert">{{ formError }}</p>
      </form>
      <template #footer>
        <button class="btn btn-ghost" type="button" @click="categoryOpen = false">取消</button>
        <button class="btn btn-primary" type="submit" form="ledger-cat-form">保存</button>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.ledger-page { min-width: 0; }
.ledger-options__bar { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.ledger-options__month { display: inline-flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-2); }
.ledger-options__month .input { width: 165px; height: 32px; }
</style>
