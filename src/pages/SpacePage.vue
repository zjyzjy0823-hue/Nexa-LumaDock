<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import OpusIcon from '../components/ui/OpusIcon.vue'
import SpacePasswordGate from '../components/space/SpacePasswordGate.vue'
import { useCopyFeedback } from '../composables/useCopyFeedback'
import { useSpaceStore } from '../stores/space'
import { getApiBaseUrl } from '../services/fleetUrl'
import type { SpaceTier, SpaceTokenScope } from '../services/spaceApi'
import type { SpaceEntryType } from '../services/spaceCrypto'

const props = defineProps<{ mobile: boolean }>()
const emit = defineEmits<{ action: [message: string]; back: [] }>()

const spaceStore = useSpaceStore()
const { copy: copyWithFeedback, isCopied } = useCopyFeedback()

// 中栏顶部视图切换：内容 / API Token / 审计日志 / 空间与安全
type SpaceSubView = 'entries' | 'tokens' | 'audit' | 'security'
type CanvasMode = 'compose' | 'detail'
type ComposeTab = 'text' | 'file'

interface QueuedUploadFile {
  id: string
  file: File
  title: string
  note: string
  previewUrl: string | null
}

const activeTab = ref<SpaceSubView>('entries')
const canvasMode = ref<CanvasMode>('compose')
const composeTab = ref<ComposeTab>('text')
const searchQuery = ref('')
const filterType = ref<SpaceEntryType | 'all'>('all')
const mobilePanel = ref<'spaces' | 'entries' | 'canvas'>('spaces')

// 新建空间原生 <dialog> 状态
const createSpaceDialogRef = ref<HTMLDialogElement | null>(null)
const createSpaceOpen = ref(false)
const newSpaceName = ref('')
const newSpaceDesc = ref('')
const newSpaceTier = ref<SpaceTier>('standard')
const newSpacePassword = ref('')
const createSpaceBusy = ref(false)

// 右侧大画布 · 撰写文本状态
const composeTextType = ref<Exclude<SpaceEntryType, 'file'>>('text')
const composeTitle = ref('')
const composeTags = ref('')
const composeText = ref('')
const composeBusy = ref(false)

// 右侧大画布 · 文件上传队列与拖拽状态
const fileInputRef = ref<HTMLInputElement | null>(null)
const uploadQueue = ref<QueuedUploadFile[]>([])
const uploadTags = ref('')
const uploadNote = ref('')
const uploadBusy = ref(false)
const uploadProgressText = ref('')
const isDraggingFile = ref(false)
let dragDepth = 0

// 标准条目内联编辑态
const editingStandard = ref(false)
const editTitle = ref('')
const editText = ref('')
const editTags = ref('')

// Token 签发表单状态
const newTokenName = ref('')
const newTokenScopes = ref<SpaceTokenScope[]>(['read'])
const newTokenDays = ref<string>('30')
const newTokenEntryScope = ref<'all' | 'selected'>('all')
const newTokenEntryIds = ref<string[]>([])
const tokenBusy = ref(false)

// 改密与 Epoch 轮换表单状态
const changeOldPwd = ref('')
const changeNewPwd = ref('')
const rotateNewPwd = ref('')
const securityBusy = ref(false)

// 统一按次密码门禁弹窗状态
const gateOpen = ref(false)
const gateTitle = ref('')
const gateDesc = ref('')
const gateConfirmLabel = ref('确认解锁')
const gateBusy = ref(false)
const gateError = ref('')
let gateCallback: ((password: string) => Promise<void>) | null = null

const tierMeta: Record<SpaceTier, { label: string; short: string; hint: string; badgeClass: string }> = {
  standard: {
    label: '普通共享',
    short: '普通',
    hint: '随时查看 · API',
    badgeClass: 'tier-standard',
  },
  protected: {
    label: '受控机密',
    short: '机密',
    hint: '按次输密 · 审计',
    badgeClass: 'tier-protected',
  },
  e2ee: {
    label: '极密保险库',
    short: 'E2EE',
    hint: '本机加密 · 零知识',
    badgeClass: 'tier-e2ee',
  },
}

const entryTypeMeta: Record<SpaceEntryType, { label: string; icon: 'note' | 'braces' | 'key' | 'file' }> = {
  text: { label: '文本', icon: 'note' },
  config: { label: '配置', icon: 'braces' },
  key: { label: '密钥', icon: 'key' },
  file: { label: '文件', icon: 'file' },
}

const currentSpace = computed(() => spaceStore.selectedSpace)
const currentDetail = computed(() => spaceStore.selectedEntryDetail)
const currentUnlocked = computed(() =>
  spaceStore.unlockedView && spaceStore.unlockedView.entryId === spaceStore.selectedEntryId
    ? spaceStore.unlockedView
    : null,
)

// 已解密图片文件在内存中的安全预览 URL（离页/锁定由 spaceStore.clearSensitiveMemory 自动回收）
const unlockedImagePreviewUrl = computed(() => {
  const view = currentUnlocked.value
  if (!view?.fileBlob || !view.mime?.startsWith('image/')) return null
  return spaceStore.registerObjectUrl(view.fileBlob)
})

const maxFileLimitLabel = computed(() => {
  const bytes = spaceStore.capabilities?.maxFileBytes
  return bytes && bytes > 0 ? `单文件上限 ${formatBytes(bytes)}` : ''
})

const filteredEntries = computed(() => {
  const space = currentSpace.value
  const q = searchQuery.value.trim().toLowerCase()
  return spaceStore.entries.filter(item => {
    if (filterType.value !== 'all' && item.entryType !== filterType.value) return false
    if (!q) return true
    if (space?.tier === 'e2ee') {
      const m = spaceStore.decryptedCatalogByEntryId[item.id]
      if (!m) return false
      return (
        m.title.toLowerCase().includes(q)
        || (m.fileName ?? '').toLowerCase().includes(q)
        || (m.tags ?? []).some(t => t.toLowerCase().includes(q))
      )
    }
    return (
      (item.title ?? '').toLowerCase().includes(q)
      || (item.fileName ?? '').toLowerCase().includes(q)
      || item.tags.some(t => t.toLowerCase().includes(q))
    )
  })
})

const mobileHeaderTitle = computed(() => {
  if (mobilePanel.value === 'spaces') return '共享空间'
  if (mobilePanel.value === 'entries') return currentSpace.value?.name ?? '共享空间'
  if (activeTab.value === 'tokens') return 'API Token'
  if (activeTab.value === 'audit') return '审计日志'
  if (activeTab.value === 'security') return '空间与安全'
  if (canvasMode.value === 'compose') return composeTab.value === 'file' ? '上传文件' : '撰写文本'
  return displayEntryTitle(currentDetail.value ?? { id: '', title: '条目详情' })
})

