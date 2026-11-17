<script setup lang="ts">
import { onMounted, onUnmounted, onUpdated, ref } from 'vue'

const segment = ref<HTMLElement>()
const thumb = ref<HTMLElement>()
let observer: ResizeObserver

function alignThumb() {
  if (!observer) return
  const selected = segment.value?.querySelector<HTMLElement>('button[aria-pressed="true"]')
  if (!thumb.value) return
  thumb.value.style.width = (selected?.offsetWidth ?? 0) + 'px'
  thumb.value.style.translate = (selected?.offsetLeft ?? 0) + 'px'
}

onMounted(() => {
  if (!segment.value || typeof ResizeObserver === 'undefined') return
  observer = new ResizeObserver(alignThumb)
  observer.observe(segment.value)
  alignThumb()
})
onUpdated(alignThumb)
onUnmounted(() => observer?.disconnect())
</script>

<template>
  <div ref="segment" class="seg"><span ref="thumb" class="thumb" aria-hidden="true"></span><slot /></div>
</template>
