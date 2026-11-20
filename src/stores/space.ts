/**
 * Shared Space（/space）Pinia 状态管理。
 *
 * 安全红线：
 * 1. `protected` 与 `e2ee` 解密出的明文、Manifest、预览 Blob URL 严格仅存于内存 ref，
 *    绝不写入 localStorage / sessionStorage / IndexedDB。
 * 2. 离开页面、切空间、切条目、切后台、登出或账号切换时必须调用 `clearSensitiveMemory()` 立即清空。
 * 3. `e2ee` 每次读取或写入都重新向用户索取密码并在 finally 中调用 `zeroizeBytes` 清零密钥。
 */

import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { apiRequest, ApiError } from '../api/client'
import { useAuthStore } from './auth'
import { useFleetStore } from './fleet'
import { getApiBaseUrl } from '../services/fleetUrl'
import {
  archiveSpaceApi,
  changeProtectedPasswordApi,
  createSpaceApi,
  createSpaceEntryApi,
  createSpaceTokenApi,
  deleteSpaceEntryApi,
  downloadEntryBlob,
  downloadSpaceBlobChunk,
  fetchSpaceAuditLogs,
  fetchSpaceCapabilities,
  fetchSpaceEntries,
  fetchSpaceEntryDetail,
  fetchSpaceEnvelope,
  fetchSpaces,
  fetchSpaceTokens,
  fetchStandardSpaceConflicts,
  initSpaceBlob,
  revokeSpaceTokenApi,
  resolveStandardSpaceConflict,
  rotateSpaceEpochApi,
  unlockProtectedEntryApi,
  updateSpaceEntryApi,
  updateSpaceEnvelopeCas,
  uploadSpaceBlobChunk,
  type SpaceAuditLogItem,
  type SpaceCapabilities,
  type SpaceEnvelopeResponse,
  type SpaceEntryDetail,
  type SpaceEntrySummary,
  type StandardSpaceSnapshot,
  type SpaceItem,
  type SpaceRouteConfig,
  type SpaceTier,
  type SpaceTokenCreated,
  type SpaceTokenItem,
  type SpaceTokenScope,
  type StandardSpaceConflict,
} from '../services/spaceApi'
import { SpaceReplica, type PinnedCiphertext, type SpaceMutation } from '../services/spaceReplica'
import { pullStandardSpace, pushSpaceQueue } from '../services/spaceSync'
import { desktopPlatform } from '../desktop/platform'
import {
  DEFAULT_CHUNK_SIZE,
  KEY_BYTES,
  createRotatedEpochEnvelope,
  decryptChunk,
  decryptManifest,
  encryptChunk,
  encryptManifest,
  randomBytes,
  rewrapEnvelopeForPasswordChange,
  sha256Hex,
  unwrapDek,
  unwrapSpaceKey,
  wrapDek,
  wrapSpaceKey,
  zeroizeBytes,
  type SpaceEntryManifest,
  type SpaceEntryType,
} from '../services/spaceCrypto'

const EPOCH_FLOOR_PREFIX = 'studiolo:space:max-epoch:'
const TEXT_ENCODER = new TextEncoder()
const TEXT_DECODER = new TextDecoder()

export interface UnlockedEntryView {
  entryId: string
  revision: number
  manifest?: SpaceEntryManifest
  contentText: string | null
  fileBlob?: Blob
  fileName?: string
  mime?: string
  unlockedAt: number
}

function readHighestEpoch(spaceId: string): number {
  try {
    const raw = localStorage.getItem(`${EPOCH_FLOOR_PREFIX}${spaceId}`)
    const parsed = raw ? Number(raw) : 0
    return Number.isInteger(parsed) && parsed > 0 ? parsed : 0
  } catch {
    return 0
  }
}

function recordHighestEpoch(spaceId: string, epoch: number): void {
  const prev = readHighestEpoch(spaceId)
  if (epoch < prev) {
    throw new Error(`检测到空间密钥世代（epoch=${epoch}）低于本机已确认版本（${prev}），已拒绝静默回退`)
  }
  try {
    localStorage.setItem(`${EPOCH_FLOOR_PREFIX}${spaceId}`, String(epoch))
  } catch {
    // 忽略存储受限环境
  }
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  const step = 0x8000
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode(...bytes.subarray(i, i + step))
  }
  return btoa(binary)
}

