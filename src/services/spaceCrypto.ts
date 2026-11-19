/**
 * Studiolo Shared Space 客户端密码学实现（与 packages/contracts/shared-space-crypto-v1.md 逐字节对齐）。
 *
 * - KDF：Argon2id（@noble/hashes/argon2.js，RFC 9106）
 * - AEAD：AES-256-GCM（原生 WebCrypto，无平台二进制依赖，桌面 WebView / 手机浏览器 / Node 22+ 通用）
 * - 安全约束：密钥与明文仅存在于当次调用内存，使用后必须立即调用 `zeroizeBytes` 清零。
 */

import { argon2id } from '@noble/hashes/argon2.js'

export const CRYPTO_PROTOCOL_VERSION = 1 as const
export const AEAD_ALGORITHM = 'aes-256-gcm' as const
export const KDF_ALGORITHM = 'argon2id' as const

export const DEFAULT_CHUNK_SIZE = 2 * 1024 * 1024 // 2 MiB
export const KEY_BYTES = 32
export const NONCE_BYTES = 12
export const TAG_BYTES = 16
export const SALT_BYTES = 16

export const DEFAULT_ARGON2_PARAMS: Readonly<Argon2Params> = Object.freeze({
  m: 19456,
  t: 2,
  p: 1,
  dkLen: KEY_BYTES,
})

const MIN_PROD_MEMORY_KIB = 19456
const MIN_PROD_ITERATIONS = 2
const MIN_VECTOR_MEMORY_KIB = 1024
const MIN_VECTOR_ITERATIONS = 1
const MAX_MEMORY_KIB = 262144
const MAX_ITERATIONS = 16
const MAX_LANES = 4

const TEXT_ENCODER = new TextEncoder()
const TEXT_DECODER = new TextDecoder()

export interface Argon2Params {
  m: number
  t: number
  p: number
  dkLen: number
}

export interface KeyEnvelopeKdf extends Argon2Params {
  algorithm: typeof KDF_ALGORITHM
  saltB64: string
}

export interface KeyEnvelope {
  version: typeof CRYPTO_PROTOCOL_VERSION
  epoch: number
  kdf: KeyEnvelopeKdf
  aead: typeof AEAD_ALGORITHM
  nonceB64: string
  wrappedKeyB64: string
}

export interface WrappedDek {
  version: typeof CRYPTO_PROTOCOL_VERSION
  epoch: number
  aead: typeof AEAD_ALGORITHM
  nonceB64: string
  wrappedDekB64: string
}

export type SpaceEntryType = 'text' | 'config' | 'key' | 'file'

export interface SpaceEntryManifest {
  version: 1
  entryType: SpaceEntryType
  title: string
  fileName?: string
  mime: string
  sizeBytes: number
  chunkCount: number
  chunkSize: number
  plaintextSha256: string
  tags?: string[]
  summary?: string
}

export interface SpaceAadScope {
  workspaceId: string
  spaceId: string
  entryId: string
  revision: number
  epoch: number
}

export class SpaceCryptoError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'SpaceCryptoError'
  }
}

export class UnsupportedEnvelopeVersionError extends SpaceCryptoError {
  constructor(message: string) {
    super(message)
    this.name = 'UnsupportedEnvelopeVersionError'
  }
}

export class SpacePasswordMismatchError extends SpaceCryptoError {
  constructor(message: string) {
    super(message)
    this.name = 'SpacePasswordMismatchError'
  }
}

/** 尽量在释放前覆写敏感字节缓冲区。 */
export function zeroizeBytes(...buffers: Array<Uint8Array | null | undefined>): void {
  for (const buf of buffers) {
    if (buf && buf.byteLength > 0) {
      buf.fill(0)
    }
  }
}

function toArrayBufferBytes(input: Uint8Array): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(new ArrayBuffer(input.byteLength))
  out.set(input)
  return out
}

export function randomBytes(length: number): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(new ArrayBuffer(length))
  crypto.getRandomValues(out)
  return out
}

