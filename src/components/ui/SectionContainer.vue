<script setup lang="ts">
defineProps<{ title: string; subtitle?: string }>()
</script>

<template>
  <section class="section-container">
    <div class="section-container__heading">
      <div>
        <h2>{{ title }}</h2>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
      <div v-if="$slots.action" class="section-container__action"><slot name="action" /></div>
    </div>
    <div class="section-container__content"><slot /></div>
  </section>
</template>

<style scoped>
.section-container { position:relative; min-width:0; padding:17px; border:1px solid var(--workbench-line); border-radius:var(--workbench-radius); color:var(--workbench-text); background:var(--workbench-surface); box-shadow:var(--workbench-shadow); backdrop-filter:var(--workbench-material); -webkit-backdrop-filter:var(--workbench-material); }
.section-container__heading { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:14px; }
.section-container__heading h2 { margin:0; font-size:17px; font-weight:650; line-height:1.25; letter-spacing:-.018em; }
.section-container__heading p { margin:5px 0 0; color:var(--workbench-muted); font-size:12px; }
.section-container__action { display:flex; flex:none; align-items:center; gap:8px; }
.section-container__content { position:relative; min-width:0; }
</style>