function displayEntryTitle(item: { id: string; title: string | null }): string {
  if (currentSpace.value?.tier === 'e2ee') {
    return spaceStore.decryptedCatalogByEntryId[item.id]?.title ?? `密文条目 · ${item.id.slice(0, 8)}`
  }
  return item.title ?? item.id.slice(0, 8)
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

function formatQuotaPercent(used: number, quota: number): number {
  if (!quota || quota <= 0) return 0
  return Math.min(100, Math.max(2, Math.round((used / quota) * 100)))
}

function fileExtensionBadge(name: string | null | undefined): string {
  if (!name) return 'FILE'
  const idx = name.lastIndexOf('.')
  if (idx <= 0 || idx === name.length - 1) return 'FILE'
  return name.slice(idx + 1, idx + 6).toUpperCase()
}

function parseTags(raw: string): string[] {
  return raw
    .split(/[,，\s]+/)
    .map(t => t.replace(/^#/, '').trim())
    .filter(Boolean)
}

function inferTitleFromText(text: string): string {
  const firstLine = text
    .split(/\r?\n/)
    .map(line => line.trim())
    .find(Boolean)
  if (!firstLine) return '未命名文本'
  return firstLine.length > 42 ? `${firstLine.slice(0, 42)}…` : firstLine
}

// ---------------------------------------------------------------------------
// 视图与画布切换
// ---------------------------------------------------------------------------

function openCompose(tab: ComposeTab) {
  activeTab.value = 'entries'
  canvasMode.value = 'compose'
  composeTab.value = tab
  editingStandard.value = false
  if (props.mobile) {
    mobilePanel.value = 'canvas'
  }
}

function switchSubTab(tab: SpaceSubView) {
  activeTab.value = tab
  editingStandard.value = false
  if (props.mobile && tab !== 'entries') {
    mobilePanel.value = 'canvas'
  }
}

async function handleSelectSpace(spaceId: string) {
  await spaceStore.selectSpace(spaceId)
  activeTab.value = 'entries'
  editingStandard.value = false
  // 切换空间时如果空间里还没有选中条目，右侧默认展示撰写/上传大画布
  canvasMode.value = spaceStore.selectedEntryId ? 'detail' : 'compose'
  if (props.mobile) {
    mobilePanel.value = 'entries'
  }
}

async function handleSelectEntry(entryId: string) {
  editingStandard.value = false
  activeTab.value = 'entries'
  canvasMode.value = 'detail'
  await spaceStore.selectEntry(entryId)
  if (props.mobile) {
    mobilePanel.value = 'canvas'
  }
}

function handleMobileBack() {
  if (mobilePanel.value === 'canvas') {
    if (activeTab.value !== 'entries') {
      activeTab.value = 'entries'
    }
    mobilePanel.value = 'entries'
    spaceStore.clearSensitiveMemory()
    return
  }
  if (mobilePanel.value === 'entries') {
    mobilePanel.value = 'spaces'
    spaceStore.clearSensitiveMemory()
    return
  }
  emit('back')
}

// ---------------------------------------------------------------------------
// 新建空间原生 <dialog closedby="any">（带 Safari 等低版本 light-dismiss 兜底）
// ---------------------------------------------------------------------------

function openCreateSpaceDialog(presetTier?: SpaceTier) {
  if (presetTier) {
    if (presetTier === 'protected' && spaceStore.capabilities && !spaceStore.capabilities.protectedAvailable) {
      newSpaceTier.value = 'standard'
    } else {
      newSpaceTier.value = presetTier
    }
  }
  createSpaceOpen.value = true
  const dlg = createSpaceDialogRef.value
  if (dlg && !dlg.open) {
    dlg.showModal()
  }
}

function closeCreateSpaceDialog() {
  const dlg = createSpaceDialogRef.value
  if (dlg?.open) {
    dlg.close()
  }
  createSpaceOpen.value = false
}

function handleCreateSpaceDialogClose() {
  createSpaceOpen.value = false
}

function handleCreateSpaceDialogClick(event: MouseEvent) {
  const dlg = createSpaceDialogRef.value
  if (!dlg || 'closedBy' in HTMLDialogElement.prototype) return
  if (event.target !== dlg) return
  const rect = dlg.getBoundingClientRect()
  const isInside =
    rect.top <= event.clientY
    && event.clientY <= rect.top + rect.height
    && rect.left <= event.clientX
    && event.clientX <= rect.left + rect.width
  if (!isInside) {
    dlg.close()
  }
}

// ---------------------------------------------------------------------------
// 密码门禁弹窗
// ---------------------------------------------------------------------------

function openPasswordGate(options: {
  title: string
  description: string
  confirmLabel?: string
  onSubmit: (password: string) => Promise<void>
}) {
  gateTitle.value = options.title
  gateDesc.value = options.description
  gateConfirmLabel.value = options.confirmLabel ?? '确认解锁'
  gateError.value = ''
  gateCallback = options.onSubmit
  gateOpen.value = true
}

async function handleGateSubmit(password: string) {
  if (!gateCallback || gateBusy.value) return
  gateBusy.value = true
  gateError.value = ''
  try {
    await gateCallback(password)
    gateOpen.value = false
    gateCallback = null
  } catch (cause) {
    gateError.value = cause instanceof Error ? cause.message : '密码校验失败，请重试'
  } finally {
    gateBusy.value = false
  }
}

function closeGate() {
  gateOpen.value = false
  gateError.value = ''
  gateCallback = null
}

// ---------------------------------------------------------------------------
// 空间管理
// ---------------------------------------------------------------------------

async function handleCreateSpace() {
  if (createSpaceBusy.value || !newSpaceName.value.trim()) return
  createSpaceBusy.value = true
  try {
    await spaceStore.createSpace({
      name: newSpaceName.value.trim(),
      description: newSpaceDesc.value.trim(),
      tier: newSpaceTier.value,
      password: newSpaceTier.value === 'standard' ? undefined : newSpacePassword.value,
    })
    closeCreateSpaceDialog()
    newSpaceName.value = ''
    newSpaceDesc.value = ''
    newSpacePassword.value = ''
    activeTab.value = 'entries'
    canvasMode.value = 'compose'
    composeTab.value = 'text'
    emit('action', '共享空间已创建')
    if (props.mobile) mobilePanel.value = 'entries'
  } catch (cause) {
    emit('action', cause instanceof Error ? cause.message : '创建空间失败')
  } finally {
    createSpaceBusy.value = false
  }
}

async function handleArchiveCurrentSpace() {
  const sp = currentSpace.value
  if (!sp) return
  if (!window.confirm(`确认归档空间「${sp.name}」？归档将立即吊销该空间下所有 API Token。`)) return
  try {
    await spaceStore.archiveSpace(sp.id)
    activeTab.value = 'entries'
    canvasMode.value = 'compose'
    emit('action', '空间已归档并吊销关联 Token')
    if (props.mobile) mobilePanel.value = 'spaces'
  } catch (cause) {
    emit('action', cause instanceof Error ? cause.message : '归档空间失败')
  }
}

// ---------------------------------------------------------------------------
// 撰写文本保存
// ---------------------------------------------------------------------------

async function submitComposeText(password?: string) {
  const rawText = composeText.value
  const finalTitle = composeTitle.value.trim() || inferTitleFromText(rawText)
  composeBusy.value = true
  try {
    await spaceStore.createEntry({
      entryType: composeTextType.value,
      title: finalTitle,
      tags: parseTags(composeTags.value),
      contentText: rawText,
      password,
    })
    composeTitle.value = ''
    composeTags.value = ''
    composeText.value = ''
    canvasMode.value = 'detail'
    emit('action', '文本条目已保存')
    if (props.mobile) mobilePanel.value = 'canvas'
  } finally {
    composeBusy.value = false
  }
}

async function handleSaveComposeText() {
  const sp = currentSpace.value
  if (!sp || composeBusy.value) return
  if (!composeTitle.value.trim() && !composeText.value.trim()) {
    emit('action', '请先输入内容或标题')
    return
  }
  if (sp.tier === 'standard') {
    try {
      await submitComposeText()
    } catch (cause) {
      emit('action', cause instanceof Error ? cause.message : '保存失败')
    }
    return
  }
  openPasswordGate({
    title: '输入密码加密保存',
    description: '',
    confirmLabel: '保存',
    onSubmit: async pwd => {
      await submitComposeText(pwd)
    },
  })
}

function handleComposeKeydown(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault()
    void handleSaveComposeText()
  }
}

// ---------------------------------------------------------------------------
// 文件上传队列、拖拽与剪贴板粘贴
// ---------------------------------------------------------------------------

function appendFilesToQueue(fileList: FileList | File[]) {
  const files = Array.from(fileList)
  if (!files.length) return
  const maxBytes = spaceStore.capabilities?.maxFileBytes ?? 0
  let added = 0
  for (const file of files) {
    if (maxBytes > 0 && file.size > maxBytes) {
      emit('action', `「${file.name}」超出单文件上限（${formatBytes(maxBytes)}）`)
      continue
    }
    const previewUrl = file.type.startsWith('image/') ? URL.createObjectURL(file) : null
    uploadQueue.value.push({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      file,
      title: file.name,
      note: '',
      previewUrl,
    })
    added += 1
  }
  if (added > 0) {
    activeTab.value = 'entries'
    canvasMode.value = 'compose'
    composeTab.value = 'file'
    if (props.mobile) mobilePanel.value = 'canvas'
    emit('action', `已加入 ${added} 个待上传文件`)
  }
}

function clearUploadQueue() {
  for (const item of uploadQueue.value) {
    if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
  }
  uploadQueue.value = []
}

function removeQueuedFile(id: string) {
  const idx = uploadQueue.value.findIndex(item => item.id === id)
  if (idx < 0) return
  const [removed] = uploadQueue.value.splice(idx, 1)
  if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl)
}

function triggerFilePicker() {
  fileInputRef.value?.click()
}

function handleFileInputChange(event: Event) {
  const target = event.target as HTMLInputElement
  if (target.files?.length) {
    appendFilesToQueue(target.files)
  }
  target.value = ''
}

function hasFilePayload(event: DragEvent): boolean {
  return Boolean(event.dataTransfer && Array.from(event.dataTransfer.types).includes('Files'))
}

function handleCanvasDragEnter(event: DragEvent) {
  if (!currentSpace.value || !hasFilePayload(event)) return
  event.preventDefault()
  dragDepth += 1
  isDraggingFile.value = true
}

function handleCanvasDragOver(event: DragEvent) {
  if (!currentSpace.value || !hasFilePayload(event)) return
  event.preventDefault()
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = 'copy'
  }
}

function handleCanvasDragLeave(event: DragEvent) {
  if (!hasFilePayload(event)) return
  dragDepth = Math.max(0, dragDepth - 1)
  if (dragDepth === 0) {
    isDraggingFile.value = false
  }
}

function handleCanvasDrop(event: DragEvent) {
  dragDepth = 0
  isDraggingFile.value = false
  if (!currentSpace.value || !event.dataTransfer?.files?.length) return
  event.preventDefault()
  appendFilesToQueue(event.dataTransfer.files)
}

function handleGlobalPaste(event: ClipboardEvent) {
  if (!currentSpace.value || gateOpen.value || createSpaceOpen.value) return
  const items = event.clipboardData?.items
  if (!items?.length) return
  const pastedFiles: File[] = []
  for (const item of Array.from(items)) {
    if (item.kind === 'file') {
      const f = item.getAsFile()
      if (!f) continue
      if (f.name && f.name !== 'image.png') {
        pastedFiles.push(f)
      } else {
        const ext = f.type.split('/')[1] || 'png'
        const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)
        pastedFiles.push(new File([f], `clipboard-${stamp}.${ext}`, { type: f.type || 'image/png' }))
      }
    }
  }
  if (pastedFiles.length > 0) {
    event.preventDefault()
    appendFilesToQueue(pastedFiles)
  }
}

async function submitUploadQueue(password?: string) {
  if (uploadQueue.value.length === 0) return
  uploadBusy.value = true
  const tags = parseTags(uploadTags.value)
  const snapshot = [...uploadQueue.value]
  let uploadedCount = 0
  try {
    const sharedNote = uploadNote.value.trim()
    for (let i = 0; i < snapshot.length; i += 1) {
      const item = snapshot[i]!
      const entryNote = item.note.trim() || sharedNote
      uploadProgressText.value = `正在上传 (${i + 1}/${snapshot.length})：${item.file.name}`
      await spaceStore.createEntry({
        entryType: 'file',
        title: item.title.trim() || item.file.name,
        tags,
        contentText: entryNote || undefined,
        file: item.file,
        password,
      })
      removeQueuedFile(item.id)
      uploadedCount += 1
    }
    uploadTags.value = ''
    uploadNote.value = ''
    canvasMode.value = 'detail'
    emit('action', `已成功上传 ${uploadedCount} 个文件`)
    if (props.mobile) mobilePanel.value = 'canvas'
  } finally {
    uploadBusy.value = false
    uploadProgressText.value = ''
  }
}

async function handleStartUpload() {
  const sp = currentSpace.value
  if (!sp || uploadBusy.value) return
  if (uploadQueue.value.length === 0) {
    triggerFilePicker()
    return
  }
  if (sp.tier === 'standard') {
    try {
      await submitUploadQueue()
    } catch (cause) {
      emit('action', cause instanceof Error ? cause.message : '文件上传失败')
    }
    return
  }
  openPasswordGate({
    title: '输入密码加密上传',
    description: '',
    confirmLabel: `上传 (${uploadQueue.value.length})`,
    onSubmit: async pwd => {
      await submitUploadQueue(pwd)
    },
  })
}

// ---------------------------------------------------------------------------
// 解锁、编辑、删除、复制、下载
// ---------------------------------------------------------------------------

function requestUnlockEntry() {
  const sp = currentSpace.value
  const detail = currentDetail.value
  if (!sp || !detail) return
  openPasswordGate({
    title: '输入密码解锁',
    description: '',
    confirmLabel: '解锁',
    onSubmit: async pwd => {
      await spaceStore.unlockCurrentEntryWithPassword(pwd)
      emit('action', '已解锁')
    },
  })
}

function requestDecryptE2eeCatalog() {
  openPasswordGate({
    title: '输入密码解密目录',
    description: '',
    confirmLabel: '解密',
    onSubmit: async pwd => {
      await spaceStore.decryptE2eeCatalogWithPassword(pwd)
      emit('action', '目录已解密')
    },
  })
}

function startEditStandard() {
  if (!currentDetail.value || currentSpace.value?.tier !== 'standard') return
  editTitle.value = currentDetail.value.title ?? ''
  editText.value = currentDetail.value.contentText ?? ''
  editTags.value = currentDetail.value.tags.join(', ')
  editingStandard.value = true
}

async function saveEditStandard() {
  if (!currentDetail.value) return
  try {
    await spaceStore.updateStandardEntry(
      currentDetail.value,
      editTitle.value.trim() || inferTitleFromText(editText.value),
      editText.value,
      parseTags(editTags.value),
    )
    editingStandard.value = false
    emit('action', '已保存修订')
  } catch (cause) {
    emit('action', cause instanceof Error ? cause.message : '更新失败')
  }
}

