<script setup lang="ts">
import { computed, toRef } from 'vue'
import { AlertTriangle, ChevronRight, RefreshCw } from 'lucide-vue-next'
import Modal from '../ui/Modal.vue'
import ActionButton from '../ui/ActionButton.vue'
import { useSyncConflicts } from '../../composables/useSyncConflicts'
import { conflictEntityLabel, conflictFields, conflictTime, conflictTitle, detectedTime } from '../../services/conflictPresentation'
import { useLedgerStore } from '../../stores/ledger'
import { useWebsitesStore } from '../../stores/websites'
import { useDataStore } from '../../stores/data'

const props = defineProps<{ open: boolean; refreshStatus: () => Promise<void> }>()
const emit = defineEmits<{ close: []; action: [message: string] }>()
const ledger = useLedgerStore()
const websites = useWebsitesStore()
const data = useDataStore()
const { conflicts, selected, references, listLoading, detailLoading, resolving, error, busy, refresh, select, resolve } =
  useSyncConflicts(toRef(props, 'open'), message => emit('action', message), async () => {
    // Reload business views on their next visit after authoritative Local changes.
    ledger.invalidate()
    data.invalidate()
    websites.invalidate()
    await props.refreshStatus()
  })
const rows = computed(() => selected.value ? conflictFields(selected.value, references.value) : [])
</script>

<template>
  <Modal :open="open" wide title="同步冲突" description="本机数据已保留。查看两边的版本，再明确选择如何处理。" @close="!resolving && emit('close')">
    <div class="conflict-center" :aria-busy="busy">
      <div class="conflict-toolbar">
        <span>{{ conflicts.length }} 个待处理冲突</span>
        <ActionButton variant="ghost" size="sm" :disabled="busy" @click="refresh()"><RefreshCw :size="14" />刷新冲突</ActionButton>
      </div>
      <p v-if="error" class="conflict-error" role="alert">{{ error }}</p>
      <p v-if="listLoading && !conflicts.length" class="conflict-empty" role="status">正在加载同步冲突…</p>
      <p v-else-if="!conflicts.length && !error" class="conflict-empty" role="status">没有待处理的同步冲突。</p>
      <div v-if="conflicts.length" class="conflict-layout">
        <nav class="conflict-list" aria-label="待处理同步冲突">
          <button v-for="conflict in conflicts" :key="conflict.id" type="button" class="conflict-item"
            :class="{ 'conflict-item--selected': selected?.id === conflict.id }" :aria-current="selected?.id === conflict.id ? 'true' : undefined"
            :disabled="listLoading || resolving" @click="select(conflict.id)">
            <div><small>{{ conflictEntityLabel(conflict.entityType) }}</small><strong>{{ conflictTitle(conflict) }}</strong><span>{{ detectedTime(conflict.detectedAt) }}</span></div>
            <ChevronRight :size="15" aria-hidden="true" />
          </button>
        </nav>
        <section class="conflict-detail" aria-label="冲突版本详情">
          <p v-if="detailLoading" class="conflict-empty" role="status">正在加载版本详情…</p>
          <template v-else-if="selected">
            <header class="conflict-heading"><small>{{ conflictEntityLabel(selected.entityType) }}</small><h3>{{ conflictTitle(selected) }}</h3><p>检测于 {{ conflictTime(selected.detectedAt) }}</p></header>
            <p class="conflict-explanation">高亮字段表示版本不同。时间仅供参考，系统不会自动选择较新的版本。</p>
            <p v-if="selected.hasPendingTail" class="conflict-tail"><AlertTriangle :size="15" aria-hidden="true" />本机在检测到冲突后仍有编辑。保留本机会提交最新数据；使用 Core 会一并放弃这些后续编辑。</p>
            <div class="conflict-comparison" role="table" aria-label="本机与 Core 版本比较">
              <div class="conflict-version-headings" role="row">
                <span role="columnheader">字段</span>
                <div role="columnheader"><strong>本机版本</strong><small>{{ selected.localDeleted ? '已删除' : '当前本机数据' }}</small></div>
                <div role="columnheader"><strong>Core 版本</strong><small>{{ selected.remoteDeleted ? '已删除' : selected.remote ? '已保存的 Core 版本' : 'Core 中不存在' }}</small></div>
              </div>
              <div v-if="selected.localDeleted || selected.remoteDeleted || !selected.remote" class="conflict-field conflict-field--different" role="row">
                <span role="rowheader">数据状态</span><span role="cell">{{ selected.localDeleted ? '已删除' : '存在' }}</span><span role="cell">{{ selected.remoteDeleted ? '已删除' : selected.remote ? '存在' : 'Core 中不存在' }}</span>
              </div>
              <div v-for="row in rows" :key="row.key" class="conflict-field" :class="{ 'conflict-field--different': row.different }" role="row">
                <span role="rowheader">{{ row.label }}<small v-if="row.different">不同</small></span>
                <div role="cell"><details v-if="row.json && !selected.localDeleted"><summary>查看记录内容</summary><pre>{{ row.local }}</pre></details><span v-else>{{ row.local }}</span></div>
                <div role="cell"><details v-if="row.json && !selected.remoteDeleted && selected.remote"><summary>查看记录内容</summary><pre>{{ row.remote }}</pre></details><span v-else>{{ row.remote }}</span></div>
              </div>
            </div>
            <p class="conflict-explanation">保留本机后，后台会将其作为新的修改同步。若 Core 再次更改，冲突会重新出现。</p>
            <div class="conflict-actions">
              <ActionButton :disabled="busy" @click="resolve('local')">{{ resolving ? '正在处理…' : '保留本机版本' }}</ActionButton>
              <ActionButton variant="danger" :disabled="busy" @click="resolve('remote')">使用 Core 版本</ActionButton>
            </div>
          </template>
        </section>
      </div>
    </div>
  </Modal>
