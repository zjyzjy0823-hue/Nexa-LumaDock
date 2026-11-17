<script setup lang="ts">
import paths from '../../styles/opus-icons'

defineProps<{ name: keyof typeof paths }>()
</script>

<template>
  <svg class="i" viewBox="0 0 24 24" aria-hidden="true" v-html="paths[name]" />
</template>
