"""Event buses and durable delivery for the extension platform.

The first implementation was process-local.  The durable variant deliberately
reuses the existing ``memory_tasks`` queue rather than introducing another
table during the modular-monolith refactor.  Event delivery remains
at-least-once; capability projections therefore deduplicate by the envelope's
idempotency key.
"""

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import Iterable

from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    execute,
    many,
    one,
)
from agent_platform.extension_contracts import EventEnvelope, EventPublisher, EventSubscriber

logger = logging.getLogger(__name__)
EVENT_TASK_KIND = "extension_event"


class InProcessEventBus(EventPublisher):
    """Publish tenant-scoped events to registered capability subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventSubscriber]] = defaultdict(list)
        self._published: set[str] = set()
        self._failures: list[dict[str, str]] = []
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: str, subscriber: EventSubscriber) -> None:
        """Register a subscriber for one event type."""

        if subscriber not in self._subscribers[event_type]:
            self._subscribers[event_type].append(subscriber)

    def unsubscribe(self, event_type: str, subscriber: EventSubscriber) -> None:
        """Remove a subscriber without affecting other capability listeners."""

        subscribers = self._subscribers.get(event_type)
        if not subscribers:
            return
        if subscriber in subscribers:
            subscribers.remove(subscriber)
        if not subscribers:
            self._subscribers.pop(event_type, None)

    def subscribers(self, event_type: str) -> tuple[EventSubscriber, ...]:
        """Return a stable snapshot for diagnostics and tests."""

        return tuple(self._subscribers.get(event_type, ()))

    def failures(self) -> tuple[dict[str, str], ...]:
        """Return delivery failures recorded by this process."""

        return tuple(self._failures)

    def observability(self) -> dict[str, int]:
        """Return process-local delivery counters for operational endpoints."""

        return {
            "published": len(self._published),
            "subscribers": sum(len(items) for items in self._subscribers.values()),
            "failures": len(self._failures),
        }

    async def publish(self, event: EventEnvelope) -> None:
        """Deliver an event once for its idempotency key."""

        async with self._lock:
            if event.idempotency_key in self._published:
                return
            await self._deliver_locked(event)

    async def deliver(self, event: EventEnvelope) -> bool:
        """Force one delivery attempt for a durable retry."""

        async with self._lock:
            return await self._deliver_locked(event)

    async def _deliver_locked(self, event: EventEnvelope) -> bool:
        subscribers: Iterable[EventSubscriber] = tuple(self._subscribers.get(event.event_type, ()))
        failed = False
        for subscriber in subscribers:
            try:
                await subscriber.handle(event)
            except Exception as exc:
                failed = True
                self._failures.append(
                    {
                        "event_type": event.event_type,
                        "idempotency_key": event.idempotency_key,
                        "subscriber": type(subscriber).__name__,
                        "error_type": type(exc).__name__,
                    }
                )
                logger.exception(
                    "Extension event subscriber failed for %s (%s)",
                    event.event_type,
                    type(subscriber).__name__,
                )
        if not failed:
            self._published.add(event.idempotency_key)
        return not failed


class EventDeliveryError(RuntimeError):
    """Raised by the durable worker when a subscriber still needs a retry."""


class DurableEventBus(InProcessEventBus):
    """Persist event envelopes in the existing durable task queue.

    ``publish`` first creates an idempotent ``extension_event`` task, then
    attempts local delivery.  A failed local subscriber leaves the task
    pending; a memory worker retries it later through ``deliver``.
    """

    def __init__(self, engine, max_attempts: int = 5) -> None:
        super().__init__()
        self.engine = engine
        self.max_attempts = max_attempts
        self._persistence_failures = 0

    async def publish(self, event: EventEnvelope) -> None:
        try:
            task = await self._ensure_task(event)
        except Exception:
            self._persistence_failures += 1
            logger.exception("Failed to persist extension event %s", event.event_type)
            await self.deliver(event)
            return
        if task["status"] in {"done", "failed"}:
            return
        if await self.deliver(event):
            try:
                await self._mark_done(task["id"])
            except Exception:
                self._persistence_failures += 1
                logger.exception("Failed to mark extension event %s done", event.event_type)
        else:
            try:
                await self._leave_pending(task["id"])
            except Exception:
                self._persistence_failures += 1
                logger.exception("Failed to reschedule extension event %s", event.event_type)

    def observability(self) -> dict[str, int]:
        return {
            **super().observability(),
            "persistence_failures": self._persistence_failures,
        }

    async def _ensure_task(self, event: EventEnvelope) -> dict[str, object]:
        payload = {
            "event": event.model_dump(mode="json"),
            "idempotency_key": event.idempotency_key,
        }
        async with self.engine.begin() as conn:
            await execute(
                conn,
                "SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))",
                key=event.idempotency_key,
            )
            existing = await one(
                conn,
                """SELECT id,status FROM memory_tasks
                WHERE tenant_id=:tenant AND business_id=:business_id
                  AND workspace_id=:workspace_id AND kind=:kind
                  AND payload->>'idempotency_key'=:key
                ORDER BY created_at LIMIT 1""",
                tenant=event.tenant_id,
                business_id=payload.get("business_id", "customer-service"),
                workspace_id=payload.get("workspace_id", "default"),
                kind=EVENT_TASK_KIND,
                key=event.idempotency_key,
            )
            if existing is not None:
                return existing
            return await one(
                conn,
                """INSERT INTO memory_tasks
                (tenant_id,business_id,workspace_id,kind,payload,max_attempts)
                VALUES(:tenant,:business_id,:workspace_id,:kind,CAST(:payload AS jsonb),:max_attempts)
                RETURNING id,status""",
                tenant=event.tenant_id,
                business_id=payload.get("business_id", "customer-service"),
                workspace_id=payload.get("workspace_id", "default"),
                kind=EVENT_TASK_KIND,
                payload=json.dumps(payload, ensure_ascii=False),
                max_attempts=self.max_attempts,
            )

    async def _mark_done(self, task_id) -> None:
        async with self.engine.begin() as conn:
            await execute(
                conn,
                """
                UPDATE memory_tasks
                SET status='done', error=NULL, owner=NULL,
                    lease_expires_at=NULL, updated_at=now()
                WHERE id=:id AND kind=:kind
                """,
                id=task_id,
                kind=EVENT_TASK_KIND,
            )

    async def _leave_pending(self, task_id) -> None:
        async with self.engine.begin() as conn:
            await execute(
                conn,
                """
                UPDATE memory_tasks
                SET status='pending', error='subscriber_failed',
                    owner=NULL, lease_expires_at=NULL,
                    run_after=now()+5*interval '1 second', updated_at=now()
                WHERE id=:id AND kind=:kind AND status <> 'done'
                """,
                id=task_id,
                kind=EVENT_TASK_KIND,
            )

    async def delivery_status(self, tenant: str | None = None) -> dict[str, object]:
        """Return durable queue counts plus process-local delivery counters."""

        async with self.engine.connect() as conn:
            tenant_filter = " AND tenant_id=:tenant" if tenant is not None else ""
            rows = await many(
                conn,
                f"""
                SELECT status,count(*)::int AS count
                FROM memory_tasks
                WHERE kind=:kind{tenant_filter}
                GROUP BY status
                ORDER BY status
                """,
                kind=EVENT_TASK_KIND,
                **({"tenant": tenant} if tenant is not None else {}),
            )
            counts = {row["status"]: row["count"] for row in rows}
            # Keep the operational response shape stable when a queue state
            # has no rows.  Consumers should be able to render ``failed: 0``
            # (and the other known states) without special-casing an absent
            # key.
            counts = {
                status: counts.get(status, 0)
                for status in ("pending", "running", "done", "failed")
            }
        return {**self.observability(), "queue": counts}

    async def list_tasks(
        self,
        tenant: str,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, object]:
        """List tenant-scoped event tasks without exposing event payload content."""

        where = "tenant_id=:tenant AND kind=:kind"
        params: dict[str, object] = {"tenant": tenant, "kind": EVENT_TASK_KIND}
        if status is not None:
            where += " AND status=:status"
            params["status"] = status
        async with self.engine.connect() as conn:
            total = await one(
                conn,
                f"SELECT count(*)::int AS total FROM memory_tasks WHERE {where}",
                **params,
            )
            items = await many(
                conn,
                f"""
                SELECT id,status,attempts,max_attempts,error,run_after,
                       created_at,updated_at,
                       payload->>'idempotency_key' AS idempotency_key,
                       payload->'event'->>'event_type' AS event_type,
                       payload->'event'->>'aggregate_type' AS aggregate_type,
                       payload->'event'->>'aggregate_id' AS aggregate_id
                FROM memory_tasks
                WHERE {where}
                ORDER BY created_at DESC,id DESC
                LIMIT :limit OFFSET :offset
                """,
                **params,
                limit=page_size,
                offset=(page - 1) * page_size,
            )
        return {"items": items, "total": total["total"], "page": page, "page_size": page_size}

    async def retry_task(self, tenant: str, task_id) -> dict[str, object]:
        """Reset one failed event task for an immediate manual retry."""

        async with self.engine.begin() as conn:
            row = await one(
                conn,
                """UPDATE memory_tasks
                SET status='pending',attempts=0,error=NULL,owner=NULL,
                    lease_expires_at=NULL,run_after=now(),updated_at=now()
                WHERE id=:id AND tenant_id=:tenant AND kind=:kind AND status='failed'
                RETURNING id,status,attempts,max_attempts,error,run_after,updated_at""",
                id=task_id,
                tenant=tenant,
                kind=EVENT_TASK_KIND,
            )
        if row is None:
            raise DomainError("event_not_retryable", 409)
        return row


class DurableEventTaskDispatcher:
    """Adapter used by the shared task worker to deliver persisted events."""

    def __init__(self, event_bus: InProcessEventBus) -> None:
        self.event_bus = event_bus

    async def execute(self, task: dict[str, object]) -> str:
        event = EventEnvelope.model_validate(task["payload"]["event"])
        if not await self.event_bus.deliver(event):
            raise EventDeliveryError("subscriber_failed")
        return "done"
