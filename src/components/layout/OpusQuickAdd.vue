<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useLedgerStore } from '../../stores/ledger'
import { useWebsitesStore } from '../../stores/websites'
import { useDataStore } from '../../stores/data'
import { websiteService } from '../../services/websites'
import OpusIcon from '../ui/OpusIcon.vue'

const props = defineProps<{ kind: string; offline?: boolean }>()
const emit = defineEmits<{ change: [kind: string]; create: [kind: string]; action: [message: string]; openShare: [] }>()
const auth = useAuthStore()
const ledger = useLedgerStore()
const websites = useWebsitesStore()
const dataStore = useDataStore()
const amount = ref('0')
const memo = ref('')
const category = ref('')
const url = ref('')
const recordCollectionId = ref('')
const recordName = ref('')
const error = ref('')
const saving = ref(false)
const bump = ref(false)
const amountEl = ref<HTMLElement>()
let bumpTimer: ReturnType<typeof setTimeout> | undefined

const types = [
  { kind: 'share', label: '共享', icon: 'shield' },
  { kind: 'tx', label: '记一笔', icon: 'ledger' },
  { kind: 'web', label: '网站', icon: 'globe' },
  { kind: 'rec', label: '记录', icon: 'data' },
] as const
const categories = computed(() => ledger.categories.filter(item => item.type === 'expense'))
const keys = ['1', '2', '3', '⌫', '保存', '4', '5', '6', '7', '8', '9', '.', '0', '00']

watch(() => props.kind, async kind => {
  error.value = ''
  if (!kind) {
    amount.value = '0'
    memo.value = ''
    url.value = ''
    category.value = ''
    recordName.value = ''
    return
  }
  if (kind === 'tx' && auth.token) {
    await ledger.load(auth.token).catch(() => {})
    if (!category.value) category.value = categories.value[0]?.id ?? ''
  }
  if (kind === 'rec' && auth.token) {
    await dataStore.load(auth.token).catch(() => {})
    if (!recordCollectionId.value) recordCollectionId.value = dataStore.items[0]?.id ?? ''
  }
})

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
  if (!auth.token || saving.value) return
  saving.value = true
  error.value = ''
  try {
    if (props.kind === 'tx') {
      await ledger.createTransaction(auth.token, {
        type: 'expense', category_id: category.value || null, amount: amount.value,
        description: memo.value.trim() || categories.value.find(item => item.id === category.value)?.name || '支出',
        occurred_at: new Date().toISOString(), merchant: '', note: '',
      })
      emit('action', '已在本机记账')
    } else if (props.kind === 'web') {
      const input = url.value.trim()
      const link = new URL(input.includes('://') ? input : `https://${input}`)
      if (!/^https?:$/.test(link.protocol)) throw new Error('请输入有效的网址')
      const items = await websiteService.list(auth.token)
      await websites.create(auth.token, {
        name: link.hostname, url: link.href, order: Math.max(-1, ...items.map(item => item.order)) + 1, favorite: false,
      })
      emit('action', `已收藏 ${link.hostname}`)
    } else if (props.kind === 'rec') {
      const name = recordName.value.trim()
      if (!recordCollectionId.value) throw new Error('请先在「数据」中创建集合')
      if (!name) throw new Error('请输入记录名称')
      await dataStore.createRecord(auth.token, recordCollectionId.value, { name, status: 'active', category: '', data_json: {} })
      emit('action', `已在本机保存「${name}」`)
    }
    emit('change', '')
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
async function paste() {
  try { url.value = await navigator.clipboard.readText() }
  catch { error.value = '请直接粘贴网址。' }
}
</script>

<template>
  <div class="scrim" :class="{ on: kind }" @click="emit('change', '')"></div>
  <section class="sheet" :class="{ on: kind }" role="dialog" :aria-modal="kind ? 'true' : undefined" aria-labelledby="sheet-title" :inert="!kind">
    <div class="grab"></div>
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><h2 id="sheet-title" style="margin:0;flex:1">快速新增</h2><button type="button" class="icon-btn" aria-label="关闭" @click="emit('change', '')"><OpusIcon name="x" /></button></div>
    <div class="add-types"><button v-for="type in types" :key="type.kind" type="button" :aria-pressed="kind === type.kind" @click="emit('change', type.kind)"><OpusIcon :name="type.icon" />{{ type.label }}</button></div>
    <template v-if="kind === 'tx'">
      <div ref="amountEl" class="amount num" :class="{ bump }"><small>¥</small>{{ amount }}</div>
      <input v-model="memo" class="memo" placeholder="添加备注（例如：午饭）">
      <div class="cats"><button v-for="item in categories" :key="item.id" class="chip" type="button" :aria-pressed="category === item.id" @click="category = item.id">{{ item.name }}</button></div>
      <div class="keypad"><button v-for="key in keys" :key="key" type="button" :class="{ save: key === '保存' }" :aria-label="key === '⌫' ? '删除' : undefined" :disabled="key === '保存' && (saving || Number(amount) <= 0)" @click="press(key)">{{ key }}</button></div>
    </template>
    <form v-else-if="kind === 'web'" @submit.prevent="save">
      <input v-model="url" class="input" style="height:48px;font-size:15px;margin-bottom:10px" placeholder="https://" aria-label="网站网址">
      <button type="button" class="btn btn-ghost btn-lg" style="width:100%;margin-bottom:8px" @click="paste"><OpusIcon name="copy" />粘贴剪贴板中的链接</button>
      <button class="btn btn-primary btn-lg" style="width:100%" :disabled="saving || !url.trim()">收藏</button>
      <p class="faint" style="font-size:12px;text-align:center;margin:10px 0 0">也可以在浏览器里「分享 → Studiolo」直接收藏</p>
    </form>
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
    <button v-else-if="kind === 'share'" class="btn btn-primary btn-lg" style="width:100%" type="button" @click="emit('openShare')">
      <OpusIcon name="shield" /> 打开共享空间
    </button>
    <p v-if="error" role="alert" style="color:var(--danger);font-size:12.5px;margin:8px 0 0">{{ error }}</p>
    <div v-if="offline" class="offline-note"><OpusIcon name="wifiOff" />当前离线 · 保存在本机，联网后自动同步</div>
  </section>
</template>
