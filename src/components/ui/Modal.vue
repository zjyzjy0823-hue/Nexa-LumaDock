<script lang="ts">
const openDialogs: symbol[] = []
let originalOverflow = ''
</script>

<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, useId, watch } from 'vue'
import { X } from 'lucide-vue-next'

const props = defineProps<{
  open: boolean
  title: string
  description?: string
  layer?: number
}>()
const emit = defineEmits<{ close: [] }>()
const titleId = useId()
const dialog = ref<HTMLElement | null>(null)
let previousFocus: HTMLElement | null = null
const dialogId = Symbol('glass-modal')

function releaseDialog() {
  const index = openDialogs.indexOf(dialogId)
  if (index < 0) return
  const wasTop = index === openDialogs.length - 1
  openDialogs.splice(index, 1)
  if (!openDialogs.length) document.body.style.overflow = originalOverflow
  if (wasTop && previousFocus?.isConnected) previousFocus.focus()
}

function onKeydown(event: KeyboardEvent) {
  if (!props.open || openDialogs.at(-1) !== dialogId) return
  if (event.key === 'Escape') { event.preventDefault(); event.stopImmediatePropagation(); emit('close') }
  if (event.key === 'Tab' && dialog.value) {
    const items = [...dialog.value.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]')].filter(item => item.getClientRects().length)
    const first = items[0], last = items.at(-1)
    if (!first) { event.preventDefault(); dialog.value.focus() }
    else if (event.shiftKey && (document.activeElement === first || document.activeElement === dialog.value)) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && (document.activeElement === last || document.activeElement === dialog.value)) { event.preventDefault(); first.focus() }
  }
}
watch(() => props.open, async open => {
  if (open) {
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (!openDialogs.length) originalOverflow = document.body.style.overflow
    openDialogs.push(dialogId)
    document.body.style.overflow = 'hidden'
    await nextTick(); if (props.open) dialog.value?.focus()
  } else releaseDialog()
}, { immediate: true })
onMounted(() => document.addEventListener('keydown', onKeydown, true))
onUnmounted(() => { document.removeEventListener('keydown', onKeydown, true); releaseDialog() })
</script>

<template>
  <Teleport to="body">
    <Transition name="glass-modal">
      <div v-if="open" class="glass-modal-backdrop" :style="{ zIndex: layer ?? 100 }" @pointerdown.self="emit('close')">
        <section ref="dialog" class="glass-modal" role="dialog" aria-modal="true" :aria-labelledby="titleId" tabindex="-1">
          <header class="glass-modal__header">
            <div><h2 :id="titleId">{{ title }}</h2><p v-if="description">{{ description }}</p></div>
            <button class="glass-modal__close" type="button" aria-label="关闭" @click="emit('close')"><X :size="18" /></button>
          </header>
          <div class="glass-modal__body"><slot /></div>
          <footer v-if="$slots.footer" class="glass-modal__footer"><slot name="footer" /></footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.glass-modal-backdrop { position:fixed; z-index:100; inset:0; display:grid; place-items:center; padding:20px; background:rgba(30,43,86,.35); backdrop-filter:blur(9px); -webkit-backdrop-filter:blur(9px); }
.glass-modal { width:min(100%,480px); max-height:min(90dvh,760px); overflow:auto; padding:24px; border:1px solid rgba(255,255,255,.86); border-radius:var(--radius-xl); color:var(--text-primary); background:var(--glass-dialog-background); box-shadow:0 25px 75px rgba(26,44,97,.25),inset 0 1px 0 #fff; outline:none;  backdrop-filter:var(--glass-overlay-filter); -webkit-backdrop-filter:var(--glass-overlay-filter); }
.glass-modal__header { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }
.glass-modal__header h2 { margin:0; font-size:23px; font-weight:710; letter-spacing:-.035em; }
.glass-modal__header p { margin:6px 0 0; color:var(--text-secondary); font-size:12px; line-height:1.5; }
.glass-modal__close { display:grid; width:31px; height:31px; flex:none; place-items:center; padding:0; border:1px solid rgba(137,157,198,.2); border-radius:10px; color:var(--text-secondary); background:rgba(255,255,255,.74); transition:background .2s,transform .2s; }
.glass-modal__close:hover { background:#fff; transform:translateY(-2px); }
.glass-modal__body { margin-top:22px; }
.glass-modal__footer { display:flex; justify-content:flex-end; gap:9px; margin-top:24px; }
.glass-modal-enter-active,.glass-modal-leave-active { transition:background-color .22s ease; }
.glass-modal-enter-active .glass-modal,.glass-modal-leave-active .glass-modal { transition:transform .22s ease; }
.glass-modal-enter-from,.glass-modal-leave-to { background-color:rgba(30,43,86,0); }
.glass-modal-enter-from .glass-modal,.glass-modal-leave-to .glass-modal { transform:translateY(12px) scale(.98); }
</style>
