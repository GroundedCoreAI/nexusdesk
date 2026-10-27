"""Durable capability configuration storage and audit integration."""

import json
import logging
from datetime import UTC

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from agent_platform.core_platform.platform_services.persistence.store import audit, one
from agent_platform.extension_contracts import CapabilityConfigVersion

from .registry import CapabilityRegistry, ExtensionRegistryError

logger = logging.getLogger(__name__)


class CapabilityConfigService:
    """Persist platform-level capability configuration snapshots.

    Capability configuration is platform-scoped: a manifest and its active
    configuration are shared by the process. The tenant and actor are retained
    on the audit record that describes who changed the platform configuration.
    """

    def __init__(self, engine, registry: CapabilityRegistry) -> None:
        self.engine = engine
        self.registry = registry

    async def load(self) -> None:
        """Hydrate the in-process registry from the durable configuration log."""

        async with self.engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            """
                        SELECT capability_id, version, schema_version, config,
                               created_by, created_at, rollback_of
                        FROM plugin_config_versions
                        ORDER BY capability_id, version
                        """
                        )
                    )
                )
                .mappings()
                .all()
            )
        for row in rows:
            self.registry.load_config_version(self._snapshot(row))

    async def configure(
        self,
        capability_id: str,
        config: dict[str, object],
        tenant_id: str,
        actor: str,
        schema_version: str = "v1",
    ) -> CapabilityConfigVersion:
        """Validate, persist, audit, and activate a new configuration."""

        self.registry.validate_configuration(capability_id, config, actor, schema_version)
        encoded = json.dumps(config, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        try:
            async with self.engine.begin() as conn:
                version = await self._next_version(conn, capability_id)
                row = await self._insert(
                    conn,
                    capability_id,
                    version,
                    schema_version,
                    encoded,
                    actor,
                    None,
                )
                await audit(
                    conn,
                    tenant_id,
                    actor,
                    "extension.config.updated",
                    f"{capability_id}@{version}",
                    capability_id=capability_id,
                    version=version,
                    schema_version=schema_version,
                )
        except SQLAlchemyError as exc:
            logger.exception("failed to persist capability configuration")
            raise ExtensionRegistryError("capability configuration persistence failed") from exc
        snapshot = self._snapshot(row)
        await self.registry.activate_config_version(snapshot)
        return snapshot

    async def rollback_config(
        self,
        capability_id: str,
        version: int,
        tenant_id: str,
        actor: str,
    ) -> CapabilityConfigVersion:
        """Create a new durable version from a previous configuration."""

        self.registry.validate_configuration(capability_id, {}, actor)
        try:
            async with self.engine.begin() as conn:
                target_row = await one(
                    conn,
                    """
                    SELECT capability_id, version, schema_version, config,
                           created_by, created_at, rollback_of
                    FROM plugin_config_versions
                    WHERE capability_id=:capability_id AND version=:version
                    """,
                    capability_id=capability_id,
                    version=version,
                )
                if target_row is None:
                    raise ExtensionRegistryError(
                        f"capability configuration version not found: {capability_id}@{version}"
                    )
                target = self._snapshot(target_row)
                self.registry.validate_configuration(
                    capability_id,
                    target.config,
                    actor,
                    target.schema_version,
                )
                next_version = await self._next_version(conn, capability_id)
                row = await self._insert(
                    conn,
                    capability_id,
                    next_version,
                    target.schema_version,
                    json.dumps(
                        target.config,
                        ensure_ascii=False,
                        allow_nan=False,
                        separators=(",", ":"),
                    ),
                    actor,
                    version,
                )
                await audit(
                    conn,
                    tenant_id,
                    actor,
                    "extension.config.rolled_back",
                    f"{capability_id}@{next_version}",
                    capability_id=capability_id,
                    version=next_version,
                    rollback_of=version,
                    schema_version=target.schema_version,
                )
        except ExtensionRegistryError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("failed to persist capability configuration rollback")
            raise ExtensionRegistryError("capability configuration persistence failed") from exc
        snapshot = self._snapshot(row)
        await self.registry.activate_config_version(snapshot)
        return snapshot

    async def current(self, capability_id: str) -> CapabilityConfigVersion | None:
        """Return the durable active snapshot for one capability."""

        row = await self._read_one(capability_id)
        return self._snapshot(row) if row else None

    async def versions(self, capability_id: str) -> tuple[CapabilityConfigVersion, ...]:
        """Return durable configuration history in creation order."""

        if self.registry.get(capability_id) is None:
            raise ExtensionRegistryError(f"capability not registered: {capability_id}")
        async with self.engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            """
                        SELECT capability_id, version, schema_version, config,
                               created_by, created_at, rollback_of
                        FROM plugin_config_versions
                        WHERE capability_id=:capability_id
                        ORDER BY version
                        """
                        ),
                        {"capability_id": capability_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(self._snapshot(row) for row in rows)

    async def _read_one(self, capability_id: str):
        async with self.engine.connect() as conn:
            return await one(
                conn,
                """
                SELECT capability_id, version, schema_version, config,
                       created_by, created_at, rollback_of
                FROM plugin_config_versions
                WHERE capability_id=:capability_id
                ORDER BY version DESC
                LIMIT 1
                """,
                capability_id=capability_id,
            )

    async def _next_version(self, conn, capability_id: str) -> int:
        """Allocate a version while serializing writers across API processes."""

        await conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:capability_id))"),
            {"capability_id": capability_id},
        )
        row = await one(
            conn,
            """
            SELECT COALESCE(MAX(version), 0) AS version
            FROM plugin_config_versions
            WHERE capability_id=:capability_id
            """,
            capability_id=capability_id,
        )
        return int(row["version"]) + 1

    async def _insert(
        self,
        conn,
        capability_id: str,
        version: int,
        schema_version: str,
        encoded_config: str,
        actor: str,
        rollback_of: int | None,
    ):
        result = await conn.execute(
            text(
                """
                INSERT INTO plugin_config_versions(
                    capability_id, version, schema_version, config,
                    created_by, rollback_of
                )
                VALUES(
                    :capability_id, :version, :schema_version, CAST(:config AS jsonb),
                    :created_by, :rollback_of
                )
                RETURNING capability_id, version, schema_version, config,
                          created_by, created_at, rollback_of
                """
            ),
            {
                "capability_id": capability_id,
                "version": version,
                "schema_version": schema_version,
                "config": encoded_config,
                "created_by": actor,
                "rollback_of": rollback_of,
            },
        )
        return result.mappings().one()

    @staticmethod
    def _snapshot(row) -> CapabilityConfigVersion:
        created_at = row["created_at"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return CapabilityConfigVersion(
            capability_id=row["capability_id"],
            version=row["version"],
            schema_version=row["schema_version"],
            config=row["config"],
            created_by=row["created_by"],
            created_at=created_at,
            rollback_of=row["rollback_of"],
        )
