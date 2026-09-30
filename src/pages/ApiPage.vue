<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Plus } from 'lucide-vue-next'
import ApiKeyCard from '../components/api/ApiKeyCard.vue'
import CreateApiKeyModal from '../components/api/CreateApiKeyModal.vue'
import ActionButton from '../components/ui/ActionButton.vue'
import GlassCard from '../components/ui/GlassCard.vue'
import Input from '../components/ui/Input.vue'
import PageHeader from '../components/ui/PageHeader.vue'
import { createApiKey, listApiKeys, setApiKeyStatus } from '../api/apiKeys'
import { ApiError } from '../api/client'
import { apiScopes } from '../mock/api'
import { useAuthStore } from '../stores/auth'
import type { ApiKeyCreate, ApiKeyCreated, ApiKeyPublic } from '../types/api'

const emit = defineEmits<{ action: [message: string] }>()
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
const activeKeys = computed(() => keys.value.filter(key => key.status === 'active').length)
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
  <div class="api-page">
    <PageHeader title="API" eyebrow="">
      <template #actions>
        <div class="api-page__header-actions">
          <Input v-model="query" class="api-page__search" type="search" placeholder="搜索 API Key..." aria-label="搜索 API Key" />
          <ActionButton @click="openCreate"><Plus :size="16" />创建 API Key</ActionButton>
        </div>
      </template>
    </PageHeader>
    <GlassCard class="api-page__keys" title="API Keys">
      <template #action><span class="api-page__count">{{ activeKeys }} 枚活跃 / {{ keys.length }} 枚总计</span></template>
      <p class="api-page__description">管理四个模块读取接口的访问密钥与权限范围。</p>
      <div v-if="loading" class="api-page__empty" role="status">正在加载 API Key…</div>
      <div v-else-if="loadError" class="api-page__empty" role="alert"><span>{{ loadError }}</span><ActionButton variant="secondary" @click="loadKeys">重试</ActionButton></div>
      <template v-else>
        <p v-if="actionError" class="api-page__error" role="alert">{{ actionError }}</p>
        <div v-if="visibleKeys.length" class="api-page__keys-grid">
          <ApiKeyCard v-for="key in visibleKeys" :key="key.id" :api-key="key" :busy="busyId === key.id" @toggle-status="toggleKeyStatus" />
        </div>
        <div v-else class="api-page__empty">{{ keys.length ? '没有找到匹配的 API Key' : '还没有 API Key。创建后可访问授权的读取接口。' }}</div>
      </template>
      <p class="api-page__description">明文仅在创建成功时显示一次。请求日志、用量统计和 Webhook 暂不可用。</p>
    </GlassCard>
    <CreateApiKeyModal :open="createOpen" :scopes="apiScopes" :submitting="submitting" :server-error="createError" :created="created" @close="closeCreate" @create="createKey" />
  </div>
</template>

<style scoped>
.api-page { min-width:0; padding:0 20px 36px; animation:glass-page-rise .42s ease backwards; }
.api-page :deep(.page-header__eyebrow) { display:none; }
.api-page :deep(.page-header) { align-items:center; margin:3px 0 21px; }
.api-page__header-actions { display:flex; align-items:center; gap:9px; min-width:0; }
.api-page__search { width:228px; min-width:0; }
.api-page__keys { min-height:437px; }
.api-page__count { color:rgba(255,255,255,.88); font-size:11px; }
.api-page__description { margin:0 0 15px; color:rgba(255,255,255,.88); font-size:11px; text-shadow:0 1px 6px rgba(20,33,71,.3); }
.api-page__keys-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:10px; margin-bottom:15px; }
.api-page__empty { display:grid; justify-items:center; align-content:center; gap:12px; min-height:180px; color:rgba(255,255,255,.9); font-size:12px; text-align:center; }
.api-page__error { color:#c76572; font-size:11px; }
@media (max-width:700px) { .api-page { padding:0 3px 30px; } .api-page__header-actions { width:100%; } .api-page__search { flex:1; width:auto; } }
@media (prefers-reduced-motion:reduce) { .api-page { animation:none; } }
</style>
