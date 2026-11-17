<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import OpusSegment from '../components/ui/OpusSegment.vue'
import OpusIcon from '../components/ui/OpusIcon.vue'
import Modal from '../components/ui/Modal.vue'
import { useAutomationStore } from '../stores/automation'
import { useAuthStore } from '../stores/auth'
import { confirmAction } from '../composables/useConfirm'
import { automationService } from '../services/automation'
import type { AutomationAction, Execution, Workflow, WorkflowInput } from '../types/automation'

const props = defineProps<{ mobile?: boolean }>()
const emit = defineEmits<{ action: [message: string] }>()
const store = useAutomationStore(), auth = useAuthStore()
const open = ref(false), editingId = ref(''), selectedId = ref(''), firstField = ref<HTMLInputElement | null>(null), formError = ref('')
const detail = ref<Execution | null>(null)
const triggers = { manual: '手动', schedule: '定时', data_changed: '数据变更', agent_completed: 'Agent 任务完成' }
const actions = { 'ledger.create': '创建账本交易', 'data.create': '创建数据记录', 'data.update': '更新数据记录', 'agent.run': '运行 Agent 任务', 'webhook.post': 'HTTP Webhook' }
const statuses: Record<string, string> = { queued: '排队中', claimed: '已领取', running: '执行中', succeeded: '成功', success: '模拟成功', failed: '失败', skipped: '已跳过', cancelled: '已取消' }
function defaults() { return { name: '', description: '', enabled: true, trigger: 'manual' as Workflow['triggerType'], action: 'data.create' as AutomationAction['type'], scheduleType: 'daily', timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai', time: '22:00', at: new Date().toISOString(), seconds: 3600, weekdays: [0], catchUp: 'catch_up_once', entityType: 'data.record', operation: '', agentFilter: '', target: '', title: '', amount: '1.00', ledgerType: 'expense', occurredAt: new Date().toISOString(), recordStatus: 'active', category: '', payload: '{}', url: '', headers: '{}', timeout: 10, extra: {} as Record<string, unknown> } }
const form = reactive(defaults())
const selected = computed(() => store.items.find(item => item.id === selectedId.value) ?? store.items[0])
function actionLabel(item: Workflow) {
  const action = item.workflowJson.find(node => node.action)?.action
  return action ? actions[action.type] : '仅模拟'
}
const history = computed(() => store.executions.filter(item => item.workflowId === selected.value?.id))
const owners = [
  { id: 'studiolo', label: 'Studiolo', icon: 'studiolo', description: '定时、数据变化、Agent 完成后、手动' },
  { id: 'openclaw', label: 'OpenClaw', icon: 'claw', description: '原生 Cron · 待接入' },
  { id: 'hermes', label: 'Hermes', icon: 'hermes', description: '原生 Cron · 待接入' },
] as const
const filters = [
  { id: 'running', label: '运行中', color: 'var(--accent)' }, { id: 'fail', label: '失败', color: 'var(--danger)' },
  { id: 'unknown', label: '结果未知', color: 'var(--warn)' }, { id: 'paused', label: '已暂停', color: 'var(--text-3)' },
] as const
const jobFilter = ref('')
const ownerFilter = ref('all')
const showMobileDetail = ref(false)
const ownerPicker = ref<HTMLDialogElement>()
const jobState = (item: Workflow) => {
  const last = store.runtimeExecutions.find(run => run.workflowId === item.id)?.status
  if (!item.enabled) return 'paused'
  if (last === 'running' || last === 'claimed') return 'running'
  if (last === 'failed') return 'fail'
  if (last === 'succeeded' || last === 'success') return 'ok'
  return 'unknown'
}
const jobLabels = { paused: '已暂停', running: '运行中', fail: '失败', ok: '成功', unknown: '暂无结果' }
const filtered = computed(() => (ownerFilter.value === 'all' || ownerFilter.value === 'studiolo')
  ? store.items.filter(item => !jobFilter.value || (jobFilter.value === 'attn' ? ['fail', 'unknown'].includes(jobState(item)) : jobState(item) === jobFilter.value))
  : [])
function scheduleValue(item: Workflow, key: string) {
  return String((item.triggerConfigJson.schedule as Record<string, unknown> | undefined)?.[key] ?? '—')
}
function runViewTransition(update: () => Promise<void> | void, types: string[]) {
  if (props.mobile && typeof document !== 'undefined' && document.startViewTransition && document.documentElement?.dataset.motion !== 'reduced') {
    document.startViewTransition({ update, types })
  } else {
    void update()
  }
}
function chooseTask(item: Workflow) {
  if (props.mobile) {
    runViewTransition(async () => {
      selectedId.value = item.id
      showMobileDetail.value = true
      await nextTick()
    }, ['forward'])
  } else {
    selectedId.value = item.id
  }
}
function closeMobileDetail() {
  runViewTransition(async () => {
    showMobileDetail.value = false
    await nextTick()
  }, ['backward'])
}
function requestCreate() { ownerPicker.value?.showModal?.() }
function confirmOwner() { ownerPicker.value?.close?.(); openCreate() }
const date = (value?: string | null) => value ? new Date(value).toLocaleString() : '—'
const duration = (item: Execution) => item.finishedAt ? `${Math.max(0, (Date.parse(item.finishedAt) - Date.parse(item.startedAt)) / 1000).toFixed(1)}s` : '—'
let poll: ReturnType<typeof setInterval> | undefined
function openCreate() { Object.assign(form, defaults()); editingId.value = ''; formError.value = ''; open.value = true; nextTick(() => firstField.value?.focus?.()) }
defineExpose({ openCreate })
function edit(item: Workflow) {
  openCreate(); editingId.value = item.id; form.name = item.name; form.description = item.description; form.enabled = item.enabled; form.trigger = item.triggerType
  const t = item.triggerConfigJson, s = t.schedule as Record<string, unknown> | undefined
  if (s) Object.assign(form, { scheduleType: s.type, timezone: s.timezone, time: s.time, at: s.at ?? form.at, seconds: s.seconds, weekdays: s.weekdays, catchUp: s.catch_up })
  form.entityType = String(t.entity_type ?? 'data.record'); form.operation = String(t.operation ?? ''); form.agentFilter = String(t.agent_id ?? '')
  const a = item.workflowJson.find(node => node.action)?.action
  if (a) { const c = a.config; form.action = a.type; form.extra = { ...c }; form.target = String(c.collection_id ?? c.record_id ?? c.agent_id ?? ''); form.title = String(c.title ?? c.name ?? c.description ?? ''); form.amount = String(c.amount ?? '1.00'); form.ledgerType = String(c.type ?? 'expense'); form.occurredAt = String(c.occurred_at ?? form.occurredAt); form.recordStatus = String(c.status ?? 'active'); form.category = String(c.category ?? ''); form.payload = JSON.stringify(c.data_json ?? c.body ?? {}, null, 2); form.headers = JSON.stringify(c.headers ?? {}, null, 2); form.url = String(c.url ?? ''); form.timeout = Number(c.timeout ?? 10) }
}
function object(value: string): Record<string, unknown> { const parsed = JSON.parse(value); if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('请填写 JSON 对象'); return parsed }
function offsetTime(value: string) { if (!/(Z|[+-]\d{2}:\d{2})$/i.test(value)) throw new Error('时间必须包含时区偏移，例如 2026-10-03T22:00:00+08:00'); return new Date(value).toISOString() }
async function operate(action: () => Promise<unknown>) { try { await action() } catch (error) { emit('action', error instanceof Error ? error.message : '操作失败') } }
async function simulate(item: Workflow) {
  if (!auth.token) return
  selectedId.value = item.id
  await operate(async () => { await store.testRun(auth.token!, item.id); emit('action', '模拟测试完成，结果已显示在执行记录中。') })
}
async function save() {
  if (!auth.token) return
  try {
    let triggerConfig: Record<string, unknown> = {}
    if (form.trigger === 'schedule') triggerConfig = { schedule: { type: form.scheduleType, timezone: form.timezone, time: form.time, weekdays: form.weekdays, seconds: form.seconds, catch_up: form.catchUp, ...(['once','interval'].includes(form.scheduleType) ? { at: offsetTime(form.at) } : {}) } }
    if (form.trigger === 'data_changed') triggerConfig = { entity_type: form.entityType, ...(form.operation ? { operation: form.operation } : {}) }
    if (form.trigger === 'agent_completed') triggerConfig = form.agentFilter ? { agent_id: form.agentFilter } : {}
    let config: Record<string, unknown>
    if (form.action === 'ledger.create') config = { ...form.extra, type: form.ledgerType, amount: form.amount, description: form.title, occurred_at: offsetTime(form.occurredAt) }
    else if (form.action === 'agent.run') config = { agent_id: form.target, title: form.title, description: String(form.extra.description ?? '') }
    else if (form.action === 'webhook.post') config = { url: form.url, headers: object(form.headers), body: object(form.payload), timeout: form.timeout }
    else config = { [form.action === 'data.create' ? 'collection_id' : 'record_id']: form.target, name: form.title, status: form.recordStatus, category: form.category, data_json: object(form.payload) }
    const value: WorkflowInput = { name: form.name.trim(), description: form.description, enabled: form.enabled, trigger_type: form.trigger, trigger_config_json: triggerConfig, workflow_json: [{ kind: 'DO', label: '执行动作', text: actions[form.action], detail: '', action: { type: form.action, config } }] }
    if (editingId.value) await store.update(auth.token, editingId.value, value); else selectedId.value = (await store.create(auth.token, value)).id
    open.value = false; emit('action', '自动化定义已保存'); await store.refreshRuntime(auth.token)
  } catch (error) { formError.value = error instanceof Error ? error.message : '保存失败' }
}
async function remove(item: Workflow) {
  if (auth.token && await confirmAction('删除此自动化？Core 将取消尚未开始的执行。')) {
    await operate(async () => {
      await store.remove(auth.token!, item.id)
      if (props.mobile && showMobileDetail.value) closeMobileDetail()
    })
  }
}
async function showDetail(item: Execution) { if (auth.token) await operate(async () => { detail.value = await automationService.detail(auth.token!, item.workflowId, item.id) }) }
onMounted(() => { if (auth.token) store.load(auth.token, true).catch(() => {}); poll = setInterval(() => { if (auth.token && store.loaded) store.refreshRuntime(auth.token).catch(() => {}) }, 5000) })
onUnmounted(() => { clearInterval(poll) })
</script>
<template>
  <div class="automation-page" :class="mobile ? (showMobileDetail ? 'mpage push' : 'mpage') : undefined">
    <template v-if="!mobile">
      <header class="ph"><div><h1>任务</h1><div class="sub">Studiolo 自动化与 Agent Cron 在这里统一管理 · 每个任务只由一个所有者调度</div></div>
        <div class="actions"><button class="btn btn-primary" type="button" @click="requestCreate"><OpusIcon name="plus" />新建任务</button></div>
      </header>
      <div class="stat-strip"><button v-for="item in filters" :key="item.id" class="stat mat" type="button" :aria-pressed="jobFilter === item.id" @click="jobFilter = jobFilter === item.id ? '' : item.id"><span class="n num" :style="{ color: item.color }">{{ store.items.filter(task => jobState(task) === item.id).length }}</span><span class="l">{{ item.label }}</span></button></div>
      <div style="display:flex;gap:10px;align-items:center;margin-bottom:12px">
        <OpusSegment role="group" aria-label="按所有者筛选"><button type="button" :aria-pressed="ownerFilter === 'all'" @click="ownerFilter = 'all'">全部 <span class="faint">{{ store.items.length }}</span></button><button v-for="item in owners" :key="item.id" type="button" :aria-pressed="ownerFilter === item.id" @click="ownerFilter = item.id">{{ item.label }} <span class="faint">{{ item.id === 'studiolo' ? store.items.length : 0 }}</span></button></OpusSegment>
      </div>
    </template>
    <template v-else-if="!showMobileDetail">
      <div class="mhead"><h1>任务</h1><span class="spacer"></span><button class="icon-btn" type="button" style="width:40px;height:40px" aria-label="新建任务" @click="requestCreate"><OpusIcon name="plus" /></button></div>
      <div class="mchips"><button class="chip" type="button" :aria-pressed="ownerFilter === 'all' && jobFilter === ''" @click="ownerFilter = 'all'; jobFilter = ''">全部</button><button class="chip" type="button" :aria-pressed="jobFilter === 'attn'" @click="ownerFilter = 'all'; jobFilter = 'attn'">需要关注</button><button class="chip" type="button" :aria-pressed="jobFilter === 'running'" @click="ownerFilter = 'all'; jobFilter = 'running'">运行中</button><button v-for="item in owners" :key="item.id" class="chip" type="button" :aria-pressed="ownerFilter === item.id" @click="ownerFilter = item.id; jobFilter = ''">{{ item.label }}</button></div>
      <button v-for="item in filtered" :key="item.id" class="jobcard mat" type="button" @click="chooseTask(item)">
        <div class="top"><b>{{ item.name }}</b><span class="run" :class="jobState(item)">{{ jobLabels[jobState(item)] }}</span></div>
        <div><span class="owner o-studiolo"><span class="mark"><OpusIcon name="studiolo" /></span>Studiolo</span></div>
        <div class="meta"><span>{{ triggers[item.triggerType as keyof typeof triggers] ?? '旧版配置' }}</span><span>下次 {{ date(store.runtimes[item.id]?.nextRunAt) }}</span></div>
      </button>
      <p v-if="!filtered.length" class="faint" style="text-align:center;padding:30px">没有符合条件的任务</p>
    </template>
    <p v-if="store.error" class="notice danger" role="alert">{{ store.error }} <button class="btn btn-sm btn-ghost" type="button" @click="auth.token && store.load(auth.token, true).catch(() => {})">重试</button></p>
    <div v-if="store.runtimeError" class="notice" style="margin-bottom:12px"><OpusIcon name="wifiOff" /><div>{{ store.runtimeError }}</div><button class="btn btn-sm btn-ghost" type="button" :disabled="store.refreshing" @click="auth.token && store.refreshRuntime(auth.token)">刷新</button></div>
    <div :class="mobile ? undefined : 'tasks-wrap'">
      <div v-if="!mobile" class="tasks-table mat-solid"><table class="tbl">
        <thead><tr><th>任务</th><th>调度所有者</th><th>计划</th><th>下次运行</th><th>最近结果</th></tr></thead>
        <tbody>
          <tr v-for="item in filtered" :key="item.id" :class="{ 'is-selected': selected?.id === item.id }" @click="chooseTask(item)">
            <td><button class="task-name" type="button" style="text-align:left" @click.stop="chooseTask(item)"><b>{{ item.name }}</b><span>{{ actionLabel(item) }}</span></button></td>
            <td><span class="owner o-studiolo"><span class="mark"><OpusIcon name="studiolo" /></span>Studiolo</span></td>
            <td><div class="task-name"><span style="color:var(--text);font-size:13px">{{ triggers[item.triggerType as keyof typeof triggers] ?? '旧版配置' }}</span><span v-if="item.triggerType === 'schedule'">{{ scheduleValue(item, 'timezone') }}</span></div></td>
            <td class="muted">{{ date(store.runtimes[item.id]?.nextRunAt) }}</td>
            <td><div class="task-name"><span class="run" :class="jobState(item)">{{ jobLabels[jobState(item)] }}</span><span>{{ date(store.runtimes[item.id]?.lastRunAt) }}</span></div></td>
          </tr>
          <tr v-if="!filtered.length"><td colspan="5" class="faint" style="text-align:center;height:80px">{{ store.loading ? '正在加载任务…' : '没有符合条件的任务' }}</td></tr>
        </tbody>
      </table></div>
      <aside v-if="!mobile || showMobileDetail" :key="selected?.id || 'empty'" :class="mobile ? undefined : 'task-detail mat-solid enter'" aria-label="任务详情">
        <div v-if="mobile" class="navbar"><button class="icon-btn" type="button" aria-label="返回" @click="closeMobileDetail"><OpusIcon name="chevL" /></button><div class="t">任务详情</div><span style="width:40px"></span></div>
        <template v-if="selected && (mobile || filtered.some(item => item.id === selected?.id))">
          <template v-if="mobile">
            <div style="padding:4px 4px 14px"><h2 style="margin:0 0 4px;font-size:22px">{{ selected.name }}</h2><span class="run" :class="jobState(selected)">{{ jobLabels[jobState(selected)] }}</span><span class="faint" style="font-size:12.5px"> · {{ triggers[selected.triggerType as keyof typeof triggers] }}</span></div>
            <div class="owner-box oc-studiolo"><div><span class="owner o-studiolo"><span class="mark"><OpusIcon name="studiolo" /></span>Studiolo</span></div><div>由 Studiolo Core 执行，历史保存在 Core。</div></div>
            <div class="mbtns">
              <button class="btn btn-primary" type="button" :disabled="store.loading || !selected.workflowJson.some(node => node.action)" @click="auth.token && selected && operate(() => store.run(auth.token!, selected!.id))"><OpusIcon name="play" />立即运行</button>
              <button class="btn btn-ghost" type="button" :disabled="store.loading" @click="auth.token && selected && operate(() => store.update(auth.token!, selected!.id, { enabled: !selected!.enabled }))"><OpusIcon :name="selected.enabled ? 'pause' : 'play'" />{{ selected.enabled ? '暂停' : '恢复' }}</button>
            </div>
            <div class="btn-row" style="margin-bottom:12px">
              <button class="btn btn-sm btn-ghost" type="button" :disabled="store.loading" @click="selected && simulate(selected)">模拟测试</button>
              <button class="btn btn-sm btn-ghost" type="button" @click="selected && edit(selected)"><OpusIcon name="pencil" />编辑</button>
              <button class="btn btn-sm btn-danger" type="button" @click="selected && remove(selected)">删除</button>
            </div>
            <div class="kvl mat-solid">
              <div><span>计划</span><span>{{ triggers[selected.triggerType as keyof typeof triggers] ?? '旧版配置' }}</span></div>
              <div><span>原生表达</span><span class="mono">{{ scheduleValue(selected, 'time') }}</span></div>
              <div><span>时区</span><span>{{ scheduleValue(selected, 'timezone') }}</span></div>
              <div><span>下次运行</span><span>{{ date(store.runtimes[selected.id]?.nextRunAt) }}</span></div>
            </div>
            <div class="sec-t">运行历史<span class="spacer"></span><span style="font-weight:500">来自 Studiolo Core</span></div>
            <div class="mtimeline mat-solid">
              <button v-for="item in history" :key="item.id" class="t" type="button" style="width:100%;text-align:left" @click="showDetail(item)"><span class="run" :class="item.status === 'failed' ? 'fail' : item.status === 'succeeded' || item.status === 'success' ? 'ok' : 'unknown'">{{ statuses[item.status] }}</span><span class="faint">{{ duration(item) }}</span><span class="when">{{ date(item.startedAt) }}</span></button>
              <div v-if="!history.length" class="t faint">暂无执行记录</div>
            </div>
          </template>
          <template v-else>
            <div style="display:flex;align-items:flex-start;gap:10px"><div class="grow"><h3 style="margin:0;font-size:17px">{{ selected.name }}</h3><div class="faint" style="font-size:12px;margin-top:2px">{{ triggers[selected.triggerType as keyof typeof triggers] }} · <span class="run" :class="jobState(selected)">{{ jobLabels[jobState(selected)] }}</span></div></div><button class="switch" type="button" role="switch" aria-label="启用任务" :aria-checked="selected.enabled" :disabled="store.loading" @click="auth.token && selected && operate(() => store.update(auth.token!, selected!.id, { enabled: !selected!.enabled }))"></button></div>
            <div class="owner-card oc-studiolo"><div class="ttl"><span class="owner o-studiolo"><span class="mark"><OpusIcon name="studiolo" /></span>Studiolo</span></div><p>由 Studiolo Core 执行，历史保存在 Core。</p></div>
            <dl class="sched"><dt>计划</dt><dd>{{ triggers[selected.triggerType as keyof typeof triggers] ?? '旧版配置' }}</dd><dt>原生表达</dt><dd class="mono">{{ scheduleValue(selected, 'time') }}</dd><dt>所有者时区</dt><dd>{{ scheduleValue(selected, 'timezone') }}</dd><dt>下次运行</dt><dd>{{ date(store.runtimes[selected.id]?.nextRunAt) }}</dd></dl>
            <div class="btn-row">
              <button class="btn btn-primary" type="button" :disabled="store.loading || !selected.workflowJson.some(node => node.action)" @click="auth.token && selected && operate(() => store.run(auth.token!, selected!.id))"><OpusIcon name="play" />立即运行</button>
              <button class="btn btn-ghost" type="button" :disabled="store.loading" @click="selected && simulate(selected)">模拟测试</button><button class="btn btn-ghost" type="button" @click="selected && edit(selected)"><OpusIcon name="pencil" />编辑</button><button class="btn btn-danger" type="button" @click="selected && remove(selected)">删除</button>
            </div>
            <div><div class="card-h" style="margin-bottom:6px"><OpusIcon name="history" /> 运行历史<span class="spacer"></span><span class="chip">来源：Studiolo Core</span></div>
              <div class="timeline" style="margin-top:10px"><button v-for="item in history" :key="item.id" class="t" type="button" style="text-align:left" @click="showDetail(item)"><span class="dot" :class="item.status === 'failed' ? 'danger' : item.status === 'succeeded' ? 'ok' : 'unknown'"></span><span>{{ statuses[item.status] }}<small v-if="item.triggerType === 'simulation'"> · 模拟</small><span class="faint"> · {{ duration(item) }}</span><div class="faint" style="font-size:12px">{{ item.resultJson?.simulated ? '未执行任何真实动作' : item.errorCode || item.message }}</div></span><span class="when">{{ date(item.startedAt) }}</span></button><div v-if="!history.length" class="faint">暂无执行记录</div></div>
            </div>
          </template>
        </template>
        <div v-else class="cleared"><OpusIcon name="tasks" />选择一个任务</div>
      </aside>
    </div>
    <dialog ref="ownerPicker" class="dlg" aria-labelledby="nj-title" closedby="any">
      <form class="dlg-body" method="dialog" @submit.prevent="confirmOwner"><h2 id="nj-title">由谁来运行这个任务？</h2><p>每个任务只有一个调度所有者。创建后由它独立执行与保存历史，Studiolo 负责统一查看和管理。</p>
        <div class="owner-pick"><button v-for="item in owners" :key="item.id" type="button" class="owner-opt" :class="'oc-' + item.id" :aria-pressed="item.id === 'studiolo'" :disabled="item.id !== 'studiolo'"><span class="am"><OpusIcon :name="item.icon" /></span><span><div class="nm">{{ item.label }}</div><div class="ds">{{ item.description }}</div></span></button></div>
        <div class="dlg-actions"><button class="btn btn-ghost" type="button" @click="ownerPicker?.close?.()">取消</button><button class="btn btn-primary" type="submit">继续</button></div>
      </form>
    </dialog>

    <Modal :open="open" :title="`${editingId ? '编辑' : '新建'}自动化`" @close="open = false">
      <form id="automation-editor-form" @submit.prevent="save">
        <div class="field"><label for="auto-name">名称</label><input id="auto-name" ref="firstField" v-model="form.name" class="input" required maxlength="120" data-initial-focus /></div>
        <div class="field"><label for="auto-desc">描述</label><input id="auto-desc" v-model="form.description" class="input" maxlength="500" /></div>
        <label class="dlg-check"><input v-model="form.enabled" type="checkbox" />启用</label>
        <div class="field"><label for="auto-trigger">触发器</label><select id="auto-trigger" v-model="form.trigger" class="input"><option v-for="(label,key) in triggers" :key="key" :value="key">{{ label }}</option></select></div>
        <template v-if="form.trigger === 'schedule'">
          <div class="field-grid">
            <div class="field"><label>计划</label><select v-model="form.scheduleType" class="input"><option value="once">一次</option><option value="daily">每天</option><option value="weekly">每周</option><option value="interval">间隔</option></select></div>
            <div class="field"><label>时区</label><input v-model="form.timezone" class="input" required placeholder="Asia/Shanghai" /></div>
          </div>
          <div v-if="['daily','weekly'].includes(form.scheduleType)" class="field"><label>时间</label><input v-model="form.time" class="input" type="time" required /></div>
          <div v-if="form.scheduleType === 'weekly'" class="field"><label>星期</label><select v-model="form.weekdays" class="input" multiple style="height:auto"><option v-for="(label,day) in ['一','二','三','四','五','六','日']" :key="day" :value="day">星期{{ label }}</option></select></div>
          <div v-if="['once','interval'].includes(form.scheduleType)" class="field"><label>开始时间（含时区偏移）</label><input v-model="form.at" class="input" required placeholder="2026-10-03T22:00:00+08:00" /></div>
          <div v-if="form.scheduleType === 'interval'" class="field"><label>间隔（秒）</label><input v-model="form.seconds" class="input" type="number" min="10" max="31536000" required /></div>
          <div class="field"><label>错过计划</label><select v-model="form.catchUp" class="input"><option value="catch_up_once">恢复后补执行一次</option><option value="skip">跳过</option></select></div>
        </template>
        <template v-if="form.trigger === 'data_changed'">
          <div class="field-grid">
            <div class="field"><label>数据类型</label><select v-model="form.entityType" class="input"><option value="data.record">数据记录</option><option value="ledger.transaction">账本交易</option><option value="website">网站</option></select></div>
            <div class="field"><label>变更</label><select v-model="form.operation" class="input"><option value="">所有变更</option><option value="upsert">创建或更新</option><option value="delete">删除</option></select></div>
          </div>
        </template>
        <div v-if="form.trigger === 'agent_completed'" class="field"><label>Core Agent ID（留空监听全部）</label><input v-model="form.agentFilter" class="input" maxlength="36" /></div>
        <div class="field"><label>动作</label><select v-model="form.action" class="input" @change="form.extra = {}"><option v-for="(label,key) in actions" :key="key" :value="key">{{ label }}</option></select></div>
        <template v-if="form.action === 'ledger.create'">
          <div class="field-grid">
            <div class="field"><label>交易类型</label><select v-model="form.ledgerType" class="input"><option value="expense">支出</option><option value="income">收入</option></select></div>
            <div class="field"><label>金额</label><input v-model="form.amount" class="input" type="number" min="0.01" step="0.01" required /></div>
          </div>
          <div class="field"><label>交易说明</label><input v-model="form.title" class="input" required maxlength="200" /></div>
          <div class="field"><label>交易时间（含时区偏移）</label><input v-model="form.occurredAt" class="input" required /></div>
        </template>
        <template v-else-if="form.action === 'webhook.post'">
          <div class="field"><label>HTTPS URL</label><input v-model="form.url" class="input" type="url" required /></div>
          <div class="field"><label>公开请求头（JSON）</label><textarea v-model="form.headers" class="input mono" rows="2" /></div>
          <div class="field"><label>JSON 请求体</label><textarea v-model="form.payload" class="input mono" rows="4" /></div>
          <div class="field"><label>超时（秒）</label><input v-model="form.timeout" class="input" type="number" min="1" max="30" required /></div>
          <div class="notice"><OpusIcon name="info" /><div>仅公网 HTTPS，不允许凭证或敏感请求头。远端须支持 Idempotency-Key 才能防止重复副作用。</div></div>
        </template>
        <template v-else>
          <div class="field"><label>{{ form.action === 'agent.run' ? 'Core Agent ID' : form.action === 'data.create' ? '集合 ID' : '记录 ID' }}</label><input v-model="form.target" class="input" required maxlength="36" /></div>
          <div class="field"><label>{{ form.action === 'agent.run' ? '任务标题' : '记录名称' }}</label><input v-model="form.title" class="input" required maxlength="160" /></div>
          <template v-if="form.action !== 'agent.run'">
            <div class="field-grid">
              <div class="field"><label>状态</label><input v-model="form.recordStatus" class="input" maxlength="40" /></div>
              <div class="field"><label>分类</label><input v-model="form.category" class="input" maxlength="80" /></div>
            </div>
            <div class="field"><label>JSON 数据</label><textarea v-model="form.payload" class="input mono" rows="4" /></div>
          </template>
          <p v-else class="faint" style="margin:0;font-size:12px">成功创建 Core Agent 任务即视为动作成功。</p>
        </template>
        <p v-if="formError" class="dlg-error" role="alert">{{ formError }}</p>
      </form>
      <template #footer>
        <button class="btn btn-ghost" type="button" @click="open = false">取消</button>
        <button class="btn btn-primary" type="submit" form="automation-editor-form" :disabled="store.loading">保存</button>
      </template>
    </Modal>

    <Modal :open="!!detail" title="执行详情" @close="detail = null">
      <dl v-if="detail" class="meta-grid">
        <dt>自动化</dt><dd>{{ store.items.find(item => item.id === detail?.workflowId)?.name }}</dd>
        <dt>Execution ID</dt><dd class="mono">{{ detail.id }}</dd>
        <dt>触发器</dt><dd>{{ detail.triggerType }} · {{ detail.triggerInstanceId }}</dd>
        <dt>定义版本</dt><dd>{{ detail.automationRevision }}</dd>
        <dt>状态 / 尝试</dt><dd>{{ statuses[detail.status] }} / {{ detail.attempt }}</dd>
        <dt>开始 / 结束</dt><dd>{{ date(detail.startedAt) }} / {{ date(detail.finishedAt) }}</dd>
        <dt>下次重试</dt><dd>{{ date(detail.nextAttemptAt) }}</dd>
        <dt>动作</dt><dd>{{ detail.action?.type ?? '模拟' }}</dd>
        <dt>结果</dt><dd class="mono">{{ JSON.stringify(detail.resultSummary) }}</dd>
        <dt>失败原因</dt><dd>{{ detail.errorCode ?? '—' }}</dd>
      </dl>
    </Modal>
  </div>
</template>
