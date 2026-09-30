<script setup lang="ts">
import { confirmAction } from '../composables/useConfirm'
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { Bell, Plus, Search, X } from 'lucide-vue-next'
import CollectionCard from '../components/data/CollectionCard.vue'
import DataStats from '../components/data/DataStats.vue'
import DataTable from '../components/data/DataTable.vue'
import ActionButton from '../components/ui/ActionButton.vue'
import GlassCard from '../components/ui/GlassCard.vue'
import { useDataStore } from '../stores/data'
import { useAuthStore } from '../stores/auth'
import type { DataCollection, CollectionRecord, DataOverview } from '../types/data'

const emit = defineEmits<{ action: [message: string] }>()

const store = useDataStore()
const auth = useAuthStore()
const collections = computed(() => store.items)
const selectedId = ref('')
const query = ref('')
const notificationsOpen = ref(false)
const createOpen = ref(false)
const draftName = ref('')
const draftDescription = ref('')
const draftStatus = ref('active')
const draftCategory = ref('')
const editingCollection = ref<DataCollection | null>(null)
const editingRecord = ref<CollectionRecord | null>(null)
const dialogKind = ref<'collection' | 'record'>('collection')
const formError = ref('')
const nameInput = ref<HTMLInputElement | null>(null)

const normalizedQuery = computed(() => query.value.trim().toLocaleLowerCase())
const visibleCollections = computed(() => collections.value.filter(collection => {
  const search = normalizedQuery.value
  return !search || `${collection.name} ${collection.description}`.toLocaleLowerCase().includes(search)
    || collection.records.some(record => `${record.name} ${record.status} ${record.category}`.toLocaleLowerCase().includes(search))
}))
const selectedCollection = computed<DataCollection | null>(() =>
  visibleCollections.value.find(collection => collection.id === selectedId.value) ?? visibleCollections.value[0] ?? null)
const visibleRecords = computed(() => {
  const collection = selectedCollection.value
  if (!collection) return []
  const search = normalizedQuery.value
  if (!search || `${collection.name} ${collection.description}`.toLocaleLowerCase().includes(search)) return collection.records
  return collection.records.filter(record => `${record.name} ${record.status} ${record.category}`.toLocaleLowerCase().includes(search))
})
const totalRecords = computed(() => collections.value.reduce((sum, collection) => sum + collection.recordCount, 0))
const dataOverview = computed<DataOverview>(() => {
  const records = collections.value.flatMap(collection => collection.records)
  const recent = records.slice().sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)).slice(0, 3)
  return { active: records.filter(record => !['done', 'completed', '完成'].includes(record.status)).length,
    completed: records.filter(record => ['done', 'completed', '完成'].includes(record.status)).length,
    recentActivity: recent.length, trend: [], trendLabels: [], activities: recent.map(record => ({ id: record.id, title: record.name, detail: record.status, time: record.updatedAt.slice(0, 10), tone: 'blue' })) }
})

async function openCreate() {
  dialogKind.value = 'collection'; editingCollection.value = null; draftName.value = ''; draftDescription.value = ''
  notificationsOpen.value = false
  formError.value = ''
  createOpen.value = true
  await nextTick()
  nameInput.value?.focus()
}
defineExpose({ openCreate })

function closeCreate() {
  createOpen.value = false
  formError.value = ''
}

