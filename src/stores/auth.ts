import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiRequest, ApiError } from '../api/client'
import type { User } from '../types/widget'

const tokenKey = 'nexa:access-token'
const localAccountKey = 'nexa:local-account:v1'
type LocalAccount = { username: string; email: string; password: string }

function localAccount(): { credentials: LocalAccount; created: boolean } {
  try {
    const saved = JSON.parse(localStorage.getItem(localAccountKey) || 'null') as LocalAccount | null
    if (saved?.username && saved.email && saved.password) return { credentials: saved, created: false }
  } catch { /* Replace an invalid local account record. */ }
  const id = crypto.randomUUID().replaceAll('-', '')
  const credentials = {
    username: `local_${id.slice(0, 20)}`,
    email: `local_${id}@nexa.local`,
    password: `${crypto.randomUUID()}${crypto.randomUUID()}`,
  }
  localStorage.setItem(localAccountKey, JSON.stringify(credentials))
  return { credentials, created: true }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem(tokenKey))
  const user = ref<User | null>(null)

  async function restore() {
    if (!token.value) return
    try {
      user.value = await apiRequest<User>('/api/auth/me', {}, token.value)
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) logout()
      throw error
    }
  }

  async function signIn(email: string, password: string) {
    const result = await apiRequest<{ access_token: string }>('/api/auth/login', {
      method: 'POST', body: JSON.stringify({ email, password }),
    })
    token.value = result.access_token
    localStorage.setItem(tokenKey, result.access_token)
    await restore()
  }

  async function register(username: string, email: string, password: string) {
    const result = await apiRequest<{ access_token: string }>('/api/auth/register', {
      method: 'POST', body: JSON.stringify({ username, email, password }),
    })
    token.value = result.access_token
    localStorage.setItem(tokenKey, result.access_token)
    await restore()
  }

  async function ensureLocalAccount(): Promise<boolean> {
    if (token.value) {
      try {
        await restore()
        return false
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 401) throw error
      }
    }
    const { credentials, created } = localAccount()
    if (created) {
      try {
        await register(credentials.username, credentials.email, credentials.password)
        return true
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 409) throw error
        await signIn(credentials.email, credentials.password)
        return false
      }
    }
    try {
      await signIn(credentials.email, credentials.password)
      return false
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error
      await register(credentials.username, credentials.email, credentials.password)
      return true
    }
  }

  function logout() {
    token.value = null
    user.value = null
    localStorage.removeItem(tokenKey)
  }

  return { token, user, restore, signIn, register, ensureLocalAccount, logout }
})
