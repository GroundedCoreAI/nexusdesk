"""Agent execution event contract."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, JsonValue, field_validator

from .common import EventType, ExecutionKey, OpaqueString


class AgentEvent(ExecutionKey):
    """One explicitly identified event with a UTC-normalized timestamp."""

    event_id: UUID
    schema_version: Literal["v1"] = "v1"
    engine_session_id: OpaqueString | None = None
    sequence: int = Field(ge=1)
    event_type: EventType
    source: Literal["platform", "engine_native"]
    timestamp: datetime
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    trace_id: OpaqueString | None = None

    @field_validator("timestamp")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Event timestamp must be timezone-aware.")
        return value.astimezone(UTC)
