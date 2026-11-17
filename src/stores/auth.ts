import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { apiRequest, ApiError } from '../api/client'
import type { CoreConnectRequest } from '../api/core'
import type { User } from '../types/widget'

export interface AuthStatus {
  mode: 'local' | 'core'
  workstation: boolean
  setupRequired: boolean
  allowRegistration: boolean
}

const tokenKey = 'studiolo:access-token'

export const useAuthStore = defineStore('auth', () => {
  localStorage.removeItem('studiolo:local-account:v1')
  const token = ref<string | null>(localStorage.getItem(tokenKey))
  const user = ref<User | null>(null)
  const workstation = ref(false)
  const setupRequired = ref(false)
  const allowRegistration = ref(true)
  let sessionGeneration = 0
  watch(token, () => { sessionGeneration += 1 }, { flush: 'sync' })

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
    let status: AuthStatus | null = null
    try {
      status = await apiRequest<AuthStatus>('/api/v1/auth/status')
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
    logout,
  }
})