</template>

<style scoped>
.conflict-toolbar { display:flex; align-items:center; justify-content:space-between; gap:10px; padding-bottom:15px; color:var(--text-secondary); font-size:12px; }
.conflict-layout { display:grid; grid-template-columns:210px minmax(0,1fr); gap:22px; }
.conflict-list { display:flex; flex-direction:column; gap:8px; }
.conflict-item { display:flex; align-items:center; gap:8px; width:100%; padding:12px; border:1px solid var(--line); border-radius:12px; color:var(--text-primary); background:var(--glass-tile-background); text-align:left; }
.conflict-item > div { min-width:0; flex:1; }
.conflict-item strong,.conflict-item small,.conflict-item span { display:block; overflow-wrap:anywhere; }
.conflict-item strong { margin:5px 0; font-size:13px; }
.conflict-item small,.conflict-item span { color:var(--text-secondary); font-size:10px; line-height:1.5; }
.conflict-item--selected { border-color:var(--accent-deep); background:rgba(115,135,230,.1); }
.conflict-item:disabled { opacity:.65; }
.conflict-detail { min-width:0; }
.conflict-heading small,.conflict-heading p { color:var(--text-secondary); font-size:11px; }
.conflict-heading h3 { margin:5px 0; font-size:20px; overflow-wrap:anywhere; }
.conflict-heading p { margin:7px 0 13px; }
.conflict-explanation,.conflict-tail { color:var(--text-secondary); font-size:11px; line-height:1.7; }
.conflict-tail { display:flex; align-items:flex-start; gap:8px; padding:12px; border:1px solid rgba(177,78,101,.2); border-radius:10px; color:#a54b61; background:rgba(177,78,101,.04); }
.conflict-tail svg { flex-shrink:0; margin-top:2px; }
.conflict-comparison { margin:16px 0; border:1px solid var(--line); border-radius:12px; overflow:hidden; }
.conflict-version-headings,.conflict-field { display:grid; grid-template-columns:78px minmax(0,1fr) minmax(0,1fr); gap:12px; padding:12px; }
.conflict-version-headings { background:var(--glass-tile-background); align-items:center; font-size:12px; }
.conflict-version-headings > span { color:var(--text-secondary); font-size:10px; }
.conflict-version-headings small { display:block; margin-top:6px; color:var(--text-secondary); font-size:10px; font-weight:400; }
.conflict-field { border-top:1px solid var(--line); font-size:12px; line-height:1.65; overflow-wrap:anywhere; }
.conflict-field > span:first-child { color:var(--text-secondary); font-size:11px; }
.conflict-field--different { background:rgba(116,134,231,.08); }
.conflict-field small { display:block; color:var(--accent-deep); font-size:9px; }
.conflict-field summary { color:var(--accent-deep); cursor:pointer; }
.conflict-field pre { margin:8px 0 0; max-height:220px; overflow:auto; font-size:10px; line-height:1.6; white-space:pre-wrap; overflow-wrap:anywhere; }
.conflict-actions { display:flex; justify-content:flex-end; flex-wrap:wrap; gap:10px; margin-top:18px; }
.conflict-error { color:#b14e65; font-size:12px; line-height:1.65; }
.conflict-empty { padding:22px 0; color:var(--text-secondary); font-size:13px; text-align:center; }
@media (max-width:760px) { .conflict-layout { grid-template-columns:minmax(0,1fr); gap:18px; } .conflict-list { flex-direction:row; overflow-x:auto; padding-bottom:5px; } .conflict-item { min-width:170px; width:170px; flex-shrink:0; } }
@media (max-width:480px) { .conflict-version-headings,.conflict-field { grid-template-columns:52px minmax(0,1fr) minmax(0,1fr); gap:8px; padding:9px; } .conflict-actions { justify-content:stretch; } .conflict-actions button { flex:1; } }
</style>
