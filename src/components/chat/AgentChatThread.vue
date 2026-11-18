<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, useId, watch, watchEffect } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { useDataStore } from '../../stores/data'
import { sessionKey as buildSessionKey, useFleetStore } from '../../stores/fleet'
import { useWebsitesStore } from '../../stores/websites'
import { formatTokenCount } from '../../services/tokenUsage'
import type { ApprovalDecision, ArtifactRef, ChatMessage, FleetModel } from '../../types/fleet'
import OpusIcon from '../ui/OpusIcon.vue'
import ArtifactPill from './ArtifactPill.vue'
import MarkdownMessage from './MarkdownMessage.vue'
import PermissionRequestCard from './PermissionRequestCard.vue'
import { formatBytes, getProviderMeta, type OpusIconName } from './providerMeta'

const props = defineProps<{
  mobile?: boolean
  compact?: boolean
  sessionKey?: string
}>()

const emit = defineEmits<{
  action: [message: string]
  openHandoff: [payload: { summary: string; artifact?: ArtifactRef }]
}>()

const auth = useAuthStore()
const dataStore = useDataStore()
const websitesStore = useWebsitesStore()
const fleet = useFleetStore()
const sending = ref(false)
const draggingFiles = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const listEl = ref<HTMLElement | null>(null)
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
type AttachSubKey = 'dirs' | 'data' | 'sessions' | 'commands'
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
    fleet.runSettings[settingsKey.value] = { ...options.value, model: modelId, effort: undefined }
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
  fleet.runSettings[settingsKey.value] = {
    ...options.value,
    model: modelId,
    effort: effort || undefined,
  }
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
  } else if (next === 'attach') {
    ensurePersonalStoresLoaded()
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
  }
}

