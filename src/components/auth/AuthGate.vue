<script setup lang="ts">
import { ref } from 'vue'
import { ArrowRight, LockKeyhole } from 'lucide-vue-next'
import { ApiError } from '../../api/client'
import { useAuthStore } from '../../stores/auth'

const auth = useAuthStore()
const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const confirmation = ref('')
const busy = ref(false)
const error = ref('')

function setMode(next: 'login' | 'register') {
  mode.value = next
  error.value = ''
  password.value = ''
  confirmation.value = ''
}

async function submit() {
  const name = username.value.trim()
  if (name.length < 3) { error.value = '用户名至少需要 3 个字符。'; return }
  if (password.value.length < 8) { error.value = '密码至少需要 8 个字符。'; return }
  if (mode.value === 'register' && password.value !== confirmation.value) { error.value = '两次输入的密码不一致。'; return }
  busy.value = true
  error.value = ''
  try {
    if (mode.value === 'login') await auth.signIn(name, password.value)
    else await auth.register(name, password.value)
    password.value = ''
    confirmation.value = ''
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 401) error.value = '用户名或密码不正确。'
    else if (cause instanceof ApiError && cause.status === 409) error.value = '这个用户名已被使用。'
    else if (cause instanceof ApiError && cause.status === 403) error.value = '当前系统已关闭注册。'
    else error.value = cause instanceof Error ? cause.message : '操作失败，请稍后重试。'
  } finally { busy.value = false }
}
</script>

<template>
  <main class="auth-screen">
    <section class="auth-card" aria-label="Nexa 账户">
      <div class="auth-brand"><img src="/nexa-app-icon.png" alt="" /><span>Nexa</span></div>
      <div class="auth-intro"><span>PERSONAL SPACE</span><h1>欢迎来到 Nexa</h1><p>登录后进入你的个人控制中心。</p></div>
      <div class="auth-tabs" role="tablist" aria-label="账户操作">
        <button type="button" role="tab" :aria-selected="mode === 'login'" :class="{ active: mode === 'login' }" @click="setMode('login')">登录</button>
        <button type="button" role="tab" :aria-selected="mode === 'register'" :class="{ active: mode === 'register' }" @click="setMode('register')">注册</button>
      </div>
      <form class="auth-form" @submit.prevent="submit">
        <label>用户名<input v-model="username" name="username" autocomplete="username" minlength="3" maxlength="80" placeholder="输入用户名" required /></label>
        <label>密码<input v-model="password" name="password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" minlength="8" placeholder="至少 8 个字符" required /></label>
        <label v-if="mode === 'register'">确认密码<input v-model="confirmation" name="confirmation" type="password" autocomplete="new-password" minlength="8" placeholder="再次输入密码" required /></label>
        <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
        <button class="auth-submit" type="submit" :disabled="busy"><span>{{ busy ? '请稍候…' : mode === 'login' ? '进入 Nexa' : '创建账户' }}</span><ArrowRight :size="18" /></button>
      </form>
      <div class="auth-foot"><LockKeyhole :size="14" />你的数据保存在自己的 Nexa 服务中</div>
    </section>
  </main>
</template>

<style scoped>
.auth-screen { display:grid; min-height:100dvh; place-items:center; padding:24px; background:linear-gradient(rgba(24,31,77,.2),rgba(13,24,67,.42)),url('/nexa-wallpaper.png') center/cover fixed; }
.auth-card { width:min(100%,430px); padding:32px; color:#273b65; border:1px solid rgba(255,255,255,.7); border-radius:28px; background:linear-gradient(145deg,rgba(252,253,255,.93),rgba(226,235,255,.87)); box-shadow:0 30px 90px rgba(15,29,79,.34),inset 0 1px rgba(255,255,255,.95); backdrop-filter:blur(30px) saturate(145%); -webkit-backdrop-filter:blur(30px) saturate(145%); }
.auth-brand { display:flex; align-items:center; gap:10px; color:#30436c; font-size:22px; font-weight:700; letter-spacing:-.04em; }
.auth-brand img { width:36px; height:36px; border-radius:10px; box-shadow:0 4px 12px rgba(32,48,95,.16); }
.auth-intro { margin:28px 0 24px; }.auth-intro span { color:#7a8db8; font-size:10px; font-weight:800; letter-spacing:.16em; }.auth-intro h1 { margin:8px 0 5px; font-size:30px; font-weight:730; letter-spacing:-.04em; }.auth-intro p { margin:0; color:#7888a5; font-size:13px; }
.auth-tabs { display:flex; gap:4px; padding:4px; border:1px solid rgba(160,178,216,.35); border-radius:12px; background:rgba(218,229,250,.62); }.auth-tabs button { flex:1; height:35px; color:#7789aa; border:0; border-radius:9px; background:transparent; font-size:13px; font-weight:680; cursor:pointer; }.auth-tabs button.active { color:#4e68b1; background:rgba(255,255,255,.92); box-shadow:0 3px 9px rgba(39,59,112,.1); }
.auth-form { display:grid; gap:14px; margin-top:20px; }.auth-form label { display:grid; gap:7px; color:#4a5d7d; font-size:12px; font-weight:680; }.auth-form input { height:44px; padding:0 13px; color:#26395b; border:1px solid rgba(152,173,215,.55); border-radius:11px; outline:none; background:rgba(255,255,255,.82); font:inherit; font-weight:500; }.auth-form input:focus { border-color:#7895de; box-shadow:0 0 0 3px rgba(116,147,222,.14); }.auth-form input::placeholder { color:#a6b3c9; }.auth-error { margin:0; color:#b74355; font-size:12px; }
.auth-submit { display:flex; align-items:center; justify-content:center; gap:9px; height:45px; margin-top:4px; color:white; border:1px solid rgba(92,120,201,.55); border-radius:11px; background:linear-gradient(120deg,#6988d9,#6d76c9); box-shadow:0 9px 19px rgba(76,100,180,.22); font-size:13px; font-weight:700; cursor:pointer; }.auth-submit:disabled { opacity:.6; cursor:wait; }
.auth-foot { display:flex; align-items:center; justify-content:center; gap:6px; margin-top:21px; color:#8190aa; font-size:11px; }
@media(max-width:480px) { .auth-card { padding:25px 21px; }.auth-intro h1 { font-size:27px; } }
</style>
