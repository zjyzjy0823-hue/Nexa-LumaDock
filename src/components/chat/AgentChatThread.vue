<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch, watchEffect } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useDataStore } from '../../stores/data'
import { sessionKey as buildSessionKey, useFleetStore } from '../../stores/fleet'
import { useWebsitesStore } from '../../stores/websites'
import {
  createPastedTextBlock,
  extractMessageParts,
  fuzzyMatchFileScore,
  isQuotaOrModelError,
  shouldConvertToPastedBlock,
} from '../../services/chatHelpers'
import {
  buildTurnRenderItems,
  collectMessageInlineAttachments,
  splitTextByInlineMedia,
} from '../../services/messageSegments'
import {
  deleteCustomPrompt,
  loadCustomPrompts,
  saveCustomPrompt,
  type CustomPromptTemplate,
} from '../../services/customPrompts'
import { formatTokenCount } from '../../services/tokenUsage'
import type {
  ApprovalDecision,
  ArtifactRef,
  ChatMessage,
  ComposerMode,
  FleetModel,
  PastedTextBlock,
  ToolCallBadge,
} from '../../types/fleet'
import OpusIcon from '../ui/OpusIcon.vue'
import ChangedFilesSummaryBar from './ChangedFilesSummaryBar.vue'
import FormQuestionCard from './FormQuestionCard.vue'
import InlineAttachmentCard from './InlineAttachmentCard.vue'
import MarkdownMessage from './MarkdownMessage.vue'
import MessageRail from './MessageRail.vue'
import PermissionRequestCard from './PermissionRequestCard.vue'
import PromptLibraryModal from './PromptLibraryModal.vue'
import SessionTodoBar from './SessionTodoBar.vue'
import ToolCallCard from './ToolCallCard.vue'
import ToolRunGroup from './ToolRunGroup.vue'
import { formatBytes, getProviderMeta, type OpusIconName } from './providerMeta'
import { useWorkbenchTheme } from '../../composables/useWorkbenchTheme'

const props = defineProps<{
  mobile?: boolean
  compact?: boolean
  sessionKey?: string
}>()

const emit = defineEmits<{
  action: [message: string]
  openHandoff: [payload: { summary: string; artifact?: ArtifactRef }]
  openDiff: [focusFile?: string]
  openFile: [path: string, line?: number]
  openSubagent: [sessionId: string]
  openSideChat: [question?: string]
  clearSession: []
}>()

const auth = useAuthStore()
const dataStore = useDataStore()
const websitesStore = useWebsitesStore()
const fleet = useFleetStore()
const { bubbleStyle } = useWorkbenchTheme()
const sending = ref(false)
const draggingFiles = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const listEl = ref<HTMLElement | null>(null)
const innerListEl = ref<HTMLElement | null>(null)
const expandedThought = ref<Record<string, boolean>>({})

const effectiveKey = computed(() => props.sessionKey || fleet.activeSessionKey)
const effectiveSession = computed(() =>
  effectiveKey.value ? fleet.sessionsByKey[effectiveKey.value] ?? null : null,
)
const effectiveNode = computed(
  () =>
    (effectiveSession.value ? fleet.nodes.find(n => n.id === effectiveSession.value!.nodeId) : null) ??
    fleet.selectedNode,
)
const effectiveProvider = computed(() => effectiveSession.value?.provider ?? fleet.selectedProvider)
const settingsId = useId()
const settingsPopup = ref<HTMLElement>()
const settingsTrigger = ref<HTMLButtonElement>()
const modelTriggerRef = ref<HTMLButtonElement>()
const settingsOpen = ref(false)
const draftMeasure = ref<HTMLElement>()
const editorHeight = ref<number>()
const followLatest = ref(true)
const panel = ref<'model' | 'permissions' | 'attach'>('model')
const adapter = computed(() => effectiveNode.value?.adapters.find(a => a.provider === effectiveProvider.value))
const caps = computed(() => adapter.value?.capabilities ?? [])
const target = computed(() => `${effectiveNode.value?.id}::${effectiveProvider.value}`)
const catalog = computed(() => fleet.catalogs[target.value])
const mcpList = computed(() => fleet.mcpByTarget[target.value] ?? [])
const mcpConnectedCount = computed(() => mcpList.value.filter(s => s.status === 'connected' || s.status === 'ready').length)
const rulesList = computed(
  () => (effectiveKey.value ? fleet.rulesByTarget[effectiveKey.value] : undefined) ?? fleet.rulesByTarget[target.value] ?? [],
)
const skillsList = computed(
  () => (effectiveKey.value ? fleet.skillsByTarget[effectiveKey.value] : undefined) ?? fleet.skillsByTarget[target.value] ?? [],
)
const composerMode = computed<ComposerMode>(() =>
  (effectiveKey.value ? fleet.composerModeBySession[effectiveKey.value] : undefined) ?? 'build',
)
const isInterrupted = computed(() =>
  Boolean(effectiveKey.value && fleet.interruptedBySession[effectiveKey.value]),
)
const firstUnreadMsgId = computed(() =>
  effectiveKey.value ? fleet.firstUnreadMsgIdBySession[effectiveKey.value] ?? null : null,
)
const unseenBelowCount = ref(0)
const jumpBtnRef = ref<HTMLButtonElement | null>(null)
const pastedBlocksByKey = ref<Record<string, PastedTextBlock[]>>({})
const queuedPastedBlocks = computed(() => pastedBlocksByKey.value[settingsKey.value] ?? [])
const previewingPasteBlock = ref<PastedTextBlock | null>(null)

// 划词引用浮层状态（Selection Quote）
const selectionQuote = ref<{ text: string; top: number; left: number } | null>(null)
const threadRootRef = ref<HTMLElement | null>(null)

function setMode(next: ComposerMode) {
  const key = settingsKey.value
  if (key) fleet.setComposerMode(key, next)
}

function handleMessageSelection() {
  if (props.mobile || typeof window === 'undefined') {
    selectionQuote.value = null
    return
  }
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed || !listEl.value || !threadRootRef.value) {
    selectionQuote.value = null
    return
  }
  const txt = sel.toString().trim()
  if (txt.length < 4 || txt.length > 1200) {
    selectionQuote.value = null
    return
  }
  const anchorNode = sel.anchorNode
  const focusNode = sel.focusNode
  if (
    !anchorNode || !focusNode ||
    !listEl.value.contains(anchorNode) || !listEl.value.contains(focusNode)
  ) {
    selectionQuote.value = null
    return
  }
  const range = sel.getRangeAt(0)
  const rect = range.getBoundingClientRect()
  const rootRect = threadRootRef.value.getBoundingClientRect()
  if (!rect.width && !rect.height) {
    selectionQuote.value = null
    return
  }
  const rawLeft = rect.left - rootRect.left + rect.width / 2
  const clampedLeft = Math.max(64, Math.min(rootRect.width - 64, rawLeft))
  const clampedTop = Math.max(12, rect.top - rootRect.top - 36)
  selectionQuote.value = { text: txt, top: clampedTop, left: clampedLeft }
}

function applySelectionQuote() {
  const q = selectionQuote.value
  if (!q) return
  const preview = q.text.replace(/\s+/g, ' ').slice(0, 32)
  addContextItem({
    id: `quote:${Date.now()}`,
    kind: 'session',
    icon: 'chat',
    label: `引用「${preview}${q.text.length > 32 ? '…' : ''}」`,
    payload: `引用片段：\n> ${q.text.replace(/\n/g, '\n> ')}`,
  })
  selectionQuote.value = null
  window.getSelection()?.removeAllRanges()
}

function removePastedBlock(id: string) {
  const key = settingsKey.value
  pastedBlocksByKey.value = {
    ...pastedBlocksByKey.value,
    [key]: (pastedBlocksByKey.value[key] ?? []).filter(b => b.id !== id),
  }
  if (previewingPasteBlock.value?.id === id) previewingPasteBlock.value = null
}

function scrollToBottomSmooth() {
  const list = listEl.value
  if (!list) return
  followLatest.value = true
  unseenBelowCount.value = 0
  if (effectiveKey.value) fleet.markSessionRead(effectiveKey.value)
  list.scrollTo({ top: list.scrollHeight, behavior: 'smooth' })
  // 遵循 scroll-position-aware-elements：按钮隐藏后焦点转回滚动区避免掉到 body
  if (document.activeElement === jumpBtnRef.value) {
    list.focus({ preventScroll: true })
  }
}
const settingsKey = computed(() => effectiveKey.value || target.value)
const buffer = computed(() => {
  const key = settingsKey.value
  fleet.composerDrafts[key] ??= { text: '', files: [] }
  return fleet.composerDrafts[key]
})
const draft = computed({ get: () => buffer.value.text, set: text => { buffer.value.text = text } })
const queuedFiles = computed({ get: () => buffer.value.files, set: files => { buffer.value.files = files } })
const options = computed(() => fleet.runSettings[settingsKey.value] ?? {})
const model = computed(() => catalog.value?.models.find(m => m.id === options.value.model))
const sessionUsage = computed(() => (effectiveKey.value ? fleet.tokenUsageBySession[effectiveKey.value] ?? null : null))
const usageSourceLabel = computed(() => {
  const src = sessionUsage.value?.source
  if (src === 'exact') return '实测'
  if (src === 'mixed') return '混合'
  return '估算'
})
const usageContextRatio = computed(() => {
  const usage = sessionUsage.value
  if (!usage?.contextWindow || usage.contextWindow <= 0 || usage.lastTurnTokens <= 0) return 0
  return Math.min(100, (usage.lastTurnTokens / usage.contextWindow) * 100)
})
const usageContextBarWidth = computed(() => {
  const ratio = usageContextRatio.value
  return ratio > 0 ? Math.max(2, ratio) : 0
})
const usageContextPercentLabel = computed(() => {
  const ratio = usageContextRatio.value
  if (ratio === 0) return '0%'
  return ratio < 1 ? '<1%' : `${Math.round(ratio)}%`
})
const usageTooltip = computed(() => {
  const u = sessionUsage.value
  if (!u) return '仅在浏览器内存中累计当前连接下的 Token 消耗'
  const parts = [
    `累计总计 ${u.totalTokens.toLocaleString('en-US')} tokens`,
    `输入 ${u.totalInputTokens.toLocaleString('en-US')}`,
    `输出 ${u.totalOutputTokens.toLocaleString('en-US')}`,
  ]
  if (u.totalCachedTokens > 0) parts.push(`缓存命中 ${u.totalCachedTokens.toLocaleString('en-US')}`)
  if (u.totalReasoningTokens > 0) parts.push(`思考 ${u.totalReasoningTokens.toLocaleString('en-US')}`)
  return parts.join(' · ')
})
const currentDirectory = computed(() => effectiveSession.value?.cwd || effectiveNode.value?.allowedRoots?.[0] || '')
const directoryName = computed(() => currentDirectory.value.split(/[\\/]/).filter(Boolean).pop() || currentDirectory.value)
const permissionMode = computed(() =>
  options.value.readOnly ? 'read'
  : options.value.denyRequests ? 'deny'
  : options.value.autoApprove ? 'turbo'
  : 'default',
)
interface PermissionChoice {
  id: 'default' | 'read' | 'deny' | 'turbo'
  icon: 'lock' | 'shield' | 'eye' | 'zap'
  label: string
  badge?: string
  description: string
  disabled: boolean
  note?: string
}
const permissionChoices = computed<PermissionChoice[]>(() => [
  {
    id: 'read',
    icon: 'eye',
    label: '只读沙箱',
    badge: caps.value.includes('read-only') ? undefined : '不可用',
    description: '仅读取与分析文件，禁止写入或命令执行。',
    disabled: !caps.value.includes('read-only'),
    note: '当前代理引擎未开放只读沙箱能力',
  },
  {
    id: 'default',
    icon: caps.value.includes('approval') ? 'lock' : 'shield',
    label: caps.value.includes('approval') ? '运行前确认' : '由宿主托管',
    badge: '默认',
    description: caps.value.includes('approval') ? '执行敏感操作或命令前先请求人工确认。' : '使用宿主机节点默认权限策略。',
    disabled: false,
  },
  {
    id: 'deny',
    icon: 'shield',
    label: '拒绝审批请求',
    badge: caps.value.includes('deny-requests') ? undefined : '不可用',
    description: '不弹窗询问，自动拦截并拒绝新审批请求。',
    disabled: !caps.value.includes('deny-requests'),
    note: '当前代理引擎不支持自动拒绝审批策略',
  },
  {
    id: 'turbo',
    icon: 'zap',
    label: '极速模式',
    badge: caps.value.includes('auto-approve') ? undefined : '不可用',
    description: '无需人工审批，自动放行代理操作请求。',
    disabled: !caps.value.includes('auto-approve'),
    note: '当前代理引擎未启用审批直通能力',
  },
])
const activePermission = computed(() => permissionChoices.value.find(choice => choice.id === permissionMode.value))
const permissionLabel = computed(() => activePermission.value?.label ?? '执行权限')
const permissionIcon = computed(() => activePermission.value?.icon ?? 'shield')
const effortLabels: Record<string, string> = {
  none: '关闭', minimal: '极低', low: '低', medium: '中', high: '高', xhigh: '极高', max: '最高',
}
const triggerEffortLabel = computed(() => {
  if (options.value.effort) return effortLabels[options.value.effort] ?? options.value.effort
  const def = model.value?.defaultEffort
  return def ? (effortLabels[def] ?? def) : ''
})

function rowEffortText(entry: FleetModel): string {
  if (entry.unavailable) return ''
  if (options.value.model === entry.id && options.value.effort) {
    return effortLabels[options.value.effort] ?? options.value.effort
  }
  if (entry.defaultEffort) return effortLabels[entry.defaultEffort] ?? entry.defaultEffort
  if (options.value.model === entry.id && entry.efforts.length) return '默认'
  return ''
}

// Antigravity 风格级联二级浮层（模型思考强度 & 「+」上下文扩展共用）
type AttachSubKey = 'dirs' | 'data' | 'sessions' | 'commands' | 'rules' | 'mcp'
type ContextKind = 'dir' | 'data' | 'website' | 'session'
interface ComposerContextItem {
  id: string
  kind: ContextKind
  icon: OpusIconName
  label: string
  payload: string
}

const hoveredModelId = ref<string | null>(null)
const inlineEffortModelId = ref<string | null>(null)
const hoveredAttachKey = ref<AttachSubKey | null>(null)
const inlineAttachKey = ref<AttachSubKey | null>(null)
const subPlacement = ref<'right' | 'left'>('right')
const subTop = ref(0)
let subCloseTimer: ReturnType<typeof setTimeout> | null = null

const contextsByKey = ref<Record<string, ComposerContextItem[]>>({})
const queuedContexts = computed(() => contextsByKey.value[settingsKey.value] ?? [])

const subModel = computed(() =>
  hoveredModelId.value ? catalog.value?.models.find(m => m.id === hoveredModelId.value) ?? null : null,
)

const directoryContextOptions = computed(() => {
  const roots = effectiveNode.value?.allowedRoots ?? []
  const seen = new Set<string>()
  const list: Array<{ path: string; name: string; current: boolean }> = []
  for (const path of [currentDirectory.value, ...roots]) {
    if (!path || seen.has(path)) continue
    seen.add(path)
    list.push({
      path,
      name: path.split(/[\\/]/).filter(Boolean).pop() || path,
      current: path === currentDirectory.value,
    })
  }
  return list
})

const personalContextOptions = computed<ComposerContextItem[]>(() => {
  const items: ComposerContextItem[] = []
  for (const col of dataStore.items.slice(0, 4)) {
    items.push({
      id: `col:${col.id}`,
      kind: 'data',
      icon: 'data',
      label: `${col.name} (${col.recordCount})`,
      payload: `个人资料集「${col.name}」（共 ${col.recordCount} 条记录${col.description ? `，说明：${col.description}` : ''}）`,
    })
  }
  for (const rec of (dataStore.overview?.recentRecords ?? []).slice(0, 4)) {
    items.push({
      id: `rec:${rec.id}`,
      kind: 'data',
      icon: 'note',
      label: rec.name,
      payload: `资料记录「${rec.collectionName} · ${rec.name}」（状态：${rec.status || '正常'}${rec.category ? `，分类：${rec.category}` : ''}）`,
    })
  }
  const sites = websitesStore.recent.length ? websitesStore.recent : websitesStore.websites
  for (const site of sites.slice(0, 4)) {
    items.push({
      id: `web:${site.id}`,
      kind: 'website',
      icon: 'globe',
      label: site.name,
      payload: `收藏网站「${site.name}」: ${site.url}${site.description ? ` — ${site.description}` : ''}`,
    })
  }
  return items
})

const sessionContextOptions = computed<Array<ComposerContextItem & { preview: string }>>(() => {
  const out: Array<ComposerContextItem & { preview: string }> = []
  for (const sess of fleet.allSessions) {
    const key = buildSessionKey(sess.nodeId, sess.provider, sess.sessionId)
    if (key === effectiveKey.value) continue
    const msgs = fleet.messagesBySession[key] ?? []
    const lastReply = [...msgs].reverse().find(m => m.role === 'assistant' && m.text.trim())
    if (!lastReply) continue
    const nodeName = fleet.nodes.find(n => n.id === sess.nodeId)?.name || sess.nodeId
    const providerLabel = getProviderMeta(sess.provider).label
    const cleanText = lastReply.text.trim()
    out.push({
      id: `sess:${key}`,
      kind: 'session',
      icon: 'branch',
      label: `${nodeName} · ${providerLabel}`,
      preview: cleanText.slice(0, 42),
      payload: `参考会话「${nodeName} · ${providerLabel}」最新回复：\n${cleanText.slice(0, 800)}`,
    })
  }
  return out
})

const quickCommands = [
  { id: '/plan', title: '/plan', desc: '先出分步方案，确认后再动手', text: '请先分析涉及模块并列出分步方案，确认后再执行修改：\n' },
  { id: '/review', title: '/review', desc: '审查当前工作区改动与风险', text: '请审查当前工作区代码改动，指出潜在 Bug、边界情况与优化建议。' },
  { id: '/status', title: '/status', desc: '汇报工作目录、Git 与运行状态', text: '请检查当前工作目录、Git 状态与环境运行健康状况并简洁汇报。' },
  { id: '/handoff', title: '/handoff', desc: '总结当前进展便于跨节点交接', text: '请整理当前任务已完成内容、关键结论与下一步行动清单，方便交接给其他节点继续执行。' },
] as const

function clearSubCloseTimer() {
  if (subCloseTimer !== null) {
    clearTimeout(subCloseTimer)
    subCloseTimer = null
  }
}

function closeSubmenu() {
  clearSubCloseTimer()
  hoveredModelId.value = null
  hoveredAttachKey.value = null
}

function scheduleSubClose() {
  clearSubCloseTimer()
  subCloseTimer = setTimeout(() => {
    hoveredModelId.value = null
    hoveredAttachKey.value = null
    subCloseTimer = null
  }, 140)
}

function shouldUseInlineSubmenu(): boolean {
  if (props.mobile || window.innerWidth < 540) return true
  const popup = settingsPopup.value
  if (!popup) return false
  const rect = popup.getBoundingClientRect()
  const needed = 154
  return window.innerWidth - rect.right < needed && rect.left < needed
}

function computeSubmenuPosition(rowEl: HTMLElement | null, itemCount: number, subWidth = 128, rowHeight = 27) {
  const popup = settingsPopup.value
  if (!popup || !rowEl) return
  const popRect = popup.getBoundingClientRect()
  const rowRect = rowEl.getBoundingClientRect()
  subPlacement.value = window.innerWidth - popRect.right >= subWidth + 10 ? 'right' : 'left'
  const estimatedH = Math.max(1, itemCount) * rowHeight + 12
  const rawTop = rowRect.top - popRect.top - 5
  const minTop = 8 - popRect.top
  const maxTop = window.innerHeight - 8 - estimatedH - popRect.top
  subTop.value = Math.max(minTop, Math.min(rawTop, maxTop))
}

function openEffortMenu(entry: FleetModel, rowEl: HTMLElement | null) {
  clearSubCloseTimer()
  if (entry.unavailable || !entry.efforts.length || shouldUseInlineSubmenu()) {
    hoveredModelId.value = null
    return
  }
  computeSubmenuPosition(rowEl, entry.efforts.length + 1)
  hoveredModelId.value = entry.id
}

function openAttachSubmenu(key: AttachSubKey, rowEl: HTMLElement | null) {
  clearSubCloseTimer()
  if (key === 'data') ensurePersonalStoresLoaded()
  if (shouldUseInlineSubmenu()) {
    hoveredAttachKey.value = null
    return
  }
  const count = key === 'dirs' ? Math.max(1, directoryContextOptions.value.length)
    : key === 'data' ? Math.max(2, personalContextOptions.value.length)
    : key === 'sessions' ? Math.max(1, sessionContextOptions.value.length)
    : quickCommands.length
  const rowHeight = key === 'commands' || key === 'sessions' ? 58 : 27
  computeSubmenuPosition(rowEl, count, 200, rowHeight)
  hoveredAttachKey.value = key
}

function toggleAttachRow(key: AttachSubKey, rowEl: HTMLElement | null) {
  if (key === 'data') ensurePersonalStoresLoaded()
  if (shouldUseInlineSubmenu()) {
    inlineAttachKey.value = inlineAttachKey.value === key ? null : key
    return
  }
  if (hoveredAttachKey.value === key) {
    closeSubmenu()
  } else {
    openAttachSubmenu(key, rowEl)
  }
}

function onModelRowPointerEnter(entry: FleetModel, event: PointerEvent) {
  if (event.pointerType !== 'mouse') return
  openEffortMenu(entry, event.currentTarget as HTMLElement)
}

function onAttachRowPointerEnter(key: AttachSubKey, event: PointerEvent) {
  if (event.pointerType !== 'mouse') return
  openAttachSubmenu(key, event.currentTarget as HTMLElement)
}

function handleModelRowKeydown(entry: FleetModel, event: KeyboardEvent) {
  if (entry.unavailable || !entry.efforts.length) return
  const expandKey = subPlacement.value === 'left' ? 'ArrowLeft' : 'ArrowRight'
  if (event.key !== expandKey) return
  event.preventDefault()
  if (shouldUseInlineSubmenu()) {
    inlineEffortModelId.value = inlineEffortModelId.value === entry.id ? null : entry.id
    return
  }
  openEffortMenu(entry, event.currentTarget as HTMLElement)
  nextTick(() => {
    settingsPopup.value?.querySelector<HTMLButtonElement>('.effort-submenu .picker-option')?.focus()
  })
}

