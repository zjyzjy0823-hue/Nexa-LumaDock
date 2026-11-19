<script setup lang="ts">
import { confirmAction } from '../composables/useConfirm'
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import type { Component } from 'vue'
import { AudioLines, BarChart3, CalendarDays, Code2, Database, FileText, Globe2, Search, Sparkles, Workflow } from 'lucide-vue-next'
import OpusIcon from '../components/ui/OpusIcon.vue'
import OpusSegment from '../components/ui/OpusSegment.vue'
import Modal from '../components/ui/Modal.vue'
import FleetNodesSection from '../components/chat/FleetNodesSection.vue'
import { useAuthStore } from '../stores/auth'
import { useAgentsStore } from '../stores/agents'
import { useFleetStore } from '../stores/fleet'
import type { Agent, AgentCapabilityIcon, AgentStatus, AgentTask, AgentTaskStatus } from '../types/agent'

type AgentTab = 'overview' | 'tasks' | 'logs' | 'capabilities' | 'api' | 'usage'
type DirectoryFilter = 'all' | AgentStatus
type TaskFilter = 'all' | AgentTaskStatus

defineOptions({ inheritAttrs: false })
const props = defineProps<{ mobile?: boolean }>()
const emit = defineEmits<{ action: [message: string]; navigate: [page: string]; back: [] }>()
const auth = useAuthStore()
const store = useAgentsStore()
const fleet = useFleetStore()
const fleetSectionRef = ref<InstanceType<typeof FleetNodesSection> | null>(null)
const agents = computed(() => store.agents)
const searchQuery = ref('')
const directoryFilter = ref<DirectoryFilter>('all')
const taskFilter = ref<TaskFilter>('all')
const selectedId = ref('')
const activeTab = ref<AgentTab>('overview')
const mobileDetail = ref(false)
const createAgentOpen = ref(false)
const agentDialogMode = ref<'add' | 'edit'>('add')
const createTaskOpen = ref(false)
const newAgentName = ref('')
const newAgentRole = ref('')
const newAgentModel = ref('未配置')
const newAgentDescription = ref('')
const newAgentScopes = ref<string[]>([])
const scopeDomains = [{ id: 'ledger', label: 'Ledger' }, { id: 'websites', label: 'Websites' }, { id: 'data', label: 'Data' }]
const scopeEffects = [{ id: 'read', label: '读取' }, { id: 'write', label: '新增/修改' }, { id: 'delete', label: '删除（破坏性）' }]
const newTaskTitle = ref('')
const newTaskDescription = ref('')
const saving = ref(false)
const formError = ref('')
const revealedToken = ref('')
let pollTimer: ReturnType<typeof setInterval> | undefined

function notify(message: string) { emit('action', message) }
function runViewTransition(update: () => Promise<void> | void, types: string[]) {
  if (props.mobile && typeof document !== 'undefined' && document.startViewTransition && document.documentElement?.dataset.motion !== 'reduced') {
    document.startViewTransition({ update, types })
  } else {
    void update()
  }
}

watch(agents, list => { if (!list.some(item => item.id === selectedId.value)) selectedId.value = list[0]?.id ?? '' }, { immediate: true })
onMounted(() => {
  if (auth.token) {
    void store.load(auth.token)
    pollTimer = setInterval(() => { if (auth.token) void store.load(auth.token, true) }, 20_000)
  }
})
onUnmounted(() => { if (pollTimer) clearInterval(pollTimer) })

