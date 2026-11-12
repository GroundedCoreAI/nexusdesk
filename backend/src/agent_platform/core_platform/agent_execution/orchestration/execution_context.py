"""Private per-run context and synchronous adapter-factory capture."""

from collections.abc import Callable, Mapping
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from typing import TypeVar
from uuid import UUID

from ..contracts import (
    ConfigurationError,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionRequest,
)

_ANONYMOUS_LEGACY_AGENT_ID = UUID(int=0)
_Resolved = TypeVar("_Resolved")
_execution_context_var: ContextVar[object] = ContextVar("agent_execution_context", default=None)


def _configuration_error(code: ExecutionErrorCode) -> ConfigurationError:
    return ConfigurationError(
        ExecutionError(category=ExecutionErrorCategory.CONFIGURATION_ERROR, code=code)
    )


def _invalid_request() -> ConfigurationError:
    return _configuration_error(ExecutionErrorCode.INVALID_REQUEST)


def _factory_failed() -> ConfigurationError:
    return _configuration_error(ExecutionErrorCode.ADAPTER_FACTORY_FAILED)


def _normalize_execution_uuid(value: object) -> UUID:
    """Return exact stdlib UUID identity without modifying the claimed row value."""
    try:
        if not isinstance(value, UUID):
            raise _invalid_request()
        if type(value) is UUID:
            return value
        if not any(base is UUID for base in type(value).__mro__):
            raise _invalid_request()
        return UUID(str(value))
    except ConfigurationError:
        raise
    except Exception:  # noqa: BLE001 - hostile UUID values must fail closed.
        raise _invalid_request() from None


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """One claimed row and its already-rendered runtime inputs.

    This is deliberately not a serializable DTO. Event callbacks are owned by the
    worker/orchestrator and adapter respectively, and therefore cannot be fields here.
    """

    row: Mapping[str, object]
    execution_id: UUID
    history: list[dict[str, object]]
    summary_message: str | None = None
    customer_memory: str | None = None
    trace_id: str | None = None
    timeout_seconds: int | None = None

    def __post_init__(self) -> None:
        try:
            row = self.row
            if not isinstance(row, Mapping):
                raise _invalid_request()
            execution_id = _normalize_execution_uuid(self.execution_id)
            claimed_id = _normalize_execution_uuid(row.get("id"))
            history = deepcopy(self.history)
            valid = (
                execution_id == claimed_id
                and isinstance(history, list)
                and all(isinstance(item, dict) for item in history)
                and isinstance(self.summary_message, str | None)
                and isinstance(self.customer_memory, str | None)
                and isinstance(self.trace_id, str | None)
                and (
                    self.timeout_seconds is None
                    or (type(self.timeout_seconds) is int and self.timeout_seconds > 0)
                )
            )
        except ConfigurationError:
            raise
        except Exception:  # noqa: BLE001 - arbitrary context inputs must fail closed.
            raise _invalid_request() from None
        if not valid:
            raise _invalid_request()
        object.__setattr__(self, "execution_id", execution_id)
        object.__setattr__(self, "history", history)


def build_execution_context(
    row: Mapping[str, object],
    *,
    history: list[dict[str, object]],
    summary_message: str | None = None,
    customer_memory: str | None = None,
    trace_id: str | None = None,
    timeout_seconds: int | None = None,
) -> ExecutionContext:
    """Validate and capture current-run inputs without consulting an Agent repository."""
    try:
        if not isinstance(row, Mapping):
            raise _invalid_request()
        return ExecutionContext(
            row=row,
            execution_id=row["id"],
            history=history,
            summary_message=summary_message,
            customer_memory=customer_memory,
            trace_id=trace_id,
            timeout_seconds=timeout_seconds,
        )
    except ConfigurationError:
        raise
    except Exception:  # noqa: BLE001 - arbitrary claimed-row access must fail closed.
        raise _invalid_request() from None


def _snapshot_agent_id(row: Mapping[str, object]) -> UUID:
    config = row.get("config")
    if not isinstance(config, Mapping):
        raise _invalid_request()
    if "agent" not in config:
        # The fixed React request builder only reaches this branch for RuntimeFactory's
        # no-snapshot legacy base_runtime path. The sentinel is never used for a lookup.
        return _ANONYMOUS_LEGACY_AGENT_ID

    snapshot = config["agent"]
    if not isinstance(snapshot, Mapping) or "id" not in snapshot:
        raise _invalid_request()
    value = snapshot["id"]
    try:
        if type(value) is UUID:
            agent_id = value
        elif type(value) is str:
            agent_id = UUID(value)
        else:
            raise _invalid_request()
    except (ValueError, TypeError, AttributeError):
        raise _invalid_request() from None
    if agent_id == _ANONYMOUS_LEGACY_AGENT_ID:
        raise _invalid_request()
    return agent_id


def build_execution_request(context: ExecutionContext) -> ExecutionRequest:
    """Build the fixed React/native/v1 request from one validated claimed row."""
    if not isinstance(context, ExecutionContext):
        raise _invalid_request()
    try:
        row = context.row
        return ExecutionRequest(
            execution_id=context.execution_id,
            engine_id="react",
            protocol_id="native",
            adapter_version="v1",
            tenant_id=row["tenant_id"],
            agent_id=_snapshot_agent_id(row),
            conversation_id=row.get("conversation_id"),
            input=row["input"],
            config={},
            effective_capabilities={},
            engine_session_id=row.get("engine_session_id"),
            workspace_id=row.get("workspace_id"),
            trace_id=context.trace_id,
            execution_workdir=row.get("execution_workdir"),
            timeout_seconds=context.timeout_seconds,
        )
    except ConfigurationError:
        raise
    except Exception:  # noqa: BLE001 - arbitrary claimed-row access must fail closed.
        raise _invalid_request() from None


def capture_execution_context() -> ExecutionContext:
    """Synchronously capture the current context into an adapter being constructed."""
    context = _execution_context_var.get()
    if not isinstance(context, ExecutionContext):
        raise _factory_failed()
    return context


def resolve_with_execution_context(
    context: ExecutionContext,
    resolve: Callable[[], _Resolved],
) -> _Resolved:
    """Run a synchronous zero-arg resolve in a scoped, finally-reset context."""
    if not isinstance(context, ExecutionContext) or not callable(resolve):
        raise _factory_failed()
    token = _execution_context_var.set(context)
    try:
        return resolve()
    finally:
        _execution_context_var.reset(token)