async function handleDeleteEntry() {
  if (!currentDetail.value) return
  if (!window.confirm('确认删除当前共享条目？')) return
  try {
    await spaceStore.deleteCurrentEntry()
    canvasMode.value = 'compose'
    emit('action', '条目已删除')
    if (props.mobile) mobilePanel.value = 'entries'
  } catch (cause) {
    emit('action', cause instanceof Error ? cause.message : '删除失败')
  }
}

async function copyText(text: string, key: string, isSecret = false) {
  const ok = await copyWithFeedback(text, key)
  if (ok) {
    emit('action', isSecret ? '已复制敏感内容，请使用后注意清理剪贴板' : '已复制到剪贴板')
  } else {
    emit('action', '复制失败，请手动选中复制')
  }
}

function downloadUnlockedFile() {
  const view = currentUnlocked.value
  if (!view?.fileBlob) return
  const url = spaceStore.registerObjectUrl(view.fileBlob)
  const a = document.createElement('a')
  a.href = url
  a.download = view.fileName ?? `${view.entryId}.bin`
  a.click()
}

function apiExampleCurl(): string {
  const sp = currentSpace.value
  const detail = currentDetail.value
  if (!sp || !detail) return ''
  const origin = getApiBaseUrl() || window.location.origin
  const tokenPlaceholder = sp.tier === 'protected' ? 'sv_live_YOUR_VAULT_TOKEN' : 'ss_live_YOUR_SPACE_TOKEN'
  return `curl -H "Authorization: Bearer ${tokenPlaceholder}" \\\n  "${origin}/api/v1/spaces/${sp.id}/entries/${detail.id}"`
}

// ---------------------------------------------------------------------------
// API Token & 安全操作
// ---------------------------------------------------------------------------

async function handleIssueToken() {
  const sp = currentSpace.value
  if (!sp || !newTokenName.value.trim() || tokenBusy.value) return
  const days = newTokenDays.value ? Number(newTokenDays.value) : null
  const entryIds = newTokenEntryScope.value === 'selected' ? [...newTokenEntryIds.value] : null
  if (newTokenEntryScope.value === 'selected' && (!entryIds || entryIds.length === 0)) {
    emit('action', '请至少勾选一个允许访问的条目')
    return
  }

  const runIssue = async (password?: string) => {
    tokenBusy.value = true
    try {
      await spaceStore.issueToken({
        name: newTokenName.value.trim(),
        scopes: newTokenScopes.value.length ? newTokenScopes.value : ['read'],
        entryIds,
        expiresInDays: days && days > 0 ? days : null,
        password,
      })
      newTokenName.value = ''
      newTokenEntryIds.value = []
      emit('action', '专用 Token 已签发，明文仅显示一次，请立即妥善保存')
    } finally {
      tokenBusy.value = false
    }
  }

  if (sp.tier === 'protected') {
    openPasswordGate({
      title: '输入密码签发 Token',
      description: '',
      confirmLabel: '签发',
      onSubmit: pwd => runIssue(pwd),
    })
  } else {
    try {
      await runIssue()
    } catch (cause) {
      emit('action', cause instanceof Error ? cause.message : '签发 Token 失败')
    }
  }
}

async function handleRevokeToken(tokenId: string) {
  try {
    await spaceStore.revokeToken(tokenId)
    emit('action', 'Token 已吊销')
  } catch (cause) {
    emit('action', cause instanceof Error ? cause.message : '吊销失败')
  }
}

async function handleChangePassword() {
  if (!changeOldPwd.value || changeNewPwd.value.length < 8 || securityBusy.value) return
  securityBusy.value = true
  try {
    await spaceStore.changeSpacePassword(changeOldPwd.value, changeNewPwd.value)
    changeOldPwd.value = ''
    changeNewPwd.value = ''
    emit('action', '空间密码已更新')
  } catch (cause) {
    emit('action', cause instanceof Error ? cause.message : '修改密码失败')
  } finally {
    securityBusy.value = false
  }
}

async function handleRotateEpoch() {
  if (rotateNewPwd.value.length < 8 || securityBusy.value) return
  if (!window.confirm('确认执行 Epoch 密钥轮换？轮换后将生成全新 Space Key 并递增 Epoch，旧 Epoch 写入会被服务端拒绝。')) return
  securityBusy.value = true
  try {
    await spaceStore.rotateE2eeEpoch(rotateNewPwd.value)
    rotateNewPwd.value = ''
    emit('action', '已轮换至新 Epoch 并清空本地敏感内存')
  } catch (cause) {
    emit('action', cause instanceof Error ? cause.message : '轮换失败')
  } finally {
    securityBusy.value = false
  }
}

function handleVisibilityChange() {
  // 切后台或锁屏立即清空内存中所有受控机密与 E2EE 明文
  if (document.visibilityState !== 'visible') {
    spaceStore.clearSensitiveMemory()
  }
}

watch(activeTab, tab => {
  if (tab === 'tokens' || tab === 'audit') {
    void spaceStore.loadTokensAndAudit()
  }
})

watch(
  () => spaceStore.selectedSpaceId,
  () => {
    editingStandard.value = false
    clearUploadQueue()
    uploadNote.value = ''
    if (activeTab.value === 'tokens' || activeTab.value === 'audit') {
      void spaceStore.loadTokensAndAudit()
    }
  },
)

onMounted(() => {
  void spaceStore.loadSpaces()
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('paste', handleGlobalPaste)
})

onUnmounted(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener('paste', handleGlobalPaste)
  clearUploadQueue()
  spaceStore.clearSensitiveMemory()
})
</script>

