<script setup lang="ts">
import { computed, ref } from 'vue'
import { Cloud, Laptop } from 'lucide-vue-next'
import { version } from '../../../package.json'
import { ApiError } from '../../api/client'
import type { CorePlatform } from '../../api/core'
import { desktopPlatform } from '../../desktop/platform'
import { useAuthStore } from '../../stores/auth'
import OpusIcon from '../ui/OpusIcon.vue'
import OpusSegment from '../ui/OpusSegment.vue'
import StudioloMark from '../ui/StudioloMark.vue'

const auth = useAuthStore()
const platform = desktopPlatform()
const platformLabels: Record<CorePlatform, string> = {
  windows: 'Windows',
  macos: 'macOS',
  linux: 'Linux',
  android: 'Android',
  ios: 'iOS',
  web: 'Web',
}
const isMobileViewport = typeof window !== 'undefined' && window.matchMedia('(max-width: 700px)').matches
const defaultClientName = platform === 'web' && isMobileViewport
  ? 'Studiolo Mobile'
  : `Studiolo ${platformLabels[platform as CorePlatform] ?? 'Desktop'}`

// 传统 Web / 多账号登录注册状态
const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const confirmation = ref('')

// 本地首次初始化向导状态（方案 2：离线使用 / 连接已有 Core）
const wizardStep = ref<'choose' | 'core'>('choose')
const coreUrl = ref('')
const coreUsername = ref('')
const corePassword = ref('')
const clientName = ref(defaultClientName)

const busy = ref(false)
const busyKind = ref<'offline' | 'core' | 'auth' | null>(null)
const error = ref('')

const canRegister = computed(() => auth.allowRegistration)

function setMode(next: 'login' | 'register') {
  mode.value = next
  error.value = ''
  password.value = ''
  confirmation.value = ''
}

function openCoreSetup() {
  error.value = ''
  wizardStep.value = 'core'
}

function backToChoose() {
  if (busy.value) return
  error.value = ''
  corePassword.value = ''
  wizardStep.value = 'choose'
}

async function startOffline() {
  if (busy.value) return
  busy.value = true
  busyKind.value = 'offline'
  error.value = ''
  try {
    await auth.setupOffline()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '初始化失败，请稍后重试。'
  } finally {
    busy.value = false
    busyKind.value = null
  }
}

async function submitCoreSetup() {
  if (busy.value) return
  const rawUrl = coreUrl.value.trim()
  try {
    const parsed = new URL(rawUrl)
    if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname) throw new Error()
  } catch {
    error.value = '请输入有效的 Core HTTP 或 HTTPS 地址。'
    return
  }
  const account = coreUsername.value.trim()
  const name = clientName.value.trim() || defaultClientName
  if (!account || !corePassword.value) {
    error.value = '请输入 Core 用户名和密码。'
    return
  }
  busy.value = true
  busyKind.value = 'core'
  error.value = ''
  try {
    await auth.setupWithCore({
      coreUrl: rawUrl,
      username: account,
      password: corePassword.value,
      clientName: name,
      platform: (platform as CorePlatform) || 'windows',
      appVersion: version,
    })
    corePassword.value = ''
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 401) error.value = 'Core 用户名或密码不正确。'
    else if (cause instanceof ApiError && cause.status === 502) error.value = '无法连接到指定的 Core 服务器，请检查地址与网络。'
    else error.value = cause instanceof Error ? cause.message : '连接 Core 失败，请稍后重试。'
  } finally {
    busy.value = false
    busyKind.value = null
  }
}

async function submit() {
  const name = username.value.trim()
  if (name.length < 3) { error.value = '用户名至少需要 3 个字符。'; return }
  if (password.value.length < 8) { error.value = '密码至少需要 8 个字符。'; return }
  if (mode.value === 'register' && password.value !== confirmation.value) { error.value = '两次输入的密码不一致。'; return }
  busy.value = true
  busyKind.value = 'auth'
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
  } finally {
    busy.value = false
    busyKind.value = null
  }
}
</script>

