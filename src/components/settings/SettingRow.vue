<script setup lang="ts">
defineProps<{ label: string; description?: string; compact?: boolean }>()
</script>

<template>
  <div class="setting-row" :class="{ 'setting-row--compact': compact }">
    <div class="setting-row__copy">
      <span class="setting-row__label">{{ label }}</span>
      <span v-if="description" class="setting-row__description">{{ description }}</span>
    </div>
    <div class="setting-row__control"><slot /></div>
  </div>
</template>