export function b64urlEncode(bytes: Uint8Array): string {
  let binary = ''
  const step = 0x8000
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode(...bytes.subarray(i, i + step))
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

export function b64urlDecode(encoded: string): Uint8Array<ArrayBuffer> {
  if (typeof encoded !== 'string' || !encoded) {
    throw new SpaceCryptoError('Base64URL 字段不能为空')
  }
  if (!/^[A-Za-z0-9_-]+$/.test(encoded)) {
    throw new SpaceCryptoError('无效的 Base64URL 编码')
  }
  const normalized = encoded.replace(/-/g, '+').replace(/_/g, '/')
  const padLen = (4 - (normalized.length % 4)) % 4
  const binary = atob(normalized + '='.repeat(padLen))
  const out = new Uint8Array(new ArrayBuffer(binary.length))
  for (let i = 0; i < binary.length; i += 1) {
    out[i] = binary.charCodeAt(i)
  }
  return out
}

export async function sha256Hex(data: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', toArrayBufferBytes(data))
  const arr = new Uint8Array(digest)
  let hex = ''
  for (let i = 0; i < arr.length; i += 1) {
    hex += arr[i]!.toString(16).padStart(2, '0')
  }
  return hex
}

function validateId(name: string, value: string): string {
  if (typeof value !== 'string' || !value || value.includes(':')) {
    throw new SpaceCryptoError(`无效的 ${name} 标识`)
  }
  return value
}

function validateInt(name: string, value: unknown, min: number): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < min) {
    throw new SpaceCryptoError(`${name} 必须为不小于 ${min} 的整数`)
  }
  return value
}

export function buildEnvelopeAad(workspaceId: string, spaceId: string, epoch: number): Uint8Array<ArrayBuffer> {
  const ws = validateId('workspaceId', workspaceId)
  const sp = validateId('spaceId', spaceId)
  const ep = validateInt('epoch', epoch, 1)
  return toArrayBufferBytes(TEXT_ENCODER.encode(`studiolo:space:v1:${ws}:${sp}:envelope:${ep}`))
}

export function buildDekAad(scope: SpaceAadScope): Uint8Array<ArrayBuffer> {
  const ws = validateId('workspaceId', scope.workspaceId)
  const sp = validateId('spaceId', scope.spaceId)
  const en = validateId('entryId', scope.entryId)
  const rev = validateInt('revision', scope.revision, 1)
  const ep = validateInt('epoch', scope.epoch, 1)
  return toArrayBufferBytes(TEXT_ENCODER.encode(`studiolo:space:v1:${ws}:${sp}:${en}:${rev}:dek:${ep}`))
}

export function buildManifestAad(scope: SpaceAadScope): Uint8Array<ArrayBuffer> {
  const ws = validateId('workspaceId', scope.workspaceId)
  const sp = validateId('spaceId', scope.spaceId)
  const en = validateId('entryId', scope.entryId)
  const rev = validateInt('revision', scope.revision, 1)
  const ep = validateInt('epoch', scope.epoch, 1)
  return toArrayBufferBytes(TEXT_ENCODER.encode(`studiolo:space:v1:${ws}:${sp}:${en}:${rev}:manifest:${ep}`))
}

export function buildChunkAad(scope: SpaceAadScope, chunkIndex: number): Uint8Array<ArrayBuffer> {
  const ws = validateId('workspaceId', scope.workspaceId)
  const sp = validateId('spaceId', scope.spaceId)
  const en = validateId('entryId', scope.entryId)
  const rev = validateInt('revision', scope.revision, 1)
  const idx = validateInt('chunkIndex', chunkIndex, 0)
  const ep = validateInt('epoch', scope.epoch, 1)
  return toArrayBufferBytes(TEXT_ENCODER.encode(`studiolo:space:v1:${ws}:${sp}:${en}:${rev}:chunk:${idx}:${ep}`))
}

export function validateArgon2Params(
  params: Argon2Params,
  options?: { allowLowCostForVectors?: boolean },
): void {
  const allowLow = options?.allowLowCostForVectors === true
  const minM = allowLow ? MIN_VECTOR_MEMORY_KIB : MIN_PROD_MEMORY_KIB
  const minT = allowLow ? MIN_VECTOR_ITERATIONS : MIN_PROD_ITERATIONS
  if (!Number.isInteger(params.m) || params.m < minM || params.m > MAX_MEMORY_KIB) {
    throw new SpaceCryptoError(`Argon2id memory_cost 越界: ${params.m}`)
  }
  if (!Number.isInteger(params.t) || params.t < minT || params.t > MAX_ITERATIONS) {
    throw new SpaceCryptoError(`Argon2id iterations 越界: ${params.t}`)
  }
  if (!Number.isInteger(params.p) || params.p < 1 || params.p > MAX_LANES) {
    throw new SpaceCryptoError(`Argon2id lanes 越界: ${params.p}`)
  }
  if (params.dkLen !== KEY_BYTES) {
    throw new SpaceCryptoError(`Argon2id dkLen 必须为 ${KEY_BYTES}`)
  }
}

