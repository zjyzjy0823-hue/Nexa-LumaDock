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
    class="glass-toggle"
    :class="{ 'glass-toggle--on': modelValue }"
    type="button"
    role="switch"
    :aria-checked="modelValue"
    :aria-label="ariaLabel"
    :disabled="disabled"
    @click="emit('update:modelValue', !modelValue)"
  ><span class="glass-toggle__thumb" /></button>
</template>

<style scoped>
.glass-toggle { position:relative; display:inline-flex; align-items:center; width:40px; height:23px; flex:none; padding:2px; border:1px solid rgba(132,153,194,.36); border-radius:999px; background:rgba(125,145,184,.24); box-shadow:inset 0 1px 3px rgba(39,55,98,.1),0 1px 0 rgba(255,255,255,.6); transition:background .2s,border-color .2s,box-shadow .2s; }
.glass-toggle:hover:not(:disabled) { border-color:rgba(105,133,215,.55); }
.glass-toggle--on { border-color:rgba(255,255,255,.48); background:linear-gradient(120deg,var(--accent-color),#8e7ce3); box-shadow:0 3px 9px rgba(88,111,204,.2),inset 0 1px 0 rgba(255,255,255,.27); }
.glass-toggle__thumb { display:block; width:17px; height:17px; border-radius:50%; background:#fff; box-shadow:0 1px 4px rgba(29,44,88,.22); transition:transform .2s; }
.glass-toggle--on .glass-toggle__thumb { transform:translateX(17px); }
.glass-toggle:disabled { opacity:.5; }
</style>
