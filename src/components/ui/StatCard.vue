<script setup lang="ts">
import type { Component } from 'vue'
withDefaults(defineProps<{
  label: string
  value: string | number
  detail?: string
  icon?: Component
  tone?: 'blue' | 'mint' | 'violet' | 'amber'
}>(), { tone: 'blue' })
</script>

<template>
  <article class="stat-card" :class="`stat-card--${tone}`">
    <div class="stat-card__top">
      <span class="stat-card__label">{{ label }}</span>
      <span v-if="icon || $slots.icon" class="stat-card__icon"><slot name="icon"><component :is="icon" v-if="icon" :size="19" :stroke-width="1.8" /></slot></span>
    </div>
    <strong class="stat-card__value">{{ value }}</strong>
    <span v-if="detail" class="stat-card__detail">{{ detail }}</span>
    <slot />
  </article>
</template>

<style scoped>
.stat-card { position:relative; display:flex; flex-direction:column; min-width:0; min-height:134px; padding:17px 19px; overflow:hidden; border:var(--glass-card-border); border-radius:var(--radius-card); background:var(--glass-card-background); color:#fff; box-shadow:var(--shadow-card); backdrop-filter:blur(var(--glass-blur)) saturate(125%); -webkit-backdrop-filter:blur(var(--glass-blur)) saturate(125%); transition:transform .22s ease,box-shadow .22s ease,border-color .22s ease; }
.stat-card::before { content:''; position:absolute; inset:0 0 auto; height:1px; background:linear-gradient(90deg,transparent,rgba(255,255,255,.7) 15%,rgba(255,255,255,.55) 78%,transparent); pointer-events:none; }
.stat-card::after { content:''; position:absolute; width:105px; height:105px; right:-27px; bottom:-62px; border-radius:50%; background:var(--stat-glow); filter:blur(11px); }
.stat-card:hover { transform:translateY(-3px) scale(1.02); border-color:rgba(255,255,255,.72); box-shadow:var(--glass-card-hover-shadow); }
.stat-card--blue { --stat-color:#637de4; --stat-glow:rgba(119,151,255,.26); }
.stat-card--mint { --stat-color:#36a98e; --stat-glow:rgba(88,214,177,.24); }
.stat-card--violet { --stat-color:#9469dc; --stat-glow:rgba(176,132,242,.25); }
.stat-card--amber { --stat-color:#dc9b45; --stat-glow:rgba(243,194,113,.27); }
.stat-card__top { display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }
.stat-card__label { color:rgba(255,255,255,.86); font-size:11px; font-weight:650; text-shadow:0 1px 8px rgba(25,38,76,.24); }
.stat-card__icon { display:grid; width:32px; height:32px; flex:none; place-items:center; border:1px solid rgba(255,255,255,.45); border-radius:10px; color:#fff; background:color-mix(in srgb,var(--stat-color) 40%,transparent); }
.stat-card__value { position:relative; z-index:1; margin-top:6px; font-size:29px; line-height:1.15; letter-spacing:-.05em; font-weight:740; text-shadow:0 1px 10px rgba(25,38,76,.24); }
.stat-card__detail { position:relative; z-index:1; margin-top:5px; color:rgba(255,255,255,.72); font-size:10px; text-shadow:0 1px 8px rgba(25,38,76,.24); }
@media (prefers-reduced-motion:reduce) { .stat-card { transition:none; } .stat-card:hover { transform:none; } }
</style>
