<script setup lang="ts">
import { ArrowDown, ArrowUp, ChevronRight } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { systemSnapshot } from '../../data/operations'
</script>

<template>
  <GlassCard title="系统" class="system-card">
    <template #action><ChevronRight class="system-action-arrow" :size="20" aria-hidden="true" /></template>

    <div class="system-layout">
      <div class="system-metrics">
        <div v-for="metric in systemSnapshot.metrics.slice(0, 3)" :key="metric.id" class="metric" :data-type="metric.id">
          <span class="metric-name">{{ metric.label }}</span>
          <span class="metric-track"><span :style="{ width: `${metric.percent}%` }" /></span>
          <strong>{{ metric.value }}</strong>
        </div>
        <div class="network-row">
          <span>网络</span>
          <span><ArrowDown :size="13" />{{ systemSnapshot.networkDown }}</span>
          <span><ArrowUp :size="13" />{{ systemSnapshot.networkUp }}</span>
        </div>
      </div>

      <div class="memory-overview">
        <div class="ring" :aria-label="`内存使用率 ${systemSnapshot.memoryPercent}%`" role="img">
          <svg viewBox="0 0 120 120" aria-hidden="true">
            <defs>
              <linearGradient id="memory-ring" x1="0" y1="1" x2="1" y2="0">
                <stop offset="0%" stop-color="#9aaaff" />
                <stop offset="58%" stop-color="#76ceff" />
                <stop offset="100%" stop-color="#7bf3b6" />
              </linearGradient>
            </defs>
            <circle class="ring-track" cx="60" cy="60" r="48" />
            <circle class="ring-fill" cx="60" cy="60" r="48" pathLength="100" :stroke-dasharray="`${systemSnapshot.memoryPercent} 100`" />
          </svg>
          <strong>{{ systemSnapshot.memoryPercent }}<small>%</small></strong>
        </div>
        <span class="memory-label">内存</span>
        <span class="memory-detail">{{ systemSnapshot.memoryUsed }}</span>
      </div>
    </div>
  </GlassCard>
</template>

<style scoped>
.system-card{padding:17px 30px 14px 28px}
.system-card :deep(.glass-card__header){margin-bottom:10px}
.system-card :deep(.glass-card__title){color:#fff;font-size:20px;font-weight:500}
.system-card :deep(.glass-card__title)::before{content:'✧';display:inline-block;margin-right:12px;font-size:26px;line-height:.4;vertical-align:-2px}
.system-card :deep(.glass-card__title)::after{content:'›';display:inline-block;margin-left:11px;font-size:26px;font-weight:300;line-height:.5;vertical-align:-1px}
.system-action-arrow{color:#fff}
.system-layout{display:flex;align-items:center;justify-content:space-between;gap:22px;min-width:0;height:100%;transform:translateY(-14px)}
.system-metrics{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:space-between;gap:12px;padding:4px 0 9px}
.metric{display:grid;grid-template-columns:60px minmax(42px,1fr) 36px;align-items:center;gap:8px;font-size:14px}
.metric-name{color:rgba(255,255,255,.95)}
.metric-track{display:block;height:12px;border-radius:20px;background:rgba(213,230,255,.25);overflow:hidden}
.metric-track>span{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#8ddcfc,#8abaff);box-shadow:0 0 12px rgba(115,196,255,.35)}
.metric[data-type="memory"] .metric-track>span{background:linear-gradient(90deg,#d2a8ff,#e9aaff)}
.metric[data-type="disk"] .metric-track>span{background:linear-gradient(90deg,#81d8f7,#8df0b5)}
.metric strong{color:rgba(255,255,255,.98);font-size:14px;font-weight:560;text-align:right;font-variant-numeric:tabular-nums}
.network-row{display:flex;align-items:center;gap:10px;color:rgba(255,255,255,.95);font-size:13px;white-space:nowrap}
.network-row>span:first-child{margin-right:3px}
.network-row>span:not(:first-child){display:inline-flex;align-items:center;gap:2px}
.network-row svg{color:#b4f4ff}
.memory-overview{width:126px;flex:none;display:flex;flex-direction:column;align-items:center;justify-content:center}
.ring{position:relative;width:112px;height:112px}
.ring svg{width:100%;height:100%;transform:rotate(-90deg)}
.ring circle{fill:none;stroke-width:11}
.ring-track{stroke:rgba(223,235,255,.24)}
.ring-fill{stroke:url(#memory-ring);stroke-linecap:round;filter:drop-shadow(0 0 5px rgba(128,210,255,.34))}
.ring strong{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#fff;font-size:28px;font-weight:650;font-variant-numeric:tabular-nums}
.ring small{font-size:16px;font-weight:520}
.memory-label{margin-top:4px;color:#fff;font-size:16px}
.memory-detail{margin-top:2px;color:rgba(255,255,255,.83);font-size:14px;white-space:nowrap}
@container (max-width: 400px) {
  .system-card { padding: 12px 14px; }
  .system-layout { gap: 8px; transform: none; }
  .metric { grid-template-columns: 48px minmax(28px, 1fr) 30px; gap: 5px; font-size: 11px; }
  .metric strong { font-size: 11px; }
  .metric-track { height: 9px; }
  .network-row { flex-wrap: wrap; gap: 3px 6px; font-size: 10px; white-space: normal; }
  .memory-overview { width: 90px; }
  .ring { width: 78px; height: 78px; }
  .ring strong { font-size: 21px; }
  .memory-label { font-size: 12px; }
  .memory-detail { font-size: 10px; }
}
@container (max-width: 280px) {
  .memory-overview { width: 66px; }
  .ring { width: 62px; height: 62px; }
  .memory-label, .memory-detail { display: none; }
}
@container (max-height: 220px) {
  .system-card :deep(.glass-card__header) { margin-bottom: 5px; }
  .system-metrics { gap: 5px; padding-block: 0; }
}
@media(max-width:460px){.system-card{padding-inline:18px}.system-layout{gap:6px;transform:none}.metric{grid-template-columns:55px minmax(35px,1fr) 30px;gap:6px;font-size:12px}.metric strong{font-size:12px}.network-row{gap:5px;font-size:10px}.memory-overview{width:100px}.ring{width:93px;height:93px}.ring strong{font-size:24px}.memory-label{font-size:13px}.memory-detail{font-size:11px}}
</style>
