<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { Copy, KeyRound } from 'lucide-vue-next'
import ActionButton from '../ui/ActionButton.vue'
import Input from '../ui/Input.vue'
import Modal from '../ui/Modal.vue'
import { apiExpirations } from '../../mock/api'
import type { ApiKeyCreate, ApiKeyCreated, ApiKeyExpirationDays, ApiScope } from '../../types/api'

const props = defineProps<{ open: boolean; scopes: ApiScope[]; submitting: boolean; serverError: string; created: ApiKeyCreated | null }>()
const emit = defineEmits<{ close: []; create: [draft: ApiKeyCreate] }>()
const form = ref<HTMLFormElement | null>(null)
const name = ref('')
const selectedScopes = ref<ApiScope[]>(['Read'])
const expiration = ref('90')
const error = ref('')
const copied = ref(false)

watch(() => props.open, async open => {
  if (!open) return
  name.value = ''
  selectedScopes.value = ['Read']
  expiration.value = '90'
  error.value = ''
  copied.value = false
  await nextTick()
  form.value?.querySelector('input')?.focus()
})

function toggleScope(scope: ApiScope) {
  selectedScopes.value = selectedScopes.value.includes(scope)
    ? selectedScopes.value.filter(item => item !== scope)
    : [...selectedScopes.value, scope]
  error.value = ''
}
function submit() {
  if (props.submitting) return
  const trimmedName = name.value.trim()
  if (!trimmedName || trimmedName.length > 48) { error.value = '名称需为 1–48 个字符。'; return }
  if (!selectedScopes.value.length) { error.value = '请至少选择一项权限。'; return }
  emit('create', { name: trimmedName, scopes: [...selectedScopes.value], expires_in_days: expiration.value === 'never' ? null : Number(expiration.value) as Exclude<ApiKeyExpirationDays, null> })
}
async function copySecret() {
  if (!props.created) return
  try { await navigator.clipboard.writeText(props.created.secret); copied.value = true }
  catch { error.value = '复制失败，请手动选中并复制。' }
}
</script>

<template>
  <Modal :open="open" :title="created ? '保存 API Key' : '创建 API Key'" :description="created ? '明文仅本次可见。关闭后无法再次查看。' : '为应用或自动化创建一枚新的访问密钥。'" @close="emit('close')">
    <div v-if="created" class="create-api-key">
      <p class="create-api-key__hint">请现在复制并安全保存。刷新或关闭窗口后只会显示掩码。</p>
      <code class="create-api-key__reveal">{{ created.secret }}</code>
      <p v-if="error" class="create-api-key__error" role="alert">{{ error }}</p>
      <div class="create-api-key__actions"><ActionButton variant="secondary" @click="emit('close')">完成</ActionButton><ActionButton @click="copySecret"><Copy :size="14" />{{ copied ? '已复制' : '复制 Key' }}</ActionButton></div>
    </div>
    <form v-else ref="form" class="create-api-key" @submit.prevent="submit">
      <label class="create-api-key__field"><span>名称</span><Input v-model="name" type="text" placeholder="例如：Production App" aria-label="API Key 名称" :maxlength="48" required /></label>
      <fieldset class="create-api-key__field"><legend>权限 Scope</legend><div class="create-api-key__scopes"><label v-for="scope in scopes" :key="scope" :class="{ 'is-selected': selectedScopes.includes(scope) }"><input type="checkbox" :checked="selectedScopes.includes(scope)" @change="toggleScope(scope)" /><span>{{ scope }}</span></label></div></fieldset>
      <label class="create-api-key__field"><span>有效期</span><select v-model="expiration"><option v-for="option in apiExpirations" :key="option.value ?? 'never'" :value="option.value === null ? 'never' : String(option.value)">{{ option.label }}</option></select></label>
      <p class="create-api-key__hint"><KeyRound :size="13" />创建后明文仅本次可见，请及时保存。</p>
      <p v-if="error || serverError" class="create-api-key__error" role="alert">{{ error || serverError }}</p>
      <div class="create-api-key__actions"><ActionButton variant="secondary" :disabled="submitting" @click="emit('close')">取消</ActionButton><ActionButton type="submit" :disabled="submitting">{{ submitting ? '创建中…' : '创建' }}</ActionButton></div>
    </form>
  </Modal>
</template>

<style scoped>
.create-api-key { display:grid; gap:17px; min-width:0; }
.create-api-key__field { display:grid; gap:8px; min-width:0; margin:0; padding:0; border:0; color:var(--text-primary); font-size:11px; font-weight:700; }
.create-api-key__field legend { padding:0; margin-bottom:8px; }
.create-api-key__field select { width:100%; min-height:40px; padding:9px 11px; border:1px solid rgba(131,151,197,.3); border-radius:10px; outline:none; color:var(--text-primary); background:rgba(255,255,255,.8); font:inherit; font-size:12px; }
.create-api-key__field select:focus { border-color:var(--accent); box-shadow:0 0 0 3px rgba(105,139,230,.15); }
.create-api-key__scopes { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:7px; }
.create-api-key__scopes label { display:flex; align-items:center; gap:6px; min-width:0; padding:8px; border:1px solid rgba(138,159,204,.22); border-radius:9px; color:var(--text-secondary); background:rgba(255,255,255,.5); font-size:10px; font-weight:650; cursor:pointer; }
.create-api-key__scopes label.is-selected { border-color:rgba(109,143,228,.47); color:var(--accent-deep); background:rgba(115,151,234,.13); }
.create-api-key__scopes input { width:13px; height:13px; margin:0; accent-color:var(--accent); }
.create-api-key__hint { display:flex; align-items:center; gap:6px; margin:-3px 0 0; color:var(--text-secondary); font-size:10px; line-height:1.5; }
.create-api-key__hint svg { flex:none; }
.create-api-key__error { margin:-5px 0 0; color:#c76572; font-size:11px; }
.create-api-key__reveal { display:block; overflow-wrap:anywhere; padding:12px; border-radius:9px; color:var(--text-primary); background:rgba(255,255,255,.75); user-select:all; }
.create-api-key__actions { display:flex; justify-content:flex-end; gap:8px; margin-top:4px; }
@media (max-width:420px) { .create-api-key__scopes { grid-template-columns:repeat(2,minmax(0,1fr)); } }
</style>
