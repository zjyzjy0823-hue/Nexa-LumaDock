import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { dataService } from '../services/data'
import type { CollectionSummary, CollectionInput, DataOverviewV1, RecordInput, RecordPage, RecordSummary } from '../types/data'

type CachedRecordPage = RecordPage & { q: string; loading: boolean; error: string }
const emptyPage = (q: string): CachedRecordPage => ({ items: [], nextCursor: null, hasMore: false, total: 0, matchedCount: 0, q, loading: false, error: '' })
const normalizeRecord = <T extends RecordSummary>(record: T): T => ({ ...record, statusTone: record.statusTone ?? 'info' })
const message = (cause: unknown) => cause instanceof Error ? cause.message : '加载失败'

export const useDataStore = defineStore('data', () => {
  const items = ref<CollectionSummary[]>([]), loaded = ref(false), loadedAt = ref(0), error = ref('')
  const pages = ref<Record<string, CachedRecordPage>>({})
  const overview = ref<DataOverviewV1 | null>(null), overviewLoading = ref(false), overviewError = ref('')
  const listLoading = ref(false), mutating = ref(false)
  const loading = computed(() => listLoading.value || mutating.value)
  let sequence = 0, listSequence = 0, overviewSequence = 0, overviewLoadedAt = 0
  let listQuery = ''
  const pageSequences = new Map<string, number>()

  async function loadOverview(token: string, force = false) {
    if (!force && (overviewLoading.value || (overview.value && Date.now() - overviewLoadedAt < 60_000))) return
    const current = sequence, request = ++overviewSequence
    overviewLoading.value = true; overviewError.value = ''
    try {
      const result = await dataService.overview(token, 4)
      if (current === sequence && request === overviewSequence) {
        overview.value = { ...result, recentRecords: result.recentRecords.map(normalizeRecord) }
        overviewLoadedAt = Date.now()
      }
    } catch (cause) {
      if (current === sequence && request === overviewSequence) overviewError.value = message(cause)
      throw cause
    } finally { if (current === sequence && request === overviewSequence) overviewLoading.value = false }
  }

  async function load(token: string, force = false, q = '') {
    q = q.trim()
    if (!force && q === listQuery && (listLoading.value || (loaded.value && Date.now() - loadedAt.value < 60_000))) return
    const current = sequence, request = ++listSequence
    listQuery = q; listLoading.value = true; error.value = ''
    try {
      const result = await dataService.list(token, { includeRecords: false, q })
      if (current === sequence && request === listSequence) { items.value = result; loaded.value = true; loadedAt.value = Date.now() }
    } catch (cause) {
      if (current === sequence && request === listSequence) { items.value = []; loaded.value = false; error.value = message(cause) }
      throw cause
    } finally { if (current === sequence && request === listSequence) listLoading.value = false }
  }

  async function loadRecords(token: string, collectionId: string, options: { reset?: boolean; q?: string } = {}) {
    const previous = pages.value[collectionId]
    const q = (options.q ?? previous?.q ?? '').trim()
    const reset = options.reset !== false || !previous || previous.q !== q
    if (!reset && (previous.loading || !previous.hasMore)) return
    const current = sequence, request = (pageSequences.get(collectionId) ?? 0) + 1
    pageSequences.set(collectionId, request)
    if (reset) pages.value[collectionId] = emptyPage(q)
    const page = pages.value[collectionId]!
    page.loading = true; page.error = ''
    try {
      const result = await dataService.listRecords(token, collectionId, { limit: 50, cursor: reset ? null : page.nextCursor, q, includeDataJson: false })
      if (current === sequence && request === pageSequences.get(collectionId)) {
        const records = new Map((reset ? [] : page.items).map(record => [record.id, record]))
        for (const record of result.items) records.set(record.id, normalizeRecord(record))
        pages.value[collectionId] = { ...result, items: [...records.values()], q, loading: false, error: '' }
      }
    } catch (cause) {
      if (current === sequence && request === pageSequences.get(collectionId)) page.error = message(cause)
      throw cause
    } finally { if (current === sequence && request === pageSequences.get(collectionId)) pages.value[collectionId]!.loading = false }
  }
  async function loadMoreRecords(token: string, collectionId: string) {
    if (!pages.value[collectionId]) return loadRecords(token, collectionId)
    return loadRecords(token, collectionId, { reset: false })
  }

  async function mutate<T>(action: (current: number) => Promise<T>): Promise<T> {
    if (loading.value) throw new Error('操作正在进行中')
    const current = sequence
    mutating.value = true; error.value = ''
    try { return await action(current) }
    catch (cause) { if (current === sequence) error.value = message(cause); throw cause }
    finally { if (current === sequence) mutating.value = false }
  }
  async function refresh(token: string, collectionId?: string) {
    await Promise.all([
      load(token, true, listQuery), loadOverview(token, true),
      ...(collectionId ? [loadRecords(token, collectionId, { reset: true })] : []),
    ])
  }
  async function create(token: string, payload: CollectionInput) {
    return mutate(async current => {
      const item = await dataService.create(token, payload, { includeRecords: false })
      if (current === sequence) await refresh(token)
      return item
    })
  }
  async function update(token: string, id: string, payload: Partial<CollectionInput>) {
    return mutate(async current => {
      await dataService.update(token, id, payload, { includeRecords: false })
      if (current === sequence) await refresh(token)
    })
  }
  async function remove(token: string, id: string) {
    return mutate(async current => {
      await dataService.remove(token, id)
      if (current === sequence) {
        pageSequences.set(id, (pageSequences.get(id) ?? 0) + 1)
        delete pages.value[id]
        await refresh(token)
      }
    })
  }
  async function createRecord(token: string, id: string, payload: RecordInput) {
    return mutate(async current => {
      await dataService.createRecord(token, id, payload)
      if (current === sequence) await refresh(token, id)
    })
  }
  async function updateRecord(token: string, id: string, payload: Partial<RecordInput>) {
    return mutate(async current => {
      const record = await dataService.updateRecord(token, id, payload)
      if (current === sequence) await refresh(token, record.collectionId)
    })
  }
  async function removeRecord(token: string, id: string, collectionId?: string) {
    return mutate(async current => {
      const parentId = collectionId ?? Object.entries(pages.value).find(([, page]) => page.items.some(record => record.id === id))?.[0]
        ?? (await dataService.getRecord(token, id)).collectionId
      if (current !== sequence) return
      await dataService.removeRecord(token, id)
      if (current === sequence) await refresh(token, parentId)
    })
  }
  function invalidate() {
    ++sequence; ++listSequence; ++overviewSequence; pageSequences.clear()
    loaded.value = false; loadedAt.value = 0; listLoading.value = false; mutating.value = false
    pages.value = {}; overview.value = null; overviewLoadedAt = 0; overviewLoading.value = false
    error.value = ''; overviewError.value = ''
  }
  function reset() { invalidate(); items.value = []; listQuery = '' }
  return { items, pages, overview, loading, loaded, error, overviewLoading, overviewError, load, loadOverview, loadRecords, loadMoreRecords, create, update, remove, createRecord, updateRecord, removeRecord, reset, invalidate }
})
