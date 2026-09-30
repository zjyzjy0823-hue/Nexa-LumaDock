<script setup lang="ts">
import { confirmAction } from '../composables/useConfirm'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import type { Component } from 'vue'
import {
  Activity, ArrowRight, ArrowUpRight, AudioLines, BarChart3, Bot, CalendarDays,
  Check, CheckCircle2, ChevronRight, Clock3, Code2, Copy, Database,
  FileText, Filter, Globe2, Layers3, MoreHorizontal, Pause, Play, Plus,
  Search, Send, Sparkles, Workflow, X, Zap,
} from 'lucide-vue-next'
import ActionButton from '../components/ui/ActionButton.vue'
import GlassCard from '../components/ui/GlassCard.vue'
import ListItemCard from '../components/ui/ListItemCard.vue'
import SectionContainer from '../components/ui/SectionContainer.vue'
import StatCard from '../components/ui/StatCard.vue'
import StatusBadge from '../components/ui/StatusBadge.vue'
import { useAuthStore } from '../stores/auth'
import { useAgentsStore } from '../stores/agents'
import type { Agent, AgentCapabilityIcon, AgentStatus, AgentTaskStatus, AgentTask } from '../types/agent'

type AgentTab = 'overview' | 'tasks' | 'logs' | 'capabilities' | 'api' | 'usage'
type DirectoryFilter = 'all' | AgentStatus
type TaskFilter = 'all' | AgentTaskStatus

const auth = useAuthStore()
const store = useAgentsStore()
const agents = computed(() => store.agents)
const selectedId = ref('')
const activeTab = ref<AgentTab>('overview')
const directoryFilter = ref<DirectoryFilter>('all')
const taskFilter = ref<TaskFilter>('all')
const searchQuery = ref('')
const createAgentOpen = ref(false)
const agentDialogMode = ref<'add' | 'edit'>('add')
const createTaskOpen = ref(false)
const newAgentName = ref('')
const newAgentRole = ref('')
const newAgentDescription = ref('')
const newAgentModel = ref('未配置')
const newAgentScopes = ref<string[]>([])
const scopeDomains = [{ id: 'ledger', label: 'Ledger' }, { id: 'websites', label: 'Websites' }, { id: 'data', label: 'Data' }]
const scopeEffects = [{ id: 'read', label: '读取' }, { id: 'write', label: '新增/修改' }, { id: 'delete', label: '删除（破坏性）' }]
const newTaskTitle = ref('')
const newTaskDescription = ref('')
const saving = ref(false)
const formError = ref('')
const toast = ref('')
const revealedToken = ref('')
let toastTimer: ReturnType<typeof setTimeout> | undefined
let pollTimer: ReturnType<typeof setInterval> | undefined

function openCreate() {
  agentDialogMode.value = 'add'
  newAgentName.value = ''
  newAgentRole.value = ''
  newAgentDescription.value = ''
  newAgentModel.value = '未配置'
  newAgentScopes.value = []
  formError.value = ''
  createAgentOpen.value = true
}
function openEdit() {
  const item = selectedAgent.value
  if (!item) return
  agentDialogMode.value = 'edit'
  newAgentName.value = item.name
  newAgentRole.value = item.role
  newAgentDescription.value = item.description
  newAgentModel.value = item.model
  newAgentScopes.value = [...(item.dataScopes ?? [])]
  formError.value = ''
  createAgentOpen.value = true
}
defineExpose({ openCreate })
watch(agents, items => {
  if (!items.some(item => item.id === selectedId.value)) selectedId.value = items[0]?.id ?? ''
}, { immediate: true })
onMounted(() => {
  if (auth.token) void store.load(auth.token)
  pollTimer = setInterval(() => { if (auth.token) void store.load(auth.token, true) }, 20_000)
})

const tabs: { id: AgentTab; label: string }[] = [
  { id: 'overview', label: '概览' },
  { id: 'tasks', label: '任务' },
  { id: 'logs', label: '日志' },
  { id: 'capabilities', label: '能力' },
  { id: 'api', label: 'API 调用' },
  { id: 'usage', label: '使用情况' },
]

const avatarIcons: Record<Agent['avatar'], Component> = {
  spark: Sparkles, orbit: Workflow, wave: AudioLines, chart: BarChart3, sun: CalendarDays,
}
const capabilityIcons: Record<AgentCapabilityIcon, Component> = {
  search: Search, file: FileText, globe: Globe2, database: Database, code: Code2, calendar: CalendarDays,
}

const selectedAgent = computed<Agent | undefined>(() => agents.value.find(agent => agent.id === selectedId.value) ?? agents.value[0])
const visibleAgents = computed(() => agents.value.filter(agent => {
  const matchesFilter = directoryFilter.value === 'all' || agent.status === directoryFilter.value
  const query = searchQuery.value.trim().toLocaleLowerCase()
  const matchesQuery = !query || `${agent.name} ${agent.role} ${agent.model}`.toLocaleLowerCase().includes(query)
  return matchesFilter && matchesQuery
}))
const runningCount = computed(() => agents.value.filter(agent => agent.status === 'running').length)
const todayTasks = computed(() => agents.value.reduce((total, agent) => total + agent.tasksToday, 0))
const completedCount = computed(() => agents.value.reduce((total, agent) => total + agent.tasks.filter(task => task.status === 'completed').length, 0))
const currentTask = computed(() => selectedAgent.value?.tasks.find(task => task.status === 'running') ?? selectedAgent.value?.tasks.find(task => task.status === 'queued'))
const recentTasks = computed(() => selectedAgent.value?.tasks.filter(task => task.status !== 'running').slice(0, 3) ?? [])
const visibleTasks = computed(() => selectedAgent.value?.tasks.filter(task => taskFilter.value === 'all' || task.status === taskFilter.value) ?? [])
const activityByDay = computed(() => {
  const tasks = selectedAgent.value?.tasks ?? []
  return Array.from({ length: 7 }, (_, index) => {
    const day = new Date(); day.setHours(0, 0, 0, 0); day.setDate(day.getDate() - (6 - index))
    const count = tasks.filter(task => new Date(task.createdAt).toDateString() === day.toDateString()).length
    return { label: ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][day.getDay()], count }
  })
})

function agentStatus(status: AgentStatus) {
  if (status === 'running') return { label: '运行中', tone: 'success' as const }
  if (status === 'idle') return { label: '在线 · 空闲', tone: 'success' as const }
  if (status === 'error') return { label: '在线 · 错误', tone: 'warning' as const }
  if (status === 'disabled') return { label: '已停用', tone: 'neutral' as const }
  return { label: '离线', tone: 'neutral' as const }
}

function taskStatus(status: AgentTaskStatus) {
  if (status === 'running') return { label: '进行中', tone: 'info' as const }
  if (status === 'completed') return { label: '已完成', tone: 'success' as const }
  if (status === 'failed') return { label: '失败', tone: 'warning' as const }
  return { label: '等待中', tone: 'warning' as const }
}

function selectAgent(id: string) {
  selectedId.value = id
  revealedToken.value = ''
  activeTab.value = 'overview'
  taskFilter.value = 'all'
}

