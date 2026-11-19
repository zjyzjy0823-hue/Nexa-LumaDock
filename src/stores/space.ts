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
import { computed, ref } from 'vue'
import { apiRequest } from '../api/client'
import { useAuthStore } from './auth'
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
  initSpaceBlob,
  revokeSpaceTokenApi,
  rotateSpaceEpochApi,
  unlockProtectedEntryApi,
  updateSpaceEntryApi,
  updateSpaceEnvelopeCas,
  uploadSpaceBlobChunk,
  type SpaceAuditLogItem,
  type SpaceCapabilities,
  type SpaceEntryDetail,
  type SpaceEntrySummary,
  type SpaceItem,
  type SpaceRouteConfig,
  type SpaceTier,
  type SpaceTokenCreated,
  type SpaceTokenItem,
  type SpaceTokenScope,
} from '../services/spaceApi'
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
    if (!auth.token) throw new Error('尚未登录工作区')
    return { token: auth.token }
  }

  /** 立即清空所有内存中的敏感明文、解密目录、一次性 Token 与 Blob ObjectURL。 */
  function clearSensitiveMemory() {
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
  }

  async function loadSpaces() {
    const route = requireRoute()
    loading.value = true
    error.value = ''
    try {
      const [caps, list] = await Promise.all([
        fetchSpaceCapabilities(route),
        fetchSpaces(route),
      ])
      capabilities.value = caps
      spaces.value = list
      if (selectedSpaceId.value && !list.some(s => s.id === selectedSpaceId.value)) {
        selectSpace(list[0]?.id ?? '')
      } else if (!selectedSpaceId.value && list.length > 0) {
        await selectSpace(list[0]!.id)
      }
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '加载共享空间失败'
    } finally {
      loading.value = false
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
    if (!spaceId) return
    await refreshCurrentSpace()
  }

  async function refreshCurrentSpace(search?: string, entryType?: string) {
    if (!selectedSpaceId.value) return
    const route = requireRoute()
    const space = selectedSpace.value
    loading.value = true
    error.value = ''
    try {
      entries.value = await fetchSpaceEntries(route, selectedSpaceId.value, { search, entryType })
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
      error.value = cause instanceof Error ? cause.message : '加载条目失败'
    } finally {
      loading.value = false
    }
  }

  async function selectEntry(entryId: string) {
    clearSensitiveMemory()
    selectedEntryId.value = entryId
    selectedEntryDetail.value = null
    if (!entryId || !selectedSpaceId.value) return
    const route = requireRoute()
    try {
      selectedEntryDetail.value = await fetchSpaceEntryDetail(route, selectedSpaceId.value, entryId)
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '加载条目详情失败'
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
    await archiveSpaceApi(route, spaceId)
    clearSensitiveMemory()
    spaces.value = spaces.value.filter(s => s.id !== spaceId)
    if (selectedSpaceId.value === spaceId) {
      await selectSpace(spaces.value[0]?.id ?? '')
    }
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
    const route = requireRoute()
    const space = selectedSpace.value
    if (!space) throw new Error('请先选择一个共享空间')

    const mime = input.file?.type || input.mime || (input.entryType === 'file' ? 'application/octet-stream' : 'text/plain')
    const fileName = input.file?.name || input.fileName
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
        await refreshCurrentSpace()
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
    } else {
      payload.contentText = input.contentText ?? ''
    }
    if (space.tier === 'protected') {
      if (!input.password) throw new Error('请输入受控机密空间密码以保存')
      payload.password = input.password
    }
    const created = await createSpaceEntryApi(route, space.id, payload)
    await refreshCurrentSpace()
    selectedEntryId.value = created.id
    selectedEntryDetail.value = created
    return created
  }

  /** 按次输入密码解密 E2EE 当前目录（仅驻留内存，离页即清）。 */
  async function decryptE2eeCatalogWithPassword(password: string) {
    const route = requireRoute()
    const space = selectedSpace.value
    if (!space || space.tier !== 'e2ee') return

    const envCache = new Map<number, Uint8Array<ArrayBuffer>>()
    const nextCatalog: Record<string, SpaceEntryManifest> = {}
    try {
      for (const item of entries.value) {
        if (!item.wrappedDek || !item.encryptedManifestB64) continue
        const ep = item.activeEpoch
        let spaceKey = envCache.get(ep)
        if (!spaceKey) {
          const envRes = await fetchSpaceEnvelope(route, space.id, ep)
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
      decryptedCatalogByEntryId.value = nextCatalog
    } finally {
      for (const k of envCache.values()) zeroizeBytes(k)
      envCache.clear()
    }
  }

  /** 按次输入密码解锁查看单条 protected 或 e2ee 条目。 */
  async function unlockCurrentEntryWithPassword(password: string, revision?: number): Promise<UnlockedEntryView> {
    const route = requireRoute()
    const space = selectedSpace.value
    const entry = selectedEntryDetail.value
    if (!space || !entry) throw new Error('未选择条目')

    if (space.tier === 'protected') {
      const unlocked = await unlockProtectedEntryApi(route, space.id, entry.id, password, revision)
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
        ? await fetchSpaceEntryDetail(route, space.id, entry.id, revision)
        : entry
      if (!targetDetail.wrappedDek || !targetDetail.encryptedManifestB64) {
        throw new Error('该条目缺少加密封套元数据')
      }
      const envRes = await fetchSpaceEnvelope(route, space.id, targetDetail.epoch)
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
      const dek = await unwrapDek({ wrappingKey: spaceKey, wrappedDek: targetDetail.wrappedDek, scope })
      try {
        const manifest = await decryptManifest({
          dek,
          encryptedManifestB64: targetDetail.encryptedManifestB64,
          scope,
        })
        const plainChunks: Uint8Array[] = []
        let totalLen = 0
        if (targetDetail.blobId && targetDetail.chunkCount > 0) {
          for (let i = 0; i < targetDetail.chunkCount; i += 1) {
            const ct = await downloadSpaceBlobChunk(route, space.id, targetDetail.blobId, i)
            const pt = await decryptChunk({ dek, ciphertextChunk: ct, scope, chunkIndex: i })
            plainChunks.push(pt)
            totalLen += pt.byteLength
          }
        }
        const merged = new Uint8Array(totalLen)
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
          contentText: isFile ? null : TEXT_DECODER.decode(merged),
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
        unlockedView.value = view
        return view
      } finally {
        zeroizeBytes(spaceKey, dek)
      }
    }

    throw new Error('普通共享空间无需输密解锁')
  }

  async function downloadStandardEntry(entry: SpaceEntryDetail) {
    const route = requireRoute()
    const blob = await downloadEntryBlob(route, entry.spaceId, entry.id)
    const url = registerObjectUrl(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = entry.fileName || `${entry.title || entry.id}.txt`
    a.click()
  }

  async function updateStandardEntry(entry: SpaceEntryDetail, nextTitle: string, nextText: string, nextTags: string[]) {
    const route = requireRoute()
    const updated = await updateSpaceEntryApi(route, entry.spaceId, entry.id, {
      baseRevision: entry.currentRevision,
      mutationId: crypto.randomUUID(),
      title: nextTitle,
      contentText: nextText,
      tags: nextTags,
    })
    await refreshCurrentSpace()
    selectedEntryId.value = updated.id
    selectedEntryDetail.value = updated
  }

  async function deleteCurrentEntry() {
    if (!selectedSpaceId.value || !selectedEntryId.value) return
    const route = requireRoute()
    await deleteSpaceEntryApi(route, selectedSpaceId.value, selectedEntryId.value)
    clearSensitiveMemory()
    selectedEntryId.value = ''
    selectedEntryDetail.value = null
    await refreshCurrentSpace()
  }

  async function loadTokensAndAudit() {
    if (!selectedSpaceId.value) return
    const route = requireRoute()
    const [tks, logs] = await Promise.all([
      fetchSpaceTokens(route, selectedSpaceId.value),
      fetchSpaceAuditLogs(route, selectedSpaceId.value),
    ])
    tokens.value = tks
    auditLogs.value = logs
  }

  async function issueToken(input: {
    name: string
    scopes: SpaceTokenScope[]
    entryIds?: string[] | null
    expiresInDays?: number | null
    password?: string
  }): Promise<SpaceTokenCreated> {
    if (!selectedSpaceId.value) throw new Error('未选择空间')
    const route = requireRoute()
    const created = await createSpaceTokenApi(route, selectedSpaceId.value, input)
    lastCreatedToken.value = created
    await loadTokensAndAudit()
    return created
  }

  async function revokeToken(tokenId: string) {
    if (!selectedSpaceId.value) return
    const route = requireRoute()
    await revokeSpaceTokenApi(route, selectedSpaceId.value, tokenId)
    await loadTokensAndAudit()
  }

  async function changeSpacePassword(oldPassword: string, newPassword: string) {
    const route = requireRoute()
    const space = selectedSpace.value
    if (!space) throw new Error('未选择空间')
    if (space.tier === 'protected') {
      const updated = await changeProtectedPasswordApi(route, space.id, { oldPassword, newPassword })
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
