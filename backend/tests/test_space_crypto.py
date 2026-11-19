"""Shared Space 密码学跨语言向量与安全边界单元测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.space.crypto import (
    Argon2Params,
    SpaceCryptoError,
    SpacePasswordMismatchError,
    UnsupportedEnvelopeVersionError,
    b64url_decode,
    b64url_encode,
    decrypt_chunk,
    decrypt_manifest,
    derive_kek,
    derive_vault_workspace_key,
    encrypt_chunk,
    encrypt_manifest,
    hash_space_password,
    sha256_hex,
    unwrap_dek,
    unwrap_space_key,
    verify_space_password,
    wrap_dek,
    wrap_space_key,
)


VECTORS_PATH = Path(__file__).resolve().parents[2] / "packages" / "contracts" / "shared-space-crypto-v1.vectors.json"


def _load_vectors() -> dict:
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


def test_cross_language_crypto_vectors_match_byte_for_byte():
    vec = _load_vectors()
    scope = vec["scope"]
    inp = vec["inputs"]
    exp = vec["expected"]

    params = Argon2Params(
        m=inp["kdf"]["m"],
        t=inp["kdf"]["t"],
        p=inp["kdf"]["p"],
        dk_len=inp["kdf"]["dkLen"],
    )
    salt = b64url_decode(inp["saltB64"])
    space_key = b64url_decode(inp["spaceKeyB64"])
    dek = b64url_decode(inp["dekB64"])

    kek = derive_kek(inp["password"], salt, params, allow_low_cost_for_vectors=True)
    assert kek.hex() == exp["kekHex"]

    envelope = wrap_space_key(
        password=inp["password"],
        space_key=space_key,
        workspace_id=scope["workspaceId"],
        space_id=scope["spaceId"],
        epoch=scope["epoch"],
        params=params,
        salt=salt,
        nonce=b64url_decode(inp["nonces"]["envelopeB64"]),
        allow_low_cost_for_vectors=True,
    )
    assert envelope == exp["keyEnvelope"]

    unwrapped_space_key = unwrap_space_key(
        password=inp["password"],
        envelope=exp["keyEnvelope"],
        workspace_id=scope["workspaceId"],
        space_id=scope["spaceId"],
        expected_epoch=scope["epoch"],
        allow_low_cost_for_vectors=True,
    )
    assert unwrapped_space_key == space_key

    wrapped_dek = wrap_dek(
        wrapping_key=space_key,
        dek=dek,
        workspace_id=scope["workspaceId"],
        space_id=scope["spaceId"],
        entry_id=scope["entryId"],
        revision=scope["revision"],
        epoch=scope["epoch"],
        nonce=b64url_decode(inp["nonces"]["dekB64"]),
    )
    assert wrapped_dek == exp["wrappedDek"]

    unwrapped_dek = unwrap_dek(
        wrapping_key=space_key,
        wrapped_dek=exp["wrappedDek"],
        workspace_id=scope["workspaceId"],
        space_id=scope["spaceId"],
        entry_id=scope["entryId"],
        revision=scope["revision"],
        expected_epoch=scope["epoch"],
    )
    assert unwrapped_dek == dek

    enc_manifest = encrypt_manifest(
        dek=dek,
        manifest=inp["manifest"],
        workspace_id=scope["workspaceId"],
        space_id=scope["spaceId"],
        entry_id=scope["entryId"],
        revision=scope["revision"],
        epoch=scope["epoch"],
        nonce=b64url_decode(inp["nonces"]["manifestB64"]),
    )
    assert enc_manifest == exp["encryptedManifestB64"]

    dec_manifest = decrypt_manifest(
        dek=dek,
        encrypted_manifest_b64=exp["encryptedManifestB64"],
        workspace_id=scope["workspaceId"],
        space_id=scope["spaceId"],
        entry_id=scope["entryId"],
        revision=scope["revision"],
        epoch=scope["epoch"],
    )
    assert dec_manifest == inp["manifest"]

    for idx, expected_chunk in enumerate(exp["encryptedChunks"]):
        pt = b64url_decode(inp["chunksPlaintextB64"][idx])
        nonce_key = f"chunk{idx}B64"
        ct = encrypt_chunk(
            dek=dek,
            plaintext=pt,
            workspace_id=scope["workspaceId"],
            space_id=scope["spaceId"],
            entry_id=scope["entryId"],
            revision=scope["revision"],
            chunk_index=idx,
            epoch=scope["epoch"],
            nonce=b64url_decode(inp["nonces"][nonce_key]),
        )
        assert b64url_encode(ct) == expected_chunk["ciphertextB64"]
        assert sha256_hex(ct) == expected_chunk["sha256"]

        recovered = decrypt_chunk(
            dek=dek,
            ciphertext_chunk=b64url_decode(expected_chunk["ciphertextB64"]),
            workspace_id=scope["workspaceId"],
            space_id=scope["spaceId"],
            entry_id=scope["entryId"],
            revision=scope["revision"],
            chunk_index=idx,
            epoch=scope["epoch"],
        )
        assert recovered == pt


def test_wrong_password_tampering_and_aad_isolation_are_rejected():
    vec = _load_vectors()
    scope = vec["scope"]
    inp = vec["inputs"]
    exp = vec["expected"]
    space_key = b64url_decode(inp["spaceKeyB64"])
    dek = b64url_decode(inp["dekB64"])

    # 1. 错误密码解包 KeyEnvelope
    with pytest.raises(SpacePasswordMismatchError):
        unwrap_space_key(
            password=inp["wrongPassword"],
            envelope=exp["keyEnvelope"],
            workspace_id=scope["workspaceId"],
            space_id=scope["spaceId"],
            allow_low_cost_for_vectors=True,
        )

    # 2. 跨工作区或跨空间 AAD 移植拒绝
    with pytest.raises(SpacePasswordMismatchError):
        unwrap_space_key(
            password=inp["password"],
            envelope=exp["keyEnvelope"],
            workspace_id="ws-other",
            space_id=scope["spaceId"],
            allow_low_cost_for_vectors=True,
        )

    # 3. 生产模式下拒绝低于安全底线的 Argon2id 参数
    with pytest.raises(SpaceCryptoError):
        unwrap_space_key(
            password=inp["password"],
            envelope=exp["keyEnvelope"],
            workspace_id=scope["workspaceId"],
            space_id=scope["spaceId"],
            allow_low_cost_for_vectors=False,
        )

    # 4. 不支持的封套版本拒绝
    bad_ver = dict(exp["keyEnvelope"], version=99)
    with pytest.raises(UnsupportedEnvelopeVersionError):
        unwrap_space_key(
            password=inp["password"],
            envelope=bad_ver,
            workspace_id=scope["workspaceId"],
            space_id=scope["spaceId"],
            allow_low_cost_for_vectors=True,
        )

    # 5. WrappedDek 跨 revision 移植拒绝
    with pytest.raises(SpacePasswordMismatchError):
        unwrap_dek(
            wrapping_key=space_key,
            wrapped_dek=exp["wrappedDek"],
            workspace_id=scope["workspaceId"],
            space_id=scope["spaceId"],
            entry_id=scope["entryId"],
            revision=scope["revision"] + 1,
        )

    # 6. 分块序号置换或字节篡改拒绝
    chunk0_ct = bytearray(b64url_decode(exp["encryptedChunks"][0]["ciphertextB64"]))
    with pytest.raises(SpacePasswordMismatchError):
        decrypt_chunk(
            dek=dek,
            ciphertext_chunk=bytes(chunk0_ct),
            workspace_id=scope["workspaceId"],
            space_id=scope["spaceId"],
            entry_id=scope["entryId"],
            revision=scope["revision"],
            chunk_index=1,
            epoch=scope["epoch"],
        )

    chunk0_ct[-1] ^= 0x01
    with pytest.raises(SpacePasswordMismatchError):
        decrypt_chunk(
            dek=dek,
            ciphertext_chunk=bytes(chunk0_ct),
            workspace_id=scope["workspaceId"],
            space_id=scope["spaceId"],
            entry_id=scope["entryId"],
            revision=scope["revision"],
            chunk_index=0,
            epoch=scope["epoch"],
        )


def test_protected_tier_vault_key_and_password_verifier():
    vec = _load_vectors()
    scope = vec["scope"]
    inp = vec["inputs"]
    exp = vec["expected"]

    ws_key = derive_vault_workspace_key(inp["vaultMasterKey"], scope["workspaceId"])
    assert ws_key.hex() == exp["vaultWorkspaceKeyHex"]
    other_ws_key = derive_vault_workspace_key(inp["vaultMasterKey"], "ws-other")
    assert ws_key != other_ws_key

    assert verify_space_password(
        inp["password"],
        exp["protectedPasswordVerifier"],
        allow_low_cost_for_vectors=True,
    )
    assert not verify_space_password(
        inp["wrongPassword"],
        exp["protectedPasswordVerifier"],
        allow_low_cost_for_vectors=True,
    )

    # 生产默认参数哈希与校验往返
    prod_verifier = hash_space_password("Prod-Vault-Pass!2026")
    assert verify_space_password("Prod-Vault-Pass!2026", prod_verifier) is True
    assert verify_space_password("Wrong-Vault-Pass!2026", prod_verifier) is False
