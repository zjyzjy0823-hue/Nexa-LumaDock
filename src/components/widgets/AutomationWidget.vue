<script setup lang="ts">
import { ref } from 'vue'
import { Activity, DatabaseBackup, RefreshCw, Send } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { automationItems } from '../../data/operations'

const icons = { backup: DatabaseBackup, sync: RefreshCw, health: Activity, telegram: Send }
const items = ref(automationItems.map((item) => ({ ...item })))
</script>

<template>
  <GlassCard title="自动化" class="automation-card">
    <template #action><span class="see-all">查看全部 (5)</span></template>

    <div class="automation-list">
      <div v-for="item in items" :key="item.id" class="automation-row">
        <component :is="icons[item.id]" class="automation-icon" :size="17" :stroke-width="1.8" />
        <span class="automation-name">{{ item.name }}</span>
        <button
          type="button"
          class="toggle"
          :class="{ enabled: item.enabled }"
          role="switch"
          :aria-label="item.name"
          :aria-checked="item.enabled"
          @click="item.enabled = !item.enabled"
        ><span /></button>
      </div>
    </div>
  </GlassCard>
</template>

<style scoped>
.automation-card{padding:12px 19px 9px}
.automation-card :deep(.glass-card__header){margin-bottom:9px}
.automation-card :deep(.glass-card__title){color:#fff;font-size:20px;font-weight:500}
.automation-card :deep(.glass-card__title)::after{content:'›';display:inline-block;margin-left:12px;font-size:26px;font-weight:300;line-height:.5;vertical-align:-1px}
.see-all{color:rgba(255,255,255,.88);font-size:13px;white-space:nowrap}
.automation-list{display:flex;flex-direction:column}
.automation-row{min-height:32px;display:flex;align-items:center;gap:11px;border-bottom:1px solid rgba(255,255,255,.13)}
.automation-row:last-child{border-bottom:0}
.automation-icon{flex:none;color:rgba(255,255,255,.97)}
.automation-name{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:rgba(255,255,255,.97);font-size:13px}
.toggle{position:relative;flex:none;width:34px;height:17px;padding:0;border:1px solid rgba(255,255,255,.4);border-radius:20px;background:rgba(223,230,248,.73);cursor:pointer;transition:background .2s ease}
.toggle.enabled{background:linear-gradient(90deg,#4481f6,#568dff);box-shadow:0 0 9px rgba(115,178,255,.28)}
.toggle span{position:absolute;left:1px;top:1px;width:13px;height:13px;border-radius:50%;background:#fff;box-shadow:0 1px 4px rgba(23,39,85,.25);transition:transform .2s ease}
.toggle.enabled span{transform:translateX(15px)}
.toggle:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
@container (max-height: 210px) {
  .automation-card { padding: 9px 12px; }
  .automation-card :deep(.glass-card__header) { margin-bottom: 5px; }
  .automation-row { min-height: 25px; gap: 7px; }
  .automation-name { font-size: 11px; }
  .automation-icon { width: 14px; height: 14px; }
}
@container (max-height: 180px) {
  .automation-row { min-height: 22px; }
}
@container (max-width: 250px) {
  .automation-card { padding-inline: 10px; }
  .see-all { font-size: 10px; }
  .toggle { width: 30px; }
  .toggle.enabled span { transform: translateX(11px); }
}
@media(prefers-reduced-motion:reduce){.toggle,.toggle span{transition:none}}
</style>
