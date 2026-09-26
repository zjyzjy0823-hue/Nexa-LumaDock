<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { Activity, AlertCircle, CheckCircle2, Plus, Sparkles, X, Zap } from 'lucide-vue-next'
import ActionButton from '../components/ui/ActionButton.vue'
import GlassCard from '../components/ui/GlassCard.vue'
import AutomationCard from '../components/automation/AutomationCard.vue'
import ExecutionList from '../components/automation/ExecutionList.vue'
import TriggerLibrary from '../components/automation/TriggerLibrary.vue'
import WorkflowBuilder from '../components/automation/WorkflowBuilder.vue'
import {
  automationSummary, automations, executions, triggerLibrary, workflowExample,
  type AutomationItem, type WorkflowNode,
} from '../mock/automation'

const emit = defineEmits<{ action: [message: string] }>()
const automationItems = ref<AutomationItem[]>(automations.map(item => ({ ...item })))
const workflowNodes = ref<WorkflowNode[]>(workflowExample.map(node => ({ ...node })))
const selectedTriggerId = ref('device')
const expanded = ref(false)
const createOpen = ref(false)
const newName = ref('')
const newDescription = ref('')
const newTriggerId = ref('device')
const firstField = ref<HTMLInputElement | null>(null)

const runningCount = computed(() => automationItems.value.filter(item => item.enabled).length)
const visibleAutomations = computed(() => expanded.value ? automationItems.value : automationItems.value.slice(0, 4))
const stats = computed(() => [
  { label: '运行中自动化', value: `${runningCount.value} / ${automationItems.value.length}`, detail: '已启用的工作流', icon: Zap, tone: 'blue' },
  { label: '今日执行次数', value: String(automationSummary.todayExecutions), detail: '自动完成的任务', icon: Activity, tone: 'violet' },
  { label: '成功率', value: `${automationSummary.successRate}%`, detail: '近 30 天运行表现', icon: CheckCircle2, tone: 'mint' },
  { label: '错误次数', value: String(automationSummary.errorCount), detail: '需要关注的执行', icon: AlertCircle, tone: 'amber' },
])

function openCreate() {
  createOpen.value = true
  nextTick(() => firstField.value?.focus())
}
defineExpose({ openCreate })

function closeCreate() { createOpen.value = false }

function toggleAutomation(id: string) {
  const item = automationItems.value.find(entry => entry.id === id)
  if (!item) return
  item.enabled = !item.enabled
  emit('action', `「${item.title}」已${item.enabled ? '启动' : '暂停'}。`)
}

function selectTrigger(id: string) {
  const trigger = triggerLibrary.find(item => item.id === id)
  if (!trigger) return
  selectedTriggerId.value = id
  workflowNodes.value = workflowNodes.value.map(node => node.kind === 'WHEN'
    ? { ...node, text: trigger.example, detail: trigger.title }
    : node)
  emit('action', `已选择「${trigger.title}」作为触发器。`)
}

function updateWorkflow(nodes: WorkflowNode[]) {
  workflowNodes.value = nodes
  emit('action', '示例工作流已更新。')
}

function createAutomation() {
  const title = newName.value.trim()
  if (!title) return
  const trigger = triggerLibrary.find(item => item.id === newTriggerId.value) ?? triggerLibrary[0]!
  automationItems.value.unshift({
    id: `automation-${Date.now()}`,
    title,
    description: newDescription.value.trim() || '新的自动化工作流',
    icon: trigger.icon,
    enabled: true,
    trigger: trigger.example,
    lastExecution: '尚未执行',
    lastExecutionStatus: 'never',
  })
  expanded.value = true
  closeCreate()
  newName.value = ''
  newDescription.value = ''
  newTriggerId.value = 'device'
  emit('action', `「${title}」已创建并启动。`)
}

