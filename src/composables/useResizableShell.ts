import { ref } from 'vue'

/**
 * 供 ChatPage 向外层 OpusShell 通报当前额外展开栏（树栏 + 并排分屏/检查器）的占用总宽度，
 * 让左侧主导航在总空间不足时自动切到单图标态，空间恢复充足时自动还原正常宽度。
 */
export const sharedChatOccupiedWidth = ref(0)

export function clampWidth(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, Math.round(value)))
}

export function readStoredWidth(storageKey: string, fallback: number, min: number, max: number): number {
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw) return fallback
    const parsed = Number(raw)
    if (!Number.isFinite(parsed)) return fallback
    return clampWidth(parsed, min, max)
  } catch {
    return fallback
  }
}

export function saveStoredWidth(storageKey: string, value: number): void {
  try {
    localStorage.setItem(storageKey, String(Math.round(value)))
  } catch {
    // 忽略无痕模式等存储受限环境错误
  }
}

export interface ColumnDragOptions {
  event: PointerEvent
  initialWidth: number
  min: number
  max: number
  direction?: 1 | -1
  snapCollapseThreshold?: number
  snapExpandThreshold?: number
  onPreview: (nextWidth: number, collapsedHint: boolean) => void
  onCommit: (finalWidth: number, collapsedHint: boolean) => void
  onCancel?: () => void
  onEnd?: () => void
}

/**
 * 通用指针拖拽分栏尺寸调节器（支持双向阻力与阈值自动折叠/弹开）。
 */
export function startColumnDrag(options: ColumnDragOptions): void {
  if (options.event.button !== 0) return
  options.event.preventDefault()

  const startX = options.event.clientX
  const dir = options.direction ?? 1
  const prevCursor = document.body.style.cursor
  const prevSelect = document.body.style.userSelect
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'

  let lastWidth = options.initialWidth
  let lastCollapsed = false

  const evaluate = (clientX: number) => {
    const raw = options.initialWidth + (clientX - startX) * dir
    if (options.snapCollapseThreshold && raw < options.snapCollapseThreshold) {
      lastCollapsed = true
      lastWidth = options.initialWidth
      return { width: options.initialWidth, collapsed: true }
    }
    if (options.snapExpandThreshold && raw >= options.snapExpandThreshold) {
      lastCollapsed = false
    } else if (!options.snapCollapseThreshold) {
      lastCollapsed = false
    }
    lastWidth = clampWidth(raw, options.min, options.max)
    return { width: lastWidth, collapsed: lastCollapsed }
  }

  const handle = options.event.currentTarget as HTMLElement
  const pointerId = options.event.pointerId
  handle.setPointerCapture(pointerId)
  handle.classList.add('is-active')
  let frame = 0
  let latestX = startX

  const onMove = (event: PointerEvent) => {
    if (event.pointerId !== pointerId) return
    latestX = event.clientX
    if (frame) return
    frame = requestAnimationFrame(() => {
      frame = 0
      const next = evaluate(latestX)
      options.onPreview(next.width, next.collapsed)
    })
  }

  function finish(event?: PointerEvent) {
    if (event && event.pointerId !== pointerId) return
    cancelAnimationFrame(frame)
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', finish)
    window.removeEventListener('pointercancel', finish)
    window.removeEventListener('blur', onBlur)
    handle.removeEventListener('lostpointercapture', finish)
    if (handle.hasPointerCapture(pointerId)) handle.releasePointerCapture(pointerId)
    handle.classList.remove('is-active')
    document.body.style.cursor = prevCursor
    document.body.style.userSelect = prevSelect
    if (event?.type === 'pointerup') {
      const finalState = evaluate(event.clientX)
      options.onCommit(finalState.width, finalState.collapsed)
    } else {
      options.onCancel?.()
    }
    options.onEnd?.()
  }
  const onBlur = () => finish()
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', finish)
  window.addEventListener('pointercancel', finish)
  window.addEventListener('blur', onBlur)
  handle.addEventListener('lostpointercapture', finish)
}
