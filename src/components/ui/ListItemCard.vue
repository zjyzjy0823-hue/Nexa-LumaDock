<script setup lang="ts">
withDefaults(defineProps<{
  title: string
  subtitle?: string
  selected?: boolean
}>(), { selected: false })
</script>

<template>
  <button type="button" class="list-item-card" :class="{ 'list-item-card--selected': selected }" :aria-pressed="selected">
    <span v-if="$slots.leading" class="list-item-card__leading"><slot name="leading" /></span>
    <span class="list-item-card__text"><strong>{{ title }}</strong><small v-if="subtitle">{{ subtitle }}</small><slot /></span>
    <span v-if="$slots.trailing" class="list-item-card__trailing"><slot name="trailing" /></span>
  </button>
</template>

<style scoped>
.list-item-card { display:flex; align-items:center; gap:12px; width:100%; min-width:0; padding:12px; border:var(--glass-tile-border); border-radius:15px; background:var(--glass-tile-background); color:#23334f; text-align:left; box-shadow:var(--glass-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); transition:background .18s,transform .18s,border-color .18s,box-shadow .18s; }
.list-item-card:hover { transform:translateY(-2px) scale(1.02); background:var(--glass-tile-hover-background); box-shadow:var(--glass-tile-hover-shadow); }
.list-item-card--selected { border-color:rgba(197,214,255,.9); background:linear-gradient(120deg,rgba(225,235,255,.62),rgba(237,231,255,.48)); box-shadow:0 9px 24px rgba(76,95,164,.12),inset 0 1px 0 rgba(255,255,255,.7); }
.list-item-card__leading,.list-item-card__trailing { display:flex; align-items:center; flex:none; }
.list-item-card__trailing { margin-left:auto; }
.list-item-card__text { display:flex; flex-direction:column; gap:4px; min-width:0; }
.list-item-card__text strong { overflow:hidden; font-size:12px; font-weight:690; text-overflow:ellipsis; white-space:nowrap; }
.list-item-card__text small { overflow:hidden; color:#50617c; font-size:10px; text-overflow:ellipsis; white-space:nowrap; }
@media (prefers-reduced-motion:reduce) { .list-item-card { transition:none; } .list-item-card:hover { transform:none; } }
</style>