<template>
  <div
    :class="mobile ? 'mpage space-mobile' : 'page full space-desktop'"
    @dragenter="handleCanvasDragEnter"
    @dragover="handleCanvasDragOver"
    @dragleave="handleCanvasDragLeave"
    @drop="handleCanvasDrop"
  >
    <!-- 隐藏多文件选择器 -->
    <input ref="fileInputRef" type="file" multiple class="sr-only" @change="handleFileInputChange" />

    <!-- 全页文件拖拽高亮引导层 -->
    <div v-if="isDraggingFile && currentSpace" class="drag-overlay" aria-hidden="true">
      <div class="drag-overlay-card mat">
        <span class="drag-overlay-ic"><OpusIcon name="arrowUp" /></span>
        <strong>松开上传</strong>
      </div>
    </div>

    <!-- 移动端顶栏 -->
    <div v-if="mobile" class="navbar">
      <button type="button" class="icon-btn" aria-label="返回" @click="handleMobileBack">
        <OpusIcon name="chevL" />
      </button>
      <div class="t">{{ mobileHeaderTitle }}</div>
      <button v-if="mobilePanel === 'spaces'" type="button" class="icon-btn" aria-label="新建空间" @click="openCreateSpaceDialog()">
        <OpusIcon name="plus" />
      </button>
      <button
        v-else-if="mobilePanel === 'entries' && currentSpace"
        type="button"
        class="icon-btn"
        aria-label="写文本"
        @click="openCompose('text')"
      >
        <OpusIcon name="pencil" />
      </button>
      <span v-else style="width: 40px"></span>
    </div>

    <div class="space-shell" :class="{ 'is-mobile': mobile, 'is-empty-state': !mobile && !spaceStore.loading && spaceStore.spaces.length === 0 }">
      <!-- ================================================================
           左栏：空间导航轨道
           ================================================================ -->
      <aside v-show="!mobile || mobilePanel === 'spaces'" class="space-col-nav" data-surface-role="nav">
        <div class="col-nav-head">
          <div class="col-nav-title">
            <h2>共享空间</h2>
            <span class="nav-count num">{{ spaceStore.spaces.length }}</span>
          </div>
          <button type="button" class="btn btn-sm btn-primary" @click="openCreateSpaceDialog()">
            <OpusIcon name="plus" /> 新建
          </button>
        </div>

        <div v-if="spaceStore.error" class="space-alert" role="alert">{{ spaceStore.error }}</div>

        <div class="space-nav-list" data-surface-role="list">
          <button
            v-for="sp in spaceStore.spaces"
            :key="sp.id"
            type="button"
            class="space-nav-card"
            :class="{ active: sp.id === spaceStore.selectedSpaceId }"
            @click="handleSelectSpace(sp.id)"
          >
            <div class="space-nav-card-top">
              <strong class="space-nav-name">{{ sp.name }}</strong>
              <span class="tier-pill" :class="tierMeta[sp.tier].badgeClass">
                <i class="tier-dot" aria-hidden="true"></i>
                {{ tierMeta[sp.tier].short }}
              </span>
            </div>
            <div v-if="sp.description" class="space-nav-desc muted">{{ sp.description }}</div>
            <div class="space-nav-meta faint num">
              <span>{{ sp.entryCount }} 条</span>
              <span>{{ formatBytes(sp.usedBytes) }}</span>
            </div>
            <div class="quota-track" aria-hidden="true">
              <span class="quota-fill" :style="{ width: `${formatQuotaPercent(sp.usedBytes, sp.quotaBytes)}%` }"></span>
            </div>
          </button>

          <div v-if="!spaceStore.loading && spaceStore.spaces.length === 0" class="nav-empty-hint muted">
            暂无空间
          </div>
        </div>
      </aside>

      <!-- ================================================================
           中栏：条目目录 + 底部常驻「写文本 / 传文件」双主操作
           ================================================================ -->
      <section v-show="(!mobile && spaceStore.spaces.length > 0) || (mobile && mobilePanel === 'entries')" class="space-col-catalog">
        <template v-if="currentSpace">
          <div class="catalog-head">
            <div class="catalog-title-row">
              <h3 class="catalog-title">{{ currentSpace.name }}</h3>
              <span class="tier-pill" :class="tierMeta[currentSpace.tier].badgeClass">
                <i class="tier-dot" aria-hidden="true"></i>
                {{ tierMeta[currentSpace.tier].short }}
              </span>
              <span v-if="currentSpace.tier === 'e2ee'" class="epoch-tag mono">E#{{ currentSpace.activeEpoch }}</span>
            </div>

            <!-- 紧凑功能视图切换器 -->
            <div class="catalog-segment" role="tablist" aria-label="空间视图">
              <button
                type="button"
                role="tab"
                :aria-selected="activeTab === 'entries'"
                :class="{ active: activeTab === 'entries' }"
                @click="switchSubTab('entries')"
              >
                内容
              </button>
              <button
                v-if="currentSpace.tier !== 'e2ee'"
                type="button"
                role="tab"
                :aria-selected="activeTab === 'tokens'"
                :class="{ active: activeTab === 'tokens' }"
                @click="switchSubTab('tokens')"
              >
                Token
              </button>
              <button
                type="button"
                role="tab"
                :aria-selected="activeTab === 'audit'"
                :class="{ active: activeTab === 'audit' }"
                @click="switchSubTab('audit')"
              >
                审计
              </button>
              <button
                type="button"
                role="tab"
                :aria-selected="activeTab === 'security'"
                :class="{ active: activeTab === 'security' }"
                @click="switchSubTab('security')"
              >
                {{ currentSpace.tier === 'standard' ? '管理' : '安全' }}
              </button>
            </div>

            <!-- 搜索与类型胶囊筛选 -->
            <div class="catalog-search-box" data-surface-role="input">
              <OpusIcon name="search" class="search-ic faint" />
              <input
                v-model="searchQuery"
                class="catalog-search-input"
                type="search"
                placeholder="搜索"
              />
            </div>

            <div class="catalog-filter-row">
              <button
                v-for="ft in (['all', 'text', 'file', 'config', 'key'] as const)"
                :key="ft"
                type="button"
                class="filter-pill"
                :class="{ active: filterType === ft }"
                @click="filterType = ft"
              >
                {{ ft === 'all' ? '全部' : entryTypeMeta[ft].label }}
              </button>
            </div>

            <button
              v-if="currentSpace.tier === 'e2ee'"
              type="button"
              class="e2ee-unlock-bar"
              @click="requestDecryptE2eeCatalog"
            >
              <OpusIcon name="unlock" />
              <span>解密目录</span>
            </button>
          </div>

          <!-- 条目列表 -->
          <div class="catalog-list" data-surface-role="list">
            <button
              v-for="item in filteredEntries"
              :key="item.id"
              type="button"
              class="entry-item"
              :class="{ active: activeTab === 'entries' && canvasMode === 'detail' && item.id === spaceStore.selectedEntryId }"
              @click="handleSelectEntry(item.id)"
            >
              <span class="entry-ic" :class="`type-${item.entryType}`">
                <OpusIcon :name="entryTypeMeta[item.entryType].icon" />
              </span>
              <div class="entry-main">
                <div class="entry-line-top">
                  <strong class="entry-title">{{ displayEntryTitle(item) }}</strong>
                  <span v-if="item.hasConflict" class="conflict-tag">冲突</span>
                  <OpusIcon v-else-if="currentSpace.tier !== 'standard'" name="lock" class="entry-lock-ic faint" />
                </div>
                <div class="entry-line-meta faint num">
                  <span>{{ formatBytes(item.sizeBytes) }}</span>
                  <span class="mono">r{{ item.currentRevision }}</span>
                  <span v-if="item.tags.length" class="entry-tags-inline">#{{ item.tags[0] }}</span>
                </div>
              </div>
            </button>

            <div v-if="!spaceStore.loading && filteredEntries.length === 0" class="catalog-empty muted">
              <p>暂无条目</p>
            </div>
          </div>

          <!-- 底部常驻固定双主入口：零弹窗直达右侧大画布 -->
          <div class="catalog-dock">
            <button
              type="button"
              class="dock-btn"
              :class="{ active: activeTab === 'entries' && canvasMode === 'compose' && composeTab === 'text' }"
              @click="openCompose('text')"
            >
              <OpusIcon name="pencil" />
              <span>写文本</span>
            </button>
            <button
              type="button"
              class="dock-btn"
              :class="{ active: activeTab === 'entries' && canvasMode === 'compose' && composeTab === 'file' }"
              @click="openCompose('file')"
            >
              <OpusIcon name="arrowUp" />
              <span>传文件</span>
              <span v-if="uploadQueue.length" class="dock-badge num">{{ uploadQueue.length }}</span>
            </button>
          </div>
        </template>

        <div v-else class="catalog-empty muted" style="margin: auto">
          <p>请先在左侧选择或创建一个共享空间</p>
        </div>
      </section>

      <!-- ================================================================
           右栏：沉浸式大画布（写文本 / 传文件 / 详情预览 / Token / 审计 / 安全）
           ================================================================ -->
      <main v-show="!mobile || mobilePanel === 'canvas'" class="space-col-canvas">
        <template v-if="currentSpace">
          <!-- 1. 内容视图 -> 沉浸式撰写/上传画布 -->
          <div v-if="activeTab === 'entries' && (canvasMode === 'compose' || !currentDetail)" class="canvas-inner canvas-compose">
            <header class="canvas-head">
              <div class="canvas-mode-switch" role="tablist" aria-label="新增方式">
                <button
                  type="button"
                  role="tab"
                  :aria-selected="composeTab === 'text'"
                  :class="{ active: composeTab === 'text' }"
                  @click="composeTab = 'text'"
                >
                  <OpusIcon name="pencil" /> 文本
                </button>
                <button
                  type="button"
                  role="tab"
                  :aria-selected="composeTab === 'file'"
                  :class="{ active: composeTab === 'file' }"
                  @click="composeTab = 'file'"
                >
                  <OpusIcon name="arrowUp" /> 文件
                  <span v-if="uploadQueue.length" class="tab-count num">{{ uploadQueue.length }}</span>
                </button>
              </div>
              <button
                v-if="currentDetail"
                type="button"
                class="btn btn-sm btn-ghost"
                @click="canvasMode = 'detail'"
              >
                返回条目
              </button>
            </header>

            <!-- 1A. 写文本 / 配置 / 密钥 -->
            <form v-if="composeTab === 'text'" class="compose-form" @submit.prevent="handleSaveComposeText">
              <div class="compose-meta-row">
                <div class="type-pills" role="radiogroup" aria-label="文本类型">
                  <button
                    v-for="t in (['text', 'config', 'key'] as const)"
                    :key="t"
                    type="button"
                    class="type-pill-btn"
                    :class="{ active: composeTextType === t }"
                    @click="composeTextType = t"
                  >
                    <OpusIcon :name="entryTypeMeta[t].icon" />
                    <span>{{ entryTypeMeta[t].label }}</span>
                  </button>
                </div>
                <div class="compose-tag-field" data-surface-role="input">
                  <OpusIcon name="hash" class="faint" />
                  <input
                    v-model="composeTags"
                    type="text"
                    placeholder="标签"
                    aria-label="标签"
                  />
                </div>
              </div>

              <input
                v-model="composeTitle"
                type="text"
                class="compose-title-input"
                placeholder="标题"
                data-surface-role="input"
              />

              <textarea
                v-model="composeText"
                class="compose-editor"
                :class="{ mono: composeTextType !== 'text' }"
                data-surface-role="input"
                placeholder="输入内容…"
                @keydown="handleComposeKeydown"
              />

              <footer class="compose-foot">
                <span class="faint num">{{ composeText.length }} 字</span>
                <button
                  type="submit"
                  class="btn btn-primary"
                  :disabled="composeBusy || (!composeTitle.trim() && !composeText.trim())"
                >
                  <OpusIcon :name="currentSpace.tier === 'standard' ? 'check' : 'lock'" />
                  {{ composeBusy ? '保存中…' : currentSpace.tier === 'standard' ? '保存' : '加密保存' }}
                </button>
              </footer>
            </form>

            <!-- 1B. 上传文件 -->
            <div v-else class="compose-upload">
              <div
                class="upload-dropzone"
                :class="{ 'is-dragging': isDraggingFile, 'has-files': uploadQueue.length > 0 }"
                role="button"
                tabindex="0"
                @click="triggerFilePicker"
                @keydown.enter.prevent="triggerFilePicker"
                @keydown.space.prevent="triggerFilePicker"
              >
                <div class="dropzone-ic"><OpusIcon name="cloud" /></div>
                <div class="dropzone-copy">
                  <strong>拖入文件或点击上传</strong>
                  <p class="faint num">{{ maxFileLimitLabel }}</p>
                </div>
              </div>

              <!-- 待上传文件队列 -->
              <div v-if="uploadQueue.length > 0" class="upload-queue" data-surface-role="list">
                <div class="upload-queue-head">
                  <strong class="num">{{ uploadQueue.length }} 个文件</strong>
                  <div class="upload-queue-tools">
                    <div class="compose-tag-field compact" data-surface-role="input">
                      <OpusIcon name="hash" class="faint" />
                      <input v-model="uploadTags" type="text" placeholder="标签" aria-label="上传标签" />
                    </div>
                    <button type="button" class="btn btn-sm btn-ghost" :disabled="uploadBusy" @click="clearUploadQueue">
                      清空
                    </button>
                  </div>
                </div>

                <div class="upload-queue-items">
                  <div v-for="item in uploadQueue" :key="item.id" class="queue-row">
                    <img v-if="item.previewUrl" :src="item.previewUrl" :alt="item.file.name" class="queue-thumb" />
                    <span v-else class="queue-ext mono">{{ fileExtensionBadge(item.file.name) }}</span>
                    <div class="queue-info">
                      <input
                        v-model="item.title"
                        type="text"
                        class="queue-title-input"
                        :disabled="uploadBusy"
                        aria-label="文件标题"
                      />
                      <div class="queue-meta faint num">
                        <span>{{ formatBytes(item.file.size) }}</span>
                      </div>
                      <input
                        v-if="uploadQueue.length > 1"
                        v-model="item.note"
                        type="text"
                        class="queue-note-input"
                        :disabled="uploadBusy"
                        placeholder="备注"
                        aria-label="单文件备注"
                      />
                    </div>
                    <button
                      type="button"
                      class="icon-btn-sm"
                      aria-label="移除文件"
                      :disabled="uploadBusy"
                      @click="removeQueuedFile(item.id)"
                    >
                      <OpusIcon name="x" />
                    </button>
                  </div>
                </div>

                <textarea
                  v-model="uploadNote"
                  class="upload-note-textarea"
                  data-surface-role="input"
                  rows="2"
                  :disabled="uploadBusy"
                  placeholder="备注（可选）"
                  aria-label="文件备注"
                />

                <footer class="compose-foot">
                  <span class="faint">{{ uploadProgressText }}</span>
                  <button type="button" class="btn btn-primary" :disabled="uploadBusy" @click="handleStartUpload">
                    <OpusIcon :name="currentSpace.tier === 'standard' ? 'arrowUp' : 'lock'" />
                    {{
                      uploadBusy
                        ? '上传中…'
                        : currentSpace.tier === 'standard'
                          ? `上传 (${uploadQueue.length})`
                          : `加密上传 (${uploadQueue.length})`
                    }}
                  </button>
                </footer>
              </div>

              <textarea
                v-else
                v-model="uploadNote"
                class="upload-note-textarea"
                data-surface-role="input"
                rows="2"
                placeholder="备注（可选）"
                aria-label="文件备注"
              />
            </div>
          </div>

          <!-- 2. 内容视图 -> 条目详情与解密阅读画布 -->
          <div v-else-if="activeTab === 'entries' && currentDetail" class="canvas-inner canvas-detail">
            <header class="detail-head">
              <div class="detail-head-main">
                <div class="detail-badges">
                  <span class="entry-ic sm" :class="`type-${currentDetail.entryType}`">
                    <OpusIcon :name="entryTypeMeta[currentDetail.entryType].icon" />
                  </span>
                  <span class="detail-type-label">{{ entryTypeMeta[currentDetail.entryType].label }}</span>
                  <span class="faint num mono">r{{ currentDetail.revision }} · {{ formatBytes(currentDetail.sizeBytes) }}</span>
                  <span v-if="currentSpace.tier === 'e2ee'" class="epoch-tag mono">Epoch #{{ currentDetail.epoch }}</span>
                </div>
                <h3 class="detail-title">{{ currentUnlocked?.manifest?.title ?? displayEntryTitle(currentDetail) }}</h3>
                <div v-if="currentDetail.tags.length" class="detail-tags">
                  <span v-for="tag in currentDetail.tags" :key="tag" class="tag-chip">#{{ tag }}</span>
                </div>
              </div>

              <div class="detail-head-actions">
                <button
                  v-if="currentUnlocked"
                  type="button"
                  class="btn btn-sm btn-ghost"
                  @click="spaceStore.clearSensitiveMemory(); emit('action', '已立即锁定并清除内存明文')"
                >
                  <OpusIcon name="lock" /> 立即锁定
                </button>
                <button type="button" class="btn btn-sm btn-ghost danger-text" @click="handleDeleteEntry">
                  <OpusIcon name="trash" /> 删除
                </button>
              </div>
            </header>

            <!-- 2A. Standard 普通共享 -->
            <template v-if="currentSpace.tier === 'standard'">
              <div v-if="!editingStandard" class="detail-content">
                <template v-if="currentDetail.entryType === 'file'">
                  <div class="file-hero-card">
                    <span class="file-hero-ext mono">{{ fileExtensionBadge(currentDetail.fileName ?? currentDetail.title) }}</span>
                    <div class="file-hero-meta">
                      <strong>{{ currentDetail.fileName ?? currentDetail.title }}</strong>
                      <div class="faint num">{{ formatBytes(currentDetail.sizeBytes) }}</div>
                    </div>
                    <div class="file-hero-actions">
                      <button type="button" class="btn btn-sm btn-ghost" @click="startEditStandard">
                        <OpusIcon name="pencil" /> 备注
                      </button>
                      <button type="button" class="btn btn-primary btn-sm" @click="spaceStore.downloadStandardEntry(currentDetail)">
                        <OpusIcon name="download" /> 下载
                      </button>
                    </div>
                  </div>

                  <div v-if="currentDetail.contentText" class="prose-box" data-surface-role="prose">
                    <div class="prose-toolbar">
                      <span class="faint">备注</span>
                      <div class="prose-actions">
                        <button
                          type="button"
                          class="btn btn-sm btn-ghost"
                          :class="{ 'is-copied': isCopied('std-note') }"
                          @click="copyText(currentDetail.contentText, 'std-note')"
                        >
                          <OpusIcon :name="isCopied('std-note') ? 'check' : 'copy'" /> {{ isCopied('std-note') ? '已复制' : '复制' }}
                        </button>
                      </div>
                    </div>
                    <pre class="content-pre is-plain">{{ currentDetail.contentText }}</pre>
                  </div>
                </template>

                <div v-else class="prose-box" data-surface-role="prose">
                  <div class="prose-toolbar">
                    <span></span>
                    <div class="prose-actions">
                      <button
                        type="button"
                        class="btn btn-sm btn-ghost"
                        :class="{ 'is-copied': isCopied('std-text') }"
                        @click="copyText(currentDetail.contentText ?? '', 'std-text')"
                      >
                        <OpusIcon :name="isCopied('std-text') ? 'check' : 'copy'" /> {{ isCopied('std-text') ? '已复制' : '复制' }}
                      </button>
                      <button type="button" class="btn btn-sm btn-ghost" @click="startEditStandard">
                        <OpusIcon name="pencil" /> 编辑
                      </button>
                    </div>
                  </div>
                  <pre class="content-pre" :class="{ 'is-plain': currentDetail.entryType === 'text' }">{{ currentDetail.contentText ?? '' }}</pre>
                </div>

                <!-- 折叠式 API 读取示例 -->
                <details class="api-disclosure">
                  <summary>
                    <OpusIcon name="api" />
                    <span>API</span>
                  </summary>
                  <div class="api-disclosure-body">
                    <div class="api-box-head">
                      <span class="faint mono">ss_live_</span>
                      <button
                        type="button"
                        class="btn btn-sm btn-ghost"
                        :class="{ 'is-copied': isCopied('std-curl') }"
                        @click="copyText(apiExampleCurl(), 'std-curl')"
                      >
                        <OpusIcon :name="isCopied('std-curl') ? 'check' : 'copy'" /> {{ isCopied('std-curl') ? '已复制' : '复制' }}
                      </button>
                    </div>
                    <pre class="api-code">{{ apiExampleCurl() }}</pre>
                  </div>
                </details>
              </div>

              <div v-else class="detail-edit-form">
                <div class="edit-row-2">
                  <input v-model="editTitle" class="input" data-surface-role="input" placeholder="标题" aria-label="标题" />
                  <input v-model="editTags" class="input" data-surface-role="input" placeholder="标签" aria-label="标签" />
                </div>
                <textarea
                  v-model="editText"
                  class="compose-editor"
                  :class="{ mono: currentDetail.entryType !== 'file' && currentDetail.entryType !== 'text' }"
                  data-surface-role="input"
                  :rows="currentDetail.entryType === 'file' ? 6 : 12"
                  :placeholder="currentDetail.entryType === 'file' ? '备注' : '内容'"
                />
                <div class="compose-foot">
                  <span></span>
                  <div class="compose-foot-actions">
                    <button type="button" class="btn btn-sm btn-ghost" @click="editingStandard = false">取消</button>
                    <button type="button" class="btn btn-sm btn-primary" @click="saveEditStandard">
                      <OpusIcon name="check" /> 保存
                    </button>
                  </div>
                </div>
              </div>
            </template>

            <!-- 2B. Protected / E2EE 锁定态 -->
            <template v-else-if="!currentUnlocked">
              <div class="locked-vault-card mat">
                <div class="locked-vault-ic"><OpusIcon name="lock" /></div>
                <h4>已锁定</h4>
                <button type="button" class="btn btn-primary" @click="requestUnlockEntry">
                  <OpusIcon name="unlock" /> 解锁
                </button>
              </div>

              <details v-if="currentSpace.tier === 'protected'" class="api-disclosure">
                <summary>
                  <OpusIcon name="api" />
                  <span>API</span>
                </summary>
                <div class="api-disclosure-body">
                  <div class="api-box-head">
                    <span class="faint mono">sv_live_</span>
                    <button
                      type="button"
                      class="btn btn-sm btn-ghost"
                      :class="{ 'is-copied': isCopied('pro-curl') }"
                      @click="copyText(apiExampleCurl(), 'pro-curl')"
                    >
                      <OpusIcon :name="isCopied('pro-curl') ? 'check' : 'copy'" /> {{ isCopied('pro-curl') ? '已复制' : '复制' }}
                    </button>
                  </div>
                  <pre class="api-code">{{ apiExampleCurl() }}</pre>
                </div>
              </details>
            </template>

            <!-- 2C. Protected / E2EE 当次解密态（纯内存） -->
            <template v-else>
              <div v-if="currentUnlocked.fileBlob" class="unlocked-file-wrap">
                <div v-if="unlockedImagePreviewUrl" class="unlocked-image-stage">
                  <img :src="unlockedImagePreviewUrl" :alt="currentUnlocked.fileName ?? '图片预览'" />
                </div>
                <div class="file-hero-card">
                  <span class="file-hero-ext mono">{{ fileExtensionBadge(currentUnlocked.fileName) }}</span>
                  <div class="file-hero-meta">
                    <strong>{{ currentUnlocked.fileName }}</strong>
                    <div class="faint num">{{ formatBytes(currentUnlocked.fileBlob.size) }}</div>
                  </div>
                  <button type="button" class="btn btn-primary btn-sm" @click="downloadUnlockedFile">
                    <OpusIcon name="download" /> 下载
                  </button>
                </div>
                <div v-if="currentUnlocked.contentText" class="prose-box" data-surface-role="prose">
                  <div class="prose-toolbar">
                    <span class="faint">备注</span>
                    <div class="prose-actions">
                      <button
                        type="button"
                        class="btn btn-sm btn-ghost"
                        :class="{ 'is-copied': isCopied('unlock-note') }"
                        @click="copyText(currentUnlocked.contentText, 'unlock-note', true)"
                      >
                        <OpusIcon :name="isCopied('unlock-note') ? 'check' : 'copy'" /> {{ isCopied('unlock-note') ? '已复制' : '复制' }}
                      </button>
                    </div>
                  </div>
                  <pre class="content-pre is-plain">{{ currentUnlocked.contentText }}</pre>
                </div>
              </div>

              <div v-else class="prose-box" data-surface-role="prose">
                <div class="prose-toolbar">
                  <span></span>
                  <div class="prose-actions">
                    <button
                      v-if="currentUnlocked.contentText !== null"
                      type="button"
                      class="btn btn-sm btn-ghost"
                      :class="{ 'is-copied': isCopied('unlock-text') }"
                      @click="copyText(currentUnlocked.contentText, 'unlock-text', true)"
                    >
                      <OpusIcon :name="isCopied('unlock-text') ? 'check' : 'copy'" /> {{ isCopied('unlock-text') ? '已复制' : '复制' }}
                    </button>
                    <button type="button" class="btn btn-sm btn-ghost" @click="spaceStore.clearSensitiveMemory()">
                      <OpusIcon name="lock" /> 锁定
                    </button>
                  </div>
                </div>
                <pre class="content-pre secret-pre">{{ currentUnlocked.contentText ?? '' }}</pre>
              </div>
            </template>
          </div>

          <!-- 3. API Token 管理画布 -->
          <div v-else-if="activeTab === 'tokens'" class="canvas-inner canvas-subpanel">
            <header class="canvas-head">
              <h3 class="canvas-title">API Token</h3>
            </header>

            <div class="subpanel-card">
              <h4>签发</h4>
              <div class="token-form">
                <input v-model="newTokenName" class="input" data-surface-role="input" placeholder="名称" />
                <div class="token-row-inline">
                  <label class="brand-check"><input v-model="newTokenScopes" type="checkbox" value="read" /> <span>read</span></label>
                  <label class="brand-check"><input v-model="newTokenScopes" type="checkbox" value="write" /> <span>write</span></label>
                  <label class="token-days">
                    <span>天数</span>
                    <input v-model="newTokenDays" class="input small-num" data-surface-role="input" type="number" min="1" max="3650" />
                  </label>
                </div>

                <div v-if="currentSpace.tier === 'protected'" class="token-scope-box">
                  <div class="token-row-inline">
                    <label class="brand-check"><input v-model="newTokenEntryScope" type="radio" value="all" /> <span>整个空间</span></label>
                    <label class="brand-check"><input v-model="newTokenEntryScope" type="radio" value="selected" /> <span>指定条目</span></label>
                  </div>
                  <div v-if="newTokenEntryScope === 'selected'" class="token-entry-picker" data-surface-role="list">
                    <label v-for="entry in spaceStore.entries" :key="entry.id" class="token-entry-opt brand-check">
                      <input v-model="newTokenEntryIds" type="checkbox" :value="entry.id" />
                      <span>{{ entry.title ?? entry.id.slice(0, 8) }}</span>
                    </label>
                  </div>
                </div>

                <div>
                  <button type="button" class="btn btn-primary btn-sm" :disabled="tokenBusy || !newTokenName.trim()" @click="handleIssueToken">
                    {{ tokenBusy ? '签发中…' : '签发' }}
                  </button>
                </div>
              </div>

              <div v-if="spaceStore.lastCreatedToken" class="token-created-box">
                <div class="token-created-head">
                  <strong>仅显示一次</strong>
                  <button
                    type="button"
                    class="btn btn-sm btn-ghost"
                    :class="{ 'is-copied': isCopied('new-token') }"
                    @click="copyText(spaceStore.lastCreatedToken.token, 'new-token', true)"
                  >
                    <OpusIcon :name="isCopied('new-token') ? 'check' : 'copy'" /> {{ isCopied('new-token') ? '已复制' : '复制' }}
                  </button>
                </div>
                <code class="mono">{{ spaceStore.lastCreatedToken.token }}</code>
              </div>
            </div>

            <div class="subpanel-card">
              <h4>列表（{{ spaceStore.tokens.length }}）</h4>
              <div v-if="spaceStore.tokens.length === 0" class="muted">暂无</div>
              <div v-for="tk in spaceStore.tokens" :key="tk.id" class="token-item">
                <div>
                  <strong>{{ tk.name }}</strong>
                  <span class="faint mono"> · ****{{ tk.tokenLast4 }} · {{ tk.scopes.join('/') }}</span>
                  <div class="faint" style="font-size: 12px">
                    {{ tk.entryIds ? `${tk.entryIds.length} 条` : '全部' }}
                    <span v-if="tk.revokedAt"> · 已吊销</span>
                    <span v-else-if="tk.lastUsedAt"> · {{ tk.lastUsedAt.slice(0, 19).replace('T', ' ') }}</span>
                  </div>
                </div>
                <button v-if="!tk.revokedAt" type="button" class="btn btn-sm btn-ghost danger-text" @click="handleRevokeToken(tk.id)">
                  吊销
                </button>
              </div>
            </div>
          </div>

          <!-- 4. 审计日志画布 -->
          <div v-else-if="activeTab === 'audit'" class="canvas-inner canvas-subpanel">
            <header class="canvas-head">
              <h3 class="canvas-title">审计日志</h3>
            </header>

            <div class="subpanel-card" data-surface-role="list">
              <div v-if="spaceStore.auditLogs.length === 0" class="muted">暂无记录</div>
              <div v-for="log in spaceStore.auditLogs" :key="log.id" class="audit-row">
                <span class="audit-outcome" :class="log.outcome">{{ log.outcome }}</span>
                <strong>{{ log.action }}</strong>
                <span class="faint">{{ log.actorKind }}</span>
                <span class="muted audit-detail">{{ log.detail }}</span>
                <span class="faint mono audit-time">{{ log.createdAt.slice(0, 19).replace('T', ' ') }}</span>
              </div>
            </div>
          </div>

          <!-- 5. 空间管理与安全设置画布 -->
          <div v-else-if="activeTab === 'security'" class="canvas-inner canvas-subpanel">
            <header class="canvas-head">
              <h3 class="canvas-title">{{ currentSpace.tier === 'standard' ? '管理' : '安全' }}</h3>
            </header>

            <div v-if="currentSpace.tier !== 'standard'" class="subpanel-card">
              <h4>修改密码</h4>
              <div class="token-form">
                <input v-model="changeOldPwd" class="input" data-surface-role="input" type="password" placeholder="当前密码" autocomplete="off" />
                <input v-model="changeNewPwd" class="input" data-surface-role="input" type="password" placeholder="新密码（至少 8 位）" autocomplete="off" />
                <div>
                  <button
                    type="button"
                    class="btn btn-primary btn-sm"
                    :disabled="securityBusy || !changeOldPwd || changeNewPwd.length < 8"
                    @click="handleChangePassword"
                  >
                    更新密码
                  </button>
                </div>
              </div>
            </div>

            <div v-if="currentSpace.tier === 'e2ee'" class="subpanel-card">
              <h4>密钥轮换 · Epoch #{{ currentSpace.activeEpoch }}</h4>
              <div class="token-form">
                <input v-model="rotateNewPwd" class="input" data-surface-role="input" type="password" placeholder="新密码（至少 8 位）" autocomplete="off" />
                <div>
                  <button
                    type="button"
                    class="btn btn-sm btn-ghost danger-text"
                    :disabled="securityBusy || rotateNewPwd.length < 8"
                    @click="handleRotateEpoch"
                  >
                    轮换 Epoch
                  </button>
                </div>
              </div>
            </div>

            <div class="subpanel-card danger-zone">
              <h4>归档空间</h4>
              <div>
                <button type="button" class="btn btn-sm btn-ghost danger-text" @click="handleArchiveCurrentSpace">
                  <OpusIcon name="trash" /> 归档
                </button>
              </div>
            </div>
          </div>
        </template>

        <!-- 无空间时的极简引导大画布 -->
        <div v-else class="canvas-welcome">
          <div class="welcome-ic"><OpusIcon name="shield" /></div>
          <h3>创建共享空间</h3>

          <div class="welcome-tiers">
            <button
              v-for="tier in (['standard', 'protected', 'e2ee'] as SpaceTier[])"
              :key="tier"
              type="button"
              class="welcome-tier-card"
              :disabled="tier === 'protected' && Boolean(spaceStore.capabilities && !spaceStore.capabilities.protectedAvailable)"
              @click="openCreateSpaceDialog(tier)"
            >
              <div class="welcome-tier-top">
                <span class="tier-pill" :class="tierMeta[tier].badgeClass">
                  <i class="tier-dot" aria-hidden="true"></i>
                  {{ tierMeta[tier].short }}
                </span>
                <OpusIcon name="chevR" class="faint" />
              </div>
              <strong>{{ tierMeta[tier].label }}</strong>
              <p class="faint">{{ tierMeta[tier].hint }}</p>
            </button>
          </div>
        </div>
      </main>
    </div>

    <!-- 新建空间原生 <dialog closedby="any"> -->
    <dialog
      ref="createSpaceDialogRef"
      closedby="any"
      class="dlg space-dlg"
      aria-labelledby="create-space-title"
      @close="handleCreateSpaceDialogClose"
      @click="handleCreateSpaceDialogClick"
    >
      <form class="space-dlg-form" @submit.prevent="handleCreateSpace">
        <div class="dlg-head">
          <div class="dlg-head__copy">
            <h3 id="create-space-title">新建空间</h3>
          </div>
          <button type="button" class="icon-btn-sm" aria-label="关闭弹窗" @click="closeCreateSpaceDialog">
            <OpusIcon name="x" />
          </button>
        </div>

        <input v-model="newSpaceName" class="input" data-surface-role="input" required placeholder="空间名称" aria-label="空间名称" />

        <input v-model="newSpaceDesc" class="input" data-surface-role="input" placeholder="简介（可选）" aria-label="简介" />

        <div class="form-field">
          <div class="tier-picker">
            <button
              v-for="tier in (['standard', 'protected', 'e2ee'] as SpaceTier[])"
              :key="tier"
              type="button"
              class="tier-option"
              :class="{ active: newSpaceTier === tier }"
              :disabled="tier === 'protected' && Boolean(spaceStore.capabilities && !spaceStore.capabilities.protectedAvailable)"
              @click="newSpaceTier = tier"
            >
              <div class="tier-option-top">
                <strong>{{ tierMeta[tier].label }}</strong>
                <span class="tier-pill" :class="tierMeta[tier].badgeClass">{{ tierMeta[tier].short }}</span>
              </div>
              <small>{{ tierMeta[tier].hint }}</small>
            </button>
          </div>
          <p v-if="spaceStore.capabilities && !spaceStore.capabilities.protectedAvailable" class="faint" style="margin: 2px 0 0; font-size: 11.5px">
            受控机密需配置 STUDIOLO_VAULT_MASTER_KEY
          </p>
        </div>

        <label v-if="newSpaceTier !== 'standard'" class="form-field">
          <input v-model="newSpacePassword" class="input" data-surface-role="input" type="password" autocomplete="new-password" minlength="8" required placeholder="空间密码（至少 8 位）" aria-label="空间密码" />
          <small v-if="newSpaceTier === 'e2ee'" class="danger-text">
            密码不可找回，请妥善保存
          </small>
        </label>

        <div class="modal-actions">
          <button type="button" class="btn btn-ghost" @click="closeCreateSpaceDialog">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="createSpaceBusy || !newSpaceName.trim()">
            {{ createSpaceBusy ? '创建中…' : '创建' }}
          </button>
        </div>
      </form>
    </dialog>

    <!-- 统一按次密码门禁弹窗 -->
    <SpacePasswordGate
      :open="gateOpen"
      :title="gateTitle"
      :description="gateDesc"
      :confirm-label="gateConfirmLabel"
      :busy="gateBusy"
      :error="gateError"
      @close="closeGate"
      @submit="handleGateSubmit"
    />
  </div>