function onKeydown(event: KeyboardEvent) { if (event.key === 'Escape' && createOpen.value) closeCreate() }
onMounted(() => document.addEventListener('keydown', onKeydown))
onUnmounted(() => document.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="automation-page">
    <h1 class="automation-visually-hidden">自动化</h1>
    <div class="automation-page-actions" aria-label="自动化操作"><ActionButton size="sm" @click="openCreate"><Plus :size="16" />新建自动化</ActionButton></div>

    <section class="automation-stats" aria-label="自动化概览">
      <GlassCard v-for="stat in stats" :key="stat.label" class="automation-stat" :class="`automation-stat--${stat.tone}`">
        <div class="automation-stat__top"><span>{{ stat.label }}</span><span class="automation-stat__icon"><component :is="stat.icon" :size="18" :stroke-width="1.8" /></span></div>
        <strong>{{ stat.value }}</strong><small>{{ stat.detail }}</small>
      </GlassCard>
    </section>

    <div class="automation-main-grid">
      <section class="automation-flows" aria-labelledby="automation-flows-title">
        <div class="automation-section-heading"><div><span>ACTIVE WORKFLOWS</span><h2 id="automation-flows-title">我的自动化 <small>{{ automationItems.length }}</small></h2></div><button type="button" @click="expanded = !expanded">{{ expanded ? '收起列表' : '查看全部' }}<span aria-hidden="true">→</span></button></div>
        <div class="automation-card-grid"><AutomationCard v-for="item in visibleAutomations" :key="item.id" :automation="item" @toggle="toggleAutomation" /></div>
      </section>
      <WorkflowBuilder :nodes="workflowNodes" @update:nodes="updateWorkflow" />
    </div>

    <div class="automation-secondary-grid">
      <ExecutionList :executions="executions" />
      <TriggerLibrary :triggers="triggerLibrary" :selected-id="selectedTriggerId" @select="selectTrigger" />
    </div>

    <Teleport to="body">
      <div v-if="createOpen" class="automation-modal-backdrop" @click.self="closeCreate">
        <GlassCard class="automation-modal" role="dialog" aria-modal="true" aria-labelledby="automation-modal-title">
          <div class="automation-modal__heading"><div><span>NEW WORKFLOW</span><h2 id="automation-modal-title">新建自动化</h2><p>定义一个自动运行的任务。</p></div><button type="button" aria-label="关闭" @click="closeCreate"><X :size="17" /></button></div>
          <form class="automation-modal__form" @submit.prevent="createAutomation">
            <label>名称<input ref="firstField" v-model="newName" type="text" placeholder="例如：夜间同步" maxlength="40" required /></label>
            <label>描述<textarea v-model="newDescription" placeholder="这个自动化会做什么？" rows="3" maxlength="120" /></label>
            <label>触发器<select v-model="newTriggerId"><option v-for="trigger in triggerLibrary" :key="trigger.id" :value="trigger.id">{{ trigger.title }}</option></select></label>
            <div class="automation-modal__actions"><ActionButton variant="secondary" @click="closeCreate">取消</ActionButton><ActionButton type="submit"><Sparkles :size="15" />创建自动化</ActionButton></div>
          </form>
        </GlassCard>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.automation-page { min-width: 0; padding-bottom: 24px; }
.automation-visually-hidden { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0,0,0,0); white-space: nowrap; border: 0; }
.automation-page-actions { display: flex; justify-content: flex-end; align-items: center; min-height: 31px; margin-bottom: 14px; }
.automation-stats { display: grid; grid-template-columns: repeat(4,minmax(0,1fr)); gap: 14px; margin-bottom: 14px; }
.automation-stat { min-height: 127px; }
.automation-stat :deep(.glass-card__body) { display: flex; flex-direction: column; overflow: visible; }
.automation-stat__top { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.automation-stat__top > span:first-child { color: rgba(255,255,255,.86); font-size: 11px; font-weight: 670; text-shadow: 0 1px 8px rgba(25,38,76,.24); }
.automation-stat__icon { display: grid; width: 31px; height: 31px; flex: none; place-items: center; border: 1px solid rgba(255,255,255,.4); border-radius: 10px; color: white; background: rgba(113,143,235,.39); }
.automation-stat--violet .automation-stat__icon { background: rgba(160,117,216,.4); }
.automation-stat--mint .automation-stat__icon { background: rgba(64,183,146,.41); }
.automation-stat--amber .automation-stat__icon { background: rgba(218,157,76,.4); }
.automation-stat strong { margin-top: 2px; color: white; font-size: clamp(25px,2.3vw,32px); font-weight: 740; letter-spacing: -.05em; line-height: 1.16; text-shadow: 0 2px 10px rgba(29,44,100,.19); }
.automation-stat small { margin-top: 6px; color: rgba(255,255,255,.73); font-size: 10px; text-shadow: 0 1px 8px rgba(25,38,76,.2); }
.automation-main-grid { display: grid; grid-template-columns: minmax(0,1.55fr) minmax(300px,.93fr); align-items: stretch; gap: 15px; }
.automation-flows { min-width: 0; }
.automation-section-heading { display: flex; align-items: end; justify-content: space-between; gap: 12px; min-height: 46px; margin-bottom: 12px; }
.automation-section-heading > div > span { color: rgba(242,248,255,.67); font-size: 9px; font-weight: 750; letter-spacing: .16em; }
.automation-section-heading h2 { display: flex; align-items: center; gap: 8px; margin: 5px 0 0; color: #fff; font-size: 20px; font-weight: 650; letter-spacing: -.035em; text-shadow: 0 2px 14px rgba(35,53,103,.2); }
.automation-section-heading h2 small { display: grid; width: 21px; height: 21px; place-items: center; border: 1px solid rgba(255,255,255,.27); border-radius: 7px; background: rgba(255,255,255,.12); font-size: 10px; letter-spacing: 0; }
.automation-section-heading button { display: inline-flex; align-items: center; gap: 5px; padding: 4px 1px; border: 0; color: rgba(255,255,255,.86); background: none; font-size: 11px; font-weight: 640; white-space: nowrap; }
.automation-section-heading button:hover { color: #fff; }
.automation-section-heading button span { font-size: 16px; line-height: .6; }
.automation-card-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: 13px; }
.automation-secondary-grid { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); align-items: stretch; gap: 15px; margin-top: 16px; }
.automation-modal-backdrop { position: fixed; z-index: 120; inset: 0; display: grid; place-items: center; padding: 16px; background: rgba(24,39,83,.35); backdrop-filter: blur(9px); }
.automation-modal { width: min(100%,470px); height: auto; max-height: min(650px,calc(100dvh - 32px)); padding: 24px; }
.automation-modal :deep(.glass-card__body) { overflow-y: auto; }
.automation-modal__heading { display: flex; justify-content: space-between; gap: 14px; }
.automation-modal__heading span { color: rgba(255,255,255,.73); font-size: 10px; font-weight: 750; letter-spacing: .16em; }
.automation-modal__heading h2 { margin: 5px 0 4px; color: #fff; font-size: 23px; letter-spacing: -.04em; text-shadow: 0 1px 10px rgba(27,42,84,.3); }
.automation-modal__heading p { margin: 0; color: rgba(255,255,255,.75); font-size: 12px; }
.automation-modal__heading button { display: grid; width: 30px; height: 30px; place-items: center; border: 1px solid rgba(255,255,255,.3); border-radius: 9px; color: #fff; background: rgba(255,255,255,.16); }
.automation-modal__form { display: grid; gap: 15px; margin-top: 24px; }
.automation-modal__form label { display: flex; flex-direction: column; gap: 7px; color: rgba(255,255,255,.88); font-size: 11px; font-weight: 660; }
.automation-modal__form input,.automation-modal__form textarea,.automation-modal__form select { width: 100%; min-height: 39px; padding: 10px 11px; border: 1px solid rgba(131,151,197,.26); border-radius: 11px; outline: none; color: #354665; background: rgba(255,255,255,.83); font: inherit; font-size: 12px; }
.automation-modal__form input:focus,.automation-modal__form textarea:focus,.automation-modal__form select:focus { border-color: #839eec; box-shadow: 0 0 0 3px rgba(118,150,231,.13); }
.automation-modal__form textarea { resize: vertical; }
.automation-modal__form input::placeholder,.automation-modal__form textarea::placeholder { color: #b0bdcf; }
.automation-modal__actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 7px; }
@media (max-width: 1200px) { .automation-main-grid { grid-template-columns: minmax(0,1.3fr) minmax(290px,1fr); } .automation-card-grid { grid-template-columns: 1fr; } }
@media (max-width: 900px) { .automation-stats { grid-template-columns: repeat(2,minmax(0,1fr)); } .automation-main-grid { grid-template-columns: 1fr; } .automation-card-grid { grid-template-columns: repeat(2,minmax(0,1fr)); } .automation-secondary-grid { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .automation-stats { gap: 10px; } .automation-stat { min-height: 116px; padding: 14px; } .automation-card-grid { grid-template-columns: 1fr; } .automation-section-heading h2 { font-size: 18px; } }
</style>
