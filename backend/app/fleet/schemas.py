"""Fleet 控制节点与加密分块传输协议的严格 Pydantic v2 Schema。"""

from ipaddress import ip_address
import re
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


NodePlatform = Literal["macos", "windows", "linux", "android", "ios"]
AdapterProvider = Literal["codex", "opencode", "hermes", "antigravity", "dsh", "openclaw", "mock"]
EndpointKind = Literal["lan", "xtcp", "edge_relay", "core"]
BlobPurpose = Literal["fleet_artifact", "shared_space"]
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

MAX_CHUNK_BYTES = 8 * 1024 * 1024  # 单分块上限 8 MiB，防止内存中继缓冲膨胀
DEFAULT_ARTIFACT_TTL_SECONDS = 7 * 24 * 3600


def validate_endpoint_url(value: str, *, allow_insecure: bool = False) -> str:
    """校验传输或控制端点 URL，拒绝非 HTTP(S) 协议、内嵌凭据以及云元数据链路地址。"""
    cleaned = value.strip().rstrip("/")
    try:
        parts = urlsplit(cleaned)
        _ = parts.port
    except ValueError as exc:
        raise ValueError("Invalid endpoint URL") from exc
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Endpoint URL must use http or https with a valid host")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError("Endpoint URL must not embed credentials, query, or fragment")
    host = parts.hostname.lower()
    if host != "localhost":
        try:
            addr = ip_address(host)
            if addr.is_link_local or addr.is_multicast or addr.is_unspecified:
                raise ValueError("Disallowed link-local or unspecified address")
            if parts.scheme == "http" and not (allow_insecure or addr.is_loopback or addr.is_private):
                raise ValueError("Public endpoints must use https")
        except ValueError as err:
            if "Disallowed" in str(err) or "Public endpoints" in str(err):
                raise
            # 域名仅在显式允许（例如内网 mDNS / 隧道内部测试）时允许 http
            if parts.scheme == "http" and not (allow_insecure or host.endswith(".local")):
                raise ValueError("Public domain endpoints must use https")
    return cleaned


class TransferEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: EndpointKind
    url: str = Field(min_length=1, max_length=500)
    priority: int = Field(default=10, ge=0, le=1000)
    label: str = Field(default="", max_length=120)

    @field_validator("url")
    @classmethod
    def check_url(cls, value: str) -> str:
        return validate_endpoint_url(value)


class AdapterSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chat: bool = False
    history: bool = False
    models: bool = False
    approval: bool = False
    forms: bool = False
    worktree: bool = False
    rollback: bool = False
    readOnly: bool = False
    fork: bool = False
    steer: bool = False
    usage: bool = False
    thinking: bool = False


class AdapterInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: AdapterProvider
    version: str = Field(default="", max_length=64)
    status: Literal["ready", "unavailable", "error"] = "ready"
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    supports: AdapterSupport = Field(default_factory=AdapterSupport)

    @model_validator(mode="after")
    def derive_supports(self):
        caps = set(self.capabilities)
        self.supports = AdapterSupport(
            chat="chat" in caps, history="history" in caps, models="models" in caps, approval="approval" in caps,
            forms="forms" in caps, worktree="worktree" in caps, rollback="checkpoints" in caps,
            readOnly="read-only" in caps, fork="fork" in caps, steer="steer" in caps,
            usage="usage" in caps or self.provider in ("codex", "hermes", "opencode", "mock"),
            thinking="thinking" in caps or self.provider in ("codex", "hermes", "opencode"),
        )
        return self


class SubscriptionQuotaWindow(BaseModel):
    group: str = Field(min_length=1, max_length=100)
    kind: Literal["primary", "secondary", "monthly"]
    remainingPercent: float = Field(ge=0, le=100)
    windowMinutes: int | None = Field(default=None, ge=1, le=1_000_000)
    resetsAt: int | None = Field(default=None, ge=1, le=253402300799)


class SubscriptionQuota(BaseModel):
    status: Literal["ready", "no_data", "unavailable", "offline", "unsupported"]
    checkedAt: int | None = Field(default=None, ge=1, le=253402300799)
    windows: list[SubscriptionQuotaWindow] = Field(default_factory=list, max_length=16)


class NodeCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    platform: NodePlatform = "windows"
    hostname: str | None = Field(default=None, max_length=120)

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Node name cannot be empty")
        return stripped


class NodePatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    platform: NodePlatform | None = None
    hostname: str | None = Field(default=None, max_length=120)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("Node name cannot be empty")
        return stripped


class NodeOut(BaseModel):
    id: str
    workspaceId: str
    name: str
    platform: str
    hostname: str | None = None
    status: str
    tokenLast4: str | None = None
    tokenCreatedAt: str | None = None
    revokedAt: str | None = None
    allowedRoots: list[str]
    adapters: list[AdapterInfo]
    transferEndpoints: list[TransferEndpoint]
    lastSeenAt: str | None = None
    createdAt: str
    updatedAt: str


class NodeTokenOut(BaseModel):
    node: NodeOut
    nodeToken: str


class BlobInitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: BlobPurpose = "fleet_artifact"
    digest: str = Field(min_length=64, max_length=64)
    ciphertextSize: int = Field(ge=1, le=2 * 1024 * 1024 * 1024)
    chunkSize: int = Field(ge=1024, le=MAX_CHUNK_BYTES)
    chunkCount: int = Field(ge=1, le=8192)
    storageRole: Literal["core", "edge_relay", "direct"] = "core"
    storageLocation: str = Field(default="", max_length=500)
    ttlSeconds: int | None = Field(default=DEFAULT_ARTIFACT_TTL_SECONDS, ge=60, le=30 * 24 * 3600)
    # 非敏感加密信封参数（如 salt/nonce/algorithm/aadVersion 等，不含明文与密钥）
    manifest: dict[str, Any] | None = None

    @field_validator("digest")
    @classmethod
    def check_digest(cls, value: str) -> str:
        lower = value.strip().lower()
        if not _SHA256_RE.match(lower):
            raise ValueError("digest must be 64-char lowercase hex SHA-256")
        return lower


class BlobCommitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    storageRole: Literal["core", "edge_relay", "direct"] | None = None
    storageLocation: str | None = Field(default=None, max_length=500)
    manifest: dict[str, Any] | None = None


class BlobOut(BaseModel):
    id: str
    workspaceId: str
    uploaderKind: str
    uploaderId: str
    purpose: BlobPurpose
    digest: str
    ciphertextSize: int
    chunkSize: int
    chunkCount: int
    storageRole: str
    storageLocation: str
    manifest: dict[str, Any] | None = None
    committedAt: str | None = None
    expiresAt: str | None = None
    createdAt: str


class ResolvedEndpoint(BaseModel):
    kind: EndpointKind
    url: str
    priority: int
    label: str = ""
    ticket: str | None = None


class BlobEndpointsOut(BaseModel):
    blob: BlobOut
    endpoints: list[ResolvedEndpoint]


class NodeHelloPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hostname: str | None = Field(default=None, max_length=120)
    platform: NodePlatform | None = None
    allowedRoots: list[str] = Field(default_factory=list, max_length=64)
    adapters: list[AdapterInfo] = Field(default_factory=list, max_length=32)
    transferEndpoints: list[TransferEndpoint] = Field(default_factory=list, max_length=16)


def valid_uuid(value: str) -> str:
    return str(UUID(value))