const avatarIcons: Record<Agent['avatar'], Component> = {
  spark: Sparkles, orbit: Workflow, wave: AudioLines, chart: BarChart3, sun: CalendarDays,
}
const capabilityIcons: Record<AgentCapabilityIcon, Component> = {
  search: Search, file: FileText, globe: Globe2, database: Database, code: Code2, calendar: CalendarDays,
}
const tabs: { id: AgentTab; label: string }[] = [
  { id: 'overview', label: '概览' }, { id: 'tasks', label: '任务' }, { id: 'logs', label: '日志' },
  { id: 'capabilities', label: '能力' }, { id: 'api', label: 'API 调用' }, { id: 'usage', label: '使用情况' },
]
const visibleAgents = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return agents.value.filter(agent => {
    const matchesStatus = directoryFilter.value === 'all' || agent.status === directoryFilter.value
    const matchesQuery = !query || [agent.name, agent.role, agent.model, agent.description].some(value => value.toLowerCase().includes(query))
    return matchesStatus && matchesQuery
  })
})
const selectedAgent = computed<Agent | undefined>(() => agents.value.find(agent => agent.id === selectedId.value) ?? visibleAgents.value[0] ?? agents.value[0])
const currentTask = computed(() => selectedAgent.value?.tasks.find(task => task.status === 'running') ?? selectedAgent.value?.tasks.find(task => task.status === 'queued'))
const visibleTasks = computed(() => (selectedAgent.value?.tasks ?? []).filter(task => taskFilter.value === 'all' || task.status === taskFilter.value))
const runningCount = computed(() => agents.value.filter(agent => agent.status === 'running').length)
const onlineNodesCount = computed(() => fleet.nodes.filter(n => n.status === 'online').length)
const readyEnginesCount = computed(() =>
  fleet.nodes.reduce((sum, n) => sum + n.adapters.filter(a => a.status === 'ready').length, 0),
)
const todayTasks = computed(() => agents.value.reduce((total, agent) => total + agent.tasksToday, 0))
const completedCount = computed(() => agents.value.reduce((total, agent) => total + agent.tasks.filter(task => task.status === 'completed').length, 0))
const activityByDay = computed(() => {
  const tasks = selectedAgent.value?.tasks ?? []
  return Array.from({ length: 7 }, (_, index) => {
    const day = new Date(); day.setHours(0, 0, 0, 0); day.setDate(day.getDate() - (6 - index))
    const count = tasks.filter(task => new Date(task.createdAt).toDateString() === day.toDateString()).length
    return { label: ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][day.getDay()], count }
  })
})

