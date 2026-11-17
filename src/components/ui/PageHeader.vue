<script setup lang="ts">
withDefaults(defineProps<{
  title: string
  subtitle?: string
  eyebrow?: string
}>(), { eyebrow: 'STUDIOLO WORKSPACE' })
</script>

<template>
  <header class="page-header">
    <div class="page-header__copy">
      <div v-if="eyebrow" class="page-header__eyebrow"><span class="page-header__sparkle">✦</span>{{ eyebrow }}</div>
      <h1>{{ title }}</h1>
      <p v-if="subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="page-header__actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.page-header { display:flex; align-items:flex-end; justify-content:space-between; gap:20px; min-width:0; margin:6px 0 22px; color:var(--workbench-text); }
.page-header__copy { min-width:0; }
.page-header__eyebrow { margin-bottom:5px; color:var(--workbench-muted); font-size:12px; font-weight:600; }
.page-header__sparkle { display:none; }
h1 { margin:0; font-size:clamp(28px,3vw,38px); line-height:1.15; letter-spacing:-.04em; font-weight:730; }
p { margin:7px 0 0; color:var(--workbench-muted); font-size:13px; line-height:1.5; }
.page-header__actions { display:flex; flex-wrap:wrap; align-items:center; gap:8px; flex:none; }
@media (max-width:700px) { .page-header { align-items:flex-start; flex-direction:column; gap:12px; margin:3px 0 16px; } }
</style>
