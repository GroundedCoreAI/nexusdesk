"""Approval capability lifecycle and event projection."""

from collections import Counter

from agent_platform.core_platform.platform_services.events import InProcessEventBus
from agent_platform.extension_contracts import CapabilityLifecycle, EventEnvelope, EventSubscriber

APPROVAL_EVENT_TYPES = (
    "approval.requested",
    "approval.approved",
    "approval.rejected",
    "approval.cancelled",
)


class ApprovalEventProjection(EventSubscriber):
    """Observe approval events without coupling the capability to persistence."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()
        self.last_event: EventEnvelope | None = None
        self._seen: set[str] = set()

    async def handle(self, event: EventEnvelope) -> None:
        if event.idempotency_key in self._seen:
            return
        self._seen.add(event.idempotency_key)
        self.counts[event.event_type] += 1
        self.last_event = event


class ApprovalCapability(CapabilityLifecycle):
    """Lifecycle adapter for the independent Approval extension."""

    def __init__(self, event_bus: InProcessEventBus) -> None:
        self.event_bus = event_bus
        self.projection = ApprovalEventProjection()

    async def start(self) -> None:
        for event_type in APPROVAL_EVENT_TYPES:
            self.event_bus.subscribe(event_type, self.projection)

    async def stop(self) -> None:
        for event_type in APPROVAL_EVENT_TYPES:
            self.event_bus.unsubscribe(event_type, self.projection)