function agentStatus(status: AgentStatus) {
  return {
    running: { label: '运行中', cls: 'online' },
    idle: { label: '空闲', cls: 'online' },
    offline: { label: '离线', cls: 'offline' },
    error: { label: '错误', cls: 'offline' },
    disabled: { label: '已停用', cls: '' },
  }[status]
}
function taskStateClass(status: AgentTaskStatus) {
  return status === 'completed' ? 'ok' : status === 'running' ? 'running' : status === 'failed' ? 'fail' : 'unknown'
}
function taskStateLabel(status: AgentTaskStatus) {
  return { running: '进行中', completed: '已完成', failed: '失败', queued: '等待中' }[status]
}
function selectAgent(id: string) {
  revealedToken.value = ''
  taskFilter.value = 'all'
  if (props.mobile) {
    runViewTransition(async () => {
      selectedId.value = id
      activeTab.value = 'overview'
      mobileDetail.value = true
      await nextTick()
    }, ['forward'])
  } else {
    selectedId.value = id
    activeTab.value = 'overview'
  }
}
function closeMobileDetail() {
  runViewTransition(async () => {
    mobileDetail.value = false
    await nextTick()
  }, ['backward'])
}
function openCreate() {
  agentDialogMode.value = 'add'; newAgentName.value = ''; newAgentRole.value = ''; newAgentModel.value = '未配置'; newAgentDescription.value = ''; newAgentScopes.value = []; formError.value = ''; createAgentOpen.value = true
}
function openEdit() {
  if (!selectedAgent.value) return
  agentDialogMode.value = 'edit'; newAgentName.value = selectedAgent.value.name; newAgentRole.value = selectedAgent.value.role; newAgentModel.value = selectedAgent.value.model
  newAgentDescription.value = selectedAgent.value.description; newAgentScopes.value = [...(selectedAgent.value.dataScopes ?? [])]; formError.value = ''; createAgentOpen.value = true
}
defineExpose({ openCreate })
function toggleScope(scope: string) {
  newAgentScopes.value = newAgentScopes.value.includes(scope) ? newAgentScopes.value.filter(item => item !== scope) : [...newAgentScopes.value, scope]
}
async function toggleAgentStatus() {
  const item = selectedAgent.value
  if (!auth.token || !item) return
  try {
    await store.update(auth.token, item.id, { enabled: !item.enabled })
    notify(item.enabled ? `已暂停 ${item.name}` : `已启用 ${item.name}`)
  } catch (error) { notify(error instanceof Error ? error.message : '更新失败') }
}
async function generateAgentToken() {
  const item = selectedAgent.value
  if (!auth.token || !item) return
  try {
    revealedToken.value = (await store.generateToken(auth.token, item.id)).token
    notify('Agent Token 已生成，请立即保存。')
  } catch (error) { notify(error instanceof Error ? error.message : '生成失败') }
}
async function revokeAgentToken() {
  const item = selectedAgent.value
  if (!auth.token || !item || !(await confirmAction(`撤销「${item.name}」的 Agent Token？`))) return
  try {
    await store.revokeToken(auth.token, item.id)
    revealedToken.value = ''
    notify('Agent Token 已撤销。')
  } catch (error) { notify(error instanceof Error ? error.message : '撤销失败') }
}
async function copyAgentToken() {
  try { await navigator.clipboard.writeText(revealedToken.value); notify('Agent Token 已复制。') }
  catch { notify('复制失败，请手动复制。') }
}
async function saveAgent() {
  const name = newAgentName.value.trim()
  if (!auth.token || !name || saving.value) { formError.value = '请输入智能体名称。'; return }
  saving.value = true; formError.value = ''
  try {
    const existing = agentDialogMode.value === 'edit' ? selectedAgent.value : undefined
    const data = { name, role: newAgentRole.value.trim() || '自定义助理', description: newAgentDescription.value.trim(),
      model: newAgentModel.value.trim() || '未配置', workspace: existing?.workspace ?? '个人工作区',
      avatar: existing?.avatar ?? 'spark' as const, dataScopes: [...newAgentScopes.value] }
    const item = agentDialogMode.value === 'edit' && selectedId.value ? await store.update(auth.token, selectedId.value, data) : await store.create(auth.token, data)
    selectedId.value = item.id; activeTab.value = 'overview'; createAgentOpen.value = false
    notify(agentDialogMode.value === 'edit' ? '智能体已更新。' : '智能体已创建，等待运行时连接。')
  } catch (error) { formError.value = error instanceof Error ? error.message : '保存失败' }
  finally { saving.value = false }
}
async function removeAgent() {
  const item = selectedAgent.value
  if (!auth.token || !item || !(await confirmAction(`删除「${item.name}」及其任务？`))) return
  try {
    await store.remove(auth.token, item.id)
    if (props.mobile && mobileDetail.value) closeMobileDetail()
    notify('智能体已删除。')
  } catch (error) { notify(error instanceof Error ? error.message : '删除失败') }
}
async function createTask() {
  const title = newTaskTitle.value.trim()
  const item = selectedAgent.value
  if (!auth.token || !item || !title || saving.value) { formError.value = '请输入任务名称。'; return }
  saving.value = true; formError.value = ''
  try {
    await store.createTask(auth.token, item.id, title, newTaskDescription.value.trim())
    newTaskTitle.value = ''; newTaskDescription.value = ''; createTaskOpen.value = false; activeTab.value = 'tasks'
    notify('任务已加入队列。')
  } catch (error) { formError.value = error instanceof Error ? error.message : '创建失败' }
  finally { saving.value = false }
}
async function removeTask(task: AgentTask) {
  const item = selectedAgent.value
  if (!auth.token || !item || !(await confirmAction(`删除任务「${task.title}」？`))) return
  try { await store.removeTask(auth.token, item.id, task.id); notify('任务已删除。') }
  catch (error) { notify(error instanceof Error ? error.message : '删除失败') }
}
async function copyApiPath(path: string) {
  try { await navigator.clipboard.writeText(path); notify('API 路径已复制') }
  catch { notify(path) }
}
</script>

