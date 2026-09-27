<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Grip, MoveDiagonal2 } from 'lucide-vue-next'

const props = defineProps<{
  name: string
  editing: boolean
  displayWidth: number
  displayHeight: number
  baseWidth: number
  baseHeight: number
}>()
const emit = defineEmits<{
  moveStart: [event: PointerEvent]
  resizeStart: [event: PointerEvent]
  moveKey: [event: KeyboardEvent]
  resizeKey: [event: KeyboardEvent]
  reset: []
}>()

const desktop = ref(true)
let mediaQuery: MediaQueryList | undefined
const frameStyle = computed(() => desktop.value
  ? { width: `${props.displayWidth}px`, height: `${props.displayHeight}px` }
  : undefined)

function updateDesktop() { desktop.value = mediaQuery?.matches ?? true }
function start(kind: 'move' | 'resize', event: PointerEvent) {
  if (event.button !== 0) return
  const control = event.currentTarget as HTMLButtonElement
  control.focus()
  control.setPointerCapture(event.pointerId)
  if (kind === 'move') emit('moveStart', event)
  else emit('resizeStart', event)
}

onMounted(() => {
  mediaQuery = window.matchMedia('(min-width: 1280px)')
  updateDesktop()
  mediaQuery.addEventListener('change', updateDesktop)
})
onUnmounted(() => mediaQuery?.removeEventListener('change', updateDesktop))
</script>

<template>
  <div class="resizable-widget" :class="{ 'resizable-widget--editing': editing && desktop }" :style="frameStyle">
    <div class="resizable-widget__content"><slot /></div>
    <template v-if="editing && desktop">
      <button
        type="button"
        class="widget-control widget-control--move"
        :aria-label="`移动${name}组件`"
        :title="`拖动移动${name}；方向键微调，Shift 加方向键快速移动；双击恢复此组件。`"
        @pointerdown.stop="start('move', $event)"
        @keydown="emit('moveKey', $event)"
        @dblclick.stop="emit('reset')"
      ><Grip :size="14" aria-hidden="true" /><span>移动</span></button>
      <button
        type="button"
        class="widget-control widget-control--resize"
        :aria-label="`调整${name}组件大小`"
        :title="`拖动调整${name}的宽度和高度；方向键微调，Shift 加方向键快速调整；双击恢复此组件。`"
        @pointerdown.stop="start('resize', $event)"
        @keydown="emit('resizeKey', $event)"
        @dblclick.stop="emit('reset')"
      ><MoveDiagonal2 :size="17" aria-hidden="true" /></button>
    </template>
  </div>
</template>

<style scoped>
/* The size container lets each card adapt to its own dimensions. It also isolates
   the child card's backdrop, so sample and scale the wallpaper on this outer frame. */
.resizable-widget {
  position: relative;
  min-width: 0;
  border-radius: var(--radius-card);
  container-type: size;
  backdrop-filter: blur(var(--glass-blur)) saturate(125%);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(125%);
  transition: transform .22s ease;
}
.resizable-widget:not(.resizable-widget--editing):hover { transform: translateY(-3px) scale(1.02); }
.resizable-widget :deep(.glass-card:hover) { transform: none; }
.resizable-widget__content { width: 100%; height: 100%; min-width: 0; min-height: 0; }
.resizable-widget--editing { outline: 2px dashed rgba(255,255,255,.85); outline-offset: 3px; }
.widget-control { position: absolute; z-index: 8; display: flex; align-items: center; justify-content: center; gap: 3px; height: 26px; padding: 0 8px; border: 1px solid rgba(255,255,255,.8); border-radius: 9px; background: rgba(63,93,162,.9); box-shadow: 0 4px 12px rgba(28,42,86,.25); color: white; font-size: 11px; font-weight: 600; touch-action: none; user-select: none; }
.widget-control:hover, .widget-control:focus-visible { background: #557ee5; }
.widget-control:focus-visible { outline: 2px solid #fff; outline-offset: 2px; }
.widget-control--move { top: -12px; left: 50%; transform: translateX(-50%); cursor: grab; }
.widget-control--move:active { cursor: grabbing; }
.widget-control--resize { right: -8px; bottom: -8px; width: 30px; height: 30px; padding: 0; cursor: nwse-resize; }
@media (max-width: 1279px) { .resizable-widget { width: 100%; } }
@media (prefers-reduced-motion: reduce) { .resizable-widget { transition: none; } .resizable-widget:not(.resizable-widget--editing):hover { transform: none; } }
</style>
