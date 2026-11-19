import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import {
  DEFAULT_ARGON2_PARAMS,
  SpaceCryptoError,
  SpacePasswordMismatchError,
  UnsupportedEnvelopeVersionError,
  b64urlDecode,
  b64urlEncode,
  createRotatedEpochEnvelope,
  decryptChunk,
  decryptManifest,
  deriveKek,
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
} from '../src/services/spaceCrypto.ts'

const vectorsPath = resolve(process.cwd(), 'packages/contracts/shared-space-crypto-v1.vectors.json')
const vectors = JSON.parse(readFileSync(vectorsPath, 'utf8'))

function bytesToHex(bytes) {
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
}

test('TS 实现与 Python 生成的 shared-space-crypto-v1 跨语言向量逐字节一致', async () => {
  const { scope, inputs, expected } = vectors
  const salt = b64urlDecode(inputs.saltB64)
  const spaceKey = b64urlDecode(inputs.spaceKeyB64)
  const dek = b64urlDecode(inputs.dekB64)

  const kek = deriveKek(inputs.password, salt, inputs.kdf, { allowLowCostForVectors: true })
  assert.equal(bytesToHex(kek), expected.kekHex)

  const envelope = await wrapSpaceKey({
    password: inputs.password,
    spaceKey,
    workspaceId: scope.workspaceId,
    spaceId: scope.spaceId,
    epoch: scope.epoch,
    params: inputs.kdf,
    salt,
    nonce: b64urlDecode(inputs.nonces.envelopeB64),
    allowLowCostForVectors: true,
  })
  assert.deepEqual(envelope, expected.keyEnvelope)

  const unwrappedSpaceKey = await unwrapSpaceKey({
    password: inputs.password,
    envelope: expected.keyEnvelope,
    workspaceId: scope.workspaceId,
    spaceId: scope.spaceId,
    expectedEpoch: scope.epoch,
    allowLowCostForVectors: true,
  })
  assert.deepEqual(Array.from(unwrappedSpaceKey), Array.from(spaceKey))

  const wrappedDek = await wrapDek({
    wrappingKey: spaceKey,
    dek,
    scope,
    nonce: b64urlDecode(inputs.nonces.dekB64),
  })
  assert.deepEqual(wrappedDek, expected.wrappedDek)

  const unwrappedDek = await unwrapDek({
    wrappingKey: spaceKey,
    wrappedDek: expected.wrappedDek,
    scope,
  })
  assert.deepEqual(Array.from(unwrappedDek), Array.from(dek))

  const encManifest = await encryptManifest({
    dek,
    manifest: inputs.manifest,
    scope,
    nonce: b64urlDecode(inputs.nonces.manifestB64),
  })
  assert.equal(encManifest, expected.encryptedManifestB64)

  const decManifest = await decryptManifest({
    dek,
    encryptedManifestB64: expected.encryptedManifestB64,
    scope,
  })
  assert.deepEqual(decManifest, inputs.manifest)

  for (const expectedChunk of expected.encryptedChunks) {
    const idx = expectedChunk.chunkIndex
    const pt = b64urlDecode(inputs.chunksPlaintextB64[idx])
    const nonce = b64urlDecode(inputs.nonces[`chunk${idx}B64`])
    const ct = await encryptChunk({ dek, plaintext: pt, scope, chunkIndex: idx, nonce })
    assert.equal(b64urlEncode(ct), expectedChunk.ciphertextB64)
    assert.equal(await sha256Hex(ct), expectedChunk.sha256)

    const recovered = await decryptChunk({
      dek,
      ciphertextChunk: b64urlDecode(expectedChunk.ciphertextB64),
      scope,
      chunkIndex: idx,
    })
    assert.deepEqual(Array.from(recovered), Array.from(pt))
  }
})

