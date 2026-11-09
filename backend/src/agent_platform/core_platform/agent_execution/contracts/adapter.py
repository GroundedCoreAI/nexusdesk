"""Engine adapter protocol and explicit identity-boundary checks."""

from collections.abc import AsyncIterator
from typing import Protocol

from .capabilities import EngineCapabilities
from .errors import ConfigurationError, ExecutionError, ExecutionErrorCategory, ExecutionErrorCode
from .events import AgentEvent
from .handle import ExecutionHandle
from .request import ExecutionRequest
from .result import ExecutionResult


class AgentEngineAdapter(Protocol):
    """Structural boundary implemented by each agent engine adapter."""

    @property
    def engine_id(self) -> str: ...

    @property
    def protocol_id(self) -> str: ...

    @property
    def adapter_version(self) -> str: ...

    async def get_capabilities(self) -> EngineCapabilities: ...

    async def start(self, request: ExecutionRequest) -> ExecutionHandle: ...

    def stream_events(self, handle: ExecutionHandle) -> AsyncIterator[AgentEvent]: ...

    async def cancel(self, handle: ExecutionHandle) -> None: ...

    async def collect_result(self, handle: ExecutionHandle) -> ExecutionResult: ...


def _identity(value: ExecutionRequest | ExecutionHandle | ExecutionResult | AgentEvent) -> tuple:
    return (
        value.execution_id,
        value.engine_id,
        value.protocol_id,
        value.adapter_version,
    )


def _identity_error(code: ExecutionErrorCode) -> ConfigurationError:
    return ConfigurationError(
        ExecutionError(
            category=ExecutionErrorCategory.CONFIGURATION_ERROR,
            code=code,
        )
    )


def ensure_request_identity(request: ExecutionRequest, adapter: AgentEngineAdapter) -> None:
    """Reject a request whose identity tuple differs from the adapter."""

    adapter_identity = (adapter.engine_id, adapter.protocol_id, adapter.adapter_version)
    request_identity = (request.engine_id, request.protocol_id, request.adapter_version)
    if request_identity != adapter_identity:
        raise _identity_error(ExecutionErrorCode.INVALID_REQUEST)


def ensure_handle_identity(request: ExecutionRequest, handle: ExecutionHandle) -> None:
    """Reject, rather than repair, a handle with a different execution key."""

    if _identity(request) != _identity(handle):
        raise _identity_error(ExecutionErrorCode.INVALID_HANDLE)


def ensure_result_identity(handle: ExecutionHandle, result: ExecutionResult) -> None:
    """Reject a result that does not belong to the supplied handle."""

    if _identity(handle) != _identity(result):
        raise _identity_error(ExecutionErrorCode.INVALID_RESULT)


def ensure_event_identity(handle: ExecutionHandle, event: AgentEvent) -> None:
    """Reject execution-key or provider-session mismatches for an event."""

    if _identity(handle) != _identity(event):
        raise _identity_error(ExecutionErrorCode.INVALID_EVENT)
    if handle.provider_session_id != event.engine_session_id:
        raise _identity_error(ExecutionErrorCode.INVALID_EVENT)
