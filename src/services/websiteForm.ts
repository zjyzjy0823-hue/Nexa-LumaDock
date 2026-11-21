import type { Website, WebsiteInput } from '../types/website'

export function websiteDraft(item?: Website) {
  return {
    name: item?.name ?? '',
    url: item?.url ?? '',
    icon: item?.icon ?? '',
    description: item?.description ?? '',
    categoryId: item?.categoryId ?? '',
    favorite: item?.favorite ?? false,
    order: item?.order ?? 0,
  }
}

export type WebsiteDraft = ReturnType<typeof websiteDraft>

export function normalizeWebsiteUrl(input: string): URL {
  const candidate = input.trim()
  const hasHttp = /^https?:\/\//i.test(candidate)
  if (!candidate || /\s/.test(candidate) || (/^[a-z][a-z0-9+.-]*:/i.test(candidate) && !hasHttp)) {
    throw new Error('请输入有效的 HTTP 或 HTTPS 网址。')
  }
  try {
    const url = new URL(hasHttp ? candidate : `https://${candidate}`)
    if (!url.hostname || url.href.length > 2048) throw new Error()
    return url
  } catch {
    throw new Error('请输入有效的 HTTP 或 HTTPS 网址。')
  }
}

export function websiteInput(draft: WebsiteDraft): WebsiteInput {
  const name = draft.name.trim()
  if (!name || !draft.url.trim()) throw new Error('请填写网站名称和网址。')
  return {
    name,
    url: normalizeWebsiteUrl(draft.url).href,
    icon: draft.icon.trim() || null,
    description: draft.description.trim() || null,
    categoryId: draft.categoryId || null,
    favorite: draft.favorite,
    order: draft.order,
  }
}
