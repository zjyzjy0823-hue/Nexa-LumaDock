import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useDashboardStore } from '../stores/dashboard'
import { minimumFor } from '../widgets/registry'

type Frame = { x: number; y: number; w: number; h: number }
type Frames = Record<string, Frame>
type Interaction = { id: string; kind: 'move' | 'resize'; pointerId: number; x: number; y: number; initial: Frames }
const canvasWidth = 1284
const guestKey = 'nexa:guest-layout:v1'

export function useWidgetLayout(notify: (message: string) => void) {
  const auth = useAuthStore()
  const dashboard = useDashboardStore()
  const board = ref<HTMLElement | null>(null)
  const width = ref(canvasWidth)
  const desktop = ref(true)
  const editing = ref(false)
  const activeWidget = ref<string | null>(null)
  const scale = computed(() => width.value / canvasWidth)
  let query: MediaQueryList | undefined
  let observer: ResizeObserver | undefined
  let interaction: Interaction | null = null
  let oldSelection = ''
  let oldCursor = ''

  function snapshot(): Frames {
    return Object.fromEntries(dashboard.widgets.map(widget => [widget.id, {
      x: widget.position.x, y: widget.position.y, w: widget.size.width, h: widget.size.height,
    }]))
  }
  function apply(frames: Frames) {
    dashboard.replace(dashboard.widgets.map(widget => {
      const frame = frames[widget.id]
      return frame ? { ...widget, position: { x: frame.x, y: frame.y }, size: { width: frame.w, height: frame.h } } : widget
    }))
  }
  function save() {
    if (auth.token) void dashboard.save(auth.token).catch(() => notify(dashboard.error || '布局保存失败'))
    else try { localStorage.setItem(guestKey, JSON.stringify(snapshot())) } catch { notify('本地布局保存失败。') }
  }
  function loadGuest() {
    try {
      const saved = JSON.parse(localStorage.getItem(guestKey) || 'null') as Frames | null
      if (!saved || !dashboard.widgets.every(widget => {
        const frame = saved[widget.id]
        const min = minimumFor(widget.type)
        return frame && [frame.x, frame.y, frame.w, frame.h].every(Number.isFinite) &&
          frame.x >= 0 && frame.y >= 0 && frame.y < 20000 && frame.w >= min.minWidth &&
          frame.h >= min.minHeight && frame.h <= 2000 && frame.x + frame.w <= canvasWidth
      })) return
      apply(saved)
    } catch { /* Invalid guest layout falls back to defaults. */ }
  }
  function overlap(a: Frame, b: Frame) {
    return a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y
  }
  function flow(id: string, frame: Frame, initial: Frames, horizontal = false) {
    const next = structuredClone(initial)
    next[id] = frame
    const queue = [id]
    let attempts = 0
    while (queue.length && attempts++ < 200) {
      const source = queue.shift()!
      for (const widget of dashboard.widgets) {
        const target = widget.id
        if (target === source || target === id || !next[target] || !overlap(next[source], next[target])) continue
        let moved = false
        if (horizontal) {
          const x = next[target].x >= next[source].x
            ? next[source].x + next[source].w : next[source].x - next[target].w
          if (x >= 0 && x + next[target].w <= canvasWidth) { next[target].x = x; moved = true }
        }
        if (!moved) next[target].y = next[source].y + next[source].h
        queue.push(target)
      }
    }
    apply(next)
  }
  function finish(commit: boolean) {
    if (!interaction) return
    if (!commit) apply(interaction.initial)
    interaction = null
    activeWidget.value = null
    window.removeEventListener('pointermove', pointerMove)
    window.removeEventListener('pointerup', pointerUp)
    window.removeEventListener('pointercancel', pointerCancel)
    document.body.style.userSelect = oldSelection
    document.body.style.cursor = oldCursor
    if (commit) save()
  }
  function begin(id: string, kind: 'move' | 'resize', event: PointerEvent) {
    if (!editing.value || !desktop.value || event.button !== 0) return
    finish(true)
    event.preventDefault()
    oldSelection = document.body.style.userSelect
    oldCursor = document.body.style.cursor
    document.body.style.userSelect = 'none'
    document.body.style.cursor = kind === 'move' ? 'grabbing' : 'nwse-resize'
    activeWidget.value = id
    interaction = { id, kind, pointerId: event.pointerId, x: event.clientX, y: event.clientY, initial: snapshot() }
    window.addEventListener('pointermove', pointerMove)
    window.addEventListener('pointerup', pointerUp)
    window.addEventListener('pointercancel', pointerCancel)
  }
  function pointerMove(event: PointerEvent) {
    if (!interaction || interaction.pointerId !== event.pointerId) return
    const start = interaction.initial[interaction.id]
    const dx = (event.clientX - interaction.x) / scale.value
    const dy = (event.clientY - interaction.y) / scale.value
    const widget = dashboard.widgets.find(item => item.id === interaction!.id)!
    const min = minimumFor(widget.type)
    const frame = interaction.kind === 'move'
      ? { ...start, x: Math.round(Math.max(0, Math.min(canvasWidth - start.w, start.x + dx))), y: Math.round(Math.max(0, start.y + dy)) }
      : { ...start, w: Math.round(Math.max(min.minWidth, Math.min(canvasWidth - start.x, start.w + dx))), h: Math.round(Math.max(min.minHeight, start.h + dy)) }
    flow(interaction.id, frame, interaction.initial, Math.abs(dx) >= Math.abs(dy))
  }
  function pointerUp(event: PointerEvent) { if (interaction?.pointerId === event.pointerId) finish(true) }
  function pointerCancel(event: PointerEvent) { if (interaction?.pointerId === event.pointerId) finish(false) }
  function keyAdjust(id: string, kind: 'move' | 'resize', event: KeyboardEvent) {
    if (!editing.value || !desktop.value || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return
    event.preventDefault()
    const amount = event.shiftKey ? 40 : 16
    const dx = event.key === 'ArrowLeft' ? -amount : event.key === 'ArrowRight' ? amount : 0
    const dy = event.key === 'ArrowUp' ? -amount : event.key === 'ArrowDown' ? amount : 0
    const initial = snapshot()
    const start = initial[id]
    const widget = dashboard.widgets.find(item => item.id === id)!
    const min = minimumFor(widget.type)
    const frame = kind === 'move'
      ? { ...start, x: Math.max(0, Math.min(canvasWidth - start.w, start.x + dx)), y: Math.max(0, start.y + dy) }
      : { ...start, w: Math.max(min.minWidth, Math.min(canvasWidth - start.x, start.w + dx)), h: Math.max(min.minHeight, start.h + dy) }
    flow(id, frame, initial, dx !== 0)
    save()
  }
  function resetWidget(id: string) {
    const widget = dashboard.defaults.find(item => item.id === id)
    if (!widget) return
    flow(id, { x: widget.position.x, y: widget.position.y, w: widget.size.width, h: widget.size.height }, snapshot())
    save()
  }
  function resetAll() {
    finish(false)
    dashboard.replace(dashboard.defaults)
    save()
    notify('已恢复默认布局。')
  }
  function updateViewport() {
    desktop.value = query?.matches ?? true
    if (!desktop.value) { finish(false); editing.value = false }
    if (board.value) width.value = board.value.getBoundingClientRect().width || canvasWidth
  }
  onMounted(() => {
    query = window.matchMedia('(min-width: 1280px)')
    query.addEventListener('change', updateViewport)
    updateViewport()
    observer = new ResizeObserver(updateViewport)
    if (board.value) observer.observe(board.value)
    loadGuest()
  })
  onUnmounted(() => {
    finish(false)
    observer?.disconnect()
    query?.removeEventListener('change', updateViewport)
  })
  return { board, desktop, editing, activeWidget, scale, begin, keyAdjust, finish, resetWidget, resetAll, loadGuest }
}
