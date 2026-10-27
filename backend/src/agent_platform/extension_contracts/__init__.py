"""Stable contracts shared by the platform core and extensions.

The contract package deliberately does not import from ``modules`` or
``integrations``. Concrete implementations may depend on these types, but the
types themselves must remain independent of any business capability.
"""

from .capabilities import (
    CapabilityConfigurable,
    CapabilityConfigVersion,
    CapabilityLifecycle,
    CapabilityManifest,
    CapabilityStatus,
    CapabilityStatusView,
    ExtensionKind,
)
from .events import EventEnvelope, EventPublisher, EventSubscriber
from .identity import IdentityBindings
from .policy import (
    ConfirmationRequirement,
    ExecutionConstraint,
    PolicyContext,
    PolicyDecision,
    PolicyProvider,
    RiskLevel,
)
from .runtime import (
    ConversationPort,
    RunEvent,
    RunPort,
    RunRequest,
    RunSnapshot,
    RunStatus,
    RuntimeBindings,
    RuntimeConfirmationPort,
    RuntimeCustomerPort,
    RuntimeMemoryPort,
    RuntimePolicyPort,
    RuntimeRetrievalPort,
    RuntimeToolPort,
)
from .tools import (
    OperationLedgerPort,
    OperationRecord,
    ToolContribution,
    ToolDefinition,
    ToolExecutionContext,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolHandler,
    ToolRegistryPort,
    ToolReplayPort,
    ToolRisk,
)
from .ui import (
    UiExtensionManifest,
    UiNavigationItem,
    UiRouteContribution,
)

__all__ = [
    "CapabilityConfigVersion",
    "CapabilityConfigurable",
    "CapabilityLifecycle",
    "CapabilityManifest",
    "CapabilityStatus",
    "CapabilityStatusView",
    "ConfirmationRequirement",
    "ConversationPort",
    "EventEnvelope",
    "EventPublisher",
    "EventSubscriber",
    "ExecutionConstraint",
    "ExtensionKind",
    "IdentityBindings",
    "OperationLedgerPort",
    "OperationRecord",
    "PolicyContext",
    "PolicyDecision",
    "PolicyProvider",
    "RiskLevel",
    "RunEvent",
    "RunPort",
    "RunRequest",
    "RunSnapshot",
    "RunStatus",
    "RuntimeBindings",
    "RuntimeConfirmationPort",
    "RuntimeCustomerPort",
    "RuntimeMemoryPort",
    "RuntimePolicyPort",
    "RuntimeRetrievalPort",
    "RuntimeToolPort",
    "ToolContribution",
    "ToolDefinition",
    "ToolExecutionContext",
    "ToolExecutionRequest",
    "ToolExecutionResult",
    "ToolHandler",
    "ToolRegistryPort",
    "ToolReplayPort",
    "ToolRisk",
    "UiExtensionManifest",
    "UiNavigationItem",
    "UiRouteContribution",
]