/** 使用 Argon2id 从空间密码和盐派生 32 字节 KEK。 */
export function deriveKek(
  password: string,
  salt: Uint8Array,
  params: Argon2Params = DEFAULT_ARGON2_PARAMS,
  options?: { allowLowCostForVectors?: boolean },
): Uint8Array<ArrayBuffer> {
  if (typeof password !== 'string' || !password) {
    throw new SpaceCryptoError('密码不能为空')
  }
  if (!(salt instanceof Uint8Array) || salt.byteLength < SALT_BYTES || salt.byteLength > 64) {
    throw new SpaceCryptoError('盐长度必须在 16 到 64 字节之间')
  }
  validateArgon2Params(params, options)
  const passwordBytes = TEXT_ENCODER.encode(password)
  try {
    const derived = argon2id(passwordBytes, salt, {
      t: params.t,
      m: params.m,
      p: params.p,
      dkLen: params.dkLen,
    })
    return toArrayBufferBytes(derived)
  } finally {
    zeroizeBytes(passwordBytes)
  }
}

async function importAesKey(rawKey: Uint8Array, usages: KeyUsage[]): Promise<CryptoKey> {
  if (!(rawKey instanceof Uint8Array) || rawKey.byteLength !== KEY_BYTES) {
    throw new SpaceCryptoError(`AES-256-GCM 密钥必须为 ${KEY_BYTES} 字节`)
  }
  return crypto.subtle.importKey('raw', toArrayBufferBytes(rawKey), { name: 'AES-GCM', length: 256 }, false, usages)
}

function requireNonce(nonce?: Uint8Array): Uint8Array<ArrayBuffer> {
  if (!nonce) return randomBytes(NONCE_BYTES)
  if (nonce.byteLength !== NONCE_BYTES) {
    throw new SpaceCryptoError(`nonce 必须为 ${NONCE_BYTES} 字节`)
  }
  return toArrayBufferBytes(nonce)
}

/** 用用户密码封装随机 Space Key，生成标准 KeyEnvelope。 */
export async function wrapSpaceKey(input: {
  password: string
  spaceKey: Uint8Array
  workspaceId: string
  spaceId: string
  epoch?: number
  params?: Argon2Params
  salt?: Uint8Array
  nonce?: Uint8Array
  allowLowCostForVectors?: boolean
}): Promise<KeyEnvelope> {
  if (input.spaceKey.byteLength !== KEY_BYTES) {
    throw new SpaceCryptoError(`spaceKey 必须为 ${KEY_BYTES} 字节`)
  }
  const epoch = input.epoch ?? 1
  const params = input.params ?? DEFAULT_ARGON2_PARAMS
  const salt = input.salt ? toArrayBufferBytes(input.salt) : randomBytes(SALT_BYTES)
  const nonce = requireNonce(input.nonce)
  const kek = deriveKek(input.password, salt, params, {
    allowLowCostForVectors: input.allowLowCostForVectors,
  })
  try {
    const aesKey = await importAesKey(kek, ['encrypt'])
    const aad = buildEnvelopeAad(input.workspaceId, input.spaceId, epoch)
    const encrypted = await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv: nonce, additionalData: aad, tagLength: 128 },
      aesKey,
      toArrayBufferBytes(input.spaceKey),
    )
    return {
      version: CRYPTO_PROTOCOL_VERSION,
      epoch,
      kdf: {
        algorithm: KDF_ALGORITHM,
        m: params.m,
        t: params.t,
        p: params.p,
        dkLen: params.dkLen,
        saltB64: b64urlEncode(salt),
      },
      aead: AEAD_ALGORITHM,
      nonceB64: b64urlEncode(nonce),
      wrappedKeyB64: b64urlEncode(new Uint8Array(encrypted)),
    }
  } finally {
    zeroizeBytes(kek)
  }
}

