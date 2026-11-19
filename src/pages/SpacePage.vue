<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import OpusIcon from '../components/ui/OpusIcon.vue'
import SpacePasswordGate from '../components/space/SpacePasswordGate.vue'
import { useSpaceStore } from '../stores/space'
import { getApiBaseUrl } from '../services/fleetUrl'
import type { SpaceTier, SpaceTokenScope } from '../services/spaceApi'
import type { SpaceEntryType } from '../services/spaceCrypto'

const props = defineProps<{ mobile: boolean }>()
const emit = defineEmits<{ action: [message: string]; back: [] }>()

const spaceStore = useSpaceStore()

// 右侧子视图：内容 / API Token / 审计日志 / 安全设置
const activeTab = ref<'entries' | 'tokens' | 'audit' | 'security'>('entries')
const searchQuery = ref('')
const filterType = ref<SpaceEntryType | 'all'>('all')
const mobilePanel = ref<'spaces' | 'entries' | 'detail'>('spaces')

// 新建空间表单状态
const createSpaceOpen = ref(false)
const newSpaceName = ref('')
const newSpaceDesc = ref('')
const newSpaceTier = ref<SpaceTier>('standard')
const newSpacePassword = ref('')
const createSpaceBusy = ref(false)

// 新建条目表单状态
const createEntryOpen = ref(false)
const newEntryType = ref<SpaceEntryType>('text')
const newEntryTitle = ref('')
const newEntryTags = ref('')
const newEntryText = ref('')
const newEntryFile = ref<File | null>(null)
const createEntryBusy = ref(false)

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
    hint: 'UI 随时查看/下载，支持专用 ss_live_ API 与白名单 Agent 只读',
    badgeClass: 'tier-standard',
  },
  protected: {
    label: '受控机密',
    short: '机密',
    hint: 'UI 每次输密码查看，API 凭细粒度 sv_live_ 直读并强审计',
    badgeClass: 'tier-protected',
  },
  e2ee: {
    label: '极密保险库',
    short: 'E2EE',
    hint: '纯客户端 Argon2id + AES-256-GCM 零知识加密，Core 永不触达明文',
    badgeClass: 'tier-e2ee',
  },
}

const entryTypeLabels: Record<SpaceEntryType, string> = {
  text: '文本',
  config: '配置',
  key: '密钥',
  file: '文件',
}

const currentSpace = computed(() => spaceStore.selectedSpace)
const currentDetail = computed(() => spaceStore.selectedEntryDetail)
const currentUnlocked = computed(() =>
  spaceStore.unlockedView && spaceStore.unlockedView.entryId === spaceStore.selectedEntryId
    ? spaceStore.unlockedView
    : null,
)

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
    createSpaceOpen.value = false
    newSpaceName.value = ''
    newSpaceDesc.value = ''
    newSpacePassword.value = ''
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
    emit('action', '空间已归档并吊销关联 Token')
    if (props.mobile) mobilePanel.value = 'spaces'
  } catch (cause) {
    emit('action', cause instanceof Error ? cause.message : '归档空间失败')
  }
}

function handleFileInputChange(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0] ?? null
  newEntryFile.value = file
  if (file && !newEntryTitle.value.trim()) {
    newEntryTitle.value = file.name
  }
}

async function submitCreateEntryWithOptionalPassword(password?: string) {
  createEntryBusy.value = true
  try {
    const tags = newEntryTags.value
      .split(/[,，\s]+/)
      .map(t => t.trim())
      .filter(Boolean)
    await spaceStore.createEntry({
      entryType: newEntryType.value,
      title: newEntryTitle.value.trim(),
      tags,
      contentText: newEntryType.value === 'file' ? undefined : newEntryText.value,
      file: newEntryType.value === 'file' ? (newEntryFile.value ?? undefined) : undefined,
      password,
    })
    createEntryOpen.value = false
    newEntryTitle.value = ''
    newEntryTags.value = ''
    newEntryText.value = ''
    newEntryFile.value = null
    emit('action', '条目已保存')
    if (props.mobile) mobilePanel.value = 'detail'
  } finally {
    createEntryBusy.value = false
  }
}

