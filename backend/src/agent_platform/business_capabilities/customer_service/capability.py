"""Customer Service capability lifecycle and event projection."""

from collections import Counter

from agent_platform.core_platform.platform_services.events import InProcessEventBus
from agent_platform.extension_contracts import CapabilityLifecycle, EventEnvelope, EventSubscriber

CUSTOMER_SERVICE_EVENT_TYPES = (
    "ticket.proposed",
    "ticket.created",
    "ticket.rejected",
    "ticket.status_changed",
    "ticket.due_at_changed",
    "ticket.commitment_added",
)


class CustomerServiceEventProjection(EventSubscriber):
    """Small in-process projection used by the capability boundary.

    Durable ticket state remains owned by ``CustomerService``. This projection
    only proves that ticket events are delivered through the Event Contract and
    provides lifecycle diagnostics without adding a new persistence schema.
    """

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


class CustomerServiceCapability(CapabilityLifecycle):
    """Lifecycle adapter for Customer Service extension contributions."""

    def __init__(self, event_bus: InProcessEventBus) -> None:
        self.event_bus = event_bus
        self.projection = CustomerServiceEventProjection()

    async def start(self) -> None:
        for event_type in CUSTOMER_SERVICE_EVENT_TYPES:
            self.event_bus.subscribe(event_type, self.projection)

    async def stop(self) -> None:
        for event_type in CUSTOMER_SERVICE_EVENT_TYPES:
            self.event_bus.unsubscribe(event_type, self.projection)
