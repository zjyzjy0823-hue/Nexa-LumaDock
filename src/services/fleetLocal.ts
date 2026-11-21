import { decodeBase64Url, encodeBase64Url } from './blobTransfer'
import type { ChatMessage, ChatSession, RunOptions } from '../types/fleet'

interface StoredFile { name: string; type: string; lastModified: number; data: string }

export interface FleetOutboxItem {
  id: string
  sessionKey: string
  session: ChatSession
  text: string
  wireText: string
  files: File[]
  options?: RunOptions
  createdAt: number
}

export interface FleetCachedSession {
  session: ChatSession
  messages: ChatMessage[]
  savedAt: number
}

interface EncryptedRecord { nonce: Uint8Array<ArrayBuffer>; ciphertext: ArrayBuffer }
type RecordKind = 'history' | 'outbox'
const encoder = new TextEncoder()
const decoder = new TextDecoder()
let database: Promise<IDBDatabase> | undefined

function openDatabase(): Promise<IDBDatabase> {
  database ??= new Promise<IDBDatabase>((resolve, reject) => {
    const request = indexedDB.open('studiolo-fleet-local', 1)
    request.onupgradeneeded = () => {
      request.result.createObjectStore('keys')
      request.result.createObjectStore('records')
    }
    request.onsuccess = () => {
      const db = request.result
      db.onversionchange = () => { db.close(); database = undefined }
      resolve(db)
    }
    request.onerror = () => reject(request.error)
  }).catch(error => { database = undefined; throw error })
  return database
}

function read<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

function write(db: IDBDatabase, storeName: 'keys' | 'records', action: (store: IDBObjectStore) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(storeName, 'readwrite')
    transaction.oncomplete = () => resolve()
    transaction.onabort = () => reject(transaction.error ?? new Error('本地存储事务已中止'))
    action(transaction.objectStore(storeName))
  })
}

export class FleetLocalStore {
  private key: Promise<CryptoKey> | undefined

  static available(): boolean {
    return typeof indexedDB !== 'undefined' && Boolean(globalThis.crypto?.subtle)
  }

  constructor(readonly scope: string) {}

  private encryptionKey(): Promise<CryptoKey> {
    this.key ??= this.loadKey().catch(error => { this.key = undefined; throw error })
    return this.key
  }

  private async loadKey(): Promise<CryptoKey> {
    const db = await openDatabase()
    const existing = await read<CryptoKey | undefined>(db.transaction('keys').objectStore('keys').get(this.scope))
    if (existing) return existing
    const generated = await crypto.subtle.generateKey({ name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'])
    let key = generated
    await write(db, 'keys', store => {
      const request = store.get(this.scope)
      request.onsuccess = () => {
        if (request.result) key = request.result as CryptoKey
        else store.add(generated, this.scope)
      }
    })
    return key
  }

  private async put(kind: RecordKind, id: string, value: unknown): Promise<void> {
    const key = [this.scope, kind, id]
    const nonce = crypto.getRandomValues(new Uint8Array(12))
    const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce, additionalData: encoder.encode(JSON.stringify(key)) },
      await this.encryptionKey(), encoder.encode(JSON.stringify(value)))
    const db = await openDatabase()
    await write(db, 'records', store => { store.put({ nonce, ciphertext }, key) })
  }

  private async list<T>(kind: RecordKind): Promise<Array<{ id: string; value: T }>> {
    const db = await openDatabase()
    const store = db.transaction('records').objectStore('records')
    const range = IDBKeyRange.bound([this.scope, kind], [this.scope, kind, '\uffff'])
    const [ids, records] = await Promise.all([read(store.getAllKeys(range)), read<EncryptedRecord[]>(store.getAll(range))])
    if (!records.length) return []
    const key = await this.encryptionKey()
    const decrypted = await Promise.allSettled(records.map(async ({ nonce, ciphertext }, index) => {
      const recordKey = ids[index] as string[]
      const plaintext = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: nonce, additionalData: encoder.encode(JSON.stringify(recordKey)) }, key, ciphertext)
      return { id: recordKey[2], value: JSON.parse(decoder.decode(plaintext)) as T }
    }))
    return decrypted.flatMap(result => result.status === 'fulfilled' ? [result.value] : [])
  }

  async remove(kind: RecordKind, id: string): Promise<void> {
    await write(await openDatabase(), 'records', store => { store.delete([this.scope, kind, id]) })
  }

  async savePrompt(item: FleetOutboxItem): Promise<void> {
    const files: StoredFile[] = await Promise.all(item.files.map(async file => ({
      name: file.name, type: file.type, lastModified: file.lastModified,
      data: encodeBase64Url(new Uint8Array(await file.arrayBuffer())),
    })))
    await this.put('outbox', item.id, { ...item, files })
  }

  async outbox(): Promise<FleetOutboxItem[]> {
    const rows = await this.list<Omit<FleetOutboxItem, 'files'> & { files: StoredFile[] }>('outbox')
    return rows.map(({ value }) => ({ ...value, files: value.files.map(file =>
      new File([decodeBase64Url(file.data)], file.name, { type: file.type, lastModified: file.lastModified })) }))
      .sort((left, right) => left.createdAt - right.createdAt)
  }

  async history(): Promise<Array<{ id: string; value: FleetCachedSession }>> {
    return this.list<FleetCachedSession>('history')
  }

  async saveHistory(id: string, session: ChatSession, rows: ChatMessage[]): Promise<void> {
    const messages = []
    let byteCount = 0
    for (const row of rows.slice(-120).reverse()) {
      // Transfer keys, in-flight approvals and live Blob URLs are scoped to the current app session.
      const { artifacts, approvals, forms, branches, media, ...message } = row
      const cached = {
        ...message,
        streaming: false,
        media: media?.filter(item => !item.url.startsWith('blob:')),
        toolCalls: message.toolCalls?.map(call => ({ ...call, media: call.media?.filter(item => !item.url.startsWith('blob:')) })),
      }
      byteCount += encoder.encode(JSON.stringify(cached)).byteLength
      if (byteCount > 1024 * 1024) break
      messages.unshift(cached)
    }
    if (messages.length) await this.put('history', id, { session, messages, savedAt: Date.now() })
  }
}
