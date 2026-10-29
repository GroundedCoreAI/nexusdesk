"""Knowledge capability lifecycle and retrieval-event projection."""

from collections import Counter

from agent_platform.core_platform.platform_services.events import InProcessEventBus
from agent_platform.extension_contracts import CapabilityLifecycle, EventEnvelope, EventSubscriber


class KnowledgeEventProjection(EventSubscriber):
    """Observe retrieval events without coupling the capability to run storage."""

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


class KnowledgeCapability(CapabilityLifecycle):
    """Lifecycle adapter for Knowledge extension contributions."""

    def __init__(self, event_bus: InProcessEventBus) -> None:
        self.event_bus = event_bus
        self.projection = KnowledgeEventProjection()

    async def start(self) -> None:
        self.event_bus.subscribe("knowledge.retrieved", self.projection)

    async def stop(self) -> None:
        self.event_bus.unsubscribe("knowledge.retrieved", self.projection)
