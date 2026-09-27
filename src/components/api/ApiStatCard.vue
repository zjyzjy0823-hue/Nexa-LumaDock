<script setup lang="ts">
import { computed } from 'vue'
import { Activity, KeyRound, RadioTower, ShieldAlert } from 'lucide-vue-next'
import StatCard from '../ui/StatCard.vue'
import type { ApiStat } from '../../types/api'

const props = defineProps<{ stat: ApiStat }>()
const icons = { requests: Activity, keys: KeyRound, webhooks: RadioTower, errors: ShieldAlert }
const sparkline = computed(() => {
  const values = props.stat.sparkline
  const low = Math.min(...values)
  const span = Math.max(...values) - low || 1
  return values.map((value, index) => `${2 + index * 96 / (values.length - 1)},${27 - (value - low) / span * 21}`).join(' ')
})
</script>

<template>
  <StatCard class="api-stat-card" :label="stat.label" :value="stat.value" :detail="stat.trend" :tone="stat.tone" :icon="icons[stat.id]">
    <svg class="api-stat-card__sparkline" viewBox="0 0 100 32" preserveAspectRatio="none" aria-hidden="true">
      <polyline :points="sparkline" />
    </svg>
  </StatCard>
</template>

<style scoped>
.api-stat-card { min-height: 143px; }
.api-stat-card__sparkline { position:absolute; right:14px; bottom:17px; width:90px; height:31px; overflow:visible; color:var(--stat-color); opacity:.95; filter:drop-shadow(0 2px 3px rgba(36,54,102,.16)); }
.api-stat-card__sparkline polyline { fill:none; stroke:currentColor; stroke-width:2.6; stroke-linecap:round; stroke-linejoin:round; vector-effect:non-scaling-stroke; }
@media (max-width:560px) {
  .api-stat-card {
    min-height:128px;
    background:linear-gradient(160deg,rgba(78,99,163,.81),rgba(45,60,118,.79) 62%,rgba(65,54,117,.8));
  }
  .api-stat-card__sparkline { width:75px; opacity:.88; }
}
</style>
