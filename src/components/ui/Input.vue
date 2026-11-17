<script setup lang="ts">
import { Search } from 'lucide-vue-next'

withDefaults(defineProps<{
  modelValue: string
  type?: string
  placeholder?: string
  ariaLabel?: string
  id?: string
  name?: string
  autocomplete?: string
  required?: boolean
  maxlength?: number
  disabled?: boolean
}>(), { type: 'text', required: false, disabled: false })

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
  <div class="opus-input-wrap" :class="{ 'opus-input-wrap--search': type === 'search', 'opus-input-wrap--disabled': disabled }">
    <Search v-if="type === 'search'" :size="15" :stroke-width="1.9" aria-hidden="true" />
    <input
      :id="id"
      class="input"
      :name="name"
      :autocomplete="autocomplete"
      :value="modelValue"
      :type="type"
      :placeholder="placeholder"
      :aria-label="ariaLabel"
      :required="required"
      :maxlength="maxlength"
      :disabled="disabled"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
    />
  </div>
</template>

<style scoped>
.opus-input-wrap { position: relative; min-width: 0; }
.opus-input-wrap--search svg { position: absolute; left: 10px; top: 50%; translate: 0 -50%; color: var(--text-3); pointer-events: none; }
.opus-input-wrap--search .input { padding-left: 32px; }
.opus-input-wrap--disabled { opacity: .55; }
.opus-input-wrap .input::-webkit-search-cancel-button { display: none; }
</style>
