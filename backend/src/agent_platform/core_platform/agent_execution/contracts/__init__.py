"""Public contracts for the agent execution platform."""

from .adapter import (
    AgentEngineAdapter,
    ensure_event_identity,
    ensure_handle_identity,
    ensure_request_identity,
    ensure_result_identity,
)
from .base import ExecutionContractModel
from .capabilities import EngineCapabilities
from .common import ExecutionKey
from .errors import (
    AdapterExecutionError,
    ConfigurationError,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionErrorDetails,
    normalize_adapter_exception,
)
from .events import AgentEvent
from .handle import ExecutionHandle
from .request import ExecutionRequest
from .result import ExecutionResult

__all__ = [
    "AdapterExecutionError",
    "AgentEngineAdapter",
    "AgentEvent",
    "ConfigurationError",
    "EngineCapabilities",
    "ExecutionContractModel",
    "ExecutionError",
    "ExecutionErrorCategory",
    "ExecutionErrorCode",
    "ExecutionErrorDetails",
    "ExecutionHandle",
    "ExecutionKey",
    "ExecutionRequest",
    "ExecutionResult",
    "ensure_event_identity",
    "ensure_handle_identity",
    "ensure_request_identity",
    "ensure_result_identity",
    "normalize_adapter_exception",
]
