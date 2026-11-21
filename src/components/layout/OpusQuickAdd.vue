<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useLedgerStore } from '../../stores/ledger'
import { useWebsitesStore } from '../../stores/websites'
import { useDataStore } from '../../stores/data'
import { isAndroidLocal } from '../../desktop/androidLocal'
import { websiteService } from '../../services/websites'
import { websiteDraft, websiteInput } from '../../services/websiteForm'
import type { WebsiteCategory } from '../../types/website'
import OpusIcon from '../ui/OpusIcon.vue'
import WebsiteFormFields from '../websites/WebsiteFormFields.vue'
import OpusQuickShare from './OpusQuickShare.vue'

const props = defineProps<{ kind: string; offline?: boolean }>()
const emit = defineEmits<{ change: [kind: string]; create: [kind: string]; action: [message: string]; openShare: [spaceId?: string] }>()
const auth = useAuthStore()
const ledger = useLedgerStore()
const websites = useWebsitesStore()
const dataStore = useDataStore()
const amount = ref('0')
const memo = ref('')
const category = ref('')
const addingCategory = ref(false)
const categoryName = ref('')
const categoryNameInput = ref<HTMLInputElement>()
const site = ref(websiteDraft())
const siteCategories = ref<WebsiteCategory[]>([])
const siteCategoriesLoading = ref(false)
const websiteToken = computed(() => auth.token ?? (isAndroidLocal() ? '' : null))
const recordCollectionId = ref('')
const recordName = ref('')
const error = ref('')
const saving = ref(false)
const bump = ref(false)
const amountEl = ref<HTMLElement>()
const closeButton = ref<HTMLButtonElement>()
const panelContent = ref<HTMLElement>()
let returnFocus: HTMLElement | null = null
let bumpTimer: ReturnType<typeof setTimeout> | undefined

const types = [
  { kind: 'share', label: '共享', icon: 'shield' },
  { kind: 'tx', label: '记一笔', icon: 'ledger' },
  { kind: 'web', label: '网站', icon: 'globe' },
  { kind: 'rec', label: '记录', icon: 'data' },
] as const
const categories = computed(() => ledger.categories.filter(item => item.type === 'expense'))
const keys = ['1', '2', '3', '⌫', '保存', '4', '5', '6', '7', '8', '9', '.', '0', '00']

watch(() => props.kind, async (kind, previous) => {
  error.value = ''
  if (kind) void nextTick(() => { if (panelContent.value) panelContent.value.scrollTop = 0 })
  if (kind && !previous) {
    returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    void nextTick(() => closeButton.value?.focus())
  }
  if (!kind) {
    amount.value = '0'
    memo.value = ''
    category.value = ''
    addingCategory.value = false
    categoryName.value = ''
    site.value = websiteDraft()
    siteCategories.value = []
    recordName.value = ''
    if (returnFocus?.isConnected) returnFocus.focus()
    returnFocus = null
    return
  }
  if (kind === 'tx' && auth.token) {
    await ledger.load(auth.token).catch(cause => {
      if (props.kind === 'tx') error.value = cause instanceof Error ? cause.message : '分类加载失败'
    })
    if (category.value && !categories.value.some(item => item.id === category.value)) category.value = ''
  }
  if (kind === 'web' && websiteToken.value !== null) {
    const token = websiteToken.value
    siteCategoriesLoading.value = true
    try {
      const groups = await websiteService.categories(token)
      if (websiteToken.value !== token || props.kind !== 'web') return
      siteCategories.value = groups
      if (!groups.some(item => item.id === site.value.categoryId)) site.value.categoryId = ''
    } catch (cause) {
      if (props.kind === 'web') error.value = cause instanceof Error ? cause.message : '网站分类加载失败'
    } finally {
      siteCategoriesLoading.value = false
    }
  }
  if (kind === 'rec' && auth.token) {
    await dataStore.load(auth.token).catch(() => {})
    if (!recordCollectionId.value) recordCollectionId.value = dataStore.items[0]?.id ?? ''
  }
})
onUnmounted(() => clearTimeout(bumpTimer))

function triggerBump() {
  bump.value = false
  if (bumpTimer) clearTimeout(bumpTimer)
  requestAnimationFrame(() => {
    if (amountEl.value) void amountEl.value.offsetWidth
    bump.value = true
    bumpTimer = setTimeout(() => { bump.value = false }, 240)
  })
}

