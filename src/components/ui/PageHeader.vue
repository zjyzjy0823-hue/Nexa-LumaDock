<script setup lang="ts">
withDefaults(defineProps<{
  title: string
  subtitle?: string
  eyebrow?: string
}>(), { eyebrow: 'NEXA WORKSPACE' })
</script>

<template>
  <header class="page-header">
    <div class="page-header__copy">
      <div class="page-header__eyebrow"><span class="page-header__sparkle">✦</span>{{ eyebrow }}</div>
      <h1>{{ title }}</h1>
      <p v-if="subtitle">{{ subtitle }}</p>
    </div>
    <div v-if="$slots.actions" class="page-header__actions"><slot name="actions" /></div>
  </header>
</template>

<style scoped>
.page-header { display:flex; align-items:flex-end; justify-content:space-between; gap:24px; min-width:0; margin:10px 0 25px; color:white; }
.page-header__copy { min-width:0; }
.page-header__eyebrow { display:flex; align-items:center; gap:8px; margin-bottom:9px; color:rgba(240,246,255,.75); font-size:10px; font-weight:750; letter-spacing:.19em; }
.page-header__sparkle { color:#e6d5ff; font-size:14px; line-height:1; }
h1 { margin:0; font-size:clamp(32px,3.4vw,46px); line-height:1.08; letter-spacing:-.055em; font-weight:680; text-shadow:0 4px 24px rgba(29,39,85,.2); }
p { margin:9px 0 0; color:rgba(246,249,255,.78); font-size:13px; line-height:1.5; }
.page-header__actions { display:flex; align-items:center; gap:10px; flex:none; padding-bottom:2px; }
@media (max-width:700px) { .page-header { align-items:flex-start; flex-direction:column; gap:16px; margin-top:8px; } .page-header__actions { flex-wrap:wrap; } }
</style>
