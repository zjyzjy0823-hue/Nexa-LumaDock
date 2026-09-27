import { defineStore } from 'pinia'
import { ref } from 'vue'
import { deviceService } from '../services/devices'
import type { Device, DeviceInput } from '../types/device'

export const useDevicesStore = defineStore('devices', () => {
  const devices = ref<Device[]>([])
  const loading = ref(false)
  const error = ref('')
  const loadedAt = ref<Date | null>(null)
  let sequence = 0

  async function load(token: string, force = false) {
    if (!force && (loading.value || (loadedAt.value && Date.now() - loadedAt.value.getTime() < 30_000))) return
    const current = ++sequence
    loading.value = true
    error.value = ''
    try {
      const items = await deviceService.list(token)
      if (current === sequence) { devices.value = items; loadedAt.value = new Date() }
    } catch (cause) {
      if (current === sequence) { devices.value = []; loadedAt.value = null; error.value = cause instanceof Error ? cause.message : '设备加载失败' }
    } finally { if (current === sequence) loading.value = false }
  }
  async function create(token: string, data: DeviceInput) {
    const current = sequence
    const item = await deviceService.create(token, data)
    if (current === sequence) devices.value.unshift(item)
    return item
  }
  async function update(token: string, id: string, data: Partial<DeviceInput>) {
    const current = sequence
    const item = await deviceService.update(token, id, data)
    if (current === sequence) devices.value = devices.value.map(old => old.id === id ? item : old)
    return item
  }
  async function remove(token: string, id: string) {
    const current = sequence
    await deviceService.remove(token, id)
    if (current === sequence) devices.value = devices.value.filter(item => item.id !== id)
  }
  async function generateToken(token: string, id: string) {
    const result = await deviceService.generateToken(token, id)
    devices.value = devices.value.map(item => item.id === id
      ? { ...item, tokenLast4: result.last4, tokenCreatedAt: result.createdAt } : item)
    return result
  }
  async function revokeToken(token: string, id: string) {
    await deviceService.revokeToken(token, id)
    devices.value = devices.value.map(item => item.id === id
      ? { ...item, tokenLast4: null, tokenCreatedAt: null } : item)
  }
  function reset() { ++sequence; devices.value = []; loading.value = false; error.value = ''; loadedAt.value = null }
  return { devices, loading, error, loadedAt, load, create, update, remove, generateToken, revokeToken, reset }
})
