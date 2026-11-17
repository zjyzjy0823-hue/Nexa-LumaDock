<script setup lang="ts">
defineProps<{ title: string; description?: string; kicker?: string }>()
</script>

<template>
  <section class="settings-section">
    <h2>{{ title }}</h2>
    <p v-if="description" class="settings-section__description">{{ description }}</p>
    <div class="settings-section__content"><slot /></div>
  </section>
</template>
