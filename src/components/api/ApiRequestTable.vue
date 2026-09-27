<script setup lang="ts">
import { Activity } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import type { ApiRequest } from '../../types/api'

defineProps<{ requests: ApiRequest[] }>()

function statusTone(status: number) {
  if (status >= 500) return 'error'
  if (status >= 400) return 'warning'
  return 'success'
}
</script>

<template>
  <GlassCard class="api-request-table" title="Recent Requests">
    <template #action><span class="api-request-table__live"><span />LIVE LOG</span></template>
    <p class="api-request-table__intro">最新 API 请求与响应</p>
    <div v-if="requests.length" class="api-request-table__scroll">
      <table>
        <thead><tr><th scope="col">方法</th><th scope="col">路径</th><th scope="col">状态</th><th scope="col">耗时</th><th scope="col">时间</th></tr></thead>
        <tbody>
          <tr v-for="request in requests" :key="request.id">
            <td><span class="api-request-table__method" :class="`api-request-table__method--${request.method.toLowerCase()}`">{{ request.method }}</span></td>
            <td><code :title="request.path">{{ request.path }}</code></td>
            <td><span class="api-request-table__status" :class="`api-request-table__status--${statusTone(request.status)}`"><i />{{ request.status }}</span></td>
            <td class="api-request-table__duration">{{ request.durationMs }} ms</td>
            <td class="api-request-table__time">{{ request.time }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-else class="api-request-table__empty"><Activity :size="24" /><span>没有找到匹配的请求</span></div>
    <div class="api-request-table__footer"><span>{{ requests.length }} 次调用</span><span>最近更新 {{ requests[0]?.time ?? '—' }}</span></div>
  </GlassCard>
</template>

<style scoped>
.api-request-table { min-height:437px; }
.api-request-table :deep(.glass-card__body) { display:flex; flex-direction:column; overflow:visible; }
.api-request-table__live { display:inline-flex; align-items:center; gap:6px; color:rgba(255,255,255,.8); font-size:9px; font-weight:760; letter-spacing:.1em; white-space:nowrap; }
.api-request-table__live span { width:6px; height:6px; border-radius:50%; background:#97f0c6; box-shadow:0 0 0 3px rgba(151,240,198,.13); }
.api-request-table__intro { margin:-5px 0 16px; color:rgba(255,255,255,.73); font-size:10px; }
.api-request-table__scroll { min-width:0; flex:1; overflow-x:auto; overflow-y:visible; scrollbar-width:thin; }
table { width:100%; min-width:425px; border-collapse:separate; border-spacing:0 6px; text-align:left; table-layout:fixed; }
th { padding:0 9px 6px; color:rgba(255,255,255,.78); font-size:9px; font-weight:700; }
th:nth-child(1) { width:57px; } th:nth-child(2) { width:auto; } th:nth-child(3) { width:50px; } th:nth-child(4) { width:54px; } th:nth-child(5) { width:65px; }
td { height:48px; padding:8px 9px; border-top:1px solid rgba(255,255,255,.64); border-bottom:1px solid rgba(255,255,255,.64); color:var(--text-secondary); background:var(--glass-tile-background); font-size:10px; white-space:nowrap; }
td:first-child { border-left:1px solid rgba(255,255,255,.64); border-radius:10px 0 0 10px; }
td:last-child { border-right:1px solid rgba(255,255,255,.64); border-radius:0 10px 10px 0; }
td code { display:block; overflow:hidden; color:var(--text-primary); font-size:10px; font-weight:630; text-overflow:ellipsis; white-space:nowrap; }
.api-request-table__method { display:inline-grid; min-width:35px; min-height:20px; place-items:center; padding:2px 5px; border-radius:6px; color:#5275c6; background:rgba(104,143,231,.13); font-size:9px; font-weight:780; }
.api-request-table__method--post { color:#8765c4; background:rgba(156,120,217,.15); }
.api-request-table__status { display:inline-flex; align-items:center; gap:4px; font-size:10px; font-weight:740; }
.api-request-table__status i { width:5px; height:5px; border-radius:50%; background:currentColor; }
.api-request-table__status--success { color:#289a76; }
.api-request-table__status--warning { color:#cb943e; }
.api-request-table__status--error { color:#d46c76; }
.api-request-table__duration,.api-request-table__time { color:#687993; font-size:9px; }
.api-request-table__empty { display:flex; flex:1; flex-direction:column; align-items:center; justify-content:center; gap:8px; min-height:170px; color:rgba(255,255,255,.78); font-size:11px; }
.api-request-table__footer { display:flex; justify-content:space-between; gap:8px; padding:11px 1px 0; color:rgba(255,255,255,.73); font-size:9px; }
.api-request-table__footer span:last-child { display:inline-flex; align-items:center; gap:3px; color:rgba(255,255,255,.85); }
@media (max-width:560px) {
  .api-request-table { min-height:0; }
  .api-request-table__scroll { overflow:visible; }
  table { min-width:0; border-spacing:0; }
  thead { display:none; }
  tbody { display:grid; gap:7px; }
  tr { display:grid; grid-template-columns:42px minmax(0,1fr) 36px; grid-template-rows:auto auto; align-items:center; column-gap:7px; row-gap:6px; padding:9px; border:1px solid rgba(255,255,255,.64); border-radius:10px; background:var(--glass-tile-background); }
  td,td:first-child,td:last-child { height:auto; padding:0; border:0; border-radius:0; background:transparent; }
  td:nth-child(1) { grid-column:1; grid-row:1 / 3; }
  td:nth-child(2) { grid-column:2; grid-row:1; }
  td:nth-child(3) { grid-column:3; grid-row:1; }
  td:nth-child(4) { grid-column:2; grid-row:2; }
  td:nth-child(5) { grid-column:3; grid-row:2; text-align:right; }
  td code { font-size:10px; }
  .api-request-table__duration,.api-request-table__time { font-size:9px; }
}
</style>
