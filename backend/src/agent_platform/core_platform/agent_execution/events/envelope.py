"""Durable event identity derived from the existing AgentEvent v1 contract.

The common envelope already exists (``contracts/events.py``). This module adds
only the internal write projection: it preserves the event identity, keeps the
adapter-local ``sequence`` as producer metadata, and distinguishes the internal
``tool.replay`` event (identity-bearing, fenced, never publicly published).
"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from pydantic import JsonValue

from ..contracts.events import AgentEvent

EVENT_SCHEMA_VERSION = "v1"
EVENT_SOURCES: tuple[str, ...] = ("platform", "engine_native")
# The one internal type excluded from public Outbox publication (08 R-4).
INTERNAL_NON_PUBLISHABLE_EVENT_TYPES: frozenset[str] = frozenset({"tool.replay"})
# Additive optional producer metadata names React must reserve (03 §4.2).
PRODUCER_FIELD_NAMES: tuple[str, ...] = ("producer_id", "producer_event_id")


def _is_uuid(value: object) -> bool:
    return isinstance(value, UUID) and (
        type(value) is UUID or any(base is UUID for base in type(value).__mro__)
    )


def _bounded_name(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError(f"{field_name} must be a nonempty string of at most 200 characters")
    return value


@dataclass(frozen=True, slots=True)
class EventProducerIdentity:
    """Optional stable native producer key for deduplication.

    Both halves are required together: a half key cannot be declared unique in
    the partial database index without becoming ambiguous. Existing producers
    (which supply neither) remain valid.
    """

    producer_id: str | None = None
    producer_event_id: str | None = None

    def __post_init__(self) -> None:
        if self.producer_id is None and self.producer_event_id is None:
            return
        if self.producer_id is None or self.producer_event_id is None:
            raise ValueError("producer identity requires both producer_id and producer_event_id")
        object.__setattr__(self, "producer_id", _bounded_name(self.producer_id, "producer_id"))
        object.__setattr__(
            self, "producer_event_id", _bounded_name(self.producer_event_id, "producer_event_id")
        )

    def dedup_key(self) -> tuple[str, str] | None:
        if self.producer_id is None or self.producer_event_id is None:
            return None
        return (self.producer_id, self.producer_event_id)


@dataclass(frozen=True, slots=True)
class AgentEventWrite:
    """One internal durable-event write, pre-database.

    ``producer_sequence`` is the Adapter-local sequence from ``AgentEvent`` and
    is metadata only. ``durable_sequence`` stays None until the Repository's
    transaction allocates ``runtime_events.seq``.
    """

    run_id: UUID
    event_id: UUID
    schema_version: str
    event_type: str
    source: str
    timestamp: datetime
    payload: dict[str, JsonValue] = field(default_factory=dict)
    engine_session_id: str | None = None
    trace_id: str | None = None
    producer_id: str | None = None
    producer_event_id: str | None = None
    producer_sequence: int = 1
    durable_sequence: int | None = None

    def __post_init__(self) -> None:
        if not _is_uuid(self.run_id) or not _is_uuid(self.event_id):
            raise ValueError("durable event identity requires run and event UUIDs")
        if self.schema_version != EVENT_SCHEMA_VERSION:
            raise ValueError("unsupported durable event schema version")
        if self.source not in EVENT_SOURCES:
            raise ValueError("durable event source is outside the closed vocabulary")
        if not isinstance(self.event_type, str) or not self.event_type:
            raise ValueError("durable event type must be nonempty")
        if not (self.timestamp.tzinfo is not None and self.timestamp.utcoffset() is not None):
            raise ValueError("durable event timestamp must be timezone-aware")
        if type(self.producer_sequence) is not int or self.producer_sequence < 1:
            raise ValueError("producer sequence must be a positive integer")
        if self.durable_sequence is not None and (
            type(self.durable_sequence) is not int or self.durable_sequence < 1
        ):
            raise ValueError("durable sequence must be a positive integer or None")
        if not isinstance(self.payload, Mapping):
            raise TypeError("durable event payload must be a mapping")
        if self.producer_id is not None or self.producer_event_id is not None:
            EventProducerIdentity(self.producer_id, self.producer_event_id)
        object.__setattr__(self, "payload", deepcopy(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class EventWriteResult:
    """The durable identity a write landed with, or the original on duplicate."""

    seq: int
    event_id: UUID
    duplicate: bool

    def __post_init__(self) -> None:
        if type(self.seq) is not int or self.seq < 1:
            raise ValueError("event write result requires a positive durable sequence")
        if not _is_uuid(self.event_id):
            raise ValueError("event write result requires an event UUID")
        if type(self.duplicate) is not bool:
            raise ValueError("event write result duplicate marker must be a boolean")


def is_publishable(event_type: str) -> bool:
    """Whether one durable event type may enter the public Outbox."""
    return isinstance(event_type, str) and event_type not in INTERNAL_NON_PUBLISHABLE_EVENT_TYPES


def from_agent_event(
    event: AgentEvent,
    *,
    run_id: UUID | None = None,
    producer: EventProducerIdentity | None = None,
    durable_sequence: int | None = None,
) -> AgentEventWrite:
    """Project one existing AgentEvent into the internal write DTO."""
    if not isinstance(event, AgentEvent):
        raise TypeError("durable event projection requires an AgentEvent")
    bound_run = event.execution_id if run_id is None else run_id
    if not _is_uuid(bound_run) or bound_run != event.execution_id:
        raise ValueError("durable event run binding must match the AgentEvent execution identity")
    identity = producer or EventProducerIdentity()
    return AgentEventWrite(
        run_id=bound_run,
        event_id=event.event_id,
        schema_version=event.schema_version,
        event_type=event.event_type,
        source=event.source,
        timestamp=event.timestamp,
        payload=dict(event.payload),
        engine_session_id=event.engine_session_id,
        trace_id=event.trace_id,
        producer_id=identity.producer_id,
        producer_event_id=identity.producer_event_id,
        producer_sequence=event.sequence,
        durable_sequence=durable_sequence,
    )
