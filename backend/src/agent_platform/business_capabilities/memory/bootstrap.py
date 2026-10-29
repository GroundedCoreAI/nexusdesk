"""Assembly of the memory claim loop for both deployment forms.

- quickstart / development: the API process lifespan embeds the loop when
  ``AGENT_EMBEDDED_WORKER=true`` (``embedded_memory_worker``), mirroring how the
  embedded runtime worker is gated; the two-container promise is unchanged.
- production: the standalone ``memory-worker`` container runs
  ``python -m agent_platform.applications.worker.memory`` (``build_memory_worker``),
  decoupled from the runtime worker and horizontally scalable.

Phase 2 added ``memory_extract`` tasks and Phase 3 adds ``event_write`` tasks
to the shared queue; the dispatcher routes each claimed row to its service by
``kind``. The deployment shape is unchanged — the existing memory-worker gains
new task kinds purely through code.
"""

from agent_platform.business_capabilities.memory.decay import REINFORCE_KIND, ReinforceService
from agent_platform.business_capabilities.memory.events import EVENT_KIND, EventWriter
from agent_platform.business_capabilities.memory.extraction import EXTRACT_KIND, ExtractionService
from agent_platform.business_capabilities.memory.service import MemoryService
from agent_platform.business_capabilities.memory.store import TsVectorStore
from agent_platform.business_capabilities.memory.summary import SummaryService
from agent_platform.business_capabilities.memory.worker import MemoryWorker
from agent_platform.core_platform.platform_services.events import (
    EVENT_TASK_KIND,
    DurableEventTaskDispatcher,
    InProcessEventBus,
)


class MemoryDispatcher:
    """Route claimed tasks to the service that owns their kind."""

    def __init__(self, summary, extraction, events=None, reinforce=None, event_bus=None):
        self.summary, self.extraction, self.events = summary, extraction, events
        self.reinforce = reinforce
        self.event_bus = event_bus
        self.event_dispatcher = (
            DurableEventTaskDispatcher(event_bus)
            if isinstance(event_bus, InProcessEventBus)
            else None
        )

    async def execute(self, task):
        if task["kind"] == EVENT_TASK_KIND:
            if self.event_dispatcher is None:
                return "skipped"
            return await self.event_dispatcher.execute(task)
        if task["kind"] == EXTRACT_KIND:
            return await self.extraction.execute(task)
        if task["kind"] == EVENT_KIND and self.events is not None:
            return await self.events.execute(task)
        if task["kind"] == REINFORCE_KIND and self.reinforce is not None:
            return await self.reinforce.execute(task)
        return await self.summary.execute(task)


def build_memory_worker(groups, settings):
    """Wire a MemoryWorker from explicit Runtime service groups."""
    engine = groups.runtime.engine
    gateway = groups.runtime.gateway
    store = groups.business.memory_store or TsVectorStore(engine, settings)
    dispatcher = MemoryDispatcher(
        SummaryService(engine, gateway, settings),
        ExtractionService(engine, gateway, settings, MemoryService(engine, settings)),
        EventWriter(engine, store, settings),
        ReinforceService(engine, settings),
        event_bus=getattr(groups.runtime, "events", None),
    )
    return MemoryWorker(engine, dispatcher, settings, store=store)


def embedded_memory_worker(groups, settings):
    """Assemble the API-embedded claim loop when the deployment opted in.

    Returns ``None`` unless the embedded worker mode and at least one memory
    feature is enabled, so the caller simply skips starting the loop. The
    gate follows the Phase 3 R10 extension precedent: Phase 1-3 write
    features (summary/extraction/events) plus, since Phase 4 (R23a), the
    periodic jobs — ``memory_decay_enabled`` and the rule scan
    (``memory_rule_scan_interval_minutes>0``). Both default on, so a
    quickstart that turned off only the write features still runs the
    timers it never asked to disable; the standalone production worker is
    unaffected either way.
    """
    if not (
        settings.embedded_worker
        and (
            settings.summary_enabled
            or settings.memory_extract_enabled
            or settings.memory_event_enabled
            or getattr(settings, "memory_decay_enabled", False)
            or getattr(settings, "memory_rule_scan_interval_minutes", 0) > 0
            or getattr(groups.runtime, "events", None) is not None
        )
    ):
        return None
    return build_memory_worker(groups, settings)
