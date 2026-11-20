import { ApiError } from '../api/client'
import {
  createSpaceEntryApi, fetchSpaceChanges, fetchSpaceEntries, fetchSpaceEntryDetail, fetchStandardSpaceSnapshot,
  initSpaceBlob, pushStandardSpaceMutation, uploadSpaceBlobChunk,
  type SpaceEntryDetail, type SpaceEntrySummary, type SpaceRouteConfig, type StandardSpaceSnapshot,
} from './spaceApi'
import { sha256Hex } from './spaceCrypto'
import type { SpaceMutation, SpaceReplica } from './spaceReplica'

export async function pullStandardSpace(
  replica: SpaceReplica, route: SpaceRouteConfig, spaceId: string, rebuild = false,
): Promise<{ entries: SpaceEntrySummary[]; supported: boolean }> {
  const key = `snapshot/${spaceId}`
  let snapshot = rebuild ? undefined : await replica.read<StandardSpaceSnapshot>(key)
  if (!snapshot) {
    try { snapshot = await fetchStandardSpaceSnapshot(route, spaceId) }
    catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) throw error
      // Older Core versions can still list and read entries online.
      const entries = await fetchSpaceEntries(route, spaceId)
      return { entries, supported: false }
    }
    for (const entry of snapshot.entries) {
      if (entry.entryType !== 'file') await refreshStandardDetail(replica, route, spaceId, entry.id)
    }
  }
  const entries = new Map<string, SpaceEntrySummary>(snapshot.entries.map(entry => [entry.id, entry]))
  let cursor = snapshot.cursor
  for (let pageIndex = 0; pageIndex < 8; pageIndex++) {
    let page: Awaited<ReturnType<typeof fetchSpaceChanges>>
    try { page = await fetchSpaceChanges(route, spaceId, cursor) }
    catch (error) {
      if (!rebuild && error instanceof ApiError && error.status === 409 && error.message === 'space_resync_required') {
        return pullStandardSpace(replica, route, spaceId, true)
      }
      throw error
    }
    if (page.nextSeq < cursor || (page.hasMore && page.nextSeq === cursor)) throw new Error('共享空间同步游标未能前进。')
    const latest = new Map(page.changes.filter(change => change.entryId).map(change => [change.entryId!, change.changeType]))
    for (const [id, operation] of latest) {
      const entry = operation === 'delete' ? undefined : await refreshStandardDetail(replica, route, spaceId, id)
      if (entry) entries.set(id, entry)
      else entries.delete(id)
    }
    cursor = page.nextSeq
    if (!page.hasMore) break
  }
  const catalog = [...entries.values()].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
  await replica.write(key, { cursor, entries: catalog })
  return { entries: catalog, supported: true }
}

async function refreshStandardDetail(replica: SpaceReplica, route: SpaceRouteConfig, spaceId: string, id: string) {
  try {
    const detail = await fetchSpaceEntryDetail(route, spaceId, id)
    if (detail.tier !== 'standard') throw new Error('Core returned a non-standard entry to the standard replica')
    await replica.write(`detail/${spaceId}/${id}`, detail)
    return detail
  } catch (error) {
    if (!(error instanceof ApiError) || ![404, 410].includes(error.status)) throw error
  }
}

export async function pushSpaceQueue(replica: SpaceReplica, route: SpaceRouteConfig, current: () => boolean) {
  const initial = await replica.queue()
  for (const id of initial.map(item => item.id)) {
    if (!current()) return
    const queue = await replica.queue()
    const mutation = queue.find(item => item.id === id)
    if (!current() || !mutation || mutation.after || mutation.error) continue
    try {
      let revision: number
      let resolvedConflict = false
      if (mutation.operation === 'create') {
        const created = await pushCreate(replica, route, mutation, current)
        if (!created) return
        revision = created.revision
        await replica.write(`detail/${mutation.spaceId}/${mutation.entryId}`, created)
        if (mutation.file) await replica.write(`file/${mutation.spaceId}/${mutation.entryId}/${created.blobId ?? revision}`, mutation.file)
      } else {
        const result = await pushStandardSpaceMutation(route, mutation.spaceId, mutation.entryId, {
          mutationId: mutation.id, operation: mutation.operation, baseRevision: mutation.baseRevision,
          deviceLabel: mutation.deviceLabel, edit: mutation.operation === 'edit' ? mutation.edit : undefined,
        })
        if (result.status === 'conflict') {
          await replica.changeQueue(items => items.map(item => item.id === id ? { ...item, candidateId: result.candidateId ?? undefined } : item))
          continue
        }
        revision = result.revision
        resolvedConflict = result.status === 'resolved'
      }
      await replica.changeQueue(items => items.filter(item => item.id !== id).map(item => {
        if (item.after !== id) return item
        return item.operation === 'create' || resolvedConflict
          ? { ...item, after: undefined }
          : { ...item, after: undefined, baseRevision: revision }
      }))
    } catch (error) {
      if (!(error instanceof ApiError) || error.status === 0 || error.status >= 500 || error.status === 401 || error.status === 429) throw error
      if (error.status === 404 && mutation.operation === 'create' && mutation.stagedBlobId) {
        await replica.changeQueue(items => items.map(item => item.id === id && item.operation === 'create'
          ? { ...item, stagedBlobId: undefined, uploaded: false } : item))
        throw error
      }
      // Keep rejected drafts locally, with dependent edits intact.
      const message = error.status === 404 ? 'Core 未提供该条目的同步接口，或条目所属的空间已归档。' : error.message
      await replica.changeQueue(items => items.map(item => item.id === id ? { ...item, error: message } : item))
    }
  }
}

async function pushCreate(
  replica: SpaceReplica, route: SpaceRouteConfig, mutation: Extract<SpaceMutation, { operation: 'create' }>, current: () => boolean,
): Promise<SpaceEntryDetail | undefined> {
  const { id, spaceId, draft, file } = mutation
  let blobId = mutation.stagedBlobId
  if (file && !mutation.uploaded) {
    const chunkSize = 2 * 1024 * 1024
    const chunkCount = Math.max(1, Math.ceil(file.size / chunkSize))
    if (!blobId) {
      blobId = (await initSpaceBlob(route, spaceId, { chunkSize, chunkCount, totalSize: file.size })).id
      await replica.changeQueue(items => items.map(item => item.id === id ? { ...item, stagedBlobId: blobId } : item))
    }
    for (let index = 0; index < chunkCount; index++) {
      if (!current()) return
      const bytes = new Uint8Array(await file.slice(index * chunkSize, (index + 1) * chunkSize).arrayBuffer())
      const uploaded = await uploadSpaceBlobChunk(route, spaceId, blobId, index, bytes, await sha256Hex(bytes))
      if (uploaded.uploadedChunks.length === chunkCount) break
    }
    await replica.changeQueue(items => items.map(item => item.id === id ? { ...item, uploaded: true } : item))
  }
  if (!current()) return
  return createSpaceEntryApi(route, spaceId, {
    id: draft.id, mutationId: id, entryType: draft.entryType, title: draft.title, fileName: draft.fileName,
    mime: draft.mime, tags: draft.tags, contentText: draft.contentText, blobId,
  })
}
