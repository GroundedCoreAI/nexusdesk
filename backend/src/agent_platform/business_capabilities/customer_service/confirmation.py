"""Compatibility adapter for the existing pending-action confirmation flow."""

from uuid import UUID

from agent_platform.core_platform.platform_services.persistence.store import one


class CustomerConfirmationAdapter:
    """Expose pending actions through the Runtime confirmation port.

    Ticket creation and its transaction rules remain owned by
    ``CustomerService``.  This adapter only provides the stable confirmation
    boundary needed by the platform harness.
    """

    def __init__(self, customer_service):
        self.customer_service = customer_service

    async def get(self, tenant_id: str, confirmation_id: UUID):
        async with self.customer_service.engine.connect() as connection:
            return await one(
                connection,
                "SELECT id,tenant_id,conversation_id,kind,payload,status,expires_at "
                "FROM pending_actions WHERE id=:id AND tenant_id=:tenant_id",
                id=confirmation_id,
                tenant_id=tenant_id,
            )

    async def decide(self, tenant_id, actor_id, confirmation_id, approve):
        return await self.customer_service.decide(
            tenant_id,
            actor_id,
            confirmation_id,
            approve,
        )