async function save() {
  const kind = props.kind
  const token = kind === 'web' ? websiteToken.value : auth.token
  if (token === null || (kind !== 'web' && !token) || saving.value || addingCategory.value && kind === 'tx') return
  saving.value = true
  error.value = ''
  try {
    if (kind === 'tx') {
      await ledger.createTransaction(token, {
        type: 'expense', category_id: category.value || null, amount: amount.value,
        description: memo.value.trim() || categories.value.find(item => item.id === category.value)?.name || '支出',
        occurred_at: new Date().toISOString(), merchant: '', note: '',
      })
      emit('action', '已在本机记账')
    } else if (kind === 'web') {
      const data = websiteInput(site.value)
      const items = await websiteService.list(token)
      if (websiteToken.value !== token) return
      data.order = items.reduce((max, item) => Math.max(max, item.order), -1) + 1
      await websites.create(token, data)
      emit('action', `已添加「${data.name}」`)
    } else if (kind === 'rec') {
      const name = recordName.value.trim()
      if (!recordCollectionId.value) throw new Error('请先在「数据」中创建集合')
      if (!name) throw new Error('请输入记录名称')
      await dataStore.createRecord(token, recordCollectionId.value, { name, status: 'active', category: '', data_json: {} })
      emit('action', `已在本机保存「${name}」`)
    }
    if (props.kind === kind) emit('change', '')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '保存失败'
  } finally {
    saving.value = false
  }
}
function press(key: string) {
  if (key === '保存') return void save()
  if (key === '⌫') {
    amount.value = amount.value.slice(0, -1) || '0'
    triggerBump()
    return
  }
  const next = key !== '.' && amount.value === '0' ? (key === '00' ? '0' : String(Number(key))) : amount.value + key
  if (/^\d{1,9}(\.\d{0,2})?$/.test(next)) {
    amount.value = next
    triggerBump()
  }
}
function openCategoryForm() {
  addingCategory.value = true
  error.value = ''
  void nextTick(() => categoryNameInput.value?.focus())
}

