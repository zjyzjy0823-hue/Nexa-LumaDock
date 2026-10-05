<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import { Plus, Play, X } from 'lucide-vue-next'
import GlassCard from '../components/ui/GlassCard.vue'
import ActionButton from '../components/ui/ActionButton.vue'
import { useAutomationStore } from '../stores/automation'
import { useAuthStore } from '../stores/auth'
import { confirmAction } from '../composables/useConfirm'
import { automationService } from '../services/automation'
import type { AutomationAction, Execution, Workflow, WorkflowInput } from '../types/automation'
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
const counters = computed(() => ['queued', 'running', 'succeeded', 'failed'].map(status => ({ status, count: store.executions.filter(item => item.status === status || (status === 'running' && item.status === 'claimed')).length })))
const date = (value?: string | null) => value ? new Date(value).toLocaleString() : '—'
const duration = (item: Execution) => item.finishedAt ? `${Math.max(0, (Date.parse(item.finishedAt) - Date.parse(item.startedAt)) / 1000).toFixed(1)}s` : '—'
let poll: ReturnType<typeof setInterval> | undefined
function openCreate() { Object.assign(form, defaults()); editingId.value = ''; formError.value = ''; open.value = true; nextTick(() => firstField.value?.focus()) }
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
async function remove(item: Workflow) { if (auth.token && await confirmAction('删除此自动化？Core 将取消尚未开始的执行。')) await operate(() => store.remove(auth.token!, item.id)) }
async function showDetail(item: Execution) { if (auth.token) await operate(async () => { detail.value = await automationService.detail(auth.token!, item.workflowId, item.id) }) }
function onKey(event: KeyboardEvent) { if (event.key === 'Escape') { open.value = false; detail.value = null } }
onMounted(() => { if (auth.token) store.load(auth.token, true).catch(() => {}); poll = setInterval(() => { if (auth.token && store.loaded) store.refreshRuntime(auth.token).catch(() => {}) }, 5000); document.addEventListener('keydown', onKey) })
onUnmounted(() => { clearInterval(poll); document.removeEventListener('keydown', onKey) })
</script>
<template>
  <div class="automation-page">
    <div class="heading"><div><h1>自动化</h1><p>由 Core 统一调度和执行；配置保留在本地并同步。</p></div><ActionButton @click="openCreate"><Plus :size="16" />新建自动化</ActionButton></div>
    <p v-if="store.error" role="alert">{{ store.error }} <button @click="auth.token && store.load(auth.token, true).catch(() => {})">重试</button></p><p v-if="store.loading" role="status">正在加载…</p>
    <GlassCard v-if="store.runtimeError" role="status">{{ store.runtimeError }}<ActionButton size="sm" variant="secondary" :disabled="store.refreshing" @click="auth.token && store.refreshRuntime(auth.token)">刷新</ActionButton></GlassCard>
    <div class="counters"><GlassCard v-for="counter in counters" :key="counter.status"><span>{{ statuses[counter.status] }}</span><strong>{{ counter.count }}</strong></GlassCard></div>
    <div class="content-grid"><section aria-label="自动化定义"><h2>我的自动化</h2><p v-if="store.loaded && !store.items.length">还没有自动化，请创建一个。</p>
      <GlassCard v-for="item in store.items" :key="item.id" class="workflow" :class="{ selected: selected?.id === item.id }"><button class="workflow-title" @click="selectedId = item.id">{{ item.name }}</button><p>{{ item.description }}</p><p>{{ item.enabled ? '已启用' : '已停用' }} · {{ triggers[item.triggerType as keyof typeof triggers] ?? '旧版配置' }} → {{ actionLabel(item) }}</p>
        <small>下次执行：{{ store.runtimes[item.id] ? date(store.runtimes[item.id]?.nextRunAt) : 'Core 状态不可用' }}<br />上次执行：{{ date(store.runtimes[item.id]?.lastRunAt) }} · {{ statuses[store.runtimes[item.id]?.lastResult ?? ''] ?? '—' }}</small>
        <div class="actions"><ActionButton size="sm" :disabled="store.loading || !item.workflowJson.some(node => node.action)" @click="auth.token && operate(() => store.run(auth.token!, item.id))"><Play :size="13" />立即运行</ActionButton><ActionButton size="sm" variant="secondary" :disabled="store.loading" @click="auth.token && operate(() => store.testRun(auth.token!, item.id))">模拟测试</ActionButton><ActionButton size="sm" variant="secondary" @click="edit(item)">编辑</ActionButton><ActionButton size="sm" variant="secondary" :disabled="store.loading" @click="auth.token && operate(() => store.update(auth.token!, item.id, { enabled: !item.enabled }))">{{ item.enabled ? '停用' : '启用' }}</ActionButton><ActionButton size="sm" variant="danger" :disabled="store.loading" @click="remove(item)">删除</ActionButton></div>
      </GlassCard></section>
      <GlassCard class="history"><div class="heading"><h2>执行记录 · {{ selected?.name ?? '选择自动化' }}</h2><ActionButton size="sm" variant="secondary" :disabled="store.refreshing" @click="auth.token && store.refreshRuntime(auth.token)">刷新</ActionButton></div><p v-if="!history.length">{{ store.runtimeError ? '执行记录暂不可用' : '暂无执行记录' }}</p>
        <div class="table-scroll"><table v-if="history.length"><thead><tr><th>状态 / 触发方式</th><th>开始 / 耗时</th><th>结果 / 失败原因</th><th>尝试</th></tr></thead><tbody><tr v-for="item in history" :key="item.id"><td><button @click="showDetail(item)">{{ statuses[item.status] }}</button><small>{{ triggers[item.triggerType as keyof typeof triggers] ?? '模拟' }}</small></td><td>{{ date(item.attempt ? item.startedAt : item.createdAt) }}<small>{{ duration(item) }}</small></td><td>{{ item.errorCode ?? (item.resultJson?.simulated ? '未执行任何真实动作' : JSON.stringify(item.resultSummary)) }}</td><td>{{ item.attempt }}</td></tr></tbody></table></div>
      </GlassCard></div>
    <Teleport to="body"><div v-if="open" class="modal-backdrop" @click.self="open = false"><GlassCard class="modal" role="dialog" aria-modal="true" aria-labelledby="automation-editor-title"><div class="heading"><h2 id="automation-editor-title">{{ editingId ? '编辑' : '新建' }}自动化</h2><button aria-label="关闭" @click="open = false"><X :size="18" /></button></div>
      <form @submit.prevent="save"><label>名称<input ref="firstField" v-model="form.name" required maxlength="120" /></label><label>描述<input v-model="form.description" maxlength="500" /></label><label class="checkbox"><input v-model="form.enabled" type="checkbox" />启用</label><label>触发器<select v-model="form.trigger"><option v-for="(label,key) in triggers" :key="key" :value="key">{{ label }}</option></select></label>
        <template v-if="form.trigger === 'schedule'"><label>计划<select v-model="form.scheduleType"><option value="once">一次</option><option value="daily">每天</option><option value="weekly">每周</option><option value="interval">间隔</option></select></label><label>时区<input v-model="form.timezone" required placeholder="Asia/Shanghai" /></label><label v-if="['daily','weekly'].includes(form.scheduleType)">时间<input v-model="form.time" type="time" required /></label><label v-if="form.scheduleType === 'weekly'">星期<select v-model="form.weekdays" multiple><option v-for="(label,day) in ['一','二','三','四','五','六','日']" :key="day" :value="day">星期{{ label }}</option></select></label><label v-if="['once','interval'].includes(form.scheduleType)">开始时间（含时区偏移）<input v-model="form.at" required placeholder="2026-10-03T22:00:00+08:00" /></label><label v-if="form.scheduleType === 'interval'">间隔（秒）<input v-model="form.seconds" type="number" min="10" max="31536000" required /></label><label>错过计划<select v-model="form.catchUp"><option value="catch_up_once">恢复后补执行一次</option><option value="skip">跳过</option></select></label></template>
        <template v-if="form.trigger === 'data_changed'"><label>数据类型<select v-model="form.entityType"><option value="data.record">数据记录</option><option value="ledger.transaction">账本交易</option><option value="website">网站</option></select></label><label>变更<select v-model="form.operation"><option value="">所有变更</option><option value="upsert">创建或更新</option><option value="delete">删除</option></select></label></template><label v-if="form.trigger === 'agent_completed'">Core Agent ID（留空监听全部）<input v-model="form.agentFilter" maxlength="36" /></label>
        <label>动作<select v-model="form.action" @change="form.extra = {}"><option v-for="(label,key) in actions" :key="key" :value="key">{{ label }}</option></select></label>
        <template v-if="form.action === 'ledger.create'"><label>交易类型<select v-model="form.ledgerType"><option value="expense">支出</option><option value="income">收入</option></select></label><label>金额<input v-model="form.amount" type="number" min="0.01" step="0.01" required /></label><label>交易说明<input v-model="form.title" required maxlength="200" /></label><label>交易时间（含时区偏移）<input v-model="form.occurredAt" required /></label></template>
        <template v-else-if="form.action === 'webhook.post'"><label>HTTPS URL<input v-model="form.url" type="url" required /></label><label>公开请求头（JSON）<textarea v-model="form.headers" rows="2" /></label><label>JSON 请求体<textarea v-model="form.payload" rows="4" /></label><label>超时（秒）<input v-model="form.timeout" type="number" min="1" max="30" required /></label><p>仅公网 HTTPS，不允许凭证或敏感请求头。远端须支持 Idempotency-Key 才能防止重复副作用。</p></template>
        <template v-else><label>{{ form.action === 'agent.run' ? 'Core Agent ID' : form.action === 'data.create' ? '集合 ID' : '记录 ID' }}<input v-model="form.target" required maxlength="36" /></label><label>{{ form.action === 'agent.run' ? '任务标题' : '记录名称' }}<input v-model="form.title" required maxlength="160" /></label><template v-if="form.action !== 'agent.run'"><label>状态<input v-model="form.recordStatus" maxlength="40" /></label><label>分类<input v-model="form.category" maxlength="80" /></label><label>JSON 数据<textarea v-model="form.payload" rows="4" /></label></template><p v-else>成功创建 Core Agent 任务即视为动作成功。</p></template>
        <p v-if="formError" role="alert">{{ formError }}</p><div class="actions"><ActionButton variant="secondary" @click="open = false">取消</ActionButton><ActionButton type="submit" :disabled="store.loading">保存</ActionButton></div>
      </form></GlassCard></div>
      <div v-if="detail" class="modal-backdrop" @click.self="detail = null"><GlassCard class="modal" role="dialog" aria-modal="true" aria-labelledby="execution-detail-title"><div class="heading"><h2 id="execution-detail-title">执行详情</h2><button aria-label="关闭" @click="detail = null"><X :size="18" /></button></div><dl><dt>自动化</dt><dd>{{ store.items.find(item => item.id === detail?.workflowId)?.name }}</dd><dt>Execution ID</dt><dd>{{ detail.id }}</dd><dt>触发器</dt><dd>{{ detail.triggerType }} · {{ detail.triggerInstanceId }}</dd><dt>定义版本</dt><dd>{{ detail.automationRevision }}</dd><dt>状态 / 尝试</dt><dd>{{ statuses[detail.status] }} / {{ detail.attempt }}</dd><dt>开始 / 结束</dt><dd>{{ date(detail.startedAt) }} / {{ date(detail.finishedAt) }}</dd><dt>下次重试</dt><dd>{{ date(detail.nextAttemptAt) }}</dd><dt>动作</dt><dd>{{ detail.action?.type ?? '模拟' }}</dd><dt>结果</dt><dd>{{ JSON.stringify(detail.resultSummary) }}</dd><dt>失败原因</dt><dd>{{ detail.errorCode ?? '—' }}</dd></dl></GlassCard></div>
    </Teleport>
  </div>
