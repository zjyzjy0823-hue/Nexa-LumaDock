<script setup lang="ts">
import GlassCard from '../ui/GlassCard.vue'

defineProps<{ title: string; description?: string; kicker?: string }>()
</script>

<template>
  <GlassCard :title="title" class="settings-section">
    <p v-if="description" class="settings-section__description">{{ description }}</p>
    <div class="settings-section__content"><slot /></div>
  </GlassCard>
</template>
