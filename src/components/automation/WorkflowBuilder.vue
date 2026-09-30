<script setup lang="ts">
import { ref, watch } from 'vue'
import { ArrowDown, Check, GitBranch, Pencil, X } from 'lucide-vue-next'
import GlassCard from '../ui/GlassCard.vue'
import { workflowOptions, type WorkflowNode } from '../../mock/automation'

const props = defineProps<{ nodes: WorkflowNode[] }>()
const emit = defineEmits<{ 'update:nodes': [nodes: WorkflowNode[]] }>()
const editing = ref(false)
const draft = ref<WorkflowNode[]>(props.nodes.map(node => ({ ...node })))
watch(() => props.nodes, nodes => { if (!editing.value) draft.value = nodes.map(node => ({ ...node })) }, { deep: true })

function edit() { draft.value = props.nodes.map(node => ({ ...node })); editing.value = true }
function cancel() { draft.value = props.nodes.map(node => ({ ...node })); editing.value = false }
function save() { emit('update:nodes', draft.value.map(node => ({ ...node }))); editing.value = false }
</script>

<template>
  <GlassCard class="workflow-builder">
    <div class="workflow-builder__heading">
      <div><span class="workflow-builder__eyebrow">WORKFLOW BUILDER</span><h2>工作流构建器</h2><p>连接事件、条件与动作</p></div>
      <button v-if="!editing" class="workflow-builder__edit" type="button" @click="edit"><Pencil :size="13" />编辑</button>
      <div v-else class="workflow-builder__edit-actions">
        <button type="button" aria-label="取消编辑" @click="cancel"><X :size="14" /></button>
        <button type="button" aria-label="保存工作流" @click="save"><Check :size="14" /></button>
      </div>
    </div>
    <div class="workflow-builder__canvas">
      <template v-for="(node, index) in draft" :key="node.kind">
        <GlassCard class="workflow-node" :class="`workflow-node--${node.kind.toLowerCase()}`">
          <span class="workflow-node__step">{{ node.kind }}</span>
          <div class="workflow-node__copy"><small>{{ node.label }}</small><strong v-if="!editing">{{ node.text }}</strong><select v-else v-model="node.text" :aria-label="node.label"><option v-for="option in workflowOptions[node.kind]" :key="option" :value="option">{{ option }}</option></select></div>
          <GitBranch v-if="node.kind === 'IF'" :size="17" :stroke-width="1.7" aria-hidden="true" />
          <span v-else class="workflow-node__dot" aria-hidden="true" />
        </GlassCard>
        <span v-if="index < draft.length - 1" class="workflow-builder__connector" aria-hidden="true"><i /><ArrowDown :size="14" /></span>
      </template>
    </div>
    <p class="workflow-builder__hint">当前流程配置 · {{ draft[0]?.text }} → {{ draft[1]?.text }} → {{ draft[2]?.text }}</p>
  </GlassCard>
</template>

<style scoped>
.workflow-builder { min-height: 430px; }
.workflow-builder :deep(> .glass-card__body) { overflow: visible; }
.workflow-builder__heading { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.workflow-builder__eyebrow { color: rgba(255,255,255,.7); font-size: 9px; font-weight: 760; letter-spacing: .14em; }
.workflow-builder__heading h2 { margin: 5px 0 0; color: #fff; font-size: 16px; letter-spacing: -.03em; text-shadow: 0 1px 8px rgba(27,42,84,.3); }
.workflow-builder__heading p { margin: 4px 0 0; color: rgba(255,255,255,.76); font-size: 10px; }
.workflow-builder__edit,.workflow-builder__edit-actions button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; min-height: 27px; padding: 0 8px; border: 1px solid rgba(255,255,255,.33); border-radius: 9px; color: #fff; background: rgba(255,255,255,.16); font-size: 10px; font-weight: 650; }
.workflow-builder__edit-actions { display: flex; gap: 4px; }
.workflow-builder__edit-actions button:last-child { background: rgba(106,136,235,.68); }
.workflow-builder__canvas { display: flex; align-items: center; flex-direction: column; margin: 18px 0 11px; }
.workflow-node { width: min(100%, 350px); min-height: 75px; padding: 12px 13px; border: var(--glass-tile-border); background: var(--glass-tile-background); box-shadow: var(--glass-tile-shadow); }
.workflow-node :deep(.glass-card__body) { display: flex; align-items: center; gap: 12px; overflow: visible; }
.workflow-node__step { display: grid; width: 45px; height: 40px; flex: none; place-items: center; border-radius: 11px; color: #6187df; background: rgba(226,236,255,.83); font-size: 10px; font-weight: 800; letter-spacing: .02em; }
.workflow-node--if .workflow-node__step { color: #956fcd; background: rgba(240,232,255,.84); }
.workflow-node--do .workflow-node__step { color: #32a686; background: rgba(224,247,238,.85); }
.workflow-node__copy { display: flex; flex: 1; flex-direction: column; gap: 4px; min-width: 0; }
.workflow-node__copy small { color: #71809a; font-size: 9px; }
.workflow-node__copy strong { overflow: hidden; color: #364967; font-size: 12px; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.workflow-node__copy select { width: 100%; height: 26px; border: 1px solid rgba(145,169,216,.4); border-radius: 7px; outline: none; color: #364967; background: rgba(255,255,255,.65); font-size: 11px; }
.workflow-node svg { color: #93a6c6; }
.workflow-node__dot { width: 8px; height: 8px; flex: none; margin-right: 4px; border-radius: 50%; background: #9db9ed; }
.workflow-node--do .workflow-node__dot { background: #7fd0b2; }
.workflow-builder__connector { display: flex; align-items: center; flex-direction: column; height: 24px; color: rgba(255,255,255,.7); }
.workflow-builder__connector i { width: 1px; height: 10px; background: rgba(255,255,255,.53); }
.workflow-builder__hint { margin: 4px 0 0; color: rgba(255,255,255,.8); font-size: 10px; text-align: center; line-height: 1.45; text-shadow: 0 1px 5px rgba(27,42,84,.27); }
</style>
