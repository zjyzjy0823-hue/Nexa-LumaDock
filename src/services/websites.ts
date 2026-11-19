import { apiRequest } from '../api/client'
import { androidInvoke, isAndroidLocal } from '../desktop/androidLocal'
import type { Website, WebsiteCategory, WebsiteInput } from '../types/website'

const root = '/api/v1'
export interface WebsiteFilters { categoryId?: string; search?: string; favorite?: boolean; sort?: 'order' | 'name' | 'createdAt' | 'updatedAt' | 'recent' }

export const websiteService = {
  list(token: string, filters: WebsiteFilters = {}) {
    if (isAndroidLocal()) return androidInvoke<Website[]>('android_websites_list', { filters })
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== '') query.set(key, String(value))
    return apiRequest<Website[]>(`${root}/websites?${query}`, {}, token)
  },
  create(token: string, data: WebsiteInput) {
    if (isAndroidLocal()) return androidInvoke<Website>('android_website_create', { data })
    return apiRequest<Website>(`${root}/websites`, { method: 'POST', body: JSON.stringify(data) }, token)
  },
  update(token: string, id: string, data: Partial<WebsiteInput>) {
    if (isAndroidLocal()) return androidInvoke<Website>('android_website_update', { id, data })
    return apiRequest<Website>(`${root}/websites/${id}`, { method: 'PATCH', body: JSON.stringify(data) }, token)
  },
  remove(token: string, id: string) {
    if (isAndroidLocal()) return androidInvoke<void>('android_website_delete', { id })
    return apiRequest<void>(`${root}/websites/${id}`, { method: 'DELETE' }, token)
  },
  visit(token: string, id: string) {
    if (isAndroidLocal()) return androidInvoke<Website>('android_website_visit', { id })
    return apiRequest<Website>(`${root}/websites/${id}/visit`, { method: 'POST' }, token)
  },
  categories(token: string) {
    if (isAndroidLocal()) return androidInvoke<WebsiteCategory[]>('android_website_categories_list')
    return apiRequest<WebsiteCategory[]>(`${root}/website-categories`, {}, token)
  },
  createCategory(token: string, data: Pick<WebsiteCategory, 'name' | 'order'>) {
    if (isAndroidLocal()) return androidInvoke<WebsiteCategory>('android_website_categories_create', { data })
    return apiRequest<WebsiteCategory>(`${root}/website-categories`, { method: 'POST', body: JSON.stringify(data) }, token)
  },
  updateCategory(token: string, id: string, data: Partial<Pick<WebsiteCategory, 'name' | 'order'>>) {
    if (isAndroidLocal()) return androidInvoke<WebsiteCategory>('android_website_categories_update', { id, data })
    return apiRequest<WebsiteCategory>(`${root}/website-categories/${id}`, { method: 'PATCH', body: JSON.stringify(data) }, token)
  },
  removeCategory(token: string, id: string) {
    if (isAndroidLocal()) return androidInvoke<void>('android_website_categories_delete', { id })
    return apiRequest<void>(`${root}/website-categories/${id}`, { method: 'DELETE' }, token)
  },
}
