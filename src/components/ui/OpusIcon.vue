<script setup lang="ts">
import paths from '../../styles/opus-icons'

defineProps<{ name: keyof typeof paths }>()
</script>

<template>
  <img v-if="name === 'hermes'" class="i hermes-mark" src="/hermes-agent.png" alt="" aria-hidden="true" />
  <svg v-else class="i" viewBox="0 0 24 24" aria-hidden="true" v-html="paths[name]" />
</template>

<style scoped>
.hermes-mark { object-fit: contain; border-radius: 23%; }
</style>
