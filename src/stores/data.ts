import { defineStore } from 'pinia'
import { ref } from 'vue'
import { dataService } from '../services/data'
import type { DataCollection, CollectionInput, RecordInput } from '../types/data'

function normalize(item: DataCollection): DataCollection {
  return { ...item, records: item.records.map(record => ({ ...record, statusTone: 'info' as const })) }
}
export const useDataStore = defineStore('data', () => {
  const items = ref<DataCollection[]>([]), loading = ref(false), loaded = ref(false), loadedAt = ref(0), error = ref('')
  let sequence = 0
  async function mutate<T>(action: () => Promise<T>): Promise<T> {
    if (loading.value) throw new Error('操作正在进行中')
    const current = sequence
    loading.value = true; error.value = ''
    try { return await action() }
    catch (cause) { if (current === sequence) error.value = cause instanceof Error ? cause.message : '操作失败'; throw cause }
    finally { if (current === sequence) loading.value = false }
  }
  async function load(token: string, force = false) {
    if (!force && (loading.value || (loaded.value && Date.now() - loadedAt.value < 60_000))) return
    const current = ++sequence; loading.value = true; error.value = ''
    try { const result = await dataService.list(token); if (current === sequence) { items.value = result.map(normalize); loaded.value = true; loadedAt.value = Date.now() } }
    catch (cause) { if (current === sequence) { items.value = []; loaded.value = false; error.value = cause instanceof Error ? cause.message : '加载失败' }; throw cause }
    finally { if (current === sequence) loading.value = false }
  }
  async function create(token: string, payload: CollectionInput) { return mutate(async () => { const current = sequence; const item = normalize(await dataService.create(token, payload)); if (current === sequence) items.value.unshift(item); return item }) }
  async function update(token: string, id: string, payload: Partial<CollectionInput>) { return mutate(async () => { const current = sequence; const item = normalize(await dataService.update(token, id, payload)); if (current === sequence) items.value = items.value.map(old => old.id === id ? item : old) }) }
  async function remove(token: string, id: string) { return mutate(async () => { const current = sequence; await dataService.remove(token, id); if (current === sequence) items.value = items.value.filter(item => item.id !== id) }) }
  async function createRecord(token: string, id: string, payload: RecordInput) { return mutate(async () => { const current = sequence; const record = await dataService.createRecord(token, id, payload); if (current === sequence) items.value = items.value.map(item => item.id === id ? { ...item, records: [...item.records, { ...record, statusTone: 'info' }], recordCount: item.recordCount + 1 } : item) }) }
  async function updateRecord(token: string, id: string, payload: Partial<RecordInput>) { return mutate(async () => { const current = sequence; const record = await dataService.updateRecord(token, id, payload); if (current === sequence) items.value = items.value.map(item => ({ ...item, records: item.records.map(old => old.id === id ? { ...record, statusTone: 'info' } : old) })) }) }
  async function removeRecord(token: string, id: string) { return mutate(async () => { const current = sequence; await dataService.removeRecord(token, id); if (current === sequence) items.value = items.value.map(item => ({ ...item, records: item.records.filter(record => record.id !== id), recordCount: item.recordCount - (item.records.some(record => record.id === id) ? 1 : 0) })) }) }
  function reset() { ++sequence; items.value = []; loading.value = false; loaded.value = false; loadedAt.value = 0; error.value = '' }
  function invalidate() { loaded.value = false; loadedAt.value = 0 }
  return { items, loading, loaded, error, load, create, update, remove, createRecord, updateRecord, removeRecord, reset, invalidate }
})
