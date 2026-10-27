"""Durable operator state for capability lifecycle management."""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TypeVar

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .registry import CapabilityRegistry, ExtensionRegistryError

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


class CapabilityRuntimeStateService:
    """Persist and hydrate capability enablement without restoring stale failures."""

    def __init__(self, engine, registry: CapabilityRegistry) -> None:
        self.engine = engine
        self.registry = registry

    async def run_lifecycle_locked(
        self,
        capability_id: str,
        operation: Callable[[], Awaitable[_T]],
    ) -> _T:
        """Run one lifecycle mutation while holding a cross-process advisory lock.

        The lock is session-scoped and the connection remains checked out for
        the whole operation. This is intentional: lifecycle hooks can take
        longer than a transaction, while concurrent API workers must still
        serialize enable/disable/upgrade/rollback for one capability.
        """

        lock_key = f"nexusdesk:capability-lifecycle:{capability_id}"
        async with self.engine.connect() as conn:
            await conn.execute(
                text("SELECT pg_advisory_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": lock_key},
            )
            await conn.commit()
            try:
                return await operation()
            finally:
                await conn.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:lock_key, 0))"),
                    {"lock_key": lock_key},
                )
                await conn.commit()

    async def load(self) -> None:
        """Load compatible lifecycle state after all manifests are registered."""

        async with self.engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT capability_id, manifest_version, enabled,
                                   failure_count, reason, last_started_at,
                                   last_stopped_at, last_failure_at
                            FROM plugin_runtime_state
                            ORDER BY capability_id
                            """
                        )
                    )
                )
                .mappings()
                .all()
            )
        for row in rows:
            try:
                self.registry.load_runtime_state(
                    row["capability_id"],
                    manifest_version=row["manifest_version"],
                    enabled=row["enabled"],
                    failure_count=row["failure_count"],
                    reason=row["reason"],
                    last_started_at=_as_utc(row["last_started_at"]),
                    last_stopped_at=_as_utc(row["last_stopped_at"]),
                    last_failure_at=_as_utc(row["last_failure_at"]),
                )
            except ExtensionRegistryError:
                logger.warning(
                    "Ignoring stale capability runtime state for %s",
                    row["capability_id"],
                )

    async def persist(self, capability_id: str, actor: str) -> None:
        """Persist the current lifecycle view after a successful operator action."""

        view = self.registry.get(capability_id)
        if view is None:
            raise ExtensionRegistryError(f"capability not registered: {capability_id}")
        try:
            async with self.engine.begin() as conn:
                await conn.execute(
                    text(
                        """
                        INSERT INTO plugin_runtime_state(
                            capability_id, manifest_version, enabled, status,
                            reason, failure_count, last_started_at,
                            last_stopped_at, last_failure_at, updated_by
                        )
                        VALUES(
                            :capability_id, :manifest_version, :enabled, :status,
                            :reason, :failure_count, :last_started_at,
                            :last_stopped_at, :last_failure_at, :updated_by
                        )
                        ON CONFLICT (capability_id) DO UPDATE SET
                            manifest_version=EXCLUDED.manifest_version,
                            enabled=EXCLUDED.enabled,
                            status=EXCLUDED.status,
                            reason=EXCLUDED.reason,
                            failure_count=EXCLUDED.failure_count,
                            last_started_at=EXCLUDED.last_started_at,
                            last_stopped_at=EXCLUDED.last_stopped_at,
                            last_failure_at=EXCLUDED.last_failure_at,
                            updated_by=EXCLUDED.updated_by,
                            updated_at=now()
                        """
                    ),
                    {
                        "capability_id": view.capability_id,
                        "manifest_version": view.version,
                        "enabled": view.enabled,
                        "status": view.status,
                        "reason": view.reason,
                        "failure_count": view.failure_count,
                        "last_started_at": view.last_started_at,
                        "last_stopped_at": view.last_stopped_at,
                        "last_failure_at": view.last_failure_at,
                        "updated_by": actor,
                    },
                )
        except (SQLAlchemyError, OSError, TimeoutError) as exc:
            logger.exception("failed to persist capability runtime state")
            raise ExtensionRegistryError("capability runtime state persistence failed") from exc

    async def persist_all(self, actor: str) -> None:
        """Persist all known capabilities after startup lifecycle evaluation."""

        for item in self.registry.list():
            await self.persist(item.capability_id, actor)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


__all__ = ["CapabilityRuntimeStateService"]
