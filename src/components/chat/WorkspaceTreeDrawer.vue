<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useFleetStore } from '../../stores/fleet'
import type { WorkspaceTreeEntry } from '../../types/fleet'
import OpusIcon from '../ui/OpusIcon.vue'

const props = defineProps<{
  sessionKey: string
}>()

const emit = defineEmits<{
  close: []
  openFile: [path: string]
  citeFile: [path: string]
  openExternal: [path: string, target: 'editor' | 'folder']
}>()

const fleet = useFleetStore()
const expandedDirs = reactive<Record<string, boolean>>({})

const session = computed(() => fleet.sessionsByKey[props.sessionKey] ?? null)

function getEntries(relDir: string): WorkspaceTreeEntry[] {
  const s = session.value
  if (!s) return []
  return (
    fleet.treeCacheByTarget[`${s.nodeId}::${s.provider}::${s.sessionId}::${relDir}`] ??
    fleet.treeCacheByTarget[`${s.nodeId}::${s.provider}::${relDir}`] ??
    []
  )
}

interface FlatTreeRow {
  entry: WorkspaceTreeEntry
  depth: number
}

const flatRows = computed<FlatTreeRow[]>(() => {
  const rows: FlatTreeRow[] = []
  const walk = (relDir: string, depth: number) => {
    for (const entry of getEntries(relDir)) {
      rows.push({ entry, depth })
      if (entry.isDir && expandedDirs[entry.path]) {
        walk(entry.path, depth + 1)
      }
    }
  }
  walk('', 0)
  return rows
})

watch(
  () => props.sessionKey,
  (k) => {
    if (k) fleet.requestWorkspaceTree('', k)
  },
  { immediate: true },
)

function toggleEntry(entry: WorkspaceTreeEntry) {
  if (entry.isDir) {
    const next = !expandedDirs[entry.path]
    expandedDirs[entry.path] = next
    if (next && !getEntries(entry.path).length) {
      fleet.requestWorkspaceTree(entry.path, props.sessionKey)
    }
  } else {
    emit('openFile', entry.path)
  }
}

function formatSize(bytes: number): string {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes}B`
  return `${(bytes / 1024).toFixed(1)}K`
}
</script>

<template>
  <section class="wt-drawer" aria-label="工作区目录文件树">
    <header class="wt-hdr">
      <div class="wt-hdr-title">
        <OpusIcon name="layers" class="wt-hdr-ic" />
        <span>工作区目录</span>
      </div>
      <div class="wt-actions">
        <button
          type="button"
          class="icon-btn"
          aria-label="在外部编辑器打开工作区"
          title="在宿主机编辑器中打开此工作区"
          @click="emit('openExternal', '', 'editor')"
        >
          <OpusIcon name="external" />
        </button>
        <button
          type="button"
          class="icon-btn"
          aria-label="刷新目录树"
          title="刷新工作区根目录"
          @click="fleet.requestWorkspaceTree('', sessionKey)"
        >
          <OpusIcon name="sync" />
        </button>
        <button
          type="button"
          class="icon-btn"
          aria-label="关闭目录树"
          title="关闭工作区目录"
          @click="emit('close')"
        >
          <OpusIcon name="x" />
        </button>
      </div>
    </header>

    <div class="wt-body" role="tree" aria-label="项目文件树">
      <div v-if="!flatRows.length" class="wt-empty faint">
        <p>正在扫描工作目录或目录为空。</p>
        <button type="button" class="btn btn-subtle btn-sm" @click="fleet.requestWorkspaceTree('', sessionKey)">重新加载</button>
      </div>
      <div
        v-for="row in flatRows"
        :key="row.entry.path"
        class="wt-row"
        :style="{ paddingLeft: `${10 + row.depth * 14}px` }"
        role="treeitem"
        :aria-expanded="row.entry.isDir ? Boolean(expandedDirs[row.entry.path]) : undefined"
      >
        <button
          type="button"
          class="wt-row-btn"
          :title="row.entry.path"
          @click="toggleEntry(row.entry)"
        >
          <OpusIcon
            v-if="row.entry.isDir"
            :name="expandedDirs[row.entry.path] ? 'chevD' : 'chevR'"
            class="wt-chev"
          />
          <span v-else class="wt-chev-spacer" />
          <OpusIcon :name="row.entry.isDir ? 'grid' : 'file'" class="wt-ic" />
          <span class="wt-name">{{ row.entry.name }}</span>
          <span v-if="!row.entry.isDir" class="wt-size num">{{ formatSize(row.entry.sizeBytes) }}</span>
        </button>
        <button
          type="button"
          class="wt-cite-btn"
          :title="`引用 @${row.entry.path} 到输入框`"
          @click.stop="emit('citeFile', row.entry.path)"
        >
          @
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.wt-drawer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--surface-1);
}
.wt-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 10px 7px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  flex: none;
}
.wt-hdr-title { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; }
.wt-hdr-ic { width: 14px; height: 14px; color: var(--accent); }
.wt-actions { display: flex; align-items: center; gap: 4px; }
.wt-body { flex: 1; min-height: 0; overflow: auto; padding: 6px 4px; }
.wt-empty { padding: 24px 12px; text-align: center; font-size: 12px; display: grid; gap: 8px; justify-items: center; }
.wt-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding-right: 6px;
  border-radius: var(--r-xs);
}
.wt-row:hover { background: var(--surface-2); }
.wt-row-btn {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 2px;
  border: 0;
  background: transparent;
  color: var(--text);
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}
.wt-chev { width: 11px; height: 11px; color: var(--text-3); flex: none; }
.wt-chev-spacer { width: 11px; flex: none; }
.wt-ic { width: 13px; height: 13px; color: var(--text-3); flex: none; }
.wt-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wt-size { font-size: 10.5px; color: var(--text-3); flex: none; }
.wt-cite-btn {
  opacity: 0;
  padding: 1px 5px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--surface-1);
  color: var(--accent);
  font-size: 10.5px;
  cursor: pointer;
}
.wt-row:hover .wt-cite-btn, .wt-cite-btn:focus-visible { opacity: 1; }
</style>
