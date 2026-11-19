/**
 * 浏览器端分块 E2EE 文件传输模块（AES-256-GCM + SHA-256）。
 *
 * 与 `agent-node/agent_node/crypto_chunks.py` 保持逐字节协议一致：
 * - 单分块格式：`12B Nonce || Ciphertext || 16B GCM Tag`
 * - AAD：`UTF-8("studiolo:blob:{aadContext}:{chunkIndex}")`
 * - 密钥：32 字节（256 位），仅通过 `ArtifactRef.keyB64` 在端到端内存中流转，绝不上传至 Core/Edge Relay。
 */

import type { ArtifactRef, BlobEndpointsOut, BlobOut, EndpointKind, ResolvedEndpoint } from '../types/fleet'

export const DEFAULT_CHUNK_SIZE = 2 * 1024 * 1024 // 2 MiB（与 agent-node 对齐）
export const NONCE_BYTES = 12
const TEXT_ENCODER = new TextEncoder()

export function encodeBase64Url(bytes: Uint8Array): string {
  let binary = ''
  const step = 0x8000
  for (let i = 0; i < bytes.length; i += step) {
    binary += String.fromCharCode(...bytes.subarray(i, i + step))
  }
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

export function decodeBase64Url(encoded: string): Uint8Array<ArrayBuffer> {
  const normalized = encoded.replace(/-/g, '+').replace(/_/g, '/')
  const padLen = (4 - (normalized.length % 4)) % 4
  const binary = atob(normalized + '='.repeat(padLen))
  const out = new Uint8Array(new ArrayBuffer(binary.length))
  for (let i = 0; i < binary.length; i += 1) {
    out[i] = binary.charCodeAt(i)
  }
  return out
}

export function toHex(bytes: ArrayBuffer | Uint8Array): string {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
  let hex = ''
  for (let i = 0; i < arr.length; i += 1) {
    hex += arr[i].toString(16).padStart(2, '0')
  }
  return hex
}

export function generateFileKey(): Uint8Array<ArrayBuffer> {
  const key = new Uint8Array(new ArrayBuffer(32))
  crypto.getRandomValues(key)
  return key
}

function buildAad(aadContext: string, chunkIndex: number): Uint8Array<ArrayBuffer> {
  const bytes = TEXT_ENCODER.encode(`studiolo:blob:${aadContext}:${chunkIndex}`)
  const out = new Uint8Array(new ArrayBuffer(bytes.byteLength))
  out.set(bytes)
  return out
}

async function importAesKey(rawKey: Uint8Array<ArrayBuffer>, usages: KeyUsage[]): Promise<CryptoKey> {
  if (rawKey.byteLength !== 32) {
    throw new Error('AES-256-GCM 密钥必须为 32 字节')
  }
  return crypto.subtle.importKey('raw', rawKey, { name: 'AES-GCM', length: 256 }, false, usages)
}

export async function sha256Hex(data: Uint8Array): Promise<string> {
  const buf = new Uint8Array(new ArrayBuffer(data.byteLength))
  buf.set(data)
  const digest = await crypto.subtle.digest('SHA-256', buf)
  return toHex(digest)
}

export async function encryptChunk(
  rawKey: Uint8Array<ArrayBuffer>,
  aadContext: string,
  chunkIndex: number,
  plaintext: Uint8Array,
): Promise<Uint8Array<ArrayBuffer>> {
  const key = await importAesKey(rawKey, ['encrypt'])
  const iv = new Uint8Array(new ArrayBuffer(NONCE_BYTES))
  crypto.getRandomValues(iv)
  const plainBuf = new Uint8Array(new ArrayBuffer(plaintext.byteLength))
  plainBuf.set(plaintext)

  const encrypted = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv, additionalData: buildAad(aadContext, chunkIndex), tagLength: 128 },
      key,
      plainBuf,
    ),
  )

  const wire = new Uint8Array(new ArrayBuffer(NONCE_BYTES + encrypted.byteLength))
  wire.set(iv, 0)
  wire.set(encrypted, NONCE_BYTES)
  return wire
}

