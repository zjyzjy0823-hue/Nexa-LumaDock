<script lang="ts">
const openDialogs: symbol[] = []
</script>

<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import OpusIcon from './OpusIcon.vue'

const props = defineProps<{
  open: boolean
  title: string
  description?: string
  layer?: number
  wide?: boolean
}>()
const emit = defineEmits<{ close: [] }>()
const titleId = useId()
const dialog = ref<HTMLDialogElement | null>(null)
const mountedBody = ref(false)
let closeTimer: ReturnType<typeof setTimeout> | undefined
let previousFocus: HTMLElement | null = null
let backdropPressed = false
const dialogId = Symbol('opus-dialog')

function releaseDialog() {
  const index = openDialogs.indexOf(dialogId)
  if (index < 0) return
  const wasTop = index === openDialogs.length - 1
  openDialogs.splice(index, 1)
  if (wasTop && previousFocus?.isConnected) previousFocus.focus()
}

function onPointerDown(event: PointerEvent) {
  backdropPressed = event.target === dialog.value
}

function onDialogClick(event: MouseEvent) {
  if (backdropPressed && event.target === dialog.value) emit('close')
  backdropPressed = false
}

function onCancel(event: Event) {
  event.preventDefault()
  emit('close')
}

function onKeydown(event: KeyboardEvent) {
  if (!props.open || openDialogs.at(-1) !== dialogId) return
  if (event.key === 'Escape') {
    event.preventDefault()
    event.stopImmediatePropagation()
    emit('close')
  }
}

watch(() => props.open, async open => {
  if (closeTimer) { clearTimeout(closeTimer); closeTimer = undefined }
  if (open) {
    mountedBody.value = true
    previousFocus = typeof document !== 'undefined' && document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (!openDialogs.includes(dialogId)) openDialogs.push(dialogId)
    await nextTick()
    if (!props.open || !dialog.value) return
    if (typeof dialog.value.showModal === 'function') {
      if (!dialog.value.open) dialog.value.showModal()
    }
    const target = dialog.value.querySelector?.<HTMLElement>('[data-initial-focus], [autofocus]') ?? dialog.value
    target?.focus?.()
  } else {
    if (dialog.value && typeof dialog.value.close === 'function' && dialog.value.open) {
      dialog.value.close()
    }
    releaseDialog()
    closeTimer = setTimeout(() => {
      if (!props.open) mountedBody.value = false
    }, 240)
  }
}, { immediate: true })

onMounted(() => {
  if (typeof document !== 'undefined') document.addEventListener('keydown', onKeydown, true)
})
onUnmounted(() => {
  if (closeTimer) clearTimeout(closeTimer)
  if (typeof document !== 'undefined') document.removeEventListener('keydown', onKeydown, true)
  if (dialog.value && typeof dialog.value.close === 'function' && dialog.value.open) dialog.value.close()
  releaseDialog()
})
</script>

<template>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="dlg"
      :class="{ 'dlg--wide': wide }"
      :style="layer ? { zIndex: layer } : undefined"
      :aria-labelledby="titleId"
      closedby="any"
      @pointerdown="onPointerDown"
      @click="onDialogClick"
      @cancel="onCancel"
    >
      <div v-if="mountedBody" class="dlg-body">
        <div class="dlg-head">
          <div class="dlg-head__copy">
            <h2 :id="titleId">{{ title }}</h2>
            <p v-if="description">{{ description }}</p>
          </div>
          <button class="icon-btn" type="button" aria-label="关闭" @click="emit('close')"><OpusIcon name="x" /></button>
        </div>
        <slot />
        <div v-if="$slots.footer" class="dlg-actions"><slot name="footer" /></div>
      </div>
    </dialog>
  </Teleport>
</template>