</template>

<style scoped>
.space-desktop {
  position: relative;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.space-mobile {
  position: relative;
}

/* 三栏现代保险库画布骨架 */
.space-shell {
  display: grid;
  grid-template-columns: 248px 304px minmax(0, 1fr);
  height: 100%;
  min-height: 0;
  background: var(--bg);
}

.space-shell.is-empty-state {
  grid-template-columns: 248px minmax(0, 1fr);
}

.space-shell.is-mobile {
  display: block;
  height: auto;
}

.nav-empty-hint {
  padding: 12px 6px;
  font-size: 12px;
  line-height: 1.55;
}

/* ---------- 左栏：空间导航 ---------- */
.space-col-nav {
  min-width: 0;
  min-height: 0;
  border-right: 1px solid var(--line);
  background: var(--surface-2);
  display: flex;
  flex-direction: column;
  padding: 14px 12px;
  gap: 12px;
  overflow: hidden;
}

.col-nav-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 4px;
}

.col-nav-title {
  display: flex;
  align-items: center;
  gap: 7px;
}

.col-nav-title h2 {
  margin: 0;
  font-size: 14.5px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.nav-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 18px;
  padding: 0 6px;
  border-radius: var(--r-pill, 999px);
  background: var(--surface-3);
  color: var(--text-2);
  font-size: 11px;
  font-weight: 600;
}

