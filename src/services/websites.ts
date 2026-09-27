import { apiRequest } from '../api/client'
import type { Website, WebsiteCategory, WebsiteInput } from '../types/website'

const root = '/api/v1'
export interface WebsiteFilters { categoryId?: string; search?: string; favorite?: boolean; sort?: 'order' | 'name' | 'createdAt' | 'updatedAt' | 'recent' }

export const websiteService = {
  list(token: string, filters: WebsiteFilters = {}) {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) if (value !== undefined && value !== '') query.set(key, String(value))
    return apiRequest<Website[]>(`${root}/websites?${query}`, {}, token)
  },
  create(token: string, data: WebsiteInput) { return apiRequest<Website>(`${root}/websites`, { method: 'POST', body: JSON.stringify(data) }, token) },
  update(token: string, id: string, data: Partial<WebsiteInput>) { return apiRequest<Website>(`${root}/websites/${id}`, { method: 'PATCH', body: JSON.stringify(data) }, token) },
  remove(token: string, id: string) { return apiRequest<void>(`${root}/websites/${id}`, { method: 'DELETE' }, token) },
  visit(token: string, id: string) { return apiRequest<Website>(`${root}/websites/${id}/visit`, { method: 'POST' }, token) },
  categories(token: string) { return apiRequest<WebsiteCategory[]>(`${root}/website-categories`, {}, token) },
  createCategory(token: string, data: Pick<WebsiteCategory, 'name' | 'order'>) { return apiRequest<WebsiteCategory>(`${root}/website-categories`, { method: 'POST', body: JSON.stringify(data) }, token) },
  updateCategory(token: string, id: string, data: Partial<Pick<WebsiteCategory, 'name' | 'order'>>) { return apiRequest<WebsiteCategory>(`${root}/website-categories/${id}`, { method: 'PATCH', body: JSON.stringify(data) }, token) },
  removeCategory(token: string, id: string) { return apiRequest<void>(`${root}/website-categories/${id}`, { method: 'DELETE' }, token) },
}
