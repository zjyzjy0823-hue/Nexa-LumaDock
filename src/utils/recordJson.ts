export function parseRecordJson(text: string): Record<string, unknown> {
  let value: unknown
  try {
    value = JSON.parse(text.trim() || '{}')
  } catch {
    throw new Error('记录内容不是有效的 JSON，请检查后再保存。')
  }
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('记录内容必须是 JSON 对象，例如 {"备注":"内容"}。')
  }
  return value as Record<string, unknown>
}