async function createCategory() {
  const token = auth.token
  const name = categoryName.value.trim()
  if (!token || !name || saving.value || ledger.loading) return
  saving.value = true
  error.value = ''
  try {
    const item = await ledger.createCategory(token, { name, type: 'expense', icon: 'shopping' })
    if (auth.token !== token) return
    category.value = item.id
    addingCategory.value = false
    categoryName.value = ''
    emit('action', `已新增分类「${item.name}」`)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '新增分类失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="scrim" :class="{ on: kind }" @click="emit('change', '')"></div>
  <section class="sheet quick-add-sheet" :class="{ on: kind }" role="dialog" :aria-modal="kind ? 'true' : undefined"
    aria-labelledby="sheet-title" :inert="!kind" @keydown.esc.stop="emit('change', '')">
    <div class="grab" aria-hidden="true"></div>
    <header class="quick-add-heading">
      <h2 id="sheet-title">快速新增</h2>
      <button ref="closeButton" type="button" class="quick-close" aria-label="关闭" @click="emit('change', '')"><OpusIcon name="x" /></button>
    </header>
    <div class="quick-add-tabs" role="group" aria-label="新增类型">
      <button v-for="type in types" :key="type.kind" type="button" :aria-pressed="kind === type.kind" @click="emit('change', type.kind)">
        <OpusIcon :name="type.icon" />{{ type.label }}
      </button>
    </div>
    <div ref="panelContent" class="quick-add-content">
      <OpusQuickShare v-if="kind" :active="kind === 'share'" @action="emit('action', $event)" @open-share="emit('openShare', $event)" />
      <form v-if="kind" v-show="kind === 'web'" class="quick-website-form" @submit.prevent="save">
        <WebsiteFormFields v-model="site" :active="kind === 'web'" :categories="siteCategories" show-paste @error="error = $event" />
        <button class="btn btn-primary quick-website-save" :disabled="saving || siteCategoriesLoading || !site.name.trim() || !site.url.trim()">
          {{ saving ? '保存中…' : '添加网站' }}
        </button>
      </form>
      <template v-if="kind === 'tx'">
        <div ref="amountEl" class="amount num" :class="{ bump }"><small>¥</small>{{ amount }}</div>
        <input v-model="memo" class="memo" maxlength="200" placeholder="添加备注（例如：午饭）">
        <form v-if="addingCategory" class="quick-ledger-category" @submit.prevent="createCategory">
          <input ref="categoryNameInput" v-model="categoryName" class="input" maxlength="80" aria-label="新分类名称" placeholder="新分类名称" />
          <button type="button" class="btn btn-ghost btn-sm" :disabled="saving" @click="addingCategory = false">取消</button>
          <button type="submit" class="btn btn-primary btn-sm" :disabled="saving || ledger.loading || !categoryName.trim()">添加</button>
        </form>
        <div v-else class="quick-ledger-category">
          <label for="quick-ledger-category">分类</label>
          <select id="quick-ledger-category" v-model="category" class="input" :disabled="ledger.loading || saving">
            <option value="">{{ ledger.loading ? '正在读取分类…' : '未分类' }}</option>
            <option v-for="item in categories" :key="item.id" :value="item.id">{{ item.name }}</option>
          </select>
          <button type="button" class="btn btn-ghost btn-sm" :disabled="!auth.token || ledger.loading || saving" @click="openCategoryForm">
            <OpusIcon name="plus" />新建分类
          </button>
        </div>
        <div class="keypad"><button v-for="key in keys" :key="key" type="button" :class="{ save: key === '保存' }" :aria-label="key === '⌫' ? '删除' : undefined" :disabled="key === '保存' && (saving || ledger.loading || addingCategory || Number(amount) <= 0)" @click="press(key)">{{ key }}</button></div>
      </template>
      <form v-else-if="kind === 'rec'" @submit.prevent="save">
        <template v-if="dataStore.items.length">
          <div class="kvl mat-solid">
            <div>
              <span>集合</span>
              <select v-model="recordCollectionId" aria-label="目标集合" style="border:0;background:transparent;text-align:right;font-weight:600">
                <option v-for="item in dataStore.items" :key="item.id" :value="item.id">{{ item.name }}</option>
              </select>
            </div>
          </div>
          <input v-model="recordName" class="input" style="height:48px;font-size:15px;margin-bottom:10px" placeholder="名称" aria-label="记录名称">
          <button class="btn btn-primary btn-lg" style="width:100%" :disabled="saving || !recordName.trim()">保存</button>
        </template>
        <template v-else>
          <div class="notice" style="margin-bottom:12px"><OpusIcon name="data" /><div>还没有数据集合，请先创建集合</div></div>
          <button type="button" class="btn btn-primary btn-lg" style="width:100%" @click="emit('create', 'collection')">新建集合</button>
        </template>
      </form>
      <p v-if="error" role="alert" style="color:var(--danger);font-size:12.5px;margin:8px 0 0">{{ error }}</p>
      <div v-if="offline && kind && kind !== 'share'" class="offline-note"><OpusIcon name="wifiOff" />未连接同步 · 保存在本机</div>
    </div>
  </section>
</template>

<style scoped>
.quick-add-sheet {
  display: flex;
  flex-direction: column;
  height: min(calc(562px + env(safe-area-inset-bottom)), 88%);
  overflow: hidden;
}
.quick-add-sheet > .grab, .quick-add-heading, .quick-add-tabs { flex: none; }
.quick-add-content {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
}
.quick-add-content > :not(.quick-share) { flex: none; }
.quick-ledger-category {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  margin: 4px 0 10px;
  font-size: 13px;
}
.quick-ledger-category > .input { flex: 1; min-width: 0; height: 38px; }
.quick-ledger-category > button { flex: none; min-height: 38px; }
.quick-website-form { display: grid; gap: 12px; }
.quick-website-form :deep(.field) { margin-bottom: 8px; }
.quick-website-form :deep(.website-icon-field) { margin-bottom: 8px; }
.quick-website-form :deep(.website-options .field), .quick-website-form :deep(.website-icon-field .field) { margin-bottom: 0; }
.quick-website-save { min-height: 42px; }
.quick-add-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.quick-add-heading { margin-bottom: 14px; }
.quick-add-heading h2 { margin: 0; font-size: 20px; letter-spacing: -.02em; }
.quick-close {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--text-2);
}
.quick-close .i { width: 16px; height: 16px; }
.quick-add-tabs {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 3px;
  padding: 4px;
  margin-bottom: 16px;
  border-radius: 15px;
  background: var(--surface-3);
}
.quick-add-tabs button {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 6px;
  min-height: 43px;
  padding: 4px;
  border-radius: 11px;
  color: var(--text-2);
  font-size: 12px;
  white-space: nowrap;
}
.quick-add-tabs button[aria-pressed="true"] {
  background: var(--solid);
  color: var(--text);
  font-weight: 650;
  box-shadow: var(--shadow-1);
}
.quick-add-tabs .i { width: 16px; height: 16px; flex: none; }
@media (max-width: 360px) {
  .quick-add-tabs button { flex-direction: column; gap: 2px; }
}
</style>
