"""Event envelope and publish/subscribe contracts."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from pydantic import Field, field_validator

from .base import ContractModel


class EventEnvelope(ContractModel):
    """Tenant-scoped event with an explicit idempotency and correlation identity."""

    event_id: UUID = Field(default_factory=uuid4)
    event_type: str = Field(min_length=1, max_length=150)
    event_version: int = Field(default=1, ge=1)
    tenant_id: str = Field(min_length=1, max_length=200)
    aggregate_type: str = Field(min_length=1, max_length=100)
    aggregate_id: str = Field(min_length=1, max_length=200)
    payload: dict[str, object] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: UUID | None = None
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value


class EventPublisher(Protocol):
    """Platform event bus interface exposed to extensions."""

    async def publish(self, event: EventEnvelope) -> None:
        """Publish an event exactly once per idempotency key."""


class EventSubscriber(Protocol):
    """Subscription interface used by capability adapters."""

    async def handle(self, event: EventEnvelope) -> None:
        """Handle one event idempotently."""