function handleSubmenuKeydown(event: KeyboardEvent) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight' && event.key !== 'Escape') return
  const currentModelId = hoveredModelId.value
  const currentAttach = hoveredAttachKey.value
  event.preventDefault()
  event.stopPropagation()
  closeSubmenu()
  if (currentModelId) {
    const rowBtn = Array.from(settingsPopup.value?.querySelectorAll<HTMLButtonElement>('[data-model-id]') ?? [])
      .find(el => el.dataset.modelId === currentModelId)
    rowBtn?.focus()
  } else if (currentAttach) {
    const rowBtn = Array.from(settingsPopup.value?.querySelectorAll<HTMLButtonElement>('[data-attach-key]') ?? [])
      .find(el => el.dataset.attachKey === currentAttach)
    rowBtn?.focus()
  }
}

function ensurePersonalStoresLoaded() {
  const token = auth.token
  if (!token) return
  void dataStore.load(token).catch(() => {})
  void dataStore.loadOverview(token).catch(() => {})
  void websitesStore.loadRecent(token).catch(() => {})
}

function choosePermission(choice: PermissionChoice) {
  if (choice.disabled) return
  fleet.runSettings[settingsKey.value] = {
    ...options.value,
    readOnly: choice.id === 'read',
    denyRequests: choice.id === 'deny',
    autoApprove: choice.id === 'turbo',
  }
  closeSettings()
}

function chooseModel(modelId: string) {
  const nextEntry = catalog.value?.models.find(m => m.id === modelId)
  if (nextEntry?.unavailable) return
  const keepingSame = (options.value.model ?? '') === modelId
  if (!keepingSame) {
    fleet.setModelPreference(effectiveNode.value?.id, effectiveProvider.value, modelId, undefined, settingsKey.value)
  }
  if (nextEntry?.efforts.length && shouldUseInlineSubmenu()) {
    if (inlineEffortModelId.value === modelId && keepingSame) {
      closeSettings()
    } else {
      inlineEffortModelId.value = modelId
    }
    return
  }
  closeSettings()
}

function chooseModelEffort(modelId: string, effort: string) {
  const entry = catalog.value?.models.find(m => m.id === modelId)
  if (entry?.unavailable) return
  fleet.setModelPreference(effectiveNode.value?.id, effectiveProvider.value, modelId, effort || undefined, settingsKey.value)
  closeSettings()
}

function refreshModels() {
  if (caps.value.includes('models') && effectiveNode.value?.status === 'online') {
    fleet.requestModels(effectiveNode.value.id, effectiveProvider.value)
  }
}

function addContextItem(item: ComposerContextItem) {
  const key = settingsKey.value
  const list = contextsByKey.value[key] ?? []
  if (!list.some(existing => existing.id === item.id)) {
    contextsByKey.value = { ...contextsByKey.value, [key]: [...list, item] }
  }
  closeSettings()
  nextTick(() => textareaRef.value?.focus())
}

function removeQueuedContext(id: string) {
  const key = settingsKey.value
  contextsByKey.value = {
    ...contextsByKey.value,
    [key]: (contextsByKey.value[key] ?? []).filter(item => item.id !== id),
  }
}

function insertCommandTemplate(template: string) {
  const cur = draft.value
  draft.value = cur.trim() ? `${template}\n${cur}` : template
  closeSettings()
  nextTick(() => textareaRef.value?.focus())
}

function positionSettings() {
  const popup = settingsPopup.value
  const trigger = settingsTrigger.value
  if (!popup || !trigger) return
  const { left, right, top } = trigger.getBoundingClientRect()
  // 左侧「+」「模型」按左边缘对齐，右侧权限胶囊按右边缘对齐
  popup.style.setProperty('--trigger-x', `${panel.value === 'permissions' ? right : left}px`)
  popup.style.setProperty('--trigger-y', `${top}px`)
}

let dismissedBySelfTrigger: 'model' | 'permissions' | 'attach' | null = null

function noteTriggerPointerDown(next: 'model' | 'permissions' | 'attach') {
  // HTML popover="auto" 会在 pointerdown 阶段触发 light-dismiss，提前记录避免后续 click 又立刻重新打开
  dismissedBySelfTrigger = settingsOpen.value && panel.value === next ? next : null
}

function togglePanelWithButton(next: 'model' | 'permissions' | 'attach', triggerEl: HTMLButtonElement | null) {
  const popup = settingsPopup.value
  if (!popup || !triggerEl) return
  if (popup.matches(':popover-open') && panel.value === next) {
    popup.hidePopover()
    return
  }
  closeSubmenu()
  inlineEffortModelId.value = null
  inlineAttachKey.value = null
  panel.value = next
  settingsTrigger.value = triggerEl
  positionSettings()
  if (!popup.matches(':popover-open')) {
    const show = popup.showPopover as (options: { source: HTMLElement }) => void
    show.call(popup, { source: triggerEl })
  }
  if (next === 'model' && caps.value.includes('models') && effectiveNode.value?.status === 'online') {
    fleet.requestModels(effectiveNode.value.id, effectiveProvider.value)
  } else if (next === 'permissions' && effectiveNode.value?.status === 'online') {
    fleet.requestTrustPolicies(effectiveNode.value.id)
  } else if (next === 'attach') {
    ensurePersonalStoresLoaded()
    if (effectiveNode.value?.status === 'online') {
      fleet.requestRules(effectiveKey.value || undefined)
      if (caps.value.includes('mcp')) {
        fleet.requestMcpServers(effectiveNode.value.id, effectiveProvider.value)
      }
    }
  }
}

function showPanel(next: 'model' | 'permissions' | 'attach', event: MouseEvent) {
  if (dismissedBySelfTrigger === next) {
    dismissedBySelfTrigger = null
    return
  }
  dismissedBySelfTrigger = null
  togglePanelWithButton(next, event.currentTarget as HTMLButtonElement)
}

function handleThreadKeydown(ev: KeyboardEvent) {
  if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && ev.key === '/') {
    ev.preventDefault()
    ev.stopPropagation()
    dismissedBySelfTrigger = null
    togglePanelWithButton('model', modelTriggerRef.value ?? null)
    return
  }
  if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && ev.key.toLowerCase() === 'f') {
    ev.preventDefault()
    ev.stopPropagation()
    openThreadSearch()
  }
}

function refreshMcp() {
  if (caps.value.includes('mcp') && effectiveNode.value?.status === 'online') {
    fleet.requestMcpServers(effectiveNode.value.id, effectiveProvider.value)
  }
}

function findToolCall(msg: ChatMessage, callId: string): ToolCallBadge | undefined {
  return msg.toolCalls?.find(t => (t.callId || t.id) === callId)
}

// Web Speech API 语音输入（实时流式预览 + 自动跟随浏览器语言 + 静音自动收尾）
type SpeechRecognitionLike = {
  lang: string
  continuous: boolean
  interimResults: boolean
  onresult: ((ev: { results: ArrayLike<{ isFinal?: boolean; 0?: { transcript: string } }> }) => void) | null
  onend: (() => void) | null
  onerror: ((ev?: { error?: string }) => void) | null
  start: () => void
  stop: () => void
}
const SpeechCtor = typeof window !== 'undefined'
  ? ((window as unknown as { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike }).SpeechRecognition
    || (window as unknown as { webkitSpeechRecognition?: new () => SpeechRecognitionLike }).webkitSpeechRecognition)
  : undefined
const speechSupported = Boolean(SpeechCtor)
const speechActive = ref(false)
const speechInterim = ref('')
let speechInst: SpeechRecognitionLike | null = null
let speechBaseDraft = ''

function toggleVoiceDictation() {
  if (!SpeechCtor) return
  if (speechActive.value && speechInst) {
    speechInst.stop()
    speechActive.value = false
    speechInterim.value = ''
    return
  }
  try {
    const rec = new SpeechCtor()
    rec.lang = (typeof navigator !== 'undefined' && navigator.language) || 'zh-CN'
    rec.continuous = true
    rec.interimResults = true
    speechBaseDraft = draft.value.trim()
    speechInterim.value = ''
    rec.onresult = (ev) => {
      const finals: string[] = []
      const interims: string[] = []
      for (let i = 0; i < ev.results.length; i++) {
        const res = ev.results[i]
        const alt = res?.[0]?.transcript?.trim()
        if (!alt) continue
        if (res.isFinal) finals.push(alt)
        else interims.push(alt)
      }
      const finalTxt = finals.join(' ').trim()
      speechInterim.value = interims.join(' ').trim()
      if (finalTxt) {
        draft.value = speechBaseDraft ? `${speechBaseDraft} ${finalTxt}` : finalTxt
      }
    }
    rec.onend = () => {
      if (speechInterim.value) {
        draft.value = draft.value.trim() ? `${draft.value.trim()} ${speechInterim.value}` : speechInterim.value
      }
      speechInterim.value = ''
      speechActive.value = false
    }
    rec.onerror = (ev) => {
      speechInterim.value = ''
      speechActive.value = false
      if (ev?.error === 'not-allowed') {
        emit('action', '麦克风权限被拒绝，请在系统或浏览器设置中允许访问')
      } else if (ev?.error === 'network') {
        emit('action', '浏览器语音识别服务不可达，请检查网络或使用系统听写快捷键')
      }
    }
    speechInst = rec
    speechActive.value = true
    rec.start()
  } catch {
    speechActive.value = false
  }
}

watch(
  () => [settingsKey.value, effectiveNode.value?.id, effectiveProvider.value] as const,
  ([sKey, nid, prov]) => {
    if (nid) fleet.applyDefaultModelPref(sKey, nid, prov)
  },
  { immediate: true },
)

watch(
  () => [target.value, effectiveKey.value, effectiveNode.value?.status, caps.value.join(',')] as const,
  ([key, , status, capsStr]) => {
    if (status !== 'online' || !effectiveNode.value) return
    const capSet = new Set(capsStr.split(',').filter(Boolean))
    if (capSet.has('models') && !fleet.catalogs[key]) {
      fleet.requestModels(effectiveNode.value.id, effectiveProvider.value)
    }
    if (capSet.has('mcp') && !fleet.mcpByTarget[key]) {
      fleet.requestMcpServers(effectiveNode.value.id, effectiveProvider.value)
    }
    if (!fleet.rulesByTarget[key]) {
      fleet.requestRules(effectiveKey.value || undefined)
    }
    if (!fleet.skillsByTarget[key]) {
      fleet.requestSkills(effectiveKey.value || undefined)
    }
  },
  { immediate: true },
)

function closeSettings() {
  closeSubmenu()
  inlineEffortModelId.value = null
  inlineAttachKey.value = null
  settingsPopup.value?.hidePopover()
}

function onPopoverToggle(event: Event) {
  const open = (event as ToggleEvent).newState === 'open'
  settingsOpen.value = open
  if (!open) {
    closeSubmenu()
    inlineEffortModelId.value = null
    inlineAttachKey.value = null
  }
}

async function scrollToBottomInstant() {
  followLatest.value = true
  unseenBelowCount.value = 0
  if (effectiveKey.value) fleet.markSessionRead(effectiveKey.value)
  await nextTick()
  const list = listEl.value
  if (list) {
    list.scrollTop = list.scrollHeight
  }
  if (typeof requestAnimationFrame === 'function') {
    requestAnimationFrame(() => {
      const el = listEl.value
      if (el && followLatest.value) {
        el.scrollTop = el.scrollHeight
      }
    })
  }
}

watch(
  () => [settingsKey.value, effectiveKey.value] as const,
  () => {
    closeSettings()
    selectionQuote.value = null
    void scrollToBottomInstant()
  },
  { immediate: true },
)

function trackMessageScroll() {
  const list = listEl.value
  if (!list) return
  const atBottom = list.scrollHeight - list.clientHeight - list.scrollTop < 32
  followLatest.value = atBottom
  if (atBottom) {
    unseenBelowCount.value = 0
    if (effectiveKey.value) fleet.markSessionRead(effectiveKey.value)
  }
}

watchEffect(onCleanup => {
  const measure = draftMeasure.value
  const list = listEl.value
  const inner = innerListEl.value
  if (!list) return
  const editorObserver = measure
    ? new ResizeObserver(() => {
        editorHeight.value = Math.ceil(measure.getBoundingClientRect().height)
        if (settingsOpen.value) positionSettings()
      })
    : null
  const messageObserver = new ResizeObserver(() => {
    if (followLatest.value) {
      list.scrollTop = list.scrollHeight
    }
  })
  if (editorObserver && measure) editorObserver.observe(measure)
  messageObserver.observe(list)
  if (inner) messageObserver.observe(inner)
  window.addEventListener('resize', positionSettings)
  onCleanup(() => {
    editorObserver?.disconnect()
    messageObserver.disconnect()
    window.removeEventListener('resize', positionSettings)
  })
})

const effectiveMessages = computed<ChatMessage[]>(() =>
  effectiveKey.value ? fleet.messagesBySession[effectiveKey.value] ?? [] : [],
)
const isStreaming = computed(() =>
  Boolean(effectiveKey.value && fleet.runningBySession[effectiveKey.value]),
)
const effectiveTodos = computed(() =>
  effectiveKey.value ? fleet.todosBySession[effectiveKey.value] ?? [] : [],
)
const effectiveQueue = computed(() =>
  effectiveKey.value ? fleet.queuedPromptsBySession[effectiveKey.value] ?? [] : [],
)
const effectiveCheckpoints = computed(() =>
  effectiveKey.value ? fleet.checkpointsBySession[effectiveKey.value] ?? [] : [],
)
const effectiveDiff = computed(() =>
  effectiveKey.value ? fleet.diffBySession[effectiveKey.value] ?? null : null,
)
const cachedNodeFiles = computed(() =>
  (effectiveKey.value ? fleet.filesCacheByTarget[effectiveKey.value] : undefined)
  ?? fleet.filesCacheByTarget[target.value]
  ?? [],
)
const knownFilesSet = computed(() => {
  const set = new Set<string>()
  for (const fp of cachedNodeFiles.value) set.add(fp.replace(/\\/g, '/').toLowerCase())
  for (const df of effectiveDiff.value?.files ?? []) set.add(df.path.replace(/\\/g, '/').toLowerCase())
  return set
})
const currentWorktreeName = computed(() => {
  const wt = effectiveSession.value?.worktreePath
  if (!wt) return undefined
  return wt.replace(/\\/g, '/').split('/').filter(Boolean).pop()
})
const fallbackModels = computed(() => {
  const list = catalog.value?.models ?? []
  const curId = options.value.model || ''
  return list.filter(m => !m.unavailable && m.id && m.id !== curId).slice(0, 3)
})

// 双击 Esc 防误触中止流式生成
const escConfirmArmed = ref(false)
let escConfirmTimer: ReturnType<typeof setTimeout> | null = null

function armOrCancelOnEsc() {
  if (!isStreaming.value) return
  if (escConfirmArmed.value) {
    escConfirmArmed.value = false
    if (escConfirmTimer) clearTimeout(escConfirmTimer)
    escConfirmTimer = null
    stopStreamingRun()
    return
  }
  escConfirmArmed.value = true
  if (escConfirmTimer) clearTimeout(escConfirmTimer)
  escConfirmTimer = setTimeout(() => {
    escConfirmArmed.value = false
    escConfirmTimer = null
  }, 1800)
}

async function switchModelAndRetry(modelId: string, msgIndex: number) {
  const targetModel = catalog.value?.models.find(m => m.id === modelId)
  fleet.setModelPreference(
    effectiveNode.value?.id,
    effectiveProvider.value,
    modelId,
    targetModel?.defaultEffort,
    settingsKey.value,
  )
  emit('action', `已切换至 ${targetModel?.label || modelId} 并重试`)
  await handleRegenerate(msgIndex)
}

function formatDurationShort(ms?: number): string {
  if (ms === undefined || ms === null || Number.isNaN(ms) || ms <= 0) return ''
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`
}

function thoughtPreviewLine(text: string): string {
  const lines = text.trim().split('\n').map(l => l.trim()).filter(Boolean)
  const tail = lines[lines.length - 1] ?? ''
  return tail.length > 68 ? `${tail.slice(0, 68)}…` : tail
}

// 自定义 Prompt 模板与节点信任命令白名单
const customPrompts = ref<CustomPromptTemplate[]>(loadCustomPrompts())
const promptLibraryOpen = ref(false)
const nodeTrustPatterns = computed(() =>
  effectiveNode.value ? fleet.trustPatternsByNode[effectiveNode.value.id] ?? [] : [],
)
const newTrustPattern = ref('')

function handleSaveCustomPrompt(payload: {
  id?: string
  trigger: string
  title: string
  description: string
  template: string
}) {
  customPrompts.value = saveCustomPrompt(payload)
}

function handleRemoveCustomPrompt(id: string) {
  customPrompts.value = deleteCustomPrompt(id)
}

function handleUseCustomPrompt(tpl: string) {
  const prefix = draft.value.trim()
  draft.value = prefix ? `${prefix}\n${tpl}` : tpl
  promptLibraryOpen.value = false
  void nextTick(() => textareaRef.value?.focus())
}

function handleAddTrustPattern() {
  const nid = effectiveNode.value?.id
  const pat = newTrustPattern.value.trim()
  if (!nid || !pat) return
  fleet.addTrustPattern(nid, pat)
  newTrustPattern.value = ''
}

function handleRemoveTrustPattern(pat: string) {
  const nid = effectiveNode.value?.id
  if (!nid) return
  fleet.removeTrustPattern(nid, pat)
}

// 对话内搜索（Ctrl+F）与消息内存书签
const searchOpen = ref(false)
const searchQuery = ref('')
const searchActiveIdx = ref(0)
const searchInputRef = ref<HTMLInputElement | null>(null)
const highlightedMsgId = ref<string | null>(null)

interface SearchMatchEntry {
  msgId: string
  msgIdx: number
  thoughtKey?: string
}

const searchMatches = computed<SearchMatchEntry[]>(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return []
  const hits: SearchMatchEntry[] = []
  effectiveMessages.value.forEach((msg, msgIdx) => {
    const parts = extractMessageParts(msg)
    let matchedThoughtKey: string | undefined
    for (let pIdx = 0; pIdx < parts.length; pIdx += 1) {
      const p = parts[pIdx]
      if (p.type === 'thought' && p.text.toLowerCase().includes(q)) {
        matchedThoughtKey = `${msg.id}-p-${pIdx}`
        break
      }
    }
    const textHit = (msg.text || '').toLowerCase().includes(q)
    const toolHit = (msg.toolCalls ?? []).some(
      tc =>
        tc.name.toLowerCase().includes(q)
        || (tc.title || '').toLowerCase().includes(q)
        || (tc.output || '').toLowerCase().includes(q)
        || (tc.error || '').toLowerCase().includes(q),
    )
    if (textHit || matchedThoughtKey || toolHit) {
      hits.push({ msgId: msg.id, msgIdx, thoughtKey: matchedThoughtKey })
    }
  })
  return hits
})

function scrollToMessage(msgId: string, thoughtKey?: string) {
  if (thoughtKey && !expandedThought.value[thoughtKey]) {
    expandedThought.value = { ...expandedThought.value, [thoughtKey]: true }
  }
  highlightedMsgId.value = msgId
  followLatest.value = false
  void nextTick(() => {
    const el = listEl.value?.querySelector(`[data-msg-id="${msgId}"]`)
    if (el && typeof (el as HTMLElement).scrollIntoView === 'function') {
      ;(el as HTMLElement).scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  })
}

watch(searchMatches, list => {
  if (!list.length) {
    searchActiveIdx.value = 0
    if (searchOpen.value) highlightedMsgId.value = null
    return
  }
  if (searchActiveIdx.value >= list.length) {
    searchActiveIdx.value = 0
  }
  const hit = list[searchActiveIdx.value]
  if (hit) scrollToMessage(hit.msgId, hit.thoughtKey)
})

function openThreadSearch() {
  searchOpen.value = true
  void nextTick(() => {
    searchInputRef.value?.focus()
    searchInputRef.value?.select()
  })
}

function closeThreadSearch() {
  searchOpen.value = false
  searchQuery.value = ''
  highlightedMsgId.value = null
}

function stepSearchMatch(delta: number) {
  const list = searchMatches.value
  if (!list.length) return
  searchActiveIdx.value = (searchActiveIdx.value + delta + list.length) % list.length
  const hit = list[searchActiveIdx.value]
  if (hit) scrollToMessage(hit.msgId, hit.thoughtKey)
}

const bookmarkedIds = computed(() =>
  effectiveKey.value ? fleet.bookmarkedIdsBySession[effectiveKey.value] ?? [] : [],
)
const bookmarkedMessages = computed(() =>
  effectiveMessages.value.filter(m => bookmarkedIds.value.includes(m.id)),
)
function isMessageBookmarked(msgId: string): boolean {
  return bookmarkedIds.value.includes(msgId)
}
function toggleBookmark(msgId: string) {
  if (!effectiveKey.value) return
  fleet.toggleMessageBookmark(effectiveKey.value, msgId)
}

// 发送前草稿 + 附加上下文 + 待传文件的 Token 估算，及 `@path` 行号裁剪助手
const estimatedDraftTokens = computed(() => {
  let chars = draft.value.length
  for (const ctx of queuedContexts.value) {
    chars += (ctx.payload || '').length + (ctx.label || '').length
  }
  let fileToks = 0
  for (const f of queuedFiles.value) {
    fileToks += Math.min(25000, Math.max(120, Math.ceil((f.size || 0) / 4)))
  }
  if (!chars && !fileToks) return 0
  return Math.max(1, Math.ceil(chars / 3) + fileToks)
})

const untrimmedFileRef = computed(() => {
  const m = draft.value.match(/@([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+)(?!#L\d)/)
  return m ? m[1] : null
})

function trimFirstFileCitation() {
  const targetRef = untrimmedFileRef.value
  if (!targetRef) return
  draft.value = draft.value.replace(`@${targetRef}`, `@${targetRef}#L1-200`)
  void nextTick(() => textareaRef.value?.focus())
}

function isCheckpointReverted(cpId?: string): boolean {
  if (!cpId) return false
  return effectiveCheckpoints.value.some(c => c.checkpointId === cpId && c.reverted)
}

function handleRevertCheckpoint(cpId?: string) {
  if (!effectiveKey.value) return
  fleet.revertCheckpoint(effectiveKey.value, cpId)
}

function inspectTurnDiff(cpId?: string) {
  if (effectiveKey.value) {
    fleet.requestSessionDiff(effectiveKey.value, cpId)
  }
  emit('openDiff')
}

function handleExecutePlan() {
  if (isStreaming.value) return
  draft.value = '请继续执行剩余未完成的计划步骤，并在完成后更新进度。'
  void handleSubmit()
}

// 待发队列内联编辑
const editingQueueId = ref<string | null>(null)
const editingQueueText = ref('')

