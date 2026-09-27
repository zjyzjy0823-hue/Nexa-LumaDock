import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ledgerService } from '../services/ledger'
import type { LedgerCategory, LedgerCategoryInput, LedgerTransaction, LedgerTransactionInput, LedgerSummary } from '../types/ledger'
export const useLedgerStore = defineStore('ledger', () => {
  const items = ref<LedgerTransaction[]>([]), categories = ref<LedgerCategory[]>([]), summary = ref<LedgerSummary | null>(null)
  const today = new Date()
  const month = ref(`${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}`)
  const loading = ref(false), loaded = ref(false), error = ref('')
  const loadedAt = ref(0)
  let sequence = 0
  async function mutate(action: () => Promise<void>) {
    if (loading.value) throw new Error('操作正在进行中')
    const current = sequence; loading.value = true; error.value = ''
    try { await action() }
    catch (cause) { if (current === sequence) error.value = cause instanceof Error ? cause.message : '操作失败'; throw cause }
    finally { if (current === sequence) loading.value = false }
  }
  async function load(token: string, force = false) {
    if (!force && (loading.value || (loaded.value && summary.value?.month === month.value && Date.now() - loadedAt.value < 60_000))) return
    const current = ++sequence; loading.value = true; error.value = ''
    try { const [transactions, categoryList, totals] = await Promise.all([ledgerService.transactions(token), ledgerService.categories(token), ledgerService.summary(token, month.value)]); if (current === sequence) { items.value = transactions; categories.value = categoryList; summary.value = totals; loaded.value = true; loadedAt.value = Date.now() } }
    catch (cause) { if (current === sequence) { items.value = []; categories.value = []; summary.value = null; loaded.value = false; error.value = cause instanceof Error ? cause.message : '加载失败' }; throw cause }
    finally { if (current === sequence) loading.value = false }
  }
  async function createTransaction(token: string, data: LedgerTransactionInput) { return mutate(async () => { const current = sequence; await ledgerService.createTransaction(token, data); if (current === sequence) await load(token, true) }) }
  async function updateTransaction(token: string, id: string, data: Partial<LedgerTransactionInput>) { return mutate(async () => { const current = sequence; await ledgerService.updateTransaction(token, id, data); if (current === sequence) await load(token, true) }) }
  async function removeTransaction(token: string, id: string) { return mutate(async () => { const current = sequence; await ledgerService.removeTransaction(token, id); if (current === sequence) await load(token, true) }) }
  async function createCategory(token: string, data: LedgerCategoryInput) { return mutate(async () => { const current = sequence; await ledgerService.createCategory(token, data); if (current === sequence) await load(token, true) }) }
  async function updateCategory(token: string, id: string, data: Partial<LedgerCategoryInput>) { return mutate(async () => { const current = sequence; await ledgerService.updateCategory(token, id, data); if (current === sequence) await load(token, true) }) }
  async function removeCategory(token: string, id: string) { return mutate(async () => { const current = sequence; await ledgerService.removeCategory(token, id); if (current === sequence) await load(token, true) }) }
  function reset() { ++sequence; items.value = []; categories.value = []; summary.value = null; month.value = new Date().toISOString().slice(0, 7); loading.value = false; loaded.value = false; loadedAt.value = 0; error.value = '' }
  return { items, categories, summary, month, loading, loaded, error, load, createTransaction, updateTransaction, removeTransaction, createCategory, updateCategory, removeCategory, reset }
})
