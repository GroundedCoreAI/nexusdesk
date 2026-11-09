"""Public descriptors and exact-resolution registries."""

from .adapter_registry import AdapterDescriptor, AdapterRegistry
from .engine_registry import EngineDescriptor, EngineRegistry
from .protocol_registry import ProtocolDescriptor, ProtocolRegistry

__all__ = [
    "AdapterDescriptor",
    "AdapterRegistry",
    "EngineDescriptor",
    "EngineRegistry",
    "ProtocolDescriptor",
    "ProtocolRegistry",
]
