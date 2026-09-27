export interface Website {
  id: string
  name: string
  url: string
  icon?: string | null
  description?: string | null
  categoryId?: string | null
  favorite: boolean
  order: number
  createdAt: string
  updatedAt: string
  lastVisitedAt?: string | null
}

export interface WebsiteCategory {
  id: string
  name: string
  order: number
}

export type WebsiteInput = Pick<Website, 'name' | 'url' | 'favorite' | 'order'> &
  Partial<Pick<Website, 'icon' | 'description' | 'categoryId'>>
