<script setup lang="ts">
withDefaults(defineProps<{
  label: string
  tone?: 'success' | 'warning' | 'neutral' | 'info' | 'danger'
}>(), { tone: 'neutral' })
</script>

<template>
  <span class="status-badge" :class="`status-badge--${tone}`"><i aria-hidden="true" />{{ label }}</span>
</template>

<style scoped>
.status-badge { display:inline-flex; align-items:center; gap:6px; min-height:25px; padding:4px 9px; border:1px solid transparent; border-radius:999px; font-size:10px; font-weight:680; line-height:1; white-space:nowrap; }
.status-badge i { width:6px; height:6px; border-radius:50%; background:currentColor; box-shadow:0 0 0 3px color-mix(in srgb,currentColor 15%,transparent); }
.status-badge--success { color:#198b73; border-color:#bce8d9; background:#e2f7ee; }
.status-badge--warning { color:#b88627; border-color:#f3dfac; background:#fff5dd; }
.status-badge--neutral { color:#74839b; border-color:#dce4ee; background:#f1f4f9; }
.status-badge--info { color:#5574d1; border-color:#cedaf9; background:#eaf0ff; }
.status-badge--danger { color:#c76572; border-color:#f4cbd1; background:#fff0f2; }
</style>
