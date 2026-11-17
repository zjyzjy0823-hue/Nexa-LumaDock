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
import { useSettingsStore } from '../../stores/settings'
import { useAutomationStore } from '../../stores/automation'
import { useAuthStore } from '../../stores/auth'

const props = defineProps<{ open: boolean; refreshStatus: () => Promise<void> }>()
const emit = defineEmits<{ close: []; action: [message: string] }>()
const ledger = useLedgerStore()
const websites = useWebsitesStore()
const data = useDataStore()
const settings = useSettingsStore()
const automation = useAutomationStore()
const auth = useAuthStore()
const { conflicts, selected, references, listLoading, detailLoading, resolving, error, busy, refresh, select, resolve } =
  useSyncConflicts(toRef(props, 'open'), message => emit('action', message), async () => {
    ledger.invalidate()
    data.invalidate()
    websites.invalidate()
    if (auth.token && !settings.loading) await settings.load(auth.token, true).catch(() => {})
    automation.invalidate()
    await props.refreshStatus()
  })
const rows = computed(() => selected.value ? conflictFields(selected.value, references.value) : [])
</script>

<template>
  <Modal :open="open" wide title="同步冲突" description="本机数据已保留。查看两边的版本，再明确选择如何处理。" @close="!resolving && emit('close')">
    <div class="conflict-center" :aria-busy="busy">
      <div class="conflict-toolbar">
        <span class="muted">{{ conflicts.length }} 个待处理冲突</span>
        <ActionButton variant="secondary" size="sm" :disabled="busy" @click="refresh()"><RefreshCw :size="14" />刷新冲突</ActionButton>
      </div>
      <div v-if="error" class="notice danger" role="alert">{{ error }}</div>
      <div v-if="listLoading && !conflicts.length" class="cleared" role="status">正在加载同步冲突…</div>
      <div v-else-if="!conflicts.length && !error" class="cleared" role="status">没有待处理的同步冲突。</div>
      <div v-if="conflicts.length" class="conflict-layout">
        <nav class="list conflict-list" aria-label="待处理同步冲突">
          <button v-for="conflict in conflicts" :key="conflict.id" type="button" class="row"
            :class="{ 'is-selected': selected?.id === conflict.id }" :aria-current="selected?.id === conflict.id ? 'true' : undefined"
            :disabled="listLoading || resolving" @click="select(conflict.id)">
            <span class="grow">
              <div class="sub">{{ conflictEntityLabel(conflict.entityType) }} · {{ detectedTime(conflict.detectedAt) }}</div>
              <div class="title">{{ conflictTitle(conflict) }}</div>
            </span>
            <ChevronRight :size="15" aria-hidden="true" />
          </button>
        </nav>
        <section class="conflict-detail" aria-label="冲突版本详情">
          <div v-if="detailLoading" class="cleared" role="status">正在加载版本详情…</div>
          <template v-else-if="selected">
            <header class="conflict-heading">
              <div class="faint" style="font-size:12px">{{ conflictEntityLabel(selected.entityType) }} · 检测于 {{ conflictTime(selected.detectedAt) }}</div>
              <h3>{{ conflictTitle(selected) }}</h3>
            </header>
            <p class="muted" style="margin:6px 0 12px;font-size:12.5px">高亮字段表示版本不同。时间仅供参考，系统不会自动选择较新的版本。</p>
            <div v-if="selected.hasPendingTail" class="notice warn" style="margin-bottom:12px"><AlertTriangle :size="15" aria-hidden="true" /><div>本机在检测到冲突后仍有编辑。保留本机会提交最新数据；使用 Core 会一并放弃这些后续编辑。</div></div>
            <div class="conflict-comparison" role="table" aria-label="本机与 Core 版本比较">
              <div class="conflict-version-headings" role="row">
                <span role="columnheader">字段</span>
                <div role="columnheader"><b>本机版本</b><div class="faint" style="font-size:11.5px">{{ selected.localDeleted ? '已删除' : '当前本机数据' }}</div></div>
                <div role="columnheader"><b>Core 版本</b><div class="faint" style="font-size:11.5px">{{ selected.remoteDeleted ? '已删除' : selected.remote ? '已保存的 Core 版本' : 'Core 中不存在' }}</div></div>
              </div>
              <div v-if="selected.localDeleted || selected.remoteDeleted || !selected.remote" class="conflict-field conflict-field--different" role="row">
                <span role="rowheader">数据状态</span><span role="cell">{{ selected.localDeleted ? '已删除' : '存在' }}</span><span role="cell">{{ selected.remoteDeleted ? '已删除' : selected.remote ? '存在' : 'Core 中不存在' }}</span>
              </div>
              <div v-for="row in rows" :key="row.key" class="conflict-field" :class="{ 'conflict-field--different': row.different }" role="row">
                <span role="rowheader">{{ row.label }}<span v-if="row.different" class="chip" style="margin-left:6px;height:18px;font-size:10.5px">不同</span></span>
                <div role="cell"><details v-if="row.json && !selected.localDeleted"><summary>查看详细配置</summary><pre class="mono">{{ row.local }}</pre></details><span v-else>{{ row.local }}</span></div>
                <div role="cell"><details v-if="row.json && !selected.remoteDeleted && selected.remote"><summary>查看详细配置</summary><pre class="mono">{{ row.remote }}</pre></details><span v-else>{{ row.remote }}</span></div>
              </div>
            </div>
            <p class="faint" style="font-size:12px;margin:0 0 12px">保留本机后，后台会将其作为新的修改同步。若 Core 再次更改，冲突会重新出现。</p>
            <div class="dlg-actions">
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
.conflict-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding-bottom: 12px; font-size: 13px; }
.conflict-layout { display: grid; grid-template-columns: 210px minmax(0, 1fr); gap: 16px; }
.conflict-list { align-content: start; }
.conflict-detail { min-width: 0; }
.conflict-heading h3 { margin: 4px 0 0; font-size: 17px; overflow-wrap: anywhere; }
.conflict-comparison { margin: 12px 0; border-radius: var(--r-md); background: var(--solid); box-shadow: var(--shadow-1); overflow: hidden; }
.conflict-version-headings, .conflict-field { display: grid; grid-template-columns: 92px minmax(0, 1fr) minmax(0, 1fr); gap: 12px; padding: 10px 12px; }
.conflict-version-headings { background: var(--surface-3); align-items: center; font-size: 12.5px; }
.conflict-field { border-top: 1px solid var(--line); font-size: 12.5px; line-height: 1.55; overflow-wrap: anywhere; }
.conflict-field > span:first-child { color: var(--text-3); }
.conflict-field--different { background: var(--accent-soft); }
.conflict-field summary { color: var(--accent); cursor: pointer; }
.conflict-field pre { margin: 6px 0 0; max-height: 200px; overflow: auto; font-size: 11.5px; white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 720px) { .conflict-layout { grid-template-columns: 1fr; } }
</style>
