import type { SpaceEntryDetail, SpaceEnvelopeResponse, SpaceItem, StandardSpaceEdit } from './spaceApi'

type MutationBase = { id: string; spaceId: string; entryId: string; deviceLabel: string; after?: string; candidateId?: string; error?: string }
export type SpaceMutation = MutationBase & (
  | { operation: 'create'; draft: SpaceEntryDetail; file?: Blob; stagedBlobId?: string; uploaded?: boolean }
  | { operation: 'edit'; baseRevision: number; edit: StandardSpaceEdit; draft: SpaceEntryDetail }
  | { operation: 'delete'; baseRevision: number }
)

export interface PinnedCiphertext {
  space: SpaceItem
  detail: SpaceEntryDetail
  envelope: SpaceEnvelopeResponse
  chunks: Blob[]
}

let database: Promise<IDBDatabase> | undefined

function openReplica(): Promise<IDBDatabase> {
  if (!database) {
    database = new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('studiolo-shared-space', 1)
      request.onupgradeneeded = () => request.result.createObjectStore('replica')
      request.onsuccess = () => {
        request.result.onversionchange = () => { request.result.close(); database = undefined }
        resolve(request.result)
      }
      request.onerror = () => reject(request.error)
      request.onblocked = () => reject(new Error('共享空间本地缓存升级受阻，请关闭其他窗口。'))
    }).catch(error => { database = undefined; throw error })
  }
  return database
}

export class SpaceReplica {
  constructor(readonly namespace: string) {}

  private key(key: string): IDBValidKey { return [this.namespace, key] }

  async read<T>(key: string): Promise<T | undefined> {
    const db = await openReplica()
    return new Promise((resolve, reject) => {
      const request = db.transaction('replica').objectStore('replica').get(this.key(key))
      request.onsuccess = () => resolve(request.result as T | undefined)
      request.onerror = () => reject(request.error)
    })
  }

  async write<T>(key: string, value: T): Promise<void> {
    const db = await openReplica()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction('replica', 'readwrite')
      transaction.objectStore('replica').put(value, this.key(key))
      transaction.oncomplete = () => resolve()
      transaction.onabort = () => reject(transaction.error)
    })
  }

  async queue(): Promise<SpaceMutation[]> { return await this.read('queue') ?? [] }

  async pinned(spaceId = ''): Promise<PinnedCiphertext[]> {
    const db = await openReplica()
    const prefix = `e2ee/${spaceId ? `${spaceId}/` : ''}`
    return new Promise((resolve, reject) => {
      const range = IDBKeyRange.bound(this.key(prefix), this.key(`${prefix}\uffff`))
      const request = db.transaction('replica').objectStore('replica').getAll(range)
      request.onsuccess = () => resolve(request.result as PinnedCiphertext[])
      request.onerror = () => reject(request.error)
    })
  }

  async unpin(spaceId: string, entryId: string): Promise<void> {
    const db = await openReplica()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction('replica', 'readwrite')
      transaction.objectStore('replica').delete(this.key(`e2ee/${spaceId}/${entryId}`))
      transaction.oncomplete = () => resolve()
      transaction.onabort = () => reject(transaction.error)
    })
  }

  async changeQueue(change: (queue: SpaceMutation[]) => SpaceMutation[]): Promise<void> {
    const db = await openReplica()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction('replica', 'readwrite')
      const store = transaction.objectStore('replica')
      const key = this.key('queue')
      const request = store.get(key)
      request.onsuccess = () => {
        try { store.put(change((request.result as SpaceMutation[] | undefined) ?? []), key) }
        catch (error) { reject(error); transaction.abort() }
      }
      transaction.oncomplete = () => resolve()
      transaction.onabort = () => reject(transaction.error)
    })
  }

  async enqueue(mutation: SpaceMutation): Promise<void> {
    await this.changeQueue(queue => {
      const previous = [...queue].reverse().find(item => item.spaceId === mutation.spaceId && item.entryId === mutation.entryId)
      return [...queue, { ...mutation, after: previous?.id }]
    })
  }
}