export async function decryptChunk(
  rawKey: Uint8Array<ArrayBuffer>,
  aadContext: string,
  chunkIndex: number,
  wireChunk: Uint8Array,
): Promise<Uint8Array<ArrayBuffer>> {
  if (wireChunk.byteLength <= NONCE_BYTES + 16) {
    throw new Error(`分块 #${chunkIndex} 长度异常或被截断`)
  }
  const key = await importAesKey(rawKey, ['decrypt'])
  const iv = new Uint8Array(new ArrayBuffer(NONCE_BYTES))
  iv.set(wireChunk.subarray(0, NONCE_BYTES))
  const cipher = new Uint8Array(new ArrayBuffer(wireChunk.byteLength - NONCE_BYTES))
  cipher.set(wireChunk.subarray(NONCE_BYTES))

  const plain = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv, additionalData: buildAad(aadContext, chunkIndex), tagLength: 128 },
    key,
    cipher,
  )
  return new Uint8Array(plain)
}

function concatChunks(parts: Uint8Array[]): Uint8Array<ArrayBuffer> {
  const total = parts.reduce((sum, p) => sum + p.byteLength, 0)
  const merged = new Uint8Array(new ArrayBuffer(total))
  let offset = 0
  for (const part of parts) {
    merged.set(part, offset)
    offset += part.byteLength
  }
  return merged
}

/**
 * 在浏览器端分块加密 File/Blob，并上传至 Edge Relay（优先）或 Core Blob 仓库。
 * 密钥 `keyB64` 仅保留在返回值中随对话消息透传，不会提交到后端存储。
 */
export async function encryptAndUploadFile(options: {
  file: File
  token: string
  apiBaseUrl?: string
  chunkSize?: number
  onProgress?: (uploadedChunks: number, totalChunks: number) => void
}): Promise<ArtifactRef> {
  const { file, token, apiBaseUrl = '', chunkSize = DEFAULT_CHUNK_SIZE, onProgress } = options
  const rawBuffer = new Uint8Array(await file.arrayBuffer())
  const key = generateFileKey()
  const aadContext = crypto.randomUUID()

  const encChunks: Uint8Array<ArrayBuffer>[] = []
  const chunkDigests: string[] = []
  const totalSlices = Math.max(1, Math.ceil(rawBuffer.byteLength / chunkSize))

  for (let idx = 0; idx < totalSlices; idx += 1) {
    const start = idx * chunkSize
    const slice = rawBuffer.subarray(start, Math.min(rawBuffer.byteLength, start + chunkSize))
    const enc = await encryptChunk(key, aadContext, idx, slice)
    encChunks.push(enc)
    chunkDigests.push(await sha256Hex(enc))
  }

  const allCipher = concatChunks(encChunks)
  const fullDigest = await sha256Hex(allCipher)
  const perChunkMax = Math.max(1024, ...encChunks.map(c => c.byteLength))
  const manifest = {
    alg: 'AES-256-GCM',
    aadContext,
    fileName: file.name,
    mime: file.type || 'application/octet-stream',
    plaintextSize: file.size,
  }

  const initRes = await fetch(`${apiBaseUrl}/api/v1/fleet/artifacts/init`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      purpose: 'fleet_artifact',
      digest: fullDigest,
      ciphertextSize: allCipher.byteLength,
      chunkSize: perChunkMax,
      chunkCount: encChunks.length,
      storageRole: 'core',
      manifest,
    }),
  })
  if (!initRes.ok) {
    throw new Error(`初始化加密文件传输失败 (${initRes.status})`)
  }
  const initData = (await initRes.json()) as { blob: BlobOut; endpoints: ResolvedEndpoint[] }
  const artifactId = initData.blob.id
  let uploadedRole: EndpointKind | 'core' = 'core'

  const edgeEp = initData.endpoints.find(ep => ep.kind === 'edge_relay' && ep.ticket)
  if (edgeEp && edgeEp.ticket) {
    try {
      for (let i = 0; i < encChunks.length; i += 1) {
        const putRes = await fetch(`${edgeEp.url}/chunks/${i}`, {
          method: 'PUT',
          headers: {
            Authorization: `Bearer ${edgeEp.ticket}`,
            'X-Chunk-Sha256': chunkDigests[i],
          },
          body: encChunks[i],
        })
        if (!putRes.ok) throw new Error(`Edge Relay chunk ${i} failed`)
        onProgress?.(i + 1, encChunks.length)
      }
      const commitEdge = await fetch(`${edgeEp.url}/commit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${edgeEp.ticket}`,
        },
        body: JSON.stringify({
          digest: fullDigest,
          ciphertextSize: allCipher.byteLength,
          chunkCount: encChunks.length,
        }),
      })
      if (!commitEdge.ok) throw new Error('Edge Relay commit failed')
      uploadedRole = 'edge_relay'
    } catch {
      uploadedRole = 'core'
    }
  }

  if (uploadedRole === 'core') {
    for (let i = 0; i < encChunks.length; i += 1) {
      const putRes = await fetch(`${apiBaseUrl}/api/v1/fleet/artifacts/${artifactId}/chunks/${i}`, {
        method: 'PUT',
        headers: {
          Authorization: `Bearer ${token}`,
          'X-Chunk-Sha256': chunkDigests[i],
        },
        body: encChunks[i],
      })
      if (!putRes.ok) throw new Error(`上传密文分块 #${i} 失败 (${putRes.status})`)
      onProgress?.(i + 1, encChunks.length)
    }
  }

  const commitRes = await fetch(`${apiBaseUrl}/api/v1/fleet/artifacts/${artifactId}/commit`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ storageRole: uploadedRole, manifest }),
  })
  if (!commitRes.ok) {
    throw new Error(`提交加密产物失败 (${commitRes.status})`)
  }

  return {
    artifactId,
    aadContext,
    fileName: file.name,
    mime: file.type || 'application/octet-stream',
    plaintextSize: file.size,
    ciphertextSize: allCipher.byteLength,
    chunkCount: encChunks.length,
    digest: fullDigest,
    keyB64: encodeBase64Url(key),
    storageRole: uploadedRole,
  }
}