async function handleCreateEntry() {
  const sp = currentSpace.value
  if (!sp || !newEntryTitle.value.trim()) return
  if (newEntryType.value === 'file' && !newEntryFile.value) {
    emit('action', '请选择要上传的文件')
    return
  }
  if (sp.tier === 'standard') {
    try {
      await submitCreateEntryWithOptionalPassword()
    } catch (cause) {
      emit('action', cause instanceof Error ? cause.message : '保存失败')
    }
    return
  }
  openPasswordGate({
    title: sp.tier === 'e2ee' ? '输入极密密码加密保存' : '输入受控机密密码保存',
    description:
      sp.tier === 'e2ee'
        ? '内容将在本机使用 AES-256-GCM 加密后分块上传，Core 不会收到明文。'
        : '服务端将在校验当次空间密码后使用主密钥信封加密落盘。',
    confirmLabel: '加密并保存',
    onSubmit: async pwd => {
      await submitCreateEntryWithOptionalPassword(pwd)
    },
  })
}

function requestUnlockEntry() {
  const sp = currentSpace.value
  const detail = currentDetail.value
  if (!sp || !detail) return
  openPasswordGate({
    title: sp.tier === 'e2ee' ? '本地解密查看条目' : '验证空间密码查看条目',
    description: '本次验证仅用于展示当前条目，离开页面或切换条目后立即清除内存。',
    confirmLabel: '解密查看',
    onSubmit: async pwd => {
      await spaceStore.unlockCurrentEntryWithPassword(pwd)
      emit('action', '已临时解密，离页即清')
    },
  })
}

