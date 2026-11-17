<script setup lang="ts">
import OpusIcon from './OpusIcon.vue'

const labels = {
  local: '已在本机保存', pending: '待同步', synced: '已同步', conflict: '需处理冲突', offline: '离线',
}

defineProps<{ kind: keyof typeof labels; label?: string; dotOnly?: boolean }>()
</script>

<template>
  <span class="sync" :class="['is-' + kind, { 'dot-only': dotOnly }]" :aria-label="dotOnly ? (label ?? labels[kind]) : undefined">
    <span class="glyph"><OpusIcon v-if="kind === 'local' || kind === 'synced'" :name="kind === 'local' ? 'check' : 'checks'" /><b v-else-if="kind === 'conflict'" style="font-size:10px">!</b></span>
    <template v-if="!dotOnly">{{ label ?? labels[kind] }}</template>
  </span>
</template>
