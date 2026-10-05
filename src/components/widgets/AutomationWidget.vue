<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { Workflow } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { useAuthStore } from '../../stores/auth'
import { useAutomationStore } from '../../stores/automation'

const auth = useAuthStore()
const store = useAutomationStore()
const items = computed(() => store.items.slice(0, 3))
const enabledCount = computed(() => store.items.filter(item => item.enabled).length)
const failedCount = computed(() => store.executions.filter(item => item.status === 'failed').length)
const recentExecution = computed(() => [...store.executions].sort((a, b) => Date.parse(b.startedAt) - Date.parse(a.startedAt))[0])
const recentStatus = computed(() => recentExecution.value ? ({ success: '成功', succeeded: '成功', failed: '失败', queued: '排队中', claimed: '执行中', running: '执行中', skipped: '已跳过', cancelled: '已取消' }[recentExecution.value.status]) : '暂无执行记录')
onMounted(() => { if (auth.token) void store.load(auth.token).catch(() => {}) })
async function toggle(id: string, enabled: boolean) {
  if (!auth.token) return
  try { await store.update(auth.token, id, { enabled: !enabled }) } catch { /* Store exposes the error. */ }
}
</script>

<template>
  <GlassCard title="自动化" class="automation-card">
    <template #action><span class="see-all">{{ store.loaded ? `${store.items.length} 个 · 已启用 ${enabledCount}` : '—' }}</span></template>

    <div class="automation-list">
      <p v-if="store.error" class="automation-state" role="alert">数据加载失败 <button type="button" @click="auth.token && store.load(auth.token, true).catch(() => {})">重试</button></p>
      <p v-else-if="!store.loaded" class="automation-state">正在加载自动化…</p>
      <p v-else-if="!items.length" class="automation-state">暂无自动化</p>
      <div v-for="item in store.error ? [] : items" :key="item.id" class="automation-row">
        <Workflow class="automation-icon" :size="17" :stroke-width="1.8" />
        <span class="automation-name">{{ item.name }}</span>
        <button
          type="button"
          class="toggle"
          :class="{ enabled: item.enabled }"
          role="switch"
          :aria-label="item.name"
          :aria-checked="item.enabled"
          @click="toggle(item.id, item.enabled)"
        ><span /></button>
      </div>
      <p v-if="store.loaded && !store.error && store.items.length" class="execution-summary">{{ store.runtimeError || `执行 ${store.executions.length} 次 · 失败 ${failedCount} 次` }}<br v-if="!store.runtimeError" /><template v-if="!store.runtimeError">{{ recentExecution ? `最近执行：${recentStatus}` : '暂无执行记录' }}</template></p>
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
.automation-state,.execution-summary{margin:7px 0;color:rgba(255,255,255,.9);font-size:12px}
.automation-state button{margin-left:5px;border:0;background:none;color:white;text-decoration:underline;cursor:pointer}
.execution-summary{line-height:1.5}
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
