<script setup lang="ts">
import { ChevronRight, Database, Globe2, Monitor, Sparkles, Workflow } from 'lucide-vue-next'
import TopActionControls from './TopActionControls.vue'

const props = defineProps<{ currentPage: string }>()
const emit = defineEmits<{ navigate: [page: string]; create: [kind: string] }>()
const pageTitles: Record<string, string> = {
  Websites: '网站', Devices: '设备', Agents: '智能体',
  Data: '数据', Ledger: '账本', Automation: '自动化',
  API: 'API', Settings: '设置',
}
const createItems = [
  { kind: 'website', label: '添加网站', icon: Globe2 },
  { kind: 'device', label: '添加设备', icon: Monitor },
  { kind: 'agent', label: '创建智能体', icon: Sparkles },
  { kind: 'collection', label: '新建集合', icon: Database },
  { kind: 'automation', label: '新建自动化', icon: Workflow },
]
</script>

<template>
  <header class="workspace-topbar">
    <div class="workspace-topbar__location"><span class="workspace-topbar__dot" />个人空间 <ChevronRight :size="13" /> <strong>{{ pageTitles[props.currentPage] }}</strong></div>
    <TopActionControls :create-items="createItems" add-label="添加" @create="kind => emit('create', kind)" />
  </header>
</template>

<style scoped>
.workspace-topbar { position: relative; z-index: 70; display: flex; align-items: center; justify-content: space-between; gap: 18px; min-height: 68px; margin-bottom: 12px; color: white; }
.workspace-topbar__location { display: flex; align-items: center; gap: 9px; color: rgba(245,249,255,.67); font-size: 12px; font-weight: 580; white-space: nowrap; }
.workspace-topbar__location strong { color: #fff; font-weight: 690; }
.workspace-topbar__dot { width: 8px; height: 8px; border: 2px solid rgba(255,255,255,.85); border-radius: 50%; box-shadow: 0 0 0 4px rgba(255,255,255,.1); }
@media (max-width: 700px) { .workspace-topbar { min-height: 50px; } }
@media (max-width: 380px) { .workspace-topbar { gap: 10px; } .workspace-topbar__location { gap: 5px; font-size: 11px; } }
</style>