async function handleRegenerate(msgIndex: number) {
  if (sending.value || isStreaming.value) return
  if (effectiveKey.value && fleet.sessionsByKey[effectiveKey.value]) {
    sending.value = true
    try {
      await fleet.regenerateAssistantMessage(effectiveKey.value, msgIndex, { ...options.value })
    } catch (err) {
      emit('action', err instanceof Error ? err.message : '重新生成失败')
    } finally {
      sending.value = false
    }
    return
  }
  const msg = effectiveMessages.value[msgIndex]
  if (msg) await retryTurn(msg)
}

function handleForkAt(msgIndex: number) {
  if (!effectiveKey.value) return
  fleet.forkSessionFromMessage(effectiveKey.value, msgIndex)
  emit('action', '已从当前节点分叉出独立会话标签页')
}

function startEditQueued(id: string, text: string) {
  editingQueueId.value = id
  editingQueueText.value = text
}

function commitEditQueued(id: string) {
  if (effectiveKey.value) {
    fleet.updateQueuedPrompt(effectiveKey.value, id, editingQueueText.value)
  }
  editingQueueId.value = null
  editingQueueText.value = ''
}

// 内联 `@` 工作区文件/上下文 与 `/` 可执行指令自动补全
type SuggestMode = 'at' | 'slash' | null
interface SuggestOption {
  id: string
  kind: 'file' | 'context' | 'command'
  icon: OpusIconName
  title: string
  desc: string
  insertText?: string
  contextItem?: ComposerContextItem
  action?: () => void
}

const mentionListId = useId()
const mentionMode = ref<SuggestMode>(null)
const mentionQuery = ref('')
const mentionRange = ref<{ start: number; end: number }>({ start: 0, end: 0 })
const mentionDismissed = ref(false)
const activeSuggestIdx = ref(0)
let filesFetchTimer: ReturnType<typeof setTimeout> | null = null

const slashCommandSpecs = [
  { id: '/btw', title: '/btw', desc: '开启不污染主上下文的临时侧边问答', run: 'btw' },
  { id: '/plan', title: '/plan', desc: '切换至 Plan 规划模式（先方案后执行）', run: 'plan' },
  { id: '/diff', title: '/diff', desc: '打开右侧代码变更审查面板', run: 'diff' },
  { id: '/undo', title: '/undo', desc: '回滚上一轮文件修改检查点', run: 'undo' },
  { id: '/compact', title: '/compact', desc: '通知代理压缩早期历史上下文', run: 'compact' },
  { id: '/fork', title: '/fork', desc: '继承前情上下文分叉出新会话窗口', run: 'fork' },
  { id: '/review', title: '/review', desc: '审查当前工作区改动与潜在风险', run: 'template', template: '请审查当前工作区代码改动，指出潜在 Bug、边界情况与优化建议。' },
  { id: '/status', title: '/status', desc: '检查工作目录、Git 与运行状态', run: 'template', template: '请检查当前工作目录、Git 状态与环境运行健康状况并简洁汇报。' },
  { id: '/handoff', title: '/handoff', desc: '携带摘要交接给其他节点或引擎', run: 'handoff' },
  { id: '/clear', title: '/clear', desc: '开启干净的新工作会话', run: 'clear' },
] as const

function requestWorkspaceFilesDebounced(q: string) {
  if (effectiveNode.value?.status !== 'online') return
  if (filesFetchTimer) clearTimeout(filesFetchTimer)
  filesFetchTimer = setTimeout(() => {
    fleet.requestFilesList(q, 40, effectiveKey.value)
    filesFetchTimer = null
  }, 110)
}

function updateMentionTrigger() {
  const ta = textareaRef.value
  const val = draft.value
  const caret = ta?.selectionStart ?? val.length
  const prefix = val.slice(0, caret)

  const slashMatch = prefix.match(/^\/([^\s]*)$/)
  if (slashMatch) {
    mentionMode.value = 'slash'
    mentionQuery.value = slashMatch[1].toLowerCase()
    mentionRange.value = { start: 0, end: caret }
    mentionDismissed.value = false
    activeSuggestIdx.value = 0
    return
  }

  const atMatch = prefix.match(/(?:^|\s)@([^\s@]*)$/)
  if (atMatch) {
    const token = atMatch[1]
    const atPos = caret - token.length - 1
    mentionMode.value = 'at'
    mentionQuery.value = token.toLowerCase()
    mentionRange.value = { start: atPos, end: caret }
    mentionDismissed.value = false
    activeSuggestIdx.value = 0
    ensurePersonalStoresLoaded()
    requestWorkspaceFilesDebounced(token)
    return
  }

  mentionMode.value = null
  mentionQuery.value = ''
}

const suggestOptions = computed<SuggestOption[]>(() => {
  if (mentionDismissed.value || !mentionMode.value) return []
  const q = mentionQuery.value
  if (mentionMode.value === 'slash') {
    const baseOpts = slashCommandSpecs
      .filter(c => !q || c.title.toLowerCase().includes(q) || c.desc.toLowerCase().includes(q))
      .map<SuggestOption>(c => ({
        id: c.id,
        kind: 'command',
        icon: 'zap' as OpusIconName,
        title: c.title,
        desc: c.desc,
        action: () => {
          if (c.run === 'btw') {
            draft.value = '/btw '
            mentionMode.value = null
          } else if (c.run === 'plan') {
            setMode('plan')
            draft.value = ''
            mentionMode.value = null
            emit('action', '已切换至 Plan 模式（先输出分步计划再动手）')
          } else if (c.run === 'template') {
            draft.value = c.template
            mentionMode.value = null
          } else if (c.run === 'diff') {
            draft.value = ''
            mentionMode.value = null
            inspectTurnDiff()
          } else if (c.run === 'undo') {
            draft.value = ''
            mentionMode.value = null
            if (effectiveKey.value) fleet.revertCheckpoint(effectiveKey.value)
            else emit('action', '请先打开包含检查点的会话')
          } else if (c.run === 'compact') {
            draft.value = ''
            mentionMode.value = null
            if (effectiveKey.value) fleet.compactSession(effectiveKey.value)
            else emit('action', '请先进入活跃会话后再执行压缩')
          } else if (c.run === 'fork') {
            draft.value = ''
            mentionMode.value = null
            const lastIdx = Math.max(0, effectiveMessages.value.length - 1)
            if (effectiveKey.value) fleet.forkSessionFromMessage(effectiveKey.value, lastIdx)
          } else if (c.run === 'handoff') {
            draft.value = ''
            mentionMode.value = null
            const last = [...effectiveMessages.value].reverse().find(m => m.text.trim())
            emit('openHandoff', { summary: last?.text.slice(0, 1200) ?? '' })
          } else if (c.run === 'clear') {
            draft.value = ''
            mentionMode.value = null
            emit('clearSession')
          }
        },
      }))

    const skillOpts = skillsList.value
      .filter(s => !q || s.trigger.toLowerCase().includes(q) || s.title.toLowerCase().includes(q) || s.description.toLowerCase().includes(q))
      .map<SuggestOption>(s => ({
        id: s.id,
        kind: 'command',
        icon: 'layers',
        title: s.trigger,
        desc: `${s.description} · ${s.source}`,
        action: () => {
          draft.value = s.template
          mentionMode.value = null
        },
      }))

    const customOpts = customPrompts.value
      .filter(p => !q || p.trigger.toLowerCase().includes(q) || p.title.toLowerCase().includes(q) || p.description.toLowerCase().includes(q))
      .map<SuggestOption>(p => ({
        id: `custom:${p.id}`,
        kind: 'command',
        icon: 'sparkle',
        title: `/${p.trigger}`,
        desc: `${p.title}${p.description ? ` · ${p.description}` : ''}`,
        action: () => {
          draft.value = p.template
          mentionMode.value = null
        },
      }))

    const manageOpt: SuggestOption[] =
      !q || 'prompts manage 模板'.includes(q)
        ? [{
            id: 'custom:__manage__',
            kind: 'command',
            icon: 'settings',
            title: '/prompts',
            desc: '打开并管理自定义 Prompt 模板库',
            action: () => {
              draft.value = ''
              mentionMode.value = null
              promptLibraryOpen.value = true
            },
          }]
        : []

    return [...baseOpts, ...skillOpts, ...customOpts, ...manageOpt]
  }

  // '@' mention mode: 工作区文件 + @git diff + 个人资料/网站 + 其他会话结论
  const out: SuggestOption[] = []
  if (!q || 'git diff 变更'.includes(q)) {
    out.push({
      id: 'at:git-diff',
      kind: 'context',
      icon: 'branch',
      title: '@git diff',
      desc: '附带当前工作区 Git Diff 改动上下文',
      action: () => {
        if (effectiveKey.value) fleet.requestSessionDiff(effectiveKey.value)
        const diff = effectiveKey.value ? fleet.diffBySession[effectiveKey.value] : null
        const summaryText = diff?.files.length
          ? `工作区 Git Diff（+${diff.summary.additions}/-${diff.summary.deletions}）：${diff.files.map(f => f.path).join(', ')}`
          : '请查看当前工作区 `git diff` 未提交代码改动'
        addContextItem({
          id: 'ctx:git-diff',
          kind: 'dir',
          icon: 'branch',
          label: 'Git Diff',
          payload: summaryText,
        })
      },
    })
  }
  // Diff 中刚修改过的文件置顶 + 子序列模糊匹配打分（如 `act` 命中 `AgentChatThread.vue`）
  const modifiedSet = new Set((effectiveDiff.value?.files ?? []).map(f => f.path))
  const fileCandidates = Array.from(new Set([...Array.from(modifiedSet), ...cachedNodeFiles.value]))
  const rankedFiles: Array<{ path: string; score: number; modified: boolean }> = []
  for (const filePath of fileCandidates) {
    const score = fuzzyMatchFileScore(q, filePath)
    if (score === null) continue
    const modified = modifiedSet.has(filePath)
    rankedFiles.push({ path: filePath, score: modified ? score - 15 : score, modified })
  }
  rankedFiles.sort((a, b) => a.score - b.score || a.path.length - b.path.length)
  for (const item of rankedFiles.slice(0, 10)) {
    out.push({
      id: `file:${item.path}`,
      kind: 'file',
      icon: 'file',
      title: item.path,
      desc: item.modified ? '最近修改 · 工作区文件' : '工作区文件',
      insertText: `@${item.path} `,
    })
  }
  for (const item of personalContextOptions.value) {
    if (q && !item.label.toLowerCase().includes(q)) continue
    out.push({
      id: item.id,
      kind: 'context',
      icon: item.icon,
      title: item.label,
      desc: item.kind === 'website' ? '收藏网站' : '个人资料',
      contextItem: item,
    })
    if (out.length >= 14) break
  }
  for (const sItem of sessionContextOptions.value) {
    if (q && !sItem.label.toLowerCase().includes(q) && !sItem.preview.toLowerCase().includes(q)) continue
    out.push({
      id: sItem.id,
      kind: 'context',
      icon: 'branch',
      title: sItem.label,
      desc: sItem.preview,
      contextItem: sItem,
    })
    if (out.length >= 16) break
  }
  return out
})

const autocompleteOpen = computed(() => !mentionDismissed.value && suggestOptions.value.length > 0)

function applyAutocompleteOption(opt: SuggestOption) {
  const { start, end } = mentionRange.value
  const val = draft.value
  if (opt.action) {
    if (mentionMode.value === 'at') {
      draft.value = `${val.slice(0, start)}${val.slice(end)}`.trimStart()
    }
    opt.action()
  } else if (opt.insertText) {
    const nextVal = `${val.slice(0, start)}${opt.insertText}${val.slice(end)}`
    draft.value = nextVal
    mentionMode.value = null
    const nextCursor = start + opt.insertText.length
    void nextTick(() => {
      textareaRef.value?.focus()
      textareaRef.value?.setSelectionRange(nextCursor, nextCursor)
    })
  } else if (opt.contextItem) {
    draft.value = `${val.slice(0, start)}${val.slice(end)}`.trimStart()
    addContextItem(opt.contextItem)
    mentionMode.value = null
  }
  mentionDismissed.value = true
  void nextTick(() => textareaRef.value?.focus())
}

function insertFileReference(refOrPath: string) {
  const clean = refOrPath.trim()
  if (!clean) return
  if (/\s/.test(clean)) {
    const prefix = draft.value.trim()
    draft.value = prefix ? `${prefix}\n${clean}` : `${clean} `
    void nextTick(() => textareaRef.value?.focus())
    return
  }
  const prefix = draft.value.trim()
  const refToken = clean.startsWith('@') ? clean : `@${clean}`
  const isLineCite = /#L\d+/.test(refToken)
  draft.value = prefix ? `${prefix} ${refToken} ` : isLineCite ? `${refToken} ` : `${refToken} 请分析并检查此文件改动：`
  void nextTick(() => textareaRef.value?.focus())
}

defineExpose({ insertFileReference, openThreadSearch })

watch(
  () => effectiveMessages.value.length,
  (nextLen, prevLen) => {
    if (nextLen > 0 && (!prevLen || followLatest.value)) {
      void scrollToBottomInstant()
    }
  },
  { immediate: true },
)

watch(
  () =>
    effectiveMessages.value
      .map(m => `${m.id}:${m.streaming ? 1 : 0}:${m.text.length}:${m.thought?.length ?? 0}:${m.toolCalls?.length ?? 0}:${m.parts?.length ?? 0}`)
      .join(','),
  async (nextSig, prevSig) => {
    if (!nextSig || nextSig === prevSig) return
    await nextTick()
    if (!listEl.value) return
    // 严格遵守 followLatest：仅当用户停留在底部时自动追随，上翻阅读历史时绝不强行抢滚
    if (followLatest.value) {
      listEl.value.scrollTop = listEl.value.scrollHeight
    } else {
      unseenBelowCount.value += 1
    }
  },
)

function triggerFilePick() {
  closeSettings()
  fileInputRef.value?.click()
}

function appendFiles(fileList: File[]) {
  if (!fileList.length) return
  queuedFiles.value = [...queuedFiles.value, ...fileList]
}

const supportsFieldSizing = typeof CSS !== 'undefined' && typeof CSS.supports === 'function' && CSS.supports('field-sizing', 'content')

function insertQuickTrigger(symbol: '@' | '/') {
  closeSettings()
  const cur = draft.value
  const needsSpace = cur.length > 0 && !/\s$/.test(cur)
  draft.value = `${cur}${needsSpace ? ' ' : ''}${symbol}`
  void nextTick(() => {
    const el = textareaRef.value
    if (el) {
      el.focus()
      const pos = draft.value.length
      el.setSelectionRange(pos, pos)
      updateMentionTrigger()
    }
  })
}

async function pasteClipboardImage() {
  closeSettings()
  try {
    if (!navigator.clipboard?.read) {
      emit('action', '请直接在输入框按 Ctrl+V 粘贴截图或图片')
      return
    }
    const items = await navigator.clipboard.read()
    const picked: File[] = []
    for (const item of items) {
      const imageType = item.types.find(t => t.startsWith('image/'))
      if (!imageType) continue
      const blob = await item.getType(imageType)
      const ext = imageType.split('/')[1]?.replace(/[^a-z0-9]/gi, '') || 'png'
      picked.push(new File([blob], `clipboard-${Date.now()}.${ext}`, { type: imageType }))
    }
    if (!picked.length) {
      emit('action', '剪贴板中未检测到图片，你也可以直接 Ctrl+V 粘贴到输入框')
      return
    }
    appendFiles(picked)
  } catch {
    emit('action', '无法读取系统剪贴板，请直接在输入框按 Ctrl+V 粘贴图片')
  }
}

function handleComposerPaste(ev: ClipboardEvent) {
  const dt = ev.clipboardData
  if (!dt) return
  const files: File[] = []
  if (dt.files?.length) {
    files.push(...Array.from(dt.files))
  } else if (dt.items?.length) {
    for (const item of Array.from(dt.items)) {
      if (item.kind === 'file') {
        const f = item.getAsFile()
        if (f) files.push(f)
      }
    }
  }
  if (files.length) {
    appendFiles(files)
    if (!dt.getData('text/plain')) {
      ev.preventDefault()
    }
    return
  }
  // 粘贴超长纯文本时自动收纳为紧凑文本附件芯片，避免撑爆输入框与重排卡顿
  const plain = dt.getData('text/plain')
  if (plain && shouldConvertToPastedBlock(plain)) {
    ev.preventDefault()
    const key = settingsKey.value
    const block = createPastedTextBlock(plain, `paste-${Date.now()}-${Math.random().toString(16).slice(2, 6)}`)
    pastedBlocksByKey.value = {
      ...pastedBlocksByKey.value,
      [key]: [...(pastedBlocksByKey.value[key] ?? []), block],
    }
    emit('action', `已将 ${block.lineCount} 行粘贴内容收纳为文本附件芯片`)
  }
}

function handleFileDrop(ev: DragEvent) {
  draggingFiles.value = false
  const dropped = ev.dataTransfer?.files ? Array.from(ev.dataTransfer.files) : []
  if (dropped.length) appendFiles(dropped)
}

function handleFileSelect(ev: Event) {
  const input = ev.target as HTMLInputElement
  if (!input.files?.length) return
  appendFiles(Array.from(input.files))
  input.value = ''
}

function removeQueuedFile(idx: number) {
  queuedFiles.value = queuedFiles.value.filter((_, i) => i !== idx)
}

function stopStreamingRun() {
  if (effectiveKey.value) {
    fleet.cancelSessionRun(effectiveKey.value)
  }
}

function tryExecuteDirectSlash(text: string): boolean {
  const clean = text.trim()
  if (clean === '/btw' || clean.startsWith('/btw ')) {
    const q = clean.slice(4).trim()
    draft.value = ''
    emit('openSideChat', q || undefined)
    return true
  }
  if (clean === '/plan') {
    setMode('plan')
    draft.value = ''
    emit('action', '已切换至 Plan 模式（先输出分步方案再执行）')
    return true
  }
  if (clean === '/build') {
    setMode('build')
    draft.value = ''
    emit('action', '已切换至 Build 执行模式')
    return true
  }
  if (clean === '/prompts') {
    draft.value = ''
    promptLibraryOpen.value = true
    return true
  }
  const cmd = slashCommandSpecs.find(c => c.run !== 'template' && c.id === clean)
  if (!cmd) return false
  const opt = suggestOptions.value.find(o => o.id === cmd.id)
  if (opt?.action) {
    opt.action()
    return true
  }
  if (cmd.run === 'diff') {
    draft.value = ''
    inspectTurnDiff()
    return true
  }
  if (cmd.run === 'undo') {
    draft.value = ''
    if (effectiveKey.value) fleet.revertCheckpoint(effectiveKey.value)
    return true
  }
  if (cmd.run === 'compact') {
    draft.value = ''
    if (effectiveKey.value) fleet.compactSession(effectiveKey.value)
    return true
  }
  if (cmd.run === 'fork') {
    draft.value = ''
    if (effectiveKey.value) fleet.forkSessionFromMessage(effectiveKey.value, Math.max(0, effectiveMessages.value.length - 1))
    return true
  }
  if (cmd.run === 'clear') {
    draft.value = ''
    emit('clearSession')
    return true
  }
  if (cmd.run === 'handoff') {
    draft.value = ''
    const last = [...effectiveMessages.value].reverse().find(m => m.text.trim())
    emit('openHandoff', { summary: last?.text.slice(0, 1200) ?? '' })
    return true
  }
  return false
}