.space-nav-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: transparent;
}

.space-nav-card {
  width: 100%;
  text-align: left;
  padding: 10px 11px;
  border-radius: var(--r-md, 12px);
  border: 1px solid transparent;
  background: transparent;
  color: var(--text);
  display: grid;
  gap: 5px;
  transition: background var(--dur-1, 120ms), border-color var(--dur-1, 120ms), box-shadow var(--dur-1, 120ms);
}

.space-nav-card:hover {
  background: var(--solid);
  border-color: var(--line);
}

.space-nav-card.active {
  background: var(--solid);
  border-color: var(--accent-line, var(--accent));
  box-shadow: var(--shadow-1);
}

.space-nav-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.space-nav-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13.5px;
  font-weight: 600;
}

.space-nav-desc {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.space-nav-meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 11.5px;
}

.quota-track {
  height: 3px;
  border-radius: 999px;
  background: var(--surface-3);
  overflow: hidden;
}

.quota-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--accent);
}

.space-nav-foot {
  margin-top: auto;
  padding: 10px 11px;
  border-radius: var(--r-md, 12px);
  border: 1px solid var(--line);
  background: var(--solid);
  display: grid;
  gap: 4px;
}

.nav-foot-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}

.space-nav-foot p {
  margin: 0;
  font-size: 11.5px;
  line-height: 1.45;
}

