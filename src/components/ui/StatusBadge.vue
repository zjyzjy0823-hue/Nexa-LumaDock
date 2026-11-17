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
.status-badge { display:inline-flex; align-items:center; gap:6px; min-height:23px; padding:4px 8px; border:1px solid currentColor; border-radius:999px; font-size:11px; font-weight:620; line-height:1; white-space:nowrap; }
.status-badge i { width:6px; height:6px; border-radius:50%; background:currentColor; }
.status-badge--success { color:var(--workbench-good); background:var(--workbench-good-soft); }
.status-badge--warning { color:var(--workbench-warn); background:var(--workbench-warn-soft); }
.status-badge--neutral { color:var(--workbench-muted); background:var(--workbench-muted-surface); }
.status-badge--info { color:var(--workbench-accent); background:var(--workbench-soft); }
.status-badge--danger { color:var(--workbench-danger); background:var(--workbench-danger-soft); }
</style>