async function createCollection() {
  const name = draftName.value.trim()
  const description = draftDescription.value.trim()
  if (!name) {
    formError.value = '请输入集合名称。'
    return
  }
  if (!auth.token) return
  try {
    if (dialogKind.value === 'record') {
      if (editingRecord.value) await store.updateRecord(auth.token, editingRecord.value.id, { name, status: draftStatus.value, category: draftCategory.value })
      else if (selectedCollection.value) await store.createRecord(auth.token, selectedCollection.value.id, { name, status: draftStatus.value, category: draftCategory.value, data_json: {} })
    } else if (editingCollection.value) await store.update(auth.token, editingCollection.value.id, { name, description })
    else { const item = await store.create(auth.token, { name, description, icon: 'custom', tone: 'blue' }); selectedId.value = item.id }
    closeCreate(); emit('action', '已保存。')
  } catch (error) { formError.value = error instanceof Error ? error.message : '保存失败' }
}
function openEditCollection(item: DataCollection) { dialogKind.value = 'collection'; editingCollection.value = item; draftName.value = item.name; draftDescription.value = item.description; createOpen.value = true }
function openRecord(item?: CollectionRecord) { dialogKind.value = 'record'; editingRecord.value = item ?? null; draftName.value = item?.name ?? ''; draftStatus.value = item?.status ?? 'active'; draftCategory.value = item?.category ?? ''; createOpen.value = true }
async function removeCollection(item: DataCollection) { if (!auth.token || !(await confirmAction(`删除集合「${item.name}」及其记录？`))) return; try { await store.remove(auth.token, item.id); emit('action', '集合已删除。') } catch (error) { emit('action', error instanceof Error ? error.message : '删除失败') } }
async function removeRecord(item: CollectionRecord) { if (!auth.token || !(await confirmAction(`删除记录「${item.name}」？`))) return; try { await store.removeRecord(auth.token, item.id); emit('action', '记录已删除。') } catch (error) { emit('action', error instanceof Error ? error.message : '删除失败') } }

async function copyCollectionName(collection: DataCollection) {
  try {
    await navigator.clipboard.writeText(collection.name)
    emit('action', `已复制「${collection.name}」的名称。`)
  } catch {
    emit('action', '复制失败，请检查浏览器权限。')
  }
}

function onDocumentPointerDown(event: PointerEvent) {
  if (event.target instanceof Element && !event.target.closest('[data-data-notifications]')) notificationsOpen.value = false
}
function onDocumentKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    notificationsOpen.value = false
    closeCreate()
  }
}
onMounted(() => {
  if (auth.token) store.load(auth.token).catch(() => {})
  document.addEventListener('pointerdown', onDocumentPointerDown)
  document.addEventListener('keydown', onDocumentKeydown)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
})
</script>

