from ..remote import SyncRemoteError
from .ledger import ADAPTERS as LEDGER

from .websites import ADAPTERS as WEBSITES
from .data import ADAPTERS as DATA

REGISTRY = {adapter.entity_type: adapter for adapter in [*LEDGER, *WEBSITES, *DATA]}


def get_adapter(entity_type):
    adapter = REGISTRY.get(entity_type) if isinstance(entity_type, str) else None
    if adapter is None:
        raise SyncRemoteError("unknown_entity_type")
    return adapter


def adapter_for(item):
    for adapter in REGISTRY.values():
        if isinstance(item, adapter.model):
            return adapter
    raise SyncRemoteError("unknown_entity_type")


def seed_version():
    return max(adapter.generation for adapter in REGISTRY.values())