/**
 * 浏览器端按 LAN 直连 -> Edge Relay -> Core 顺序拉取密文分块并验证解密为明文 Blob。
 */
export async function downloadAndDecryptBlob(options: {
  artifact: ArtifactRef
  token: string
  apiBaseUrl?: string
  onProgress?: (downloadedChunks: number, totalChunks: number) => void
}): Promise<{ blob: Blob; transport: EndpointKind; fileName: string }> {
  const { artifact, token, apiBaseUrl = '', onProgress } = options
  const epRes = await fetch(`${apiBaseUrl}/api/v1/fleet/artifacts/${artifact.artifactId}/endpoints`, {
    headers: { Authorization: `Bearer ${token}` },
    redirect: 'error',
  })
  if (!epRes.ok) {
    throw new Error(`解析文件传输端点失败 (${epRes.status})`)
  }
  const epPayload = (await epRes.json()) as BlobEndpointsOut
  const chunkCount = epPayload.blob.chunkCount
  const key = decodeBase64Url(artifact.keyB64)
  const aadContext = artifact.aadContext || artifact.artifactId

  for (const ep of epPayload.endpoints) {
    const base = ep.kind === 'core' ? `${apiBaseUrl}/api/v1/fleet/artifacts/${artifact.artifactId}` : ep.url
    const headers: Record<string, string> = {}
    if (ep.kind === 'core') headers.Authorization = `Bearer ${token}`
    else if (ep.kind === 'edge_relay' && ep.ticket) headers.Authorization = `Bearer ${ep.ticket}`
    else if ((ep.kind === 'lan' || ep.kind === 'xtcp') && artifact.directToken) headers['X-Transfer-Token'] = artifact.directToken
    else continue

    try {
      const plainParts: Uint8Array[] = []
      for (let i = 0; i < chunkCount; i += 1) {
        const controller = new AbortController()
        // LAN/XTCP 端点设置短超时，不可达时快速无缝降级到 Edge Relay 或 Core
        const timer = setTimeout(() => controller.abort(), ep.kind === 'lan' || ep.kind === 'xtcp' ? 2000 : 30000)
        try {
          const res = await fetch(`${base}/chunks/${i}`, { headers, signal: controller.signal, redirect: 'error' })
          if (!res.ok) throw new Error(`HTTP ${res.status}`)
          const encBytes = new Uint8Array(await res.arrayBuffer())
          const plain = await decryptChunk(key, aadContext, i, encBytes)
          plainParts.push(plain)
          onProgress?.(i + 1, chunkCount)
        } finally {
          clearTimeout(timer)
        }
      }
      const merged = concatChunks(plainParts)
      return {
        blob: new Blob([merged], { type: artifact.mime || 'application/octet-stream' }),
        transport: ep.kind,
        fileName: artifact.fileName,
      }
    } catch {
      continue
    }
  }

  throw new Error(`无法从任何可用通道下载加密文件 ${artifact.fileName}`)
}
