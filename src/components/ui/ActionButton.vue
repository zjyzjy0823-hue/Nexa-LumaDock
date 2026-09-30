<script setup lang="ts">
withDefaults(defineProps<{
  label?: string
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'md' | 'sm'
  disabled?: boolean
  type?: 'button' | 'submit'
}>(), { variant: 'primary', size: 'md', type: 'button' })
</script>

<template>
  <button class="action-button" :class="[`action-button--${variant}`, `action-button--${size}`]" :type="type" :disabled="disabled"><slot>{{ label }}</slot></button>
</template>

<style scoped>
.action-button { display:inline-flex; align-items:center; justify-content:center; gap:8px; flex:none; border:1px solid transparent; border-radius:12px; font-size:12px; font-weight:690; line-height:1; white-space:nowrap; transition:transform .18s,box-shadow .18s,background .18s; }
.action-button:hover:not(:disabled) { transform:translateY(-2px); }
.action-button--md { min-height:39px; padding:0 15px; }
.action-button--sm { min-height:31px; padding:0 11px; font-size:11px; border-radius:10px; }
.action-button--primary { color:white; border-color:rgba(255,255,255,.33); background:linear-gradient(125deg,#6e8af0,#8a75df); box-shadow:0 8px 18px rgba(93,106,198,.25),inset 0 1px 0 rgba(255,255,255,.22); }
.action-button--primary:hover:not(:disabled) { box-shadow:0 12px 24px rgba(93,106,198,.34),inset 0 1px 0 rgba(255,255,255,.22); }
.action-button--danger { color:white; border-color:rgba(255,255,255,.4); background:linear-gradient(125deg,#cc576c,#b74460); box-shadow:0 6px 16px rgba(156,47,74,.2),inset 0 1px 0 rgba(255,255,255,.25); }
.action-button--secondary { color:#4d6190; border-color:rgba(158,177,221,.37); background:rgba(255,255,255,.68); box-shadow:inset 0 1px 0 rgba(255,255,255,.9); }
.action-button--secondary:hover:not(:disabled) { background:white; }
.action-button--ghost { color:#63738c; background:transparent; }
.action-button--ghost:hover:not(:disabled) { background:rgba(255,255,255,.45); }
.action-button:disabled { opacity:.52; }
</style>
