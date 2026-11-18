"""客户端/节点端端到端 AES-256-GCM 分块加解密工具（与浏览器 WebCrypto 字节兼容）。"""

import base64
import hashlib
import os
from pathlib import Path
from typing import Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


DEFAULT_CHUNK_SIZE = 1024 * 1024  # 默认 1 MiB 明文分块，兼顾吞吐与内存占用
NONCE_BYTES = 12
TAG_BYTES = 16


def generate_file_key() -> bytes:
    """为单次文件传输生成随机 256 位一次性数据密钥（DEK）。"""
    return AESGCM.generate_key(bit_length=256)


def encode_key_b64(key: bytes) -> str:
    return base64.urlsafe_b64encode(key).decode("ascii")


def decode_key_b64(encoded: str) -> bytes:
    raw = base64.urlsafe_b64decode(encoded.encode("ascii"))
    if len(raw) != 32:
        raise ValueError("AES-256 key must be 32 bytes")
    return raw


def _chunk_aad(artifact_id: str, chunk_index: int) -> bytes:
    return f"studiolo:blob:{artifact_id}:{chunk_index}".encode("utf-8")


def encrypt_chunk(key: bytes, artifact_id: str, chunk_index: int, plaintext: bytes) -> bytes:
    """加密单个分块：返回 12B Nonce || Ciphertext || 16B GCM Tag，绑定 artifactId+index AAD。"""
    nonce = os.urandom(NONCE_BYTES)
    cipher = AESGCM(key).encrypt(nonce, plaintext, _chunk_aad(artifact_id, chunk_index))
    return nonce + cipher


def decrypt_chunk(key: bytes, artifact_id: str, chunk_index: int, payload: bytes) -> bytes:
    """验证 AEAD 标签与关联数据后还原分块明文；篡改或跨块重放会抛 InvalidTag。"""
    if len(payload) < NONCE_BYTES + TAG_BYTES:
        raise ValueError("Encrypted chunk payload is truncated")
    nonce = payload[:NONCE_BYTES]
    cipher = payload[NONCE_BYTES:]
    return AESGCM(key).decrypt(nonce, cipher, _chunk_aad(artifact_id, chunk_index))


def iter_encrypted_file_chunks(
    file_path: Path,
    *,
    key: bytes,
    artifact_id: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Iterator[tuple[int, bytes, str]]:
    """逐块流式读取并加密文件，返回 (chunk_index, ciphertext_bytes, chunk_sha256_hex)。"""
    idx = 0
    with file_path.open("rb") as fh:
        while True:
            plain = fh.read(chunk_size)
            if not plain:
                if idx == 0:
                    # 0 字节文件也产出 1 块空密文（含 12B Nonce + 16B Tag），保证分块数 ≥ 1
                    enc = encrypt_chunk(key, artifact_id, 0, b"")
                    yield 0, enc, hashlib.sha256(enc).hexdigest()
                break
            enc = encrypt_chunk(key, artifact_id, idx, plain)
            yield idx, enc, hashlib.sha256(enc).hexdigest()
            idx += 1