/** 使用当次输入密码解包 KeyEnvelope，得到 32B Space Key。 */
export async function unwrapSpaceKey(input: {
  password: string
  envelope: KeyEnvelope
  workspaceId: string
  spaceId: string
  expectedEpoch?: number
  allowLowCostForVectors?: boolean
}): Promise<Uint8Array<ArrayBuffer>> {
  const { envelope } = input
  if (!envelope || typeof envelope !== 'object') {
    throw new UnsupportedEnvelopeVersionError('无效的 KeyEnvelope 对象')
  }
  if (envelope.version !== CRYPTO_PROTOCOL_VERSION) {
    throw new UnsupportedEnvelopeVersionError(`不支持的封套版本: ${String(envelope.version)}`)
  }
  if (envelope.aead !== AEAD_ALGORITHM) {
    throw new UnsupportedEnvelopeVersionError(`不支持的 AEAD 算法: ${String(envelope.aead)}`)
  }
  const epoch = validateInt('epoch', envelope.epoch, 1)
  if (input.expectedEpoch !== undefined && epoch !== input.expectedEpoch) {
    throw new SpacePasswordMismatchError('KeyEnvelope epoch 与预期不匹配')
  }
  if (!envelope.kdf || envelope.kdf.algorithm !== KDF_ALGORITHM) {
    throw new UnsupportedEnvelopeVersionError('不支持的 KDF 算法')
  }
  const salt = b64urlDecode(envelope.kdf.saltB64)
  const nonce = b64urlDecode(envelope.nonceB64)
  const wrapped = b64urlDecode(envelope.wrappedKeyB64)
  if (nonce.byteLength !== NONCE_BYTES || wrapped.byteLength !== KEY_BYTES + TAG_BYTES) {
    throw new SpaceCryptoError('KeyEnvelope 长度异常')
  }

  const kek = deriveKek(
    input.password,
    salt,
    {
      m: envelope.kdf.m,
      t: envelope.kdf.t,
      p: envelope.kdf.p,
      dkLen: envelope.kdf.dkLen,
    },
    { allowLowCostForVectors: input.allowLowCostForVectors },
  )
  try {
    const aesKey = await importAesKey(kek, ['decrypt'])
    const aad = buildEnvelopeAad(input.workspaceId, input.spaceId, epoch)
    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: nonce, additionalData: aad, tagLength: 128 },
      aesKey,
      wrapped,
    )
    const spaceKey = new Uint8Array(decrypted)
    if (spaceKey.byteLength !== KEY_BYTES) {
      throw new SpaceCryptoError('解包后的 Space Key 长度异常')
    }
    return toArrayBufferBytes(spaceKey)
  } catch (error) {
    if (error instanceof SpaceCryptoError) throw error
    throw new SpacePasswordMismatchError('空间密码错误或封套已被篡改')
  } finally {
    zeroizeBytes(kek)
  }
}

/** 常规改密：验证旧密码解包原 Space Key，保持 epoch 不变并用新随机盐与新密码重包 KeyEnvelope。 */
export async function rewrapEnvelopeForPasswordChange(input: {
  oldPassword: string
  newPassword: string
  currentEnvelope: KeyEnvelope
  workspaceId: string
  spaceId: string
  params?: Argon2Params
  allowLowCostForVectors?: boolean
}): Promise<KeyEnvelope> {
  const spaceKey = await unwrapSpaceKey({
    password: input.oldPassword,
    envelope: input.currentEnvelope,
    workspaceId: input.workspaceId,
    spaceId: input.spaceId,
    allowLowCostForVectors: input.allowLowCostForVectors,
  })
  try {
    return await wrapSpaceKey({
      password: input.newPassword,
      spaceKey,
      workspaceId: input.workspaceId,
      spaceId: input.spaceId,
      epoch: input.currentEnvelope.epoch,
      params: input.params,
      allowLowCostForVectors: input.allowLowCostForVectors,
    })
  } finally {
    zeroizeBytes(spaceKey)
  }
}

