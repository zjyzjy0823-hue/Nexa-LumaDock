import { defineStore } from 'pinia'
import { ref } from 'vue'
import { websiteService, type WebsiteFilters } from '../services/websites'
import type { Website, WebsiteCategory, WebsiteInput } from '../types/website'

export const useWebsitesStore = defineStore('websites', () => {
  const websites = ref<Website[]>([])
  const categories = ref<WebsiteCategory[]>([])
  const recent = ref<Website[]>([])
  const loading = ref(false)
  const error = ref('')
  let sequence = 0

  async function load(token: string, filters: WebsiteFilters = {}) {
    const current = ++sequence
    loading.value = true
    error.value = ''
    try {
      const [items, groups] = await Promise.all([websiteService.list(token, filters), websiteService.categories(token)])
      if (current === sequence) { websites.value = items; categories.value = groups }
    } catch (cause) {
      if (current === sequence) error.value = cause instanceof Error ? cause.message : '加载失败'
    } finally { if (current === sequence) loading.value = false }
  }
  async function create(token: string, data: WebsiteInput) { websites.value.push(await websiteService.create(token, data)) }
  async function loadRecent(token: string) {
    recent.value = (await websiteService.list(token, { sort: 'recent' })).filter(item => item.lastVisitedAt).slice(0, 8)
  }
  async function visit(token: string, id: string) {
    const item = await websiteService.visit(token, id)
    websites.value = websites.value.map(old => old.id === id ? item : old)
    recent.value = [item, ...recent.value.filter(old => old.id !== id)].slice(0, 8)
  }
  async function update(token: string, id: string, data: Partial<WebsiteInput>) {
    const item = await websiteService.update(token, id, data)
    websites.value = websites.value.map(old => old.id === id ? item : old)
  }
  async function remove(token: string, id: string) {
    await websiteService.remove(token, id)
    websites.value = websites.value.filter(item => item.id !== id)
    recent.value = recent.value.filter(item => item.id !== id)
  }
  async function createCategory(token: string, name: string) {
    categories.value.push(await websiteService.createCategory(token, { name, order: categories.value.length }))
  }
  async function renameCategory(token: string, id: string, name: string) {
    const item = await websiteService.updateCategory(token, id, { name })
    categories.value = categories.value.map(old => old.id === id ? item : old)
  }
  async function removeCategory(token: string, id: string) {
    await websiteService.removeCategory(token, id)
    categories.value = categories.value.filter(item => item.id !== id)
    websites.value = websites.value.map(item => item.categoryId === id ? { ...item, categoryId: null } : item)
  }
  function reset() { ++sequence; websites.value = []; recent.value = []; categories.value = []; error.value = ''; loading.value = false }
  return { websites, recent, categories, loading, error, load, loadRecent, visit, create, update, remove, createCategory, renameCategory, removeCategory, reset }
})
