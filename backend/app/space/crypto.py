"""Studiolo Shared Space 密码学实现（与 packages/contracts/shared-space-crypto-v1.md 逐字节对齐）。

职责划分：
1. 为 `e2ee` 档提供跨语言测试向量校验与桌面本地/CLI 侧加解密原语；
2. 为 `protected` 档提供服务端信封加密（HKDF-SHA256 + AES-256-GCM）及 UI 空间口令 Argon2id 校验。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


CRYPTO_PROTOCOL_VERSION = 1
AEAD_ALGORITHM = "aes-256-gcm"
KDF_ALGORITHM = "argon2id"

DEFAULT_CHUNK_SIZE = 2 * 1024 * 1024  # 2 MiB
KEY_BYTES = 32
NONCE_BYTES = 12
TAG_BYTES = 16
SALT_BYTES = 16

DEFAULT_ARGON2_MEMORY_KIB = 19456
DEFAULT_ARGON2_ITERATIONS = 2
DEFAULT_ARGON2_LANES = 1

MIN_PROD_MEMORY_KIB = 19456
MIN_PROD_ITERATIONS = 2
MIN_VECTOR_MEMORY_KIB = 1024
MIN_VECTOR_ITERATIONS = 1
MAX_MEMORY_KIB = 262144
MAX_ITERATIONS = 16
MAX_LANES = 4


class SpaceCryptoError(ValueError):
    """Shared Space 密码学通用错误。"""


class UnsupportedEnvelopeVersionError(SpaceCryptoError):
    """不支持的封套协议版本或算法。"""


class SpacePasswordMismatchError(SpaceCryptoError):
    """空间密码错误或密文/AAD 校验失败。"""


@dataclass(frozen=True)
class Argon2Params:
    m: int = DEFAULT_ARGON2_MEMORY_KIB
    t: int = DEFAULT_ARGON2_ITERATIONS
    p: int = DEFAULT_ARGON2_LANES
    dk_len: int = KEY_BYTES


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(encoded: str) -> bytes:
    if not isinstance(encoded, str) or not encoded:
        raise SpaceCryptoError("Base64URL 字段不能为空")
    padding = "=" * ((4 - len(encoded) % 4) % 4)
    try:
        return base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
    except Exception as exc:
        raise SpaceCryptoError("无效的 Base64URL 编码") from exc


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_non_empty_id(name: str, value: str) -> str:
    if not isinstance(value, str) or not value or ":" in value:
        raise SpaceCryptoError(f"无效的 {name} 标识")
    return value


def _validate_positive_int(name: str, value: int, minimum: int = 1) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise SpaceCryptoError(f"{name} 必须为不小于 {minimum} 的整数")
    return value


def build_envelope_aad(*, workspace_id: str, space_id: str, epoch: int) -> bytes:
    ws = _validate_non_empty_id("workspace_id", workspace_id)
    sp = _validate_non_empty_id("space_id", space_id)
    ep = _validate_positive_int("epoch", epoch, 1)
    return f"studiolo:space:v1:{ws}:{sp}:envelope:{ep}".encode("utf-8")


def build_dek_aad(*, workspace_id: str, space_id: str, entry_id: str, revision: int, epoch: int) -> bytes:
    ws = _validate_non_empty_id("workspace_id", workspace_id)
    sp = _validate_non_empty_id("space_id", space_id)
    en = _validate_non_empty_id("entry_id", entry_id)
    rev = _validate_positive_int("revision", revision, 1)
    ep = _validate_positive_int("epoch", epoch, 1)
    return f"studiolo:space:v1:{ws}:{sp}:{en}:{rev}:dek:{ep}".encode("utf-8")


def build_manifest_aad(*, workspace_id: str, space_id: str, entry_id: str, revision: int, epoch: int) -> bytes:
    ws = _validate_non_empty_id("workspace_id", workspace_id)
    sp = _validate_non_empty_id("space_id", space_id)
    en = _validate_non_empty_id("entry_id", entry_id)
    rev = _validate_positive_int("revision", revision, 1)
    ep = _validate_positive_int("epoch", epoch, 1)
    return f"studiolo:space:v1:{ws}:{sp}:{en}:{rev}:manifest:{ep}".encode("utf-8")


def build_chunk_aad(
    *,
    workspace_id: str,
    space_id: str,
    entry_id: str,
    revision: int,
    chunk_index: int,
    epoch: int,
) -> bytes:
    ws = _validate_non_empty_id("workspace_id", workspace_id)
    sp = _validate_non_empty_id("space_id", space_id)
    en = _validate_non_empty_id("entry_id", entry_id)
    rev = _validate_positive_int("revision", revision, 1)
    idx = _validate_positive_int("chunk_index", chunk_index, 0)
    ep = _validate_positive_int("epoch", epoch, 1)
    return f"studiolo:space:v1:{ws}:{sp}:{en}:{rev}:chunk:{idx}:{ep}".encode("utf-8")


def validate_argon2_params(params: Argon2Params, *, allow_low_cost_for_vectors: bool = False) -> None:
    min_m = MIN_VECTOR_MEMORY_KIB if allow_low_cost_for_vectors else MIN_PROD_MEMORY_KIB
    min_t = MIN_VECTOR_ITERATIONS if allow_low_cost_for_vectors else MIN_PROD_ITERATIONS
    if not (min_m <= params.m <= MAX_MEMORY_KIB):
        raise SpaceCryptoError(f"Argon2id memory_cost 越界: {params.m}")
    if not (min_t <= params.t <= MAX_ITERATIONS):
        raise SpaceCryptoError(f"Argon2id iterations 越界: {params.t}")
    if not (1 <= params.p <= MAX_LANES):
        raise SpaceCryptoError(f"Argon2id lanes 越界: {params.p}")
    if params.dk_len != KEY_BYTES:
        raise SpaceCryptoError(f"Argon2id dk_len 必须为 {KEY_BYTES}")


def derive_kek(
    password: str,
    salt: bytes,
    params: Argon2Params = Argon2Params(),
    *,
    allow_low_cost_for_vectors: bool = False,
) -> bytes:
    """使用 Argon2id 从用户密码和盐派生 32 字节 KEK。"""
    if not isinstance(password, str) or not password:
        raise SpaceCryptoError("密码不能为空")
    if not isinstance(salt, (bytes, bytearray)) or not (SALT_BYTES <= len(salt) <= 64):
        raise SpaceCryptoError("盐长度必须在 16 到 64 字节之间")
    validate_argon2_params(params, allow_low_cost_for_vectors=allow_low_cost_for_vectors)
    kdf = Argon2id(
        salt=bytes(salt),
        length=params.dk_len,
        iterations=params.t,
        lanes=params.p,
        memory_cost=params.m,
    )
    return kdf.derive(password.encode("utf-8"))


def _require_key_bytes(name: str, key: bytes) -> bytes:
    if not isinstance(key, (bytes, bytearray)) or len(key) != KEY_BYTES:
        raise SpaceCryptoError(f"{name} 必须为 {KEY_BYTES} 字节")
    return bytes(key)


def _require_nonce_bytes(nonce: bytes | None) -> bytes:
    if nonce is None:
        return secrets.token_bytes(NONCE_BYTES)
    if not isinstance(nonce, (bytes, bytearray)) or len(nonce) != NONCE_BYTES:
        raise SpaceCryptoError(f"nonce 必须为 {NONCE_BYTES} 字节")
    return bytes(nonce)


def wrap_space_key(
    *,
    password: str,
    space_key: bytes,
    workspace_id: str,
    space_id: str,
    epoch: int = 1,
    params: Argon2Params = Argon2Params(),
    salt: bytes | None = None,
    nonce: bytes | None = None,
    allow_low_cost_for_vectors: bool = False,
) -> dict[str, Any]:
    """用空间密码派生 KEK 并封装随机 Space Key，返回标准 KeyEnvelope dict。"""
    raw_space_key = _require_key_bytes("space_key", space_key)
    raw_salt = secrets.token_bytes(SALT_BYTES) if salt is None else bytes(salt)
    raw_nonce = _require_nonce_bytes(nonce)
    kek = derive_kek(password, raw_salt, params, allow_low_cost_for_vectors=allow_low_cost_for_vectors)
    aad = build_envelope_aad(workspace_id=workspace_id, space_id=space_id, epoch=epoch)
    wrapped = AESGCM(kek).encrypt(raw_nonce, raw_space_key, aad)
    return {
        "version": CRYPTO_PROTOCOL_VERSION,
        "epoch": epoch,
        "kdf": {
            "algorithm": KDF_ALGORITHM,
            "m": params.m,
            "t": params.t,
            "p": params.p,
            "dkLen": params.dk_len,
            "saltB64": b64url_encode(raw_salt),
        },
        "aead": AEAD_ALGORITHM,
        "nonceB64": b64url_encode(raw_nonce),
        "wrappedKeyB64": b64url_encode(wrapped),
    }


def unwrap_space_key(
    *,
    password: str,
    envelope: dict[str, Any],
    workspace_id: str,
    space_id: str,
    expected_epoch: int | None = None,
    allow_low_cost_for_vectors: bool = False,
) -> bytes:
    """校验 KeyEnvelope 并使用当次输入密码解包 Space Key。"""
    if not isinstance(envelope, dict):
        raise UnsupportedEnvelopeVersionError("无效的 KeyEnvelope 对象")
    if envelope.get("version") != CRYPTO_PROTOCOL_VERSION:
        raise UnsupportedEnvelopeVersionError(f"不支持的封套版本: {envelope.get('version')}")
    if envelope.get("aead") != AEAD_ALGORITHM:
        raise UnsupportedEnvelopeVersionError(f"不支持的 AEAD 算法: {envelope.get('aead')}")
    epoch = _validate_positive_int("epoch", envelope.get("epoch"), 1)
    if expected_epoch is not None and epoch != expected_epoch:
        raise SpacePasswordMismatchError("KeyEnvelope epoch 与预期不匹配")

    kdf = envelope.get("kdf")
    if not isinstance(kdf, dict) or kdf.get("algorithm") != KDF_ALGORITHM:
        raise UnsupportedEnvelopeVersionError("不支持的 KDF 算法")
    params = Argon2Params(
        m=int(kdf.get("m", 0)),
        t=int(kdf.get("t", 0)),
        p=int(kdf.get("p", 0)),
        dk_len=int(kdf.get("dkLen", 0)),
    )
    salt = b64url_decode(str(kdf.get("saltB64", "")))
    nonce = b64url_decode(str(envelope.get("nonceB64", "")))
    wrapped = b64url_decode(str(envelope.get("wrappedKeyB64", "")))
    if len(nonce) != NONCE_BYTES or len(wrapped) != KEY_BYTES + TAG_BYTES:
        raise SpaceCryptoError("KeyEnvelope 长度异常")

    kek = derive_kek(password, salt, params, allow_low_cost_for_vectors=allow_low_cost_for_vectors)
    aad = build_envelope_aad(workspace_id=workspace_id, space_id=space_id, epoch=epoch)
    try:
        space_key = AESGCM(kek).decrypt(nonce, wrapped, aad)
    except InvalidTag as exc:
        raise SpacePasswordMismatchError("空间密码错误或封套已被篡改") from exc
    return _require_key_bytes("space_key", space_key)


def wrap_dek(
    *,
    wrapping_key: bytes,
    dek: bytes,
    workspace_id: str,
    space_id: str,
    entry_id: str,
    revision: int,
    epoch: int = 1,
    nonce: bytes | None = None,
) -> dict[str, Any]:
    """用 Space Key（e2ee）或 WorkspaceVaultKey（protected）封装每修订 DEK。"""
    raw_wrap_key = _require_key_bytes("wrapping_key", wrapping_key)
    raw_dek = _require_key_bytes("dek", dek)
    raw_nonce = _require_nonce_bytes(nonce)
    aad = build_dek_aad(
        workspace_id=workspace_id,
        space_id=space_id,
        entry_id=entry_id,
        revision=revision,
        epoch=epoch,
    )
    wrapped = AESGCM(raw_wrap_key).encrypt(raw_nonce, raw_dek, aad)
    return {
        "version": CRYPTO_PROTOCOL_VERSION,
        "epoch": epoch,
        "aead": AEAD_ALGORITHM,
        "nonceB64": b64url_encode(raw_nonce),
        "wrappedDekB64": b64url_encode(wrapped),
    }


def unwrap_dek(
    *,
    wrapping_key: bytes,
    wrapped_dek: dict[str, Any],
    workspace_id: str,
    space_id: str,
    entry_id: str,
    revision: int,
    expected_epoch: int | None = None,
) -> bytes:
    """解包条目修订 DEK，校验版本、算法与 AAD 绑定。"""
    raw_wrap_key = _require_key_bytes("wrapping_key", wrapping_key)
    if not isinstance(wrapped_dek, dict):
        raise UnsupportedEnvelopeVersionError("无效的 WrappedDek 对象")
    if wrapped_dek.get("version") != CRYPTO_PROTOCOL_VERSION:
        raise UnsupportedEnvelopeVersionError(f"不支持的 DEK 封套版本: {wrapped_dek.get('version')}")
    if wrapped_dek.get("aead") != AEAD_ALGORITHM:
        raise UnsupportedEnvelopeVersionError(f"不支持的 AEAD 算法: {wrapped_dek.get('aead')}")
    epoch = _validate_positive_int("epoch", wrapped_dek.get("epoch"), 1)
    if expected_epoch is not None and epoch != expected_epoch:
        raise SpacePasswordMismatchError("WrappedDek epoch 与预期不匹配")

    nonce = b64url_decode(str(wrapped_dek.get("nonceB64", "")))
    ciphertext = b64url_decode(str(wrapped_dek.get("wrappedDekB64", "")))
    if len(nonce) != NONCE_BYTES or len(ciphertext) != KEY_BYTES + TAG_BYTES:
        raise SpaceCryptoError("WrappedDek 长度异常")
    aad = build_dek_aad(
        workspace_id=workspace_id,
        space_id=space_id,
        entry_id=entry_id,
        revision=revision,
        epoch=epoch,
    )
    try:
        dek = AESGCM(raw_wrap_key).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise SpacePasswordMismatchError("DEK 解包失败或密文已被篡改") from exc
    return _require_key_bytes("dek", dek)


def encrypt_manifest(
    *,
    dek: bytes,
    manifest: dict[str, Any],
    workspace_id: str,
    space_id: str,
    entry_id: str,
    revision: int,
    epoch: int = 1,
    nonce: bytes | None = None,
) -> str:
    """加密条目 Manifest JSON，返回 `12B Nonce || Ciphertext || 16B Tag` 的 Base64URL。"""
    raw_dek = _require_key_bytes("dek", dek)
    raw_nonce = _require_nonce_bytes(nonce)
    aad = build_manifest_aad(
        workspace_id=workspace_id,
        space_id=space_id,
        entry_id=entry_id,
        revision=revision,
        epoch=epoch,
    )
    plaintext = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ciphertext = AESGCM(raw_dek).encrypt(raw_nonce, plaintext, aad)
    return b64url_encode(raw_nonce + ciphertext)


def decrypt_manifest(
    *,
    dek: bytes,
    encrypted_manifest_b64: str,
    workspace_id: str,
    space_id: str,
    entry_id: str,
    revision: int,
    epoch: int = 1,
) -> dict[str, Any]:
    """解密条目 Manifest JSON。"""
    raw_dek = _require_key_bytes("dek", dek)
    blob = b64url_decode(encrypted_manifest_b64)
    if len(blob) < NONCE_BYTES + TAG_BYTES:
        raise SpaceCryptoError("加密 Manifest 长度不足")
    nonce, ciphertext = blob[:NONCE_BYTES], blob[NONCE_BYTES:]
    aad = build_manifest_aad(
        workspace_id=workspace_id,
        space_id=space_id,
        entry_id=entry_id,
        revision=revision,
        epoch=epoch,
    )
    try:
        plaintext = AESGCM(raw_dek).decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise SpacePasswordMismatchError("Manifest 解密失败或已被篡改") from exc
    data = json.loads(plaintext.decode("utf-8"))
    if not isinstance(data, dict):
        raise SpaceCryptoError("Manifest 必须为 JSON 对象")
    return data


def encrypt_chunk(
    *,
    dek: bytes,
    plaintext: bytes,
    workspace_id: str,
    space_id: str,
    entry_id: str,
    revision: int,
    chunk_index: int,
    epoch: int = 1,
    nonce: bytes | None = None,
) -> bytes:
    """加密单分块正文或文件块，返回 `12B Nonce || Ciphertext || 16B Tag`。"""
    raw_dek = _require_key_bytes("dek", dek)
    raw_nonce = _require_nonce_bytes(nonce)
    aad = build_chunk_aad(
        workspace_id=workspace_id,
        space_id=space_id,
        entry_id=entry_id,
        revision=revision,
        chunk_index=chunk_index,
        epoch=epoch,
    )
    return raw_nonce + AESGCM(raw_dek).encrypt(raw_nonce, bytes(plaintext), aad)


def decrypt_chunk(
    *,
    dek: bytes,
    ciphertext_chunk: bytes,
    workspace_id: str,
    space_id: str,
    entry_id: str,
    revision: int,
    chunk_index: int,
    epoch: int = 1,
) -> bytes:
    """解密单分块正文或文件块。"""
    raw_dek = _require_key_bytes("dek", dek)
    if not isinstance(ciphertext_chunk, (bytes, bytearray)) or len(ciphertext_chunk) < NONCE_BYTES + TAG_BYTES:
        raise SpaceCryptoError("密文分块长度不足")
    nonce = bytes(ciphertext_chunk[:NONCE_BYTES])
    body = bytes(ciphertext_chunk[NONCE_BYTES:])
    aad = build_chunk_aad(
        workspace_id=workspace_id,
        space_id=space_id,
        entry_id=entry_id,
        revision=revision,
        chunk_index=chunk_index,
        epoch=epoch,
    )
    try:
        return AESGCM(raw_dek).decrypt(nonce, body, aad)
    except InvalidTag as exc:
        raise SpacePasswordMismatchError("密文分块校验失败或已被篡改") from exc


# ---------------- Protected 档服务端信封加密与空间口令校验 ----------------


def derive_vault_workspace_key(master_key: str | bytes, workspace_id: str) -> bytes:
    """使用 HKDF-SHA256 从 STUDIOLO_VAULT_MASTER_KEY 派生按工作区隔离的 32B 包装密钥。"""
    raw_master = master_key.encode("utf-8") if isinstance(master_key, str) else bytes(master_key)
    if len(raw_master) < KEY_BYTES:
        raise SpaceCryptoError("STUDIOLO_VAULT_MASTER_KEY 长度至少需要 32 字节")
    ws = _validate_non_empty_id("workspace_id", workspace_id)
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=KEY_BYTES,
        salt=b"studiolo-vault-master-salt-v1",
        info=f"studiolo:vault:v1:workspace:{ws}".encode("utf-8"),
    )
    return hkdf.derive(raw_master)


def hash_space_password(
    password: str,
    params: Argon2Params = Argon2Params(),
    *,
    salt: bytes | None = None,
    allow_low_cost_for_vectors: bool = False,
) -> str:
    """为 protected 档空间生成 Argon2id 口令校验串。"""
    raw_salt = secrets.token_bytes(SALT_BYTES) if salt is None else bytes(salt)
    digest = derive_kek(password, raw_salt, params, allow_low_cost_for_vectors=allow_low_cost_for_vectors)
    return f"argon2id$m={params.m},t={params.t},p={params.p}${b64url_encode(raw_salt)}${b64url_encode(digest)}"


def verify_space_password(
    password: str,
    encoded: str,
    *,
    allow_low_cost_for_vectors: bool = False,
) -> bool:
    """恒定时间验证 protected 档空间口令。"""
    try:
        if not isinstance(password, str) or not password or not isinstance(encoded, str):
            return False
        alg, param_str, salt_b64, digest_b64 = encoded.split("$")
        if alg != KDF_ALGORITHM:
            return False
        parsed: dict[str, int] = {}
        for part in param_str.split(","):
            key, val = part.split("=", 1)
            parsed[key] = int(val)
        params = Argon2Params(m=parsed["m"], t=parsed["t"], p=parsed["p"], dk_len=KEY_BYTES)
        salt = b64url_decode(salt_b64)
        expected = b64url_decode(digest_b64)
        if len(expected) != KEY_BYTES:
            return False
        actual = derive_kek(password, salt, params, allow_low_cost_for_vectors=allow_low_cost_for_vectors)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False
