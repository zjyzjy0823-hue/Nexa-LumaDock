import { onUnmounted, ref } from 'vue'

/**
 * 统一的剪贴板复制与“点击打勾”反馈 Composable。
 * 支持单页面内多个复制按钮通过 key 独立管理打勾状态与自动复位。
 */
export function useCopyFeedback(defaultDuration = 1600) {
  const copiedMap = ref<Record<string, boolean>>({})
  const timers = new Map<string, ReturnType<typeof setTimeout>>()

  function clearKeyTimer(key: string) {
    const existing = timers.get(key)
    if (existing) {
      clearTimeout(existing)
      timers.delete(key)
    }
  }

  function isCopied(key = 'default'): boolean {
    return Boolean(copiedMap.value[key])
  }

  function markCopied(key = 'default', duration = defaultDuration): void {
    clearKeyTimer(key)
    copiedMap.value = { ...copiedMap.value, [key]: true }
    const timer = setTimeout(() => {
      const next = { ...copiedMap.value }
      delete next[key]
      copiedMap.value = next
      timers.delete(key)
    }, duration)
    timers.set(key, timer)
  }

  function reset(): void {
    for (const timer of timers.values()) {
      clearTimeout(timer)
    }
    timers.clear()
    copiedMap.value = {}
  }

  async function writeClipboard(text: string): Promise<boolean> {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text)
        return true
      } catch {
        // 降级到传统选区复制（兼容局域网非 HTTPS 预览）
      }
    }
    if (typeof document === 'undefined') return false
    try {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.setAttribute('readonly', '')
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      textarea.style.pointerEvents = 'none'
      document.body.appendChild(textarea)
      textarea.select()
      const ok = document.execCommand('copy')
      document.body.removeChild(textarea)
      return ok
    } catch {
      return false
    }
  }

  async function copy(text: string, key = 'default', duration = defaultDuration): Promise<boolean> {
    const ok = await writeClipboard(text)
    if (ok) {
      markCopied(key, duration)
    }
    return ok
  }

  onUnmounted(() => {
    reset()
  })

  return {
    copiedMap,
    isCopied,
    markCopied,
    copy,
    reset,
  }
}
