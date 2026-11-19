# Studiolo Shared Space 密码学契约 v1 (`shared-space-crypto-v1`)

本规范定义 Studiolo Shared Space（`/space`）在 **TypeScript（WebCrypto + `@noble/hashes`）**、**Python（`cryptography`）** 及后续 **Rust（Android 本地）** 之间必须逐字节一致的密码学封装、密钥层级、AAD 绑定与验证规则。

- **协议版本**：`1`
- **默认编码**：字符串统一 UTF-8，二进制字段统一 **无填充 Base64URL（RFC 4648 §5）**，摘要统一小写十六进制 **SHA-256**。
- **对称加密算法**：`aes-256-gcm`（256 位密钥 / 12 字节随机 Nonce / 16 字节认证标签）。
- **口令派生函数**：`argon2id`（RFC 9106）。

---

## 1. Argon2id 参数基线与合法边界

| 参数 | 生产默认值 | 允许下界（安全底线） | 允许上界（防 DoS） | 说明 |
| --- | --- | --- | --- | --- |
| `m` (KiB) | `19456`（19 MiB） | `19456`（测试向量可低至 `1024` 仅限向量标记） | `262144`（256 MiB） | OWASP 推荐移动/桌面平衡档 |
| `t` (iterations) | `2` | `2`（测试向量可低至 `1`） | `16` | 迭代次数 |
| `p` (lanes) | `1` | `1` | `4` | 并行度 |
| `dkLen` (bytes) | `32` | `32` | `32` | 固定输出 256 位 KEK |
| `salt` (bytes) | `16` | `16` | `64` | 每空间每次改密独立随机生成 |

> 非测试环境下，客户端与服务端均必须拒绝低于生产安全底线（`m < 19456` 或 `t < 2`）的封套参数。

---

## 2. 极密保险库 (`e2ee`) 密钥层级与数据格式

```text
User Password + random salt (16B)
        │  Argon2id (m=19456, t=2, p=1, dkLen=32)
        ▼
      KEK (32B, 仅存当次内存)
        │  AES-256-GCM unwrap (AAD = envelope)
        ▼
   Space Key (32B, 每 epoch 独立随机)
        │  AES-256-GCM unwrap (AAD = dek)
        ▼
    Entry DEK (32B, 每 entry revision 独立随机)
        ├── AES-256-GCM encrypt/decrypt Manifest JSON (AAD = manifest)
        └── AES-256-GCM encrypt/decrypt Chunk[i] (AAD = chunk[i])
```

### 2.1 规范化 AAD（Associated Authenticated Data）

所有 AAD 均为 ASCII/UTF-8 编码，严禁缺失任何字段，确保密文无法在工作区、空间、条目、修订、用途、分块序号或 `epoch` 间移植重放：

| 用途 | AAD 格式 |
| --- | --- |
| 封装 `Space Key`（`KeyEnvelope`） | `studiolo:space:v1:{workspaceId}:{spaceId}:envelope:{epoch}` |
| 封装条目修订 `DEK`（`WrappedDek`） | `studiolo:space:v1:{workspaceId}:{spaceId}:{entryId}:{revision}:dek:{epoch}` |
| 加密条目元信息（`Manifest`） | `studiolo:space:v1:{workspaceId}:{spaceId}:{entryId}:{revision}:manifest:{epoch}` |
| 加密条目正文/文件分块（`Chunk`） | `studiolo:space:v1:{workspaceId}:{spaceId}:{entryId}:{revision}:chunk:{chunkIndex}:{epoch}` |

### 2.2 `KeyEnvelope` JSON 格式

```json
{
  "version": 1,
  "epoch": 1,
  "kdf": {
    "algorithm": "argon2id",
    "m": 19456,
    "t": 2,
    "p": 1,
    "dkLen": 32,
    "saltB64": "<16B+ Base64URL>"
  },
  "aead": "aes-256-gcm",
  "nonceB64": "<12B Base64URL>",
  "wrappedKeyB64": "<48B Base64URL: 32B SpaceKey + 16B Tag>"
}
```

- **常规改密**：用旧密码解包出原 `Space Key`，保持 `epoch` 不变，生成新随机 `salt` 与 `nonce`、用新密码派生新 `KEK` 重新包装，通过 CAS（`envelope_version`）更新。
- **泄露/撤销轮换**：生成全新随机 32B `Space Key` 与 `epoch + 1`，暂存并校验所有需要保留条目的重包/重加密修订后原子切换 `active_epoch`；客户端记住已接受的最高 `epoch`，拒绝静默回退。

### 2.3 `WrappedDek` JSON 格式

```json
{
  "version": 1,
  "epoch": 1,
  "aead": "aes-256-gcm",
  "nonceB64": "<12B Base64URL>",
  "wrappedDekB64": "<48B Base64URL: 32B DEK + 16B Tag>"
}
```

### 2.4 加密分块字节格式（Chunk）

- 默认分块明文大小：`2 * 1024 * 1024`（2 MiB）。
- 单分块密文存储格式：`12B Nonce || Ciphertext || 16B GCM Tag`（与 Fleet `blobTransfer.ts` 保持一致）。
- 上传/校验摘要：对完整密文分块字节流计算 `SHA-256` 十六进制摘要。

### 2.5 加密 `Manifest` JSON 格式

`e2ee` 模式下，条目文件名、标题、类型标签、MIME、大小、分块总数、明文 SHA-256 全部放入加密 `Manifest`，Core 数据库仅存不透明 `entryId`、`revision`、`epoch`、`entryType`（可选不透明或枚举）、密文总字节与块数：

```json
{
  "version": 1,
  "entryType": "file",
  "title": "deploy-key.pem",
  "fileName": "deploy-key.pem",
  "mime": "application/x-pem-file",
  "sizeBytes": 1679,
  "chunkCount": 1,
  "chunkSize": 2097152,
  "plaintextSha256": "<hex>",
  "tags": ["prod", "ssh"],
  "summary": ""
}
```

---

## 3. 受控机密 (`protected`) 服务端信封加密与空间口令校验

`protected` 档支持 **UI 每次输密码读取** 及 **细粒度 `sv_live_` Vault Token API 直读明文**：

1. **服务端主密钥派生**：从环境配置 `STUDIOLO_VAULT_MASTER_KEY`（≥ 32 字节高熵密钥）经 `HKDF-SHA256` 按 `info = "studiolo:vault:v1:workspace:{workspaceId}"` 派生 32B `WorkspaceVaultKey`。
2. **数据加密**：每条 `protected` 条目修订生成独立随机 32B `DEK`，用 `WorkspaceVaultKey` 以 `AES-256-GCM` 包装 `DEK`（AAD 与 `e2ee` 保持同一命名空间：`studiolo:space:v1:{workspaceId}:{spaceId}:{entryId}:{revision}:dek:{epoch}`），正文/文件块用 `DEK` 以 `AES-256-GCM` 分块加密落盘。
3. **UI 空间密码校验**：空间保存 `Argon2id` 校验串，格式为：
   `argon2id$m=19456,t=2,p=1$<saltB64>$<hashB64>`
   所有 UI 查看/修改/下载均先校验当次输入密码并恒定时间比对，绝不将明文密码写入日志、缓存或数据库。

---

## 4. 跨语言测试向量

确定性跨语言向量定义于 [shared-space-crypto-v1.vectors.json](shared-space-crypto-v1.vectors.json)，前端（`tests/space-crypto.test.mjs`）与后端（`backend/tests/test_space_crypto.py`）必须同时通过所有正向与篡改/错密负向用例。
