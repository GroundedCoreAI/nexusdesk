"""Private execution outcome and acknowledgement-capable stream protocol."""

import inspect
from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Literal, Protocol, Self, cast, runtime_checkable

from pydantic import JsonValue

from ..contracts import AgentEvent, ExecutionHandle, ExecutionResult


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """Worker-facing terminal data that is intentionally absent from public DTOs."""

    status: Literal["completed", "failed", "cancelled"]
    output: str | None = None
    history: list[dict[str, object]] | None = None
    dropped: list[dict[str, object]] | None = None
    legacy_error_code: str | None = None
    usage: dict[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in {"completed", "failed", "cancelled"}:
            raise ValueError("Unknown execution outcome status")
        if not isinstance(self.usage, dict):
            raise TypeError("Outcome usage must be a dictionary")
        try:
            history = deepcopy(self.history)
            dropped = deepcopy(self.dropped)
            usage = deepcopy(self.usage)
        except Exception:  # noqa: BLE001 - private values must fail without raw diagnostics.
            raise TypeError("Outcome values must be deep-copyable") from None

        if self.status == "completed":
            if not isinstance(history, list) or not all(isinstance(item, dict) for item in history):
                raise ValueError("Completed outcomes require history")
            if not isinstance(dropped, list) or not all(isinstance(item, dict) for item in dropped):
                raise ValueError("Completed outcomes require dropped history")
            if self.legacy_error_code is not None:
                raise ValueError("Completed outcomes cannot have an error code")
        else:
            if self.output is not None or history is not None or dropped is not None:
                raise ValueError("Failed and cancelled outcomes cannot carry completion values")
            if self.status == "failed":
                if not isinstance(self.legacy_error_code, str) or not self.legacy_error_code:
                    raise ValueError("Failed outcomes require a legacy error code")
            elif self.legacy_error_code is not None:
                raise ValueError("Cancelled outcomes cannot have an error code")

        object.__setattr__(self, "history", history)
        object.__setattr__(self, "dropped", dropped)
        object.__setattr__(self, "usage", usage)

    @classmethod
    def from_result(
        cls,
        result: ExecutionResult,
        *,
        history: list[dict[str, object]] | None = None,
        dropped: list[dict[str, object]] | None = None,
        legacy_error_code: str | None = None,
    ) -> "ExecutionOutcome":
        """Keep public usage verbatim while separating successful Memory values."""
        if not isinstance(result, ExecutionResult):
            raise TypeError("result must be an ExecutionResult")
        if result.status == "completed":
            return cls(
                status="completed",
                output=result.output,
                history=history if history is not None else [],
                dropped=dropped if dropped is not None else [],
                usage=result.usage,
            )
        if history is not None or dropped is not None:
            raise ValueError("Only completed outcomes can carry Memory values")
        return cls(
            status=result.status,
            output=result.output,
            legacy_error_code=legacy_error_code,
            usage=result.usage,
        )


@runtime_checkable
class AcknowledgingEventStream(Protocol):
    """AsyncIterator plus acknowledgement, abort, and close capabilities."""

    def __aiter__(self) -> Self: ...

    async def __anext__(self) -> AgentEvent: ...

    async def acknowledge(self, event: AgentEvent) -> None: ...

    async def abort(self, error: BaseException) -> None: ...

    async def aclose(self) -> None: ...


def _is_async_callable(method: object) -> bool:
    return inspect.iscoroutinefunction(method) or inspect.iscoroutinefunction(type(method).__call__)


def as_acknowledging_event_stream(
    stream: AsyncIterator[AgentEvent],
) -> AcknowledgingEventStream | None:
    """Return only genuinely asynchronous acknowledgement capabilities."""
    try:
        if not isinstance(stream, AcknowledgingEventStream):
            return None
        if not callable(stream.__aiter__) or _is_async_callable(stream.__aiter__):
            return None
        async_methods = (stream.__anext__, stream.acknowledge, stream.abort, stream.aclose)
        if not all(_is_async_callable(method) for method in async_methods):
            return None
    except Exception:  # noqa: BLE001 - untrusted structural descriptors must fail closed.
        return None
    return cast(AcknowledgingEventStream, stream)


@runtime_checkable
class OutcomeCollectingAdapter(Protocol):
    """Core-private terminal collection that retains Engine-internal error codes."""

    async def collect_outcome(self, handle: ExecutionHandle) -> ExecutionOutcome: ...


def as_outcome_collecting_adapter(adapter: object) -> OutcomeCollectingAdapter | None:
    """Detect real asynchronous private collection without trusting async lookalikes."""
    try:
        if not isinstance(adapter, OutcomeCollectingAdapter):
            return None
        if not _is_async_callable(adapter.collect_outcome):
            return None
    except Exception:  # noqa: BLE001 - untrusted structural descriptors must fail closed.
        return None
    return cast(OutcomeCollectingAdapter, adapter)
