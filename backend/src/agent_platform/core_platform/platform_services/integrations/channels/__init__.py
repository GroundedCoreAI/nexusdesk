
"""Built-in chat channel adapters."""

from agent_platform.core_platform.platform_services.integrations.channels.base import (
    DeliveryResult,
    IncomingEnvelope,
    WebhookResult,
)
from agent_platform.core_platform.platform_services.integrations.channels.registry import (
    adapter_for,
    provider_catalog,
)

__all__ = [
    "DeliveryResult",
    "IncomingEnvelope",
    "WebhookResult",
    "adapter_for",
    "provider_catalog",
]
