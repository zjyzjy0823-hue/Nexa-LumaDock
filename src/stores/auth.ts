import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { apiRequest, ApiError } from '../api/client'
import type { CoreConnection, CoreConnectRequest } from '../api/core'
import { desktopPlatform } from '../desktop/platform'
import { normalizeCoreOrigin, setApiBaseUrl } from '../services/fleetUrl'
import type { User } from '../types/widget'

export interface AuthStatus {
  mode: 'local' | 'core'
  workstation: boolean
  setupRequired: boolean
  allowRegistration: boolean
}

const tokenKey = 'studiolo:access-token'
const androidCoreKey = 'studiolo:android-core'

export const useAuthStore = defineStore('auth', () => {
  localStorage.removeItem('studiolo:local-account:v1')
  const android = desktopPlatform() === 'android'
  const androidCoreUrl = ref('')
  if (android) {
    const savedOrigin = localStorage.getItem(androidCoreKey)
    if (savedOrigin) {
      try { androidCoreUrl.value = normalizeCoreOrigin(savedOrigin) } catch { localStorage.removeItem(androidCoreKey) }
    }
    if (!androidCoreUrl.value) localStorage.removeItem(tokenKey)
    setApiBaseUrl(androidCoreUrl.value)
  }
  const token = ref<string | null>(localStorage.getItem(tokenKey))
  const user = ref<User | null>(null)
  const mode = ref<AuthStatus['mode']>(android ? 'core' : 'local')
  const coreConnection = ref<CoreConnection>()
  const workstation = ref(false)
  const setupRequired = ref(false)
  const allowRegistration = ref(true)
  let sessionGeneration = 0
  watch(token, () => { sessionGeneration += 1; coreConnection.value = undefined }, { flush: 'sync' })

  function setSessionToken(next: string) {
    token.value = next
    localStorage.setItem(tokenKey, next)
  }

  async function restore() {
    const restoredToken = token.value
    if (!restoredToken) return
    const restoredGeneration = sessionGeneration
    const current = () => token.value === restoredToken && sessionGeneration === restoredGeneration
    try {
      const restoredUser = await apiRequest<User>('/api/v1/auth/me', {}, restoredToken)
      if (current()) user.value = restoredUser
    } catch (error) {
      if (current() && error instanceof ApiError && error.status === 401) logout()
      throw error
    }
  }

  async function resumeWorkstation() {
    const result = await apiRequest<{ access_token: string }>('/api/v1/auth/workstation/session', { method: 'POST' })
    setSessionToken(result.access_token)
    setupRequired.value = false
    await restore()
  }

  async function bootstrap() {
    if (android && !androidCoreUrl.value) return
    let status: AuthStatus | null = null
    try {
      status = await apiRequest<AuthStatus>('/api/v1/auth/status')
      if (android && status.mode !== 'core') throw new Error('此地址未运行 Studiolo Core。')
      mode.value = status.mode
      workstation.value = status.workstation
      setupRequired.value = status.setupRequired
      allowRegistration.value = status.allowRegistration
    } catch (error) {
      // 仅当 /auth/status 404（老后端兼容）时按传统 token 恢复流程处理；网络/5xx 向上抛出启动错误。
      if (!(error instanceof ApiError && error.status === 404)) throw error
    }

    if (status?.workstation && status.setupRequired) {
      if (token.value) logout()
      return
    }

    if (token.value) {
      try {
        await restore()
        return
      } catch (error) {
        if (error instanceof ApiError && error.status === 401 && status?.workstation) {
          await resumeWorkstation()
          return
        }
        if (android && error instanceof ApiError && error.status === 401) return
        throw error
      }
    }

    if (status?.workstation) {
      try {
        await resumeWorkstation()
      } catch (error) {
        if (error instanceof ApiError && (error.status === 404 || error.status === 409)) {
          setupRequired.value = error.status === 404
          return
        }
        throw error
      }
    }
  }

  async function setAndroidCore(value: string) {
    const origin = normalizeCoreOrigin(value)
    const status = await apiRequest<AuthStatus>('/api/v1/auth/status', {}, null, origin)
    if (status.mode !== 'core') throw new Error('此地址未运行 Studiolo Core。')
    logout()
    localStorage.setItem(androidCoreKey, origin)
    androidCoreUrl.value = origin
    setApiBaseUrl(origin)
    allowRegistration.value = status.allowRegistration
  }

  function clearAndroidCore() {
    logout()
    localStorage.removeItem(androidCoreKey)
    androidCoreUrl.value = ''
    setApiBaseUrl('')
  }

  async function signIn(username: string, password: string) {
    const result = await apiRequest<{ access_token: string }>('/api/v1/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }),
    })
    setSessionToken(result.access_token)
    await restore()
  }

  async function register(username: string, password: string) {
    const result = await apiRequest<{ access_token: string }>('/api/v1/auth/register', {
      method: 'POST', body: JSON.stringify({ username, password }),
    })
    setSessionToken(result.access_token)
    await restore()
  }

  async function setupOffline() {
    const result = await apiRequest<{ access_token: string }>('/api/v1/auth/workstation/setup', {
      method: 'POST', body: JSON.stringify({ mode: 'offline' }),
    })
    setSessionToken(result.access_token)
    setupRequired.value = false
    await restore()
  }

  async function setupWithCore(payload: CoreConnectRequest) {
    const result = await apiRequest<{ access_token: string }>('/api/v1/auth/workstation/setup', {
      method: 'POST', body: JSON.stringify({ mode: 'core', ...payload }),
    })
    setSessionToken(result.access_token)
    setupRequired.value = false
    await restore()
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem(tokenKey)
  }

  return {
    token,
    user,
    mode,
    coreConnection,
    androidCoreUrl,
    workstation,
    setupRequired,
    allowRegistration,
    bootstrap,
    restore,
    resumeWorkstation,
    signIn,
    register,
    setupOffline,
    setupWithCore,
    setAndroidCore,
    clearAndroidCore,
    logout,
  }
})
