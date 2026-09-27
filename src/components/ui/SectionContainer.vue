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
.section-container { position:relative; min-width:0; padding:19px; overflow:hidden; border:var(--glass-card-border); border-radius:var(--radius-card); background:var(--glass-card-background); box-shadow:var(--shadow-card); backdrop-filter:blur(var(--glass-blur)) saturate(125%); -webkit-backdrop-filter:blur(var(--glass-blur)) saturate(125%); color:#263653; transition:transform .22s ease,box-shadow .22s ease,border-color .22s ease; }
.section-container::before { content:''; position:absolute; inset:0 0 auto; height:1px; background:linear-gradient(90deg,transparent,white,transparent); pointer-events:none; }
.section-container:hover { transform:translateY(-3px) scale(1.02); border-color:rgba(255,255,255,.72); box-shadow:var(--shadow-card-hover); }
.section-container__heading { position:relative; display:flex; align-items:center; justify-content:space-between; gap:18px; margin-bottom:18px; }
.section-container__heading h2 { margin:0; color:#fff; font-size:20px; font-weight:530; line-height:1.2; letter-spacing:-.025em; text-shadow:0 1px 10px rgba(25,38,76,.26); }
.section-container__heading p { margin:5px 0 0; color:rgba(255,255,255,.78); font-size:11px; text-shadow:0 1px 8px rgba(25,38,76,.28); }
.section-container__action { display:flex; align-items:center; gap:8px; flex:none; }
.section-container__content { position:relative; min-width:0; }
@media (max-width:700px) { .section-container { padding:17px; } }
@media (prefers-reduced-motion:reduce) { .section-container { transition:none; } .section-container:hover { transform:none; } }
</style>
