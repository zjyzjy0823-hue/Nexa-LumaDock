<script setup lang="ts">
import { openExternal } from '../../utils/openExternal'

const props = defineProps<{ href: string }>()
const emit = defineEmits<{ activate: []; action: [message: string] }>()

async function activate(event: MouseEvent) {
  if (event.defaultPrevented) return
  if (event.type === 'auxclick' ? event.button !== 1 : event.button !== 0) return
  event.preventDefault()
  const opening = openExternal(props.href)
  emit('activate')
  try { await opening }
  catch (error) { emit('action', error instanceof Error ? error.message : '无法打开网站。') }
}
</script>

<template>
  <a :href="href" rel="noopener noreferrer" @click="activate" @auxclick="activate"><slot /></a>
</template>