<template>
  <div v-if="mobile && mobileDetail && selectedAgent" class="mpage push">
    <div class="navbar">
      <button class="icon-btn" type="button" aria-label="返回" @click="closeMobileDetail"><OpusIcon name="chevL" /></button>
      <div class="t">{{ selectedAgent.name }}</div>
      <button class="icon-btn" type="button" aria-label="编辑" @click="openEdit"><OpusIcon name="pencil" /></button>
    </div>
    <div class="dhero">
      <div class="tile-icon"><component :is="avatarIcons[selectedAgent.avatar]" class="i" /></div>
      <h2>{{ selectedAgent.name }}</h2>
      <span class="conn" :class="agentStatus(selectedAgent.status).cls">{{ agentStatus(selectedAgent.status).label }} · {{ selectedAgent.role }}</span>
    </div>
    <div class="mbtns">
      <button class="btn btn-primary" type="button" @click="formError = ''; createTaskOpen = true"><OpusIcon name="plus" />新建任务</button>
      <button class="btn btn-ghost" type="button" @click="toggleAgentStatus"><OpusIcon :name="selectedAgent.enabled ? 'pause' : 'play'" />{{ selectedAgent.enabled ? '暂停' : '启用' }}</button>
    </div>
    <div class="kvl mat-solid">
      <div><span>模型</span><span>{{ selectedAgent.model }}</span></div>
      <div><span>Runtime</span><span>{{ selectedAgent.runtimeType || '—' }}</span></div>
      <div><span>完成率</span><span>{{ selectedAgent.successRate }}</span></div>
      <div><span>Token</span><span class="mono">{{ selectedAgent.tokenLast4 ? `na_live_••${selectedAgent.tokenLast4}` : '未生成' }}</span></div>
    </div>
    <div class="btn-row">
      <button class="btn btn-ghost" type="button" @click="generateAgentToken">{{ selectedAgent.tokenLast4 ? '重新生成 Token' : '生成 Token' }}</button>
      <button v-if="selectedAgent.tokenLast4" class="btn btn-danger" type="button" @click="revokeAgentToken">撤销 Token</button>
      <button class="btn btn-danger" type="button" @click="removeAgent">删除智能体</button>
    </div>
    <div class="sec-t">任务（{{ selectedAgent.tasks.length }}）</div>
    <div class="mlist mat-solid">
      <div v-for="task in selectedAgent.tasks" :key="task.id" class="mrow"><span class="grow"><div class="title">{{ task.title }}</div><div class="sub">{{ taskStateLabel(task.status) }} · {{ task.time }}</div></span><button v-if="task.status === 'queued'" class="btn btn-sm btn-danger" type="button" @click="removeTask(task)">删除</button></div>
      <div v-if="!selectedAgent.tasks.length" class="mrow faint">暂无任务</div>
    </div>
  </div>

  <div v-else-if="mobile" class="mpage push">
    <div class="navbar">
      <button class="icon-btn" type="button" aria-label="返回" @click="emit('back')"><OpusIcon name="chevL" /></button>
      <div class="t">Agent 配置</div>
      <button class="icon-btn" type="button" aria-label="添加智能体" @click="openCreate"><OpusIcon name="plus" /></button>
    </div>
    <div class="msearch"><OpusIcon name="search" /><input v-model="searchQuery" placeholder="搜索智能体…" aria-label="搜索智能体"></div>
    <div style="padding:0 12px 10px">
      <FleetNodesSection :mobile="true" @navigate="emit('navigate', $event)" @action="notify" />
    </div>
    <div v-if="store.loading" class="cleared" role="status">正在加载智能体…</div>
    <div v-else-if="store.error" class="notice danger" role="alert">{{ store.error }}<button class="btn btn-sm btn-ghost" type="button" @click="auth.token && store.load(auth.token)">重试</button></div>
    <div v-else class="mlist mat-solid">
      <button v-for="agent in visibleAgents" :key="agent.id" class="mrow" type="button" @click="selectAgent(agent.id)">
        <span class="tile-icon"><component :is="avatarIcons[agent.avatar]" class="i" /></span>
        <span class="grow"><div class="title">{{ agent.name }}</div><div class="sub">{{ agent.role }} · {{ agent.lastActive }}</div></span>
        <span class="conn" :class="agentStatus(agent.status).cls">{{ agentStatus(agent.status).label }}</span>
        <OpusIcon name="chevR" />
      </button>
      <div v-if="!visibleAgents.length" class="mrow faint">暂无智能体</div>
    </div>
  </div>

  <div v-else class="agents-page">
    <header class="ph">
      <div><h1>Agent 与节点配置</h1><div class="sub">管理已接入的控制节点、对话智能体（Codex / OpenCode / Hermes 等）与本地数据代理</div></div>
      <div class="actions">
        <button class="btn btn-ghost" type="button" @click="emit('navigate', 'Chat')"><OpusIcon name="chat" />前往对话</button>
        <button class="btn btn-ghost" type="button" @click="fleetSectionRef?.openCreateModal()"><OpusIcon name="server" />新增控制节点</button>
        <button class="btn btn-ghost" type="button" :disabled="!selectedAgent" @click="formError = ''; createTaskOpen = true"><OpusIcon name="zap" />新建任务</button>
        <button class="btn btn-primary" type="button" @click="openCreate"><OpusIcon name="plus" />添加数据智能体</button>
      </div>
    </header>

    <div class="stat-strip">
      <div class="stat mat"><span class="n num" style="color:var(--accent)">{{ String(fleet.nodes.length).padStart(2, '0') }}</span><span class="l">控制节点（{{ onlineNodesCount }} 在线）</span></div>
      <div class="stat mat"><span class="n num" style="color:var(--ok)">{{ String(readyEnginesCount).padStart(2, '0') }}</span><span class="l">已接入对话引擎</span></div>
      <div class="stat mat"><span class="n num">{{ String(agents.length).padStart(2, '0') }}</span><span class="l">本地数据智能体（{{ runningCount }} 运行中）</span></div>
      <div class="stat mat"><span class="n num">{{ todayTasks }} / {{ completedCount }}</span><span class="l">今日 / 完成任务</span></div>
    </div>

    <FleetNodesSection ref="fleetSectionRef" @navigate="emit('navigate', $event)" @action="notify" />

    <div v-if="store.loading" class="cleared" role="status">正在加载本地数据智能体…</div>
    <div v-else-if="store.error" class="notice danger" role="alert">{{ store.error }} <button class="btn btn-sm btn-ghost" type="button" @click="auth.token && store.load(auth.token)">重试</button></div>
    <div v-else-if="!agents.length && fleet.nodes.length" class="card mat agents-compact-na">
      <div>
        <strong>本地 Data Actions 智能体（na_live_）</strong>
        <div class="faint" style="font-size:12.5px">尚未添加通过 API 读写个人账本/资料库的独立数据智能体；上方已为您展示当前对话中所有可用的控制节点与引擎。</div>
      </div>
      <button class="btn btn-subtle btn-sm" type="button" @click="openCreate"><OpusIcon name="plus" />添加数据智能体</button>
    </div>
    <div v-else class="agents-split">
      <aside class="card mat agents-side">
        <div class="agents-side__head">
          <div class="search" style="flex:1"><OpusIcon name="search" /><input v-model="searchQuery" class="input" type="search" placeholder="搜索智能体…" aria-label="搜索智能体" /></div>
          <span class="faint" style="font-size:12px">{{ agents.length }}</span>
        </div>
        <div class="agents-filters" aria-label="智能体状态筛选">
          <button v-for="filter in ([['all', '全部'], ['running', '运行中'], ['idle', '空闲'], ['offline', '离线'], ['error', '错误'], ['disabled', '已停用']] as const)" :key="filter[0]" class="chip" type="button" :aria-pressed="directoryFilter === filter[0]" @click="directoryFilter = filter[0]">{{ filter[1] }}</button>
        </div>
        <div v-if="visibleAgents.length" class="list">
          <button v-for="agent in visibleAgents" :key="agent.id" class="row" type="button" :class="{ 'is-selected': selectedAgent?.id === agent.id }" @click="selectAgent(agent.id)">
            <span class="tile-icon"><component :is="avatarIcons[agent.avatar]" class="i" /></span>
            <span class="grow"><div class="title">{{ agent.name }}</div><div class="sub">{{ agent.role }}</div></span>
            <span class="conn" :class="agentStatus(agent.status).cls">{{ agentStatus(agent.status).label }}</span>
          </button>
        </div>
        <div v-else class="cleared" style="padding:24px"><OpusIcon name="bot" />{{ agents.length ? '没有匹配的智能体' : '还没有智能体' }}</div>
      </aside>

      <section v-if="selectedAgent" :key="selectedAgent.id" class="card mat enter agents-main">
        <div class="agents-hero">
          <span class="tile-icon" style="width:46px;height:46px;border-radius:14px"><component :is="avatarIcons[selectedAgent.avatar]" class="i" style="width:22px;height:22px" /></span>
          <div class="grow" style="min-width:0">
            <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap"><h2 style="margin:0;font-size:19px">{{ selectedAgent.name }}</h2><span class="conn" :class="agentStatus(selectedAgent.status).cls">{{ agentStatus(selectedAgent.status).label }}</span></div>
            <div class="faint" style="font-size:12.5px;margin-top:2px">{{ selectedAgent.role }} · {{ selectedAgent.model }} · {{ selectedAgent.workspace }}</div>
            <p v-if="selectedAgent.description" class="muted" style="margin:6px 0 0;font-size:13px">{{ selectedAgent.description }}</p>
          </div>
          <div class="btn-row">
            <button class="btn btn-sm btn-ghost" type="button" @click="toggleAgentStatus"><OpusIcon :name="selectedAgent.enabled ? 'pause' : 'play'" />{{ selectedAgent.enabled ? '暂停' : '启用' }}</button>
            <button class="btn btn-sm btn-ghost" type="button" @click="openEdit">编辑</button>
            <button class="btn btn-sm btn-danger" type="button" @click="removeAgent">删除</button>
            <button class="btn btn-sm btn-primary" type="button" @click="formError = ''; createTaskOpen = true"><OpusIcon name="plus" />新建任务</button>
          </div>
        </div>

        <OpusSegment role="tablist" aria-label="智能体详情标签页" style="margin:14px 0">
          <button v-for="tab in tabs" :key="tab.id" type="button" :aria-pressed="activeTab === tab.id" @click="activeTab = tab.id">{{ tab.label }}</button>
        </OpusSegment>

        <div v-if="activeTab === 'overview'" class="agents-overview">
          <div class="agents-overview__grid">
            <div class="owner-card oc-studiolo">
              <div class="ttl"><OpusIcon name="zap" />{{ currentTask?.status === 'running' ? '当前任务' : '接下来' }}</div>
              <div style="font-weight:650;font-size:15px">{{ currentTask?.title ?? '一切准备就绪' }}</div>
              <p>{{ currentTask?.description ?? '创建一个任务，开始与智能体协作。' }}</p>
              <div><button class="btn btn-sm btn-subtle" type="button" @click="activeTab = 'tasks'">查看全部任务 <OpusIcon name="chevR" /></button></div>
            </div>
            <div class="mat-solid" style="padding:14px;border-radius:var(--r-md)">
              <dl class="meta-grid">
                <dt>完成率</dt><dd>{{ selectedAgent.successRate }}</dd>
                <dt>最近连接</dt><dd>{{ selectedAgent.uptime }}</dd>
                <dt>Runtime</dt><dd>{{ selectedAgent.runtimeType || '—' }} {{ selectedAgent.runtimeVersion || '' }}</dd>
                <dt>实例</dt><dd>{{ selectedAgent.runtimeInstance || '—' }}</dd>
                <dt>最近心跳</dt><dd>{{ selectedAgent.lastSeenAt ? new Date(selectedAgent.lastSeenAt).toLocaleString() : '—' }}</dd>
              </dl>
            </div>
          </div>

          <div class="mat-solid agents-token-row">
            <div class="grow">
              <div style="font-weight:600">Agent Token</div>
              <div class="faint" style="font-size:12px">数据权限由 Scope 控制 · {{ selectedAgent.dataScopes?.length ? `已授权 ${selectedAgent.dataScopes.length} 项` : '无数据权限' }}</div>
            </div>
            <code class="mono">{{ revealedToken || (selectedAgent.tokenLast4 ? `na_live_••••${selectedAgent.tokenLast4}` : '尚未生成') }}</code>
            <button v-if="revealedToken" class="btn btn-sm btn-ghost" type="button" @click="copyAgentToken">复制</button>
            <button class="btn btn-sm btn-ghost" type="button" @click="generateAgentToken">{{ selectedAgent.tokenLast4 ? '重新生成' : '生成 Token' }}</button>
            <button v-if="selectedAgent.tokenLast4" class="btn btn-sm btn-danger" type="button" @click="revokeAgentToken">撤销</button>
          </div>
        </div>

        <div v-else-if="activeTab === 'tasks'">
          <div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap">
            <button v-for="filter in ([['all', '全部'], ['running', '进行中'], ['completed', '已完成'], ['failed', '失败'], ['queued', '等待中']] as const)" :key="filter[0]" class="chip" type="button" :aria-pressed="taskFilter === filter[0]" @click="taskFilter = filter[0]">{{ filter[1] }}</button>
          </div>
          <div class="mat-solid" style="border-radius:var(--r-md);overflow:auto">
            <table class="tbl">
              <thead><tr><th>任务</th><th>状态</th><th>时间</th><th></th></tr></thead>
              <tbody>
                <tr v-for="task in visibleTasks" :key="task.id"><td style="font-weight:550">{{ task.title }}<div class="faint" style="font-size:12px">{{ task.description }}</div><div v-if="task.result?.text" class="faint" style="font-size:12px">结果：{{ task.result.text }}</div><div v-if="task.errorMessage" style="font-size:12px;color:var(--danger)">错误：{{ task.errorMessage }}</div></td><td><span class="run" :class="taskStateClass(task.status)">{{ taskStateLabel(task.status) }}</span></td><td class="muted">{{ task.time }}</td><td class="r"><button v-if="task.status === 'queued'" class="btn btn-sm btn-danger" type="button" @click="removeTask(task)">删除</button></td></tr>
                <tr v-if="!visibleTasks.length"><td colspan="4" class="faint" style="text-align:center;height:70px">当前筛选下没有任务</td></tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-else-if="activeTab === 'logs'" class="list">
          <div v-for="(log, index) in selectedAgent.logs" :key="`${log.time}-${index}`" class="row"><span class="chip">{{ log.level }}</span><span class="grow">{{ log.eventType || 'agent.event' }} · {{ log.message }}</span><span class="faint">{{ new Date(log.createdAt).toLocaleString() }}</span></div>
          <div v-if="!selectedAgent.logs.length" class="cleared" style="padding:24px"><OpusIcon name="info" />暂无运行日志</div>
        </div>

        <div v-else-if="activeTab === 'capabilities'" class="list">
          <div v-for="cap in selectedAgent.capabilities" :key="cap.title" class="row"><span class="tile-icon"><component :is="capabilityIcons[cap.icon]" class="i" /></span><span class="grow"><div class="title">{{ cap.title }}</div><div class="sub">{{ cap.description }}</div></span><OpusIcon name="check" style="color:var(--ok)" /></div>
          <div v-if="!selectedAgent.capabilities.length" class="cleared" style="padding:24px"><OpusIcon name="sparkle" />尚未连接能力</div>
        </div>

        <div v-else-if="activeTab === 'api'" class="mat-solid" style="border-radius:var(--r-md);overflow:auto">
          <table v-if="selectedAgent.apiCalls.length" class="tbl"><thead><tr><th>方法</th><th>路径</th><th>时间</th><th>延迟</th><th>状态</th><th></th></tr></thead>
            <tbody><tr v-for="(call, index) in selectedAgent.apiCalls" :key="`${call.endpoint}-${index}`"><td class="mono">{{ call.method }}</td><td class="mono">{{ call.endpoint }}</td><td class="muted">{{ call.time }}</td><td class="muted">{{ call.duration }}</td><td style="color:var(--ok)">{{ call.status }} OK</td><td class="r"><button class="btn btn-sm btn-ghost" type="button" @click="copyApiPath(call.endpoint)"><OpusIcon name="copy" />复制</button></td></tr></tbody>
          </table>
          <div v-else class="cleared" style="padding:24px"><OpusIcon name="api" />暂无 API 调用</div>
        </div>

        <div v-else class="agents-overview">
          <div class="stats4" style="grid-template-columns:repeat(3,minmax(0,1fr));margin-bottom:0">
            <div class="mat-solid" style="padding:14px;border-radius:var(--r-md)"><div class="faint" style="font-size:12px">今日任务</div><div class="v num" style="font-size:20px;font-weight:700;margin-top:4px">{{ selectedAgent.tasksToday }}</div></div>
            <div class="mat-solid" style="padding:14px;border-radius:var(--r-md)"><div class="faint" style="font-size:12px">API 调用</div><div class="v num" style="font-size:20px;font-weight:700;margin-top:4px">{{ selectedAgent.callsToday }}</div></div>
            <div class="mat-solid" style="padding:14px;border-radius:var(--r-md)"><div class="faint" style="font-size:12px">任务完成率</div><div class="v num" style="font-size:20px;font-weight:700;margin-top:4px">{{ selectedAgent.successRate }}</div></div>
          </div>
          <div class="bars" style="height:100px;margin-top:16px"><i v-for="(day, i) in activityByDay" :key="day.label" :style="{ height: Math.max(8, Math.min(100, day.count * 22)) + '%', animationDelay: i * 25 + 'ms' }" :title="`${day.label}: ${day.count} 个任务`"></i></div>
        </div>
      </section>
      <div v-else class="card mat cleared">还没有智能体，点击右上角添加</div>
    </div>
  </div>

  <Modal :open="createAgentOpen" :title="agentDialogMode === 'edit' ? '编辑智能体' : '添加智能体'" description="配置智能体身份与可访问的数据 Scope。" @close="createAgentOpen = false">
    <form id="agent-editor-form" @submit.prevent="saveAgent">
      <div class="field"><label for="ag-name">智能体名称</label><input id="ag-name" v-model="newAgentName" class="input" required maxlength="32" placeholder="例如：Nova" data-initial-focus /></div>
      <div class="field-grid">
        <div class="field"><label for="ag-role">角色定位</label><input id="ag-role" v-model="newAgentRole" class="input" maxlength="48" placeholder="例如：写作助理" /></div>
        <div class="field"><label for="ag-model">模型标识</label><input id="ag-model" v-model="newAgentModel" class="input" maxlength="120" placeholder="例如：本地模型" /></div>
      </div>
      <div class="field"><label for="ag-desc">职责说明</label><input id="ag-desc" v-model="newAgentDescription" class="input" maxlength="500" placeholder="这个智能体负责什么" /></div>
      <div class="field">
        <label>数据访问权限</label>
        <div class="agents-scope-grid">
          <div v-for="group in scopeDomains" :key="group.id" class="agents-scope-row">
            <span class="muted" style="font-size:12px;font-weight:600">{{ group.label }}</span>
            <div style="display:flex;gap:10px;flex-wrap:wrap">
              <label v-for="effect in scopeEffects" :key="effect.id" class="dlg-check" :style="effect.id === 'delete' ? 'color:var(--danger)' : undefined">
                <input v-model="newAgentScopes" type="checkbox" :value="`${group.id}:${effect.id}`" />{{ effect.label }}
              </label>
            </div>
          </div>
          <div class="agents-scope-row">
            <span class="muted" style="font-size:12px;font-weight:600">Shared Space</span>
            <div style="display:flex;gap:10px;flex-wrap:wrap">
              <label class="dlg-check">
                <input v-model="newAgentScopes" type="checkbox" value="space:read" />仅普通共享只读（机密与 E2EE 始终禁止）
              </label>
            </div>
          </div>
        </div>
      </div>
      <p v-if="formError" class="dlg-error" role="alert">{{ formError }}</p>
    </form>
    <template #footer>
      <button class="btn btn-ghost" type="button" :disabled="saving" @click="createAgentOpen = false">取消</button>
      <button class="btn btn-primary" type="submit" form="agent-editor-form" :disabled="saving">{{ saving ? '保存中…' : agentDialogMode === 'edit' ? '保存修改' : '添加智能体' }}</button>
    </template>
  </Modal>

  <Modal :open="createTaskOpen" title="新建智能体任务" description="将任务排入该智能体的执行队列。" @close="createTaskOpen = false">
    <form id="agent-task-form" @submit.prevent="createTask">
      <div class="field"><label for="ag-task-title">任务名称</label><input id="ag-task-title" v-model="newTaskTitle" class="input" required maxlength="80" placeholder="例如：整理本周市场动态" data-initial-focus /></div>
      <div class="field"><label for="ag-task-desc">任务说明</label><input id="ag-task-desc" v-model="newTaskDescription" class="input" maxlength="500" placeholder="补充任务内容" /></div>
      <p v-if="formError" class="dlg-error" role="alert">{{ formError }}</p>
    </form>
    <template #footer>
      <button class="btn btn-ghost" type="button" :disabled="saving" @click="createTaskOpen = false">取消</button>
      <button class="btn btn-primary" type="submit" form="agent-task-form" :disabled="saving">{{ saving ? '提交中…' : '创建任务' }}</button>
    </template>
  </Modal>
