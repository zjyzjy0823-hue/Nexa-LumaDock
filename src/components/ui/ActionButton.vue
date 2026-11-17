<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{
  label?: string
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'md' | 'sm'
  disabled?: boolean
  type?: 'button' | 'submit'
}>(), { variant: 'primary', size: 'md', type: 'button' })

const buttonClass = computed(() => [
  'btn',
  props.variant === 'primary' ? 'btn-primary' : props.variant === 'secondary' ? 'btn-ghost' : props.variant === 'danger' ? 'btn-danger' : 'btn-subtle',
  props.size === 'sm' ? 'btn-sm' : undefined,
])
</script>

<template>
  <button :class="buttonClass" :type="type" :disabled="disabled"><slot>{{ label }}</slot></button>
</template>