async function handleSubmit() {
  if (sending.value) return
  const text = draft.value.trim()
  const files = [...queuedFiles.value]
  const contexts = [...queuedContexts.value]
  const pastedBlocks = [...queuedPastedBlocks.value]

  if (isStreaming.value && !text && !files.length && !contexts.length && !pastedBlocks.length) {
    stopStreamingRun()
    return
  }
  if (!text && !files.length && !contexts.length && !pastedBlocks.length) return

  if (!isStreaming.value && !files.length && !contexts.length && !pastedBlocks.length && tryExecuteDirectSlash(text)) {
    mentionMode.value = null
    return
  }

  if (!effectiveNode.value) {
    emit('action', '请先在左侧选择或配对至少一个在线节点')
    return
  }
  const submittedKey = settingsKey.value
  const submitted = buffer.value
  const originalText = submitted.text
  const contextBlock = contexts.length
    ? `[附加上下文]\n${contexts.map(c => `- ${c.payload}`).join('\n')}\n\n`
    : ''
  const pastedSection = pastedBlocks.length
    ? `\n\n${pastedBlocks.map((b, i) => `[粘贴片段 #${i + 1} · ${b.lineCount} 行]\n\`\`\`\n${b.content}\n\`\`\``).join('\n\n')}`
    : ''
  const baseBody = text || (files.length ? '' : '请结合以上附加上下文进行分析或处理。')
  const payloadText = `${contextBlock}${baseBody}${pastedSection}`.trim()
  const runOpts = {
    ...options.value,
    ...(composerMode.value === 'plan' ? { planMode: true } : {}),
  }

  const clearSubmittedExtras = () => {
    if (submitted.text === originalText) submitted.text = ''
    submitted.files = submitted.files.filter(file => !files.includes(file))
    if (contexts.length) {
      const sentIds = new Set(contexts.map(c => c.id))
      contextsByKey.value = {
        ...contextsByKey.value,
        [submittedKey]: (contextsByKey.value[submittedKey] ?? []).filter(c => !sentIds.has(c.id)),
      }
    }
    if (pastedBlocks.length) {
      const sentPasteIds = new Set(pastedBlocks.map(b => b.id))
      pastedBlocksByKey.value = {
        ...pastedBlocksByKey.value,
        [submittedKey]: (pastedBlocksByKey.value[submittedKey] ?? []).filter(b => !sentPasteIds.has(b.id)),
      }
      previewingPasteBlock.value = null
    }
    mentionMode.value = null
  }

  if (isStreaming.value && effectiveKey.value) {
    fleet.enqueuePrompt(effectiveKey.value, payloadText, files, runOpts)
    clearSubmittedExtras()
    return
  }

  sending.value = true
  followLatest.value = true
  unseenBelowCount.value = 0
  try {
    if (effectiveKey.value && fleet.sessionsByKey[effectiveKey.value]) {
      await fleet.sendPromptToSpecificSession(effectiveKey.value, payloadText, files, runOpts)
    } else {
      await fleet.sendPrompt(payloadText, files, runOpts)
    }
    clearSubmittedExtras()
  } catch (err) {
    emit('action', err instanceof Error ? err.message : '消息发送失败')
  } finally {
    sending.value = false
  }
}

function handleKeydown(ev: KeyboardEvent) {
  if (autocompleteOpen.value) {
    const opts = suggestOptions.value
    if (ev.key === 'ArrowDown') {
      ev.preventDefault()
      activeSuggestIdx.value = (activeSuggestIdx.value + 1) % opts.length
      return
    }
    if (ev.key === 'ArrowUp') {
      ev.preventDefault()
      activeSuggestIdx.value = (activeSuggestIdx.value - 1 + opts.length) % opts.length
      return
    }
    if (ev.key === 'Escape') {
      ev.preventDefault()
      mentionDismissed.value = true
      return
    }
    if ((ev.key === 'Tab' || (ev.key === 'Enter' && !ev.shiftKey)) && !ev.isComposing) {
      ev.preventDefault()
      const chosen = opts[activeSuggestIdx.value] ?? opts[0]
      if (chosen) applyAutocompleteOption(chosen)
      return
    }
  }
  // 流式生成中按 Esc 触发两段式防误触中止
  if (ev.key === 'Escape' && isStreaming.value && !ev.isComposing) {
    ev.preventDefault()
    armOrCancelOnEsc()
    return
  }
  // 空输入框按 ↑ 回溯编辑上一条发出的用户消息
  if (ev.key === 'ArrowUp' && !draft.value && !ev.shiftKey && !ev.ctrlKey && !ev.metaKey && !ev.isComposing) {
    const lastUser = [...effectiveMessages.value].reverse().find(m => m.role === 'user' && m.text.trim())
    if (lastUser) {
      ev.preventDefault()
      draft.value = lastUser.text
      void nextTick(() => {
        const ta = textareaRef.value
        if (ta) {
          ta.focus()
          ta.setSelectionRange(ta.value.length, ta.value.length)
        }
      })
      return
    }
  }
  if (ev.key === 'Enter' && !ev.isComposing) {
    const wantsCtrlEnter = fleet.sendShortcut === 'ctrl-enter'
    const shouldSend = wantsCtrlEnter
      ? (ev.ctrlKey || ev.metaKey) && !ev.shiftKey
      : !ev.shiftKey && !ev.altKey
    if (shouldSend) {
      ev.preventDefault()
      void handleSubmit()
    }
  }
}

function handleApproval(callId: string, decision: ApprovalDecision) {
  fleet.respondPermission(callId, decision)
}

function toggleThought(key: string, ev: Event) {
  const el = ev.target as HTMLDetailsElement | null
  if (!el) return
  const isOpen = Boolean(el.open)
  if (Boolean(expandedThought.value[key]) === isOpen) return
  expandedThought.value = { ...expandedThought.value, [key]: isOpen }
}

function shareAsHandoff(msg: ChatMessage, artifact?: ArtifactRef) {
  emit('openHandoff', { summary: msg.text.slice(0, 1200), artifact })
}

const queuedThumbUrls = ref<Map<File, string>>(new Map())
const lightboxEl = ref<HTMLDialogElement | null>(null)
const lightboxSrc = ref('')
const lightboxAlt = ref('')
const copiedMsgId = ref<string | null>(null)
let msgCopyTimer: ReturnType<typeof setTimeout> | null = null

watch(
  queuedFiles,
  files => {
    const prev = queuedThumbUrls.value
    const next = new Map<File, string>()
    const keep = new Set(files)
    for (const [f, url] of prev.entries()) {
      if (keep.has(f)) next.set(f, url)
      else if (typeof URL !== 'undefined') URL.revokeObjectURL(url)
    }
    for (const f of files) {
      if (f.type.startsWith('image/') && !next.has(f) && typeof URL !== 'undefined') {
        next.set(f, URL.createObjectURL(f))
      }
    }
    queuedThumbUrls.value = next
  },
  { immediate: true },
)

function queuedFileThumb(file: File): string | undefined {
  return queuedThumbUrls.value.get(file)
}

function openImageLightbox(src: string, alt: string) {
  lightboxSrc.value = src
  lightboxAlt.value = alt
  void nextTick(() => {
    lightboxEl.value?.showModal()
  })
}

function cleanMediaFileName(raw?: string): string {
  const s = (raw || '').trim()
  if (!s) return 'download'
  return s.replace(/\\/g, '/').split('/').pop() || s
}

function triggerBrowserDownload(url: string, fileName: string) {
  if (!url || typeof document === 'undefined') return
  const cleanName = cleanMediaFileName(fileName)
  const a = document.createElement('a')
  a.href = url
  a.download = cleanName
  a.target = '_blank'
  a.rel = 'noopener noreferrer'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  emit('action', `正在下载 ${cleanName}`)
}

function downloadLightboxImage() {
  if (!lightboxSrc.value) return
  triggerBrowserDownload(lightboxSrc.value, lightboxAlt.value || 'image.png')
}

function onLightboxClose() {
  lightboxSrc.value = ''
  lightboxAlt.value = ''
}

function onLightboxBackdropFallback(event: MouseEvent) {
  const dialog = lightboxEl.value
  if (!dialog || event.target !== dialog) return
  const rect = dialog.getBoundingClientRect()
  const inside = rect.top <= event.clientY && event.clientY <= rect.top + rect.height
    && rect.left <= event.clientX && event.clientX <= rect.left + rect.width
  if (!inside) dialog.close()
}

let hasLightboxClickFallback = false
onMounted(() => {
  const dialog = lightboxEl.value
  if (dialog && typeof HTMLDialogElement !== 'undefined' && !('closedBy' in HTMLDialogElement.prototype)) {
    dialog.addEventListener('click', onLightboxBackdropFallback)
    hasLightboxClickFallback = true
  }
})

onUnmounted(() => {
  if (speechInst && speechActive.value) {
    try { speechInst.stop() } catch { /* ignore */ }
  }
  if (msgCopyTimer) clearTimeout(msgCopyTimer)
  if (escConfirmTimer) clearTimeout(escConfirmTimer)
  if (filesFetchTimer) clearTimeout(filesFetchTimer)
  if (hasLightboxClickFallback) {
    lightboxEl.value?.removeEventListener('click', onLightboxBackdropFallback)
  }
  for (const url of queuedThumbUrls.value.values()) {
    if (typeof URL !== 'undefined') URL.revokeObjectURL(url)
  }
  queuedThumbUrls.value.clear()
})

function formatMsgTime(ts: number): string {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

async function copyMessageText(msg: ChatMessage) {
  if (!msg.text || !navigator.clipboard?.writeText) return
  try {
    await navigator.clipboard.writeText(msg.text)
    copiedMsgId.value = msg.id
    if (msgCopyTimer) clearTimeout(msgCopyTimer)
    msgCopyTimer = setTimeout(() => {
      copiedMsgId.value = null
      msgCopyTimer = null
    }, 1500)
  } catch {
    emit('action', '剪贴板写入失败，请手动选中复制')
  }
}

async function retryTurn(msg: ChatMessage) {
  if (sending.value || isStreaming.value) return
  const msgs = effectiveMessages.value
  let promptText = ''
  if (msg.role === 'user') {
    promptText = msg.text
  } else {
    const idx = msgs.findIndex(m => m.id === msg.id)
    for (let i = idx - 1; i >= 0; i -= 1) {
      if (msgs[i].role === 'user' && msgs[i].text.trim()) {
        promptText = msgs[i].text
        break
      }
    }
  }
  if (!promptText.trim()) return
  sending.value = true
  try {
    if (effectiveKey.value && fleet.sessionsByKey[effectiveKey.value]) {
      await fleet.sendPromptToSpecificSession(effectiveKey.value, promptText, [], { ...options.value })
    } else {
      await fleet.sendPrompt(promptText, [], { ...options.value })
    }
  } catch (err) {
    emit('action', err instanceof Error ? err.message : '重新发送失败')
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <div
    ref="threadRootRef"
    class="thread-root"
    :class="{ 'thread-compact': compact, 'thread-mobile': mobile }"
    :data-bubble-style="bubbleStyle"
    @keydown="handleThreadKeydown"
  >
    <div v-if="searchOpen" class="thread-search-bar" role="search" aria-label="在当前对话中搜索">
      <OpusIcon name="search" class="ts-ic" />
      <input
        ref="searchInputRef"
        v-model="searchQuery"
        type="search"
        class="ts-input"
        placeholder="搜索本会话文本、思考过程或工具输出…"
        aria-label="搜索对话内容"
        @keydown.enter.exact.prevent="stepSearchMatch(1)"
        @keydown.shift.enter.prevent="stepSearchMatch(-1)"
        @keydown.esc.prevent="closeThreadSearch"
      />
      <span class="ts-count num">
        {{ searchMatches.length ? `${searchActiveIdx + 1} / ${searchMatches.length}` : searchQuery.trim() ? '0 / 0' : '' }}
      </span>
      <button
        type="button"
        class="icon-btn ts-nav-btn"
        title="上一个匹配 (Shift+Enter)"
        aria-label="上一个匹配"
        :disabled="!searchMatches.length"
        @click="stepSearchMatch(-1)"
      ><OpusIcon name="arrowUp" /></button>
      <button
        type="button"
        class="icon-btn ts-nav-btn"
        title="下一个匹配 (Enter)"
        aria-label="下一个匹配"
        :disabled="!searchMatches.length"
        @click="stepSearchMatch(1)"
      ><OpusIcon name="arrowDown" /></button>
      <button
        type="button"
        class="icon-btn ts-nav-btn"
        title="关闭搜索 (Esc)"
        aria-label="关闭搜索"
        @click="closeThreadSearch"
      ><OpusIcon name="x" /></button>
    </div>

    <div v-if="bookmarkedMessages.length && !compact" class="bookmark-strip" aria-label="本会话已收藏的消息书签">
      <span class="bm-lead">
        <OpusIcon name="sparkle" />
        <span>书签</span>
      </span>
      <div class="bm-chips">
        <button
          v-for="(bm, bIdx) in bookmarkedMessages"
          :key="bm.id"
          type="button"
          class="bm-chip"
          :title="bm.text.slice(0, 140)"
          @click="scrollToMessage(bm.id)"
        >
          <span>#{{ bIdx + 1 }} · {{ (bm.text || bm.error || '消息').replace(/\s+/g, ' ').slice(0, 18) }}</span>
        </button>
      </div>
    </div>

    <div
      ref="listEl"
      tabindex="-1"
      :class="mobile ? 'mmsgs' : 'msgs'"
      @scroll.passive="trackMessageScroll"
      @mouseup="handleMessageSelection"
      @keyup="handleMessageSelection"
    >
      <div ref="innerListEl" :class="mobile ? 'mmsgs-inner' : 'msgs-inner'">
        <div v-if="effectiveKey && effectiveMessages.length >= 50" class="older-history-bar">
          <button
            type="button"
            class="older-history-btn"
            @click="fleet.requestOlderHistory(effectiveKey)"
          >
            <OpusIcon name="history" />
            <span>加载更早历史消息</span>
          </button>
        </div>

        <div v-if="!effectiveMessages.length" class="thread-empty">
          <div class="thread-empty-ic" :class="getProviderMeta(effectiveProvider).accentClass">
            <OpusIcon :name="getProviderMeta(effectiveProvider).icon" />
          </div>
          <h4>
            {{ effectiveNode ? `与 ${getProviderMeta(effectiveProvider).label} 开始会话` : '尚未选定在线控制节点' }}
          </h4>
          <p v-if="effectiveNode">
            {{
              effectiveNode.status === 'online'
                ? '输入任务，输入 @ 引用文件，或输入 / 调用指令与 /btw 侧边问答。'
                : '目标节点当前离线，请确认宿主机已启动 Studiolo AgentNode。'
            }}
          </p>
          <p v-else>前往「设置 -> Agent 与连接」添加控制节点，发放 sn_live_ 凭证并在目标机器启动 agent-node。</p>
        </div>

        <template v-for="(msg, msgIdx) in effectiveMessages" :key="msg.id">
          <div v-if="firstUnreadMsgId && msg.id === firstUnreadMsgId" class="unread-divider" role="separator">
            <span>新消息</span>
          </div>

          <div
            v-if="msg.role === 'system'"
            :data-msg-id="msg.id"
            class="sys-notice"
            :class="{
              'is-search-hit': highlightedMsgId === msg.id,
              'is-deferred-msg': msgIdx < effectiveMessages.length - 8,
            }"
          >
            <OpusIcon name="info" />
            <span>{{ msg.text }}</span>
          </div>

          <div
            v-else-if="msg.role === 'user' || msg.streaming || msg.text || msg.thought || msg.toolCalls?.length || msg.parts?.length || msg.error || msg.forms?.length || msg.approvals?.length || msg.artifacts?.length || msg.media?.length"
            :data-msg-id="msg.id"
            :class="[
              mobile ? 'mmsg' : 'msg',
              msg.role === 'user' ? 'user' : 'agent',
              getProviderMeta(msg.provider).accentClass,
              {
                'is-search-hit': highlightedMsgId === msg.id,
                'is-deferred-msg': msgIdx < effectiveMessages.length - 8,
              },
            ]"
          >
            <template v-if="msg.role === 'user'">
              <div class="user-col">
                <div class="bubble">
                  <template
                    v-for="(uSeg, uIdx) in splitTextByInlineMedia(
                      msg.text || '',
                      collectMessageInlineAttachments(msg, fleet.imagePreviewByArtifactId),
                      { allowTrailingUnmatched: true },
                    ).segments"
                    :key="`${msg.id}-useg-${uIdx}`"
                  >
                    <div v-if="uSeg.type === 'text'" class="msg-text">{{ uSeg.text }}</div>
                    <InlineAttachmentCard
                      v-else
                      :attachment="uSeg.attachment"
                      :compact="compact"
                      @preview-image="openImageLightbox"
                      @open-file="fp => emit('openFile', fp)"
                      @handoff="art => shareAsHandoff(msg, art)"
                      @status="emit('action', $event)"
                    />
                  </template>
                </div>

                <div class="user-foot">
                  <div v-if="msg.branches && msg.branches.length > 1" class="branch-switcher">
                    <button
                      type="button"
                      class="branch-nav-btn"
                      aria-label="上一分支"
                      :disabled="(msg.activeBranchIndex ?? 0) <= 0 || isStreaming"
                      @click="fleet.switchBranch(effectiveKey, msgIdx, (msg.activeBranchIndex ?? 0) - 1)"
                    >‹</button>
                    <span class="num">{{ (msg.activeBranchIndex ?? 0) + 1 }} / {{ msg.branches.length }}</span>
                    <button
                      type="button"
                      class="branch-nav-btn"
                      aria-label="下一分支"
                      :disabled="(msg.activeBranchIndex ?? 0) >= msg.branches.length - 1 || isStreaming"
                      @click="fleet.switchBranch(effectiveKey, msgIdx, (msg.activeBranchIndex ?? 0) + 1)"
                    >›</button>
                  </div>
                  <div class="user-hover-actions">
                    <button
                      v-if="msg.text"
                      type="button"
                      class="btn btn-subtle btn-sm"
                      :class="{ 'is-copied': copiedMsgId === msg.id }"
                      @click="copyMessageText(msg)"
                    >
                      <OpusIcon :name="copiedMsgId === msg.id ? 'check' : 'copy'" />
                      <span>{{ copiedMsgId === msg.id ? '已复制' : '复制' }}</span>
                    </button>
                    <button
                      v-if="!compact && effectiveKey && fleet.sessionsByKey[effectiveKey]"
                      type="button"
                      class="btn btn-subtle btn-sm"
                      @click="handleForkAt(msgIdx)"
                    >
                      <OpusIcon name="branch" />
                      <span>分支</span>
                    </button>
                  </div>
                </div>
              </div>
            </template>

            <template v-else>
              <span v-if="!mobile" class="am" :title="getProviderMeta(msg.provider).label">
                <OpusIcon :name="getProviderMeta(msg.provider).icon" />
              </span>
              <div class="agent-col">
                <div class="bubble">
                  <template v-if="buildTurnRenderItems(msg, fleet.imagePreviewByArtifactId).length">
                    <div class="msg-parts">
                      <template
                        v-for="item in buildTurnRenderItems(msg, fleet.imagePreviewByArtifactId)"
                        :key="item.id"
                      >
                        <details
                          v-if="item.type === 'thought'"
                          class="thought-box thought-light"
                          :open="Boolean(expandedThought[item.id])"
                          @toggle="toggleThought(item.id, $event)"
                        >
                          <summary>
                            <OpusIcon name="chevR" class="thought-chev" />
                            <span class="thought-lbl">
                              {{ msg.streaming && item.isLast ? '思考中' : '思考过程' }}
                            </span>
                            <span class="thought-cnt num">{{ item.text.length }} 字</span>
                            <span
                              v-if="!expandedThought[item.id] && msg.streaming && item.isLast"
                              class="thought-live-preview"
                            >{{ thoughtPreviewLine(item.text) }}</span>
                          </summary>
                          <div class="thought-body">{{ item.text }}</div>
                        </details>
                        <ToolRunGroup
                          v-else-if="item.type === 'tool-group'"
                          :group="item.group"
                          @open-file="fp => emit('openFile', fp)"
                          @open-subagent="sid => emit('openSubagent', sid)"
                        />
                        <ToolCallCard
                          v-else-if="item.type === 'tool'"
                          :tool="item.tool"
                          @open-file="fp => emit('openFile', fp)"
                          @open-subagent="sid => emit('openSubagent', sid)"
                        />
                        <MarkdownMessage
                          v-else-if="item.type === 'text' && item.text"
                          :text="item.text"
                          :streaming="msg.streaming && item.isLast"
                          :known-files="knownFilesSet"
                          @open-file="(fp, ln) => emit('openFile', fp, ln)"
                        />
                        <InlineAttachmentCard
                          v-else-if="item.type === 'media'"
                          :attachment="item.attachment"
                          :compact="compact"
                          @preview-image="openImageLightbox"
                          @open-file="fp => emit('openFile', fp)"
                          @handoff="art => shareAsHandoff(msg, art)"
                          @status="emit('action', $event)"
                        />
                      </template>
                    </div>
                  </template>
                  <div v-else-if="msg.streaming" class="typing" aria-label="思考与输出中"><i></i><i></i><i></i></div>

                  <FormQuestionCard
                    v-for="frm in msg.forms"
                    :key="frm.formId"
                    :form="frm"
                    @submit="(fid, ans) => fleet.replyForm(fid, ans, false)"
                    @cancel="fid => fleet.replyForm(fid, undefined, true)"
                  />

                  <div v-if="msg.error" class="state warn error-card-wrap">
                    <div class="error-card-top">
                      <OpusIcon name="alert" />
                      <span>{{ msg.error }}</span>
                    </div>
                    <div v-if="isQuotaOrModelError(msg.error) && fallbackModels.length && !isStreaming" class="error-rescue-row">
                      <span class="error-rescue-lbl">切换可用模型并重试：</span>
                      <button
                        v-for="fm in fallbackModels"
                        :key="fm.id"
                        type="button"
                        class="btn btn-subtle btn-sm"
                        @click="switchModelAndRetry(fm.id, msgIdx)"
                      >
                        <span>{{ fm.label }}</span>
                      </button>
                    </div>
                  </div>

                  <PermissionRequestCard
                    v-for="card in msg.approvals"
                    :key="card.callId"
                    :card="card"
                    @respond="handleApproval"
                  />
                </div>

                <div
                  v-if="msg.role === 'assistant' && !msg.streaming && (msg.text || msg.error || msg.checkpointId || msg.diffSummary?.filesChanged)"
                  class="msg-foot msg-foot--outside"
                >
                  <span v-if="msg.createdAt" class="msg-time num" :title="usageTooltip">
                    {{ formatMsgTime(msg.createdAt) }}
                    <template v-if="msg.modelLabel"> · {{ msg.modelLabel }}</template>
                    <template v-if="formatDurationShort(msg.durationMs)"> · {{ formatDurationShort(msg.durationMs) }}</template>
                    <template v-if="msg.turnTokens"> · {{ formatTokenCount(msg.turnTokens) }} tok</template>
                  </span>
                  <div v-if="msg.checkpointId || msg.diffSummary?.filesChanged" class="turn-diff-bar">
                    <button
                      type="button"
                      class="diff-pill num"
                      title="在右侧检查代码改动详情"
                      @click="inspectTurnDiff(msg.checkpointId)"
                    >
                      <OpusIcon name="branch" />
                      <span>+{{ msg.diffSummary?.additions ?? 0 }} -{{ msg.diffSummary?.deletions ?? 0 }}</span>
                      <span>· {{ msg.diffSummary?.filesChanged ?? 0 }} 文件</span>
                    </button>
                    <button
                      v-if="msg.checkpointId && !isCheckpointReverted(msg.checkpointId)"
                      type="button"
                      class="btn btn-subtle btn-sm"
                      title="撤销本轮产生的代码改动"
                      @click="handleRevertCheckpoint(msg.checkpointId)"
                    >
                      <OpusIcon name="history" />
                      <span>回滚此轮</span>
                    </button>
                    <span v-else-if="msg.checkpointId" class="reverted-tag">已回滚</span>
                  </div>
                  <div class="msg-foot-actions">
                    <button
                      v-if="msg.text"
                      type="button"
                      class="btn btn-subtle btn-sm"
                      :class="{ 'is-copied': copiedMsgId === msg.id }"
                      @click="copyMessageText(msg)"
                    >
                      <OpusIcon :name="copiedMsgId === msg.id ? 'check' : 'copy'" />
                      <span>{{ copiedMsgId === msg.id ? '已复制' : '复制' }}</span>
                    </button>
                    <button
                      type="button"
                      class="btn btn-subtle btn-sm"
                      :disabled="sending || isStreaming"
                      @click="handleRegenerate(msgIdx)"
                    >
                      <OpusIcon name="sync" />
                      <span>重生成</span>
                    </button>
                    <button
                      v-if="!compact && effectiveKey && fleet.sessionsByKey[effectiveKey]"
                      type="button"
                      class="btn btn-subtle btn-sm"
                      @click="handleForkAt(msgIdx)"
                    >
                      <OpusIcon name="branch" />
                      <span>分支</span>
                    </button>
                    <button
                      type="button"
                      class="btn btn-subtle btn-sm msg-foot-secondary"
                      :class="{ 'is-bookmarked': isMessageBookmarked(msg.id) }"
                      :title="isMessageBookmarked(msg.id) ? '取消本条消息书签' : '添加内存书签以便快速回看（仅当前会话内存保存）'"
                      @click="toggleBookmark(msg.id)"
                    >
                      <OpusIcon name="sparkle" />
                      <span>{{ isMessageBookmarked(msg.id) ? '已收藏' : '收藏' }}</span>
                    </button>
                    <button
                      v-if="msg.text && !compact"
                      type="button"
                      class="btn btn-subtle btn-sm msg-foot-secondary"
                      @click="shareAsHandoff(msg)"
                    >
                      <OpusIcon name="send" />
                      <span>交接会话</span>
                    </button>
                  </div>
                </div>
              </div>
            </template>
          </div>
        </template>
      </div>
    </div>

    <!-- 右侧隐形对话大纲轨（>= 3 轮时出现，悬停轻柔展开） -->
    <MessageRail
      v-if="!mobile && !compact"
      :messages="effectiveMessages"
      :active-msg-id="highlightedMsgId"
      @jump="id => scrollToMessage(id)"
    />

    <!-- 划词引用浮层（Selection Quote） -->
    <button
      v-if="selectionQuote"
      type="button"
      class="sel-quote-pill"
      :style="{ top: `${selectionQuote.top}px`, left: `${selectionQuote.left}px` }"
      @mousedown.prevent="applySelectionQuote"
    >
      <OpusIcon name="chat" />
      <span>引用追问</span>
    </button>

    <div :class="mobile ? 'mcomposer' : 'composer'">
      <!-- 上翻离开底部时浮现在输入区上沿的一键回到底部小按钮（绝不被模型栏或输入区遮挡） -->
      <Transition name="jump-pill">
        <button
          v-if="!followLatest && effectiveMessages.length > 0"
          ref="jumpBtnRef"
          type="button"
          class="jump-latest-pill"
          :class="{ 'is-mobile-circle': mobile && unseenBelowCount === 0 }"
          aria-label="回到底部查看最新消息"
          title="回到底部"
          @click="scrollToBottomSmooth"
        >
          <OpusIcon name="arrowDown" />
          <span v-if="!mobile || unseenBelowCount > 0">{{ unseenBelowCount > 0 ? `新回复 (${unseenBelowCount})` : '回到底部' }}</span>
        </button>
      </Transition>

      <div v-if="isInterrupted && !isStreaming && effectiveKey" class="interrupted-bar">
        <span class="interrupted-txt">上次生成已中断</span>
        <button
          type="button"
          class="btn btn-subtle btn-sm"
          @click="fleet.continueInterruptedRun(effectiveKey)"
        >
          <OpusIcon name="play" />
          <span>继续完成</span>
        </button>
      </div>

      <SessionTodoBar
        v-if="!compact"
        :items="effectiveTodos"
        :streaming="isStreaming"
        @execute-plan="handleExecutePlan"
      />

      <div v-if="effectiveQueue.length" class="follow-queue">
        <div class="queue-hdr">
          <OpusIcon name="tasks" class="queue-ic" />
          <span>待发队列 ({{ effectiveQueue.length }}) · 当前轮次完成后自动依次执行</span>
        </div>
        <div class="queue-items">
          <div v-for="(item, qIdx) in effectiveQueue" :key="item.id" class="queue-row">
            <template v-if="editingQueueId === item.id">
              <input
                v-model="editingQueueText"
                type="text"
                class="input queue-edit-input"
                aria-label="编辑排队指令"
                @keydown.enter.prevent="commitEditQueued(item.id)"
                @keydown.esc.prevent="editingQueueId = null"
              />
              <button type="button" class="btn btn-primary btn-sm" @click="commitEditQueued(item.id)">保存</button>
            </template>
            <template v-else>
              <span class="queue-text" :title="item.text">
                {{ item.text }}
                <em v-if="item.files?.length" class="queue-att-badge">📎{{ item.files.length }}</em>
              </span>
              <button
                v-if="effectiveQueue.length > 1"
                type="button"
                class="icon-btn queue-icon-btn"
                aria-label="上移优先级"
                title="上移"
                :disabled="qIdx === 0"
                @click="fleet.reorderQueuedPrompt(effectiveKey, item.id, -1)"
              ><OpusIcon name="arrowUp" /></button>
              <button
                v-if="effectiveQueue.length > 1"
                type="button"
                class="icon-btn queue-icon-btn"
                aria-label="下移优先级"
                title="下移"
                :disabled="qIdx === effectiveQueue.length - 1"
                @click="fleet.reorderQueuedPrompt(effectiveKey, item.id, 1)"
              ><OpusIcon name="arrowDown" /></button>
              <button
                type="button"
                class="btn btn-subtle btn-sm"
                title="打断当前生成并立即优先发送这条指令"
                @click="fleet.steerQueuedPrompt(effectiveKey, item.id)"
              >立即插队</button>
              <button
                type="button"
                class="icon-btn queue-icon-btn"
                aria-label="编辑排队内容"
                title="编辑"
                @click="startEditQueued(item.id, item.text)"
              ><OpusIcon name="pencil" /></button>
              <button
                type="button"
                class="icon-btn queue-icon-btn"
                aria-label="移出待发队列"
                title="删除"
                @click="fleet.removeQueuedPrompt(effectiveKey, item.id)"
              ><OpusIcon name="x" /></button>
            </template>
          </div>
        </div>
      </div>

      <div v-if="escConfirmArmed && isStreaming" class="esc-arm-banner" role="status">
        <span>再按一次 <kbd>Esc</kbd> 中止当前生成</span>
        <button type="button" class="btn btn-subtle btn-sm" @click="stopStreamingRun(); escConfirmArmed = false">立即停止</button>
      </div>

      <ChangedFilesSummaryBar
        v-if="!compact"
        :diff="effectiveDiff"
        :worktree-name="currentWorktreeName"
        @review="fp => emit('openDiff', fp)"
      />

      <!-- 移动端极简运行配置栏：左右紧凑图标钮（模式 / 权限），中间模型选择拉长 -->
      <div v-if="mobile" class="m-status-strip" role="toolbar" aria-label="移动端运行配置">
        <button
          type="button"
          class="m-status-icon-btn"
          :class="{ 'is-accent': composerMode === 'plan' }"
          :title="composerMode === 'plan' ? 'Plan 方案模式（点击切回 Build）' : 'Build 执行模式（点击切换 Plan）'"
          :aria-label="composerMode === 'plan' ? 'Plan 方案模式' : 'Build 执行模式'"
          @click="setMode(composerMode === 'plan' ? 'build' : 'plan')"
        >
          <OpusIcon :name="composerMode === 'plan' ? 'note' : 'zap'" />
        </button>
        <button
          ref="modelTriggerRef"
          type="button"
          class="m-status-pill m-status-pill--model"
          :aria-label="`选择模型：${model?.label || options.model || '默认模型'}`"
          :aria-expanded="settingsOpen && panel === 'model'"
          @pointerdown="noteTriggerPointerDown('model')"
          @click="showPanel('model', $event)"
        >
          <span class="m-pill-text">{{ model?.label || options.model || '默认模型' }}</span>
          <span
            v-if="model?.provider && !model.label.startsWith(model.provider)"
            class="trigger-provider m-pill-provider"
            :title="`provider: ${model.provider}`"
          >{{ model.provider }}</span>
          <span v-if="triggerEffortLabel" class="m-pill-sub">{{ triggerEffortLabel }}</span>
          <OpusIcon name="chevD" class="m-pill-chev" />
        </button>
        <button
          type="button"
          class="m-status-icon-btn"
          :class="`is-perm-${permissionMode}`"
          :title="`${permissionLabel} · 点击切换权限`"
          :aria-label="`执行权限：${permissionLabel}`"
          :aria-expanded="settingsOpen && panel === 'permissions'"
          @pointerdown="noteTriggerPointerDown('permissions')"
          @click="showPanel('permissions', $event)"
        >
          <OpusIcon :name="permissionIcon" />
        </button>
      </div>

      <input ref="fileInputRef" type="file" multiple hidden @change="handleFileSelect" />
      <div
        :class="[
          mobile ? 'box' : 'composer-box',
          { disabled: !effectiveNode || effectiveNode.status !== 'online', 'is-dragging': draggingFiles },
        ]"
        @dragover.prevent="draggingFiles = true"
        @dragleave.self="draggingFiles = false"
        @drop.prevent="handleFileDrop"
      >
        <div
          v-if="autocompleteOpen"
          :id="mentionListId"
          class="mention-popover"
          role="listbox"
          :aria-label="mentionMode === 'slash' ? '斜杠命令列表' : '引用工作区文件与上下文'"
        >
          <button
            v-for="(opt, idx) in suggestOptions"
            :id="`${mentionListId}-opt-${idx}`"
            :key="opt.id"
            type="button"
            role="option"
            class="mention-option"
            :class="{ 'is-active': idx === activeSuggestIdx }"
            :aria-selected="idx === activeSuggestIdx"
            @mousedown.prevent="applyAutocompleteOption(opt)"
          >
            <OpusIcon :name="opt.icon" class="mention-ic" />
            <span class="mention-title">{{ opt.title }}</span>
            <span class="mention-desc">{{ opt.desc }}</span>
          </button>
        </div>

        <div class="composer-editor">
          <TransitionGroup name="attachment" tag="div" class="queued-files">
            <span v-for="(file, idx) in queuedFiles" :key="`file-${file.name}-${idx}`" class="chip" :class="{ 'chip--image': Boolean(queuedFileThumb(file)) }">
              <button
                v-if="queuedFileThumb(file)"
                type="button"
                class="chip-thumb-btn"
                :title="`查看大图：${file.name}`"
                @click="openImageLightbox(queuedFileThumb(file)!, file.name)"
              >
                <img :src="queuedFileThumb(file)" :alt="file.name" class="chip-thumb" />
              </button>
              <OpusIcon v-else name="clip" />
              <span class="attachment-name" :title="file.name">{{ file.name }} ({{ formatBytes(file.size) }})</span>
              <button type="button" class="chip-x" aria-label="移除附件" @click="removeQueuedFile(idx)">×</button>
            </span>
            <span v-for="ctx in queuedContexts" :key="ctx.id" class="chip chip--context" :title="ctx.payload">
              <OpusIcon :name="ctx.icon" /><span class="attachment-name">{{ ctx.label }}</span>
              <button type="button" class="chip-x" aria-label="移除上下文" @click="removeQueuedContext(ctx.id)">×</button>
            </span>
            <span
              v-for="pb in queuedPastedBlocks"
              :key="pb.id"
              class="chip chip--paste"
              :title="`点击预览粘贴内容（${pb.lineCount} 行 · ${pb.charCount} 字）`"
            >
              <button type="button" class="chip-paste-trigger" @click="previewingPasteBlock = previewingPasteBlock?.id === pb.id ? null : pb">
                <OpusIcon name="note" />
                <span class="attachment-name">{{ pb.title }} · {{ pb.lineCount }} 行</span>
              </button>
              <button type="button" class="chip-x" aria-label="移除粘贴文本块" @click="removePastedBlock(pb.id)">×</button>
            </span>
          </TransitionGroup>
          <div v-if="previewingPasteBlock" class="paste-preview-box">
            <div class="paste-preview-hdr">
              <span>粘贴文本预览 · {{ previewingPasteBlock.lineCount }} 行 ({{ previewingPasteBlock.charCount }} 字)</span>
              <button type="button" class="chip-x" @click="previewingPasteBlock = null">×</button>
            </div>
            <pre class="paste-preview-body">{{ previewingPasteBlock.content.slice(0, 2400) }}{{ previewingPasteBlock.content.length > 2400 ? '\n…' : '' }}</pre>
          </div>
          <div v-if="speechActive && speechInterim" class="speech-interim-bar">
            <span class="speech-dot" aria-hidden="true" />
            <span>{{ speechInterim }}</span>
          </div>

          <!-- 移动端极简 3 控件输入行：左 + / 中自适应多行输入 / 右发送 -->
          <div v-if="mobile" class="m-composer-bar">
            <button
              type="button"
              class="m-add-btn"
              :class="{ 'is-active-trigger': settingsOpen && panel === 'attach' }"
              aria-label="添加文件、引用或指令"
              aria-haspopup="dialog"
              :aria-controls="settingsId"
              :aria-expanded="settingsOpen && panel === 'attach'"
              @pointerdown="noteTriggerPointerDown('attach')"
              @click="showPanel('attach', $event)"
            >
              <OpusIcon name="plus" />
            </button>
            <div class="editor-field m-editor-field">
              <div v-if="!supportsFieldSizing" ref="draftMeasure" class="draft-measure" aria-hidden="true">{{ draft + '\u200b' }}</div>
              <textarea
                ref="textareaRef"
                v-model="draft"
                class="composer-input m-auto-input"
                :style="!supportsFieldSizing && editorHeight ? { height: `${editorHeight}px` } : undefined"
                :placeholder="effectiveNode ? `向 ${getProviderMeta(effectiveProvider).label} 发送任务…` : '暂无在线节点…'"
                aria-label="任务内容"
                :aria-expanded="autocompleteOpen"
                :aria-controls="autocompleteOpen ? mentionListId : undefined"
                :aria-activedescendant="autocompleteOpen ? `${mentionListId}-opt-${activeSuggestIdx}` : undefined"
                rows="1"
                @input="updateMentionTrigger"
                @click="updateMentionTrigger"
                @keydown="handleKeydown"
                @paste="handleComposerPaste"
              />
            </div>
            <button
              v-if="isStreaming && (draft.trim() || queuedFiles.length || queuedContexts.length || queuedPastedBlocks.length)"
              type="button"
              class="btn btn-subtle btn-sm m-queue-btn"
              @click="handleSubmit"
            >排队</button>
            <button
              type="button"
              class="send m-send-btn"
              :class="{ stop: isStreaming }"
              :disabled="sending || (!isStreaming && !draft.trim() && !queuedFiles.length && !queuedContexts.length && !queuedPastedBlocks.length)"
              :aria-label="isStreaming ? '中止当前生成' : '发送消息'"
              @click="isStreaming ? stopStreamingRun() : handleSubmit()"
            >
              <Transition name="send-icon">
                <OpusIcon :key="String(isStreaming)" :name="isStreaming ? 'stop' : 'arrowUp'" />
              </Transition>
            </button>
          </div>

          <div v-else class="editor-field">
            <div ref="draftMeasure" class="draft-measure" aria-hidden="true">{{ draft + '\u200b' }}</div>
            <textarea ref="textareaRef" v-model="draft" class="composer-input" :style="{ height: editorHeight ? `${editorHeight}px` : undefined }"
              :placeholder="effectiveNode ? `向 ${effectiveNode.name} 描述任务… (${fleet.sendShortcut === 'ctrl-enter' ? 'Ctrl+Enter 发送' : 'Enter 发送'} · @ 文件 · / 指令)` : '暂无在线节点…'"
              aria-label="任务内容"
              :title="fleet.sendShortcut === 'ctrl-enter' ? 'Ctrl/Cmd+Enter 发送，Enter 换行，空框按 ↑ 编辑上条' : 'Enter 发送，Shift+Enter 换行，空框按 ↑ 编辑上条'"
              :aria-expanded="autocompleteOpen"
              :aria-controls="autocompleteOpen ? mentionListId : undefined"
              :aria-activedescendant="autocompleteOpen ? `${mentionListId}-opt-${activeSuggestIdx}` : undefined"
              rows="1"
              @input="updateMentionTrigger"
              @click="updateMentionTrigger"
              @keydown="handleKeydown"
              @paste="handleComposerPaste" />
          </div>
        </div>
        <div v-if="!mobile" class="composer-row">
          <button
            type="button"
            class="icon-btn"
            :class="{ 'is-active-trigger': settingsOpen && panel === 'attach' }"
            title="添加上下文、文件或快捷指令"
            aria-label="添加上下文"
            aria-haspopup="dialog"
            :aria-controls="settingsId"
            :aria-expanded="settingsOpen && panel === 'attach'"
            @pointerdown="noteTriggerPointerDown('attach')"
            @click="showPanel('attach', $event)"
          >
            <OpusIcon name="plus" />
          </button>
          <div v-if="!compact" class="mode-seg" role="group" aria-label="对话执行模式">
            <button
              type="button"
              class="mode-seg-btn"
              :class="{ 'is-active': composerMode === 'build' }"
              title="Build 模式：直接编码与执行任务"
              @click="setMode('build')"
            >Build</button>
            <button
              type="button"
              class="mode-seg-btn"
              :class="{ 'is-active': composerMode === 'plan' }"
              title="Plan 模式：先输出分步方案，确认后再修改代码"
              @click="setMode('plan')"
            >Plan</button>
          </div>
          <span class="trigger-wrap">
            <button
              ref="modelTriggerRef"
              class="model-trigger"
              type="button"
              :aria-label="`选择模型：${model?.label || '默认模型'}${triggerEffortLabel ? ' ' + triggerEffortLabel : ''}`"
              aria-haspopup="dialog"
              :aria-controls="settingsId"
              :aria-expanded="settingsOpen && panel === 'model'"
              @pointerdown="noteTriggerPointerDown('model')"
              @click="showPanel('model', $event)"
            >
              <span class="trigger-label">{{ model?.label || options.model || '默认模型' }}</span>
              <span
                v-if="model?.provider && !model.label.startsWith(model.provider)"
                class="trigger-provider"
                :title="`provider: ${model.provider}`"
              >{{ model.provider }}</span>
              <span v-if="triggerEffortLabel" class="trigger-effort">{{ triggerEffortLabel }}</span>
              <OpusIcon name="chevD" class="trigger-chev" />
            </button>
            <span v-if="!mobile && !settingsOpen" class="trigger-tip" role="tooltip">选择模型 <kbd>Ctrl+/</kbd></span>
          </span>
          <span class="spacer" />
          <button
            v-if="untrimmedFileRef && !mobile"
            type="button"
            class="draft-trim-pill"
            :title="`将 @${untrimmedFileRef} 裁剪为前 200 行引用以节省上下文 Token`"
            @click="trimFirstFileCitation"
          >
            <OpusIcon name="braces" />
            <span>裁行 L1-200</span>
          </button>
          <span
            v-if="estimatedDraftTokens > 0 && !mobile"
            class="draft-token-pill num"
            :title="`当前草稿与附加上下文预计消耗约 ${estimatedDraftTokens} tokens`"
          >~{{ formatTokenCount(estimatedDraftTokens) }} tok</span>
          <button
            v-if="speechSupported && !mobile"
            type="button"
            class="icon-btn voice-btn"
            :class="{ 'is-recording': speechActive }"
            :title="speechActive ? '停止语音听写' : '语音输入（中文/英文识别）'"
            :aria-label="speechActive ? '停止语音输入' : '开始语音输入'"
            @click="toggleVoiceDictation"
          >
            <OpusIcon name="sparkle" />
          </button>
          <button
            type="button"
            class="safety-badge"
            :class="[`is-${permissionMode}`, { 'is-active-pill': settingsOpen && panel === 'permissions' }]"
            :aria-label="permissionLabel + ' · 沙箱与权限'"
            :title="permissionLabel + ' · 沙箱与权限'"
            aria-haspopup="dialog"
            :aria-controls="settingsId"
            :aria-expanded="settingsOpen && panel === 'permissions'"
            @pointerdown="noteTriggerPointerDown('permissions')"
            @click="showPanel('permissions', $event)"
          >
            <OpusIcon :name="permissionIcon" class="trigger-lead" />
            <span class="trigger-label">{{ permissionLabel }}</span>
            <OpusIcon name="chevD" class="trigger-chev" />
          </button>
          <button
            v-if="isStreaming && (draft.trim() || queuedFiles.length || queuedContexts.length || queuedPastedBlocks.length)"
            type="button"
            class="btn btn-subtle btn-sm queue-add-btn"
            title="加入待发队列（生成结束后自动发送）"
            @click="handleSubmit"
          >
            <OpusIcon name="plus" />
            <span>排队</span>
          </button>
          <button
            type="button"
            class="send"
            :class="{ stop: isStreaming }"
            :disabled="sending || (!isStreaming && !draft.trim() && !queuedFiles.length && !queuedContexts.length && !queuedPastedBlocks.length)"
            :aria-label="isStreaming ? '中止当前生成' : '发送消息'"
            @click="isStreaming ? stopStreamingRun() : handleSubmit()"
          >
            <Transition name="send-icon">
              <OpusIcon :key="String(isStreaming)" :name="isStreaming ? 'stop' : 'arrowUp'" />
            </Transition>
          </button>
        </div>
      </div>

      <div
        :id="settingsId"
        ref="settingsPopup"
        popover="auto"
        role="dialog"
        :aria-label="panel === 'model' ? '模型与思考强度' : panel === 'attach' ? '添加上下文' : '执行权限'"
        class="run-popover"
        :class="`is-${panel}`"
        @toggle="onPopoverToggle"
      >
        <template v-if="panel === 'attach'">
          <div class="popover-head">添加上下文</div>
          <div class="picker-list" role="group" aria-label="添加上下文" @scroll.passive="closeSubmenu">
            <button
              type="button"
              class="picker-option"
              @pointerenter="closeSubmenu"
              @click="triggerFilePick"
            >
              <OpusIcon name="clip" class="menu-lead" />
              <span class="option-title">上传加密文件</span>
              <span class="picker-effort">E2EE</span>
            </button>
            <button
              v-if="mobile"
              type="button"
              class="picker-option"
              @click="insertQuickTrigger('@')"
            >
              <OpusIcon name="file" class="menu-lead" />
              <span class="option-title">引用工作区文件</span>
              <span class="picker-effort">@</span>
            </button>
            <button
              v-if="mobile"
              type="button"
              class="picker-option"
              @click="insertQuickTrigger('/')"
            >
              <OpusIcon name="zap" class="menu-lead" />
              <span class="option-title">调用斜杠指令</span>
              <span class="picker-effort">/</span>
            </button>
            <button
              v-if="!mobile"
              type="button"
              class="picker-option"
              @pointerenter="closeSubmenu"
              @click="pasteClipboardImage"
            >
              <OpusIcon name="copy" class="menu-lead" />
              <span class="option-title">粘贴剪贴板图片</span>
              <span class="picker-effort">Ctrl+V</span>
            </button>
            <div class="picker-item">
              <button
                type="button"
                class="picker-option"
                :class="{ 'is-sub-open': hoveredAttachKey === 'dirs' || inlineAttachKey === 'dirs' }"
                data-attach-key="dirs"
                @pointerenter="onAttachRowPointerEnter('dirs', $event)"
                @pointerleave="scheduleSubClose"
                @click="toggleAttachRow('dirs', $event.currentTarget as HTMLElement)"
              >
                <OpusIcon name="file" class="menu-lead" />
                <span class="option-title">工作目录路径</span>
                <OpusIcon name="chevR" class="option-tail" />
              </button>
              <div v-if="inlineAttachKey === 'dirs'" class="effort-inline">
                <button
                  v-for="dir in directoryContextOptions"
                  :key="dir.path"
                  type="button"
                  class="picker-option"
                  :title="dir.path"
                  @click="addContextItem({ id: `dir:${dir.path}`, kind: 'dir', icon: 'file', label: dir.name, payload: `工作目录参考: ${dir.path}` })"
                >
                  <OpusIcon name="file" class="menu-lead" />
                  <span class="option-title">{{ dir.name }}</span>
                  <span v-if="dir.current" class="picker-badge">当前</span>
                </button>
                <p v-if="!directoryContextOptions.length" class="picker-footer-note"><span>当前节点尚未配置允许目录</span></p>
              </div>
            </div>
            <div class="picker-item">
              <button
                type="button"
                class="picker-option"
                :class="{ 'is-sub-open': hoveredAttachKey === 'data' || inlineAttachKey === 'data' }"
                data-attach-key="data"
                @pointerenter="onAttachRowPointerEnter('data', $event)"
                @pointerleave="scheduleSubClose"
                @click="toggleAttachRow('data', $event.currentTarget as HTMLElement)"
              >
                <OpusIcon name="data" class="menu-lead" />
                <span class="option-title">引用个人数据</span>
                <OpusIcon name="chevR" class="option-tail" />
              </button>
              <div v-if="inlineAttachKey === 'data'" class="effort-inline">
                <button
                  v-for="item in personalContextOptions"
                  :key="item.id"
                  type="button"
                  class="picker-option"
                  :title="item.payload"
                  @click="addContextItem(item)"
                >
                  <OpusIcon :name="item.icon" class="menu-lead" />
                  <span class="option-title">{{ item.label }}</span>
                </button>
                <p v-if="!personalContextOptions.length" class="picker-footer-note"><span>暂无可引用的资料或收藏网站</span></p>
              </div>
            </div>
            <div class="picker-item">
              <button
                type="button"
                class="picker-option"
                :class="{ 'is-sub-open': hoveredAttachKey === 'sessions' || inlineAttachKey === 'sessions' }"
                data-attach-key="sessions"
                @pointerenter="onAttachRowPointerEnter('sessions', $event)"
                @pointerleave="scheduleSubClose"
                @click="toggleAttachRow('sessions', $event.currentTarget as HTMLElement)"
              >
                <OpusIcon name="branch" class="menu-lead" />
                <span class="option-title">引入其他会话结论</span>
                <OpusIcon name="chevR" class="option-tail" />
              </button>
              <div v-if="inlineAttachKey === 'sessions'" class="effort-inline">
                <button
                  v-for="sItem in sessionContextOptions"
                  :key="sItem.id"
                  type="button"
                  class="picker-option"
                  :title="sItem.payload"
                  @click="addContextItem({ id: sItem.id, kind: 'session', icon: sItem.icon, label: sItem.label, payload: sItem.payload })"
                >
                  <OpusIcon name="branch" class="menu-lead" />
                  <span class="option-title">{{ sItem.label }}</span>
                </button>
                <p v-if="!sessionContextOptions.length" class="picker-footer-note"><span>暂无其他会话回复可引用</span></p>
              </div>
            </div>
            <div class="picker-item">
              <button
                type="button"
                class="picker-option"
                :class="{ 'is-sub-open': hoveredAttachKey === 'commands' || inlineAttachKey === 'commands' }"
                data-attach-key="commands"
                @pointerenter="onAttachRowPointerEnter('commands', $event)"
                @pointerleave="scheduleSubClose"
                @click="toggleAttachRow('commands', $event.currentTarget as HTMLElement)"
              >
                <OpusIcon name="zap" class="menu-lead" />
                <span class="option-title">快捷指令</span>
                <OpusIcon name="chevR" class="option-tail" />
              </button>
              <div v-if="inlineAttachKey === 'commands'" class="effort-inline">
                <button
                  v-for="cmd in quickCommands"
                  :key="cmd.id"
                  type="button"
                  class="picker-option picker-option--rich"
                  :title="cmd.desc"
                  @click="insertCommandTemplate(cmd.text)"
                >
                  <span class="option-copy">
                    <span class="option-title">{{ cmd.title }}</span>
                    <span class="option-desc">{{ cmd.desc }}</span>
                  </span>
                </button>
              </div>
            </div>
            <button
              type="button"
              class="picker-option"
              @pointerenter="closeSubmenu"
              @click="closeSettings(); promptLibraryOpen = true"
            >
              <OpusIcon name="sparkle" class="menu-lead" />
              <span class="option-title">自定义 Prompt 模板</span>
              <span class="picker-effort num">{{ customPrompts.length }} 条</span>
            </button>
            <div v-if="rulesList.length" class="picker-item">
              <button
                type="button"
                class="picker-option"
                :class="{ 'is-sub-open': hoveredAttachKey === 'rules' || inlineAttachKey === 'rules' }"
                data-attach-key="rules"
                @pointerenter="onAttachRowPointerEnter('rules', $event)"
                @pointerleave="scheduleSubClose"
                @click="toggleAttachRow('rules', $event.currentTarget as HTMLElement)"
              >
                <OpusIcon name="note" class="menu-lead" />
                <span class="option-title">项目规则预设 ({{ rulesList.length }})</span>
                <OpusIcon name="chevR" class="option-tail" />
              </button>
              <div v-if="inlineAttachKey === 'rules'" class="effort-inline">
                <button
                  v-for="rule in rulesList"
                  :key="rule.id"
                  type="button"
                  class="picker-option"
                  :title="rule.source"
                  @click="addContextItem({ id: rule.id, kind: 'dir', icon: 'note', label: rule.title, payload: `项目规范（${rule.source}）：\n${rule.content.slice(0, 1200)}` })"
                >
                  <OpusIcon name="note" class="menu-lead" />
                  <span class="option-title">{{ rule.title }}</span>
                  <span class="picker-badge">{{ rule.source }}</span>
                </button>
              </div>
            </div>
            <div v-if="mcpList.length || caps.includes('mcp')" class="picker-item">
              <button
                type="button"
                class="picker-option"
                :class="{ 'is-sub-open': hoveredAttachKey === 'mcp' || inlineAttachKey === 'mcp' }"
                data-attach-key="mcp"
                @pointerenter="onAttachRowPointerEnter('mcp', $event)"
                @pointerleave="scheduleSubClose"
                @click="toggleAttachRow('mcp', $event.currentTarget as HTMLElement)"
              >
                <OpusIcon name="api" class="menu-lead" />
                <span class="option-title">MCP 工具服务</span>
                <span class="picker-effort num">{{ mcpConnectedCount }}/{{ mcpList.length }}</span>
                <OpusIcon name="chevR" class="option-tail" />
              </button>
              <div v-if="inlineAttachKey === 'mcp'" class="effort-inline">
                <div class="mcp-sub-head">
                  <span>服务状态</span>
                  <button
                    type="button"
                    class="head-icon-btn"
                    title="刷新 MCP 服务器状态"
                    aria-label="刷新 MCP 状态"
                    @click.stop="refreshMcp"
                  >
                    <OpusIcon name="sync" />
                  </button>
                </div>
                <div v-if="!mcpList.length" class="mcp-empty faint">当前运行时暂未报告已配置的 MCP 服务。</div>
                <div v-for="srv in mcpList" :key="srv.name" class="mcp-row">
                  <div class="mcp-row-top">
                    <span class="mcp-name">{{ srv.name }}</span>
                    <span class="mcp-badge" :class="srv.status === 'connected' || srv.status === 'ready' ? 'is-ok' : 'is-warn'">
                      {{ srv.status || 'unknown' }}
                    </span>
                  </div>
                  <p v-if="srv.error" class="mcp-err">{{ srv.error }}</p>
                  <p v-else-if="srv.tools?.length" class="mcp-tools faint">
                    {{ srv.tools.length }} 个工具：{{ srv.tools.slice(0, 6).join(', ') }}{{ srv.tools.length > 6 ? '…' : '' }}
                  </p>
                </div>
              </div>
            </div>
          </div>
          <div class="popover-footer">
            <p class="picker-footer-note">
              <OpusIcon name="info" />
              <span>{{ mobile ? '点选图片或文件加密发送，输入 @ 引用文件' : '支持拖拽文件或 Ctrl+V 直接贴图' }}</span>
            </p>
          </div>
          <div
            v-if="hoveredAttachKey"
            class="effort-submenu effort-submenu--wide"
            :class="subPlacement === 'left' ? 'is-left' : 'is-right'"
            :style="{ top: `${subTop}px` }"
            role="group"
            :aria-label="hoveredAttachKey"
            @pointerenter="clearSubCloseTimer"
            @pointerleave="scheduleSubClose"
            @keydown="handleSubmenuKeydown"
          >
            <template v-if="hoveredAttachKey === 'dirs'">
              <button
                v-for="dir in directoryContextOptions"
                :key="dir.path"
                type="button"
                class="picker-option"
                :title="dir.path"
                @click="addContextItem({ id: `dir:${dir.path}`, kind: 'dir', icon: 'file', label: dir.name, payload: `工作目录参考: ${dir.path}` })"
              >
                <OpusIcon name="file" class="menu-lead" />
                <span class="option-title">{{ dir.name }}</span>
                <span v-if="dir.current" class="picker-badge">当前</span>
              </button>
              <p v-if="!directoryContextOptions.length" class="picker-footer-note"><span>当前节点暂无目录配置</span></p>
            </template>
            <template v-else-if="hoveredAttachKey === 'data'">
              <button
                v-for="item in personalContextOptions"
                :key="item.id"
                type="button"
                class="picker-option"
                :title="item.payload"
                @click="addContextItem(item)"
              >
                <OpusIcon :name="item.icon" class="menu-lead" />
                <span class="option-title">{{ item.label }}</span>
              </button>
              <p v-if="!personalContextOptions.length" class="picker-footer-note"><span>暂无可引用的资料或网站记录</span></p>
            </template>
            <template v-else-if="hoveredAttachKey === 'sessions'">
              <button
                v-for="sItem in sessionContextOptions"
                :key="sItem.id"
                type="button"
                class="picker-option picker-option--rich"
                :title="sItem.payload"
                @click="addContextItem({ id: sItem.id, kind: 'session', icon: sItem.icon, label: sItem.label, payload: sItem.payload })"
              >
                <OpusIcon name="branch" class="option-lead" />
                <span class="option-copy">
                  <span class="option-title">{{ sItem.label }}</span>
                  <span class="option-desc">{{ sItem.preview }}</span>
                </span>
              </button>
              <p v-if="!sessionContextOptions.length" class="picker-footer-note"><span>暂无其他会话回复可引用</span></p>
            </template>
            <template v-else-if="hoveredAttachKey === 'commands'">
              <button
                v-for="cmd in quickCommands"
                :key="cmd.id"
                type="button"
                class="picker-option picker-option--rich"
                @click="insertCommandTemplate(cmd.text)"
              >
                <OpusIcon name="zap" class="option-lead" />
                <span class="option-copy">
                  <span class="option-title">{{ cmd.title }}</span>
                  <span class="option-desc">{{ cmd.desc }}</span>
                </span>
              </button>
            </template>
            <template v-else-if="hoveredAttachKey === 'rules'">
              <button
                v-for="rule in rulesList"
                :key="rule.id"
                type="button"
                class="picker-option picker-option--rich"
                @click="addContextItem({ id: rule.id, kind: 'dir', icon: 'note', label: rule.title, payload: `项目规范（${rule.source}）：\n${rule.content.slice(0, 1200)}` })"
              >
                <OpusIcon name="note" class="option-lead" />
                <span class="option-copy">
                  <span class="option-title">{{ rule.title }}</span>
                  <span class="option-desc">{{ rule.source }}</span>
                </span>
              </button>
            </template>
            <template v-else-if="hoveredAttachKey === 'mcp'">
              <div class="mcp-sub-head">
                <span>MCP 工具服务器</span>
                <button
                  type="button"
                  class="head-icon-btn"
                  title="刷新 MCP 服务器状态"
                  aria-label="刷新 MCP 状态"
                  @click.stop="refreshMcp"
                >
                  <OpusIcon name="sync" />
                </button>
              </div>
              <div v-if="!mcpList.length" class="mcp-empty faint">
                当前运行时暂未报告已配置的 MCP 服务。
              </div>
              <div v-for="srv in mcpList" :key="srv.name" class="mcp-row">
                <div class="mcp-row-top">
                  <span class="mcp-name">{{ srv.name }}</span>
                  <span
                    class="mcp-badge"
                    :class="srv.status === 'connected' || srv.status === 'ready' ? 'is-ok' : 'is-warn'"
                  >
                    {{ srv.status || 'unknown' }}
                  </span>
                </div>
                <p v-if="srv.error" class="mcp-err">{{ srv.error }}</p>
                <p v-else-if="srv.tools?.length" class="mcp-tools faint">
                  {{ srv.tools.length }} 个工具：{{ srv.tools.slice(0, 6).join(', ') }}{{ srv.tools.length > 6 ? '…' : '' }}
                </p>
              </div>
            </template>
          </div>
        </template>
        <template v-else-if="panel === 'model'">
          <div class="popover-head popover-head--row">
            <span>模型</span>
            <button
              v-if="caps.includes('models') && effectiveNode?.status === 'online'"
              type="button"
              class="head-icon-btn"
              title="重新同步节点模型"
              aria-label="重新同步节点模型"
              @click="refreshModels"
            >
              <OpusIcon name="sync" />
            </button>
          </div>
          <div class="picker-list" role="group" aria-label="模型" @scroll.passive="closeSubmenu">
            <button
              type="button"
              class="picker-option"
              :aria-pressed="!options.model"
              @pointerenter="closeSubmenu"
              @click="chooseModel('')"
            >
              <span class="option-title">节点默认模型</span>
              <span class="picker-badge">默认</span>
              <OpusIcon v-if="!options.model" name="check" class="option-tail is-check" />
            </button>
            <div v-for="entry in catalog?.models" :key="entry.id" class="picker-item">
              <button
                type="button"
                class="picker-option"
                :class="{
                  'is-sub-open': hoveredModelId === entry.id || inlineEffortModelId === entry.id,
                  'is-unavailable': entry.unavailable,
                }"
                :disabled="entry.unavailable"
                :title="entry.note || entry.label"
                :data-model-id="entry.id"
                :aria-pressed="options.model === entry.id"
                @pointerenter="onModelRowPointerEnter(entry, $event)"
                @pointerleave="scheduleSubClose"
                @keydown="handleModelRowKeydown(entry, $event)"
                @click="chooseModel(entry.id)"
              >
                <span class="option-title">{{ entry.label }}</span>
                <span
                  v-if="entry.provider && !entry.label.startsWith(entry.provider)"
                  class="picker-badge picker-provider"
                  :title="`provider: ${entry.provider}`"
                >{{ entry.provider }}</span>
                <span v-if="rowEffortText(entry)" class="picker-effort">{{ rowEffortText(entry) }}</span>
                <span v-if="entry.badge" class="picker-badge">{{ entry.badge }}</span>
                <span v-if="entry.unavailable" class="picker-warn">
                  <span>{{ entry.note || '不可用' }}</span>
                  <OpusIcon name="info" />
                </span>
                <template v-else-if="entry.efforts.length">
                  <OpusIcon
                    v-if="options.model === entry.id && hoveredModelId !== entry.id && inlineEffortModelId !== entry.id"
                    name="check"
                    class="option-tail is-check"
                  />
                  <OpusIcon v-else name="chevR" class="option-tail" />
                </template>
                <OpusIcon v-else-if="options.model === entry.id" name="check" class="option-tail is-check" />
              </button>
              <div
                v-if="inlineEffortModelId === entry.id && entry.efforts.length && !entry.unavailable"
                class="effort-inline"
                role="group"
                :aria-label="`${entry.label} 思考强度`"
              >
                <button
                  type="button"
                  class="picker-option"
                  :aria-pressed="options.model === entry.id && !options.effort"
                  @click="chooseModelEffort(entry.id, '')"
                >
                  <span class="option-title">默认</span>
                  <OpusIcon v-if="options.model === entry.id && !options.effort" name="check" class="option-tail is-check" />
                </button>
                <button
                  v-for="effort in entry.efforts"
                  :key="effort"
                  type="button"
                  class="picker-option"
                  :aria-pressed="options.model === entry.id && options.effort === effort"
                  @click="chooseModelEffort(entry.id, effort)"
                >
                  <span class="option-title">{{ effortLabels[effort] ?? effort }}</span>
                  <OpusIcon v-if="options.model === entry.id && options.effort === effort" name="check" class="option-tail is-check" />
                </button>
              </div>
            </div>
          </div>
          <div class="popover-footer">
            <p v-if="catalog?.message || !catalog?.models.length" class="picker-footer-note">
              <OpusIcon name="info" />
              <span>{{ catalog?.message || (!caps.includes('models') ? '由节点配置模型和思考强度' : catalog ? '当前代理未返回可用模型' : '正在读取节点模型…') }}</span>
            </p>
            <div class="usage-summary" :title="usageTooltip">
              <div class="usage-row">
                <span class="usage-label">
                  <OpusIcon name="tasks" class="footer-lead" />
                  <span>会话用量</span>
                  <span v-if="sessionUsage" class="picker-badge">{{ usageSourceLabel }}</span>
                </span>
                <span class="usage-total num">
                  {{ sessionUsage ? `${formatTokenCount(sessionUsage.totalTokens)} tokens` : '0 tokens' }}
                </span>
              </div>
              <div v-if="sessionUsage" class="usage-meta num">
                <span>输入 {{ formatTokenCount(sessionUsage.totalInputTokens) }}</span>
                <span>·</span>
                <span>输出 {{ formatTokenCount(sessionUsage.totalOutputTokens) }}</span>
                <template v-if="sessionUsage.totalCachedTokens > 0">
                  <span>·</span>
                  <span>缓存 {{ formatTokenCount(sessionUsage.totalCachedTokens) }}</span>
                </template>
                <span>·</span>
                <span>{{ sessionUsage.turns }} 轮</span>
              </div>
              <div v-else class="usage-meta">
                发送消息后仅在内存中统计本连接用量
              </div>
              <div v-if="sessionUsage?.contextWindow" class="usage-meter">
                <div class="usage-meter-track">
                  <div class="usage-meter-fill" :style="{ width: `${usageContextBarWidth}%` }" />
                </div>
                <span class="usage-meter-pct num">
                  {{ formatTokenCount(sessionUsage.lastTurnTokens) }} / {{ formatTokenCount(sessionUsage.contextWindow) }} · {{ usageContextPercentLabel }}
                </span>
              </div>
            </div>
          </div>
          <div
            v-if="subModel && subModel.efforts.length && !subModel.unavailable"
            class="effort-submenu"
            :class="subPlacement === 'left' ? 'is-left' : 'is-right'"
            :style="{ top: `${subTop}px` }"
            role="group"
            :aria-label="`${subModel.label} 思考强度`"
            @pointerenter="clearSubCloseTimer"
            @pointerleave="scheduleSubClose"
            @keydown="handleSubmenuKeydown"
          >
            <button
              type="button"
              class="picker-option"
              :aria-pressed="options.model === subModel.id && !options.effort"
              @click="chooseModelEffort(subModel.id, '')"
            >
              <span class="option-title">默认</span>
              <OpusIcon v-if="options.model === subModel.id && !options.effort" name="check" class="option-tail is-check" />
            </button>
            <button
              v-for="effort in subModel.efforts"
              :key="effort"
              type="button"
              class="picker-option"
              :aria-pressed="options.model === subModel.id && options.effort === effort"
              @click="chooseModelEffort(subModel.id, effort)"
            >
              <span class="option-title">{{ effortLabels[effort] ?? effort }}</span>
              <OpusIcon v-if="options.model === subModel.id && options.effort === effort" name="check" class="option-tail is-check" />
            </button>
          </div>
        </template>
        <template v-else>
          <div class="popover-head">执行权限</div>
          <div role="group" aria-label="执行权限" class="picker-list picker-list--perm">
            <button
              v-for="choice in permissionChoices"
              :key="choice.id"
              type="button"
              class="picker-option picker-option--rich"
              :class="{ 'is-unavailable': choice.disabled }"
              :disabled="choice.disabled"
              :title="choice.disabled ? choice.note : choice.description"
              :aria-pressed="permissionMode === choice.id"
              @click="choosePermission(choice)"
            >
              <OpusIcon :name="choice.icon" class="option-lead" />
              <span class="option-copy">
                <span class="option-title-row">
                  <span class="option-title">{{ choice.label }}</span>
                  <span v-if="choice.badge" class="picker-badge">{{ choice.badge }}</span>
                </span>
                <span class="option-desc">{{ choice.disabled ? (choice.note || choice.description) : choice.description }}</span>
              </span>
              <OpusIcon v-if="permissionMode === choice.id" name="check" class="option-tail is-check" />
            </button>
          </div>
          <details :key="settingsKey" class="sandbox-details">
            <summary>
              <OpusIcon name="file" />
              <span><small>当前工作目录</small><b :title="currentDirectory">{{ directoryName || '未设置' }}</b></span>
              <OpusIcon name="chevR" class="details-chevron" />
            </summary>
            <div v-if="currentDirectory" class="sandbox-list">
              <code>{{ currentDirectory }}</code>
            </div>
            <div v-if="effectiveNode?.allowedRoots.length" class="sandbox-list">
              <span>允许访问的目录</span>
              <code v-for="root in effectiveNode.allowedRoots" :key="root">{{ root }}</code>
            </div>
            <div class="sandbox-list">
              <span>文件传输通道</span>
              <small v-for="ep in effectiveNode?.transferEndpoints" :key="ep.url">{{ ep.label }} · {{ ep.kind }}</small>
              <small>加密中继 · Core</small>
            </div>
          </details>
          <div v-if="effectiveNode" class="trust-policy-section">
            <div class="trust-sec-head">
              <span>节点信任命令白名单</span>
              <span class="trust-sec-count num">{{ nodeTrustPatterns.length }}</span>
            </div>
            <div v-if="nodeTrustPatterns.length" class="trust-chips">
              <span v-for="pat in nodeTrustPatterns" :key="pat" class="trust-chip" :title="pat">
                <code>{{ pat }}</code>
                <button
                  type="button"
                  class="trust-chip-x"
                  :aria-label="`移除信任规则 ${pat}`"
                  @click="handleRemoveTrustPattern(pat)"
                >×</button>
              </span>
            </div>
            <p v-else class="trust-empty faint">
              尚未添加自动放行命令；在低/中风险审批弹窗可点击「始终信任」。
            </p>
            <form class="trust-add-form" @submit.prevent="handleAddTrustPattern">
              <input
                v-model="newTrustPattern"
                type="text"
                class="input trust-add-input"
                placeholder="命令前缀如 npm test"
                aria-label="新增信任命令前缀"
              />
              <button type="submit" class="btn btn-subtle btn-sm" :disabled="!newTrustPattern.trim()">添加</button>
            </form>
          </div>
        </template>
      </div>
    </div>
    <PromptLibraryModal
      :open="promptLibraryOpen"
      :prompts="customPrompts"
      @close="promptLibraryOpen = false"
      @save="handleSaveCustomPrompt"
      @remove="handleRemoveCustomPrompt"
      @use-prompt="handleUseCustomPrompt"
    />
    <dialog
      ref="lightboxEl"
      class="img-lightbox"
      closedby="any"
      :aria-label="lightboxAlt ? `大图预览：${lightboxAlt}` : '图片大图预览'"
      @close="onLightboxClose"
    >
      <form method="dialog" class="lightbox-frame">
        <header class="lightbox-head">
          <span class="lightbox-title">{{ lightboxAlt || '图片预览' }}</span>
          <div class="lightbox-actions">
            <button
              v-if="lightboxSrc"
              type="button"
              class="btn btn-subtle btn-sm"
              title="下载原图"
              @click="downloadLightboxImage"
            >
              <OpusIcon name="download" />
              <span>下载</span>
            </button>
            <button type="submit" class="icon-btn lightbox-close" aria-label="关闭大图预览" autofocus>
              <OpusIcon name="x" />
            </button>
          </div>
        </header>
        <img v-if="lightboxSrc" :src="lightboxSrc" :alt="lightboxAlt" class="lightbox-img" />
      </form>
    </dialog>
  </div>