function requestDecryptE2eeCatalog() {
  openPasswordGate({
    title: '输入极密密码解密当前目录',
    description: 'E2EE 空间的文件名与标签均在加密 Manifest 中，输入当次密码后可在内存浏览与搜索，离页自动清空。',
    confirmLabel: '解密目录',
    onSubmit: async pwd => {
      await spaceStore.decryptE2eeCatalogWithPassword(pwd)
      emit('action', '目录已在内存中解密')
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
    const tags = editTags.value
      .split(/[,，\s]+/)
      .map(t => t.trim())
      .filter(Boolean)
    await spaceStore.updateStandardEntry(currentDetail.value, editTitle.value.trim(), editText.value, tags)
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
    emit('action', '条目已删除')
    if (props.mobile) mobilePanel.value = 'entries'
  } catch (cause) {
    emit('action', cause instanceof Error ? cause.message : '删除失败')
  }
}

async function copyText(text: string, isSecret = false) {
  try {
    await navigator.clipboard.writeText(text)
    emit('action', isSecret ? '已复制敏感内容，请使用后注意清理剪贴板' : '已复制到剪贴板')
  } catch {
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
      title: '输入空间密码以签发 Vault Token (sv_live_)',
      description: '签发细粒度 Vault Token 属于高敏感授权操作，需先校验当前受控机密空间密码。',
      confirmLabel: '确认签发',
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
    if (activeTab.value === 'tokens' || activeTab.value === 'audit') {
      void spaceStore.loadTokensAndAudit()
    }
  },
)

onMounted(() => {
  void spaceStore.loadSpaces()
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onUnmounted(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  spaceStore.clearSensitiveMemory()
})
</script>

<template>
  <div :class="mobile ? 'mpage space-mobile' : 'page full space-desktop'">
    <!-- 移动端顶栏 -->
    <div v-if="mobile" class="navbar">
      <button
        type="button"
        class="icon-btn"
        aria-label="返回"
        @click="mobilePanel === 'detail' ? (mobilePanel = 'entries', spaceStore.clearSensitiveMemory()) : mobilePanel === 'entries' ? (mobilePanel = 'spaces', spaceStore.clearSensitiveMemory()) : emit('back')"
      >
        <OpusIcon name="chevL" />
      </button>
      <div class="t">
        {{ mobilePanel === 'spaces' ? '共享空间' : mobilePanel === 'entries' ? (currentSpace?.name ?? '条目') : displayEntryTitle(currentDetail ?? { id: '', title: '详情' }) }}
      </div>
      <button v-if="mobilePanel === 'spaces'" type="button" class="icon-btn" aria-label="新建空间" @click="createSpaceOpen = true">
        <OpusIcon name="plus" />
      </button>
      <button v-else-if="mobilePanel === 'entries' && currentSpace" type="button" class="icon-btn" aria-label="新建条目" @click="createEntryOpen = true">
        <OpusIcon name="plus" />
      </button>
      <span v-else style="width: 40px"></span>
    </div>

    <div class="space-layout" :class="{ 'is-mobile': mobile }">
      <!-- 左栏：空间列表 -->
      <aside v-show="!mobile || mobilePanel === 'spaces'" class="pane-side space-col-spaces">
        <div class="pane-h">
          <h2>共享空间</h2>
          <span class="spacer"></span>
          <button type="button" class="btn btn-sm btn-primary" @click="createSpaceOpen = true">
            <OpusIcon name="plus" /> 新建
          </button>
        </div>

        <div class="space-tier-legend">
          <span class="tier-pill tier-standard">普通 · 随时看/API</span>
          <span class="tier-pill tier-protected">机密 · 输密/Vault Token</span>
          <span class="tier-pill tier-e2ee">E2EE · 零知识</span>
        </div>

        <div v-if="spaceStore.error" class="space-alert" role="alert">{{ spaceStore.error }}</div>

        <div class="space-list">
          <button
            v-for="sp in spaceStore.spaces"
            :key="sp.id"
            type="button"
            class="space-card"
            :class="{ active: sp.id === spaceStore.selectedSpaceId }"
            @click="spaceStore.selectSpace(sp.id); if (mobile) mobilePanel = 'entries'"
          >
            <div class="space-card-top">
              <strong>{{ sp.name }}</strong>
              <span class="tier-pill" :class="tierMeta[sp.tier].badgeClass">{{ tierMeta[sp.tier].short }}</span>
            </div>
            <div v-if="sp.description" class="space-card-desc muted">{{ sp.description }}</div>
            <div class="space-card-meta faint">
              <span>{{ sp.entryCount }} 条</span>
              <span>{{ formatBytes(sp.usedBytes) }} / {{ formatBytes(sp.quotaBytes) }}</span>
            </div>
          </button>
          <div v-if="!spaceStore.loading && spaceStore.spaces.length === 0" class="space-empty muted">
            还没有共享空间，点击右上角「新建」按普通/机密/极密分级创建。
          </div>
        </div>
      </aside>

      <!-- 中栏：条目列表 -->
      <section v-show="!mobile || mobilePanel === 'entries'" class="space-col-entries">
        <template v-if="currentSpace">
          <div class="space-bar">
            <div>
              <div class="space-title-row">
                <h3>{{ currentSpace.name }}</h3>
                <span class="tier-pill" :class="tierMeta[currentSpace.tier].badgeClass">{{ tierMeta[currentSpace.tier].label }}</span>
                <span v-if="currentSpace.tier === 'e2ee'" class="faint">Epoch #{{ currentSpace.activeEpoch }}</span>
              </div>
              <p class="muted space-hint">{{ tierMeta[currentSpace.tier].hint }}</p>
            </div>
            <div class="space-bar-actions">
              <button type="button" class="btn btn-sm btn-primary" @click="createEntryOpen = true">
                <OpusIcon name="plus" /> 新建条目
              </button>
              <button
                v-if="currentSpace.tier === 'e2ee'"
                type="button"
                class="btn btn-sm btn-ghost"
                @click="requestDecryptE2eeCatalog"
              >
                <OpusIcon name="unlock" /> 输密解密目录
              </button>
            </div>
          </div>

          <div class="space-tabs" role="tablist">
            <button type="button" :class="{ active: activeTab === 'entries' }" @click="activeTab = 'entries'">内容条目</button>
            <button v-if="currentSpace.tier !== 'e2ee'" type="button" :class="{ active: activeTab === 'tokens' }" @click="activeTab = 'tokens'">
              API Token
            </button>
            <button type="button" :class="{ active: activeTab === 'audit' }" @click="activeTab = 'audit'">审计日志</button>
            <button v-if="currentSpace.tier !== 'standard'" type="button" :class="{ active: activeTab === 'security' }" @click="activeTab = 'security'">
              密码与轮换
            </button>
            <span class="spacer"></span>
            <button type="button" class="btn btn-sm btn-ghost danger-text" @click="handleArchiveCurrentSpace">归档空间</button>
          </div>

          <!-- 内容条目列表视图 -->
          <template v-if="activeTab === 'entries'">
            <div class="space-filter-row">
              <input
                v-model="searchQuery"
                class="input"
                type="search"
                :placeholder="currentSpace.tier === 'e2ee' ? '先点击「输密解密目录」后可在内存中搜索…' : '搜索标题、文件名或标签…'"
              />
              <select v-model="filterType" class="input space-type-select" aria-label="条目类型">
                <option value="all">全部类型</option>
                <option value="text">文本</option>
                <option value="config">配置</option>
                <option value="key">密钥</option>
                <option value="file">文件</option>
              </select>
            </div>

            <div class="entry-list">
              <button
                v-for="item in filteredEntries"
                :key="item.id"
                type="button"
                class="entry-row"
                :class="{ active: item.id === spaceStore.selectedEntryId }"
                @click="spaceStore.selectEntry(item.id); editingStandard = false; if (mobile) mobilePanel = 'detail'"
              >
                <div class="entry-row-top">
                  <span class="entry-type-tag">{{ entryTypeLabels[item.entryType] }}</span>
                  <strong class="entry-title">{{ displayEntryTitle(item) }}</strong>
                  <span v-if="item.hasConflict" class="conflict-tag">有冲突</span>
                </div>
                <div class="entry-row-meta faint">
                  <span>r{{ item.currentRevision }}</span>
                  <span>{{ formatBytes(item.sizeBytes) }}</span>
                  <span v-if="item.tags.length">#{{ item.tags.join(' #') }}</span>
                </div>
              </button>
              <div v-if="!spaceStore.loading && filteredEntries.length === 0" class="space-empty muted">
                当前空间暂无条目。
              </div>
            </div>
          </template>

          <!-- API Token 管理面板（standard -> ss_live_, protected -> sv_live_） -->
          <div v-else-if="activeTab === 'tokens'" class="space-subpanel">
            <div class="subpanel-card">
              <h4>
                签发专用 {{ currentSpace.tier === 'protected' ? 'Vault Token (sv_live_)' : 'Space Token (ss_live_)' }}
              </h4>
              <p class="muted">
                {{
                  currentSpace.tier === 'protected'
                    ? 'sv_live_ 仅可读取本受控机密空间（可进一步限定到指定条目白名单），每次调用均记入审计日志。'
                    : 'ss_live_ 可随时通过 REST API 读取（或按授权写入）本普通共享空间，无法访问任何机密或 E2EE 空间。'
                }}
              </p>

              <div class="token-form">
                <input v-model="newTokenName" class="input" placeholder="Token 名称，例如：部署脚本只读" />
                <div class="token-row-inline">
                  <label><input v-model="newTokenScopes" type="checkbox" value="read" /> 读取 (read)</label>
                  <label><input v-model="newTokenScopes" type="checkbox" value="write" /> 写入 (write)</label>
                  <label>有效期(天) <input v-model="newTokenDays" class="input small-num" type="number" min="1" max="3650" /></label>
                </div>

                <div v-if="currentSpace.tier === 'protected'" class="token-scope-box">
                  <div class="token-row-inline">
                    <label><input v-model="newTokenEntryScope" type="radio" value="all" /> 授权整个空间</label>
                    <label><input v-model="newTokenEntryScope" type="radio" value="selected" /> 仅授权勾选条目（最小权限推荐）</label>
                  </div>
                  <div v-if="newTokenEntryScope === 'selected'" class="token-entry-picker">
                    <label v-for="entry in spaceStore.entries" :key="entry.id" class="token-entry-opt">
                      <input v-model="newTokenEntryIds" type="checkbox" :value="entry.id" />
                      <span>{{ entry.title ?? entry.id.slice(0, 8) }}</span>
                    </label>
                  </div>
                </div>

                <button type="button" class="btn btn-primary btn-sm" :disabled="tokenBusy || !newTokenName.trim()" @click="handleIssueToken">
                  {{ tokenBusy ? '签发中…' : '签发 Token' }}
                </button>
              </div>

              <div v-if="spaceStore.lastCreatedToken" class="token-created-box">
                <div><strong>新 Token（仅显示一次，离页自动清除）：</strong></div>
                <code>{{ spaceStore.lastCreatedToken.token }}</code>
                <button type="button" class="btn btn-sm btn-ghost" @click="copyText(spaceStore.lastCreatedToken.token, true)">复制 Token</button>
              </div>
            </div>

            <div class="subpanel-card">
              <h4>已签发 Token</h4>
              <div v-if="spaceStore.tokens.length === 0" class="muted">暂无 Token。</div>
              <div v-for="tk in spaceStore.tokens" :key="tk.id" class="token-item">
                <div>
                  <strong>{{ tk.name }}</strong>
                  <span class="faint"> · ****{{ tk.tokenLast4 }} · {{ tk.scopes.join('/') }}</span>
                  <div class="faint" style="font-size: 12px">
                    范围：{{ tk.entryIds ? `仅 ${tk.entryIds.length} 个条目` : '整个空间' }}
                    <span v-if="tk.revokedAt"> · 已吊销</span>
                    <span v-else-if="tk.lastUsedAt"> · 最近使用 {{ tk.lastUsedAt.slice(0, 19).replace('T', ' ') }}</span>
                  </div>
                </div>
                <button v-if="!tk.revokedAt" type="button" class="btn btn-sm btn-ghost danger-text" @click="handleRevokeToken(tk.id)">
                  吊销
                </button>
              </div>
            </div>
          </div>

          <!-- 审计日志面板 -->
          <div v-else-if="activeTab === 'audit'" class="space-subpanel">
            <div class="subpanel-card">
              <h4>访问审计日志（不含任何明文与密码）</h4>
              <div v-if="spaceStore.auditLogs.length === 0" class="muted">暂无审计记录。</div>
              <div v-for="log in spaceStore.auditLogs" :key="log.id" class="audit-row">
                <span class="audit-outcome" :class="log.outcome">{{ log.outcome }}</span>
                <strong>{{ log.action }}</strong>
                <span class="faint">{{ log.actorKind }}</span>
                <span class="muted">{{ log.detail }}</span>
                <span class="spacer"></span>
                <span class="faint">{{ log.createdAt.slice(0, 19).replace('T', ' ') }}</span>
              </div>
            </div>
          </div>

          <!-- 改密与 Epoch 轮换面板 -->
          <div v-else-if="activeTab === 'security'" class="space-subpanel">
            <div class="subpanel-card">
              <h4>修改空间密码</h4>
              <p class="muted">
                {{
                  currentSpace.tier === 'e2ee'
                    ? '常规改密：先用旧密码解包 Space Key，再生成新随机盐与新密码通过 CAS 重包 KeyEnvelope（保持当前 Epoch）。'
                    : '验证旧空间密码后更新服务端 Argon2id 口令校验串，立即对后续 UI 访问生效。'
                }}
              </p>
              <div class="token-form">
                <input v-model="changeOldPwd" class="input" type="password" placeholder="当前空间密码" autocomplete="off" />
                <input v-model="changeNewPwd" class="input" type="password" placeholder="新空间密码（至少 8 位）" autocomplete="off" />
                <button
                  type="button"
                  class="btn btn-primary btn-sm"
                  :disabled="securityBusy || !changeOldPwd || changeNewPwd.length < 8"
                  @click="handleChangePassword"
                >
                  更新空间密码
                </button>
              </div>
            </div>

            <div v-if="currentSpace.tier === 'e2ee'" class="subpanel-card">
              <h4>泄露响应 · Epoch 密钥轮换（当前 Epoch #{{ currentSpace.activeEpoch }}）</h4>
              <p class="muted">
                怀疑旧密码或旧 Space Key 泄露时执行：生成全新随机 256 位 Space Key 并递增至 Epoch #{{ currentSpace.activeEpoch + 1 }}，服务端拒绝陈旧 Epoch 写入，本机记录最高 Epoch 防止静默回退。
              </p>
              <div class="token-form">
                <input v-model="rotateNewPwd" class="input" type="password" placeholder="为新 Epoch 设置新密码（至少 8 位）" autocomplete="off" />
                <button
                  type="button"
                  class="btn btn-sm btn-ghost danger-text"
                  :disabled="securityBusy || rotateNewPwd.length < 8"
                  @click="handleRotateEpoch"
                >
                  执行 Epoch 轮换
                </button>
              </div>
            </div>
          </div>
        </template>
        <div v-else class="space-empty muted">请选择或创建一个共享空间。</div>
      </section>

      <!-- 右栏：条目详情 / 按次解锁 / API 示例 -->
      <aside v-show="(!mobile && activeTab === 'entries') || (mobile && mobilePanel === 'detail')" class="pane-inspector space-col-detail">
        <template v-if="currentSpace && currentDetail">
          <div class="detail-head">
            <div>
              <span class="entry-type-tag">{{ entryTypeLabels[currentDetail.entryType] }}</span>
              <h3>{{ currentUnlocked?.manifest?.title ?? displayEntryTitle(currentDetail) }}</h3>
              <div class="faint" style="font-size: 12px">
                修订 r{{ currentDetail.revision }} · {{ formatBytes(currentDetail.sizeBytes) }}
                <span v-if="currentSpace.tier === 'e2ee'"> · Epoch #{{ currentDetail.epoch }}</span>
              </div>
            </div>
            <div class="detail-actions">
              <button v-if="currentUnlocked" type="button" class="btn btn-sm btn-ghost" @click="spaceStore.clearSensitiveMemory(); emit('action', '已立即锁定并清除内存明文')">
                <OpusIcon name="lock" /> 立即锁定
              </button>
              <button type="button" class="btn btn-sm btn-ghost danger-text" @click="handleDeleteEntry">删除</button>
            </div>
          </div>

          <!-- 1. Standard 普通共享：随时查看/编辑/下载/API -->
          <template v-if="currentSpace.tier === 'standard'">
            <div v-if="!editingStandard" class="detail-body">
              <div v-if="currentDetail.entryType === 'file'" class="file-card">
                <div><strong>{{ currentDetail.fileName ?? currentDetail.title }}</strong></div>
                <div class="faint">{{ currentDetail.mime }} · {{ formatBytes(currentDetail.sizeBytes) }}</div>
                <button type="button" class="btn btn-primary btn-sm" @click="spaceStore.downloadStandardEntry(currentDetail)">下载文件</button>
              </div>
              <pre v-else class="content-pre">{{ currentDetail.contentText ?? '' }}</pre>

              <div class="detail-toolbar">
                <button v-if="currentDetail.entryType !== 'file'" type="button" class="btn btn-sm btn-ghost" @click="copyText(currentDetail.contentText ?? '')">复制内容</button>
                <button v-if="currentDetail.entryType !== 'file'" type="button" class="btn btn-sm btn-ghost" @click="startEditStandard">编辑</button>
              </div>

              <div class="api-box">
                <div class="api-box-head">
                  <strong>随时 API 读取示例（ss_live_）</strong>
                  <button type="button" class="btn btn-sm btn-ghost" @click="copyText(apiExampleCurl())">复制 curl</button>
                </div>
                <pre class="api-code">{{ apiExampleCurl() }}</pre>
              </div>
            </div>

            <div v-else class="detail-edit">
              <input v-model="editTitle" class="input" placeholder="标题" />
              <input v-model="editTags" class="input" placeholder="标签（逗号分隔）" />
              <textarea v-model="editText" class="input content-textarea" rows="10" />
              <div class="detail-toolbar">
                <button type="button" class="btn btn-sm btn-ghost" @click="editingStandard = false">取消</button>
                <button type="button" class="btn btn-sm btn-primary" @click="saveEditStandard">保存新修订</button>
              </div>
            </div>
          </template>

          <!-- 2. Protected / E2EE 锁定态 -->
          <template v-else-if="!currentUnlocked">
            <div class="locked-panel mat">
              <div class="lk"><OpusIcon name="lock" /></div>
              <h4>{{ currentSpace.tier === 'e2ee' ? '极密内容已本地加密锁定' : '受控机密内容已锁定' }}</h4>
              <p class="muted">
                {{
                  currentSpace.tier === 'e2ee'
                    ? '每次读取均需重新输入空间密码在本地解密；离开页面、切换条目或切后台将立即清空内存。'
                    : 'UI 每次查看均需重新输入空间密码；自动化脚本请使用「API Token」签发细粒度 sv_live_ 读取。'
                }}
              </p>
              <button type="button" class="btn btn-primary" @click="requestUnlockEntry">
                <OpusIcon name="unlock" /> 输入密码查看内容
              </button>
            </div>

            <div v-if="currentSpace.tier === 'protected'" class="api-box">
              <div class="api-box-head">
                <strong>受控机密 API 读取示例（sv_live_）</strong>
                <button type="button" class="btn btn-sm btn-ghost" @click="copyText(apiExampleCurl())">复制 curl</button>
              </div>
              <pre class="api-code">{{ apiExampleCurl() }}</pre>
            </div>
          </template>

          <!-- 3. Protected / E2EE 当次解密态（纯内存） -->
          <template v-else>
            <div class="unlocked-banner">
              <OpusIcon name="unlock" /> 已在内存中临时解密，离开页面或切换条目后立即清除
            </div>
            <div v-if="currentUnlocked.fileBlob" class="file-card">
              <div><strong>{{ currentUnlocked.fileName }}</strong></div>
              <div class="faint">{{ currentUnlocked.mime }} · {{ formatBytes(currentUnlocked.fileBlob.size) }}</div>
              <button type="button" class="btn btn-primary btn-sm" @click="downloadUnlockedFile">下载解密后的文件</button>
            </div>
            <pre v-else class="content-pre secret-pre">{{ currentUnlocked.contentText ?? '' }}</pre>
            <div class="detail-toolbar">
              <button v-if="currentUnlocked.contentText !== null" type="button" class="btn btn-sm btn-ghost" @click="copyText(currentUnlocked.contentText, true)">
                复制明文
              </button>
              <button type="button" class="btn btn-sm btn-ghost" @click="spaceStore.clearSensitiveMemory()">立即清空锁定</button>
            </div>
          </template>
        </template>
        <div v-else class="space-empty muted">选择一条共享内容以查看详情或按次解密。</div>
      </aside>
    </div>

    <!-- 新建空间模态框 -->
    <div v-if="createSpaceOpen" class="space-modal-backdrop" role="dialog" aria-modal="true" @click.self="createSpaceOpen = false">
      <form class="space-modal-card mat" @submit.prevent="handleCreateSpace">
        <h3>新建共享空间</h3>
        <label class="form-field">
          <span>空间名称</span>
          <input v-model="newSpaceName" class="input" required placeholder="例如：日常笔记 / 生产密钥库 / 极密私钥" />
        </label>
        <label class="form-field">
          <span>简介（可选）</span>
          <input v-model="newSpaceDesc" class="input" placeholder="用途说明" />
        </label>
        <div class="form-field">
          <span>安全等级</span>
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
              <strong>{{ tierMeta[tier].label }}</strong>
              <small>{{ tierMeta[tier].hint }}</small>
            </button>
          </div>
          <p v-if="spaceStore.capabilities && !spaceStore.capabilities.protectedAvailable" class="faint" style="margin: 4px 0 0; font-size: 12px">
            提示：当前后端未配置 STUDIOLO_VAULT_MASTER_KEY，受控机密（protected）档暂不可用；普通共享与极密 E2EE 均可正常使用。
          </p>
        </div>
        <label v-if="newSpaceTier !== 'standard'" class="form-field">
          <span>空间密码（至少 8 位）</span>
          <input v-model="newSpacePassword" class="input" type="password" autocomplete="new-password" minlength="8" required />
          <small v-if="newSpaceTier === 'e2ee'" class="danger-text">
            注意：极密 E2EE 空间无任何服务端密码找回或托管机制，请务必自行妥善备份密码！
          </small>
        </label>
        <div class="modal-actions">
          <button type="button" class="btn btn-ghost" @click="createSpaceOpen = false">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="createSpaceBusy || !newSpaceName.trim()">
            {{ createSpaceBusy ? '正在创建…' : '创建空间' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 新建条目模态框 -->
    <div v-if="createEntryOpen && currentSpace" class="space-modal-backdrop" role="dialog" aria-modal="true" @click.self="createEntryOpen = false">
      <form class="space-modal-card mat" @submit.prevent="handleCreateEntry">
        <h3>在「{{ currentSpace.name }}」新建条目</h3>
        <div class="form-row-2">
          <label class="form-field">
            <span>类型</span>
            <select v-model="newEntryType" class="input">
              <option value="text">文本</option>
              <option value="config">配置</option>
              <option value="key">密钥 / Key</option>
              <option value="file">小型文件</option>
            </select>
          </label>
          <label class="form-field">
            <span>标签（逗号分隔）</span>
            <input v-model="newEntryTags" class="input" placeholder="ops, prod" />
          </label>
        </div>
        <label class="form-field">
          <span>标题</span>
          <input v-model="newEntryTitle" class="input" required placeholder="条目标题或文件名" />
        </label>
        <label v-if="newEntryType === 'file'" class="form-field">
          <span>选择文件</span>
          <input type="file" class="input" @change="handleFileInputChange" />
        </label>
        <label v-else class="form-field">
          <span>内容</span>
          <textarea v-model="newEntryText" class="input content-textarea" rows="8" placeholder="输入文本、配置或密钥内容…" />
        </label>
        <div class="modal-actions">
          <button type="button" class="btn btn-ghost" @click="createEntryOpen = false">取消</button>
          <button type="submit" class="btn btn-primary" :disabled="createEntryBusy || !newEntryTitle.trim()">
            {{ currentSpace.tier === 'standard' ? '保存' : '下一步：输入密码加密保存' }}
          </button>
        </div>
      </form>
    </div>

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
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
.space-layout {
  display: grid;
  grid-template-columns: 260px minmax(280px, 1fr) minmax(320px, 1.15fr);
  height: 100%;
  min-height: 0;
}
.space-layout.is-mobile {
  display: block;
  height: auto;
}
.space-col-spaces,
.space-col-entries,
.space-col-detail {
  min-width: 0;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
}
.space-col-entries {
  border-right: 1px solid var(--line);
}
.space-tier-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.tier-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
}
.tier-standard {
  background: var(--surface-3);
  color: var(--text);
}
.tier-protected {
  background: rgba(217, 119, 6, 0.14);
  color: #b45309;
}
.tier-e2ee {
  background: rgba(79, 70, 229, 0.14);
  color: #4338ca;
}
:global([data-mode='dark']) .tier-protected {
  color: #fbbf24;
}
:global([data-mode='dark']) .tier-e2ee {
  color: #a5b4fc;
}
.space-list,
.entry-list {
  display: grid;
  gap: 8px;
  align-content: start;
}
.space-card,
.entry-row {
  text-align: left;
  padding: 11px 12px;
  border-radius: var(--r-md, 12px);
  border: 1px solid var(--line);
  background: var(--solid);
  color: var(--text);
  cursor: pointer;
  display: grid;
  gap: 5px;
}
.space-card.active,
.entry-row.active {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}
.space-card-top,
.entry-row-top {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: space-between;
}
.entry-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.space-card-desc {
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.space-card-meta,
.entry-row-meta {
  display: flex;
  gap: 10px;
  font-size: 11.5px;
}
.space-bar {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 10px;
  align-items: flex-start;
}
.space-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.space-title-row h3 {
  margin: 0;
}
.space-hint {
  margin: 4px 0 0;
  font-size: 12px;
}
.space-bar-actions {
  display: flex;
  gap: 8px;
}
.space-tabs {
  display: flex;
  gap: 6px;
  align-items: center;
  border-bottom: 1px solid var(--line);
  padding-bottom: 8px;
  flex-wrap: wrap;
}
.space-tabs > button:not(.btn) {
  padding: 5px 10px;
  border-radius: 8px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--muted);
  font-size: 12.5px;
  cursor: pointer;
}
.space-tabs > button:not(.btn).active {
  background: var(--surface-3);
  color: var(--text);
  font-weight: 600;
}
.space-filter-row {
  display: flex;
  gap: 8px;
}
.space-type-select {
  width: 110px;
  flex-shrink: 0;
}
.entry-type-tag {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 6px;
  background: var(--surface-3);
  color: var(--muted);
}
.conflict-tag {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 6px;
  background: rgba(220, 38, 38, 0.14);
  color: var(--danger);
}
.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}
.detail-head h3 {
  margin: 4px 0;
}
.detail-actions,
.detail-toolbar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.content-pre,
.api-code {
  margin: 0;
  padding: 12px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--surface-2, var(--surface-3));
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 360px;
  overflow: auto;
}
.content-textarea {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12.5px;
  resize: vertical;
}
.locked-panel {
  padding: 24px 18px;
  border-radius: 14px;
  border: 1px solid var(--line);
  text-align: center;
  display: grid;
  gap: 10px;
  justify-items: center;
}
.locked-panel h4,
.locked-panel p {
  margin: 0;
}
.unlocked-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 10px;
  background: rgba(22, 163, 74, 0.12);
  color: #15803d;
  font-size: 12px;
}
.api-box,
.subpanel-card,
.file-card {
  padding: 12px;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: var(--solid);
  display: grid;
  gap: 10px;
}
.api-box-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12.5px;
}
.space-subpanel {
  display: grid;
  gap: 12px;
}
.token-form {
  display: grid;
  gap: 10px;
}
.token-row-inline {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  align-items: center;
  font-size: 12.5px;
}
.small-num {
  width: 78px;
  display: inline-block;
}
.token-entry-picker {
  display: grid;
  gap: 6px;
  max-height: 140px;
  overflow: auto;
  padding: 8px;
  border: 1px solid var(--line);
  border-radius: 8px;
}
.token-entry-opt {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 12.5px;
}
.token-created-box {
  padding: 10px;
  border-radius: 10px;
  border: 1px solid var(--accent);
  background: var(--surface-3);
  display: grid;
  gap: 8px;
  word-break: break-all;
}
.token-item,
.audit-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 0;
  border-top: 1px solid var(--line);
  font-size: 12.5px;
}
.audit-outcome {
  padding: 1px 6px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}
