"""Runtime admission services assembled by the application composition root."""

from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    execute,
    one,
)

from .schemas import RunRequest


class RuntimeAdmission:
    """Submit legacy application requests without exposing platform services."""

    def __init__(
        self,
        engine: object,
        repository: object,
        agents: object,
        settings: object,
        snapshot: dict[str, object],
    ) -> None:
        self.engine = engine
        self.repository = repository
        self.agents = agents
        self.settings = settings
        self.snapshot = snapshot

    async def submit(self, tenant: str, body: RunRequest) -> object:
        async with self.engine.begin() as connection:
            await execute(connection, "SELECT pg_advisory_xact_lock(71432019)")
            conversation = await one(
                connection,
                "SELECT * FROM runtime_conversations WHERE tenant_id=:t AND external_id=:key",
                t=tenant,
                key=body.conversation_id,
            )
            snapshot = dict(self.snapshot)
            if conversation and conversation["agent_id"]:
                snapshot["agent"] = await self.agents.snapshot(
                    tenant, conversation["agent_id"], connection
                )
            elif self.settings.model_backend == "unconfigured":
                raise DomainError("model_not_configured", 409)
            return await self.repository.submit(
                tenant,
                body,
                snapshot,
                self.settings.queue_capacity,
                self.settings.tenant_capacity,
                self.settings.queue_timeout_seconds,
                connection=connection,
            )
