<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { BookOpen, ChevronRight, Database, Globe2, Monitor, PanelLeft, Search, Settings, Sparkles, Workflow } from 'lucide-vue-next'
import TopActionControls from './TopActionControls.vue'
import Modal from '../ui/Modal.vue'
import { desktopPlatform } from '../../desktop/platform'

const props = defineProps<{ currentPage: string; collapsed: boolean }>()
const emit = defineEmits<{ create: [kind: string]; navigate: [page: string]; toggleSidebar: [] }>()
const pageTitles: Record<string, string> = {
  Home: '今天', Dashboard: '自定义仪表盘',
  Websites: '网站', Devices: '设备', Agents: '智能体',
  Data: '数据', Ledger: '账本', Automation: '自动化',
  API: 'API', Settings: '设置',
}
const createItems = [
  { kind: 'ledger', label: '记一笔', icon: BookOpen },
  { kind: 'website', label: '添加网站', icon: Globe2 },
  { kind: 'device', label: '添加设备', icon: Monitor },
  { kind: 'agent', label: '创建智能体', icon: Sparkles },
  { kind: 'collection', label: '新建集合', icon: Database },
  { kind: 'automation', label: '新建自动化', icon: Workflow },
]
const query = ref('')
const open = ref(false)
const results = computed(() => {
  const search = query.value.trim().toLowerCase()
  return [...Object.entries(pageTitles).map(([id, label]) => ({ id, label, kind: 'page' as const })),
    ...createItems.map(item => ({ id: item.kind, label: item.label, kind: 'create' as const })),
  ].filter(item => !search || item.label.toLowerCase().includes(search) || item.id.toLowerCase().includes(search))
})
function showCommands() { query.value = ''; open.value = true }
function choose(item: (typeof results.value)[number]) {
  open.value = false
  if (item.kind === 'page') emit('navigate', item.id)
  else emit('create', item.id)
}
function shortcut(event: KeyboardEvent) {
  if (event.defaultPrevented || event.isComposing || event.altKey || !(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'k') return
  if (document.querySelector('[aria-modal="true"]')) return
  event.preventDefault()
  showCommands()
}
onMounted(() => document.addEventListener('keydown', shortcut))
onUnmounted(() => document.removeEventListener('keydown', shortcut))
</script>

<template>
  <header class="workspace-topbar workbench-material">
    <div class="workspace-topbar__location">
      <button class="workbench-icon workspace-topbar__sidebar" type="button" aria-label="侧栏" :aria-expanded="!collapsed" @click="emit('toggleSidebar')"><PanelLeft :size="17" /></button>
      <span class="workspace-topbar__space">个人空间</span><ChevronRight class="workspace-topbar__space" :size="13" />
      <strong>{{ pageTitles[props.currentPage] }}</strong>
    </div>
    <button class="command-trigger" type="button" aria-label="命令面板" aria-haspopup="dialog" @click="showCommands">
      <Search :size="16" /><span>搜索页面或操作</span><kbd>{{ desktopPlatform() === 'macos' ? '⌘' : 'Ctrl' }} K</kbd>
    </button>
    <button class="workbench-icon workspace-topbar__settings" type="button" aria-label="设置" @click="emit('navigate', 'Settings')"><Settings :size="20" /></button>
    <TopActionControls :create-items="createItems" add-label="添加" @create="kind => emit('create', kind)" />
  </header>
  <Modal :open="open" title="快速跳转" @close="open = false">
    <label class="command-search"><Search :size="17" /><input v-model="query" aria-label="搜索页面或操作" placeholder="搜索页面或操作…" data-initial-focus @keydown.enter.prevent="results[0] && choose(results[0])" /></label>
    <div class="command-list">
      <button v-for="item in results" :key="item.kind + item.id" type="button" @click="choose(item)">
        {{ item.label }}<small>{{ item.kind === 'page' ? '页面' : '操作' }}</small>
      </button>
      <p v-if="!results.length" role="status">没有匹配的页面或操作。</p>
    </div>
  </Modal>
</template>

<style scoped>
.workspace-topbar { position:relative; z-index:70; display:flex; align-items:center; justify-content:space-between; gap:18px; min-height:53px; padding:0 clamp(16px,3vw,38px); border-width:0 0 1px; box-shadow:none; color:var(--workbench-text); }
.workspace-topbar__location { display:flex; align-items:center; gap:9px; color:var(--workbench-muted); font-size:13px; white-space:nowrap; }
.workspace-topbar__location strong { color:var(--workbench-text); font-weight:650; }
.workspace-topbar__settings { display:none; }
.command-trigger, .command-search { display:flex; align-items:center; gap:8px; min-height:35px; padding:0 11px; color:var(--workbench-muted); background:var(--workbench-solid); border:1px solid var(--workbench-line); border-radius:9px; font-size:12px; }
.command-trigger { width:min(100%,310px); text-align:left; }
.command-trigger kbd { margin-left:auto; padding:2px 5px; border:1px solid var(--workbench-line); border-radius:5px; white-space:nowrap; }
.command-search input { flex:1; min-width:0; padding:8px 0; border:0; outline:none; background:none; color:var(--workbench-text); }
.command-search:focus-within { border-color:var(--workbench-accent); }
.command-list { display:grid; max-height:min(43dvh,330px); margin-top:10px; overflow:auto; }
.command-list button { display:flex; align-items:center; justify-content:space-between; min-height:38px; padding:0 9px; border:0; border-radius:8px; background:none; color:var(--workbench-text); text-align:left; }
.command-list button:hover { background:var(--workbench-soft); }
.command-list :is(small,p) { color:var(--workbench-muted); }
.workspace-topbar :deep(.topbar__icon-button), .workspace-topbar :deep(.topbar__new) { width:35px; height:35px; border-radius:9px; color:var(--workbench-text); }
.workspace-topbar :deep(.topbar__new) { background:var(--workbench-solid); border-color:var(--workbench-line); backdrop-filter:none; }
.workspace-topbar :deep(.top-action-controls svg) { width:19px; height:19px; }
@media (max-width:700px) {
  .workspace-topbar { min-height:50px; gap:8px; }
  .workspace-topbar__settings { display:grid; }
  .workspace-topbar__location { margin-right:auto; }
  .workspace-topbar :is(.workspace-topbar__sidebar,.workspace-topbar__space,.command-trigger > span,.command-trigger > kbd) { display:none; }
  .workspace-topbar :deep(.top-action-controls) { display:none; }
  .command-trigger { width:35px; justify-content:center; padding:0; }
}
@media (max-width: 380px) { .workspace-topbar { gap: 10px; } .workspace-topbar__location { gap: 5px; font-size: 11px; } }
</style>
