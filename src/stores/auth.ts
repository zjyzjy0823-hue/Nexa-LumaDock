import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import { apiRequest, ApiError } from '../api/client'
import type { User } from '../types/widget'

const tokenKey = 'nexa:access-token'

export const useAuthStore = defineStore('auth', () => {
  localStorage.removeItem('nexa:local-account:v1')
  const token = ref<string | null>(localStorage.getItem(tokenKey))
  const user = ref<User | null>(null)
  let sessionGeneration = 0
  watch(token, () => { sessionGeneration += 1 }, { flush: 'sync' })

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

  async function signIn(username: string, password: string) {
    const result = await apiRequest<{ access_token: string }>('/api/v1/auth/login', {
      method: 'POST', body: JSON.stringify({ username, password }),
    })
    token.value = result.access_token
    localStorage.setItem(tokenKey, result.access_token)
    await restore()
  }

  async function register(username: string, password: string) {
    const result = await apiRequest<{ access_token: string }>('/api/v1/auth/register', {
      method: 'POST', body: JSON.stringify({ username, password }),
    })
    token.value = result.access_token
    localStorage.setItem(tokenKey, result.access_token)
    await restore()
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem(tokenKey)
  }

  return { token, user, restore, signIn, register, logout }
})
