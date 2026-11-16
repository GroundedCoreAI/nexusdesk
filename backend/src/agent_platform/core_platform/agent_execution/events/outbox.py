"""Transactional Outbox dispatcher over the existing durable event bus.

The Event Store stays the source of truth. One publishable durable event
receives one Outbox row in the same transaction (0068 trigger); this dispatcher
maps it onto the existing ``EventEnvelope`` and hands it to an acknowledged
enqueue port. ``published`` means the durable transport accepted the row, not
that every subscriber committed (03 §6.2, FR-12).
"""

import logging
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import text

from agent_platform.extension_contracts import EventEnvelope

logger = logging.getLogger(__name__)

_MAX_BACKOFF_SECONDS = 300
_MAX_ERROR_CHARS = 200


class OutboxPublisher(Protocol):
    """Acknowledged enqueue port; ``DurableEventBus.enqueue`` implements it."""

    async def enqueue(self, event: EventEnvelope) -> bool: ...


@dataclass(frozen=True, slots=True)
class _PendingRow:
    run_id: UUID
    seq: int
    event_id: UUID
    attempts: int
    event_type: str
    data: dict
    trace_id: str | None
    tenant_id: str

    def envelope(self) -> EventEnvelope:
        correlation: UUID | None = None
        if self.trace_id is not None:
            try:
                correlation = UUID(self.trace_id)
            except (TypeError, ValueError):
                correlation = None
        return EventEnvelope(
            event_id=self.event_id,
            event_type=self.event_type[:150],
            event_version=1,
            tenant_id=self.tenant_id,
            aggregate_type="runtime_run",
            aggregate_id=str(self.run_id),
            payload=self.data,
            correlation_id=correlation,
            idempotency_key=str(self.event_id),
        )


class OutboxDispatcher:
    """Publish pending rows; failures stay retryable with bounded backoff."""

    def __init__(
        self,
        engine,
        publisher: OutboxPublisher,
        *,
        batch_size: int = 100,
        poll_seconds: float = 1.0,
        tenant_id: str | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("Outbox batch size must be positive")
        if poll_seconds <= 0:
            raise ValueError("Outbox poll interval must be positive")
        self._engine = engine
        self._publisher = publisher
        self._batch_size = batch_size
        self._poll_seconds = poll_seconds
        # Optional tenant scoping for sharded deployments and controlled tests;
        # the production default publishes every tenant.
        self._tenant_id = tenant_id

    async def dispatch_once(self) -> int:
        """Publish one bounded batch; returns rows transitioned to published.

        Reads are intentionally unlocked: at-least-once publication is safe
        because ``event_id`` is the durable bus idempotency key, and a crash
        before/after the status update simply rescans the pending row.
        """
        tenant_filter = " AND r.tenant_id=:tenant" if self._tenant_id is not None else ""
        params: dict[str, object] = {"batch": self._batch_size}
        if self._tenant_id is not None:
            params["tenant"] = self._tenant_id
        async with self._engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            """SELECT o.run_id,o.seq,o.event_id,o.attempts,
                        e.type AS event_type,e.data,e.trace_id,r.tenant_id
                        FROM runtime_event_outbox o
                        JOIN runtime_events e
                          ON e.run_id=o.run_id AND e.seq=o.seq
                        JOIN runtime_runs r ON r.id=o.run_id
                        WHERE o.status='pending' AND o.available_at<=now()"""
                            + tenant_filter
                            + """ ORDER BY o.created_at,o.seq
                        LIMIT :batch"""
                        ),
                        params,
                    )
                )
                .mappings()
                .all()
            )
        published = 0
        for row in rows:
            pending = _PendingRow(
                run_id=row["run_id"],
                seq=row["seq"],
                event_id=row["event_id"],
                attempts=row["attempts"],
                event_type=row["event_type"],
                data=row["data"] if isinstance(row["data"], dict) else {},
                trace_id=row["trace_id"],
                tenant_id=row["tenant_id"],
            )
            try:
                accepted = await self._publisher.enqueue(pending.envelope())
            except Exception as exc:  # noqa: BLE001 - publisher isolation; type only.
                await self._mark_failed(pending, type(exc).__name__)
                continue
            if not accepted:
                await self._mark_failed(pending, "publisher_rejected")
                continue
            published += await self._mark_published(pending)
        return published

    async def pending_count(self) -> int:
        tenant_filter = " AND r.tenant_id=:tenant" if self._tenant_id is not None else ""
        params: dict[str, object] = {"tenant": self._tenant_id} if self._tenant_id else {}
        async with self._engine.connect() as conn:
            return await conn.scalar(
                text(
                    """SELECT count(*) FROM runtime_event_outbox o
                JOIN runtime_runs r ON r.id=o.run_id
                WHERE o.status='pending'"""
                    + tenant_filter
                ),
                params,
            )

    async def reconcile(self) -> int:
        """Restore missing publishable Outbox rows at/after the rollout watermark."""
        tenant_filter = " AND r.tenant_id=:tenant" if self._tenant_id is not None else ""
        params: dict[str, object] = {}
        if self._tenant_id is not None:
            params["tenant"] = self._tenant_id
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    """INSERT INTO runtime_event_outbox(run_id,seq,event_id,status)
                SELECT e.run_id,e.seq,e.event_id,'pending'
                FROM runtime_events e
                JOIN runtime_runs r ON r.id=e.run_id
                JOIN runtime_event_outbox_watermark w ON w.id='default'
                WHERE e.type <> 'tool.replay'
                  AND e.created_at >= w.created_after"""
                    + tenant_filter
                    + """
                  AND NOT EXISTS (
                    SELECT 1 FROM runtime_event_outbox o
                    WHERE o.run_id=e.run_id AND o.seq=e.seq)
                ON CONFLICT DO NOTHING"""
                ),
                params,
            )
            return result.rowcount or 0

    async def _mark_published(self, pending: _PendingRow) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text("""UPDATE runtime_event_outbox
                SET status='published',published_at=now(),attempts=attempts+1,
                    last_error=NULL
                WHERE run_id=:run_id AND seq=:seq AND status='pending'"""),
                {"run_id": pending.run_id, "seq": pending.seq},
            )
            return result.rowcount or 0

    async def _mark_failed(self, pending: _PendingRow, error: str) -> None:
        backoff = min(_MAX_BACKOFF_SECONDS, 2 ** min(pending.attempts, 8))
        stable = error[:_MAX_ERROR_CHARS] or "publication_failed"
        async with self._engine.begin() as conn:
            await conn.execute(
                text("""UPDATE runtime_event_outbox
                SET attempts=attempts+1,last_error=:error,
                    available_at=now()+:backoff * interval '1 second'
                WHERE run_id=:run_id AND seq=:seq AND status='pending'"""),
                {
                    "run_id": pending.run_id,
                    "seq": pending.seq,
                    "error": stable,
                    "backoff": backoff,
                },
            )
        logger.warning(
            "execution outbox publication deferred run_id=%s seq=%s error=%s",
            pending.run_id,
            pending.seq,
            stable,
        )
