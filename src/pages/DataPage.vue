<script setup lang="ts">
import { confirmAction } from '../composables/useConfirm'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import OpusIcon from '../components/ui/OpusIcon.vue'
import Modal from '../components/ui/Modal.vue'
import { useDataStore } from '../stores/data'
import { useAuthStore } from '../stores/auth'
import { dataService } from '../services/data'
import { parseRecordJson } from '../utils/recordJson'
import type { CollectionSummary, CollectionRecord, RecordSummary, DataOverview } from '../types/data'

defineOptions({ inheritAttrs: false })
const props = defineProps<{ mobile?: boolean; search?: string }>()
const emit = defineEmits<{ action: [message: string]; mobileDetail: [active: boolean] }>()

const store = useDataStore()
const auth = useAuthStore()
const collections = computed(() => store.items)
const selectedId = ref('')
const query = ref('')
const focusedRecord = ref<RecordSummary | null>(null)
const mobileRecord = ref<RecordSummary | null>(null)
const flashRecordId = ref<string | null>(null)
let flashTimer: ReturnType<typeof setTimeout> | undefined

function runViewTransition(update: () => Promise<void> | void, types: string[]) {
  if (typeof document !== 'undefined' && document.startViewTransition && document.documentElement?.dataset.motion !== 'reduced') {
    document.startViewTransition({ update, types })
  } else {
    void update()
  }
}

function showMobileRecord(item: RecordSummary | null) {
  runViewTransition(async () => {
    mobileRecord.value = item
    emit('mobileDetail', Boolean(item))
    await nextTick()
  }, [item ? 'forward' : 'backward'])
}
function markFlash(id: string | undefined) {
  if (!id) return
  flashRecordId.value = id
  if (flashTimer) clearTimeout(flashTimer)
  flashTimer = setTimeout(() => { flashRecordId.value = null }, 1300)
}

const createOpen = ref(false)
const draftName = ref('')
const draftDescription = ref('')
const draftStatus = ref('active')
const draftCategory = ref('')
const draftJson = ref('{}')
const editingCollection = ref<CollectionSummary | null>(null)
const editingRecord = ref<CollectionRecord | null>(null)
const dialogKind = ref<'collection' | 'record'>('collection')
const formError = ref('')
const nameInput = ref<HTMLInputElement | null>(null)

const debouncedQuery = ref('')
const visibleCollections = computed(() => collections.value)
const selectedCollection = computed<CollectionSummary | null>(() =>
  visibleCollections.value.find(collection => collection.id === selectedId.value) ?? visibleCollections.value[0] ?? null)
const selectedPage = computed(() => selectedCollection.value ? store.pages[selectedCollection.value.id] : undefined)
const visibleRecords = computed(() => selectedPage.value?.items ?? [])
const totalRecords = computed(() => store.overview?.totalRecords ?? 0)
const dataOverview = computed<DataOverview>(() => {
  const overview = store.overview
  const recent = overview?.recentRecords ?? []
  return { active: overview?.active ?? 0, completed: overview?.completed ?? 0,
    recentActivity: recent.length, trend: [], trendLabels: [],
    activities: recent.map(record => ({ id: record.id, title: record.name, detail: record.status, time: record.updatedAt.slice(0, 10), tone: 'blue' })),
  }
})
let searchTimer: ReturnType<typeof setTimeout> | undefined
let recordSequence = 0
watch(() => props.search, search => { query.value = search ?? '' }, { immediate: true })
watch(query, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { debouncedQuery.value = query.value.trim() }, 250)
})
watch([debouncedQuery, () => auth.token], ([q, token]) => {
  if (token) void store.load(token, true, q).catch(() => {})
})
const recordQuery = computed(() => {
  const q = debouncedQuery.value
  const collection = selectedCollection.value
  if (!q || !collection) return q
  return `${collection.name} ${collection.description}`.toLocaleLowerCase().includes(q.toLocaleLowerCase()) ? '' : q
})
watch([() => selectedCollection.value?.id, recordQuery, () => auth.token], ([id, q, token]) => {
  ++recordSequence
  focusedRecord.value = null
  if (token && id) void store.loadRecords(token, id, { reset: true, q }).catch(() => {})
}, { immediate: true })
function retryLoad() {
  if (auth.token) {
    void store.load(auth.token, true, debouncedQuery.value).catch(() => {})
    void store.loadOverview(auth.token, true).catch(() => {})
  }
}
function loadMoreRecords() {
  if (auth.token && selectedCollection.value) void store.loadMoreRecords(auth.token, selectedCollection.value.id).catch(() => {})
}
function retryRecords() {
  if (!auth.token || !selectedCollection.value) return
  if (selectedPage.value?.items.length) loadMoreRecords()
  else void store.loadRecords(auth.token, selectedCollection.value.id, { reset: true, q: recordQuery.value }).catch(() => {})
}

