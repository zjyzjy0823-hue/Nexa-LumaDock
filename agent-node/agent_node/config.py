"""节点本地不可由远端覆盖的安全配置与 allowedRoots 沙箱路径守卫。"""

from dataclasses import dataclass, field
from ipaddress import ip_address
import json
import os
from pathlib import Path
import socket
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class PathOutsideAllowedRootsError(PermissionError):
    """请求路径越出了节点本地白名单 allowedRoots。"""


@dataclass(frozen=True)
class DirectTransferConfig:
    enabled: bool = True
    bind_host: str = "127.0.0.1"
    port: int = 18910
    advertise_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class NodeConfig:
    core_url: str
    node_token: str = field(repr=False)
    allowed_roots: tuple[Path, ...]
    direct: DirectTransferConfig = field(default_factory=DirectTransferConfig)
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def ws_url(self) -> str:
        parts = urlsplit(self.core_url)
        ws_scheme = "wss" if parts.scheme == "https" else "ws"
        return urlunsplit((ws_scheme, parts.netloc, "/ws/fleet/node", "", ""))


def validate_core_base_url(value: str, *, allow_insecure: bool = False) -> str:
    """规范化 Core 地址，非回环主机强制使用 HTTPS。"""
    raw = value.strip().rstrip("/")
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Invalid Core URL")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise ValueError("Core URL must not embed credentials, query, or fragment")
    host = parts.hostname.lower()
    is_loopback = host in ("localhost", "127.0.0.1", "::1")
    if not is_loopback:
        try:
            addr = ip_address(host)
            is_loopback = addr.is_loopback
        except ValueError:
            pass
    if parts.scheme == "http" and not (is_loopback or allow_insecure):
        raise ValueError("Non-loopback Core URL must use https")
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def canonicalize_roots(roots: list[str] | tuple[str, ...]) -> tuple[Path, ...]:
    resolved: list[Path] = []
    for raw in roots:
        if not raw or not str(raw).strip():
            continue
        p = Path(os.path.realpath(os.path.expanduser(str(raw).strip())))
        resolved.append(p)
    if not resolved:
        raise ValueError("Node allowedRoots must configure at least one directory")
    return tuple(dict.fromkeys(resolved))


def ensure_allowed_path(target: str | Path, allowed_roots: tuple[Path, ...]) -> Path:
    """解析真实路径与符号链接，确认目标位于节点 allowedRoots 之内。"""
    candidate = Path(os.path.realpath(os.path.expanduser(str(target))))
    for root in allowed_roots:
        if os.name == "nt":
            try:
                Path(str(candidate).lower()).relative_to(Path(str(root).lower()))
                return candidate
            except ValueError:
                continue
        else:
            if candidate.is_relative_to(root):
                return candidate
    raise PathOutsideAllowedRootsError(f"Path '{candidate}' is outside node allowedRoots")


def detect_lan_urls(port: int) -> list[str]:
    """探测本机非回环私网 IPv4，供同局域网设备直传加密分块时选路。"""
    urls: list[str] = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("10.255.255.255", 1))
        ip = sock.getsockname()[0]
        sock.close()
        addr = ip_address(ip)
        if addr.is_private and not addr.is_loopback:
            urls.append(f"http://{ip}:{port}")
    except OSError:
        pass
    return urls


def load_node_config(config_path: str | Path | None = None, environ: dict[str, str] | None = None) -> NodeConfig:
    env = dict(os.environ if environ is None else environ)
    raw: dict[str, Any] = {}
    if config_path is not None:
        raw = json.loads(Path(config_path).read_text(encoding="utf-8"))

    core_url = validate_core_base_url(
        env.get("STUDIOLO_CORE_URL") or str(raw.get("coreUrl") or ""),
        allow_insecure=env.get("STUDIOLO_ALLOW_INSECURE_CORE", "").lower() in ("1", "true"),
    )
    token_env = str(raw.get("nodeTokenEnv") or "STUDIOLO_NODE_TOKEN")
    token = (env.get(token_env) or raw.get("nodeToken") or "").strip()
    if not token.startswith("sn_live_"):
        raise ValueError("Node credential must start with sn_live_")

    env_roots = [x for x in env.get("STUDIOLO_ALLOWED_ROOTS", "").split(os.pathsep) if x]
    roots = canonicalize_roots(env_roots or raw.get("allowedRoots") or [])

    direct_raw = raw.get("directTransfer") or {}
    direct_cfg = DirectTransferConfig(
        enabled=bool(direct_raw.get("enabled", True)),
        bind_host=str(env.get("STUDIOLO_DIRECT_HOST") or direct_raw.get("bindHost") or "127.0.0.1"),
        port=int(env.get("STUDIOLO_DIRECT_PORT") or direct_raw.get("port") or 18910),
        advertise_urls=tuple(direct_raw.get("advertiseUrls") or ()),
    )
    providers = dict(raw.get("providers") or {})
    return NodeConfig(
        core_url=core_url,
        node_token=token,
        allowed_roots=roots,
        direct=direct_cfg,
        providers=providers,
    )
