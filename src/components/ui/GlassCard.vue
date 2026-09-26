<script setup lang="ts">
defineProps<{
  title?: string
  kicker?: string
}>()
</script>

<template>
  <article class="glass-card">
    <div v-if="title || kicker || $slots.action" class="glass-card__header">
      <div class="glass-card__heading">
        <span v-if="kicker" class="glass-card__kicker">{{ kicker }}</span>
        <h2 v-if="title" class="glass-card__title">{{ title }}</h2>
      </div>
      <div v-if="$slots.action" class="glass-card__action"><slot name="action" /></div>
    </div>
    <div class="glass-card__body"><slot /></div>
  </article>
</template>

<style scoped>
.glass-card {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  height: 100%;
  overflow: hidden;
  padding: 17px 19px 18px;
  border: 1px solid rgba(255, 255, 255, .48);
  border-radius: var(--radius-card);
  background: linear-gradient(140deg, rgba(217,229,255,.27), rgba(202,216,246,.19) 55%, rgba(247,220,237,.24));
  box-shadow: var(--shadow-card);
  backdrop-filter: blur(var(--glass-blur)) saturate(125%);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(125%);
  transition: transform .22s ease, box-shadow .22s ease, border-color .22s ease;
}
.glass-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,.7) 15%, rgba(255,255,255,.55) 78%, transparent);
  pointer-events: none;
}
.glass-card::after {
  content: '';
  position: absolute;
  width: 180px;
  height: 120px;
  top: -75px;
  right: -35px;
  border-radius: 50%;
  background: rgba(255,255,255,.13);
  filter: blur(38px);
  pointer-events: none;
}
.glass-card:hover {
  transform: translateY(-3px);
  border-color: rgba(255,255,255,.72);
  box-shadow: var(--shadow-card-hover);
}
.glass-card__header, .glass-card__body { position: relative; z-index: 1; }
.glass-card__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
.glass-card__heading { min-width: 0; }
.glass-card__kicker { display: none; }
.glass-card__title { margin: 0; color: #fff; font-size: 20px; font-weight: 530; letter-spacing: -.025em; line-height: 1.2; text-shadow: 0 1px 10px rgba(25,38,76,.12); }
.glass-card__action { flex: none; display: flex; align-items: center; }
.glass-card__body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: rgba(219, 230, 255, .55) transparent;
}
@media (prefers-reduced-motion: reduce) { .glass-card { transition: none; } .glass-card:hover { transform: none; } }
</style>
