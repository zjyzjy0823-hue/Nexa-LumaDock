import { defineStore } from 'pinia'
import { ref } from 'vue'
import { websiteService, type WebsiteFilters } from '../services/websites'
import type { Website, WebsiteCategory, WebsiteInput } from '../types/website'

export const useWebsitesStore = defineStore('websites', () => {
  const websites = ref<Website[]>([])
  const categories = ref<WebsiteCategory[]>([])
  const recent = ref<Website[]>([])
  const recentLoading = ref(false)
  const recentError = ref('')
  const recentLoadedAt = ref(0)
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
  async function create(token: string, data: WebsiteInput) {
    const current = sequence
    const item = await websiteService.create(token, data)
    if (current === sequence) websites.value.push(item)
  }
  async function loadRecent(token: string) {
    if (recentLoading.value || (recentLoadedAt.value && Date.now() - recentLoadedAt.value < 30_000)) return
    const current = sequence
    recentLoading.value = true
    recentError.value = ''
    try {
      const items = (await websiteService.list(token, { sort: 'recent' })).filter(item => item.lastVisitedAt).slice(0, 8)
      if (current === sequence) { recent.value = items; recentLoadedAt.value = Date.now() }
    } catch (cause) {
      if (current === sequence) { recent.value = []; recentLoadedAt.value = 0; recentError.value = cause instanceof Error ? cause.message : '网站加载失败' }
    } finally { if (current === sequence) recentLoading.value = false }
  }
  async function visit(token: string, id: string) {
    const current = sequence
    const item = await websiteService.visit(token, id)
    if (current !== sequence) return
    websites.value = websites.value.map(old => old.id === id ? item : old)
    recent.value = [item, ...recent.value.filter(old => old.id !== id)].slice(0, 8)
    recentLoadedAt.value = Date.now()
  }
  async function update(token: string, id: string, data: Partial<WebsiteInput>) {
    const current = sequence
    const item = await websiteService.update(token, id, data)
    if (current === sequence) websites.value = websites.value.map(old => old.id === id ? item : old)
  }
  async function remove(token: string, id: string) {
    const current = sequence
    await websiteService.remove(token, id)
    if (current !== sequence) return
    websites.value = websites.value.filter(item => item.id !== id)
    recent.value = recent.value.filter(item => item.id !== id)
  }
  async function createCategory(token: string, name: string) {
    const current = sequence
    const item = await websiteService.createCategory(token, { name, order: categories.value.length })
    if (current === sequence) categories.value.push(item)
  }
  async function renameCategory(token: string, id: string, name: string) {
    const current = sequence
    const item = await websiteService.updateCategory(token, id, { name })
    if (current === sequence) categories.value = categories.value.map(old => old.id === id ? item : old)
  }
  async function removeCategory(token: string, id: string) {
    const current = sequence
    await websiteService.removeCategory(token, id)
    if (current !== sequence) return
    categories.value = categories.value.filter(item => item.id !== id)
    websites.value = websites.value.map(item => item.categoryId === id ? { ...item, categoryId: null } : item)
  }
  function reset() { ++sequence; websites.value = []; recent.value = []; categories.value = []; error.value = ''; loading.value = false; recentLoading.value = false; recentError.value = ''; recentLoadedAt.value = 0 }
  return { websites, recent, categories, loading, error, recentLoading, recentError, load, loadRecent, visit, create, update, remove, createCategory, renameCategory, removeCategory, reset }
})
