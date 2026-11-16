"""Knowledge loop wiring shared by the embedded and standalone topologies.

``Applications/worker/knowledge.py`` runs this loop in its own container, the
way production does; ``embedded_knowledge_worker`` runs the same object inside
the API process so a quickstart or test deployment consumes knowledge without a
second process to remember. Both are safe at once: every claim uses
``FOR UPDATE SKIP LOCKED`` plus a 120-second lease, and parsing/chunking already
runs off the event loop through ``asyncio.to_thread``.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

POLL_SECONDS = 1.0


class KnowledgeWorker:
    """Drain ``knowledge_tasks`` then ``knowledge_jobs`` for one tenant."""

    def __init__(
        self,
        workspace,
        ingestion,
        tenant: str,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self._workspace = workspace
        self._ingestion = ingestion
        self._tenant = tenant
        self._poll = poll_seconds
        self._stopping = asyncio.Event()

    async def serve(self) -> None:
        while not self._stopping.is_set():
            try:
                worked = await self._workspace.run_next(self._tenant)
                if not worked:
                    worked = await self._ingestion.run_next(self._tenant)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - a poll loop must not die on one bad job
                logger.warning("Knowledge loop iteration failed (%s)", type(exc).__name__)
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(self._stopping.wait(), timeout=self._poll)
                except TimeoutError:
                    pass

    def stop(self) -> None:
        self._stopping.set()


def build_knowledge_worker(groups, settings) -> KnowledgeWorker:
    return KnowledgeWorker(
        groups.knowledge_workspace,
        groups.ingestion,
        settings.tenant_id,
    )


def embedded_knowledge_worker(groups, settings):
    """Return the API-embedded loop, or ``None`` when a worker container owns it.

    Follows ``embedded_worker`` exactly like the memory worker, so the two
    loops are never half-embedded: ``AGENT_EMBEDDED_WORKER=false`` means every
    consumer is a separate process.
    """

    if not settings.embedded_worker:
        return None
    return build_knowledge_worker(groups, settings)