</template>

<style scoped>
.thread-root {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: 1 1 0;
  min-height: 0;
  min-width: 0;
  height: auto;
  overflow: hidden;
}
.thread-root :deep(.msgs),
.thread-root :deep(.mmsgs) {
  flex: 1 1 0;
  min-height: 0;
  overflow-x: hidden;
}
.thread-root :deep(.mmsgs) {
  padding-bottom: 24px;
}
.thread-root :deep(.composer),
.thread-root :deep(.mcomposer) {
  position: relative;
  flex: none;
}
.msgs:has(.thread-empty) { display: grid; align-items: safe center; }
.msgs .thread-empty { padding: 24px 0; }
.msgs .thread-empty h4 { font-size: clamp(18px, 2cqi, 24px); letter-spacing: -.025em; }
.composer { padding: 12px clamp(12px, 4%, 38px) 16px; }
.composer-box {
  border: 1px solid var(--line-strong);
  border-radius: 20px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, .04), 0 0 0 3px color-mix(in srgb, var(--surface-2) 85%, transparent);
}
.composer-box:focus-within {
  border-color: var(--accent-line);
  box-shadow: 0 6px 20px -6px rgba(15, 23, 42, .10), 0 0 0 3px var(--accent-soft);
}
.composer-box.is-dragging,
.mcomposer .box.is-dragging {
  border-color: var(--accent-line);
  background: color-mix(in srgb, var(--accent-soft) 45%, var(--solid));
}
.composer-editor { min-width: 0; }
.mcomposer .composer-editor { flex: 1; min-width: 0; }
.editor-field { position: relative; overflow: clip; }
.composer-input, .draft-measure {
  box-sizing: border-box;
  min-height: 44px;
  width: 100%;
  padding: 4px 0;
  font: inherit;
  font-size: 14px;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.composer-input {
  display: block;
  transition: height 150ms var(--ease-out);
}
.composer .composer-input { max-height: min(160px, 30dvh); }
.mcomposer .composer-input, .mcomposer .draft-measure {
  min-height: 32px;
  padding: 4px 0;
  font-size: 15px;
  line-height: 1.4;
}
.thread-root .composer-input:focus,
.thread-root .composer-input:focus-visible {
  outline: none;
  box-shadow: none;
  border-radius: 0;
}
.draft-measure { position: absolute; inset: 0 0 auto; visibility: hidden; pointer-events: none; }
.queued-files { max-height: 18vh; overflow: auto; }
.trigger-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  min-width: 0;
  max-width: 52%;
}
.trigger-tip {
  position: absolute;
  left: 0;
  bottom: calc(100% + 8px);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 9px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--solid);
  color: var(--text);
  font-size: 11.5px;
  font-weight: 450;
  white-space: nowrap;
  box-shadow: 0 6px 18px -4px rgba(15, 23, 42, .12), 0 2px 6px rgba(15, 23, 42, .05);
  pointer-events: none;
  opacity: 0;
  transform: translateY(3px);
  transition: opacity var(--dur-1) ease, transform var(--dur-1) var(--ease-out);
  z-index: 5;
}
.trigger-tip kbd {
  font: inherit;
  font-size: 11px;
  color: var(--text-3);
}
@media (hover: hover) {
  .trigger-wrap:has(.model-trigger:hover) .trigger-tip,
  .trigger-wrap:has(.model-trigger:focus-visible) .trigger-tip {
    opacity: 1;
    transform: none;
  }
}
.model-trigger {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  max-width: 100%;
  height: 26px;
  padding: 0 7px;
  border-radius: 7px;
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 450;
  cursor: pointer;
  transition: background-color var(--dur-1), color var(--dur-1);
}
.model-trigger:is(:hover, :focus-visible),
.model-trigger[aria-expanded="true"] {
  background: var(--surface-2);
  color: var(--text);
}
.trigger-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.trigger-effort {
  flex: none;
  color: var(--text-3);
  font-size: 12px;
  font-weight: 400;
  white-space: nowrap;
}
.trigger-chev {
  width: 12px;
  height: 12px;
  flex: none;
  color: var(--text-3);
  transition: transform var(--dur-1) var(--ease-out), color var(--dur-1);
}
[aria-expanded="true"] .trigger-chev {
  transform: rotate(180deg);
  color: var(--text);
}
.mcomposer .box {
  display: grid;
  gap: 6px;
  padding: 8px 8px 8px 10px;
  border: 1px solid var(--line-strong);
  border-radius: 22px;
  background: var(--solid);
  box-shadow: 0 2px 10px rgba(15, 23, 42, .05);
}
.m-status-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 2px 0 7px;
}
.m-status-icon-btn {
  flex: none;
  display: inline-grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text-2);
  cursor: pointer;
}
.m-status-icon-btn .i { width: 15px; height: 15px; }
.m-status-icon-btn.is-accent {
  border-color: var(--accent-line);
  background: var(--accent-soft);
  color: var(--accent);
}
.m-status-icon-btn.is-perm-full-auto {
  border-color: color-mix(in srgb, var(--warn) 38%, transparent);
  background: var(--warn-soft);
  color: var(--warn);
}
.m-status-pill {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 32px;
  padding: 0 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 12.5px;
  font-weight: 520;
  white-space: nowrap;
  cursor: pointer;
}
.m-status-pill--model {
  flex: 1 1 0;
  min-width: 0;
  max-width: none;
  justify-content: space-between;
}
.m-status-pill .m-pill-text {
  flex: 1;
  min-width: 0;
  text-align: left;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.m-status-pill .i { width: 13px; height: 13px; flex: none; }
.m-status-pill .m-pill-chev { width: 11px; height: 11px; opacity: .7; }
.m-status-pill .m-pill-sub { color: var(--text-3); font-size: 11.5px; }
.m-status-pill.is-accent {
  border-color: var(--accent-line);
  background: var(--accent-soft);
  color: var(--accent);
}
.m-status-pill.is-perm-full-auto {
  border-color: color-mix(in srgb, var(--warn) 38%, transparent);
  background: var(--warn-soft);
  color: var(--warn);
}
.m-composer-bar {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  min-width: 0;
}
.m-add-btn {
  flex: none;
  display: inline-grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border: 0;
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--text-2);
  cursor: pointer;
}
.m-add-btn .i { width: 18px; height: 18px; }
.m-add-btn:active { background: var(--surface-3); color: var(--text); }
.m-editor-field {
  flex: 1;
  min-width: 0;
}
.mcomposer .m-auto-input {
  field-sizing: content;
  height: auto;
  width: 100%;
  min-block-size: 38px;
  max-block-size: 136px;
  padding: 8px 2px;
  font-size: 15px;
  line-height: 1.45;
  overflow-y: auto;
  resize: none;
}
.mcomposer .draft-measure {
  min-height: 38px;
  padding: 8px 2px;
  font-size: 15px;
  line-height: 1.45;
}
.m-queue-btn {
  flex: none;
  min-height: 34px;
  padding: 0 10px;
  border-radius: 999px;
}
.mcomposer .composer-input::placeholder { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.run-popover {
  --popup-width: min(244px, calc(100vw - 16px));
  --popup-left: calc(var(--trigger-x) - var(--popup-width));
  inset: auto auto max(8px, calc(100dvh - var(--trigger-y) + 8px))
    clamp(8px, var(--popup-left), calc(100vw - var(--popup-width) - 8px));
  width: var(--popup-width);
  overflow: visible;
  margin: 0;
  padding: 5px;
  border: 1px solid var(--line);
  border-radius: 10px;
  color: var(--text);
  background: var(--solid);
  box-shadow: 0 10px 30px -6px rgba(15, 23, 42, .14), 0 2px 8px -2px rgba(15, 23, 42, .06);
  opacity: 0;
  transform: translateY(5px) scale(.985);
  transform-origin: bottom right;
  transition: opacity 120ms ease, transform 150ms var(--ease-out), display 150ms allow-discrete, overlay 150ms allow-discrete;
}
.run-popover.is-model {
  --popup-width: min(226px, calc(100vw - 16px));
  --popup-left: var(--trigger-x);
  transform-origin: bottom left;
}
.run-popover.is-attach {
  --popup-width: min(222px, calc(100vw - 16px));
  --popup-left: var(--trigger-x);
  transform-origin: bottom left;
}
.run-popover:not(:popover-open) { pointer-events: none; }
.run-popover:popover-open { opacity: 1; transform: none; }
@starting-style {
  .run-popover:popover-open { opacity: 0; transform: translateY(5px) scale(.985); }
}
.composer .send,
.mcomposer .send {
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 999px;
}
.mcomposer .send.m-send-btn {
  width: 38px;
  height: 38px;
}
.thread-mobile .run-popover,
.thread-mobile .run-popover.is-model,
.thread-mobile .run-popover.is-attach {
  --popup-width: min(272px, calc(100vw - 24px));
  inset: auto auto max(12px, calc(100dvh - var(--trigger-y) + 8px))
    clamp(12px, calc(var(--trigger-x) - var(--popup-width) / 2), calc(100vw - var(--popup-width) - 12px));
  width: var(--popup-width);
  max-height: 44dvh;
  overflow-y: auto;
  overscroll-behavior: contain;
  border-radius: 14px;
  padding: 6px;
  transform-origin: bottom center;
}
.thread-mobile .picker-option {
  min-height: 36px;
  padding: 6px 9px;
  font-size: 13px;
}
.thread-mobile .mention-option {
  min-height: 38px;
  padding: 7px 10px;
}
.send .i { grid-area: 1 / 1; }
.send:not(:disabled):active { scale: .94; }
.send-icon-enter-active, .send-icon-leave-active,
.attachment-enter-active, .attachment-leave-active {
  transition: opacity 120ms ease, transform 150ms var(--ease-out);
}
.send-icon-enter-from, .send-icon-leave-to { opacity: 0; transform: scale(.7); }
.attachment-enter-from, .attachment-leave-to { opacity: 0; transform: translateY(3px); }
.popover-head {
  padding: 2px 8px 4px;
  font-size: 10.5px;
  font-weight: 500;
  line-height: 14px;
  color: var(--text-3);
  user-select: none;
}
.popover-head--row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 4px 4px 8px;
}
.head-icon-btn {
  display: inline-grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: 6px;
  color: var(--text-3);
  cursor: pointer;
  transition: background-color var(--dur-1), color var(--dur-1);
}
.head-icon-btn .i {
  width: 12px;
  height: 12px;
}
.head-icon-btn:hover {
  background: var(--surface-2);
  color: var(--text);
}
.picker-list {
  display: grid;
  gap: 1px;
  max-height: min(300px, max(112px, calc(var(--trigger-y) - 96px)));
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-width: thin;
}
.picker-list--perm {
  gap: 1px;
}
.picker-item {
  display: grid;
  min-width: 0;
}
.picker-option {
  display: flex;
  align-items: center;
  gap: 5px;
  width: 100%;
  min-height: 26px;
  padding: 4px 8px;
  border-radius: 6px;
  text-align: left;
  font-size: 12px;
  line-height: 1.3;
  color: var(--text);
  cursor: pointer;
  transition: background-color var(--dur-1), color var(--dur-1);
}
.picker-option--rich {
  align-items: center;
  gap: 8px;
  min-height: 0;
  padding: 5px 8px;
  border-radius: 7px;
}
.option-lead {
  width: 14px;
  height: 14px;
  flex: none;
  color: var(--text-2);
}
.option-copy {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}
.option-title-row {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
}
.option-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 450;
  color: var(--text);
}
.picker-option[aria-pressed="true"] .option-title,
.picker-option--rich .option-title {
  font-weight: 550;
}
.option-desc {
  font-size: 10.5px;
  line-height: 1.3;
  color: var(--text-3);
  white-space: normal;
}
.picker-effort {
  flex: none;
  color: var(--text-3);
  font-size: 11px;
  font-weight: 400;
  white-space: nowrap;
}
.picker-badge {
  display: inline-flex;
  align-items: center;
  height: 15px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--surface-3);
  color: var(--text-2);
  font-size: 9.5px;
  font-weight: 500;
  line-height: 1;
  flex: none;
}
/* 模型所属 provider（opencode / opencode-go 等），同名模型靠它区分 */
.picker-provider,
.trigger-provider {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text-3);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 500;
  letter-spacing: 0.01em;
}
.trigger-provider {
  display: inline-flex;
  align-items: center;
  height: 15px;
  padding: 0 5px;
  border-radius: 999px;
  font-size: 9.5px;
  line-height: 1;
  flex: none;
}
.picker-warn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: auto;
  padding: 0 5px;
  height: 15px;
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 9.5px;
  line-height: 1;
  flex: none;
}
.picker-warn .i {
  width: 10px;
  height: 10px;
  flex: none;
}
.picker-option.is-unavailable {
  opacity: .52;
  cursor: not-allowed;
}
.option-tail {
  width: 12px;
  height: 12px;
  margin-left: auto;
  flex: none;
  color: var(--text-3);
}
.option-tail.is-check {
  width: 13px;
  height: 13px;
  color: var(--text);
}
.picker-option:not(:disabled):is(:hover, :focus-visible, .is-sub-open),
.sandbox-details summary:hover {
  background: var(--surface-2);
}
.thread-root .picker-option:focus,
.thread-root .sandbox-details summary:focus,
.thread-root .head-icon-btn:focus,
.thread-root .model-trigger:focus,
.thread-root .safety-badge:focus {
  outline: none;
}
.thread-root .picker-option:focus-visible,
.thread-root .sandbox-details summary:focus-visible,
.thread-root .head-icon-btn:focus-visible,
.thread-root .model-trigger:focus-visible {
  outline: 1.5px solid var(--accent-line);
  outline-offset: -1.5px;
}
.thread-root .safety-badge:focus-visible {
  outline: 1.5px solid var(--accent-line);
  outline-offset: -1.5px;
  border-radius: 999px;
}
.menu-lead {
  width: 13px;
  height: 13px;
  flex: none;
  color: var(--text-3);
}
.picker-option:hover .menu-lead,
.picker-option.is-sub-open .menu-lead {
  color: var(--text);
}
.effort-submenu {
  position: absolute;
  display: grid;
  gap: 1px;
  min-width: 112px;
  max-width: 162px;
  padding: 5px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--solid);
  color: var(--text);
  box-shadow: 0 10px 30px -6px rgba(15, 23, 42, .14), 0 2px 8px -2px rgba(15, 23, 42, .06);
  z-index: 2;
}
.effort-submenu--wide {
  min-width: 196px;
  max-width: 232px;
}
.effort-submenu::before {
  content: "";
  position: absolute;
  inset-block: 0;
  width: 10px;
}
.effort-submenu.is-right { left: calc(100% + 6px); }
.effort-submenu.is-right::before { right: 100%; }
.effort-submenu.is-left { right: calc(100% + 6px); }
.effort-submenu.is-left::before { left: 100%; }
.effort-inline {
  display: grid;
  gap: 1px;
  margin: 2px 0 3px 8px;
  padding-left: 6px;
  border-left: 1px solid var(--line);
}
.popover-footer {
  display: grid;
  gap: 2px;
  margin: 5px -5px 0;
  padding: 5px 5px 0;
  border-top: 1px solid var(--line);
}
.picker-footer-note {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  padding: 3px 8px;
  color: var(--text-3);
  font-size: 10.5px;
  line-height: 1.3;
}
.picker-footer-note .i {
  width: 12px;
  height: 12px;
  flex: none;
  color: var(--text-3);
}
.usage-summary {
  display: grid;
  gap: 3px;
  padding: 5px 8px;
  border-radius: 6px;
  background: var(--surface-2);
}
.usage-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.usage-label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-2);
}
.usage-label .footer-lead {
  width: 12px;
  height: 12px;
  flex: none;
  color: var(--text-3);
}
.usage-total {
  font-size: 11px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
}
.usage-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  line-height: 1.3;
  color: var(--text-3);
}
.usage-meter {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 1px;
}
.usage-meter-track {
  flex: 1;
  min-width: 0;
  height: 3px;
  border-radius: 999px;
  background: var(--line);
  overflow: hidden;
}
.usage-meter-fill {
  height: 100%;
  border-radius: 999px;
  background: var(--accent, var(--text));
  transition: width 180ms var(--ease-out);
}
.usage-meter-pct {
  flex: none;
  font-size: 9.5px;
  color: var(--text-3);
  white-space: nowrap;
}
.sandbox-details {
  margin: 5px -5px 0;
  padding: 5px 5px 0;
  border-top: 1px solid var(--line);
}
.sandbox-details summary {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: 7px;
  cursor: pointer;
  transition: background-color var(--dur-1);
}
.sandbox-details summary::-webkit-details-marker { display: none; }
.sandbox-details summary .i { width: 14px; height: 14px; flex: none; color: var(--text-3); }
.sandbox-details summary .details-chevron { width: 12px; height: 12px; transition: transform var(--dur-1) var(--ease-out); }
.sandbox-details summary span { display: grid; flex: 1; min-width: 0; }
.sandbox-details summary small { color: var(--text-3); font-size: 10px; }
.sandbox-details summary b { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11.5px; font-weight: 500; }
.sandbox-details[open] .details-chevron { transform: rotate(90deg); }
.sandbox-list { display: grid; gap: 3px; padding: 4px 8px 3px; color: var(--text-2); font-size: 10.5px; overflow-wrap: anywhere; }
.sandbox-list code { padding: 2px 5px; border-radius: 5px; background: var(--surface-2); font-size: 10.5px; }
:global([data-mode="dark"] .thread-root .run-popover),
:global([data-mode="dark"] .thread-root .effort-submenu),
:global([data-mode="dark"] .thread-root .trigger-tip) {
  border-color: var(--line-strong);
  box-shadow: 0 16px 38px -6px rgba(0, 0, 0, .55), 0 2px 10px -2px rgba(0, 0, 0, .35);
}
@container (max-width: 290px) {
  .composer { padding-inline: 6px; }
  .composer-box { padding-inline: 6px; }
  .composer-row { gap: 3px; }
  .composer-row .icon-btn { width: 24px; flex: none; }
  .composer-row .safety-badge { padding-inline: 7px; }
  .composer-row .safety-badge .trigger-label,
  .composer-row .safety-badge .trigger-chev { display: none; }
  .composer-row .trigger-wrap { max-width: 56%; }
  .composer-row .model-trigger { padding-inline: 5px; }
}
:global([data-motion="reduced"] .thread-root .composer-input),
:global([data-motion="reduced"] .thread-root .run-popover),
:global([data-motion="reduced"] .thread-root .send-icon-enter-active),
:global([data-motion="reduced"] .thread-root .send-icon-leave-active),
:global([data-motion="reduced"] .thread-root .attachment-enter-active),
:global([data-motion="reduced"] .thread-root .attachment-leave-active) { transition: none; }
.mmsgs-inner {
  display: grid;
  gap: 14px;
}
.thread-empty {
  display: grid;
  justify-items: center;
  text-align: center;
  gap: 8px;
  padding: 44px 20px 20px;
  color: var(--text-2);
}
.thread-empty h4 { margin: 4px 0 0; font-size: 15px; color: var(--text); }
.thread-empty p { margin: 0; max-width: 420px; font-size: 12.5px; line-height: 1.6; }
.thread-empty-ic {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  border-radius: 14px;
  background: color-mix(in srgb, var(--oc, var(--accent)) 14%, transparent);
  color: var(--oc, var(--accent));
}
.thread-empty-ic .i { width: 22px; height: 22px; }
.tool-list { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 6px; }
.thought-box {
  margin-bottom: 8px;
  padding: 6px 10px;
  border-radius: var(--r-sm);
  background: var(--surface-2);
  font-size: 12px;
  color: var(--text-2);
}
.thought-box summary { cursor: pointer; font-weight: 550; }
.thought-body {
  margin-top: 6px;
  white-space: pre-wrap;
  font-size: 12px;
  line-height: 1.55;
  color: var(--text-3);
}
.msg-text { white-space: pre-wrap; word-break: break-word; color: inherit; }
.msg.agent, .mmsg.agent { min-width: 0; }
.msg.agent .bubble, .mmsg.agent .bubble {
  color: var(--text);
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
}
.msg.user .bubble, .mmsg.user .bubble { color: var(--accent-ink); }
:deep(.msg.user .artifact-pill),
:deep(.mmsg.user .artifact-pill) {
  background: var(--solid);
  color: var(--text);
}
.msg-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px 8px;
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px solid var(--line);
}
.msg-time {
  font-size: 11px;
  color: var(--text-3);
}
.msg-foot-actions {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-left: auto;
  max-width: 100%;
}
.chip--image {
  padding-left: 4px;
  gap: 6px;
}
.chip-thumb-btn {
  display: inline-flex;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: zoom-in;
  flex: none;
}
.chip-thumb {
  width: 22px;
  height: 22px;
  object-fit: cover;
  border-radius: 5px;
}
.msg-img-thumb {
  display: block;
  margin-top: 8px;
  padding: 0;
  border: 1px solid var(--line);
  border-radius: 10px;
  overflow: hidden;
  background: var(--surface-2);
  cursor: zoom-in;
}
.msg-img-thumb img {
  display: block;
  max-width: min(260px, 100%);
  max-height: 180px;
  object-fit: cover;
}
.msg-media-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
}
.msg-media-card {
  display: flex;
  flex-direction: column;
  max-width: min(320px, 100%);
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  overflow: hidden;
  background: var(--surface-2);
}
.msg-media-thumb-btn {
  display: block;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: zoom-in;
  line-height: 0;
}
.msg-media-img {
  display: block;
  max-width: 100%;
  max-height: 220px;
  width: auto;
  height: auto;
  object-fit: contain;
}
.msg-media-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 10px;
  border-top: 1px solid var(--line);
  background: var(--solid);
  color: var(--text);
}
.msg-media-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--text-2);
}
.msg-media-dl {
  flex: none;
  height: 26px;
  padding: 0 8px;
  font-size: 11.5px;
}
.msg-file-card {
  display: flex;
  align-items: center;
  gap: 8px;
  width: min(320px, 100%);
  padding: 8px 10px;
  border: 1px solid var(--line-strong);
  border-radius: 10px;
  background: var(--solid);
  color: var(--text);
}
.msg-file-ic {
  width: 16px;
  height: 16px;
  color: var(--accent);
  flex: none;
}
.lightbox-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex: none;
}
dialog.img-lightbox {
  max-width: min(92vw, 960px);
  max-height: 90dvh;
  margin: auto;
  padding: 0;
  border: 1px solid var(--line-strong);
  border-radius: 14px;
  background: var(--solid);
  color: var(--text);
  box-shadow: var(--shadow-pop);
}
dialog.img-lightbox[open] {
  display: grid;
}
dialog.img-lightbox:modal {
  overscroll-behavior: contain;
}
dialog.img-lightbox::backdrop {
  overflow: hidden;
  overscroll-behavior: contain;
  background: rgba(15, 23, 42, .68);
  backdrop-filter: blur(4px);
}
.lightbox-frame {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  min-width: 0;
  max-height: 90dvh;
}
.lightbox-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
}
.lightbox-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
  font-weight: 550;
}
.lightbox-img {
  display: block;
  max-width: min(90vw, 920px);
  max-height: calc(90dvh - 56px);
  margin: 10px;
  object-fit: contain;
  border-radius: 8px;
}
.queued-files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  width: min(760px, 100%);
  margin: 0 auto;
}
.queued-files:not(:empty) { margin-bottom: 5px; }
.queued-files .chip { min-width: 0; max-width: 100%; }
.queued-files .chip--context { background: var(--surface-2); border-color: var(--line); }
.attachment-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.composer-row {
  flex-wrap: nowrap;
  min-width: 0;
}
.safety-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  max-width: 48%;
  height: 28px;
  padding: 0 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 450;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color var(--dur-1), border-color var(--dur-1), color var(--dur-1);
}
.safety-badge:is(:hover, :focus-visible),
.safety-badge[aria-expanded="true"] {
  background: var(--surface-3);
  border-color: var(--line-strong);
  color: var(--text);
}
.safety-badge.is-deny {
  background: var(--warn-soft);
  border-color: color-mix(in srgb, var(--warn) 25%, transparent);
  color: var(--warn);
}
.safety-badge.is-deny .trigger-lead,
.safety-badge.is-deny .trigger-chev {
  color: var(--warn);
}
.safety-badge .trigger-lead {
  width: 13.5px;
  height: 13.5px;
  flex: none;
  color: var(--text-2);
}
.safety-badge.is-turbo .trigger-lead {
  color: var(--warn);
}
.chip-x {
  margin-left: 2px;
  color: var(--text-3);
  cursor: pointer;
}
.chip-x:hover { color: var(--text); }

