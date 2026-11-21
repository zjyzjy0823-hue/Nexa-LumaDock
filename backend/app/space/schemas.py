"""Shared Space Pydantic v2 请求与响应模型定义。"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


SpaceTier = Literal["standard", "protected", "e2ee"]
SpaceEntryType = Literal["text", "config", "key", "file"]
SpaceTokenKind = Literal["standard", "vault"]
SpaceTokenScope = Literal["read", "write"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def valid_uuid(value: str) -> str:
    return str(UUID(value))


class SpaceCapabilitiesOut(StrictModel):
    enabled: bool
    protectedAvailable: bool
    maxFileBytes: int
    defaultQuotaBytes: int
    defaultChunkSize: int
    tiers: list[SpaceTier]


class SpaceCreateInput(StrictModel):
    id: str | None = Field(default=None, min_length=36, max_length=36)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    tier: SpaceTier = "standard"
    quotaBytes: int | None = Field(default=None, ge=1024 * 1024)
    # 仅 protected 档必填（用于 UI 按次密码校验）
    password: str | None = Field(default=None, min_length=8, max_length=256)
    # 仅 e2ee 档必填（客户端用密码包装的初始 epoch=1 KeyEnvelope）
    envelope: dict[str, Any] | None = None


class SpaceOut(StrictModel):
    id: str
    workspaceId: str
    name: str
    description: str
    tier: SpaceTier
    activeEpoch: int
    envelopeVersion: int
    quotaBytes: int
    usedBytes: int
    entryCount: int = 0
    archivedAt: str | None = None
    createdAt: str
    updatedAt: str


class SpaceEnvelopeOut(StrictModel):
    spaceId: str
    epoch: int
    envelopeVersion: int
    envelope: dict[str, Any]
    updatedAt: str


class SpaceEnvelopeUpdateInput(StrictModel):
    expectedEnvelopeVersion: int = Field(ge=1)
    envelope: dict[str, Any]


class SpaceRotateEpochInput(StrictModel):
    expectedActiveEpoch: int = Field(ge=1)
    envelope: dict[str, Any]


class ProtectedPasswordChangeInput(StrictModel):
    oldPassword: str = Field(min_length=1, max_length=256)
    newPassword: str = Field(min_length=8, max_length=256)


class SpaceBlobInitInput(StrictModel):
    chunkSize: int = Field(ge=1024, le=8 * 1024 * 1024)
    chunkCount: int = Field(ge=1, le=2048)
    totalSize: int = Field(ge=0)


class SpaceBlobOut(StrictModel):
    id: str
    spaceId: str
    chunkSize: int
    chunkCount: int
    totalSize: int
    uploadedChunks: list[int]
    committedAt: str | None = None
    createdAt: str


class SpaceEntryCreateInput(StrictModel):
    id: str | None = Field(default=None, min_length=36, max_length=36)
    entryType: SpaceEntryType = "text"
    mutationId: str | None = Field(default=None, min_length=1, max_length=64)
    # standard / protected 可见展示字段（e2ee 必须省略，放入加密 manifest）
    title: str | None = Field(default=None, min_length=1, max_length=200)
    fileName: str | None = Field(default=None, max_length=255)
    mime: str = Field(default="text/plain", max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=32)
    # standard / protected 正文或 base64 文件内容（大文件也可走 blobId）
    contentText: str | None = None
    contentBase64: str | None = None
    blobId: str | None = None
    # protected 档 UI 创建时携带当次密码（sv_live_ 写调用无需）
    password: str | None = Field(default=None, min_length=1, max_length=256)
    # e2ee 档专用字段（客户端预加密）
    epoch: int | None = Field(default=None, ge=1)
    wrappedDek: dict[str, Any] | None = None
    encryptedManifestB64: str | None = None
    plaintextSize: int = Field(default=0, ge=0)
    contentSha256: str = Field(default="", max_length=64)


class SpaceEntryUpdateInput(StrictModel):
    baseRevision: int = Field(ge=1)
    mutationId: str | None = Field(default=None, min_length=1, max_length=64)
    allowConflictFork: bool = False
    title: str | None = Field(default=None, min_length=1, max_length=200)
    fileName: str | None = Field(default=None, max_length=255)
    mime: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = Field(default=None, max_length=32)
    contentText: str | None = None
    contentBase64: str | None = None
    blobId: str | None = None
    password: str | None = Field(default=None, min_length=1, max_length=256)
    epoch: int | None = Field(default=None, ge=1)
    wrappedDek: dict[str, Any] | None = None
    encryptedManifestB64: str | None = None
    plaintextSize: int | None = Field(default=None, ge=0)
    contentSha256: str | None = Field(default=None, max_length=64)


class SpacePasswordUnlockInput(StrictModel):
    password: str = Field(min_length=1, max_length=256)
    revision: int | None = Field(default=None, ge=1)


class SpaceEntrySummaryOut(StrictModel):
    id: str
    spaceId: str
    tier: SpaceTier
    entryType: SpaceEntryType
    currentRevision: int
    activeEpoch: int
    title: str | None = None
    fileName: str | None = None
    mime: str
    tags: list[str]
    sizeBytes: int
    hasConflict: bool = False
    deletedAt: str | None = None
    createdAt: str
    updatedAt: str
    # e2ee 列表附带最新修订加密壳，方便客户端一次输密解密目录页
    wrappedDek: dict[str, Any] | None = None
    encryptedManifestB64: str | None = None
    blobId: str | None = None
    chunkCount: int = 0
    chunkSize: int = 2 * 1024 * 1024


class SpaceEntryDetailOut(SpaceEntrySummaryOut):
    revision: int
    epoch: int
    contentSha256: str = ""
    # standard 随时返回；protected 仅通过 unlock(密码) 或 sv_live_ 返回；e2ee 永远为 None
    contentText: str | None = None
    contentBase64: str | None = None
    locked: bool = False
    conflictRevisions: list[int] = Field(default_factory=list)


class SpaceStandardEdit(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    tags: list[str] = Field(max_length=32)
    contentText: str


class SpaceStandardMutation(StrictModel):
    mutationId: UUID
    baseRevision: int = Field(ge=1)
    deviceLabel: str = Field(min_length=1, max_length=120)
    operation: Literal["edit", "delete"]
    edit: SpaceStandardEdit | None = None


class SpaceStandardCandidateOut(StrictModel):
    id: str
    entryId: str
    deviceLabel: str
    operation: Literal["edit", "delete"]
    edit: SpaceStandardEdit | None = None
    baseRevision: int
    createdAt: str
    current: SpaceEntryDetailOut


class SpaceStandardResolution(StrictModel):
    expectedRevision: int = Field(ge=1)
    expectedDeleted: bool
    strategy: Literal["core", "candidate"]


class SpaceStandardMutationOut(StrictModel):
    status: Literal["applied", "conflict", "resolved"]
    revision: int
    candidateId: str | None = None


class SpaceStandardSnapshot(StrictModel):
    cursor: int
    entries: list[SpaceEntrySummaryOut]


class SpaceTokenCreateInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[SpaceTokenScope] = Field(default_factory=lambda: ["read"], min_length=1)
    entryIds: list[str] | None = None
    expiresInDays: int | None = Field(default=None, ge=1, le=3650)
    # 为 protected 空间签发 sv_live_ 时要求确认当次空间密码
    password: str | None = Field(default=None, min_length=1, max_length=256)


class SpaceTokenOut(StrictModel):
    id: str
    spaceId: str
    tokenKind: SpaceTokenKind
    name: str
    tokenLast4: str
    scopes: list[str]
    entryIds: list[str] | None = None
    expiresAt: str | None = None
    lastUsedAt: str | None = None
    revokedAt: str | None = None
    createdAt: str


class SpaceTokenCreatedOut(SpaceTokenOut):
    # 明文 Token 仅签发瞬间返回一次，服务端仅存 SHA-256
    token: str


class SpaceDeviceGrantOut(StrictModel):
    clientId: str
    deviceName: str
    platform: str
    canRead: bool
    explicit: bool


class SpaceAuditLogOut(StrictModel):
    id: str
    spaceId: str
    entryId: str | None = None
    actorKind: str
    actorId: str
    action: str
    outcome: str
    detail: str
    createdAt: str


class SpaceChangeOut(StrictModel):
    seq: int
    spaceId: str
    entryId: str | None = None
    revision: int
    epoch: int
    changeType: str
    createdAt: str


class SpaceChangesPageOut(StrictModel):
    spaceId: str
    sinceSeq: int
    nextSeq: int
    hasMore: bool
    activeEpoch: int
    envelopeVersion: int
    changes: list[SpaceChangeOut]