<template>
  <main class="auth-screen">
    <div class="glass-wallpaper" aria-hidden="true"></div>
    <section class="auth-card mat enter" :aria-label="auth.setupRequired ? '初始化 Studiolo' : 'Studiolo 账户'">
      <header class="auth-head">
        <span class="logo auth-logo" aria-hidden="true"><StudioloMark /></span>
        <h1 class="auth-title">Studiolo</h1>
      </header>

      <template v-if="auth.setupRequired">
        <div v-if="wizardStep === 'choose'" class="setup-choices">
          <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
          <button class="btn btn-primary setup-primary" type="button" :disabled="busy" @click="startOffline">
            <Laptop :size="18" :stroke-width="1.9" />
            <span class="setup-copy">
              <strong>{{ busyKind === 'offline' ? '正在进入工作台…' : '立即离线使用' }}</strong>
              <small>数据保存在本机，无需账号</small>
            </span>
            <OpusIcon name="arrowUp" style="rotate:90deg" />
          </button>
          <button class="setup-option" type="button" :disabled="busy" @click="openCoreSetup">
            <Cloud :size="18" :stroke-width="1.9" />
            <span class="setup-copy">
              <strong>连接 Studiolo Core</strong>
              <small>登录已有 Core 同步跨设备数据</small>
            </span>
            <OpusIcon name="chevR" />
          </button>
        </div>

        <form v-else class="auth-form" @submit.prevent="submitCoreSetup">
          <div class="setup-subhead">
            <button class="setup-back" type="button" :disabled="busy" @click="backToChoose"><OpusIcon name="chevL" />返回</button>
            <span>连接 Studiolo Core</span>
          </div>
          <label class="auth-field"><span>Core 服务器地址</span><input v-model="coreUrl" class="input" name="coreUrl" type="url" placeholder="https://core.example.com" required /></label>
          <label class="auth-field"><span>用户名</span><input v-model="coreUsername" class="input" name="coreUsername" autocomplete="username" placeholder="Core 账号用户名" required /></label>
          <label class="auth-field"><span>密码</span><input v-model="corePassword" class="input" name="corePassword" type="password" autocomplete="current-password" placeholder="Core 账号密码" required /></label>
          <label class="auth-field"><span>本机名称</span><input v-model="clientName" class="input" name="clientName" maxlength="120" placeholder="例如 Studiolo Windows" required /></label>
          <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
          <button class="btn btn-primary auth-submit" type="submit" :disabled="busy">
            <span>{{ busyKind === 'core' ? '正在连接与同步…' : '连接并进入' }}</span>
            <OpusIcon name="arrowUp" style="rotate:90deg" />
          </button>
        </form>
      </template>

      <template v-else>
        <OpusSegment v-if="canRegister" class="auth-seg" role="tablist" aria-label="账户操作">
          <button type="button" role="tab" :aria-pressed="mode === 'login'" :aria-selected="mode === 'login'" @click="setMode('login')">登录</button>
          <button type="button" role="tab" :aria-pressed="mode === 'register'" :aria-selected="mode === 'register'" @click="setMode('register')">注册</button>
        </OpusSegment>
        <form class="auth-form" @submit.prevent="submit">
          <label class="auth-field"><span>用户名</span><input v-model="username" class="input" name="username" autocomplete="username" minlength="3" maxlength="80" placeholder="输入用户名" required /></label>
          <label class="auth-field"><span>密码</span><input v-model="password" class="input" name="password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" minlength="8" placeholder="至少 8 个字符" required /></label>
          <label v-if="mode === 'register'" class="auth-field"><span>确认密码</span><input v-model="confirmation" class="input" name="confirmation" type="password" autocomplete="new-password" minlength="8" placeholder="再次输入密码" required /></label>
          <p v-if="error" class="auth-error" role="alert">{{ error }}</p>
          <button class="btn btn-primary auth-submit" type="submit" :disabled="busy"><span>{{ busy ? '请稍候…' : mode === 'login' ? '进入 Studiolo' : '创建账户' }}</span><OpusIcon name="arrowUp" style="rotate:90deg" /></button>
        </form>
      </template>
    </section>
  </main>
</template>

<style scoped>
.auth-screen { position: relative; isolation: isolate; display: grid; min-height: 100dvh; place-items: center; padding: 24px; background: var(--bg); overflow: auto; }
.desktop-body .auth-screen { min-height: 100%; }
.auth-card { position: relative; z-index: 1; width: min(100%, 376px); padding: 30px 28px 28px; border-radius: var(--r-md); box-shadow: var(--shadow-pop); }
.auth-head { display: grid; justify-items: center; gap: 10px; margin-bottom: 22px; text-align: center; }
.auth-logo { width: 38px; height: 38px; border-radius: 9px; }
.auth-logo svg { width: 20px; height: 20px; }
.auth-title { margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -.025em; line-height: 1.2; color: var(--text); }
.auth-seg { display: flex; width: 100%; margin-bottom: 18px; }
.auth-seg :deep(button) { flex: 1; justify-content: center; height: 32px; font-size: 13px; font-weight: 550; }
.setup-choices { display: grid; gap: 10px; }
.setup-primary,
.setup-option {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 12px;
  width: 100%;
  height: auto;
  min-height: 60px;
  padding: 12px 14px;
  border-radius: var(--r-sm);
  text-align: left;
  white-space: normal;
  transition: background-color var(--dur-1), border-color var(--dur-1), box-shadow var(--dur-1), scale var(--dur-1) var(--ease-out);
}
.setup-option:active:not(:disabled) { scale: calc(1 - .02 * var(--move)); }
.setup-option {
  border: 1px solid var(--line-strong);
  background: var(--solid);
  color: var(--text);
}
.setup-option:hover:not(:disabled) {
  background: var(--surface-2);
}
.setup-copy {
  display: grid;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.setup-copy strong { font-size: 14px; font-weight: 600; line-height: 1.25; }
.setup-copy small { font-size: 12px; line-height: 1.3; opacity: .78; }
.setup-subhead {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 2px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.setup-back {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  height: 26px;
  padding: 0 8px 0 4px;
  border-radius: 6px;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 500;
}
.setup-back:hover:not(:disabled) { background: var(--surface-3); color: var(--text); }
.setup-back svg { width: 14px; height: 14px; }
.auth-form { display: grid; gap: 13px; }
.auth-field { display: grid; gap: 6px; font-size: 12.5px; color: var(--text-2); font-weight: 550; }
.auth-field .input { height: 40px; font-size: 14px; border-radius: var(--r-sm); }
.auth-error { margin: 0; color: var(--danger); font-size: 12.5px; }
.auth-submit { width: 100%; height: 42px; margin-top: 4px; justify-content: center; gap: 8px; border-radius: var(--r-sm); font-size: 14.5px; font-weight: 600; }
@media (max-width: 480px) { .auth-card { padding: 26px 20px 22px; } }
</style>
