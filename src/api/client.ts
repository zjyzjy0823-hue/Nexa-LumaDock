const baseUrl = import.meta.env.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export async function apiRequest<T>(path: string, options: RequestInit = {}, token?: string | null): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${baseUrl}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    })
  } catch {
    throw new ApiError(0, '无法连接到 Nexa 后端')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string; error?: { message?: string } }
    throw new ApiError(response.status, body.error?.message || body.detail || `请求失败 (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