async function openCreate() {
  ++recordSequence
  dialogKind.value = 'collection'; editingCollection.value = null; editingRecord.value = null; draftName.value = ''; draftDescription.value = ''
  formError.value = ''
  createOpen.value = true
  await nextTick()
  nameInput.value?.focus()
}
defineExpose({ openCreate, openCreateRecord: () => {
  if (selectedCollection.value) void openRecord()
  else void openCreate()
} })

function closeCreate() {
  ++recordSequence
  createOpen.value = false
  formError.value = ''
}

async function createCollection() {
  const name = draftName.value.trim()
  const description = draftDescription.value.trim()
  if (!name) {
    formError.value = dialogKind.value === 'record' ? '请输入记录名称。' : '请输入集合名称。'
    return
  }
  if (!auth.token) return
  try {
    if (dialogKind.value === 'record') {
      const payload = { name, status: draftStatus.value, category: draftCategory.value, data_json: parseRecordJson(draftJson.value) }
      const before = new Set(visibleRecords.value.map(item => item.id))
      if (editingRecord.value) {
        await store.updateRecord(auth.token, editingRecord.value.id, payload)
        markFlash(editingRecord.value.id)
      } else if (selectedCollection.value) {
        await store.createRecord(auth.token, selectedCollection.value.id, payload)
        markFlash(visibleRecords.value.find(item => !before.has(item.id))?.id)
      }
    } else if (editingCollection.value) await store.update(auth.token, editingCollection.value.id, { name, description })
    else { const item = await store.create(auth.token, { name, description, icon: 'custom', tone: 'blue' }); selectedId.value = item.id }
    if (focusedRecord.value) focusedRecord.value = visibleRecords.value.find(item => item.id === focusedRecord.value?.id) ?? null
    if (mobileRecord.value) mobileRecord.value = visibleRecords.value.find(item => item.id === mobileRecord.value?.id) ?? null
    closeCreate(); emit('action', '已保存。')
  } catch (error) { formError.value = error instanceof Error ? error.message : '保存失败' }
}
function openEditCollection(item: CollectionSummary) { ++recordSequence; editingRecord.value = null; formError.value = ''; dialogKind.value = 'collection'; editingCollection.value = item; draftName.value = item.name; draftDescription.value = item.description; createOpen.value = true }
async function openRecord(item?: RecordSummary) {
  const current = ++recordSequence
  const token = auth.token
  try {
    const record = item && token ? await dataService.getRecord(token, item.id) : undefined
    if (current !== recordSequence || token !== auth.token) return
    if (item && !record) return
    dialogKind.value = 'record'; editingCollection.value = null; editingRecord.value = record ?? null; draftName.value = record?.name ?? ''
    draftStatus.value = record?.status ?? 'active'; draftCategory.value = record?.category ?? ''
    draftJson.value = JSON.stringify(record?.dataJson ?? {}, null, 2)
    formError.value = ''; createOpen.value = true
    await nextTick()
    nameInput.value?.focus()
  } catch (error) { if (current === recordSequence && token === auth.token) emit('action', error instanceof Error ? error.message : '记录加载失败') }
}
async function removeCollection(item: CollectionSummary) { if (!auth.token || !(await confirmAction(`删除集合「${item.name}」及其记录？`))) return; try { await store.remove(auth.token, item.id); emit('action', '集合已删除。') } catch (error) { emit('action', error instanceof Error ? error.message : '删除失败') } }
async function removeRecord(item: RecordSummary) {
  if (!auth.token || !(await confirmAction(`删除记录「${item.name}」？`))) return
  try {
    await store.removeRecord(auth.token, item.id, item.collectionId)
    if (focusedRecord.value?.id === item.id) focusedRecord.value = null
    if (mobileRecord.value?.id === item.id) showMobileRecord(null)
    if (editingRecord.value?.id === item.id) closeCreate()
    emit('action', '记录已删除。')
  } catch (error) { emit('action', error instanceof Error ? error.message : '删除失败') }
}

