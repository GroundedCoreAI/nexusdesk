"""Open business-event mapping with an adapter-local envelope."""

import asyncio
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

from ...contracts import AdapterExecutionError, AgentEvent, ExecutionRequest
from .error_mapper import map_protocol_error

_ENVELOPE_FIELDS = frozenset(
    {
        "event_id",
        "schema_version",
        "execution_id",
        "engine_id",
        "protocol_id",
        "adapter_version",
        "engine_session_id",
        "sequence",
        "event_type",
        "source",
        "timestamp",
        "payload",
        "trace_id",
    }
)


def _protocol_error() -> AdapterExecutionError:
    error = AdapterExecutionError(map_protocol_error().error)
    error.__cause__ = None
    error.__context__ = None
    error.__traceback__ = None
    error.__suppress_context__ = True
    return error


class ReactEventMapper:
    """Map raw ``(kind, data)`` pairs without a business-event allowlist."""

    def __init__(
        self,
        request: ExecutionRequest,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], UUID] | None = None,
    ) -> None:
        self._request = request
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or uuid4
        self._sequence = 0

    def map(self, kind: object, data: object) -> AgentEvent:
        """Create one fresh event or fail safely before it reaches a consumer."""
        try:
            if type(kind) is not str or type(data) is not dict:
                raise ValueError
            if kind.startswith("run.") or kind == "tool.replay":
                raise ValueError
            if _ENVELOPE_FIELDS.intersection(data):
                raise ValueError
            payload = deepcopy(data)
            event = AgentEvent(
                event_id=self._id_factory(),
                execution_id=self._request.execution_id,
                engine_id=self._request.engine_id,
                protocol_id=self._request.protocol_id,
                adapter_version=self._request.adapter_version,
                engine_session_id=self._request.engine_session_id,
                sequence=self._sequence + 1,
                event_type=kind,
                source="engine_native",
                timestamp=self._clock(),
                payload=payload,
                trace_id=self._request.trace_id,
            )
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit):
            raise
        except Exception:  # noqa: BLE001 - arbitrary runtime payloads must fail closed.
            raise _protocol_error() from None
        self._sequence += 1
        return event
