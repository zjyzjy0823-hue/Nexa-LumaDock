<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import OpusIcon from '../components/ui/OpusIcon.vue'
import CreateApiKeyModal from '../components/api/CreateApiKeyModal.vue'
import { createApiKey, listApiKeys, setApiKeyStatus } from '../api/apiKeys'
import { ApiError } from '../api/client'
import { apiScopes } from '../mock/api'
import { useAuthStore } from '../stores/auth'
import type { ApiKeyCreate, ApiKeyCreated, ApiKeyPublic } from '../types/api'

defineProps<{ mobile?: boolean }>()
const emit = defineEmits<{ action: [message: string]; back: [] }>()
const auth = useAuthStore()
const keys = ref<ApiKeyPublic[]>([])
const query = ref('')
const loading = ref(true)
const loadError = ref('')
const actionError = ref('')
const busyId = ref<string | null>(null)
const createOpen = ref(false)
const submitting = ref(false)
const createError = ref('')
const created = ref<ApiKeyCreated | null>(null)
const visibleKeys = computed(() => keys.value.filter(key =>
  `${key.name} ${key.masked_key} ${key.scopes.join(' ')}`.toLocaleLowerCase().includes(query.value.trim().toLocaleLowerCase())))

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : '请求失败，请重试。'
}
async function handleAuthError(error: unknown) {
  if (error instanceof ApiError && error.status === 401) {
    try { await auth.restore() } catch { /* restore clears invalid login state */ }
  }
}
async function loadKeys() {
  loading.value = true
  loadError.value = ''
  try {
    if (!auth.token) throw new Error('请先登录。')
    keys.value = await listApiKeys(auth.token)
  } catch (error) {
    keys.value = []
    loadError.value = errorMessage(error)
    await handleAuthError(error)
  } finally { loading.value = false }
}
function openCreate() { createError.value = ''; created.value = null; createOpen.value = true }
defineExpose({ openCreate })
function closeCreate() {
  if (submitting.value) return
  createOpen.value = false
  created.value = null
  createError.value = ''
}
async function createKey(payload: ApiKeyCreate) {
  if (!auth.token) return
  submitting.value = true
  createError.value = ''
  try {
    const result = await createApiKey(auth.token, payload)
    const { secret: _secret, ...publicKey } = result
    keys.value.unshift(publicKey)
    created.value = result
    query.value = ''
  } catch (error) {
    createError.value = errorMessage(error)
    await handleAuthError(error)
  } finally { submitting.value = false }
}
async function toggleKeyStatus(id: string) {
  const key = keys.value.find(item => item.id === id)
  if (!key || key.status === 'expired' || !auth.token) return
  busyId.value = id
  actionError.value = ''
  try {
    const updated = await setApiKeyStatus(auth.token, id, key.status === 'active' ? 'inactive' : 'active')
    keys.value = keys.value.map(item => item.id === id ? updated : item)
    emit('action', `「${updated.name}」已${updated.status === 'active' ? '启用' : '停用'}。`)
  } catch (error) {
    actionError.value = errorMessage(error)
    await handleAuthError(error)
  } finally { busyId.value = null }
}
onMounted(loadKeys)
onUnmounted(() => { created.value = null })
</script>

<template>
  <div class="api-page" :class="mobile ? 'mpage push' : undefined">
    <div v-if="mobile" class="navbar">
      <button class="icon-btn" type="button" aria-label="返回" @click="emit('back')"><OpusIcon name="chevL" /></button>
      <div class="t">集成与 API</div>
      <button class="icon-btn" type="button" aria-label="新建令牌" @click="openCreate"><OpusIcon name="plus" /></button>
    </div>
    <header v-else class="ph">
      <div><h1>集成与 API</h1><div class="sub">令牌按身份隔离，可单独管理</div></div>
      <div class="actions"><button class="btn btn-primary" type="button" @click="openCreate"><OpusIcon name="plus" />新建令牌</button></div>
    </header>
    <div class="notice info" style="margin-bottom:14px"><OpusIcon name="shield" /><div><b>任何令牌都无法读取共享空间的明文。</b>读取内容必须由人当次输入密码，普通令牌只允许访问已授权的接口。</div></div>
    <div v-if="loading" class="cleared" role="status">正在加载令牌…</div>
    <div v-else-if="loadError" class="notice danger" role="alert">{{ loadError }}<button class="btn btn-sm btn-ghost" type="button" @click="loadKeys">重试</button></div>
    <template v-else>
      <p v-if="actionError" class="notice danger" role="alert">{{ actionError }}</p>
      <div v-if="keys.length" class="api-search">
        <div :class="mobile ? 'msearch' : 'api-search__box'"><OpusIcon name="search" /><input v-model="query" :class="mobile ? undefined : 'input'" type="search" placeholder="搜索令牌" aria-label="搜索令牌"></div>
      </div>
      <div v-if="mobile" class="mlist mat-solid">
        <div v-for="key in visibleKeys" :key="key.id" class="mrow">
          <span class="tile-icon"><OpusIcon name="key" /></span>
          <span class="grow"><div class="title">{{ key.name }}</div><div class="sub mono">{{ key.masked_key }} · {{ key.scopes.join('、') }}</div></span>
          <button class="btn btn-sm" :class="key.status === 'active' ? 'btn-danger' : 'btn-ghost'" type="button" :disabled="busyId === key.id || key.status === 'expired'" @click="toggleKeyStatus(key.id)">{{ key.status === 'expired' ? '已过期' : key.status === 'active' ? '停用' : '启用' }}</button>
        </div>
        <div v-if="!visibleKeys.length" class="mrow faint">{{ keys.length ? '没有匹配的令牌' : '还没有令牌' }}</div>
      </div>
      <div v-else class="mat-solid" style="border-radius:var(--r-lg);overflow:auto">
        <table class="tbl"><thead><tr><th>名称</th><th>令牌</th><th>权限范围</th><th>最近使用</th><th></th></tr></thead>
          <tbody><tr v-for="key in visibleKeys" :key="key.id"><td style="font-weight:550">{{ key.name }}</td><td class="mono muted">{{ key.masked_key }}</td><td class="muted">{{ key.scopes.join('、') }}</td><td class="faint">{{ key.last_used_at ? new Date(key.last_used_at).toLocaleString('zh-CN') : '—' }}</td><td class="r"><button class="btn btn-sm" :class="key.status === 'active' ? 'btn-danger' : 'btn-subtle'" type="button" :disabled="busyId === key.id || key.status === 'expired'" @click="toggleKeyStatus(key.id)">{{ key.status === 'expired' ? '已过期' : key.status === 'active' ? '停用' : '启用' }}</button></td></tr>
          <tr v-if="!visibleKeys.length"><td colspan="5" class="faint" style="text-align:center;height:80px">{{ keys.length ? '没有匹配的令牌' : '还没有令牌' }}</td></tr></tbody>
        </table>
      </div>
    </template>
    <CreateApiKeyModal :open="createOpen" :scopes="apiScopes" :submitting="submitting" :server-error="createError" :created="created" @close="closeCreate" @create="createKey" />
  </div>
</template>

<style scoped>
.api-search { margin-bottom: 12px; }
.api-search__box { position: relative; max-width: 280px; }
.api-search__box :deep(svg.i) { position: absolute; left: 10px; top: 50%; translate: 0 -50%; width: 15px; height: 15px; color: var(--text-3); pointer-events: none; }
.api-search__box .input { padding-left: 32px; height: 34px; }
</style>