.audit-outcome.allowed {
  background: rgba(22, 163, 74, 0.14);
  color: #15803d;
}
.audit-outcome.denied {
  background: rgba(220, 38, 38, 0.14);
  color: var(--danger);
}
.danger-text {
  color: var(--danger);
}
.space-alert {
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(220, 38, 38, 0.12);
  color: var(--danger);
  font-size: 12.5px;
}
.space-empty {
  padding: 28px 16px;
  text-align: center;
  font-size: 13px;
}
.space-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(15, 23, 42, 0.45);
}
.space-modal-card {
  width: min(520px, 100%);
  max-height: 90dvh;
  overflow-y: auto;
  padding: 20px;
  border-radius: 16px;
  border: 1px solid var(--line);
  background: var(--solid);
  box-shadow: var(--shadow-pop);
  display: grid;
  gap: 14px;
}
.space-modal-card h3 {
  margin: 0;
}
.form-field {
  display: grid;
  gap: 6px;
  font-size: 12.5px;
}
.form-row-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.tier-picker {
  display: grid;
  gap: 8px;
}
.tier-option {
  text-align: left;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: var(--solid);
  color: var(--text);
  cursor: pointer;
  display: grid;
  gap: 3px;
}
.tier-option.active {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}
.tier-option:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.tier-option small {
  color: var(--muted);
  font-size: 11.5px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
</style>
