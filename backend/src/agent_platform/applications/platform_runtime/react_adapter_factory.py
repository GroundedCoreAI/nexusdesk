"""Synchronous fresh ReactAdapter construction from the current execution scope."""

from agent_platform.core_platform.agent_execution.adapters.react.adapter import (
    ReactAdapter,
    RuntimeFactory,
)
from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
    capture_execution_context,
)


class ReactAdapterFactory:
    """Capture ContextVar synchronously; Runtime construction remains in the runner."""

    def __init__(self, runtime_factory: RuntimeFactory) -> None:
        self._runtime_factory = runtime_factory

    def __call__(self) -> ReactAdapter:
        return ReactAdapter(capture_execution_context(), self._runtime_factory)
