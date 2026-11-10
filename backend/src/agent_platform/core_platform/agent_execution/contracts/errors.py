"""Safe execution errors and static diagnostic catalog."""

import asyncio
from collections.abc import Mapping
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, computed_field, model_validator

from .base import ExecutionContractModel
from .common import AdapterVersion, EngineId, ProtocolId, Slug


class ExecutionErrorCategory(StrEnum):
    CONFIGURATION_ERROR = "configuration_error"
    ENGINE_UNAVAILABLE = "engine_unavailable"
    PROTOCOL_ERROR = "protocol_error"
    AUTHENTICATION_ERROR = "authentication_error"
    PERMISSION_DENIED = "permission_denied"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    WORKSPACE_ERROR = "workspace_error"
    INTERNAL_ERROR = "internal_error"


class ExecutionErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    INVALID_HANDLE = "invalid_handle"
    INVALID_RESULT = "invalid_result"
    INVALID_EVENT = "invalid_event"
    INVALID_SCENARIO = "invalid_scenario"
    INVALID_ADAPTER_STATE = "invalid_adapter_state"
    DUPLICATE_ENGINE = "duplicate_engine"
    DUPLICATE_PROTOCOL = "duplicate_protocol"
    DUPLICATE_ADAPTER = "duplicate_adapter"
    UNKNOWN_ENGINE = "unknown_engine"
    ENGINE_DISABLED = "engine_disabled"
    UNKNOWN_PROTOCOL = "unknown_protocol"
    PROTOCOL_DISABLED = "protocol_disabled"
    INCOMPATIBLE_ENGINE_PROTOCOL = "incompatible_engine_protocol"
    UNKNOWN_ADAPTER_VERSION = "unknown_adapter_version"
    ADAPTER_DISABLED = "adapter_disabled"
    ADAPTER_FACTORY_FAILED = "adapter_factory_failed"
    ADAPTER_IDENTITY_MISMATCH = "adapter_identity_mismatch"
    ADAPTER_CONTRACT_MISMATCH = "adapter_contract_mismatch"
    ENGINE_UNAVAILABLE = "engine_unavailable"
    PROTOCOL_ERROR = "protocol_error"
    EVENT_IDENTITY_CONFLICT = "event_identity_conflict"
    AUTHENTICATION_FAILED = "authentication_failed"
    PERMISSION_DENIED = "permission_denied"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    EXECUTION_TIMEOUT = "execution_timeout"
    EXECUTION_CANCELLED = "execution_cancelled"
    WORKSPACE_ERROR = "workspace_error"
    INTERNAL_ERROR = "internal_error"
    SIMULATED_PROCESS_FAILURE = "simulated_process_failure"


_ERROR_CATALOG: dict[ExecutionErrorCode, tuple[ExecutionErrorCategory, str]] = {
    ExecutionErrorCode.INVALID_REQUEST: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Execution request is invalid.",
    ),
    ExecutionErrorCode.INVALID_HANDLE: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Execution handle is invalid.",
    ),
    ExecutionErrorCode.INVALID_RESULT: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Execution result is invalid.",
    ),
    ExecutionErrorCode.INVALID_EVENT: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Agent event is invalid.",
    ),
    ExecutionErrorCode.INVALID_SCENARIO: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Local test scenario is invalid.",
    ),
    ExecutionErrorCode.INVALID_ADAPTER_STATE: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Adapter state does not allow this operation.",
    ),
    ExecutionErrorCode.DUPLICATE_ENGINE: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Engine is already registered.",
    ),
    ExecutionErrorCode.DUPLICATE_PROTOCOL: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Protocol is already registered.",
    ),
    ExecutionErrorCode.DUPLICATE_ADAPTER: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Adapter is already registered for this exact tuple.",
    ),
    ExecutionErrorCode.UNKNOWN_ENGINE: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Engine is not registered.",
    ),
    ExecutionErrorCode.ENGINE_DISABLED: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Engine is disabled.",
    ),
    ExecutionErrorCode.UNKNOWN_PROTOCOL: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Protocol is not registered.",
    ),
    ExecutionErrorCode.PROTOCOL_DISABLED: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Protocol is disabled.",
    ),
    ExecutionErrorCode.INCOMPATIBLE_ENGINE_PROTOCOL: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Engine and protocol have no registered adapter combination.",
    ),
    ExecutionErrorCode.UNKNOWN_ADAPTER_VERSION: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Adapter version is not registered for this engine and protocol.",
    ),
    ExecutionErrorCode.ADAPTER_DISABLED: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Adapter is disabled.",
    ),
    ExecutionErrorCode.ADAPTER_FACTORY_FAILED: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Adapter factory failed safely.",
    ),
    ExecutionErrorCode.ADAPTER_IDENTITY_MISMATCH: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Adapter identity does not match its registration.",
    ),
    ExecutionErrorCode.ADAPTER_CONTRACT_MISMATCH: (
        ExecutionErrorCategory.CONFIGURATION_ERROR,
        "Adapter does not implement the required contract.",
    ),
    ExecutionErrorCode.ENGINE_UNAVAILABLE: (
        ExecutionErrorCategory.ENGINE_UNAVAILABLE,
        "Engine is unavailable.",
    ),
    ExecutionErrorCode.PROTOCOL_ERROR: (
        ExecutionErrorCategory.PROTOCOL_ERROR,
        "Adapter protocol failed.",
    ),
    ExecutionErrorCode.EVENT_IDENTITY_CONFLICT: (
        ExecutionErrorCategory.PROTOCOL_ERROR,
        "Event identity conflicts with different content.",
    ),
    ExecutionErrorCode.AUTHENTICATION_FAILED: (
        ExecutionErrorCategory.AUTHENTICATION_ERROR,
        "Engine authentication failed.",
    ),
    ExecutionErrorCode.PERMISSION_DENIED: (
        ExecutionErrorCategory.PERMISSION_DENIED,
        "Engine permission was denied.",
    ),
    ExecutionErrorCode.RESOURCE_EXHAUSTED: (
        ExecutionErrorCategory.RESOURCE_EXHAUSTED,
        "Engine resources are exhausted.",
    ),
    ExecutionErrorCode.EXECUTION_TIMEOUT: (
        ExecutionErrorCategory.TIMEOUT,
        "Execution timed out.",
    ),
    ExecutionErrorCode.EXECUTION_CANCELLED: (
        ExecutionErrorCategory.CANCELLED,
        "Execution was cancelled.",
    ),
    ExecutionErrorCode.WORKSPACE_ERROR: (
        ExecutionErrorCategory.WORKSPACE_ERROR,
        "Engine workspace operation failed.",
    ),
    ExecutionErrorCode.INTERNAL_ERROR: (
        ExecutionErrorCategory.INTERNAL_ERROR,
        "Execution failed internally.",
    ),
    ExecutionErrorCode.SIMULATED_PROCESS_FAILURE: (
        ExecutionErrorCategory.INTERNAL_ERROR,
        "Simulated process failure occurred.",
    ),
}


