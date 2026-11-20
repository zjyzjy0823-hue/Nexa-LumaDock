<script setup lang="ts">
defineProps<{ progress: number; value: string; caption: string; compact?: boolean }>()
</script>

<template>
  <div class="dashboard-gauge">
    <div class="gauge-arc">
      <svg viewBox="0 0 132 72" aria-hidden="true">
        <path class="gauge-track" d="M 14 64 A 52 52 0 0 1 118 64" />
        <path class="gauge-fill" d="M 14 64 A 52 52 0 0 1 118 64" pathLength="100"
          stroke-dasharray="100" :stroke-dashoffset="100 - progress" />
      </svg>
      <div class="gauge-value num" :class="{ compact }" :title="value">{{ value }}</div>
    </div>
    <div class="gauge-caption">{{ caption }}</div>
  </div>
</template>

<style scoped>
.dashboard-gauge { display: grid; justify-items: center; margin: auto 0; min-width: 0; }
.gauge-arc { position: relative; display: grid; place-items: center; max-width: 100%; }
.gauge-arc svg { width: clamp(132px, 12cqi, 232px); max-width: 100%; height: auto; overflow: visible; }
.gauge-track, .gauge-fill { fill: none; stroke-width: 11; stroke-linecap: butt; }
.gauge-track { stroke: var(--surface-3); }
.gauge-fill { stroke: var(--accent); transition: stroke-dashoffset 680ms var(--ease-out); }
.gauge-value {
  position: absolute;
  inset: auto 8% 2px;
  text-align: center;
  font-size: clamp(14px, 1.35cqi, 24px);
  font-weight: 750;
  color: var(--text);
  letter-spacing: -.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.gauge-value.compact { font-size: clamp(12px, 1.18cqi, 21px); }
.gauge-caption { font-size: clamp(11px, 0.85cqi, 14px); color: var(--text-3); margin-top: 4px; text-align: center; }
[data-motion="reduced"] .gauge-fill { transition: none; }
@media (prefers-reduced-motion: reduce) { .gauge-fill { transition: none; } }
</style>
