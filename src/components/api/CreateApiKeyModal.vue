<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import OpusIcon from '../ui/OpusIcon.vue'
import Modal from '../ui/Modal.vue'
import { useCopyFeedback } from '../../composables/useCopyFeedback'
import { apiExpirations } from '../../mock/api'
import type { ApiKeyCreate, ApiKeyCreated, ApiKeyExpirationDays, ApiScope } from '../../types/api'

const props = defineProps<{ open: boolean; scopes: ApiScope[]; submitting: boolean; serverError: string; created: ApiKeyCreated | null }>()
const emit = defineEmits<{ close: []; create: [draft: ApiKeyCreate] }>()
const form = ref<HTMLFormElement | null>(null)
const name = ref('')
const selectedScopes = ref<ApiScope[]>(['Read'])
const expiration = ref('90')
const error = ref('')
const { copy: copyWithFeedback, isCopied, reset: resetCopy } = useCopyFeedback()

watch(() => props.open, async open => {
  if (!open) return
  name.value = ''
  selectedScopes.value = ['Read']
  expiration.value = '90'
  error.value = ''
  resetCopy()
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
  const ok = await copyWithFeedback(props.created.secret, 'secret')
  if (!ok) error.value = '复制失败，请手动选中并复制。'
}
</script>

<template>
  <Modal :open="open" :title="created ? '保存 API Key' : '创建 API Key'" :description="created ? '明文仅本次可见。关闭后无法再次查看。' : '为应用或自动化创建一枚新的访问密钥。'" @close="emit('close')">
    <div v-if="created" class="create-api-key">
      <div class="notice warn"><OpusIcon name="alert" /><div>请现在复制并安全保存。刷新或关闭窗口后只会显示掩码。</div></div>
      <div class="secret-box">{{ created.secret }}</div>
      <p v-if="error" class="dlg-error" role="alert">{{ error }}</p>
      <div class="dlg-actions"><button class="btn btn-ghost" type="button" @click="emit('close')">完成</button><button class="btn btn-primary" :class="{ 'is-copied': isCopied('secret') }" type="button" @click="copySecret"><OpusIcon :name="isCopied('secret') ? 'check' : 'copy'" />{{ isCopied('secret') ? '已复制' : '复制 Key' }}</button></div>
    </div>
    <form v-else ref="form" @submit.prevent="submit">
      <div class="field"><label for="api-key-name">名称</label><input id="api-key-name" v-model="name" class="input" type="text" placeholder="例如：Production App" aria-label="API Key 名称" :maxlength="48" required data-initial-focus /></div>
      <div class="field">
        <label>权限 Scope</label>
        <div class="create-api-key__scopes">
          <button v-for="scope in scopes" :key="scope" class="chip" type="button" :aria-pressed="selectedScopes.includes(scope)" @click="toggleScope(scope)">{{ scope }}</button>
        </div>
      </div>
      <div class="field"><label for="api-key-exp">有效期</label><select id="api-key-exp" v-model="expiration" class="input"><option v-for="option in apiExpirations" :key="option.value ?? 'never'" :value="option.value === null ? 'never' : String(option.value)">{{ option.label }}</option></select></div>
      <div class="notice"><OpusIcon name="key" /><div>创建后明文仅本次可见，请及时保存。</div></div>
      <p v-if="error || serverError" class="dlg-error" role="alert">{{ error || serverError }}</p>
      <div class="dlg-actions"><button class="btn btn-ghost" type="button" :disabled="submitting" @click="emit('close')">取消</button><button class="btn btn-primary" type="submit" :disabled="submitting">{{ submitting ? '创建中…' : '创建' }}</button></div>
    </form>
  </Modal>
</template>

<style scoped>
.create-api-key { display: grid; gap: 14px; min-width: 0; }
.create-api-key__scopes { display: flex; flex-wrap: wrap; gap: 6px; }
</style>