/** 泄露/撤销轮换：生成全新随机 Space Key 与递增 epoch 封套，供调用方随后重包或重加密条目。 */
export async function createRotatedEpochEnvelope(input: {
  newPassword: string
  workspaceId: string
  spaceId: string
  currentEpoch: number
  params?: Argon2Params
  allowLowCostForVectors?: boolean
}): Promise<{ nextEpoch: number; nextSpaceKey: Uint8Array<ArrayBuffer>; envelope: KeyEnvelope }> {
  const nextEpoch = validateInt('currentEpoch', input.currentEpoch, 1) + 1
  const nextSpaceKey = randomBytes(KEY_BYTES)
  const envelope = await wrapSpaceKey({
    password: input.newPassword,
    spaceKey: nextSpaceKey,
    workspaceId: input.workspaceId,
    spaceId: input.spaceId,
    epoch: nextEpoch,
    params: input.params,
    allowLowCostForVectors: input.allowLowCostForVectors,
  })
  return { nextEpoch, nextSpaceKey, envelope }
}

/** 用 Space Key 封装每修订独立 DEK。 */
export async function wrapDek(input: {
  wrappingKey: Uint8Array
  dek: Uint8Array
  scope: SpaceAadScope
  nonce?: Uint8Array
}): Promise<WrappedDek> {
  if (input.dek.byteLength !== KEY_BYTES) {
    throw new SpaceCryptoError(`dek 必须为 ${KEY_BYTES} 字节`)
  }
  const nonce = requireNonce(input.nonce)
  const aesKey = await importAesKey(input.wrappingKey, ['encrypt'])
  const aad = buildDekAad(input.scope)
  const encrypted = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: nonce, additionalData: aad, tagLength: 128 },
    aesKey,
    toArrayBufferBytes(input.dek),
  )
  return {
    version: CRYPTO_PROTOCOL_VERSION,
    epoch: input.scope.epoch,
    aead: AEAD_ALGORITHM,
    nonceB64: b64urlEncode(nonce),
    wrappedDekB64: b64urlEncode(new Uint8Array(encrypted)),
  }
}

/** 解包条目修订 DEK。 */
export async function unwrapDek(input: {
  wrappingKey: Uint8Array
  wrappedDek: WrappedDek
  scope: SpaceAadScope
}): Promise<Uint8Array<ArrayBuffer>> {
  const { wrappedDek, scope } = input
  if (!wrappedDek || typeof wrappedDek !== 'object') {
    throw new UnsupportedEnvelopeVersionError('无效的 WrappedDek 对象')
  }
  if (wrappedDek.version !== CRYPTO_PROTOCOL_VERSION) {
    throw new UnsupportedEnvelopeVersionError(`不支持的 DEK 封套版本: ${String(wrappedDek.version)}`)
  }
  if (wrappedDek.aead !== AEAD_ALGORITHM) {
    throw new UnsupportedEnvelopeVersionError(`不支持的 AEAD 算法: ${String(wrappedDek.aead)}`)
  }
  if (wrappedDek.epoch !== scope.epoch) {
    throw new SpacePasswordMismatchError('WrappedDek epoch 与预期不匹配')
  }
  const nonce = b64urlDecode(wrappedDek.nonceB64)
  const ciphertext = b64urlDecode(wrappedDek.wrappedDekB64)
  if (nonce.byteLength !== NONCE_BYTES || ciphertext.byteLength !== KEY_BYTES + TAG_BYTES) {
    throw new SpaceCryptoError('WrappedDek 长度异常')
  }
  const aesKey = await importAesKey(input.wrappingKey, ['decrypt'])
  const aad = buildDekAad(scope)
  try {
    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: nonce, additionalData: aad, tagLength: 128 },
      aesKey,
      ciphertext,
    )
    return toArrayBufferBytes(new Uint8Array(decrypted))
  } catch {
    throw new SpacePasswordMismatchError('DEK 解包失败或密文已被篡改')
  }
}

/** 递归按 key 排序序列化 JSON，与 Python `json.dumps(..., separators=(",", ":"), sort_keys=True)` 逐字节一致。 */
function canonicalJsonStringify(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) {
    return `[${value.map(item => canonicalJsonStringify(item)).join(',')}]`
  }
  const record = value as Record<string, unknown>
  const keys = Object.keys(record)
    .filter(k => record[k] !== undefined)
    .sort()
  return `{${keys.map(k => `${JSON.stringify(k)}:${canonicalJsonStringify(record[k])}`).join(',')}}`
}

