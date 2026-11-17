<script setup lang="ts">
withDefaults(defineProps<{
  modelValue: boolean
  ariaLabel?: string
  disabled?: boolean
}>(), { disabled: false })

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()
</script>

<template>
  <button
    class="switch"
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :aria-label="ariaLabel"
    :disabled="disabled"
    @click="emit('update:modelValue', !modelValue)"
  />
</template>