test('错误密码、AAD 跨租户移植、篡改分块、低成本参数与未知版本均被拒绝', async () => {
  const { scope, inputs, expected } = vectors
  const dek = b64urlDecode(inputs.dekB64)

  await assert.rejects(
    () =>
      unwrapSpaceKey({
        password: inputs.wrongPassword,
        envelope: expected.keyEnvelope,
        workspaceId: scope.workspaceId,
        spaceId: scope.spaceId,
        allowLowCostForVectors: true,
      }),
    SpacePasswordMismatchError,
  )

  await assert.rejects(
    () =>
      unwrapSpaceKey({
        password: inputs.password,
        envelope: expected.keyEnvelope,
        workspaceId: 'ws-other',
        spaceId: scope.spaceId,
        allowLowCostForVectors: true,
      }),
    SpacePasswordMismatchError,
  )

  await assert.rejects(
    () =>
      unwrapSpaceKey({
        password: inputs.password,
        envelope: expected.keyEnvelope,
        workspaceId: scope.workspaceId,
        spaceId: scope.spaceId,
        allowLowCostForVectors: false,
      }),
    SpaceCryptoError,
  )

  await assert.rejects(
    () =>
      unwrapSpaceKey({
        password: inputs.password,
        envelope: { ...expected.keyEnvelope, version: 2 },
        workspaceId: scope.workspaceId,
        spaceId: scope.spaceId,
        allowLowCostForVectors: true,
      }),
    UnsupportedEnvelopeVersionError,
  )

  const tampered = b64urlDecode(expected.encryptedChunks[0].ciphertextB64)
  tampered[tampered.byteLength - 1] ^= 0xff
  await assert.rejects(
    () =>
      decryptChunk({
        dek,
        ciphertextChunk: tampered,
        scope,
        chunkIndex: 0,
      }),
    SpacePasswordMismatchError,
  )

  await assert.rejects(
    () =>
      decryptChunk({
        dek,
        ciphertextChunk: b64urlDecode(expected.encryptedChunks[0].ciphertextB64),
        scope,
        chunkIndex: 1,
      }),
    SpacePasswordMismatchError,
  )
})

test('常规改密保持原 Space Key 与 epoch、泄露轮换生成新 Space Key 与递增 epoch，且 zeroizeBytes 清零内存', async () => {
  const workspaceId = 'ws-prod-1'
  const spaceId = 'sp-e2ee-1'
  const initialSpaceKey = randomBytes(32)
  const initialCopy = new Uint8Array(initialSpaceKey)

  const env1 = await wrapSpaceKey({
    password: 'Old-Strong-Password!1',
    spaceKey: initialSpaceKey,
    workspaceId,
    spaceId,
    epoch: 1,
    params: DEFAULT_ARGON2_PARAMS,
  })

  // 常规改密：重包封套，保持原 Space Key 和 epoch=1
  const envRewrapped = await rewrapEnvelopeForPasswordChange({
    oldPassword: 'Old-Strong-Password!1',
    newPassword: 'New-Strong-Password!2',
    currentEnvelope: env1,
    workspaceId,
    spaceId,
    params: DEFAULT_ARGON2_PARAMS,
  })
  assert.equal(envRewrapped.epoch, 1)
  assert.notEqual(envRewrapped.kdf.saltB64, env1.kdf.saltB64)

  const recoveredAfterPwdChange = await unwrapSpaceKey({
    password: 'New-Strong-Password!2',
    envelope: envRewrapped,
    workspaceId,
    spaceId,
    expectedEpoch: 1,
  })
  assert.deepEqual(Array.from(recoveredAfterPwdChange), Array.from(initialCopy))

  // 泄露轮换：生成新随机 Space Key 与 epoch=2
  const rotated = await createRotatedEpochEnvelope({
    newPassword: 'Rotated-Epoch-Password!3',
    workspaceId,
    spaceId,
    currentEpoch: 1,
    params: DEFAULT_ARGON2_PARAMS,
  })
  assert.equal(rotated.nextEpoch, 2)
  assert.equal(rotated.envelope.epoch, 2)
  assert.notDeepEqual(Array.from(rotated.nextSpaceKey), Array.from(initialCopy))

  const recoveredEpoch2 = await unwrapSpaceKey({
    password: 'Rotated-Epoch-Password!3',
    envelope: rotated.envelope,
    workspaceId,
    spaceId,
    expectedEpoch: 2,
  })
  assert.deepEqual(Array.from(recoveredEpoch2), Array.from(rotated.nextSpaceKey))

  zeroizeBytes(initialSpaceKey, recoveredAfterPwdChange, rotated.nextSpaceKey, recoveredEpoch2)
  assert.ok(initialSpaceKey.every(b => b === 0))
  assert.ok(recoveredEpoch2.every(b => b === 0))
})