/* 等级胶囊 */
.tier-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
}

.tier-dot {
  width: 6px;
  height: 6px;
  border-radius: 999px;
  background: currentColor;
}

.tier-standard {
  background: var(--ok-soft, rgba(23, 130, 79, 0.1));
  color: var(--ok, #17824f);
}

.tier-protected {
  background: var(--warn-soft, rgba(196, 128, 18, 0.12));
  color: var(--warn, #a8690c);
}

.tier-e2ee {
  background: var(--accent-soft, rgba(61, 90, 254, 0.1));
  color: var(--accent, #3d5afe);
}

/* ---------- 中栏：条目目录 + 底部双入口 ---------- */
.space-col-catalog {
  min-width: 0;
  min-height: 0;
  border-right: 1px solid var(--line);
  background: var(--bg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.catalog-head {
  padding: 14px 14px 10px;
  border-bottom: 1px solid var(--line);
  display: grid;
  gap: 10px;
  flex-shrink: 0;
}

.catalog-title-row {
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 0;
}

.catalog-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}

.epoch-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 6px;
  border: 1px solid var(--line);
  color: var(--text-3);
}

.catalog-segment {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: 1fr;
  gap: 2px;
  padding: 3px;
  border-radius: 10px;
  background: var(--surface-3);
}

.catalog-segment button {
  padding: 5px 6px;
  border-radius: 7px;
  font-size: 12px;
  color: var(--text-2);
  font-weight: 500;
  transition: background var(--dur-1, 120ms), color var(--dur-1, 120ms);
}

.catalog-segment button.active {
  background: var(--solid);
  color: var(--text);
  font-weight: 600;
  box-shadow: var(--shadow-1);
}

.catalog-search-box {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 10px;
  height: 34px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--solid);
}

.catalog-search-box:focus-within {
  border-color: var(--accent);
}

.search-ic {
  font-size: 14px;
  flex-shrink: 0;
}

.catalog-search-input {
  width: 100%;
  border: 0;
  background: transparent;
  font-size: 12.5px;
  outline: none;
}

.catalog-filter-row {
  display: flex;
  gap: 5px;
  overflow-x: auto;
  scrollbar-width: none;
}

.catalog-filter-row::-webkit-scrollbar {
  display: none;
}

.filter-pill {
  padding: 3px 9px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: transparent;
  color: var(--text-2);
  font-size: 11.5px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: background var(--dur-1, 120ms), border-color var(--dur-1, 120ms), color var(--dur-1, 120ms);
}

.filter-pill:hover {
  border-color: var(--line-strong);
  color: var(--text);
}

.filter-pill.active {
  background: var(--text);
  border-color: var(--text);
  color: var(--inv);
  font-weight: 600;
}

.e2ee-unlock-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 7px 10px;
  border-radius: 10px;
  border: 1px dashed var(--accent-line, var(--accent));
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  font-weight: 500;
}

.catalog-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: transparent;
}

.entry-item {
  width: 100%;
  text-align: left;
  padding: 9px 10px;
  border-radius: 11px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text);
  display: flex;
  align-items: flex-start;
  gap: 10px;
  transition: background var(--dur-1, 120ms), border-color var(--dur-1, 120ms);
}

.entry-item:hover {
  background: var(--solid);
  border-color: var(--line);
}

.entry-item.active {
  background: var(--solid);
  border-color: var(--accent-line, var(--accent));
  box-shadow: var(--shadow-1);
}

.entry-ic {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: grid;
  place-items: center;
  font-size: 14px;
  background: var(--surface-3);
  color: var(--text-2);
  flex-shrink: 0;
}

.entry-ic.sm {
  width: 24px;
  height: 24px;
  border-radius: 7px;
  font-size: 12.5px;
}

.entry-ic.type-file {
  background: var(--accent-soft);
  color: var(--accent);
}

.entry-ic.type-key {
  background: var(--warn-soft);
  color: var(--warn);
}

.entry-ic.type-config {
  background: var(--ok-soft);
  color: var(--ok);
}

.entry-main {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 3px;
}

.entry-line-top {
  display: flex;
  align-items: center;
  gap: 6px;
}

.entry-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 600;
}

.entry-lock-ic {
  font-size: 12px;
  flex-shrink: 0;
}

.entry-line-meta {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11.5px;
  overflow: hidden;
}

.entry-tags-inline {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-2);
}

.conflict-tag {
  font-size: 10.5px;
  padding: 1px 6px;
  border-radius: 6px;
  background: var(--danger-soft, rgba(220, 38, 38, 0.12));
  color: var(--danger);
  font-weight: 600;
}

.catalog-empty {
  padding: 36px 16px;
  text-align: center;
  font-size: 12.5px;
  display: grid;
  gap: 4px;
}

.catalog-empty p {
  margin: 0;
}

/* 中栏底部固定「写文本 / 传文件」双主操作栏 */
.catalog-dock {
  flex-shrink: 0;
  padding: 10px 12px;
  border-top: 1px solid var(--line);
  background: var(--solid);
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.dock-btn {
  position: relative;
  height: 36px;
  padding: 0 12px;
  border-radius: 10px;
  border: 1px solid var(--line-strong);
  background: var(--surface-2);
  color: var(--text);
  font-size: 12.5px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: background var(--dur-1, 120ms), border-color var(--dur-1, 120ms), color var(--dur-1, 120ms);
}

.dock-btn:hover {
  border-color: var(--accent);
}

.dock-btn.active {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--accent-ink, #fff);
}

.dock-badge,
.tab-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11px;
  font-weight: 700;
}

.dock-btn.active .dock-badge {
  background: rgba(255, 255, 255, 0.22);
  color: var(--accent-ink, #fff);
}

/* ---------- 右栏：沉浸式现代保险库大画布 ---------- */
.space-col-canvas {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  background: var(--solid);
  padding: 24px 28px;
  display: flex;
  flex-direction: column;
}

.canvas-inner {
  width: min(820px, 100%);
  margin: 0 auto;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.canvas-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line);
}

.canvas-title {
  margin: 0;
  font-size: 17px;
  font-weight: 650;
  letter-spacing: -0.015em;
}

.canvas-subtitle {
  margin: 4px 0 0;
  font-size: 12.5px;
}

.canvas-mode-switch {
  display: inline-flex;
  padding: 3px;
  border-radius: 11px;
  background: var(--surface-3);
  border: 1px solid var(--line);
  gap: 2px;
}

.canvas-mode-switch button {
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--text-2);
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.canvas-mode-switch button.active {
  background: var(--solid);
  color: var(--text);
  font-weight: 600;
  box-shadow: var(--shadow-1);
}

/* 写文本表单 */
.compose-form {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.compose-meta-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.type-pills {
  display: flex;
  gap: 6px;
}

.type-pill-btn {
  padding: 5px 11px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--text-2);
  font-size: 12px;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.type-pill-btn.active {
  background: var(--text);
  border-color: var(--text);
  color: var(--inv);
  font-weight: 600;
}

.compose-tag-field {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  height: 32px;
  border-radius: 9px;
  border: 1px solid var(--line);
  background: var(--solid);
  min-width: 190px;
}

.compose-tag-field.compact {
  min-width: 150px;
  height: 30px;
}

.compose-tag-field input {
  width: 100%;
  border: 0;
  background: transparent;
  font-size: 12px;
  outline: none;
}

.compose-title-input {
  width: 100%;
  border: 0;
  border-bottom: 1px solid var(--line);
  padding: 8px 2px 10px;
  font-size: 19px;
  font-weight: 650;
  letter-spacing: -0.015em;
  background: transparent;
  outline: none;
}

.compose-title-input:focus {
  border-bottom-color: var(--accent);
}

.compose-editor {
  width: 100%;
  flex: 1;
  min-height: 280px;
  padding: 14px 16px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  font-size: 13.5px;
  line-height: 1.65;
  resize: vertical;
  outline: none;
}

.compose-editor:focus {
  border-color: var(--accent);
  background: var(--solid);
}

.compose-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 6px;
}

.compose-foot-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.compose-foot-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 文件上传画布 */
.compose-upload {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.upload-dropzone {
  flex: 1;
  min-height: 260px;
  padding: 36px 24px;
  border-radius: 18px;
  border: 2px dashed var(--line-strong);
  background: var(--surface-2);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 14px;
  cursor: pointer;
  transition: border-color var(--dur-2, 200ms), background var(--dur-2, 200ms), box-shadow var(--dur-2, 200ms);
}

.upload-dropzone.has-files {
  flex: 0 0 auto;
  min-height: 164px;
  padding: 22px 20px;
}

.upload-dropzone:hover,
.upload-dropzone.is-dragging {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.dropzone-ic {
  width: 52px;
  height: 52px;
  border-radius: 16px;
  background: var(--solid);
  border: 1px solid var(--line);
  display: grid;
  place-items: center;
  font-size: 22px;
  color: var(--accent);
  box-shadow: var(--shadow-1);
}

.dropzone-copy {
  display: grid;
  gap: 5px;
  max-width: 440px;
}

.dropzone-copy strong {
  font-size: 15px;
}

.dropzone-copy p {
  margin: 0;
  font-size: 12.5px;
}

.e2ee-note {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  color: var(--accent);
  font-weight: 500;
}

.kbd {
  display: inline-block;
  padding: 1px 5px;
  border-radius: 5px;
  border: 1px solid var(--line-strong);
  background: var(--solid);
  font-family: var(--font-mono);
  font-size: 11px;
}

.upload-queue {
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--solid);
  padding: 14px;
  display: grid;
  gap: 12px;
}

.upload-queue-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
}

.upload-queue-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}

.upload-queue-items {
  display: grid;
  gap: 8px;
  max-height: 280px;
  overflow-y: auto;
}

.queue-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 10px;
  border-radius: 11px;
  border: 1px solid var(--line);
  background: var(--surface-2);
}

.queue-thumb {
  width: 42px;
  height: 42px;
  border-radius: 8px;
  object-fit: cover;
  border: 1px solid var(--line);
  flex-shrink: 0;
}

.queue-ext,
.file-hero-ext {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--solid);
  color: var(--accent);
  display: grid;
  place-items: center;
  font-size: 11px;
  font-weight: 700;
  flex-shrink: 0;
}

.queue-info {
  flex: 1;
  min-width: 0;
  display: grid;
  gap: 2px;
}

.queue-title-input {
  width: 100%;
  border: 0;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  padding: 2px 4px;
  border-radius: 6px;
}

.queue-title-input:focus {
  background: var(--solid);
  outline: 1px solid var(--accent);
}

.queue-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  font-size: 11.5px;
  padding-left: 4px;
}

.queue-note-input {
  width: 100%;
  margin-top: 4px;
  padding: 5px 8px;
  border-radius: 7px;
  border: 1px solid var(--line);
  background: var(--solid);
  font-size: 12px;
  outline: none;
}