<template>
  <div class="data-page">
    <h1 class="visually-hidden">数据</h1>
    <div class="data-page__toolbar" aria-label="数据操作">
      <label class="data-page__search"><Search :size="16" :stroke-width="1.9" /><input v-model="query" type="search" placeholder="搜索集合或记录..." aria-label="搜索集合或记录" /><button v-if="query" type="button" aria-label="清除搜索" @click="query = ''"><X :size="14" /></button></label>
      <div class="data-page__notification-wrap" data-data-notifications>
        <button class="data-page__notification" type="button" aria-label="查看数据通知" :aria-expanded="notificationsOpen" @click="notificationsOpen = !notificationsOpen"><Bell :size="17" :stroke-width="1.9" /><span /></button>
        <div v-if="notificationsOpen" class="data-page__notifications" role="region" aria-label="数据通知">
          <strong>最近通知</strong>
          <div v-for="activity in dataOverview.activities" :key="activity.id"><span class="data-page__notification-dot" /><span>{{ activity.title }} · {{ activity.detail }}</span><small>{{ activity.time }}</small></div>
        </div>
      </div>
      <ActionButton size="md" @click="openCreate"><Plus :size="16" />新建集合</ActionButton>
      <ActionButton v-if="selectedCollection" size="md" @click="openRecord()"><Plus :size="16" />新增记录</ActionButton>
    </div>
    <p v-if="store.loading" role="status">正在加载数据…</p>
    <p v-if="store.error" role="alert">{{ store.error }} <button type="button" @click="auth.token && store.load(auth.token, true).catch(() => {})">重试</button></p>

    <section v-if="store.loaded" class="data-page__collections" aria-labelledby="data-collections-heading">
      <div class="data-page__section-heading"><div><span>COLLECTION OVERVIEW</span><h2 id="data-collections-heading">集合概览</h2></div><p>{{ visibleCollections.length }} 个集合 <span>·</span> {{ totalRecords }} 条记录</p></div>
      <div v-if="visibleCollections.length" class="data-page__collection-grid">
        <CollectionCard v-for="collection in visibleCollections" :key="collection.id" :collection="collection" :selected="selectedCollection?.id === collection.id" @select="selectedId = collection.id" @copy="copyCollectionName(collection)" @edit="openEditCollection(collection)" @remove="removeCollection(collection)" />
      </div>
      <GlassCard v-else class="data-page__no-results"><Search :size="26" /><strong>{{ query ? '没有找到匹配的集合' : '还没有集合' }}</strong><span>新建一个集合开始管理数据。</span></GlassCard>
    </section>

    <section v-if="store.loaded" class="data-page__details" aria-label="数据库与统计">
      <DataTable :collection="selectedCollection" :records="visibleRecords" @edit="openRecord" @remove="removeRecord" />
      <DataStats :total-records="totalRecords" :overview="dataOverview" />
    </section>

    <Teleport to="body">
      <div v-if="createOpen" class="data-page__dialog-backdrop" @click="closeCreate">
        <GlassCard class="data-page__dialog" role="dialog" aria-modal="true" aria-labelledby="data-create-title" @click.stop>
          <div class="data-page__dialog-heading"><div><span>{{ dialogKind === 'record' ? 'RECORD' : 'COLLECTION' }}</span><h2 id="data-create-title">{{ editingCollection || editingRecord ? '编辑' : '新建' }}{{ dialogKind === 'record' ? '记录' : '集合' }}</h2><p>保存到当前账户。</p></div><button class="data-page__dialog-close" type="button" aria-label="关闭" @click="closeCreate"><X :size="18" /></button></div>
          <form @submit.prevent="createCollection">
            <label>名称<input ref="nameInput" v-model="draftName" type="text" maxlength="120" placeholder="名称" /></label>
            <label v-if="dialogKind === 'collection'">描述<input v-model="draftDescription" type="text" maxlength="500" placeholder="描述" /></label>
            <template v-else><label>状态<input v-model="draftStatus" type="text" maxlength="40" /></label><label>分类<input v-model="draftCategory" type="text" maxlength="80" /></label></template>
            <p v-if="formError" class="data-page__form-error" role="alert">{{ formError }}</p>
            <div class="data-page__dialog-actions"><ActionButton variant="secondary" @click="closeCreate">取消</ActionButton><ActionButton type="submit"><Plus :size="15" />保存</ActionButton></div>
          </form>
        </GlassCard>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.data-page { min-width:0; padding:0 20px 36px; color:#263653; }
.visually-hidden { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
.data-page__toolbar { display:flex; align-items:center; justify-content:flex-end; gap:9px; min-height:39px; margin:4px 0 15px; }
.data-page__search { display:flex; align-items:center; gap:8px; width:230px; height:39px; padding:0 11px; border:1px solid rgba(255,255,255,.63); border-radius:11px; color:#6380bb; background:rgba(255,255,255,.76); box-shadow:inset 0 1px 0 rgba(255,255,255,.8),0 5px 14px rgba(31,49,103,.08); }
.data-page__search:focus-within { border-color:rgba(132,157,232,.85); background:rgba(255,255,255,.9); }
.data-page__search input { width:100%; min-width:0; padding:0; border:0; outline:none; color:#30405d; background:transparent; font-size:11px; }
.data-page__search input::placeholder { color:#8493a9; }
.data-page__search button { display:grid; width:21px; height:21px; flex:none; place-items:center; padding:0; border:0; border-radius:6px; color:#788ba8; background:rgba(113,137,196,.1); }
.data-page__notification-wrap { position:relative; }
.data-page__notification { position:relative; display:grid; width:39px; height:39px; place-items:center; border:1px solid rgba(255,255,255,.58); border-radius:11px; color:#fff; background:rgba(255,255,255,.22); box-shadow:inset 0 1px 0 rgba(255,255,255,.18); backdrop-filter:blur(12px); transition:background .2s,transform .2s; }
.data-page__notification:hover { transform:translateY(-2px); background:rgba(255,255,255,.32); }
.data-page__notification > span { position:absolute; top:8px; right:8px; width:6px; height:6px; border:1px solid #fff; border-radius:50%; background:#f2acac; }
.data-page__notifications { position:absolute; top:47px; right:0; z-index:20; width:280px; padding:15px; border:1px solid rgba(255,255,255,.9); border-radius:14px; color:#41516c; background:var(--glass-popover-background); box-shadow:0 18px 40px rgba(29,44,91,.22);   backdrop-filter:var(--glass-overlay-filter); -webkit-backdrop-filter:var(--glass-overlay-filter); }
.data-page__notifications > strong { display:block; margin-bottom:7px; font-size:12px; }
.data-page__notifications > div { display:grid; grid-template-columns:7px minmax(0,1fr) auto; align-items:center; gap:8px; min-height:37px; border-top:1px solid rgba(137,159,202,.13); font-size:10px; }
.data-page__notification-dot { width:6px; height:6px; border-radius:50%; background:#8199ed; }
.data-page__notifications small { color:#9aa6b7; font-size:9px; white-space:nowrap; }
.data-page__section-heading { display:flex; align-items:end; justify-content:space-between; gap:12px; margin:5px 0 15px; color:#fff; }
.data-page__section-heading span { color:rgba(244,248,255,.72); font-size:9px; font-weight:740; letter-spacing:.16em; }
.data-page__section-heading h2 { margin:6px 0 0; font-size:19px; line-height:1.2; letter-spacing:-.03em; text-shadow:0 2px 10px rgba(24,37,82,.2); }
.data-page__section-heading p { margin:0 2px 1px 0; color:rgba(248,250,255,.79); font-size:10px; white-space:nowrap; }
.data-page__section-heading p span { margin:0 4px; font-size:10px; letter-spacing:0; }
.data-page__collection-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:13px; }
.data-page__no-results { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:7px; min-height:170px; color:#dbe4ff; font-size:11px; }
.data-page__no-results strong { color:#fff; font-size:14px; }
.data-page__details { display:grid; grid-template-columns:minmax(0,1.65fr) minmax(280px,.9fr); align-items:start; gap:14px; margin-top:20px; }
.data-page__dialog-backdrop { position:fixed; inset:0; z-index:100; display:grid; place-items:center; padding:20px; background:rgba(24,37,74,.4); backdrop-filter:blur(9px); }
.data-page__dialog { width:min(100%,440px); height:auto; padding:24px; }
.data-page__dialog-heading { display:flex; align-items:start; justify-content:space-between; gap:12px; }
.data-page__dialog-heading span { color:#879bda; font-size:9px; font-weight:760; letter-spacing:.17em; }
.data-page__dialog-heading h2 { margin:6px 0 4px; color:#fff; font-size:22px; letter-spacing:-.035em; text-shadow:0 1px 8px rgba(20,33,71,.28); }
.data-page__dialog-heading p { margin:0; color:rgba(255,255,255,.78); font-size:11px; }
.data-page__dialog-close { display:grid; width:31px; height:31px; flex:none; place-items:center; border:1px solid rgba(255,255,255,.5); border-radius:9px; color:#fff; background:rgba(255,255,255,.2); }
.data-page__dialog form { display:grid; gap:15px; margin-top:24px; }
.data-page__dialog label { display:grid; gap:7px; color:rgba(255,255,255,.9); font-size:11px; font-weight:690; }
.data-page__dialog input { height:39px; width:100%; padding:0 12px; border:1px solid rgba(130,152,197,.28); border-radius:10px; outline:none; color:#2e3f5e; background:rgba(255,255,255,.84); font-size:12px; }
.data-page__dialog input:focus { border-color:#839fec; box-shadow:0 0 0 3px rgba(118,150,231,.13); }
.data-page__dialog input::placeholder { color:#aebacc; }
.data-page__form-error { margin:-5px 0 0; color:#c45d69; font-size:11px; }
.data-page__dialog-actions { display:flex; justify-content:flex-end; gap:9px; margin-top:8px; }
@media (max-width:1120px) { .data-page__collection-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .data-page__details { grid-template-columns:1fr; } }
@media (max-width:900px) { .data-page__search { width:min(100%,360px); flex:1; } }
@media (max-width:600px) { .data-page { padding:0 2px 30px; } .data-page__collection-grid { grid-template-columns:1fr; } .data-page__toolbar { flex-wrap:wrap; justify-content:flex-start; } .data-page__search { width:100%; flex-basis:100%; } .data-page__notifications { right:auto; left:0; } .data-page__section-heading { align-items:flex-start; } .data-page__section-heading p { margin-top:7px; } }
</style>
