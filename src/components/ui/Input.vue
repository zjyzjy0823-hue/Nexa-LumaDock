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
  <div class="glass-input" :class="{ 'glass-input--search': type === 'search', 'glass-input--disabled': disabled }">
    <Search v-if="type === 'search'" :size="16" :stroke-width="1.9" aria-hidden="true" />
    <input
      :id="id"
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
.glass-input { display:flex; align-items:center; gap:8px; min-width:0; min-height:39px; padding:0 11px; border:1px solid rgba(156,177,216,.36); border-radius:11px; color:#6380bb; background:rgba(255,255,255,.76); box-shadow:inset 0 1px 0 rgba(255,255,255,.85),0 5px 14px rgba(31,49,103,.07); transition:border-color .18s,background .18s,box-shadow .18s; }
.glass-input:focus-within { border-color:color-mix(in srgb,var(--accent-color) 66%,white); background:rgba(255,255,255,.9); box-shadow:0 0 0 3px rgba(113,145,237,.14),inset 0 1px 0 rgba(255,255,255,.9); }
.glass-input--disabled { opacity:.55; }
.glass-input svg { flex:none; }
.glass-input input { width:100%; min-width:0; padding:0; border:0; outline:0; color:var(--text-primary); background:transparent; font-size:12px; }
.glass-input input::placeholder { color:#8594aa; }
.glass-input input::-webkit-search-cancel-button { display:none; }
</style>
