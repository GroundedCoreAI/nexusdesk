"""Reference external capability used by lifecycle acceptance tests.

The manifest for this capability lives outside the Python package. The
implementation is deliberately bound by ``applications.customer_service.trusted_extensions`` so
the manifest cannot import or execute arbitrary code.
"""

from dataclasses import dataclass

from agent_platform.core_platform.extension_platform import (
    CapabilityContributionBundle,
    EventSubscription,
)
from agent_platform.extension_contracts import (
    ConfirmationRequirement,
    EventEnvelope,
    PolicyContext,
    PolicyDecision,
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionResult,
    UiExtensionManifest,
    UiNavigationItem,
    UiRouteContribution,
)

SAMPLE_OPERATIONS_CAPABILITY_ID = "sample-operations"


class SampleOperationsLifecycle:
    """Small lifecycle implementation with observable state for acceptance tests."""

    def __init__(self) -> None:
        self.started = False
        self.config: dict[str, object] = {}
        self.received_events: list[str] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def configure(self, config: dict[str, object]) -> None:
        self.config = dict(config)

    async def health(self) -> bool:
        return self.started

    async def handle(self, event: EventEnvelope) -> None:
        self.received_events.append(event.idempotency_key)


@dataclass(frozen=True)
class _SampleOperationsTool:
    definition: ToolDefinition
    lifecycle: SampleOperationsLifecycle

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        return ToolExecutionResult(
            status="succeeded",
            data={
                "started": self.lifecycle.started,
                "configured": bool(self.lifecycle.config),
                "tenant": request.context.tenant_id,
            },
        )


class _SampleOperationsToolContribution:
    def __init__(self, lifecycle: SampleOperationsLifecycle) -> None:
        self.lifecycle = lifecycle

    def handlers(self, row: dict[str, object], emit) -> tuple[_SampleOperationsTool, ...]:
        return (
            _SampleOperationsTool(
                definition=ToolDefinition(
                    name="sample_operations_status",
                    description="Read the health and configuration status of the sample capability.",
                    parameters={
                        "type": "object",
                        "properties": {},
                        "additionalProperties": False,
                    },
                    capability=SAMPLE_OPERATIONS_CAPABILITY_ID,
                    risk="read",
                    required_permissions=frozenset({"sample-operations.read"}),
                ),
                lifecycle=self.lifecycle,
            ),
        )


class _SampleOperationsPolicy:
    async def evaluate(
        self,
        context: PolicyContext,
        capability: str,
        action: str,
        risk: str,
    ) -> PolicyDecision:
        requires_confirmation = risk in {"write", "irreversible"}
        return PolicyDecision(
            effect="allow",
            reason_code="sample_operations_policy",
            risk=risk,
            confirmation=ConfirmationRequirement(
                required=requires_confirmation,
                action="confirm_sample_operations" if requires_confirmation else None,
            ),
            policy_version="sample-operations-v1",
        )


def _sample_operations_ui() -> UiExtensionManifest:
    path = "/extensions/sample-operations"
    return UiExtensionManifest(
        extension_id=SAMPLE_OPERATIONS_CAPABILITY_ID,
        version="1.0.0",
        navigation=(
            UiNavigationItem(
                id="sample-operations-home",
                label_key="extensions.sampleOperations",
                path=path,
                icon="ApiOutlined",
                group="platform",
                required_permissions=("sample-operations.read",),
                required_capability=SAMPLE_OPERATIONS_CAPABILITY_ID,
                order=900,
            ),
        ),
        routes=(
            UiRouteContribution(
                id="sample-operations-home",
                path=path,
                feature="extensions/sample-operations",
                required_permissions=("sample-operations.read",),
                required_capability=SAMPLE_OPERATIONS_CAPABILITY_ID,
            ),
        ),
    )


def sample_operations_contributions(
    platform: object,
    lifecycle: SampleOperationsLifecycle | None = None,
) -> CapabilityContributionBundle:
    """Build all four contribution types for the trusted sample capability."""

    lifecycle = lifecycle or getattr(platform, "sample_operations_lifecycle", None)
    if not isinstance(lifecycle, SampleOperationsLifecycle):
        lifecycle = SampleOperationsLifecycle()
        platform.sample_operations_lifecycle = lifecycle
    if getattr(platform, "event_bus", None) is None:
        raise TypeError("sample operations contribution requires the platform event bus")
    return CapabilityContributionBundle(
        tools=(_SampleOperationsToolContribution(lifecycle),),
        events=(EventSubscription("sample-operations.created", lifecycle),),
        policies=(_SampleOperationsPolicy(),),
        ui=(_sample_operations_ui(),),
    )


__all__ = [
    "SAMPLE_OPERATIONS_CAPABILITY_ID",
    "SampleOperationsLifecycle",
    "sample_operations_contributions",
]