</template>
<style scoped>
.workflow,.history,.modal { height:auto; } .modal { transform:none; overflow-x:hidden; } .modal:hover { transform:none; } .modal :deep(.glass-card__body) { min-width:0; flex:none; }
.automation-page { padding-bottom:24px; color:#fff; } .heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:16px; } h1 { font-size:25px; margin:0; } h2 { font-size:17px; margin:0 0 12px; } p { font-size:12px; line-height:1.6; } .counters { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:16px 0; } .counters strong { display:block; font-size:30px; margin-top:10px; } .content-grid { display:grid; grid-template-columns:minmax(300px,1fr) minmax(400px,1.4fr); gap:18px; align-items:start; } .workflow { margin-bottom:14px; border:var(--glass-tile-border); background:var(--glass-tile-background); color:#354665; } .selected { outline:2px solid #8a9fe6; } .workflow-title { font-weight:700; font-size:16px; border:0; background:none; color:inherit; padding:0; cursor:pointer; } .actions { display:flex; flex-wrap:wrap; gap:7px; margin-top:15px; } small { display:block; font-size:11px; line-height:1.7; } .table-scroll { overflow:auto; } table { border-collapse:collapse; width:100%; font-size:11px; } th,td { padding:12px 8px; text-align:left; border-bottom:1px solid #ffffff35; word-break:break-word; } td button,.heading>button { background:#ffffffa0; border:0; border-radius:8px; color:#354665; padding:6px 10px; cursor:pointer; } .modal-backdrop { position:fixed; z-index:120; inset:0; display:grid; place-items:center; padding:16px; background:#18275366; backdrop-filter:blur(9px); } .modal { width:min(100%,540px); max-height:calc(100dvh - 32px); overflow:auto; color:#fff; } .modal :deep(.glass-card__body) { overflow:visible; } form { display:grid; gap:12px; } label { display:grid; gap:6px; font-size:12px; } input,textarea,select { width:100%; padding:9px 11px; border:1px solid #94abd477; border-radius:9px; color:#354665; background:#ffffffe8; font:inherit; } .checkbox { display:flex; align-items:center; } .checkbox input { width:auto; } dt { font-size:11px; opacity:.8; margin-top:14px; } dd { margin:4px 0; font-size:12px; overflow-wrap:anywhere; } @media(max-width:1000px) { .content-grid { grid-template-columns:1fr; } } @media(max-width:600px) { .counters { grid-template-columns:repeat(2,1fr); } .heading { align-items:start; } }
.modal { overflow-x:hidden; }
</style>