</template>

<style scoped>
.agents-page { min-width: 0; }
.agents-split { display: grid; grid-template-columns: 290px minmax(0, 1fr); gap: 14px; align-items: start; }
.agents-side { display: grid; gap: 10px; }
.agents-side__head { display: flex; align-items: center; gap: 8px; }
.agents-side__head .search { position: relative; }
.agents-side__head .search :deep(svg.i) { position: absolute; left: 10px; top: 50%; translate: 0 -50%; width: 15px; height: 15px; color: var(--text-3); pointer-events: none; }
.agents-side__head .search .input { height: 32px; padding-left: 32px; font-size: 13px; }
.agents-filters { display: flex; flex-wrap: wrap; gap: 6px; }
.agents-hero { display: flex; align-items: flex-start; gap: 14px; flex-wrap: wrap; }
.agents-overview { display: grid; gap: 14px; }
.agents-overview__grid { display: grid; grid-template-columns: minmax(0, 1.1fr) minmax(240px, .9fr); gap: 14px; }
.agents-token-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; padding: 12px 14px; border-radius: var(--r-md); }
.agents-scope-grid { display: grid; gap: 8px; padding: 10px; border-radius: var(--r-sm); background: var(--surface-3); }
.agents-scope-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.agents-compact-na { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding: 14px 16px; }
@media (max-width: 980px) { .agents-split, .agents-overview__grid { grid-template-columns: 1fr; } }
</style>
