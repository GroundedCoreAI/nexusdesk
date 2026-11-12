"""Pure, non-sensitive mapping from React runtime failures to safe public errors."""

import asyncio
import sys
from dataclasses import dataclass

from ...contracts import (
    AdapterExecutionError,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
)

_PublicError = tuple[ExecutionErrorCategory, ExecutionErrorCode]
_INVALID_REQUEST: _PublicError = (
    ExecutionErrorCategory.CONFIGURATION_ERROR,
    ExecutionErrorCode.INVALID_REQUEST,
)
_PROTOCOL_ERROR: _PublicError = (
    ExecutionErrorCategory.PROTOCOL_ERROR,
    ExecutionErrorCode.PROTOCOL_ERROR,
)
_RESOURCE_EXHAUSTED: _PublicError = (
    ExecutionErrorCategory.RESOURCE_EXHAUSTED,
    ExecutionErrorCode.RESOURCE_EXHAUSTED,
)
_ENGINE_UNAVAILABLE: _PublicError = (
    ExecutionErrorCategory.ENGINE_UNAVAILABLE,
    ExecutionErrorCode.ENGINE_UNAVAILABLE,
)
_PERMISSION_DENIED: _PublicError = (
    ExecutionErrorCategory.PERMISSION_DENIED,
    ExecutionErrorCode.PERMISSION_DENIED,
)
_AUTHENTICATION_FAILED: _PublicError = (
    ExecutionErrorCategory.AUTHENTICATION_ERROR,
    ExecutionErrorCode.AUTHENTICATION_FAILED,
)
_TIMEOUT: _PublicError = (
    ExecutionErrorCategory.TIMEOUT,
    ExecutionErrorCode.EXECUTION_TIMEOUT,
)
_INTERNAL_ERROR: _PublicError = (
    ExecutionErrorCategory.INTERNAL_ERROR,
    ExecutionErrorCode.INTERNAL_ERROR,
)
_RUNTIME_FAULT_MODULE = "agent_platform.core_platform.agent_runtime.schemas"


def _codes(codes: str, public_error: _PublicError) -> dict[str, _PublicError]:
    return {code: public_error for code in codes.split()}


_ERROR_MAP: dict[str, _PublicError] = {
    **_codes(
        "agent_model_required configuration_changed model_resource_not_found "
        "model_resource_disabled model_profile_version_not_found model_tools_not_supported "
        "model_not_configured",
        _INVALID_REQUEST,
    ),
    **_codes(
        "model_input_too_large model_round_limit tool_call_limit model_output_too_large "
        "gateway_concurrency_exceeded gateway_request_quota_exceeded model_response_too_large",
        _RESOURCE_EXHAUSTED,
    ),
    **_codes(
        "invalid_model_response empty_model_response duplicate_tool_call_id repeated_tool_call",
        _PROTOCOL_ERROR,
    ),
    **_codes(
        "model_provider_unavailable model_rate_limited model_provider_rejected "
        "model_transport_error model_stream_interrupted",
        _ENGINE_UNAVAILABLE,
    ),
    **_codes("content_blocked_input content_blocked_output", _PERMISSION_DENIED),
    "model_credential_unavailable": _AUTHENTICATION_FAILED,
    "model_timeout": _TIMEOUT,
}


@dataclass(frozen=True, slots=True)
class ReactErrorMapping:
    """Safe public error plus the original private Run failure code."""

    error: ExecutionError
    legacy_error_code: str


def _mapping(public_error: _PublicError, legacy_error_code: str) -> ReactErrorMapping:
    category, code = public_error
    return ReactErrorMapping(
        error=ExecutionError(category=category, code=code),
        legacy_error_code=legacy_error_code,
    )


def map_protocol_error(*, legacy_error_code: str = "execution_error") -> ReactErrorMapping:
    """Map reserved/malformed events and acknowledgement failures without raw details."""
    safe_legacy_code = legacy_error_code if legacy_error_code else "execution_error"
    return _mapping(_PROTOCOL_ERROR, safe_legacy_code)


def _is_runtime_fault(exception: Exception) -> bool:
    """Use the already-loaded class object without importing or trusting class names."""
    try:
        module = sys.modules.get(_RUNTIME_FAULT_MODULE)
        if module is None:
            return False
        fault_type = vars(module).get("RuntimeFault")
        if type(fault_type) is not type:
            return False
        return any(base is fault_type for base in type(exception).__mro__)
    except Exception:  # noqa: BLE001 - hostile type metadata must fail closed.
        return False


def _exception_group_leaves(exception: BaseExceptionGroup) -> list[Exception]:
    """Flatten TaskGroup failures without selecting or rendering arbitrary leaves."""
    leaves: list[Exception] = []
    groups = [exception]
    while groups:
        group = groups.pop()
        for child in reversed(group.exceptions):
            if isinstance(child, BaseExceptionGroup):
                groups.append(child)
            elif isinstance(
                child,
                (asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit),
            ) or not isinstance(child, Exception):
                raise exception
            else:
                leaves.append(child)
    return leaves


def map_execution_error(
    exception: BaseException,
    *,
    legacy_error_code: str | None = None,
) -> ReactErrorMapping:
    """Map lifecycle failures while never retaining raw exception text or traceback."""
    if isinstance(
        exception,
        (asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit),
    ):
        raise exception
    if not isinstance(exception, Exception):
        raise exception

    if isinstance(exception, BaseExceptionGroup):
        leaves = _exception_group_leaves(exception)
        if not leaves:
            return _mapping(_INTERNAL_ERROR, "execution_error")
        if len(leaves) == 1:
            return map_execution_error(leaves[0], legacy_error_code=legacy_error_code)
        mappings = [
            map_execution_error(leaf, legacy_error_code=legacy_error_code) for leaf in leaves
        ]
        first = mappings[0]
        identity = (first.error, first.legacy_error_code)
        if all((mapped.error, mapped.legacy_error_code) == identity for mapped in mappings[1:]):
            return first
        return _mapping(_INTERNAL_ERROR, "execution_error")

    if _is_runtime_fault(exception):
        try:
            code = exception.code
        except Exception:  # noqa: BLE001 - fault descriptors must not leak raw failures.
            return _mapping(_INTERNAL_ERROR, "execution_error")
        if type(code) is not str or not code:
            return _mapping(_INTERNAL_ERROR, "execution_error")
        return _mapping(_ERROR_MAP.get(code, _INTERNAL_ERROR), code)
    if isinstance(exception, TimeoutError):
        return _mapping(_TIMEOUT, "run_timeout")
    if isinstance(exception, AdapterExecutionError):
        return ReactErrorMapping(
            error=exception.error,
            legacy_error_code=legacy_error_code or "execution_error",
        )
    return _mapping(_INTERNAL_ERROR, "execution_error")