class ExecutionErrorDetails(ExecutionContractModel):
    """Restricted, non-sensitive diagnostic context."""

    engine_id: EngineId | None = None
    protocol_id: ProtocolId | None = None
    adapter_version: AdapterVersion | None = None
    field: Slug | None = None
    operation: Slug | None = None


class ExecutionError(ExecutionContractModel):
    """Safe error data whose message comes only from the static catalog."""

    contract_version: Literal["v1"] = "v1"
    category: ExecutionErrorCategory = Field(strict=False)
    code: ExecutionErrorCode = Field(strict=False)
    retryable: bool = False
    details: ExecutionErrorDetails = Field(default_factory=ExecutionErrorDetails)

    @model_validator(mode="before")
    @classmethod
    def validate_message_integrity_token(cls, data: object) -> object:
        if not isinstance(data, Mapping) or "message" not in data:
            return data
        try:
            code = ExecutionErrorCode(data.get("code"))
        except (TypeError, ValueError):
            raise ValueError("Error message requires a valid error code.") from None
        message = data["message"]
        if not isinstance(message, str) or message != _ERROR_CATALOG[code][1]:
            raise ValueError("Error message must exactly match the static catalog message.")
        validated_data = dict(data)
        validated_data.pop("message")
        return validated_data

    @model_validator(mode="after")
    def validate_catalog_consistency(self) -> Self:
        expected_category = _ERROR_CATALOG[self.code][0]
        if self.category is not expected_category:
            raise ValueError("Error category does not match the static code catalog.")
        if self.retryable and self.category not in {
            ExecutionErrorCategory.ENGINE_UNAVAILABLE,
            ExecutionErrorCategory.RESOURCE_EXHAUSTED,
        }:
            raise ValueError("This error code is not retryable.")
        return self

    @computed_field
    @property
    def message(self) -> str:
        return _ERROR_CATALOG[self.code][1]


class AdapterExecutionError(Exception):
    """Exception carrying one already-validated, safe execution error."""

    def __init__(self, error: ExecutionError) -> None:
        if not isinstance(error, ExecutionError):
            raise TypeError("error must be an ExecutionError")
        self.error = error
        super().__init__(error.message)
        self.__suppress_context__ = True

    def __str__(self) -> str:
        return self.error.message


class ConfigurationError(AdapterExecutionError):
    """Safe registry, lifecycle, or configuration misuse error."""


def normalize_adapter_exception(exception: BaseException) -> AdapterExecutionError:
    """Map boundary failures to safe errors without retaining exception text."""

    if isinstance(
        exception,
        (asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit),
    ):
        raise exception
    if not isinstance(exception, Exception):
        raise exception
    if isinstance(exception, AdapterExecutionError):
        return exception
    if isinstance(exception, TimeoutError):
        error = ExecutionError(
            category=ExecutionErrorCategory.TIMEOUT,
            code=ExecutionErrorCode.EXECUTION_TIMEOUT,
        )
    else:
        error = ExecutionError(
            category=ExecutionErrorCategory.INTERNAL_ERROR,
            code=ExecutionErrorCode.INTERNAL_ERROR,
        )
    return AdapterExecutionError(error)