export const useSpaceStore = defineStore('space', () => {
  const auth = useAuthStore()
  const fleet = useFleetStore()
  const localView = ref(false)
  const linkedCore = computed(() => auth.mode === 'local' && auth.workstation && auth.coreConnection?.connected
    ? auth.coreConnection : null)
  const waitingForConnection = computed(() => auth.mode === 'local' && auth.workstation && auth.coreConnection === undefined)
  const route = computed<SpaceRouteConfig | null>(previous => {
    if (!auth.token || waitingForConnection.value) return null
    const current = linkedCore.value && !localView.value
      ? fleet.coreWorkspaceRoute : { token: auth.token, origin: getApiBaseUrl() }
    if (!current) return null
    return previous?.origin === current.origin && previous.token === current.token ? previous : current
  })
  const coreSignInRequired = computed(() => !!linkedCore.value && !localView.value && !route.value)
  const apiOrigin = computed(() => route.value?.origin)
  const replica = computed<SpaceReplica | null>(previous => {
    if (!auth.replicaAccount || waitingForConnection.value || localView.value || (!linkedCore.value && auth.mode !== 'core')) return null
    const link = linkedCore.value
    const namespace = JSON.stringify([
      link?.coreUrl ?? getApiBaseUrl(), link?.workspaceId ?? '', auth.replicaAccount,
    ])
    return previous?.namespace === namespace ? previous : new SpaceReplica(namespace)
  })
  const available = computed(() => !!route.value || !!replica.value)
  const queued = ref<SpaceMutation[]>([])
  const offline = ref(false)
  const syncing = ref(false)
  const syncError = ref('')
  const pendingCount = computed(() => queued.value.filter(item => !item.candidateId && !item.error).length)
  const pendingSpaceConflicts = computed(() => queued.value.filter(item => item.candidateId).length)
  const rejected = computed(() => queued.value.filter(item => item.error))
  const conflicts = ref<StandardSpaceConflict[]>([])
  const conflictsLoading = ref(false)
  const conflictError = ref('')
  const legacySpaces = ref(new Set<string>())
  const pinned = ref<Record<string, number>>({})
  let activePush: Promise<void> | null = null
  let listRequest = 0
  let entriesRequest = 0
  let detailRequest = 0
  let sensitiveGeneration = 0

  const capabilities = ref<SpaceCapabilities | null>(null)
  const spaces = ref<SpaceItem[]>([])
  const selectedSpaceId = ref<string>('')
  const entries = ref<SpaceEntrySummary[]>([])
  const selectedEntryId = ref<string>('')
  const selectedEntryDetail = ref<SpaceEntryDetail | null>(null)
  const tokens = ref<SpaceTokenItem[]>([])
  const auditLogs = ref<SpaceAuditLogItem[]>([])
  const lastCreatedToken = ref<SpaceTokenCreated | null>(null)

  // 纯内存敏感内容状态（绝不落盘）
  const unlockedView = ref<UnlockedEntryView | null>(null)
  const decryptedCatalogByEntryId = ref<Record<string, SpaceEntryManifest>>({})
  const activeObjectUrls = new Set<string>()

  const loading = ref(false)
  const error = ref<string>('')

  const selectedSpace = computed(() => spaces.value.find(s => s.id === selectedSpaceId.value) ?? null)
  const selectedEntrySummary = computed(() => entries.value.find(e => e.id === selectedEntryId.value) ?? null)

  function requireRoute(): SpaceRouteConfig {
    if (!route.value) throw new Error(coreSignInRequired.value ? '请先登录 Core 共享空间' : '共享空间连接尚未就绪')
    return route.value
  }

  function checkRoute(target: SpaceRouteConfig, spaceId?: string) {
    if (target !== route.value || (spaceId !== undefined && spaceId !== selectedSpaceId.value)) {
      throw new Error('共享空间已切换，请刷新后查看操作结果。')
    }
  }

  /** 立即清空所有内存中的敏感明文、解密目录、一次性 Token 与 Blob ObjectURL。 */
  function clearSensitiveMemory() {
    sensitiveGeneration++
    unlockedView.value = null
    decryptedCatalogByEntryId.value = {}
    lastCreatedToken.value = null
    if (selectedEntryDetail.value && selectedSpace.value?.tier !== 'standard') {
      selectedEntryDetail.value = {
        ...selectedEntryDetail.value,
        contentText: null,
        contentBase64: null,
        locked: true,
      }
    }
    for (const url of activeObjectUrls) {
      try {
        URL.revokeObjectURL(url)
      } catch {
        // 忽略释放异常
      }
    }
    activeObjectUrls.clear()
  }

  function registerObjectUrl(blob: Blob): string {
    const url = URL.createObjectURL(blob)
    activeObjectUrls.add(url)
    return url
  }

  function reset() {
    listRequest++
    entriesRequest++
    detailRequest++
    clearSensitiveMemory()
    capabilities.value = null
    spaces.value = []
    selectedSpaceId.value = ''
    entries.value = []
    selectedEntryId.value = ''
    selectedEntryDetail.value = null
    tokens.value = []
    auditLogs.value = []
    error.value = ''
    loading.value = false
    queued.value = []
    offline.value = false
    syncError.value = ''
    conflicts.value = []
    conflictsLoading.value = false
    conflictError.value = ''
    legacySpaces.value = new Set<string>()
    pinned.value = {}
    syncing.value = false
  }

  watch(linkedCore, (next, previous) => {
    if (next?.workspaceId !== previous?.workspaceId || next?.coreUrl !== previous?.coreUrl) localView.value = false
  })
  watch(route, reset, { flush: 'sync' })
  watch(replica, reset, { flush: 'sync' })

  async function queueState(target: SpaceReplica) {
    const queue = await target.queue()
    if (replica.value === target) queued.value = queue
    return queue
  }

  function canUseCache(cause: unknown) {
    return cause instanceof ApiError && (cause.status === 0 || cause.status >= 500)
  }

  async function refreshReplica(target: SpaceReplica, connection: SpaceRouteConfig | null) {
    if (target !== replica.value || connection !== route.value) return
    const queue = await queueState(target)
    if (target !== replica.value || connection !== route.value || !connection || !queue.some(item => !item.error)) return
    if (activePush) return activePush
    const current = () => target === replica.value && connection === route.value
    const push = async () => {
      syncing.value = true
      syncError.value = ''
      try {
        const transmit = () => pushSpaceQueue(target, connection, current)
        if (navigator.locks) await navigator.locks.request(`space-sync/${target.namespace}`, { ifAvailable: true }, lock => lock ? transmit() : undefined)
        else await transmit()
        if (current()) offline.value = false
      } catch (cause) {
        if (current()) {
          offline.value = canUseCache(cause)
          syncError.value = cause instanceof Error ? cause.message : '共享空间同步失败'
        }
      } finally {
        if (current()) {
          syncing.value = false
          await queueState(target)
        }
      }
    }
    activePush = push().finally(() => { activePush = null })
    return activePush
  }

  async function syncPending() {
    const target = replica.value
    if (!target) return
    try { await refreshReplica(target, route.value) }
    catch (cause) {
      if (replica.value === target) syncError.value = cause instanceof Error ? cause.message : '无法访问共享空间本地副本'
    }
  }

  async function retrySpaceQueue() {
    const target = replica.value
    if (!target) return
    try {
      await target.changeQueue(items => items.map(item => ({ ...item, error: undefined })))
      if (target !== replica.value) return
      await syncPending()
      await loadSpaces()
      await refreshCurrentSpace()
    } catch (cause) {
      if (target === replica.value) syncError.value = cause instanceof Error ? cause.message : '重试同步失败'
    }
  }

  async function loadSpaces() {
    const target = route.value
    const local = replica.value
    if (!target && !local) return
    const request = ++listRequest
    loading.value = true
    error.value = ''
    try {
      let data: { caps: SpaceCapabilities; list: SpaceItem[] } | undefined
      try {
        if (target) {
          const [caps, list] = await Promise.all([fetchSpaceCapabilities(target), fetchSpaces(target)])
          data = { caps, list }
          if (local) await local.write('catalog', { caps, list: list.filter(space => space.tier === 'standard') })
          if (target === route.value) offline.value = false
        }
      } catch (cause) {
        if (!local || !canUseCache(cause)) throw cause
      }
      if (!data && local) {
        data = await local.read('catalog')
        const saved = await local.pinned()
        if (data) data.list.push(...new Map(saved.map(item => [item.space.id, item.space])).values())
        if (local === replica.value) offline.value = true
      }
      if (!data) throw new Error('请先联网打开共享空间，之后才能离线使用。')
      const { caps, list } = data
      if (request !== listRequest || target !== route.value) return
      capabilities.value = caps
      spaces.value = list
      if (selectedSpaceId.value && !list.some(s => s.id === selectedSpaceId.value)) {
        await selectSpace(list[0]?.id ?? '')
      } else if (!selectedSpaceId.value && list.length > 0) {
        await selectSpace(list[0]!.id)
      }
    } catch (cause) {
      if (request === listRequest) error.value = cause instanceof Error ? cause.message : '加载共享空间失败'
    } finally {
      if (request === listRequest) loading.value = false
    }
  }

  async function selectSpace(spaceId: string) {
    clearSensitiveMemory()
    selectedSpaceId.value = spaceId
    selectedEntryId.value = ''
    selectedEntryDetail.value = null
    entries.value = []
    tokens.value = []
    auditLogs.value = []
    conflicts.value = []
    conflictError.value = ''
    if (!spaceId) return
    await refreshCurrentSpace()
  }

  async function refreshCurrentSpace(search?: string, entryType?: string) {
    const target = route.value
    const space = selectedSpace.value
    if (!space) return
    const local = space.tier === 'standard' ? replica.value : null
    const encryptedReplica = space.tier === 'e2ee' ? replica.value : null
    if (!target && !local && !encryptedReplica) return
    const request = ++entriesRequest
    loading.value = true
    error.value = ''
    try {
      let list: SpaceEntrySummary[] | undefined
      try {
        if (target) {
          if (local) {
            const result = await pullStandardSpace(local, target, space.id)
            list = result.entries
            if (target === route.value) {
              if (result.supported) legacySpaces.value.delete(space.id)
              else legacySpaces.value.add(space.id)
              offline.value = false
            }
          } else list = await fetchSpaceEntries(target, space.id, { search, entryType })
        }
      } catch (cause) {
        if (!(local || encryptedReplica) || !canUseCache(cause)) throw cause
        if (target === route.value) offline.value = true
      }
      if (local) {
        list ??= (await local.read<StandardSpaceSnapshot>(`snapshot/${space.id}`))?.entries ?? []
        const rows = new Map(list.map(entry => [entry.id, entry]))
        for (const mutation of await queueState(local)) {
          if (mutation.spaceId !== space.id) continue
          if (mutation.operation === 'delete') rows.delete(mutation.entryId)
          else rows.set(mutation.entryId, { ...mutation.draft, hasConflict: !!mutation.candidateId })
        }
        const term = search?.trim().toLowerCase()
        list = [...rows.values()].filter(entry => (!entryType || entry.entryType === entryType) &&
          (!term || [entry.title, entry.fileName, ...entry.tags].some(value => value?.toLowerCase().includes(term))))
      }
      if (request !== entriesRequest || selectedSpaceId.value !== space.id) return
      if (encryptedReplica) {
        const files = await encryptedReplica.pinned(space.id)
        if (request !== entriesRequest || selectedSpaceId.value !== space.id) return
        list ??= files.map(item => item.detail)
        pinned.value = Object.fromEntries(files.map(item => [item.detail.id, item.detail.revision]))
      } else pinned.value = {}
      entries.value = list ?? []
      if (space && space.tier === 'e2ee') {
        recordHighestEpoch(space.id, space.activeEpoch)
      }
      if (selectedEntryId.value && entries.value.some(e => e.id === selectedEntryId.value)) {
        await selectEntry(selectedEntryId.value)
      } else {
        selectedEntryId.value = ''
        selectedEntryDetail.value = null
      }
    } catch (cause) {
      if (request === entriesRequest && selectedSpaceId.value === space.id) error.value = cause instanceof Error ? cause.message : '加载条目失败'
    } finally {
      if (request === entriesRequest) loading.value = false
    }
  }

  async function selectEntry(entryId: string) {
    const request = ++detailRequest
    clearSensitiveMemory()
    selectedEntryId.value = entryId
    selectedEntryDetail.value = null
    const target = route.value
    const spaceId = selectedSpaceId.value
    const local = selectedSpace.value?.tier === 'standard' ? replica.value : null
    const encryptedReplica = selectedSpace.value?.tier === 'e2ee' ? replica.value : null
    if (!entryId || !spaceId || (!target && !local && !encryptedReplica)) return
    try {
      const key = `detail/${spaceId}/${entryId}`
      const pending = local ? [...await queueState(local)].reverse().find(item => item.spaceId === spaceId && item.entryId === entryId) : undefined
      let detail = pending && pending.operation !== 'delete' ? pending.draft : undefined
      if (!detail && target) {
        try {
          detail = await fetchSpaceEntryDetail(target, spaceId, entryId)
          if (local) await local.write(key, detail)
        } catch (cause) {
          if (!(local || encryptedReplica) || !canUseCache(cause)) throw cause
        }
      }
      if (!detail && local) detail = await local.read<SpaceEntryDetail>(key)
      if (!detail && encryptedReplica) detail = (await encryptedReplica.read<PinnedCiphertext>(`e2ee/${spaceId}/${entryId}`))?.detail
      if (request === detailRequest && selectedSpaceId.value === spaceId && selectedEntryId.value === entryId) {
        selectedEntryDetail.value = detail ?? null
        if (!detail) error.value = '这个条目的内容尚未下载，请联网打开一次。'
      }
    } catch (cause) {
      if (request === detailRequest && selectedEntryId.value === entryId) error.value = cause instanceof Error ? cause.message : '加载条目详情失败'
    }
  }

  async function createSpace(input: {
    name: string
    description?: string
    tier: SpaceTier
    password?: string
    workspaceId?: string
  }): Promise<SpaceItem> {
    const route = requireRoute()
    let created: SpaceItem
    if (input.tier === 'e2ee') {
      if (!input.password || input.password.length < 8) {
        throw new Error('极密空间密码至少需要 8 位字符')
      }
      const workspaceId = input.workspaceId ?? spaces.value[0]?.workspaceId ?? await fetchWorkspaceId(route)
      const spaceId = crypto.randomUUID()
      const spaceKey = randomBytes(KEY_BYTES)
      try {
        const envelope = await wrapSpaceKey({
          password: input.password,
          spaceKey,
          workspaceId,
          spaceId,
          epoch: 1,
        })
        created = await createSpaceApi(route, {
          id: spaceId,
          name: input.name,
          description: input.description,
          tier: 'e2ee',
          envelope,
        })
        recordHighestEpoch(created.id, created.activeEpoch)
      } finally {
        zeroizeBytes(spaceKey)
      }
    } else {
      created = await createSpaceApi(route, {
        name: input.name,
        description: input.description,
        tier: input.tier,
        password: input.tier === 'protected' ? input.password : undefined,
      })
    }
    checkRoute(route)
    spaces.value = [created, ...spaces.value]
    await selectSpace(created.id)
    return created
  }

  async function fetchWorkspaceId(route: SpaceRouteConfig): Promise<string> {
    const ws = await apiRequest<{ id: string }>('/api/v1/workspace', {}, route.token, route.origin)
    return ws.id
  }

  async function archiveSpace(spaceId: string) {
    const route = requireRoute()
    if ((await replica.value?.queue())?.some(item => item.spaceId === spaceId)) throw new Error('该空间还有待同步修改或冲突，请处理后再归档。')
    await archiveSpaceApi(route, spaceId)
    checkRoute(route)
    clearSensitiveMemory()
    spaces.value = spaces.value.filter(s => s.id !== spaceId)
    if (selectedSpaceId.value === spaceId) {
      await selectSpace(spaces.value[0]?.id ?? '')
    }
  }

  async function importLocalStandardSpaces() {
    const target = requireRoute()
    const local = replica.value
    const localToken = auth.token
    if (!linkedCore.value || localView.value || !localToken || !local) throw new Error('请先登录已配对的 Core。')
    const source = { token: localToken, origin: getApiBaseUrl() }
    const current = () => target === route.value && local === replica.value && localToken === auth.token
    const [localSpaces, coreSpaces] = await Promise.all([fetchSpaces(source), fetchSpaces(target)])
    const destination = new Map(coreSpaces.map(space => [space.id, space]))
    let added = 0
    for (const space of localSpaces.filter(item => item.tier === 'standard')) {
      if (!current()) throw new Error('工作区已切换，已加入的条目会保留。')
      const existing = destination.get(space.id)
      if (existing && existing.tier !== 'standard') throw new Error('Core 中存在同 ID 的其他类型空间。')
      if (!existing) {
        try { await createSpaceApi(target, { id: space.id, name: space.name, description: space.description, tier: 'standard' }) }
        catch (cause) {
          if (!(cause instanceof ApiError) || cause.status !== 409 || !(await fetchSpaces(target)).some(item => item.id === space.id && item.tier === 'standard')) throw cause
        }
      }
      const [sourceEntries, coreEntries] = await Promise.all([fetchSpaceEntries(source, space.id), fetchSpaceEntries(target, space.id)])
      const remoteIds = new Set(coreEntries.map(entry => entry.id))
      for (const entry of sourceEntries) {
        if (!current()) throw new Error('工作区已切换，已加入的条目会保留。')
        if (remoteIds.has(entry.id)) continue
        const detail = await fetchSpaceEntryDetail(source, space.id, entry.id)
        const file = detail.entryType === 'file' ? await downloadEntryBlob(source, space.id, detail.id, undefined, detail.revision) : undefined
        if (!current()) throw new Error('工作区已切换，已加入的条目会保留。')
        const mutation: SpaceMutation = { ...newIntent(detail), id: detail.id, operation: 'create', file,
          draft: { ...detail, revision: 0, currentRevision: 0, contentBase64: null, blobId: null } }
        let enqueued = false
        await local.changeQueue(queue => {
          if (queue.some(item => item.id === mutation.id)) return queue
          enqueued = true
          return [...queue, mutation]
        })
        if (enqueued) added++
      }
    }
    if (current()) {
      await loadSpaces()
      void syncPending().then(() => { if (current()) void refreshCurrentSpace() })
    }
    return added
  }

  /** 创建条目（自动适配 standard / protected / e2ee 三档）。 */
  async function createEntry(input: {
    entryType: SpaceEntryType
    title: string
    fileName?: string
    mime?: string
    tags?: string[]
    contentText?: string
    file?: File
    password?: string
  }): Promise<SpaceEntryDetail> {
    const space = selectedSpace.value
    if (!space) throw new Error('请先选择一个共享空间')

    const mime = input.file?.type || input.mime || (input.entryType === 'file' ? 'application/octet-stream' : 'text/plain')
    const fileName = input.file?.name || input.fileName
    const local = space.tier === 'standard' ? replica.value : null
    if (local) {
      const time = new Date().toISOString()
      const title = input.title.trim()
      const contentText = input.contentText ?? ''
      const sizeBytes = input.file?.size ?? TEXT_ENCODER.encode(contentText).length
      if (!title || title.length > 200) throw new Error('请输入 1–200 字的条目标题。')
      if (capabilities.value && sizeBytes > capabilities.value.maxFileBytes) throw new Error('条目大小超过共享空间上限。')
      const id = crypto.randomUUID()
      const draft: SpaceEntryDetail = {
        id, spaceId: space.id, tier: 'standard', entryType: input.entryType, title, fileName: fileName ?? null,
        mime, tags: [...(input.tags ?? [])], sizeBytes, createdAt: time, updatedAt: time, deletedAt: null,
        epoch: 1, activeEpoch: 1, currentRevision: 0, revision: 0, hasConflict: false, contentText,
        locked: false, contentBase64: null, contentSha256: '', conflictRevisions: [], wrappedDek: null,
        encryptedManifestB64: null, blobId: null, chunkCount: 0, chunkSize: DEFAULT_CHUNK_SIZE,
      }
      await saveStandardIntent(local, { ...newIntent(draft), operation: 'create', draft, file: input.file })
      return draft
    }

    const route = requireRoute()
    const rawBytes = input.file
      ? new Uint8Array(await input.file.arrayBuffer())
      : TEXT_ENCODER.encode(input.contentText ?? '')

    if (space.tier === 'e2ee') {
      if (!input.password) throw new Error('请输入极密空间密码以加密保存')
      const envRes = await fetchSpaceEnvelope(route, space.id)
      recordHighestEpoch(space.id, envRes.epoch)
      const spaceKey = await unwrapSpaceKey({
        password: input.password,
        envelope: envRes.envelope,
        workspaceId: space.workspaceId,
        spaceId: space.id,
        expectedEpoch: envRes.epoch,
      })
      const entryId = crypto.randomUUID()
      const dek = randomBytes(KEY_BYTES)
      try {
        const scope = {
          workspaceId: space.workspaceId,
          spaceId: space.id,
          entryId,
          revision: 1,
          epoch: envRes.epoch,
        }
        const chunkSize = DEFAULT_CHUNK_SIZE
        const chunks: Uint8Array[] = []
        for (let offset = 0; offset < rawBytes.byteLength; offset += chunkSize) {
          chunks.push(rawBytes.subarray(offset, Math.min(offset + chunkSize, rawBytes.byteLength)))
        }
        if (chunks.length === 0) chunks.push(new Uint8Array(0))

        const encryptedChunks: Array<{ bytes: Uint8Array<ArrayBuffer>; sha256: string }> = []
        let totalCipherSize = 0
        for (let i = 0; i < chunks.length; i += 1) {
          const ct = await encryptChunk({ dek, plaintext: chunks[i]!, scope, chunkIndex: i })
          const digest = await sha256Hex(ct)
          encryptedChunks.push({ bytes: ct, sha256: digest })
          totalCipherSize += ct.byteLength
        }

        const blob = await initSpaceBlob(route, space.id, {
          chunkSize,
          chunkCount: encryptedChunks.length,
          totalSize: totalCipherSize,
        })
        for (let i = 0; i < encryptedChunks.length; i += 1) {
          await uploadSpaceBlobChunk(
            route,
            space.id,
            blob.id,
            i,
            encryptedChunks[i]!.bytes,
            encryptedChunks[i]!.sha256,
          )
        }

        const noteSummary = input.entryType === 'file' ? (input.contentText?.trim() || undefined) : undefined
        const manifest: SpaceEntryManifest = {
          version: 1,
          entryType: input.entryType,
          title: input.title.trim(),
          fileName,
          mime,
          sizeBytes: rawBytes.byteLength,
          chunkCount: encryptedChunks.length,
          chunkSize,
          plaintextSha256: await sha256Hex(rawBytes),
          tags: input.tags ?? [],
          summary: noteSummary,
        }
        const wrappedDek = await wrapDek({ wrappingKey: spaceKey, dek, scope })
        const encryptedManifestB64 = await encryptManifest({ dek, manifest, scope })
        const created = await createSpaceEntryApi(route, space.id, {
          id: entryId,
          entryType: input.entryType,
          mutationId: crypto.randomUUID(),
          epoch: envRes.epoch,
          wrappedDek,
          encryptedManifestB64,
          blobId: blob.id,
          plaintextSize: rawBytes.byteLength,
          contentSha256: encryptedChunks[0]?.sha256 ?? '',
        })
        checkRoute(route, space.id)
        await refreshCurrentSpace()
        checkRoute(route, space.id)
        selectedEntryId.value = created.id
        selectedEntryDetail.value = created
        return created
      } finally {
        zeroizeBytes(spaceKey, dek)
      }
    }

    const payload: Record<string, unknown> = {
      entryType: input.entryType,
      mutationId: crypto.randomUUID(),
      title: input.title.trim(),
      fileName,
      mime,
      tags: input.tags ?? [],
    }
    if (input.file) {
      payload.contentBase64 = bytesToBase64(rawBytes)
      const fileNote = input.contentText?.trim()
      if (fileNote) {
        payload.contentText = fileNote
      }
    } else {
      payload.contentText = input.contentText ?? ''
    }
    if (space.tier === 'protected') {
      if (!input.password) throw new Error('请输入受控机密空间密码以保存')
      payload.password = input.password
    }
    const created = await createSpaceEntryApi(route, space.id, payload)
    checkRoute(route, space.id)
    await refreshCurrentSpace()
    checkRoute(route, space.id)
    selectedEntryId.value = created.id
    selectedEntryDetail.value = created
    return created
  }

  /** 按次输入密码解密 E2EE 当前目录（仅驻留内存，离页即清）。 */
  async function decryptE2eeCatalogWithPassword(password: string) {
    const space = selectedSpace.value
    if (!space || space.tier !== 'e2ee') return
    const generation = sensitiveGeneration
    const target = route.value
    const saved = await replica.value?.pinned(space.id) ?? []

    const envCache = new Map<number, Uint8Array<ArrayBuffer>>()
    const nextCatalog: Record<string, SpaceEntryManifest> = {}
    try {
      for (const item of entries.value) {
        if (!item.wrappedDek || !item.encryptedManifestB64) continue
        const ep = item.activeEpoch
        let spaceKey = envCache.get(ep)
        if (!spaceKey) {
          const envRes = await envelopeForRead(target, space.id, ep, saved.find(row => row.envelope.epoch === ep)?.envelope)
          if (ep === space.activeEpoch) recordHighestEpoch(space.id, envRes.epoch)
          spaceKey = await unwrapSpaceKey({
            password,
            envelope: envRes.envelope,
            workspaceId: space.workspaceId,
            spaceId: space.id,
            expectedEpoch: ep,
          })
          envCache.set(ep, spaceKey)
        }
        const scope = {
          workspaceId: space.workspaceId,
          spaceId: space.id,
          entryId: item.id,
          revision: item.currentRevision,
          epoch: ep,
        }
        const dek = await unwrapDek({ wrappingKey: spaceKey, wrappedDek: item.wrappedDek, scope })
        try {
          nextCatalog[item.id] = await decryptManifest({
            dek,
            encryptedManifestB64: item.encryptedManifestB64,
            scope,
          })
        } finally {
          zeroizeBytes(dek)
        }
      }
      if (generation !== sensitiveGeneration || selectedSpace.value?.id !== space.id) throw new Error('共享空间已切换，请重新解锁。')
      decryptedCatalogByEntryId.value = nextCatalog
    } finally {
      for (const k of envCache.values()) zeroizeBytes(k)
      envCache.clear()
    }
  }

  /** 按次输入密码解锁查看单条 protected 或 e2ee 条目。 */
  async function unlockCurrentEntryWithPassword(password: string, revision?: number): Promise<UnlockedEntryView> {
    const space = selectedSpace.value
    const entry = selectedEntryDetail.value
    if (!space || !entry) throw new Error('未选择条目')
    const generation = sensitiveGeneration
    const target = route.value
    const current = () => generation === sensitiveGeneration && selectedEntryDetail.value?.id === entry.id && selectedSpace.value?.id === space.id

    if (space.tier === 'protected') {
      const unlocked = await unlockProtectedEntryApi(requireRoute(), space.id, entry.id, password, revision)
      if (!current()) throw new Error('共享空间已切换，请重新解锁。')
      let fileBlob: Blob | undefined
      if (unlocked.entryType === 'file' && unlocked.contentBase64) {
        const bin = atob(unlocked.contentBase64)
        const bytes = new Uint8Array(bin.length)
        for (let i = 0; i < bin.length; i += 1) bytes[i] = bin.charCodeAt(i)
        fileBlob = new Blob([bytes], { type: unlocked.mime })
      }
      const view: UnlockedEntryView = {
        entryId: unlocked.id,
        revision: unlocked.revision,
        contentText: unlocked.contentText,
        fileBlob,
        fileName: unlocked.fileName ?? unlocked.title ?? unlocked.id,
        mime: unlocked.mime,
        unlockedAt: Date.now(),
      }
      unlockedView.value = view
      return view
    }

    if (space.tier === 'e2ee') {
      const targetDetail = revision && revision !== entry.revision
        ? await fetchSpaceEntryDetail(requireRoute(), space.id, entry.id, revision)
        : entry
      if (!targetDetail.wrappedDek || !targetDetail.encryptedManifestB64) {
        throw new Error('该条目缺少加密封套元数据')
      }
      const saved = await replica.value?.read<PinnedCiphertext>(`e2ee/${space.id}/${entry.id}`)
      const matching = saved?.detail.revision === targetDetail.revision && saved.detail.epoch === targetDetail.epoch ? saved : undefined
      const envRes = await envelopeForRead(target, space.id, targetDetail.epoch, matching?.envelope)
      if (targetDetail.epoch === space.activeEpoch) recordHighestEpoch(space.id, envRes.epoch)
      const spaceKey = await unwrapSpaceKey({
        password,
        envelope: envRes.envelope,
        workspaceId: space.workspaceId,
        spaceId: space.id,
        expectedEpoch: targetDetail.epoch,
      })
      const scope = {
        workspaceId: space.workspaceId,
        spaceId: space.id,
        entryId: targetDetail.id,
        revision: targetDetail.revision,
        epoch: targetDetail.epoch,
      }
      let dek: Uint8Array<ArrayBuffer> | undefined
      let merged: Uint8Array<ArrayBuffer> | undefined
      const plainChunks: Uint8Array[] = []
      try {
        dek = await unwrapDek({ wrappingKey: spaceKey, wrappedDek: targetDetail.wrappedDek, scope })
        const manifest = await decryptManifest({
          dek,
          encryptedManifestB64: targetDetail.encryptedManifestB64,
          scope,
        })
        let totalLen = 0
        if (targetDetail.blobId && targetDetail.chunkCount > 0) {
          for (let i = 0; i < targetDetail.chunkCount; i += 1) {
            if (!current()) throw new Error('共享空间已切换，请重新解锁。')
            const cached = matching?.chunks[i]
            if (!cached && !target) throw new Error('密文未下载，请联网后保存离线副本。')
            const ct = cached ? new Uint8Array(await cached.arrayBuffer()) : await downloadSpaceBlobChunk(target!, space.id, targetDetail.blobId, i)
            const pt = await decryptChunk({ dek, ciphertextChunk: ct, scope, chunkIndex: i })
            plainChunks.push(pt)
            totalLen += pt.byteLength
          }
        }
        merged = new Uint8Array(totalLen)
        let offset = 0
        for (const chunk of plainChunks) {
          merged.set(chunk, offset)
          offset += chunk.byteLength
          zeroizeBytes(chunk)
        }
        const actualSha = await sha256Hex(merged)
        if (manifest.plaintextSha256 && actualSha !== manifest.plaintextSha256) {
          zeroizeBytes(merged)
          throw new Error('解密后内容摘要不匹配，文件可能已损坏')
        }
        const isFile = manifest.entryType === 'file'
        const view: UnlockedEntryView = {
          entryId: targetDetail.id,
          revision: targetDetail.revision,
          manifest,
          contentText: isFile ? (manifest.summary?.trim() || null) : TEXT_DECODER.decode(merged),
          fileBlob: isFile ? new Blob([merged], { type: manifest.mime }) : undefined,
          fileName: manifest.fileName ?? manifest.title,
          mime: manifest.mime,
          unlockedAt: Date.now(),
        }
        zeroizeBytes(merged)
        decryptedCatalogByEntryId.value = {
          ...decryptedCatalogByEntryId.value,
          [targetDetail.id]: manifest,
        }
        if (!current()) throw new Error('共享空间已切换，请重新解锁。')
        unlockedView.value = view
        return view
      } finally {
        zeroizeBytes(spaceKey, dek, merged, ...plainChunks)
      }
    }

    throw new Error('普通共享空间无需输密解锁')
  }

  async function envelopeForRead(target: SpaceRouteConfig | null, spaceId: string, epoch: number, cached?: SpaceEnvelopeResponse) {
    if (target) {
      try { return await fetchSpaceEnvelope(target, spaceId, epoch) }
      catch (cause) { if (!cached || !canUseCache(cause)) throw cause }
    }
    if (!cached) throw new Error('未下载此密钥封套，请联网后保存离线副本。')
    return cached
  }

  async function pinEncryptedEntry() {
    const local = replica.value
    const target = requireRoute()
    const space = selectedSpace.value
    const entry = selectedEntryDetail.value
    if (!local || space?.tier !== 'e2ee' || !entry) return
    const detail = await fetchSpaceEntryDetail(target, space.id, entry.id)
    if (detail.tier !== 'e2ee' || !detail.wrappedDek || !detail.encryptedManifestB64) throw new Error('Core 未返回可保存的密文。')
    const envelope = await fetchSpaceEnvelope(target, space.id, detail.epoch)
    const chunks: Blob[] = []
    if (detail.blobId) {
      for (let i = 0; i < detail.chunkCount; i++) {
        if (local !== replica.value || target !== route.value) throw new Error('工作区已切换。')
        const bytes = await downloadSpaceBlobChunk(target, space.id, detail.blobId, i)
        chunks.push(new Blob([bytes]))
      }
    }
    if (local !== replica.value || target !== route.value) throw new Error('工作区已切换。')
    await local.write<PinnedCiphertext>(`e2ee/${space.id}/${entry.id}`, {
      space: { ...space }, envelope, chunks,
      detail: { ...detail, title: null, fileName: null, mime: 'application/octet-stream', tags: [], contentText: null, contentBase64: null, contentSha256: '', locked: true },
    })
    if (local === replica.value && selectedSpaceId.value === space.id) pinned.value[entry.id] = detail.revision
  }

  async function unpinEncryptedEntry(entryId: string) {
    const local = replica.value
    const spaceId = selectedSpaceId.value
    if (!local || !spaceId) return
    await local.unpin(spaceId, entryId)
    if (local !== replica.value || spaceId !== selectedSpaceId.value) return
    delete pinned.value[entryId]
    if (offline.value) await refreshCurrentSpace()
  }

  async function downloadStandardEntry(entry: SpaceEntryDetail) {
    const local = replica.value
    const target = route.value
    const key = `file/${entry.spaceId}/${entry.id}/${entry.blobId ?? entry.revision}`
    let blob = local ? await local.read<Blob>(key) : undefined
    if (!blob && local && entry.revision === 0) {
      const create = (await local.queue()).find(item => item.operation === 'create' && item.entryId === entry.id)
      if (create?.operation === 'create') blob = create.file
    }
    if (!blob && entry.entryType !== 'file') blob = new Blob([entry.contentText ?? ''], { type: entry.mime })
    if (!blob) {
      if (!target) throw new Error('该文件尚未下载，请联网后打开。')
      try { blob = await downloadEntryBlob(target, entry.spaceId, entry.id, undefined, entry.revision) }
      catch (cause) {
        if (local && canUseCache(cause)) throw new Error('该文件尚未下载，请联网后打开。')
        throw cause
      }
      if (local) await local.write(key, blob)
    }
    if (target !== route.value || local !== replica.value) return
    const url = registerObjectUrl(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = entry.fileName || `${entry.title || entry.id}.txt`
    a.click()
  }

  async function updateStandardEntry(entry: SpaceEntryDetail, nextTitle: string, nextText: string, nextTags: string[]) {
    const local = replica.value
    if (local && entry.tier === 'standard' && !legacySpaces.value.has(entry.spaceId)) {
      const edit = { title: nextTitle.trim(), contentText: nextText, tags: [...nextTags] }
      if (!edit.title || edit.title.length > 200) throw new Error('请输入 1–200 字的条目标题。')
      const draft: SpaceEntryDetail = { ...entry, ...edit, updatedAt: new Date().toISOString() }
      await saveStandardIntent(local, { ...newIntent(entry), operation: 'edit', baseRevision: entry.currentRevision, edit, draft })
      return
    }
    const route = requireRoute()
    const updated = await updateSpaceEntryApi(route, entry.spaceId, entry.id, {
      baseRevision: entry.currentRevision,
      mutationId: crypto.randomUUID(),
      title: nextTitle,
      contentText: nextText,
      tags: nextTags,
    })
    checkRoute(route, entry.spaceId)
    await refreshCurrentSpace()
    checkRoute(route, entry.spaceId)
    selectedEntryId.value = updated.id
    selectedEntryDetail.value = updated
  }

  async function deleteCurrentEntry() {
    if (!selectedSpaceId.value || !selectedEntryId.value) return
    const local = replica.value
    const entry = selectedEntryDetail.value
    if (local && entry?.tier === 'standard' && !legacySpaces.value.has(entry.spaceId)) {
      await saveStandardIntent(local, { ...newIntent(entry), operation: 'delete', baseRevision: entry.currentRevision })
      return
    }
    const route = requireRoute()
    const spaceId = selectedSpaceId.value
    const entryId = selectedEntryId.value
    await deleteSpaceEntryApi(route, spaceId, entryId)
    checkRoute(route, spaceId)
    if (selectedEntryId.value !== entryId) return
    clearSensitiveMemory()
    selectedEntryId.value = ''
    selectedEntryDetail.value = null
    await refreshCurrentSpace()
  }

  function newIntent(entry: SpaceEntryDetail) {
    const connection = auth.coreConnection?.connected ? auth.coreConnection : null
    const identity = connection && (linkedCore.value || connection.coreUrl === apiOrigin.value) ? connection : null
    const platform = desktopPlatform()
    const label = identity ? identity.clientName
      : { windows: 'Windows', macos: 'macOS', linux: 'Linux', android: 'Android', web: '浏览器' }[platform]
    return {
      id: crypto.randomUUID(), spaceId: entry.spaceId, entryId: entry.id,
      deviceLabel: label.slice(0, 120),
    }
  }

  async function saveStandardIntent(local: SpaceReplica, mutation: SpaceMutation) {
    // Vue wraps displayed records in proxies, while IndexedDB needs cloneable values.
    const record = mutation.operation === 'delete' ? mutation
      : { ...mutation, draft: JSON.parse(JSON.stringify(mutation.draft)) as SpaceEntryDetail }
    await local.enqueue(record)
    if (local !== replica.value || mutation.spaceId !== selectedSpaceId.value) return
    await queueState(local)
    if (mutation.operation === 'delete') {
      entries.value = entries.value.filter(item => item.id !== mutation.entryId)
      selectedEntryId.value = ''
      selectedEntryDetail.value = null
    } else {
      entries.value = [mutation.draft, ...entries.value.filter(item => item.id !== mutation.entryId)]
      selectedEntryId.value = mutation.entryId
      selectedEntryDetail.value = mutation.draft
    }
    void syncPending().then(() => {
      if (local === replica.value && mutation.spaceId === selectedSpaceId.value && !offline.value) void refreshCurrentSpace()
    })
  }

  async function loadConflicts() {
    const target = route.value
    const space = selectedSpace.value
    conflicts.value = []
    conflictError.value = ''
    if (!target || space?.tier !== 'standard') return
    conflictsLoading.value = true
    try {
      const items = await fetchStandardSpaceConflicts(target, space.id)
      if (target === route.value && space.id === selectedSpaceId.value) conflicts.value = items
    } catch (cause) {
      if (target === route.value && space.id === selectedSpaceId.value) {
        conflictError.value = cause instanceof Error ? cause.message : '无法读取 Core 的冲突列表'
      }
    } finally {
      if (target === route.value && space.id === selectedSpaceId.value) conflictsLoading.value = false
    }
  }

  async function resolveConflict(candidate: StandardSpaceConflict, strategy: 'core' | 'candidate') {
    const target = requireRoute()
    const spaceId = candidate.current.spaceId
    await resolveStandardSpaceConflict(target, spaceId, candidate, strategy)
    if (target !== route.value || spaceId !== selectedSpaceId.value) return
    await syncPending()
    await Promise.all([loadConflicts(), refreshCurrentSpace()])
  }

  async function loadTokensAndAudit() {
    const spaceId = selectedSpaceId.value
    const target = route.value
    if (!spaceId || !target || offline.value) return
    const current = () => target === route.value && spaceId === selectedSpaceId.value
    try {
      const [tks, logs] = await Promise.all([fetchSpaceTokens(target, spaceId), fetchSpaceAuditLogs(target, spaceId)])
      if (!current()) return
      tokens.value = tks
      auditLogs.value = logs
    } catch (cause) {
      if (current()) error.value = cause instanceof Error ? cause.message : '无法读取空间管理数据'
    }
  }

  async function issueToken(input: {
    name: string
    scopes: SpaceTokenScope[]
    entryIds?: string[] | null
    expiresInDays?: number | null
    password?: string
  }): Promise<SpaceTokenCreated> {
    const spaceId = selectedSpaceId.value
    if (!spaceId) throw new Error('未选择空间')
    const route = requireRoute()
    const generation = sensitiveGeneration
    const created = await createSpaceTokenApi(route, spaceId, input)
    checkRoute(route, spaceId)
    if (generation !== sensitiveGeneration) throw new Error('页面已锁定。请到 Token 列表检查签发结果。')
    lastCreatedToken.value = created
    await loadTokensAndAudit()
    return created
  }

  async function revokeToken(tokenId: string) {
    const spaceId = selectedSpaceId.value
    if (!spaceId) return
    const route = requireRoute()
    await revokeSpaceTokenApi(route, spaceId, tokenId)
    checkRoute(route, spaceId)
    await loadTokensAndAudit()
  }

  async function changeSpacePassword(oldPassword: string, newPassword: string) {
    const route = requireRoute()
    const space = selectedSpace.value
    if (!space) throw new Error('未选择空间')
    if (space.tier === 'protected') {
      const updated = await changeProtectedPasswordApi(route, space.id, { oldPassword, newPassword })
      checkRoute(route, space.id)
      spaces.value = spaces.value.map(s => (s.id === updated.id ? updated : s))
      return
    }
    if (space.tier === 'e2ee') {
      const currentEnv = await fetchSpaceEnvelope(route, space.id)
      recordHighestEpoch(space.id, currentEnv.epoch)
      const rewrapped = await rewrapEnvelopeForPasswordChange({
        oldPassword,
        newPassword,
        currentEnvelope: currentEnv.envelope,
        workspaceId: space.workspaceId,
        spaceId: space.id,
      })
      const saved = await updateSpaceEnvelopeCas(route, space.id, {
        expectedEnvelopeVersion: currentEnv.envelopeVersion,
        envelope: rewrapped,
      })
      checkRoute(route, space.id)
      spaces.value = spaces.value.map(s =>
        s.id === space.id ? { ...s, envelopeVersion: saved.envelopeVersion } : s,
      )
      return
    }
    throw new Error('普通空间没有访问密码')
  }

  async function rotateE2eeEpoch(newPassword: string) {
    const route = requireRoute()
    const space = selectedSpace.value
    if (!space || space.tier !== 'e2ee') throw new Error('仅极密 E2EE 空间支持 Epoch 密钥轮换')
    const rotated = await createRotatedEpochEnvelope({
      newPassword,
      workspaceId: space.workspaceId,
      spaceId: space.id,
      currentEpoch: space.activeEpoch,
    })
    try {
      const saved = await rotateSpaceEpochApi(route, space.id, {
        expectedActiveEpoch: space.activeEpoch,
        envelope: rotated.envelope,
      })
      checkRoute(route, space.id)
      recordHighestEpoch(space.id, saved.epoch)
      spaces.value = spaces.value.map(s =>
        s.id === space.id ? { ...s, activeEpoch: saved.epoch, envelopeVersion: saved.envelopeVersion } : s,
      )
      clearSensitiveMemory()
    } finally {
      zeroizeBytes(rotated.nextSpaceKey)
    }
  }

  return {
    route,
    available,
    linkedCore,
    localView,
    coreSignInRequired,
    waitingForConnection,
    apiOrigin,
    offline,
    syncing,
    syncError,
    pendingCount,
    pendingSpaceConflicts,
    usingReplica: computed(() => !!replica.value),
    rejected,
    conflicts,
    conflictsLoading,
    conflictError,
    pinned,
    canPinEncrypted: computed(() => !!replica.value && !!route.value && !offline.value),
    pinEncryptedEntry,
    unpinEncryptedEntry,
    loadConflicts,
    resolveConflict,
    syncPending,
    retrySpaceQueue,
    capabilities,
    spaces,
    selectedSpaceId,
    selectedSpace,
    entries,
    selectedEntryId,
    selectedEntrySummary,
    selectedEntryDetail,
    tokens,
    auditLogs,
    lastCreatedToken,
    unlockedView,
    decryptedCatalogByEntryId,
    loading,
    error,
    clearSensitiveMemory,
    registerObjectUrl,
    reset,
    loadSpaces,
    selectSpace,
    refreshCurrentSpace,
    selectEntry,
    createSpace,
    archiveSpace,
    importLocalStandardSpaces,
    createEntry,
    decryptE2eeCatalogWithPassword,
    unlockCurrentEntryWithPassword,
    downloadStandardEntry,
    updateStandardEntry,
    deleteCurrentEntry,
    loadTokensAndAudit,
    issueToken,
    revokeToken,
    changeSpacePassword,
    rotateE2eeEpoch,
  }
})
