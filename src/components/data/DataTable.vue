<script setup lang="ts">
import { FileText, Layers3 } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import ActionButton from '../ui/ActionButton.vue'
import StatusBadge from '../ui/StatusBadge.vue'
import type { RecordSummary, CollectionSummary } from '../../types/data'

defineProps<{
  collection: CollectionSummary | null
  records: RecordSummary[]
  total: number
  matchedCount: number
  hasMore: boolean
  loading: boolean
  error: string
}>()
const emit = defineEmits<{ edit: [record: RecordSummary]; remove: [record: RecordSummary]; loadMore: []; retry: [] }>()
</script>

<template>
  <GlassCard class="data-table" :title="collection ? `${collection.name} Collection` : '数据库视图'">
    <template #action><span class="data-table__count">{{ total }} 条记录</span></template>
    <div class="data-table__intro"><span class="data-table__live" /><span>{{ collection?.description ?? '选择一个集合，查看其中的记录' }}</span><span class="data-table__view">表格视图</span></div>
    <div class="data-table__scroll">
      <table>
        <thead><tr><th scope="col">名称</th><th scope="col">状态</th><th scope="col">分类</th><th scope="col">更新时间</th><th scope="col">操作</th></tr></thead>
        <tbody v-if="records.length">
          <tr v-for="record in records" :key="record.id">
            <td><span class="data-table__name"><span class="data-table__file"><FileText :size="15" :stroke-width="1.8" /></span><strong>{{ record.name }}</strong></span></td>
            <td><StatusBadge :label="record.status" :tone="record.statusTone" /></td>
            <td><span class="data-table__category">{{ record.category }}</span></td>
            <td><time>{{ record.updatedAt }}</time></td>
            <td><div class="data-table__actions"><ActionButton variant="secondary" size="sm" @click="emit('edit', record)">编辑</ActionButton><ActionButton variant="danger" size="sm" @click="emit('remove', record)">删除</ActionButton></div></td>
          </tr>
        </tbody>
      </table>
      <div v-if="!records.length" class="data-table__empty"><Layers3 :size="24" /><strong>{{ collection?.recordCount === 0 ? '集合还是空的' : '暂无匹配记录' }}</strong><span>{{ !collection ? '创建或选择一个集合开始管理数据。' : collection.recordCount === 0 ? '新集合已创建，可用于整理下一批数据。' : '换个关键词试试，或选择其他集合。' }}</span></div>
    </div>
    <p v-if="loading" role="status">正在加载记录…</p>
    <p v-if="error" role="alert">{{ error }} <ActionButton variant="secondary" size="sm" @click="emit('retry')">重试</ActionButton></p>
    <div class="data-table__footer">
      <span>显示 {{ records.length }} / {{ total }} 条记录<span v-if="matchedCount !== total"> · 匹配 {{ matchedCount }} 条</span></span>
      <ActionButton v-if="hasMore" variant="secondary" size="sm" :disabled="loading" @click="emit('loadMore')">加载更多</ActionButton>
      <span>最近更新优先</span>
    </div>
  </GlassCard>
</template>

<style scoped>
.data-table { height:auto; min-height:365px; }
.data-table__count { padding:6px 9px; border:1px solid var(--workbench-line); border-radius:8px; color:var(--workbench-text); background:var(--workbench-solid); font-size:10px; font-weight:650; white-space:nowrap; }
.data-table__intro { display:flex; align-items:center; gap:8px; padding:2px 1px 15px; color:var(--workbench-text); font-size:11px; text-shadow:none; }
.data-table__live { width:7px; height:7px; flex:none; border-radius:50%; background:var(--workbench-muted-surface); box-shadow:0 0 0 4px rgba(100,192,170,.14); }
.data-table__view { margin-left:auto; color:var(--workbench-muted); font-size:10px; white-space:nowrap; }
.data-table__scroll { min-width:0; overflow-x:auto; border:var(--glass-tile-border); border-radius:13px; background:var(--workbench-solid); box-shadow:var(--glass-tile-shadow); backdrop-filter:var(--workbench-material); -webkit-backdrop-filter:var(--workbench-material); }
table { width:100%; min-width:515px; border-collapse:collapse; text-align:left; }
th { padding:12px 14px; color:var(--workbench-muted); background:var(--workbench-muted-surface); font-size:10px; font-weight:680; }
th:first-child { width:38%; }
th:nth-child(2) { width:20%; }
th:nth-child(3) { width:20%; }
td { height:58px; padding:10px 14px; border-top:1px solid var(--workbench-line); color:var(--workbench-muted); font-size:11px; }
tbody tr { transition:background .18s; }
tbody tr:hover { background:var(--workbench-solid); }
.data-table__name { display:flex; align-items:center; gap:10px; min-width:0; }
.data-table__name strong { overflow:hidden; color:var(--workbench-text); font-size:11px; font-weight:700; text-overflow:ellipsis; white-space:nowrap; }
.data-table__file { display:grid; width:28px; height:28px; flex:none; place-items:center; border:1px solid var(--workbench-line); border-radius:8px; color:var(--workbench-good); background:var(--workbench-solid); }
.data-table__category { display:inline-block; padding:6px 9px; border-radius:7px; color:var(--workbench-muted); background:var(--workbench-solid); white-space:nowrap; }
time { color:var(--workbench-muted); white-space:nowrap; }
.data-table__actions { display:flex; gap:6px; }
.data-table__empty { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:7px; min-height:210px; color:var(--workbench-muted); font-size:11px; }
.data-table__empty strong { color:var(--workbench-muted); font-size:13px; }
.data-table__footer { display:flex; justify-content:space-between; gap:12px; padding:13px 1px 2px; color:var(--workbench-muted); font-size:10px; }
@media (max-width:640px) { .data-table__intro { flex-wrap:wrap; } .data-table__view { display:none; } }
</style>
