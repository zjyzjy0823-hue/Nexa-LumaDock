<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { getDiagnostics, diagnosticsRows, diagnosticsText, type Diagnostics } from '../../services/diagnostics'
import SettingRow from './SettingRow.vue'
import ActionButton from '../ui/ActionButton.vue'

const auth = useAuthStore()
const data = ref<Diagnostics | null>(null)
const loading = ref(false)
const message = ref('')
let sequence = 0
const rows = computed(() => data.value ? diagnosticsRows(data.value) : [])
async function refresh() {
  const current = ++sequence
  const token = auth.token
  data.value = null
  message.value = ''
  loading.value = Boolean(token)
  if (!token) return
  try { const result = await getDiagnostics(token); if (current === sequence) data.value = result }
  catch { if (current === sequence) message.value = '无法获取诊断，请检查后端连接后重试。' }
  finally { if (current === sequence) loading.value = false }
}
async function copy() {
  if (!data.value) return
  try { await navigator.clipboard.writeText(diagnosticsText(data.value)); message.value = '诊断信息已复制。' }
  catch { message.value = '复制失败，请重试。' }
}
watch(() => auth.token, refresh, { immediate: true, flush: 'sync' })
</script>

<template>
  <section class="settings-card diagnostics" aria-labelledby="diagnostics-title">
    <div class="diagnostics-actions">
      <h3 id="diagnostics-title">Nexa Diagnostics</h3>
      <ActionButton variant="secondary" size="sm" :disabled="loading" @click="refresh">刷新</ActionButton>
      <ActionButton variant="secondary" size="sm" :disabled="!data || loading" @click="copy">复制诊断</ActionButton>
    </div>
    <p v-if="loading" role="status">正在检查后端与 Core…</p>
    <p v-if="message" role="status">{{ message }}</p>
    <SettingRow v-for="[label, text] in rows" :key="label" :label="label"><span class="diagnostics-value">{{ text }}</span></SettingRow>
  </section>
</template>

<style scoped>
.diagnostics { margin-top: 14px; }
.diagnostics-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
h3 { flex: 1; color: var(--text-primary); font-size: 14px; }
p { color: var(--text-secondary); font-size: 12px; }
.diagnostics-value { max-width: 100%; overflow-wrap: anywhere; color: var(--text-primary); font-size: 12px; line-height: 1.7; }
</style>