async function copyCollectionName(collection: CollectionSummary) {
  try {
    await navigator.clipboard.writeText(collection.name)
    emit('action', `已复制「${collection.name}」的名称。`)
  } catch {
    emit('action', '复制失败，请检查浏览器权限。')
  }
}

onMounted(() => {
  if (auth.token) {
    void store.load(auth.token, false, debouncedQuery.value).catch(() => {})
    void store.loadOverview(auth.token).catch(() => {})
  }
})
onUnmounted(() => {
  clearTimeout(searchTimer)
  clearTimeout(flashTimer)
  ++recordSequence
  emit('mobileDetail', false)
})
</script>

<template>
  <div v-if="mobile && mobileRecord" class="mpage push">
    <div class="navbar">
      <button class="icon-btn" type="button" aria-label="返回" @click="showMobileRecord(null)"><OpusIcon name="chevL" /></button>
      <div class="t">{{ mobileRecord.name }}</div>
      <button class="icon-btn" type="button" aria-label="编辑记录" @click="mobileRecord && openRecord(mobileRecord)"><OpusIcon name="pencil" /></button>
    </div>
    <div class="dhero">
      <div class="tile-icon"><OpusIcon name="receipt" /></div>
      <h2>{{ mobileRecord.name }}</h2>
    </div>
    <div class="kvl mat-solid">
      <div><span>分类</span><span>{{ mobileRecord.category || '未分类' }}</span></div>
      <div><span>状态</span><span>{{ mobileRecord.status }}</span></div>
    </div>
    <div class="kvl mat-solid">
      <div><span>来源集合</span><span>{{ selectedCollection?.name }}</span></div>
      <div><span>最近修改</span><span>{{ new Date(mobileRecord.updatedAt).toLocaleString('zh-CN') }}</span></div>
    </div>
    <div class="mbtns">
      <button class="btn btn-ghost" type="button" @click="mobileRecord && openRecord(mobileRecord)"><OpusIcon name="pencil" />编辑记录</button>
      <button class="btn btn-danger" type="button" @click="mobileRecord && removeRecord(mobileRecord)"><OpusIcon name="trash" />删除记录</button>
    </div>
  </div>
  <div v-else :class="mobile ? 'data-page' : 'page full'">
    <div v-if="store.loading && !store.loaded" class="cleared" role="status">正在加载数据…</div>
    <p v-if="store.error" class="notice danger" role="alert">{{ store.error }} <button class="btn btn-sm btn-ghost" type="button" @click="retryLoad">重试</button></p>
    <template v-if="mobile">
      <div class="sec-t" style="margin-top:4px">{{ selectedCollection?.name ?? '数据' }}<span class="spacer"></span><button v-if="selectedCollection" class="btn btn-sm btn-subtle" type="button" @click="openRecord()"><OpusIcon name="plus" />记录</button></div>
      <div class="mlist mat-solid">
        <button v-for="item in visibleRecords" :key="item.id" class="mrow" :class="{ enter: flashRecordId === item.id }" type="button" @click="showMobileRecord(item)"><span class="grow"><div class="title">{{ item.name }}</div><div class="sub">{{ item.category || '未分类' }} · {{ item.status }}</div></span><OpusIcon name="chevR" /></button>
        <div v-if="!visibleRecords.length" class="mrow faint">暂无记录</div>
        <button v-if="selectedPage?.hasMore" class="mrow" type="button" @click="loadMoreRecords">加载更多</button>
      </div>
      <div class="sec-t">其它集合<span class="spacer"></span><button class="btn btn-sm btn-subtle" type="button" @click="openCreate"><OpusIcon name="plus" />集合</button></div>
      <div class="mlist mat-solid">
        <button v-for="item in visibleCollections" :key="item.id" class="mrow" type="button" @click="selectedId = item.id"><span class="tile-icon"><OpusIcon name="layers" /></span><span class="grow"><div class="title">{{ item.name }}</div><div class="sub">{{ item.recordCount }} 条</div></span><OpusIcon name="chevR" /></button>
      </div>
      <div v-if="selectedCollection" class="btn-row"><button class="btn btn-sm btn-ghost" type="button" @click="openEditCollection(selectedCollection)">编辑集合</button><button class="btn btn-sm btn-danger" type="button" @click="removeCollection(selectedCollection)">删除集合</button></div>
    </template>
    <div v-else class="split opus-data-split">
      <aside class="pane-side">
        <div class="pane-h"><h2>数据</h2><span class="faint">{{ totalRecords }} 条</span><span class="spacer"></span><button type="button" class="icon-btn" aria-label="新建集合" title="新建集合" @click="openCreate"><OpusIcon name="plus" /></button></div>
        <div class="list" style="padding:0 8px">
          <button v-for="item in visibleCollections" :key="item.id" class="row" type="button" :class="{ 'is-selected': selectedCollection?.id === item.id }" @click="selectedId = item.id">
            <span class="tile-icon"><OpusIcon name="layers" /></span><span class="grow"><div class="title">{{ item.name }}</div><div class="sub">{{ item.recordCount }} 条 · {{ item.updatedAt.slice(0, 10) }}</div></span>
          </button>
        </div>
      </aside>
      <section style="display:flex;flex-direction:column;min-width:0;overflow:hidden">
        <div class="toolbar">
          <h2 style="margin:0;font-size:16px">{{ selectedCollection?.name ?? '集合' }}</h2><span class="faint">{{ selectedCollection?.recordCount ?? 0 }} 条</span><span class="spacer"></span>
          <div class="search"><OpusIcon name="search" /><input v-model="query" class="input" type="search" placeholder="在集合中搜索" aria-label="在集合中搜索"></div>
          <button class="btn btn-primary" type="button" :disabled="!selectedCollection" @click="openRecord()"><OpusIcon name="plus" />新建记录</button>
        </div>
        <div style="overflow:auto;flex:1">
          <table class="tbl"><thead><tr><th>名称</th><th>状态</th><th>分类</th><th>更新时间</th></tr></thead>
            <tbody><tr v-for="item in visibleRecords" :key="item.id" :class="{ 'is-selected': focusedRecord?.id === item.id, flash: flashRecordId === item.id }" @click="focusedRecord = item">
              <td style="font-weight:550"><button type="button" @click.stop="focusedRecord = item">{{ item.name }}</button></td><td class="muted">{{ item.status }}</td><td class="muted">{{ item.category || '未分类' }}</td><td class="muted">{{ item.updatedAt.slice(0, 10) }}</td>
            </tr></tbody>
          </table>
          <div v-if="!visibleRecords.length" class="cleared"><OpusIcon name="table" />暂无记录</div>
          <div v-if="selectedPage?.loading" class="cleared" role="status">正在加载记录…</div>
          <div v-if="selectedPage?.error" class="notice danger" role="alert">{{ selectedPage.error }} <button class="btn btn-sm btn-ghost" type="button" @click="retryRecords">重试</button></div>
          <div v-if="selectedCollection" class="toolbar"><span class="faint">显示 {{ visibleRecords.length }} / {{ selectedPage?.total ?? selectedCollection.recordCount }} 条记录</span><button v-if="selectedPage?.hasMore" class="btn btn-sm btn-ghost" type="button" :disabled="selectedPage.loading" @click="loadMoreRecords">加载更多</button></div>
        </div>
      </section>
      <aside class="pane-inspector">
        <div v-if="focusedRecord" :key="focusedRecord.id" class="insp enter">
          <h3>{{ focusedRecord.name }}</h3>
          <dl class="meta-grid"><dt>UUID</dt><dd class="mono">{{ focusedRecord.id }}</dd><dt>状态</dt><dd>{{ focusedRecord.status }}</dd><dt>分类</dt><dd>{{ focusedRecord.category || '未分类' }}</dd><dt>更新时间</dt><dd>{{ new Date(focusedRecord.updatedAt).toLocaleString('zh-CN') }}</dd></dl>
          <div class="btn-row"><button class="btn btn-sm btn-primary" type="button" @click="focusedRecord && openRecord(focusedRecord)"><OpusIcon name="pencil" />编辑记录</button><button class="btn btn-sm btn-danger" type="button" @click="focusedRecord && removeRecord(focusedRecord)">删除记录</button></div>
        </div>
        <div v-else-if="selectedCollection" class="insp">
          <h3>{{ selectedCollection.name }}</h3>
          <p v-if="selectedCollection.description" class="muted">{{ selectedCollection.description }}</p>
          <div class="btn-row"><button class="btn btn-sm btn-ghost" type="button" @click="copyCollectionName(selectedCollection)"><OpusIcon name="copy" />复制名称</button><button class="btn btn-sm btn-ghost" type="button" @click="openEditCollection(selectedCollection)">编辑集合</button><button class="btn btn-sm btn-danger" type="button" @click="removeCollection(selectedCollection)">删除集合</button></div>
          <details v-if="store.overview || store.overviewError">
            <summary class="muted" style="cursor:pointer;font-size:12.5px">数据概览</summary>
            <ul v-if="store.overview" class="muted" style="font-size:12.5px;padding-left:18px"><li>活跃 {{ dataOverview.active }} 条 · 已完成 {{ dataOverview.completed }} 条</li><li v-for="item in dataOverview.activities" :key="item.id">{{ item.title }} · {{ item.time }}</li></ul>
            <div v-if="store.overviewError" class="notice danger" role="alert">{{ store.overviewError }} <button class="btn btn-sm btn-ghost" type="button" @click="retryLoad">重试</button></div>
          </details>
        </div>
        <div v-else class="cleared"><OpusIcon name="table" />选择一条记录查看详情</div>
      </aside>
    </div>
  </div>

  <Modal :open="createOpen" :title="`${editingCollection || editingRecord ? '编辑' : '新建'}${dialogKind === 'record' ? '记录' : '集合'}`" @close="closeCreate">
    <form id="data-create-form" @submit.prevent="createCollection">
      <div class="field"><label for="data-name">名称</label><input id="data-name" ref="nameInput" v-model="draftName" class="input" type="text" maxlength="120" placeholder="名称" data-initial-focus /></div>
      <div v-if="dialogKind === 'collection'" class="field"><label for="data-desc">描述</label><input id="data-desc" v-model="draftDescription" class="input" type="text" maxlength="500" placeholder="描述" /></div>
      <template v-else>
        <div class="field-grid">
          <div class="field"><label for="data-status">状态</label><input id="data-status" v-model="draftStatus" class="input" type="text" maxlength="40" /></div>
          <div class="field"><label for="data-category">分类</label><input id="data-category" v-model="draftCategory" class="input" type="text" maxlength="80" /></div>
        </div>
        <div class="field"><label for="data-json">记录内容（JSON）</label><textarea id="data-json" v-model="draftJson" class="input mono" aria-label="记录内容（JSON）" rows="5" spellcheck="false" placeholder="{}" /></div>
      </template>
      <p v-if="formError" class="dlg-error" role="alert">{{ formError }}</p>
    </form>
    <template #footer>
      <button v-if="mobile && editingRecord" class="btn btn-danger" type="button" @click="editingRecord && removeRecord(editingRecord)">删除记录</button>
      <button type="button" class="btn btn-ghost" @click="closeCreate">取消</button>
      <button type="submit" form="data-create-form" class="btn btn-primary"><OpusIcon name="check" />保存</button>
    </template>
  </Modal>
</template>

<style scoped>
.opus-data-split { grid-template-columns: 220px minmax(0, 1fr) 340px; }
@container (max-width: 900px) { .opus-data-split { grid-template-columns: 180px minmax(0, 1fr) 245px; } }
@container (max-width: 640px) { .opus-data-split { grid-template-columns: 128px minmax(0, 1fr); height: auto; } .opus-data-split .pane-inspector { grid-column: 1 / -1; } }
</style>
