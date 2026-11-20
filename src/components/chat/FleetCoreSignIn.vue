<script setup lang="ts">
import { ref } from 'vue'
import { ApiError } from '../../api/client'
import { useFleetStore } from '../../stores/fleet'

const props = withDefaults(defineProps<{ feature?: string }>(), { feature: '对话' })
const fleet = useFleetStore()
const username = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')

async function signIn() {
  if (busy.value) return
  error.value = ''
  busy.value = true
  try {
    await fleet.signInToCoreFleet(username.value.trim(), password.value)
  } catch (cause) {
    error.value = cause instanceof ApiError && cause.status === 401 ? 'Core 用户名或密码不正确。'
      : cause instanceof Error ? cause.message : 'Core 登录失败。'
  } finally {
    password.value = ''
    busy.value = false
  }
}
</script>

<template>
  <form class="card mat core-fleet-sign-in" :aria-label="'登录 Core ' + props.feature" @submit.prevent="signIn">
    <h3>登录 Core {{ props.feature }}</h3>
    <p>{{ fleet.coreSignInUrl }}</p>
    <label>Core 用户名<input v-model="username" class="input" autocomplete="username" required /></label>
    <label>Core 密码<input v-model="password" class="input" type="password" autocomplete="current-password" required /></label>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <button type="submit" class="btn btn-primary" :disabled="busy">{{ busy ? '正在登录…' : '登录 Core ' + props.feature }}</button>
  </form>
</template>

<style scoped>
.core-fleet-sign-in { display: grid; gap: 12px; width: min(100%, 420px); margin: 20px auto; padding: 20px; }
h3, p { margin: 0; overflow-wrap: anywhere; }
label { display: grid; gap: 6px; }
.error { color: var(--danger); }
</style>
