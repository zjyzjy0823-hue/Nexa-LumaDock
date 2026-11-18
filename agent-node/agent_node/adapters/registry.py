"""根据节点本地配置统一构建启用的 AgentAdapter 注册表。"""

from ..config import NodeConfig
from .antigravity import AntigravityAdapter
from .base import AgentAdapter
from .codex import CodexAdapter
from .dsh import DshAdapter
from .hermes import HermesAdapter
from .mock import MockAdapter
from .openclaw import OpenClawAdapter
from .opencode import OpenCodeAdapter


def build_adapter_registry(config: NodeConfig) -> dict[str, AgentAdapter]:
    p = config.providers
    roots = config.allowed_roots
    registry: dict[str, AgentAdapter] = {}

    if p.get("codex", {}).get("enabled", True):
        registry["codex"] = CodexAdapter(roots, command=str(p.get("codex", {}).get("command") or "codex"))
    if p.get("opencode", {}).get("enabled", True):
        oc = p.get("opencode", {})
        registry["opencode"] = OpenCodeAdapter(
            roots,
            serve_url=str(oc.get("serveUrl") or "http://127.0.0.1:4096"),
            username=oc.get("username"),
            password=oc.get("password"),
        )
    if p.get("hermes", {}).get("enabled", True):
        hm = p.get("hermes", {})
        registry["hermes"] = HermesAdapter(
            roots,
            command=str(hm.get("command") or "hermes"),
            mode=str(hm.get("mode") or "acp"),
            serve_url=hm.get("serveUrl"),
            api_key=hm.get("apiKey"),
        )
    if p.get("antigravity", {}).get("enabled", True):
        registry["antigravity"] = AntigravityAdapter(roots, command=str(p.get("antigravity", {}).get("command") or "agy"))
    if p.get("dsh", {}).get("enabled", True):
        registry["dsh"] = DshAdapter(roots, command=str(p.get("dsh", {}).get("command") or "dsh"))
    if p.get("openclaw", {}).get("enabled", False):
        claw = p.get("openclaw", {})
        registry["openclaw"] = OpenClawAdapter(
            roots,
            gateway_url=str(claw.get("gatewayUrl") or "ws://127.0.0.1:18789"),
            token=claw.get("token"),
        )
    if p.get("mock", {}).get("enabled", False):
        registry["mock"] = MockAdapter(roots)

    return registry