async function generateAgentToken() {
  const item = selectedAgent.value
  if (!auth.token || !item) return
  try {
    revealedToken.value = (await store.generateToken(auth.token, item.id)).token
    showToast('新 Token 仅显示本次，请立即复制保存。')
  } catch (error) { showToast(error instanceof Error ? error.message : '生成失败') }
}

async function revokeAgentToken() {
  const item = selectedAgent.value
  if (!auth.token || !item) return
  try { await store.revokeToken(auth.token, item.id); revealedToken.value = ''; showToast('Token 已撤销。') }
  catch (error) { showToast(error instanceof Error ? error.message : '撤销失败') }
}

async function copyAgentToken() {
  if (!revealedToken.value) return
  try { await navigator.clipboard.writeText(revealedToken.value); showToast('Token 已复制。') }
  catch { showToast('复制失败，请手动复制。') }
}

async function toggleAgentStatus() {
  const item = selectedAgent.value
  if (!auth.token || !item) return
  try {
    await store.update(auth.token, item.id, { enabled: !item.enabled })
    showToast(item.enabled ? `${item.name} 已暂停` : `${item.name} 已启用，等待运行时连接`)
  } catch (error) { showToast(error instanceof Error ? error.message : '操作失败') }
}

function showToast(message: string) {
  toast.value = message
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = '' }, 3000)
}

async function saveAgent() {
  const name = newAgentName.value.trim()
  if (!auth.token || !name || saving.value) { formError.value = '请输入智能体名称。'; return }
  saving.value = true
  formError.value = ''
  try {
    const existing = agentDialogMode.value === 'edit' ? selectedAgent.value : undefined
    const data = { name, role: newAgentRole.value.trim() || '自定义助理', description: newAgentDescription.value.trim(),
      model: newAgentModel.value.trim() || '未配置', workspace: existing?.workspace ?? '个人工作区',
      avatar: existing?.avatar ?? 'spark' as const, dataScopes: [...newAgentScopes.value] }
    const item = agentDialogMode.value === 'edit' && selectedId.value
      ? await store.update(auth.token, selectedId.value, data)
      : await store.create(auth.token, data)
    selectedId.value = item.id
    activeTab.value = 'overview'
    createAgentOpen.value = false
    showToast(agentDialogMode.value === 'edit' ? '智能体已更新。' : '智能体已创建，等待运行时连接。')
  } catch (error) { formError.value = error instanceof Error ? error.message : '保存失败' }
  finally { saving.value = false }
}

async function removeAgent() {
  const item = selectedAgent.value
  if (!auth.token || !item || !(await confirmAction(`删除「${item.name}」及其任务？`))) return
  try { await store.remove(auth.token, item.id); showToast('智能体已删除。') }
  catch (error) { showToast(error instanceof Error ? error.message : '删除失败') }
}

async function createTask() {
  const title = newTaskTitle.value.trim()
  const item = selectedAgent.value
  if (!auth.token || !item || !title || saving.value) { formError.value = '请输入任务名称。'; return }
  saving.value = true
  formError.value = ''
  try {
    await store.createTask(auth.token, item.id, title, newTaskDescription.value.trim())
    newTaskTitle.value = ''
    newTaskDescription.value = ''
    createTaskOpen.value = false
    activeTab.value = 'tasks'
    showToast('任务已加入队列。')
  } catch (error) { formError.value = error instanceof Error ? error.message : '创建失败' }
  finally { saving.value = false }
}

async function removeTask(task: AgentTask) {
  const item = selectedAgent.value
  if (!auth.token || !item || !(await confirmAction(`删除任务「${task.title}」？`))) return
  try { await store.removeTask(auth.token, item.id, task.id); showToast('任务已删除。') }
  catch (error) { showToast(error instanceof Error ? error.message : '删除失败') }
}

async function copyApiPath(path: string) {
  try {
    await navigator.clipboard.writeText(path)
    showToast('API 路径已复制')
  } catch {
    showToast(path)
  }
}

onUnmounted(() => { if (toastTimer) clearTimeout(toastTimer); if (pollTimer) clearInterval(pollTimer) })
</script>