/* 系统通知气泡、工具卡片容器、分支/回滚/队列与内联 @ / 菜单样式 */
.sys-notice {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  align-self: center;
  margin: 4px auto;
  padding: 5px 12px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 11.5px;
}
.sys-notice .i { width: 13px; height: 13px; color: var(--accent); flex: none; }
.tool-list {
  display: grid;
  gap: 6px;
  margin-bottom: 6px;
}
.turn-diff-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.diff-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  font-size: 11px;
  color: var(--text-2);
  cursor: pointer;
}
.diff-pill:hover { border-color: var(--accent-line); color: var(--text); }
.diff-pill .i { width: 11px; height: 11px; color: var(--accent); }
.reverted-tag {
  font-size: 11px;
  color: var(--text-3);
  padding: 2px 6px;
}
.user-col {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  max-width: 80%;
  min-width: 0;
}
.mmsg.user .user-col { max-width: 82%; }
:global(.dock) .msg.user .user-col,
.thread-compact .msg.user .user-col { max-width: 92%; }
.msg.user .user-col > .bubble,
.mmsg.user .user-col > .bubble {
  max-width: 100%;
}
.user-foot {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 4px;
  padding-right: 2px;
}
.user-hover-actions {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  opacity: 0.72;
  transition: opacity var(--dur-1);
}
.msg.user:hover .user-hover-actions,
.msg.user:focus-within .user-hover-actions,
.mmsg.user .user-hover-actions {
  opacity: 1;
}
.msg.user .user-hover-actions .btn-subtle,
.mmsg.user .user-hover-actions .btn-subtle {
  color: var(--text-3);
}
.msg.user .user-hover-actions .btn-subtle:hover,
.mmsg.user .user-hover-actions .btn-subtle:hover {
  background: var(--surface-3);
  color: var(--text);
}
.branch-switcher {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  font-size: 11px;
  color: var(--text-2);
}
.branch-nav-btn {
  padding: 0 3px;
  color: var(--text-2);
  cursor: pointer;
  font-weight: 600;
}
.branch-nav-btn:disabled { opacity: .35; cursor: not-allowed; }
.follow-queue {
  margin: 0 auto 6px;
  width: min(760px, 100%);
  padding: 6px 10px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-2);
  display: grid;
  gap: 5px;
}
.queue-hdr {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--text-3);
}
.queue-ic { width: 12px; height: 12px; color: var(--accent); }
.queue-items { display: grid; gap: 4px; }
.queue-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border-radius: var(--r-sm);
  background: var(--solid);
  border: 1px solid var(--line);
}
.queue-text {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
.queue-edit-input {
  flex: 1;
  min-width: 0;
  height: 26px;
  font-size: 12px;
}
.queue-icon-btn { width: 24px; height: 24px; flex: none; }
.queue-add-btn { height: 28px; padding: 0 9px; font-size: 11.5px; flex: none; }

.composer-box, .mcomposer .box { position: relative; }
.mention-popover {
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: calc(100% + 6px);
  z-index: 45;
  max-height: 240px;
  overflow-y: auto;
  display: grid;
  gap: 2px;
  padding: 5px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--solid);
  box-shadow: var(--shadow-pop);
}
.mention-option {
  display: flex;
  align-items: center;
  gap: 8px;
  min-block-size: 28px;
  padding: 5px 8px;
  border-radius: 7px;
  text-align: left;
  font-size: 12px;
  color: var(--text);
  cursor: pointer;
}
.mention-option:hover,
.mention-option.is-active {
  background: var(--surface-2);
}
.mention-ic { width: 13px; height: 13px; color: var(--text-3); flex: none; }
.mention-option.is-active .mention-ic { color: var(--accent); }
.mention-title {
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 550;
  flex: none;
  max-width: 55%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.mention-desc {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  color: var(--text-3);
  text-align: right;
}
.msg-parts {
  display: grid;
  gap: 8px;
}
.msg-parts .thought-box {
  margin-bottom: 0;
}
.voice-btn.is-recording {
  color: var(--warn);
  background: var(--warn-soft);
}
.mcp-sub-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  border-bottom: 1px solid var(--line);
}
.mcp-empty { padding: 14px 12px; font-size: 12px; text-align: center; }
.mcp-row {
  padding: 8px 10px;
  border-bottom: 1px solid var(--line);
  display: grid;
  gap: 4px;
}
.mcp-row:last-child { border-bottom: 0; }
.mcp-row-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.mcp-name { font-weight: 600; font-size: 12px; color: var(--text); }
.mcp-badge {
  padding: 1px 6px;
  border-radius: var(--r-full);
  font-size: 10.5px;
}
.mcp-badge.is-ok { background: color-mix(in srgb, var(--ok) 15%, transparent); color: var(--ok); }
.mcp-badge.is-warn { background: var(--warn-soft); color: var(--warn); }
.mcp-tools, .mcp-err { margin: 0; font-size: 11px; }
.mcp-err { color: var(--warn); }