.queue-note-input:focus {
  border-color: var(--accent);
}

.upload-note-field {
  margin-top: 2px;
}

.upload-note-textarea {
  width: 100%;
  padding: 10px 12px;
  border-radius: 11px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  font-size: 13px;
  line-height: 1.55;
  resize: vertical;
  min-height: 78px;
  outline: none;
}

.upload-note-textarea:focus {
  border-color: var(--accent);
  background: var(--solid);
}

/* ---------- 条目详情与解密阅读画布 ---------- */
.detail-head {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--line);
}

.detail-head-main {
  min-width: 0;
  display: grid;
  gap: 6px;
}

.detail-badges {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
}

.detail-type-label {
  font-weight: 600;
  color: var(--text-2);
}

.detail-title {
  margin: 0;
  font-size: 19px;
  font-weight: 650;
  letter-spacing: -0.015em;
  word-break: break-word;
}

.detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag-chip {
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--surface-3);
  color: var(--text-2);
  font-size: 11.5px;
}

.detail-head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.detail-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
  flex: 1;
}

.file-hero-card {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 14px;
  padding: 16px 18px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--surface-2);
}

.file-hero-meta {
  flex: 1;
  min-width: 180px;
  display: grid;
  gap: 3px;
}

.file-hero-meta strong {
  font-size: 14.5px;
  word-break: break-all;
}

.file-hero-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.unlocked-file-wrap {
  display: grid;
  gap: 14px;
}

.unlocked-image-stage {
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  padding: 12px;
  display: grid;
  place-items: center;
}

.unlocked-image-stage img {
  max-width: 100%;
  max-height: 360px;
  border-radius: 10px;
  object-fit: contain;
}

.prose-box {
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--solid);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.prose-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--line);
  background: var(--surface-2);
  font-size: 12px;
}

.prose-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.content-pre {
  margin: 0;
  padding: 16px;
  font-family: var(--font-mono);
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 460px;
  overflow: auto;
}

.content-pre.is-plain {
  font-family: var(--font-sans);
  font-size: 14px;
}

.locked-vault-card {
  margin: 18px 0;
  padding: 42px 24px;
  border-radius: 18px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  text-align: center;
  display: grid;
  justify-items: center;
  gap: 12px;
}

.locked-vault-ic {
  width: 52px;
  height: 52px;
  border-radius: 16px;
  background: var(--solid);
  border: 1px solid var(--line);
  display: grid;
  place-items: center;
  font-size: 20px;
  color: var(--accent);
  box-shadow: var(--shadow-1);
}

.locked-vault-card h4,
.locked-vault-card p {
  margin: 0;
  max-width: 420px;
}

.unlocked-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 13px;
  border-radius: 11px;
  background: var(--ok-soft, rgba(23, 130, 79, 0.1));
  color: var(--ok, #17824f);
  font-size: 12.5px;
  font-weight: 500;
}

/* 原生 <details> 折叠式 API 示例 */
.api-disclosure {
  margin-top: auto;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  overflow: hidden;
}

.api-disclosure summary {
  list-style: none;
  padding: 10px 14px;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-2);
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.api-disclosure summary::-webkit-details-marker {
  display: none;
}

.api-disclosure[open] summary {
  border-bottom: 1px solid var(--line);
  color: var(--text);
}

.api-disclosure-body {
  padding: 12px 14px;
  display: grid;
  gap: 10px;
}

.api-box-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}

.api-code {
  margin: 0;
  padding: 11px 12px;
  border-radius: 9px;
  border: 1px solid var(--line);
  background: var(--solid);
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 内联编辑表单 */
.detail-edit-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  flex: 1;
}

.edit-row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

/* ---------- Token / 审计 / 安全子画布 ---------- */
.subpanel-card {
  padding: 16px 18px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  display: grid;
  gap: 12px;
}

.subpanel-card h4 {
  margin: 0;
  font-size: 14px;
}

.subpanel-card p {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.55;
}

.danger-zone {
  border-color: var(--danger-soft, rgba(204, 63, 39, 0.25));
}

.token-form {
  display: grid;
  gap: 10px;
}

.token-row-inline {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  align-items: center;
  font-size: 12.5px;
}

.brand-check {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.brand-check input {
  accent-color: var(--accent);
}

@supports not (accent-color: var(--accent)) {
  .brand-check {
    padding-left: 22px;
  }

  .brand-check input {
    position: absolute;
    clip-path: inset(50%);
    overflow: hidden;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    border: 0;
    white-space: nowrap;
  }

  .brand-check input + span::before {
    content: '';
    position: absolute;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    width: 15px;
    height: 15px;
    border: 1.5px solid var(--line-strong);
    background: var(--solid);
    border-radius: 4px;
    box-sizing: border-box;
  }

  .brand-check input[type='radio'] + span::before {
    border-radius: 999px;
  }

  .brand-check input:focus-visible + span::before {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }

  .brand-check input:checked + span::before {
    background: var(--accent);
    border-color: var(--accent);
  }

  .brand-check input[type='checkbox']:checked + span::after {
    content: '✓';
    position: absolute;
    left: 3px;
    top: 50%;
    transform: translateY(-50%);
    color: var(--accent-ink, #fff);
    font-size: 11px;
    font-weight: 700;
  }

  .brand-check input[type='radio']:checked + span::after {
    content: '';
    position: absolute;
    left: 4px;
    top: 50%;
    transform: translateY(-50%);
    width: 7px;
    height: 7px;
    border-radius: 999px;
    background: var(--accent-ink, #fff);
  }
}

.token-days {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.small-num {
  width: 82px;
}

.token-scope-box {
  display: grid;
  gap: 8px;
}

.token-entry-picker {
  display: grid;
  gap: 6px;
  max-height: 160px;
  overflow: auto;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--solid);
}

.token-created-box {
  padding: 12px 14px;
  border-radius: 11px;
  border: 1px solid var(--accent);
  background: var(--solid);
  display: grid;
  gap: 8px;
  word-break: break-all;
}

.token-created-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12.5px;
}

.token-item,
.audit-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 0;
  border-top: 1px solid var(--line);
  font-size: 12.5px;
}

.audit-detail {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audit-time {
  flex-shrink: 0;
  font-size: 11.5px;
}

.audit-outcome {
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}

.audit-outcome.allowed {
  background: var(--ok-soft);
  color: var(--ok);
}

.audit-outcome.denied {
  background: var(--danger-soft);
  color: var(--danger);
}

/* 空状态欢迎画布 */
.canvas-welcome {
  margin: auto;
  width: min(680px, 100%);
  padding: 32px 16px;
  text-align: center;
  display: grid;
  justify-items: center;
  gap: 14px;
}

.welcome-ic {
  width: 52px;
  height: 52px;
  border-radius: 16px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  color: var(--accent);
  display: grid;
  place-items: center;
  font-size: 22px;
  box-shadow: var(--shadow-1);
}

.canvas-welcome h3 {
  margin: 0;
  font-size: 20px;
  font-weight: 650;
  letter-spacing: -0.02em;
}

.welcome-lead {
  margin: 0;
  max-width: 460px;
  font-size: 13px;
  line-height: 1.6;
}

.welcome-tiers {
  width: 100%;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin: 6px 0 4px;
}

.welcome-tier-card {
  text-align: left;
  padding: 15px 14px;
  border-radius: 14px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--text);
  display: grid;
  align-content: start;
  gap: 8px;
  transition: border-color var(--dur-1, 120ms), background var(--dur-1, 120ms), box-shadow var(--dur-1, 120ms);
}

.welcome-tier-card:hover:not(:disabled) {
  background: var(--solid);
  border-color: var(--accent-line, var(--accent));
  box-shadow: var(--shadow-1);
}

.welcome-tier-card:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.welcome-tier-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.welcome-tier-card strong {
  font-size: 14px;
}

.welcome-tier-card p {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 900px) {
  .welcome-tiers {
    grid-template-columns: 1fr;
  }
}

/* 通用辅助 */
.icon-btn-sm {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: var(--text-2);
  flex-shrink: 0;
}

.icon-btn-sm:hover {
  background: var(--surface-3);
  color: var(--text);
}

.danger-text {
  color: var(--danger);
}

.space-alert {
  padding: 9px 11px;
  border-radius: 10px;
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 12px;
}

/* 全屏拖拽浮层 */
.drag-overlay {
  position: absolute;
  inset: 10px;
  z-index: 70;
  border-radius: 18px;
  border: 2px dashed var(--accent);
  background: var(--accent-soft);
  backdrop-filter: blur(6px);
  display: grid;
  place-items: center;
  pointer-events: none;
}

.drag-overlay-card {
  padding: 24px 32px;
  border-radius: 16px;
  border: 1px solid var(--accent-line, var(--accent));
  background: var(--solid);
  box-shadow: var(--shadow-2);
  display: grid;
  justify-items: center;
  gap: 8px;
  text-align: center;
}

.drag-overlay-ic {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--accent-soft);
  color: var(--accent);
  display: grid;
  place-items: center;
  font-size: 20px;
}

/* 原生 <dialog> 新建空间弹窗 */
dialog.space-dlg {
  width: min(500px, calc(100vw - 28px));
  padding: 22px;
  border-radius: var(--r-xl, 18px);
  border: 1px solid var(--line-strong);
  background: var(--solid);
  color: var(--text);
  box-shadow: var(--shadow-pop);
}

dialog.space-dlg::backdrop {
  background: var(--scrim, rgba(15, 23, 42, 0.45));
  backdrop-filter: blur(2px);
}

.space-dlg-form {
  display: grid;
  gap: 14px;
}

.space-dlg-form h3 {
  margin: 0;
  font-size: 16px;
}

.form-field {
  display: grid;
  gap: 6px;
  font-size: 12.5px;
}

.tier-picker {
  display: grid;
  gap: 8px;
}

.tier-option {
  text-align: left;
  padding: 11px 12px;
  border-radius: 11px;
  border: 1px solid var(--line);
  background: var(--surface-2);
  color: var(--text);
  display: grid;
  gap: 4px;
  transition: border-color var(--dur-1, 120ms), background var(--dur-1, 120ms);
}

.tier-option.active {
  background: var(--solid);
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.tier-option:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.tier-option-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.tier-option small {
  color: var(--text-2);
  font-size: 11.5px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
}

/* 响应式窄屏与移动端 */
@media (max-width: 1120px) {
  .space-shell:not(.is-mobile):not(.is-empty-state) {
    grid-template-columns: 216px 264px minmax(0, 1fr);
  }
  .space-shell.is-empty-state:not(.is-mobile) {
    grid-template-columns: 216px minmax(0, 1fr);
  }
  .space-col-canvas {
    padding: 18px 20px;
  }
}

.space-shell.is-mobile .space-col-nav,
.space-shell.is-mobile .space-col-catalog,
.space-shell.is-mobile .space-col-canvas {
  border-right: 0;
  padding: 14px;
  height: auto;
  overflow: visible;
}

.space-shell.is-mobile .edit-row-2 {
  grid-template-columns: 1fr;
}
</style>