<template>
  <div class="agents-page">
    <h1 class="visually-hidden">智能体</h1>
    <div class="agents-page-actions" aria-label="智能体操作">
      <ActionButton variant="secondary" size="sm" :disabled="!selectedAgent" @click="formError = ''; createTaskOpen = true"><Zap :size="15" />新建任务</ActionButton>
      <ActionButton size="sm" @click="openCreate"><Plus :size="16" />添加智能体</ActionButton>
    </div>

    <div class="agents-stats">
      <StatCard label="智能体总数" :value="String(agents.length).padStart(2, '0')" detail="已配置的 AI 助手" tone="blue" :icon="Bot" />
      <StatCard label="运行中" :value="String(runningCount).padStart(2, '0')" detail="正在处理您的任务" tone="mint" :icon="Activity" />
      <StatCard label="今日任务" :value="todayTasks" detail="跨所有智能体" tone="violet" :icon="Layers3" />
      <StatCard label="已完成任务" :value="completedCount" detail="所有智能体的任务" tone="amber" :icon="CheckCircle2" />
    </div>

    <div v-if="store.loading" class="agent-state" role="status">正在加载智能体…</div>
    <div v-else-if="store.error" class="agent-state" role="alert">{{ store.error }} <button type="button" @click="auth.token && store.load(auth.token)">重试</button></div>
    <div v-else class="agents-workspace">
      <SectionContainer class="agent-directory" title="我的智能体">
        <template #action><span class="directory-count">{{ agents.length }} 个智能体</span></template>
        <label class="agent-search">
          <Search :size="15" />
          <input v-model="searchQuery" type="search" placeholder="搜索智能体..." aria-label="搜索智能体" />
          <span class="agent-search__shortcut">筛选</span>
        </label>
        <div class="directory-filters" aria-label="智能体状态筛选">
          <button v-for="filter in ([['all', '全部'], ['running', '运行中'], ['idle', '空闲'], ['offline', '离线'], ['error', '错误'], ['disabled', '已停用']] as const)" :key="filter[0]" type="button" :class="{ active: directoryFilter === filter[0] }" :aria-pressed="directoryFilter === filter[0]" @click="directoryFilter = filter[0]">{{ filter[1] }}</button>
        </div>
        <div v-if="visibleAgents.length" class="directory-list">
          <ListItemCard v-for="agent in visibleAgents" :key="agent.id" :title="agent.name" :subtitle="agent.role" :selected="selectedId === agent.id" @click="selectAgent(agent.id)">
            <template #leading>
              <span class="agent-avatar agent-avatar--small" :class="`agent-avatar--${agent.avatar}`"><component :is="avatarIcons[agent.avatar]" :size="18" :stroke-width="1.9" /></span>
            </template>
            <span class="directory-item__meta"><span class="directory-item__dot" :class="`directory-item__dot--${agent.status}`" />{{ agentStatus(agent.status).label }}<span class="directory-item__separator">·</span>{{ agent.lastActive }}</span>
            <template #trailing><ChevronRight :size="15" class="directory-item__chevron" /></template>
          </ListItemCard>
        </div>
        <div v-else class="directory-empty"><Search :size="21" /><span>{{ agents.length ? '没有找到匹配的智能体' : '还没有智能体，创建后即可管理任务与连接状态' }}</span></div>
        <button class="directory-add" type="button" @click="openCreate"><Plus :size="16" />创建新的智能体</button>
      </SectionContainer>

      <GlassCard v-if="selectedAgent" class="agent-profile">
        <div class="profile-hero">
          <div class="profile-identity">
            <span class="agent-avatar agent-avatar--large" :class="`agent-avatar--${selectedAgent.avatar}`"><component :is="avatarIcons[selectedAgent.avatar]" :size="28" :stroke-width="1.7" /></span>
            <div class="profile-identity__copy">
              <div class="profile-title-row"><h2>{{ selectedAgent.name }}</h2><StatusBadge :label="agentStatus(selectedAgent.status).label" :tone="agentStatus(selectedAgent.status).tone" /></div>
              <p class="profile-role">{{ selectedAgent.role }}<span>·</span>{{ selectedAgent.model }}<span>·</span>{{ selectedAgent.workspace }}</p>
              <p class="profile-description">{{ selectedAgent.description }}</p>
            </div>
          </div>
          <div class="profile-actions">
            <ActionButton variant="secondary" size="sm" @click="toggleAgentStatus"><Pause v-if="selectedAgent.enabled" :size="14" /><Play v-else :size="14" />{{ selectedAgent.enabled ? '暂停' : '启用' }}</ActionButton>
            <ActionButton variant="secondary" size="sm" @click="openEdit">编辑</ActionButton>
            <ActionButton variant="secondary" size="sm" @click="removeAgent">删除</ActionButton>
            <ActionButton size="sm" @click="formError = ''; createTaskOpen = true"><Plus :size="15" />新建任务</ActionButton>
          </div>
        </div>

        <nav class="profile-tabs" aria-label="智能体详情标签页">
          <button v-for="tab in tabs" :key="tab.id" type="button" :class="{ active: activeTab === tab.id }" :aria-current="activeTab === tab.id ? 'page' : undefined" @click="activeTab = tab.id">{{ tab.label }}</button>
        </nav>

        <div v-if="activeTab === 'overview'" class="overview-tab">
          <div class="overview-heading"><div><span class="eyebrow">WORKSPACE OVERVIEW</span><h3>工作概览</h3></div><span class="overview-heading__date">已保存 <span class="live-dot" /></span></div>
          <div class="overview-top-grid">
            <div class="focus-task">
              <div class="focus-task__top"><span class="focus-task__icon"><Zap :size="17" fill="currentColor" /></span><span>{{ currentTask?.status === 'running' ? '当前任务' : '接下来' }}</span><MoreHorizontal :size="20" class="focus-task__more" /></div>
              <h4>{{ currentTask?.title ?? '一切准备就绪' }}</h4>
              <p>{{ currentTask?.description ?? '创建一个任务，开始与您的智能体协作。' }}</p>
              <div class="focus-task__bottom"><span class="focus-progress"><i /><i /><i /><i class="dim" /><i class="dim" /></span><button type="button" @click="activeTab = 'tasks'">查看全部任务 <ArrowRight :size="14" /></button></div>
            </div>
            <div class="health-panel">
              <div class="health-panel__title"><span class="health-panel__pulse"><Activity :size="18" /></span><div><h4>运行状态</h4><p>智能体与任务健康度</p></div></div>
              <div class="health-panel__rows">
                <div><span>当前状态</span><StatusBadge :label="agentStatus(selectedAgent.status).label" :tone="agentStatus(selectedAgent.status).tone" /></div>
                <div><span>任务完成率</span><strong>{{ selectedAgent.successRate }}</strong></div>
                <div><span>最近连接</span><strong>{{ selectedAgent.uptime }}</strong></div>
                <div><span>Runtime 类型</span><strong>{{ selectedAgent.runtimeType || '—' }}</strong></div>
                <div><span>Runtime 版本</span><strong>{{ selectedAgent.runtimeVersion || '—' }}</strong></div>
                <div><span>Runtime 实例</span><strong>{{ selectedAgent.runtimeInstance || '—' }}</strong></div>
                <div><span>当前任务</span><strong>{{ selectedAgent.tasks.find(task => task.id === selectedAgent?.currentTaskId)?.title || '—' }}</strong></div>
                <div><span>最近心跳</span><strong>{{ selectedAgent.lastSeenAt ? new Date(selectedAgent.lastSeenAt).toLocaleString() : '—' }}</strong></div>
              </div>
            </div>
          </div>
          <div class="runtime-token-panel">
            <strong>Agent Token</strong>
            <small>Agent Token 的数据权限由设置中的 Scope 控制。{{ selectedAgent.dataScopes?.length ? `已授权 ${selectedAgent.dataScopes.length} 项` : '无数据权限' }}</small>
            <code>{{ revealedToken || (selectedAgent.tokenLast4 ? `na_live_••••${selectedAgent.tokenLast4}` : '尚未生成') }}</code>
            <button v-if="revealedToken" type="button" @click="copyAgentToken">复制</button>
            <button type="button" @click="generateAgentToken">{{ selectedAgent.tokenLast4 ? '重新生成' : '生成 Token' }}</button>
            <button v-if="selectedAgent.tokenLast4" type="button" @click="revokeAgentToken">撤销</button>
          </div>
          <div class="overview-bottom-grid">
            <SectionContainer class="overview-section" title="近期任务">
              <template #action><button class="text-link" type="button" @click="activeTab = 'tasks'">查看全部 <ArrowUpRight :size="14" /></button></template>
              <div v-if="recentTasks.length" class="recent-tasks">
                <div v-for="task in recentTasks" :key="task.id" class="recent-task">
                  <span class="recent-task__icon" :class="`recent-task__icon--${task.status}`"><Check v-if="task.status === 'completed'" :size="15" /><Clock3 v-else :size="15" /></span>
                  <span class="recent-task__copy"><strong>{{ task.title }}</strong><small>{{ task.description }}</small></span>
                  <span class="recent-task__time">{{ task.time }}</span>
                </div>
              </div>
              <p v-else class="content-empty">暂无近期任务，创建一个任务开始工作。</p>
            </SectionContainer>
            <SectionContainer class="overview-section" title="已连接能力">
              <template #action><button class="text-link" type="button" @click="activeTab = 'capabilities'">查看全部 <ArrowUpRight :size="14" /></button></template>
              <div v-if="selectedAgent.capabilities.length" class="capabilities-mini">
                <div v-for="capability in selectedAgent.capabilities.slice(0, 4)" :key="capability.title" class="capability-mini" :class="`capability-mini--${capability.tone}`"><span><component :is="capabilityIcons[capability.icon]" :size="17" /></span><strong>{{ capability.title }}</strong></div>
              </div>
              <p v-else class="content-empty">尚未配置能力。您可以稍后为这个智能体连接工具。</p>
            </SectionContainer>
          </div>
        </div>

        <div v-else-if="activeTab === 'tasks'" class="tab-content">
          <div class="tab-content__heading"><div><span class="eyebrow">TASK CENTER</span><h3>任务中心</h3><p>跟踪 {{ selectedAgent.name }} 的全部工作</p></div><ActionButton size="sm" @click="formError = ''; createTaskOpen = true"><Plus :size="15" />创建任务</ActionButton></div>
          <div class="task-filters"><Filter :size="14" /><button v-for="filter in ([['all', '全部'], ['running', '进行中'], ['completed', '已完成'], ['failed', '失败'], ['queued', '等待中']] as const)" :key="filter[0]" type="button" :class="{ active: taskFilter === filter[0] }" :aria-pressed="taskFilter === filter[0]" @click="taskFilter = filter[0]">{{ filter[1] }}</button></div>
          <div v-if="visibleTasks.length" class="full-task-list">
            <div v-for="task in visibleTasks" :key="task.id" class="full-task"><span class="full-task__symbol" :class="`full-task__symbol--${task.status}`"><Activity v-if="task.status === 'running'" :size="17" /><Check v-else-if="task.status === 'completed'" :size="17" /><Clock3 v-else :size="17" /></span><div class="full-task__copy"><strong>{{ task.title }}</strong><span>{{ task.description }}</span><span v-if="task.result?.text" class="full-task__detail">结果：{{ task.result.text }}</span><span v-if="task.errorMessage" class="full-task__detail">错误：{{ task.errorMessage }}</span></div><span class="full-task__id">{{ task.id.slice(0, 8) }}</span><StatusBadge :label="taskStatus(task.status).label" :tone="taskStatus(task.status).tone" /><time>{{ task.time }}</time><span class="task-actions"><button v-if="task.status === 'queued'" type="button" @click="removeTask(task)">删除</button></span></div>
          </div>
          <div v-else class="tab-empty"><Layers3 :size="23" />当前筛选下没有任务</div>
        </div>

        <div v-else-if="activeTab === 'logs'" class="tab-content">
          <div class="tab-content__heading"><div><span class="eyebrow">ACTIVITY LOG</span><h3>操作日志</h3><p>查看最近的设置和任务变更</p></div><StatusBadge label="已保存" tone="info" /></div>
          <div v-if="selectedAgent.logs.length" class="log-list"><div v-for="(log, index) in selectedAgent.logs" :key="`${log.time}-${index}`" class="log-row"><span class="log-row__time">{{ new Date(log.createdAt).toLocaleString() }}</span><span class="log-row__level" :class="`log-row__level--${log.level}`">{{ log.level }}</span><span class="log-row__message">{{ log.eventType || 'agent.event' }} · {{ log.message }}</span></div></div>
          <div v-else class="tab-empty"><Activity :size="23" />暂无运行日志</div>
        </div>

        <div v-else-if="activeTab === 'capabilities'" class="tab-content">
          <div class="tab-content__heading"><div><span class="eyebrow">CONNECTED SKILLS</span><h3>智能体能力</h3><p>{{ selectedAgent.name }} 可以使用的工具与技能</p></div><span class="tab-count">{{ selectedAgent.capabilities.length }} 项能力</span></div>
          <div v-if="selectedAgent.capabilities.length" class="capability-grid"><div v-for="capability in selectedAgent.capabilities" :key="capability.title" class="capability-card" :class="`capability-card--${capability.tone}`"><span class="capability-card__icon"><component :is="capabilityIcons[capability.icon]" :size="21" /></span><div><h4>{{ capability.title }}</h4><p>{{ capability.description }}</p></div><CheckCircle2 :size="16" class="capability-card__check" /></div></div>
          <div v-else class="tab-empty"><Sparkles :size="23" />尚未连接能力</div>
        </div>

        <div v-else-if="activeTab === 'api'" class="tab-content">
          <div class="tab-content__heading"><div><span class="eyebrow">API ACTIVITY</span><h3>API 调用</h3><p>最近的请求与响应状态</p></div><span class="tab-count">今日 {{ selectedAgent.callsToday }} 次调用</span></div>
          <div class="api-summary"><div><span class="api-summary__icon"><Send :size="18" /></span><span>今日调用</span><strong>{{ selectedAgent.callsToday }}</strong></div><div><span class="api-summary__icon api-summary__icon--mint"><CheckCircle2 :size="18" /></span><span>任务完成率</span><strong>{{ selectedAgent.successRate }}</strong></div></div>
          <div v-if="selectedAgent.apiCalls.length" class="api-list"><div class="api-list__header"><span>请求</span><span>时间</span><span>耗时</span><span>状态</span><span /></div><div v-for="(call, index) in selectedAgent.apiCalls" :key="`${call.endpoint}-${index}`" class="api-row"><span class="api-row__request"><b :class="`api-row__method--${call.method.toLowerCase()}`">{{ call.method }}</b><code>{{ call.endpoint }}</code></span><span>{{ call.time }}</span><span>{{ call.duration }}</span><span class="api-row__success">{{ call.status }} OK</span><button type="button" :aria-label="`复制 ${call.endpoint}`" @click="copyApiPath(call.endpoint)"><Copy :size="14" /></button></div></div>
          <div v-else class="tab-empty"><Code2 :size="23" />暂无 API 调用</div>
        </div>

        <div v-else class="tab-content">
          <div class="tab-content__heading"><div><span class="eyebrow">USAGE INSIGHTS</span><h3>使用情况</h3><p>了解智能体的工作节奏与资源使用</p></div><span class="tab-count">最近 7 天</span></div>
          <div class="usage-summary"><div><span>今日任务</span><strong>{{ selectedAgent.tasksToday }}</strong><small>个任务</small></div><div><span>API 调用</span><strong>{{ selectedAgent.callsToday }}</strong><small>次请求</small></div><div><span>任务完成率</span><strong>{{ selectedAgent.successRate }}</strong><small>所有任务</small></div></div>
          <div class="usage-chart"><div class="usage-chart__heading"><strong>任务活跃度</strong><span>过去一周</span></div><div class="usage-chart__bars"><div v-for="day in activityByDay" :key="day.label" class="usage-chart__bar"><span :style="{ height: `${Math.max(5, Math.min(100, day.count * 22))}%` }" :title="`${day.count} 个任务`" /><small>{{ day.label }}</small></div></div></div>
        </div>
      </GlassCard>
      <div v-else class="agent-state">选择或创建一个智能体，开始管理任务。</div>
    </div>

    <div v-if="createAgentOpen || createTaskOpen" class="agents-modal-backdrop" @click.self="createAgentOpen = false; createTaskOpen = false">
      <form class="agents-modal" role="dialog" aria-modal="true" aria-label="智能体或任务" @keydown.esc="createAgentOpen = false; createTaskOpen = false" @submit.prevent="createAgentOpen ? saveAgent() : createTask()">
        <div class="agents-modal__head"><span class="agents-modal__icon"><Bot v-if="createAgentOpen" :size="21" /><Zap v-else :size="21" /></span><button type="button" aria-label="关闭" @click="createAgentOpen = false; createTaskOpen = false"><X :size="18" /></button></div>
        <h2>{{ createAgentOpen ? agentDialogMode === 'edit' ? '编辑智能体' : '添加智能体' : '创建新任务' }}</h2>
        <p>{{ createAgentOpen ? '保存智能体资料，运行连接可稍后接入。' : `将任务加入 ${selectedAgent?.name ?? '智能体'} 的队列。` }}</p>
        <template v-if="createAgentOpen"><label>名称<input v-model="newAgentName" autofocus maxlength="32" placeholder="例如：Nova" required /></label><label>角色<input v-model="newAgentRole" maxlength="48" placeholder="例如：写作助理" /></label><label>模型标识<input v-model="newAgentModel" maxlength="120" placeholder="例如：本地模型" /></label><label>简介<input v-model="newAgentDescription" maxlength="500" placeholder="这个智能体负责什么" /></label>
          <fieldset class="data-scopes"><legend>数据访问权限</legend>
            <div v-for="domain in scopeDomains" :key="domain.id" class="data-scopes__row">
              <strong>{{ domain.label }}</strong>
              <label v-for="effect in scopeEffects" :key="effect.id" :class="{ 'data-scopes__delete': effect.id === 'delete' }">
                <input v-model="newAgentScopes" type="checkbox" :value="`${domain.id}:${effect.id}`" />{{ effect.label }}
              </label>
            </div>
            <small>{{ newAgentScopes.length ? '保存后立即生效，无需重新生成 Token。删除权限需单独开启。' : '无数据权限。默认全部关闭，请按需授权。' }}</small>
          </fieldset>
        </template>
        <template v-else><label>任务名称<input v-model="newTaskTitle" autofocus maxlength="80" placeholder="例如：整理本周市场动态" required /></label><label>任务说明<input v-model="newTaskDescription" maxlength="500" placeholder="补充任务内容" /></label></template>
        <p v-if="formError" class="agent-form-error" role="alert">{{ formError }}</p>
        <div class="agents-modal__actions"><ActionButton variant="secondary" type="button" :disabled="saving" @click="createAgentOpen = false; createTaskOpen = false">取消</ActionButton><ActionButton type="submit" :disabled="saving"><Plus :size="15" />{{ saving ? '保存中…' : createAgentOpen ? agentDialogMode === 'edit' ? '保存修改' : '添加智能体' : '创建任务' }}</ActionButton></div>
      </form>
    </div>
    <Transition name="agent-toast"><div v-if="toast" class="agents-toast" role="status"><CheckCircle2 :size="17" />{{ toast }}</div></Transition>
  </div>
