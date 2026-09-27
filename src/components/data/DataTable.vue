<script setup lang="ts">
import { FileText, Layers3 } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import StatusBadge from '../ui/StatusBadge.vue'
import type { CollectionRecord, DataCollection } from '../../types/data'

defineProps<{
  collection: DataCollection | null
  records: CollectionRecord[]
}>()
const emit = defineEmits<{ edit: [record: CollectionRecord]; remove: [record: CollectionRecord] }>()
</script>

<template>
  <GlassCard class="data-table" :title="collection ? `${collection.name} Collection` : '数据库视图'">
    <template #action><span class="data-table__count">{{ collection?.recordCount ?? 0 }} 条记录</span></template>
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
            <td><button type="button" @click="emit('edit', record)">编辑</button> <button type="button" @click="emit('remove', record)">删除</button></td>
          </tr>
        </tbody>
      </table>
      <div v-if="!records.length" class="data-table__empty"><Layers3 :size="24" /><strong>{{ collection?.recordCount === 0 ? '集合还是空的' : '暂无匹配记录' }}</strong><span>{{ !collection ? '创建或选择一个集合开始管理数据。' : collection.recordCount === 0 ? '新集合已创建，可用于整理下一批数据。' : '换个关键词试试，或选择其他集合。' }}</span></div>
    </div>
    <div class="data-table__footer"><span>显示 {{ records.length }} / {{ collection?.recordCount ?? 0 }} 条记录</span><span>最近更新优先</span></div>
  </GlassCard>
</template>

<style scoped>
.data-table { height:auto; min-height:365px; }
.data-table__count { padding:6px 9px; border:1px solid rgba(255,255,255,.54); border-radius:8px; color:#fff; background:rgba(255,255,255,.17); font-size:10px; font-weight:650; white-space:nowrap; }
.data-table__intro { display:flex; align-items:center; gap:8px; padding:2px 1px 15px; color:rgba(255,255,255,.88); font-size:11px; text-shadow:0 1px 6px rgba(20,33,71,.25); }
.data-table__live { width:7px; height:7px; flex:none; border-radius:50%; background:#64c0aa; box-shadow:0 0 0 4px rgba(100,192,170,.14); }
.data-table__view { margin-left:auto; color:rgba(255,255,255,.75); font-size:10px; white-space:nowrap; }
.data-table__scroll { min-width:0; overflow-x:auto; border:var(--glass-tile-border); border-radius:13px; background:linear-gradient(140deg,rgba(250,251,255,.56),rgba(235,239,255,.34)); box-shadow:var(--glass-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); }
table { width:100%; min-width:515px; border-collapse:collapse; text-align:left; }
th { padding:12px 14px; color:#657790; background:rgba(244,247,255,.38); font-size:10px; font-weight:680; }
th:first-child { width:38%; }
th:nth-child(2) { width:20%; }
th:nth-child(3) { width:20%; }
td { height:58px; padding:10px 14px; border-top:1px solid rgba(144,162,199,.16); color:#657591; font-size:11px; }
tbody tr { transition:background .18s; }
tbody tr:hover { background:rgba(255,255,255,.45); }
.data-table__name { display:flex; align-items:center; gap:10px; min-width:0; }
.data-table__name strong { overflow:hidden; color:#314160; font-size:11px; font-weight:700; text-overflow:ellipsis; white-space:nowrap; }
.data-table__file { display:grid; width:28px; height:28px; flex:none; place-items:center; border:1px solid rgba(124,153,215,.2); border-radius:8px; color:#748fe0; background:rgba(229,237,255,.72); }
.data-table__category { display:inline-block; padding:6px 9px; border-radius:7px; color:#63718a; background:rgba(237,241,250,.76); white-space:nowrap; }
time { color:#64758f; white-space:nowrap; }
.data-table__empty { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:7px; min-height:210px; color:#91a0b5; font-size:11px; }
.data-table__empty strong { color:#526580; font-size:13px; }
.data-table__footer { display:flex; justify-content:space-between; gap:12px; padding:13px 1px 2px; color:rgba(255,255,255,.78); font-size:10px; }
@media (max-width:640px) { .data-table__intro { flex-wrap:wrap; } .data-table__view { display:none; } }
</style>
