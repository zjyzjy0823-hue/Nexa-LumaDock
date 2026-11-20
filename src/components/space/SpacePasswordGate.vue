<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import OpusIcon from '../ui/OpusIcon.vue'

const props = defineProps<{
  open: boolean
  title: string
  description: string
  confirmLabel?: string
  busy?: boolean
  error?: string
}>()

const emit = defineEmits<{
  close: []
  submit: [password: string]
}>()

const password = ref('')
const inputRef = ref<HTMLInputElement | null>(null)

watch(
  () => props.open,
  async visible => {
    password.value = ''
    if (visible) {
      await nextTick()
      inputRef.value?.focus()
    }
  },
)

function handleSubmit() {
  if (props.busy || !password.value) return
  const current = password.value
  password.value = ''
  emit('submit', current)
}

function handleClose() {
  password.value = ''
  emit('close')
}
</script>

<template>
  <div v-if="open" class="space-gate-backdrop" role="dialog" aria-modal="true" :aria-label="title" @click.self="handleClose">
    <form class="space-gate-card mat" @submit.prevent="handleSubmit">
      <div class="space-gate-head">
        <span class="space-gate-icon"><OpusIcon name="lock" /></span>
        <div class="space-gate-titles">
          <h3>{{ title }}</h3>
          <p v-if="description" class="muted">{{ description }}</p>
        </div>
      </div>

      <label class="space-gate-field">
        <input
          ref="inputRef"
          v-model="password"
          class="input"
          type="password"
          autocomplete="off"
          placeholder="输入空间密码"
          aria-label="空间密码"
          required
          :disabled="busy"
        />
      </label>

      <p v-if="error" class="space-gate-error" role="alert">{{ error }}</p>

      <div class="space-gate-actions">
        <button type="button" class="btn btn-ghost" :disabled="busy" @click="handleClose">取消</button>
        <button type="submit" class="btn btn-primary" :disabled="busy || !password">
          {{ busy ? '验证中…' : (confirmLabel ?? '解锁') }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.space-gate-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(15, 23, 42, 0.45);
}
.space-gate-card {
  width: min(440px, 100%);
  padding: 22px;
  border-radius: var(--r-xl, 16px);
  border: 1px solid var(--line);
  background: var(--solid);
  box-shadow: var(--shadow-pop);
  display: grid;
  gap: 16px;
}
.space-gate-head {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.space-gate-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: grid;
  place-items: center;
  background: var(--surface-3);
  color: var(--accent);
  flex-shrink: 0;
}
.space-gate-titles h3 {
  margin: 0;
  font-size: 16px;
}
.space-gate-titles p {
  margin: 4px 0 0;
  font-size: 12.5px;
  line-height: 1.5;
}
.space-gate-field {
  display: grid;
  gap: 6px;
  font-size: 12.5px;
  color: var(--text-2, var(--muted));
}
.space-gate-error {
  margin: 0;
  font-size: 12.5px;
  color: var(--danger);
}
.space-gate-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