/** 加密条目 Manifest JSON，返回 `12B Nonce || Ciphertext || 16B Tag` 的 Base64URL。 */
export async function encryptManifest(input: {
  dek: Uint8Array
  manifest: SpaceEntryManifest
  scope: SpaceAadScope
  nonce?: Uint8Array
}): Promise<string> {
  const nonce = requireNonce(input.nonce)
  const aesKey = await importAesKey(input.dek, ['encrypt'])
  const aad = buildManifestAad(input.scope)
  const plaintext = toArrayBufferBytes(TEXT_ENCODER.encode(canonicalJsonStringify(input.manifest)))
  try {
    const encrypted = await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv: nonce, additionalData: aad, tagLength: 128 },
      aesKey,
      plaintext,
    )
    const out = new Uint8Array(NONCE_BYTES + encrypted.byteLength)
    out.set(nonce, 0)
    out.set(new Uint8Array(encrypted), NONCE_BYTES)
    return b64urlEncode(out)
  } finally {
    zeroizeBytes(plaintext)
  }
}

/** 解密条目 Manifest JSON。 */
export async function decryptManifest(input: {
  dek: Uint8Array
  encryptedManifestB64: string
  scope: SpaceAadScope
}): Promise<SpaceEntryManifest> {
  const blob = b64urlDecode(input.encryptedManifestB64)
  if (blob.byteLength < NONCE_BYTES + TAG_BYTES) {
    throw new SpaceCryptoError('加密 Manifest 长度不足')
  }
  const nonce = blob.subarray(0, NONCE_BYTES)
  const ciphertext = blob.subarray(NONCE_BYTES)
  const aesKey = await importAesKey(input.dek, ['decrypt'])
  const aad = buildManifestAad(input.scope)
  try {
    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: toArrayBufferBytes(nonce), additionalData: aad, tagLength: 128 },
      aesKey,
      toArrayBufferBytes(ciphertext),
    )
    const parsed = JSON.parse(TEXT_DECODER.decode(decrypted))
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new SpaceCryptoError('Manifest 必须为 JSON 对象')
    }
    return parsed as SpaceEntryManifest
  } catch (error) {
    if (error instanceof SpaceCryptoError) throw error
    throw new SpacePasswordMismatchError('Manifest 解密失败或已被篡改')
  }
}

/** 加密单分块正文或文件块，返回 `12B Nonce || Ciphertext || 16B Tag`。 */
export async function encryptChunk(input: {
  dek: Uint8Array
  plaintext: Uint8Array
  scope: SpaceAadScope
  chunkIndex: number
  nonce?: Uint8Array
}): Promise<Uint8Array<ArrayBuffer>> {
  const nonce = requireNonce(input.nonce)
  const aesKey = await importAesKey(input.dek, ['encrypt'])
  const aad = buildChunkAad(input.scope, input.chunkIndex)
  const encrypted = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: nonce, additionalData: aad, tagLength: 128 },
    aesKey,
    toArrayBufferBytes(input.plaintext),
  )
  const out = new Uint8Array(new ArrayBuffer(NONCE_BYTES + encrypted.byteLength))
  out.set(nonce, 0)
  out.set(new Uint8Array(encrypted), NONCE_BYTES)
  return out
}

/** 解密单分块正文或文件块。 */
export async function decryptChunk(input: {
  dek: Uint8Array
  ciphertextChunk: Uint8Array
  scope: SpaceAadScope
  chunkIndex: number
}): Promise<Uint8Array<ArrayBuffer>> {
  if (input.ciphertextChunk.byteLength < NONCE_BYTES + TAG_BYTES) {
    throw new SpaceCryptoError('密文分块长度不足')
  }
  const nonce = input.ciphertextChunk.subarray(0, NONCE_BYTES)
  const body = input.ciphertextChunk.subarray(NONCE_BYTES)
  const aesKey = await importAesKey(input.dek, ['decrypt'])
  const aad = buildChunkAad(input.scope, input.chunkIndex)
  try {
    const decrypted = await crypto.subtle.decrypt(
      { name: 'AES-GCM', iv: toArrayBufferBytes(nonce), additionalData: aad, tagLength: 128 },
      aesKey,
      toArrayBufferBytes(body),
    )
    return toArrayBufferBytes(new Uint8Array(decrypted))
  } catch {
    throw new SpacePasswordMismatchError('密文分块校验失败或已被篡改')
  }
}