watch(
  () => [target.value, effectiveNode.value?.status, caps.value.includes('models')] as const,
  ([key, status, supportsModels]) => {
    if (status === 'online' && supportsModels && effectiveNode.value && !fleet.catalogs[key]) {
      fleet.requestModels(effectiveNode.value.id, effectiveProvider.value)
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

watch(settingsKey, () => {
  closeSettings()
  followLatest.value = true
})

function trackMessageScroll() {
  const list = listEl.value
  if (list) followLatest.value = list.scrollHeight - list.clientHeight - list.scrollTop < 12
}

watchEffect(onCleanup => {
  const measure = draftMeasure.value
  const list = listEl.value
  if (!measure || !list) return
  const editorObserver = new ResizeObserver(() => {
    editorHeight.value = Math.ceil(measure.getBoundingClientRect().height)
    if (settingsOpen.value) positionSettings()
  })
  const messageObserver = new ResizeObserver(() => {
    if (followLatest.value) list.scrollTop = list.scrollHeight
  })
  editorObserver.observe(measure)
  messageObserver.observe(list)
  window.addEventListener('resize', positionSettings)
  onCleanup(() => {
    editorObserver.disconnect()
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

watch(
  () => effectiveMessages.value.map(m => m.text.length + (m.thought?.length ?? 0)).join(','),
  async () => {
    await nextTick()
    if (listEl.value) {
      listEl.value.scrollTop = listEl.value.scrollHeight
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
  if (!files.length) return
  appendFiles(files)
  if (!dt.getData('text/plain')) {
    ev.preventDefault()
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

async function handleSubmit() {
  if (isStreaming.value) {
    fleet.cancelSessionRun(effectiveKey.value)
    return
  }
  if (sending.value) return
  const text = draft.value.trim()
  const files = [...queuedFiles.value]
  const contexts = [...queuedContexts.value]
  if (!text && !files.length && !contexts.length) return
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
  const payloadText = contextBlock
    ? `${contextBlock}${text || (files.length ? '' : '请结合以上附加上下文进行分析或处理。')}`.trim()
    : text
  sending.value = true
  try {
    if (effectiveKey.value && fleet.sessionsByKey[effectiveKey.value]) {
      await fleet.sendPromptToSpecificSession(effectiveKey.value, payloadText, files, { ...options.value })
    } else {
      await fleet.sendPrompt(payloadText, files, { ...options.value })
    }
    if (submitted.text === originalText) submitted.text = ''
    submitted.files = submitted.files.filter(file => !files.includes(file))
    if (contexts.length) {
      const sentIds = new Set(contexts.map(c => c.id))
      contextsByKey.value = {
        ...contextsByKey.value,
        [submittedKey]: (contextsByKey.value[submittedKey] ?? []).filter(c => !sentIds.has(c.id)),
      }
    }
  } catch (err) {
    emit('action', err instanceof Error ? err.message : '消息发送失败')
  } finally {
    sending.value = false
  }
}

function handleKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
    ev.preventDefault()
    void handleSubmit()
  }
}

function handleApproval(callId: string, decision: ApprovalDecision) {
  fleet.respondPermission(callId, decision)
}

function toggleThought(id: string) {
  expandedThought.value = { ...expandedThought.value, [id]: !expandedThought.value[id] }
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
  if (msgCopyTimer) clearTimeout(msgCopyTimer)
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
  <div class="thread-root" :class="{ 'thread-compact': compact, 'thread-mobile': mobile }" @keydown="handleThreadKeydown">
    <div ref="listEl" @scroll.passive="trackMessageScroll" :class="mobile ? 'mmsgs' : 'msgs'">
      <div :class="mobile ? 'mmsgs-inner' : 'msgs-inner'">
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
                ? '输入任务，或附上文件开始会话。'
                : '目标节点当前离线，请确认宿主机已启动 Studiolo AgentNode。'
            }}
          </p>
          <p v-else>前往「设置 -> Agent 与连接」添加控制节点，发放 sn_live_ 凭证并在目标机器启动 agent-node。</p>
        </div>

        <template v-for="msg in effectiveMessages" :key="msg.id">
          <div :class="[mobile ? 'mmsg' : 'msg', msg.role === 'user' ? 'user' : 'agent', getProviderMeta(msg.provider).accentClass]">
            <span v-if="msg.role !== 'user'" class="am" :title="getProviderMeta(msg.provider).label">
              <OpusIcon :name="getProviderMeta(msg.provider).icon" />
            </span>
            <div class="bubble">
              <div v-if="msg.toolCalls?.length" class="tool-list">
                <span v-for="tool in msg.toolCalls" :key="tool.id" class="tool">
                  <OpusIcon name="terminal" />
                  <span>{{ tool.name }}{{ tool.detail ? ` · ${tool.detail}` : '' }}</span>
                </span>
              </div>

              <details v-if="msg.thought" class="thought-box" :open="expandedThought[msg.id]" @toggle="toggleThought(msg.id)">
                <summary>思考过程 ({{ msg.thought.length }} 字)</summary>
                <div class="thought-body">{{ msg.thought }}</div>
              </details>

              <MarkdownMessage v-if="msg.text && msg.role !== 'user'" :text="msg.text" :streaming="msg.streaming" />
              <div v-else-if="msg.text" class="msg-text">{{ msg.text }}</div>
              <div v-else-if="msg.streaming" class="typing" aria-label="思考与输出中"><i></i><i></i><i></i></div>

              <div v-if="msg.error" class="state warn">
                <OpusIcon name="alert" />
                <span>{{ msg.error }}</span>
              </div>

              <PermissionRequestCard
                v-for="card in msg.approvals"
                :key="card.callId"
                :card="card"
                @respond="handleApproval"
              />

              <template v-for="art in msg.artifacts" :key="art.artifactId">
                <button
                  v-if="art.mime.startsWith('image/') && fleet.imagePreviewByArtifactId[art.artifactId]"
                  type="button"
                  class="msg-img-thumb"
                  :title="`查看大图：${art.fileName}`"
                  @click="openImageLightbox(fleet.imagePreviewByArtifactId[art.artifactId], art.fileName)"
                >
                  <img :src="fleet.imagePreviewByArtifactId[art.artifactId]" :alt="art.fileName" />
                </button>
                <ArtifactPill
                  :artifact="art"
                  :compact="compact"
                  @status="emit('action', $event)"
                  @handoff="shareAsHandoff(msg, $event)"
                />
              </template>

              <div v-if="msg.role === 'assistant' && !msg.streaming && (msg.text || msg.error)" class="msg-foot">
                <span v-if="msg.createdAt" class="msg-time num">{{ formatMsgTime(msg.createdAt) }}</span>
                <div class="msg-foot-actions">
                  <button
                    v-if="msg.text"
                    type="button"
                    class="btn btn-subtle btn-sm"
                    @click="copyMessageText(msg)"
                  >
                    <OpusIcon :name="copiedMsgId === msg.id ? 'check' : 'copy'" />
                    <span>{{ copiedMsgId === msg.id ? '已复制' : '复制' }}</span>
                  </button>
                  <button
                    type="button"
                    class="btn btn-subtle btn-sm"
                    :disabled="sending || isStreaming"
                    @click="retryTurn(msg)"
                  >
                    <OpusIcon name="sync" />
                    <span>重试</span>
                  </button>
                  <button
                    v-if="msg.text && !compact"
                    type="button"
                    class="btn btn-subtle btn-sm"
                    @click="shareAsHandoff(msg)"
                  >
                    <OpusIcon name="send" />
                    <span>交接会话</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </template>
      </div>
    </div>
    <div :class="mobile ? 'mcomposer' : 'composer'">
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
          </TransitionGroup>
          <div class="editor-field">
            <div ref="draftMeasure" class="draft-measure" aria-hidden="true">{{ draft + '\u200b' }}</div>
            <textarea ref="textareaRef" v-model="draft" class="composer-input" :style="{ height: editorHeight ? `${editorHeight}px` : undefined }"
              :placeholder="effectiveNode ? `向 ${effectiveNode.name} 描述任务…` : '暂无在线节点…'"
              aria-label="任务内容" title="Enter 发送，Shift+Enter 换行" rows="1" @keydown="handleKeydown" @paste="handleComposerPaste" />
          </div>
        </div>
        <div class="composer-row">
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
              <span class="trigger-label">{{ model?.label || '默认模型' }}</span>
              <span v-if="triggerEffortLabel" class="trigger-effort">{{ triggerEffortLabel }}</span>
              <OpusIcon name="chevD" class="trigger-chev" />
            </button>
            <span v-if="!mobile && !settingsOpen" class="trigger-tip" role="tooltip">选择模型 <kbd>Ctrl+/</kbd></span>
          </span>
          <span class="spacer" />
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
            type="button"
            class="send"
            :class="{ stop: isStreaming }"
            :disabled="sending || (!isStreaming && !draft.trim() && !queuedFiles.length && !queuedContexts.length)"
            :aria-label="isStreaming ? '中止当前生成' : '发送消息'"
            @click="handleSubmit"
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
        :class="panel === 'model' ? 'is-model' : panel === 'attach' ? 'is-attach' : 'is-permissions'"
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
          </div>
          <div class="popover-footer">
            <p class="picker-footer-note">
              <OpusIcon name="info" />
              <span>支持拖拽文件或 Ctrl+V 直接贴图</span>
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
        </template>
      </div>
    </div>
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
          <button type="submit" class="icon-btn lightbox-close" aria-label="关闭大图预览" autofocus>
            <OpusIcon name="x" />
          </button>
        </header>
        <img v-if="lightboxSrc" :src="lightboxSrc" :alt="lightboxAlt" class="lightbox-img" />
      </form>
    </dialog>
  </div>
</template>

<style scoped>
.thread-root {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr) auto;
  min-height: 0;
  min-width: 0;
  height: 100%;
}
.thread-root:not(.thread-mobile) { flex: 1; height: auto; }
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
  gap: 4px;
  padding: 8px 10px 6px 12px;
  border: 1px solid var(--line-strong);
  border-radius: 20px;
  box-shadow: 0 2px 8px rgba(15, 23, 42, .04), 0 0 0 3px color-mix(in srgb, var(--surface-2) 85%, transparent);
}
.mcomposer .composer-row {
  display: flex;
  align-items: center;
  gap: 4px;
}
.mcomposer .trigger-wrap { max-width: 48%; }
.mcomposer .model-trigger { padding: 0 6px; font-size: 12px; }
.mcomposer .safety-badge { max-width: 46%; height: 26px; padding: 0 8px; font-size: 11.5px; }
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
.msg.agent .bubble, .mmsg.agent .bubble { color: var(--text); }
.msg.user .bubble, .mmsg.user .bubble { color: var(--accent-ink); }
:deep(.msg.user .artifact-pill),
:deep(.mmsg.user .artifact-pill) {
  background: var(--solid);
  color: var(--text);
}
.msg-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
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
  align-items: center;
  gap: 4px;
  margin-left: auto;
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
</style>