.thread-search-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  flex: none;
}
.ts-ic { width: 14px; height: 14px; color: var(--accent); flex: none; }
.ts-input {
  flex: 1;
  min-width: 0;
  height: 26px;
  padding: 0 8px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-xs);
  background: var(--solid);
  color: var(--text);
  font-size: 12px;
}
.ts-count {
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
}
.ts-nav-btn { width: 24px; height: 24px; }
.msg-foot-actions .msg-foot-secondary {
  opacity: 0;
  pointer-events: none;
  transition: opacity var(--dur-1);
}
.msg.agent:hover .msg-foot-actions .msg-foot-secondary,
.msg.agent:focus-within .msg-foot-actions .msg-foot-secondary,
.mmsg.agent .msg-foot-actions .msg-foot-secondary,
.msg-foot-actions .msg-foot-secondary.is-bookmarked {
  opacity: 1;
  pointer-events: auto;
}
.bookmark-strip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--accent-soft) 35%, var(--surface-1));
  flex: none;
  overflow-x: auto;
}
.bm-lead {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
  flex: none;
}
.bm-lead .i { width: 12px; height: 12px; }
.bm-chips {
  display: flex;
  align-items: center;
  gap: 5px;
}
.bm-chip {
  padding: 2px 8px;
  border: 1px solid var(--accent-line);
  border-radius: var(--r-full);
  background: var(--solid);
  color: var(--text-2);
  font-size: 11px;
  cursor: pointer;
  white-space: nowrap;
}
.bm-chip:hover { color: var(--accent); }
.msg.is-search-hit .bubble,
.mmsg.is-search-hit .bubble,
.sys-notice.is-search-hit {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.msg-foot-actions .is-bookmarked {
  color: var(--accent);
  background: var(--accent-soft);
}
.draft-token-pill {
  padding: 2px 7px;
  border-radius: var(--r-full);
  background: var(--surface-2);
  border: 1px solid var(--line);
  font-size: 10.5px;
  color: var(--text-3);
  white-space: nowrap;
}
.draft-trim-pill {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 7px;
  border: 1px solid var(--accent-line);
  border-radius: var(--r-full);
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 10.5px;
  cursor: pointer;
  white-space: nowrap;
}
.draft-trim-pill:hover { filter: brightness(0.96); }
.draft-trim-pill .i { width: 11px; height: 11px; }
.trust-policy-section {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
  display: grid;
  gap: 6px;
}
.trust-sec-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-2);
}
.trust-sec-count {
  padding: 0 6px;
  border-radius: var(--r-full);
  background: var(--surface-2);
  font-size: 10.5px;
  color: var(--text-3);
}
.trust-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.trust-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 6px;
  border-radius: 5px;
  border: 1px solid var(--line-strong);
  background: var(--surface-2);
  font-size: 11px;
}
.trust-chip code { font-family: var(--mono); }
.trust-chip-x {
  border: 0;
  background: transparent;
  color: var(--text-3);
  cursor: pointer;
  padding: 0 2px;
  font-size: 12px;
}
.trust-chip-x:hover { color: var(--warn); }
.trust-empty {
  margin: 0;
  font-size: 11px;
  line-height: 1.4;
}
.trust-add-form {
  display: flex;
  gap: 4px;
}
.trust-add-input {
  flex: 1;
  min-width: 0;
  height: 26px;
  padding: 0 7px;
  font-size: 11.5px;
  font-family: var(--mono);
}

