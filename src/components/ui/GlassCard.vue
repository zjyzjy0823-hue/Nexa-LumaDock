<script setup lang="ts">
defineProps<{
  title?: string
  kicker?: string
}>()
</script>

<template>
  <article class="glass-card card mat">
    <div v-if="title || kicker || $slots.action" class="glass-card__header card-h">
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
  display: flex; flex-direction: column; min-width: 0; min-height: 0; height: 100%;
  color: var(--text);
}
.glass-card__header { justify-content: space-between; margin-bottom: 12px; }
.glass-card__heading, .glass-card__body { min-width: 0; }
.glass-card__kicker { display: none; }
.glass-card__title { margin: 0; color: var(--text); font-size: 14px; font-weight: 650; line-height: 1.25; }
.glass-card__action { flex: none; display: flex; align-items: center; }
.glass-card__body { flex: 1; min-height: 0; overflow: auto; scrollbar-width: thin; }
</style>