</template>

<style scoped>
.runtime-token-panel { display:flex; flex-wrap:wrap; align-items:center; gap:9px; margin:15px 0; padding:12px; border:1px solid var(--agent-tile-border); border-radius:12px; background:var(--agent-tile-bg); color:#435570; font-size:11px; }
.runtime-token-panel code { max-width:100%; overflow-wrap:anywhere; }
.runtime-token-panel button { padding:5px 9px; border:1px solid rgba(145,169,216,.4); border-radius:7px; background:rgba(243,246,255,.65); color:#435570; cursor:pointer; }
.agents-page { width:100%; min-width:0; padding-bottom:28px; color:#263653; --agent-tile-bg:var(--glass-tile-background); --agent-tile-border:rgba(255,255,255,.68); --agent-tile-shadow:var(--glass-tile-shadow); }
.agent-state { display:flex; align-items:center; justify-content:center; gap:10px; min-height:220px; padding:28px; border:1px solid rgba(255,255,255,.55); border-radius:18px; background:rgba(218,229,255,.3); color:white; font-size:13px; text-align:center; }
.agent-state button { padding:6px 11px; border:1px solid rgba(255,255,255,.55); border-radius:8px; background:rgba(255,255,255,.25); color:white; }
.visually-hidden { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
.agents-page-actions { display:flex; justify-content:flex-end; align-items:center; gap:8px; min-height:31px; margin-bottom:14px; }
.agents-stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; margin-bottom:14px; }
.agents-workspace { display:grid; grid-template-columns:minmax(270px,302px) minmax(0,1fr); align-items:stretch; gap:18px; }
.agent-directory { min-height:640px; }
.agents-workspace > .agent-state { min-height:640px; }
.directory-count,.tab-count { display:inline-flex; align-items:center; min-height:26px; padding:5px 10px; border:1px solid rgba(255,255,255,.35); border-radius:999px; background:rgba(235,241,255,.2); color:#fff; font-size:10px; font-weight:700; white-space:nowrap; text-shadow:0 1px 8px rgba(25,38,76,.28); }
.agent-search { display:flex; align-items:center; gap:9px; height:38px; padding:0 11px; border:1px solid var(--agent-tile-border); border-radius:11px; background:rgba(255,255,255,.78); color:#52678c; box-shadow:var(--agent-tile-shadow); }
.agent-search:focus-within { border-color:#96a9ec; box-shadow:0 0 0 3px rgba(119,145,236,.12); }
.agent-search input { width:100%; min-width:0; border:0; outline:0; background:none; color:#344664; font-size:11px; }
.agent-search input::placeholder { color:#6c7e9a; }
.agent-search__shortcut { flex:none; padding:3px 5px; border:1px solid #e1e7f1; border-radius:5px; color:#a4afc0; background:#f7f9fd; font-size:9px; line-height:1; }
.directory-filters { display:flex; gap:5px; margin:14px 0 13px; overflow-x:auto; scrollbar-width:none; }
.directory-filters::-webkit-scrollbar { display:none; }
.directory-filters button,.task-filters button { flex:none; padding:7px 10px; border:0; border-radius:8px; background:transparent; color:rgba(255,255,255,.84); font-size:10px; font-weight:650; white-space:nowrap; text-shadow:0 1px 8px rgba(25,38,76,.3); }
.directory-filters button:hover,.task-filters button:hover { color:#fff; background:rgba(230,237,252,.2); }
.directory-filters button.active,.task-filters button.active { color:#36569e; background:rgba(235,241,255,.72); box-shadow:inset 0 0 0 1px rgba(219,228,255,.68); text-shadow:none; }
.directory-list { display:grid; gap:9px; }
.agent-avatar { display:grid; flex:none; place-items:center; border:1px solid rgba(255,255,255,.46); color:white; box-shadow:inset 0 1px 0 rgba(255,255,255,.4),0 6px 12px rgba(102,119,171,.18); }
.agent-avatar--small { width:37px; height:37px; border-radius:12px; }
.agent-avatar--large { width:62px; height:62px; border-radius:19px; box-shadow:inset 0 1px 0 rgba(255,255,255,.4),0 12px 27px rgba(96,111,179,.22); }
.agent-avatar--spark { background:linear-gradient(145deg,#8da7fc,#9776e5); }
.agent-avatar--orbit { background:linear-gradient(145deg,#69b9dc,#6288df); }
.agent-avatar--wave { background:linear-gradient(145deg,#bd91ee,#8e7ce1); }
.agent-avatar--chart { background:linear-gradient(145deg,#78d8c6,#59afa7); }
.agent-avatar--sun { background:linear-gradient(145deg,#f3c88a,#e6a576); }
.directory-item__meta { display:flex; align-items:center; gap:5px; overflow:hidden; color:#586780; font-size:9px; white-space:nowrap; }
.directory-item__dot { width:6px; height:6px; flex:none; border-radius:50%; background:#b8c1cf; }
.directory-item__dot--running { background:#3aba9d; box-shadow:0 0 0 3px rgba(58,186,157,.13); }
.directory-item__dot--idle { background:#e5b15e; box-shadow:0 0 0 3px rgba(229,177,94,.15); }
.directory-item__separator { color:#bfc7d3; }
.directory-item__chevron { color:#a8b4c6; }
.directory-add { display:flex; align-items:center; justify-content:center; gap:7px; width:100%; min-height:38px; margin-top:13px; border:1px dashed rgba(255,255,255,.48); border-radius:12px; background:rgba(235,241,255,.18); color:#fff; font-size:11px; font-weight:690; text-shadow:0 1px 8px rgba(25,38,76,.3); }
.directory-add:hover { background:rgba(235,241,255,.28); border-color:rgba(255,255,255,.7); }
.directory-empty,.tab-empty { display:flex; flex-direction:column; align-items:center; justify-content:center; gap:9px; min-height:160px; color:rgba(255,255,255,.8); font-size:11px; text-shadow:0 1px 8px rgba(25,38,76,.3); }
.agent-profile { min-height:640px; padding:0 !important; border-radius:var(--radius-card) !important; background:var(--glass-card-background) !important; color:#263653; }
.agent-profile :deep(.glass-card__body) { overflow:visible; padding:0; }
.profile-hero { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:24px 25px 22px; }
.profile-identity { display:flex; align-items:center; gap:16px; min-width:0; }
.profile-identity__copy { min-width:0; }
.profile-title-row { display:flex; align-items:center; gap:11px; }
.profile-title-row h2 { margin:0; color:#fff; font-size:22px; font-weight:740; letter-spacing:-.045em; text-shadow:0 1px 10px rgba(25,38,76,.3); }
.profile-role { display:flex; align-items:center; gap:7px; margin:5px 0 0; color:rgba(255,255,255,.84); font-size:10px; font-weight:610; text-shadow:0 1px 8px rgba(25,38,76,.3); }
.profile-role span { color:rgba(255,255,255,.64); }
.profile-description { margin:8px 0 0; color:rgba(255,255,255,.76); font-size:11px; line-height:1.5; text-shadow:0 1px 8px rgba(25,38,76,.3); }
.profile-actions { display:flex; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:8px; flex:none; max-width:280px; }
.profile-tabs { display:flex; align-items:stretch; gap:4px; margin:0 25px; border-bottom:1px solid rgba(255,255,255,.3); overflow-x:auto; scrollbar-width:none; }
.profile-tabs::-webkit-scrollbar { display:none; }
.profile-tabs button { position:relative; flex:none; min-height:45px; padding:0 14px; border:0; background:transparent; color:rgba(255,255,255,.72); font-size:11px; font-weight:660; white-space:nowrap; text-shadow:0 1px 8px rgba(25,38,76,.3); }
.profile-tabs button:hover { color:#fff; }
.profile-tabs button.active { color:#fff; }
.profile-tabs button.active::after { position:absolute; right:9px; bottom:0; left:9px; height:3px; border-radius:3px 3px 0 0; background:linear-gradient(90deg,#7190ef,#a389eb); content:''; }
.overview-tab,.tab-content { padding:25px; }
.overview-heading,.tab-content__heading { display:flex; align-items:flex-end; justify-content:space-between; gap:12px; margin-bottom:17px; }
.eyebrow { color:rgba(255,255,255,.65); font-size:9px; font-weight:740; letter-spacing:.15em; text-shadow:0 1px 8px rgba(25,38,76,.3); }
.overview-heading h3,.tab-content__heading h3 { margin:5px 0 0; color:#fff; font-size:19px; font-weight:730; letter-spacing:-.025em; text-shadow:0 1px 10px rgba(25,38,76,.3); }
.tab-content__heading p { margin:5px 0 0; color:rgba(255,255,255,.76); font-size:11px; text-shadow:0 1px 8px rgba(25,38,76,.3); }
.overview-heading__date { display:flex; align-items:center; gap:7px; padding-bottom:2px; color:rgba(255,255,255,.75); font-size:10px; text-shadow:0 1px 8px rgba(25,38,76,.3); }
.live-dot { width:7px; height:7px; border-radius:50%; background:#49c3a4; box-shadow:0 0 0 4px rgba(73,195,164,.15); }
.overview-top-grid { display:grid; grid-template-columns:minmax(0,1.25fr) minmax(225px,.85fr); gap:13px; }
.focus-task { position:relative; display:flex; flex-direction:column; min-height:190px; overflow:hidden; padding:20px 22px; border:1px solid rgba(255,255,255,.56); border-radius:20px; color:#fff; background:linear-gradient(125deg,rgba(93,113,214,.62),rgba(120,96,207,.53) 55%,rgba(157,106,202,.46)); box-shadow:0 12px 24px rgba(47,46,122,.18),inset 0 1px 0 rgba(255,255,255,.28); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); text-shadow:0 1px 8px rgba(24,28,74,.35); }
.focus-task::after { position:absolute; top:-92px; right:-40px; width:280px; height:240px; border:1px solid rgba(255,255,255,.2); border-radius:50%; box-shadow:0 0 0 29px rgba(255,255,255,.045),0 0 0 62px rgba(255,255,255,.035); content:''; }
.focus-task__top,.focus-task__bottom { position:relative; z-index:1; display:flex; align-items:center; gap:9px; }
.focus-task__top { color:rgba(255,255,255,.86); font-size:10px; font-weight:690; }
.focus-task__icon { display:grid; width:27px; height:27px; place-items:center; border-radius:9px; background:rgba(255,255,255,.22); }
.focus-task__more { margin-left:auto; opacity:.75; }
.focus-task h4 { position:relative; z-index:1; margin:20px 0 5px; font-size:18px; font-weight:740; letter-spacing:-.025em; }
.focus-task p { position:relative; z-index:1; margin:0; color:rgba(255,255,255,.76); font-size:10px; }
.focus-task__bottom { justify-content:space-between; margin-top:auto; padding-top:19px; }
.focus-progress { display:flex; gap:4px; }
.focus-progress i { width:22px; height:4px; border-radius:10px; background:#fff; }
.focus-progress i.dim { background:rgba(255,255,255,.31); }
.focus-task__bottom button { display:flex; align-items:center; gap:5px; border:0; background:none; color:white; font-size:10px; font-weight:700; }
.health-panel { min-height:190px; padding:19px; border:1px solid var(--agent-tile-border); border-radius:15px; background:var(--agent-tile-bg); box-shadow:var(--agent-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); }
.health-panel__title { display:flex; align-items:center; gap:10px; padding-bottom:15px; border-bottom:1px solid #e7edf6; }
.health-panel__pulse { display:grid; width:35px; height:35px; place-items:center; border-radius:11px; background:#e4f8f2; color:#37aa8f; }
.health-panel__title h4 { margin:0; color:#31415e; font-size:12px; font-weight:730; }
.health-panel__title p { margin:3px 0 0; color:#55647d; font-size:9px; }
.health-panel__rows { display:grid; gap:10px; padding-top:14px; }
.health-panel__rows > div { display:flex; align-items:center; justify-content:space-between; gap:9px; min-height:19px; }
.health-panel__rows > div > span:first-child { color:#53627d; font-size:10px; }
.health-panel__rows strong { color:#3d4e68; font-size:11px; font-weight:720; }
.health-panel__rows strong { min-width:0; overflow-wrap:anywhere; text-align:right; }
.overview-bottom-grid { display:grid; grid-template-columns:minmax(0,1.25fr) minmax(225px,.85fr); gap:13px; margin-top:13px; }
.overview-section { min-height:230px; padding:18px !important; border-color:var(--agent-tile-border) !important; border-radius:15px !important; box-shadow:var(--agent-tile-shadow) !important; background:var(--agent-tile-bg) !important; }
.overview-section :deep(.section-container__heading) { margin-bottom:12px; }
.overview-section :deep(.section-container__heading h2) { color:#293a58; font-size:13px; text-shadow:none; }
.text-link { display:inline-flex; align-items:center; gap:3px; border:0; background:none; color:#6e86d8; font-size:10px; font-weight:680; white-space:nowrap; }
.recent-tasks { display:grid; }
.recent-task { display:flex; align-items:center; gap:9px; min-height:50px; border-top:1px solid #e8edf6; }
.recent-task__icon { display:grid; width:27px; height:27px; flex:none; place-items:center; border-radius:9px; background:#e5f6ee; color:#39a98d; }
.recent-task__icon--queued { background:#fff3de; color:#d4a45c; }
.recent-task__copy { display:flex; flex-direction:column; gap:3px; min-width:0; }
.recent-task__copy strong { overflow:hidden; color:#44536c; font-size:10px; font-weight:690; text-overflow:ellipsis; white-space:nowrap; }
.recent-task__copy small { overflow:hidden; color:#596882; font-size:9px; text-overflow:ellipsis; white-space:nowrap; }
.recent-task__time { margin-left:auto; color:#596882; font-size:9px; white-space:nowrap; }
.capabilities-mini { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
.capability-mini { display:flex; align-items:center; gap:7px; min-height:50px; padding:9px; border:1px solid rgba(255,255,255,.48); border-radius:11px; background:rgba(250,252,255,.26); }
.capability-mini span { display:grid; width:28px; height:28px; flex:none; place-items:center; border-radius:8px; background:var(--cap-bg); color:var(--cap-fg); }
.capability-mini strong { overflow:hidden; color:#53617a; font-size:9px; font-weight:690; text-overflow:ellipsis; white-space:nowrap; }
.capability-mini--blue,.capability-card--blue { --cap-bg:#e9f0ff; --cap-fg:#6f8be0; }
.capability-mini--violet,.capability-card--violet { --cap-bg:#f0eaff; --cap-fg:#9a79d6; }
.capability-mini--mint,.capability-card--mint { --cap-bg:#e5f7f1; --cap-fg:#49ae91; }
.capability-mini--amber,.capability-card--amber { --cap-bg:#fff3e4; --cap-fg:#d9a15a; }
.content-empty { padding:20px 0; color:#52627d; font-size:11px; line-height:1.5; }
.tab-content { min-height:445px; }
.task-filters { display:flex; align-items:center; gap:4px; margin:2px 0 15px; padding:8px; border:1px solid var(--agent-tile-border); border-radius:12px; background:var(--agent-tile-bg); color:#53627d; box-shadow:var(--agent-tile-shadow); }
.task-filters svg { margin:0 7px 0 4px; }
.task-filters button { color:#53627d; text-shadow:none; }
.task-filters button:hover { color:#3553a3; background:rgba(230,237,252,.45); }
.full-task-list { overflow:hidden; border:1px solid var(--agent-tile-border); border-radius:15px; background:var(--agent-tile-bg); box-shadow:var(--agent-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); }
.full-task { display:flex; align-items:center; flex-wrap:wrap; gap:12px; min-height:71px; padding:13px 16px; border-bottom:1px solid #e8edf6; }
.task-actions { display:flex; justify-content:flex-end; gap:7px; width:100%; }
.task-actions button { padding:5px 8px; border:1px solid rgba(124,148,205,.28); border-radius:7px; background:rgba(237,243,255,.75); color:#4b64a4; font-size:10px; cursor:pointer; }
.task-actions button:hover { background:#dfe9ff; }
.full-task:last-child { border-bottom:0; }
.full-task__symbol { display:grid; width:34px; height:34px; flex:none; place-items:center; border-radius:10px; background:#ebf0ff; color:#6d86db; }
.full-task__symbol--completed { background:#e6f7f0; color:#39ad8a; }
.full-task__symbol--queued { background:#fff5e6; color:#d9a45d; }
.full-task__copy { display:flex; flex:1; flex-direction:column; gap:5px; min-width:0; }
.full-task__copy strong { overflow:hidden; color:#3b4d69; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }
.full-task__copy span,.full-task__id,.full-task time { color:#596882; font-size:9px; white-space:nowrap; }
.full-task__copy .full-task__detail { white-space:normal; overflow-wrap:anywhere; line-height:1.5; }
.full-task__id { width:62px; }
.full-task time { width:74px; text-align:right; }
.log-list { overflow:hidden; border:1px solid var(--agent-tile-border); border-radius:15px; background:var(--agent-tile-bg); box-shadow:var(--agent-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); }
.log-row { display:grid; grid-template-columns:120px 54px minmax(0,1fr); align-items:center; gap:13px; min-height:57px; padding:12px 17px; border-bottom:1px solid #e8eef7; }
.log-row:last-child { border-bottom:0; }
.log-row__time { color:#596882; font-size:10px; font-variant-numeric:tabular-nums; }
.log-row__level { width:39px; padding:4px; border-radius:5px; background:#eaf0ff; color:#6884d7; font-size:9px; font-weight:700; text-align:center; }
.log-row__level--success { background:#e4f6ee; color:#3aa885; }
.log-row__level--warning { background:#fff3df; color:#c9994b; }
.log-row__message { color:#52617b; font-size:11px; }
.capability-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:13px; }
.capability-card { display:flex; align-items:flex-start; gap:13px; min-height:108px; padding:17px; border:1px solid var(--agent-tile-border); border-radius:15px; background:var(--agent-tile-bg); box-shadow:var(--agent-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); }
.capability-card__icon { display:grid; width:40px; height:40px; flex:none; place-items:center; border-radius:11px; color:var(--cap-fg); background:var(--cap-bg); }
.capability-card h4 { margin:3px 0 5px; color:#3c4c66; font-size:12px; }
.capability-card p { margin:0; color:#596882; font-size:10px; line-height:1.5; }
.capability-card__check { flex:none; margin-left:auto; color:#a7cdbb; }
.api-summary { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-bottom:17px; }
.api-summary > div { display:flex; align-items:center; gap:11px; min-height:77px; padding:15px; border:1px solid var(--agent-tile-border); border-radius:14px; background:var(--agent-tile-bg); box-shadow:var(--agent-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); }
.api-summary__icon { display:grid; width:36px; height:36px; place-items:center; border-radius:11px; background:#e9efff; color:#6e87dd; }
.api-summary__icon--mint { background:#e3f6ed; color:#43ad89; }
.api-summary > div > span:nth-child(2) { color:#52627d; font-size:10px; }
.api-summary strong { margin-left:auto; color:#334765; font-size:22px; letter-spacing:-.04em; }
.api-list { overflow-x:auto; border:1px solid var(--agent-tile-border); border-radius:14px; background:var(--agent-tile-bg); box-shadow:var(--agent-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); }
.api-list__header,.api-row { display:grid; grid-template-columns:minmax(180px,1fr) 70px 55px 62px 22px; align-items:center; gap:9px; min-width:520px; padding:0 15px; }
.api-list__header { min-height:35px; border-bottom:1px solid rgba(255,255,255,.32); color:#52627d; background:rgba(243,247,254,.24); font-size:9px; font-weight:690; }
.api-row { min-height:54px; border-bottom:1px solid rgba(255,255,255,.28); color:#596882; font-size:9px; }
.api-row:last-child { border-bottom:0; }
.api-row__request { display:flex; align-items:center; gap:9px; min-width:0; }
.api-row__request b { min-width:37px; padding:5px 4px; border-radius:5px; color:#5e80c6; background:#e8efff; font-size:8px; text-align:center; }
.api-row__request b.api-row__method--post { color:#9774d1; background:#f0eaff; }
.api-row__request b.api-row__method--patch { color:#c49555; background:#fff1df; }
.api-row__request code { overflow:hidden; color:#435570; font-size:9px; text-overflow:ellipsis; white-space:nowrap; }
.api-row__success { color:#3ba884; font-weight:690; }
.api-row button { display:grid; width:22px; height:22px; place-items:center; border:0; border-radius:6px; background:transparent; color:#9facbe; }
.api-row button:hover { background:#edf2ff; color:#6682d9; }
.usage-summary { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.usage-summary > div { display:flex; flex-direction:column; gap:8px; min-height:105px; padding:17px; border:1px solid var(--agent-tile-border); border-radius:15px; background:var(--agent-tile-bg); box-shadow:var(--agent-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); }
.usage-summary span { color:#52627d; font-size:10px; }
.usage-summary strong { color:#364a68; font-size:26px; line-height:1; letter-spacing:-.04em; }
.usage-summary small { color:#596882; font-size:9px; }
.usage-chart { margin-top:16px; padding:19px; border:1px solid var(--agent-tile-border); border-radius:15px; background:var(--agent-tile-bg); box-shadow:var(--agent-tile-shadow); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px); }
.usage-chart__heading { display:flex; justify-content:space-between; color:#394b68; font-size:11px; }
.usage-chart__heading span { color:#596882; font-size:10px; }
.usage-chart__bars { display:grid; grid-template-columns:repeat(7,1fr); gap:14px; height:188px; padding-top:15px; }
.usage-chart__bar { display:flex; flex-direction:column; align-items:center; justify-content:flex-end; gap:9px; min-width:0; }
.usage-chart__bar span { width:min(100%,35px); min-height:10px; border-radius:8px 8px 3px 3px; background:linear-gradient(180deg,#8294ed,#a294ea); box-shadow:0 6px 13px rgba(118,133,220,.19); }
.usage-chart__bar:nth-child(2n) span { background:linear-gradient(180deg,#90aaf2,#81c6e8); }
.usage-chart__bar small { flex:none; color:#596882; font-size:9px; }
.agents-modal-backdrop { position:fixed; z-index:100; inset:0; display:grid; place-items:center; padding:16px; background:rgba(30,43,79,.36); backdrop-filter:blur(8px); }
.agents-modal { width:min(100%,410px); padding:24px; border:1px solid rgba(255,255,255,.86); border-radius:23px; background:var(--glass-dialog-background); box-shadow:0 25px 80px rgba(37,51,95,.28);  backdrop-filter:var(--glass-overlay-filter); -webkit-backdrop-filter:var(--glass-overlay-filter); }
.agents-modal__head { display:flex; align-items:center; justify-content:space-between; }
.agents-modal__icon { display:grid; width:42px; height:42px; place-items:center; border-radius:13px; color:#6c81da; background:#e7edff; }
.agents-modal__head button { display:grid; width:28px; height:28px; place-items:center; border:0; border-radius:8px; color:#94a2b7; background:transparent; }
.agents-modal__head button:hover { background:#e8eefb; }
.agents-modal h2 { margin:16px 0 5px; color:#2d3e5e; font-size:20px; }
.agents-modal p { margin:0 0 23px; color:#8795aa; font-size:11px; }
.agents-modal label { display:block; margin-bottom:14px; color:#647590; font-size:11px; font-weight:700; }
.agents-modal input { display:block; width:100%; height:41px; margin-top:7px; padding:0 12px; border:1px solid #d9e2f2; border-radius:11px; outline:0; background:rgba(255,255,255,.55); color:#344664; font-size:12px; }
.agents-modal input:focus { border-color:#98aaeb; box-shadow:0 0 0 3px rgba(133,154,235,.13); }
.agents-modal input::placeholder { color:#aeb9c8; }
.agents-modal__actions { display:flex; justify-content:flex-end; gap:8px; margin-top:23px; }
.agents-modal { max-height:90vh; overflow-y:auto; }
.data-scopes { margin:14px 0; padding:12px; border:1px solid #d9e2f2; border-radius:11px; color:#344664; }
.data-scopes legend { font-size:12px; font-weight:700; }
.data-scopes__row { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin:10px 0; }
.data-scopes__row strong { width:100%; font-size:11px; }
.data-scopes__row label { display:flex; align-items:center; gap:4px; margin:0; font-weight:400; }
.data-scopes__row input { width:14px; height:14px; margin:0; padding:0; }
.data-scopes__delete { color:#b43f55 !important; }
.data-scopes small { font-size:10px; line-height:1.5; }
.agent-form-error { margin:0; color:#bd4560; font-size:11px; }
.agents-toast { position:fixed; z-index:110; right:27px; bottom:25px; display:flex; align-items:center; gap:9px; padding:11px 15px; border:1px solid rgba(255,255,255,.5); border-radius:13px; background:rgba(49,69,112,.9); color:white; box-shadow:0 12px 35px rgba(32,44,81,.22); backdrop-filter:blur(18px); font-size:11px; font-weight:660; }
.agents-toast svg { color:#8ee1be; }
.agent-toast-enter-active,.agent-toast-leave-active { transition:opacity .2s,transform .2s; }
.agent-toast-enter-from,.agent-toast-leave-to { opacity:0; transform:translateY(8px); }
@media (max-width:1220px) { .agents-workspace { grid-template-columns:265px minmax(0,1fr); gap:14px; } .overview-top-grid,.overview-bottom-grid { grid-template-columns:minmax(0,1fr) minmax(205px,.8fr); } .profile-actions { flex-direction:column; align-items:stretch; } }
@media (max-width:1030px) { .agents-stats { grid-template-columns:repeat(2,minmax(0,1fr)); } .agents-workspace { grid-template-columns:1fr; } .agent-directory,.agents-workspace > .agent-state { min-height:0; } .directory-list { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:700px) { .agents-stats { gap:9px; } .agents-workspace { gap:12px; } .directory-list { grid-template-columns:1fr; } .profile-hero { align-items:flex-start; flex-direction:column; padding:20px; } .profile-actions { flex-direction:row; } .profile-tabs { margin:0 14px; } .overview-tab,.tab-content { padding:18px; } .overview-top-grid,.overview-bottom-grid,.capability-grid { grid-template-columns:1fr; } .overview-bottom-grid { margin-top:12px; } .full-task__id,.full-task time { display:none; } .api-summary,.usage-summary { gap:8px; } .api-summary strong { font-size:18px; } }
@media (max-width:440px) { .agents-stats { grid-template-columns:1fr 1fr; } .profile-identity { align-items:flex-start; gap:11px; } .agent-avatar--large { width:52px; height:52px; } .profile-title-row { flex-wrap:wrap; gap:6px; } .profile-description { font-size:10px; } .focus-task { min-height:184px; } .usage-summary { grid-template-columns:1fr; } }
</style>