/* ---------------- 现代简洁增强：长列表优化、未读分割、浮动胶囊、划词引用、模式胶囊 ---------------- */
.thread-root {
  position: relative;
}
.is-deferred-msg {
  content-visibility: auto;
  contain-intrinsic-size: auto none auto 140px;
}
.older-history-bar {
  display: flex;
  justify-content: center;
  padding: 4px 0 12px;
}
.older-history-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  background: var(--surface-1);
  color: var(--text-2);
  font-size: 11.5px;
  cursor: pointer;
  transition: background-color 0.14s ease, color 0.14s ease;
}
.older-history-btn:hover {
  background: var(--surface-2);
  color: var(--text);
}
.older-history-btn .i {
  width: 12px;
  height: 12px;
}
.unread-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 6px 0 10px;
  font-size: 11px;
  font-weight: 560;
  color: var(--accent);
}
.unread-divider::before,
.unread-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: color-mix(in srgb, var(--accent) 30%, transparent);
}
.sel-quote-pill {
  position: absolute;
  transform: translateX(-50%);
  z-index: 28;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 11px;
  border: 0;
  border-radius: var(--r-full);
  background: var(--accent);
  color: var(--accent-ink, #fff);
  font-size: 11.5px;
  font-weight: 560;
  box-shadow: var(--shadow-2);
  cursor: pointer;
}
.sel-quote-pill .i {
  width: 12px;
  height: 12px;
}
.jump-latest-pill {
  position: absolute;
  left: 50%;
  bottom: calc(100% + 10px);
  transform: translateX(-50%);
  z-index: 25;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 5px 12px;
  border: 1px solid var(--line-strong);
  border-radius: var(--r-full);
  background: color-mix(in srgb, var(--solid) 92%, transparent);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  color: var(--text);
  font-size: 11.5px;
  font-weight: 550;
  box-shadow: var(--shadow-2);
  cursor: pointer;
}
.thread-mobile .jump-latest-pill {
  left: auto;
  right: 16px;
  transform: none;
}
.jump-latest-pill.is-mobile-circle {
  width: 34px;
  height: 34px;
  padding: 0;
  border-radius: 50%;
}
.jump-latest-pill.is-mobile-circle .i {
  width: 15px;
  height: 15px;
}
.thread-mobile .jump-pill-enter-from,
.thread-mobile .jump-pill-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
.jump-latest-pill:hover {
  background: var(--solid);
  border-color: var(--accent-line);
}
.jump-latest-pill .i {
  width: 12px;
  height: 12px;
  color: var(--accent);
}
.jump-pill-enter-active,
.jump-pill-leave-active {
  transition: opacity 0.16s ease, transform 0.16s ease;
}
.jump-pill-enter-from,
.jump-pill-leave-to {
  opacity: 0;
  transform: translate(-50%, 8px);
}
.interrupted-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 0 clamp(12px, 4%, 38px) 6px;
  padding: 5px 10px;
  border-radius: var(--r-sm);
  border: 1px solid color-mix(in srgb, var(--warn) 32%, var(--line));
  background: color-mix(in srgb, var(--warn-soft) 55%, var(--surface-1));
  font-size: 12px;
}
.interrupted-txt {
  color: var(--text-2);
}
.mode-seg {
  display: inline-flex;
  align-items: center;
  padding: 2px;
  border-radius: var(--r-full);
  background: var(--surface-2);
  border: 1px solid var(--line);
  flex: none;
}
.mode-seg-btn {
  padding: 2px 8px;
  border: 0;
  border-radius: var(--r-full);
  background: transparent;
  color: var(--text-3);
  font-size: 11px;
  font-weight: 550;
  cursor: pointer;
  transition: background-color 0.14s ease, color 0.14s ease;
}
.mode-seg-btn.is-active {
  background: var(--solid);
  color: var(--text);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}
.queue-att-badge {
  margin-left: 5px;
  font-style: normal;
  font-size: 10.5px;
  color: var(--text-3);
}
.chip--paste {
  border-color: var(--line-strong);
  background: var(--surface-2);
}
.chip-paste-trigger {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border: 0;
  padding: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
}
.paste-preview-box {
  margin: 4px 0 6px;
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  background: var(--surface-2);
  overflow: hidden;
}
.paste-preview-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  font-size: 11px;
  color: var(--text-3);
  border-bottom: 1px solid var(--line);
}
.paste-preview-body {
  margin: 0;
  padding: 7px 9px;
  max-height: 130px;
  overflow: auto;
  font-family: var(--mono);
  font-size: 11px;
  line-height: 1.45;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
}
.speech-interim-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  margin-bottom: 4px;
  border-radius: var(--r-xs);
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11.5px;
}
.speech-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  flex: none;
}

/* 降噪克制：助手消息底栏操作区默认柔和半隐，悬停时浮现 */
.msg.agent .msg-foot-actions {
  opacity: 0.42;
  transition: opacity 0.16s ease;
}
.msg.agent:hover .msg-foot-actions,
.msg.agent:focus-within .msg-foot-actions {
  opacity: 1;
}

/* 窄分屏自适应容器查询：避免并排打开工作台时模型名与权限胶囊被挤压成单字母 */
.composer-box {
  container-type: inline-size;
}
@container (max-width: 520px) {
  .composer-row {
    gap: 4px;
  }
  .trigger-provider,
  .draft-token-pill {
    display: none;
  }
  .mode-seg-btn {
    padding: 2px 6px;
    font-size: 10.5px;
  }
  .model-trigger {
    max-width: 150px;
  }
  .safety-badge .trigger-label {
    max-width: 72px;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}
@container (max-width: 390px) {
  .safety-badge .trigger-label {
    display: none;
  }
}

/* 无边框轻过程流（Thought 降噪优化） */
.thought-box.thought-light {
  border: 0;
  background: transparent;
  padding: 0;
}
.thought-box.thought-light > summary {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 6px;
  border-radius: var(--r-xs);
  color: var(--text-3);
  font-size: 12px;
  background: transparent;
}
.thought-box.thought-light > summary:hover {
  background: var(--surface-2);
  color: var(--text-2);
}
.thought-chev {
  width: 12px;
  height: 12px;
  flex: none;
  color: var(--text-3);
  transition: transform var(--dur-1, 140ms) var(--ease-out, ease);
}
.thought-box.thought-light[open] > summary .thought-chev {
  transform: rotate(90deg);
  color: var(--text-2);
}
.agent-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 5px;
}
.msg.agent .agent-col > .bubble {
  max-width: 100%;
}
.thread-mobile .mmsg.agent .agent-col {
  width: 100%;
  max-width: 100%;
}
.thread-mobile .mmsg.agent .bubble {
  max-width: 100%;
  width: 100%;
  box-sizing: border-box;
}
.msg-foot--outside {
  width: 100%;
  margin-top: 0;
  padding: 2px 4px 0;
  border-top: 0;
  background: transparent;
  justify-content: flex-start;
}
.msg-foot--outside .msg-foot-actions {
  margin-left: 0;
  justify-content: flex-start;
}
.thread-mobile .msg-foot--outside {
  gap: 4px 8px;
}
.thread-mobile .msg-foot--outside .msg-foot-actions {
  gap: 4px;
}
.thread-mobile .msg-foot--outside .btn-sm {
  height: 26px;
  padding: 0 7px;
  font-size: 11.5px;
}
.thought-lbl {
  font-weight: 520;
}
.thought-cnt {
  font-size: 11px;
  opacity: 0.72;
}
.thought-live-preview {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-style: italic;
  opacity: 0.72;
}
.thought-box.thought-light .thought-body {
  margin: 4px 0 6px 12px;
  padding: 2px 0 2px 10px;
  border-left: 1.5px solid var(--line);
  background: transparent;
  color: var(--text-3);
  font-size: 12px;
}

/* 限额/模型报错卡片内一键救场行 */
.error-card-wrap {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
}
.error-card-top {
  display: flex;
  align-items: flex-start;
  gap: 7px;
}
.error-rescue-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding-top: 6px;
  border-top: 1px dashed color-mix(in srgb, var(--warn) 35%, var(--line));
}
.error-rescue-lbl {
  font-size: 11.5px;
  color: var(--text-2);
}

/* 双击 Esc 防误触轻提示 */
.esc-arm-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin: 0 clamp(12px, 4%, 38px) 6px;
  padding: 5px 10px;
  border-radius: var(--r-sm);
  border: 1px solid var(--line-strong);
  background: var(--surface-2);
  font-size: 12px;
  color: var(--text-2);
}
.esc-arm-banner kbd {
  padding: 1px 5px;
  border-radius: 4px;
  border: 1px solid var(--line-strong);
  background: var(--solid);
  font-family: var(--mono);
  font-size: 11px;
}

/* ---------------- 五套对话气泡样式偏好（Minimal / Claude / Lobe / AntD / Timeline） ---------------- */
/* 1. 极简无框（assistant-ui / prompt-kit，默认） */
.thread-root[data-bubble-style="minimal"] :is(.msg.user, .mmsg.user) .bubble {
  background: var(--surface-3);
  color: var(--text);
  border: 0;
  border-radius: 18px 18px 6px 18px;
  box-shadow: none;
  padding: 9px 14px;
}
.thread-root[data-bubble-style="minimal"] :is(.msg.agent, .mmsg.agent) .bubble {
  background: transparent;
  box-shadow: none;
  border: 0;
  border-radius: 0;
  padding: 2px 2px;
}

/* 2. 温润描边（Claude 风格） */
.thread-root[data-bubble-style="claude"] :is(.msg.user, .mmsg.user) .bubble {
  background: color-mix(in srgb, var(--surface-3) 78%, #f5f1e8);
  color: var(--text);
  border: 1px solid var(--line-strong);
  border-radius: 18px;
  box-shadow: none;
  padding: 9px 14px;
}
:global([data-mode="dark"]) .thread-root[data-bubble-style="claude"] :is(.msg.user, .mmsg.user) .bubble {
  background: var(--surface-3);
}
.thread-root[data-bubble-style="claude"] :is(.msg.agent, .mmsg.agent) .bubble {
  background: transparent;
  box-shadow: none;
  border: 0;
  border-radius: 0;
  padding: 2px 2px;
}
.thread-root[data-bubble-style="claude"] .thought-box.thought-light {
  border-left: 2px solid var(--line-strong);
  padding-left: 8px;
  border-radius: 0;
}

/* 3. 现代轻卡片（LobeChat 风格） */
.thread-root[data-bubble-style="lobe"] :is(.msg.user, .mmsg.user) .bubble {
  background: var(--accent);
  color: var(--accent-ink);
  border: 0;
  border-radius: 14px;
  box-shadow: none;
  padding: 9px 14px;
}
.thread-root[data-bubble-style="lobe"] :is(.msg.agent, .mmsg.agent) .bubble {
  background: var(--surface-2);
  color: var(--text);
  border: 0;
  border-radius: 14px;
  box-shadow: none;
  padding: 11px 14px;
}

/* 4. 结构化边框（Ant Design X 风格） */
.thread-root[data-bubble-style="antd"] :is(.msg.user, .mmsg.user) .bubble {
  background: var(--accent-soft);
  color: var(--text);
  border: 1px solid var(--accent-line);
  border-radius: 12px;
  box-shadow: none;
  padding: 9px 14px;
}
.thread-root[data-bubble-style="antd"] :is(.msg.agent, .mmsg.agent) .bubble {
  background: var(--solid);
  color: var(--text);
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  box-shadow: var(--shadow-1);
  padding: 11px 14px;
}

/* 5. 时间轴工作流（Cursor / Linear 风格） */
.thread-root[data-bubble-style="timeline"] :is(.msg.user, .mmsg.user) {
  justify-content: stretch;
}
.thread-root[data-bubble-style="timeline"] :is(.msg.user, .mmsg.user) .user-col {
  width: 100%;
  max-width: 100%;
  align-items: stretch;
}
.thread-root[data-bubble-style="timeline"] :is(.msg.user, .mmsg.user) .bubble {
  width: 100%;
  max-width: 100%;
  box-sizing: border-box;
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--line);
  border-left: 3px solid var(--accent);
  border-radius: 10px;
  box-shadow: none;
  padding: 8px 12px;
}
.thread-root[data-bubble-style="timeline"] :is(.msg.agent, .mmsg.agent) .bubble {
  background: transparent;
  box-shadow: none;
  border: 0;
  border-left: 2px solid var(--line-strong);
  border-radius: 0;
  margin-left: 4px;
  padding: 2px 0 4px 12px;
}
</style>
