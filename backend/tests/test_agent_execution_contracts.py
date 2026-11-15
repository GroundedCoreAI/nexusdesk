import ast
import asyncio
import inspect
import json
import traceback
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import get_type_hints
from uuid import UUID

import pytest
from pydantic import ValidationError

import agent_platform.core_platform.agent_execution as execution_package
from agent_platform.core_platform.agent_execution.contracts import (
    AdapterExecutionError,
    AgentEngineAdapter,
    AgentEvent,
    ConfigurationError,
    EngineCapabilities,
    ExecutionContractModel,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionErrorDetails,
    ExecutionHandle,
    ExecutionRequest,
    ExecutionResult,
    ensure_event_identity,
    ensure_handle_identity,
    ensure_request_identity,
    ensure_result_identity,
    normalize_adapter_exception,
)
from agent_platform.extension_contracts.base import ContractModel

EXECUTION_ID = UUID("00000000-0000-4000-8000-000000000001")
AGENT_ID = UUID("00000000-0000-4000-8000-000000000002")
CONVERSATION_ID = UUID("00000000-0000-4000-8000-000000000003")
EVENT_ID = UUID("00000000-0000-4000-8000-000000000004")
TIMESTAMP = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
KEY = {
    "execution_id": EXECUTION_ID,
    "engine_id": "local-test",
    "protocol_id": "scripted",
    "adapter_version": "v1",
}

ERROR_CATALOG = {
    ("configuration_error", "invalid_request"): "Execution request is invalid.",
    ("configuration_error", "invalid_handle"): "Execution handle is invalid.",
    ("configuration_error", "invalid_result"): "Execution result is invalid.",
    ("configuration_error", "invalid_event"): "Agent event is invalid.",
    ("configuration_error", "invalid_scenario"): "Local test scenario is invalid.",
    ("configuration_error", "invalid_adapter_state"): (
        "Adapter state does not allow this operation."
    ),
    ("configuration_error", "duplicate_engine"): "Engine is already registered.",
    ("configuration_error", "duplicate_protocol"): "Protocol is already registered.",
    ("configuration_error", "duplicate_adapter"): (
        "Adapter is already registered for this exact tuple."
    ),
    ("configuration_error", "unknown_engine"): "Engine is not registered.",
    ("configuration_error", "engine_disabled"): "Engine is disabled.",
    ("configuration_error", "unknown_protocol"): "Protocol is not registered.",
    ("configuration_error", "protocol_disabled"): "Protocol is disabled.",
    ("configuration_error", "incompatible_engine_protocol"): (
        "Engine and protocol have no registered adapter combination."
    ),
    ("configuration_error", "unknown_adapter_version"): (
        "Adapter version is not registered for this engine and protocol."
    ),
    ("configuration_error", "adapter_disabled"): "Adapter is disabled.",
    ("configuration_error", "adapter_factory_failed"): "Adapter factory failed safely.",
    ("configuration_error", "adapter_identity_mismatch"): (
        "Adapter identity does not match its registration."
    ),
    ("configuration_error", "adapter_contract_mismatch"): (
        "Adapter does not implement the required contract."
    ),
    ("engine_unavailable", "engine_unavailable"): "Engine is unavailable.",
    ("protocol_error", "protocol_error"): "Adapter protocol failed.",
    ("protocol_error", "event_identity_conflict"): (
        "Event identity conflicts with different content."
    ),
    ("authentication_error", "authentication_failed"): "Engine authentication failed.",
    ("permission_denied", "permission_denied"): "Engine permission was denied.",
    ("resource_exhausted", "resource_exhausted"): "Engine resources are exhausted.",
    ("timeout", "execution_timeout"): "Execution timed out.",
    ("cancelled", "execution_cancelled"): "Execution was cancelled.",
    ("workspace_error", "workspace_error"): "Engine workspace operation failed.",
    ("internal_error", "internal_error"): "Execution failed internally.",
    ("internal_error", "simulated_process_failure"): "Simulated process failure occurred.",
}

EXPECTED_FIELDS = {
    ExecutionRequest: {
        "execution_id",
        "engine_id",
        "protocol_id",
        "adapter_version",
        "contract_version",
        "tenant_id",
        "agent_id",
        "conversation_id",
        "input",
        "config",
        "effective_capabilities",
        "engine_session_id",
        "workspace_id",
        "trace_id",
        "execution_workdir",
        "timeout_seconds",
    },
    ExecutionHandle: {
        "execution_id",
        "engine_id",
        "protocol_id",
        "adapter_version",
        "contract_version",
        "provider_session_id",
        "process_id",
        "status",
        "metadata",
    },
    ExecutionResult: {
        "execution_id",
        "engine_id",
        "protocol_id",
        "adapter_version",
        "contract_version",
        "status",
        "output",
        "artifacts",
        "usage",
        "engine_metadata",
        "error",
    },
    ExecutionError: {"contract_version", "category", "code", "retryable", "details"},
    AgentEvent: {
        "event_id",
        "execution_id",
        "engine_id",
        "protocol_id",
        "adapter_version",
        "schema_version",
        "engine_session_id",
        "sequence",
        "event_type",
        "source",
        "timestamp",
        "payload",
        "trace_id",
    },
    EngineCapabilities: {
        "contract_version",
        "streaming",
        "persistent_session",
        "session_resume",
        "cancellation",
        "human_approval",
        "interactive_input",
        "tool_calling",
        "file_operations",
        "terminal_execution",
        "native_events",
        "workspace_required",
    },
}

REQUIRED_FIELDS = {
    ExecutionRequest: {
        "execution_id",
        "engine_id",
        "protocol_id",
        "adapter_version",
        "tenant_id",
        "agent_id",
        "input",
    },
    ExecutionHandle: {"execution_id", "engine_id", "protocol_id", "adapter_version"},
    ExecutionResult: {"execution_id", "engine_id", "protocol_id", "adapter_version", "status"},
    ExecutionError: {"category", "code"},
    AgentEvent: {
        "event_id",
        "execution_id",
        "engine_id",
        "protocol_id",
        "adapter_version",
        "sequence",
        "event_type",
        "source",
        "timestamp",
    },
    EngineCapabilities: set(),
}


def request_data(**overrides):
    data = {
        **KEY,
        "tenant_id": "tenant-1",
        "agent_id": AGENT_ID,
        "input": "  raw input\n\t",
    }
    data.update(overrides)
    return data


def handle_data(**overrides):
    data = dict(KEY)
    data.update(overrides)
    return data


def result_data(**overrides):
    data = {**KEY, "status": "completed"}
    data.update(overrides)
    return data


def error_data(**overrides):
    data = {"category": "internal_error", "code": "internal_error"}
    data.update(overrides)
    return data


def event_data(**overrides):
    data = {
        "event_id": EVENT_ID,
        **KEY,
        "sequence": 1,
        "event_type": "engine.output_delta",
        "source": "engine_native",
        "timestamp": TIMESTAMP,
    }
    data.update(overrides)
    return data


def make_request(**overrides):
    return ExecutionRequest(**request_data(**overrides))


def make_handle(**overrides):
    return ExecutionHandle(**handle_data(**overrides))


def make_result(**overrides):
    return ExecutionResult(**result_data(**overrides))


def make_error(**overrides):
    return ExecutionError(**error_data(**overrides))


def make_event(**overrides):
    return AgentEvent(**event_data(**overrides))


MODEL_FACTORIES = {
    ExecutionRequest: request_data,
    ExecutionHandle: handle_data,
    ExecutionResult: result_data,
    ExecutionError: error_data,
    AgentEvent: event_data,
    EngineCapabilities: dict,
}


def test_execution_base_reuses_contract_model_with_explicit_strict_frozen_policy():
    assert issubclass(ExecutionContractModel, ContractModel)
    expected = {
        "strict": True,
        "str_strip_whitespace": False,
        "frozen": True,
        "extra": "forbid",
        "allow_inf_nan": False,
    }
    assert all(ExecutionContractModel.model_config[key] == value for key, value in expected.items())


@pytest.mark.parametrize("model", list(MODEL_FACTORIES), ids=lambda model: model.__name__)
def test_valid_models_have_exact_fields_and_reject_unknown_fields(model):
    model(**MODEL_FACTORIES[model]())
    assert set(model.model_fields) == EXPECTED_FIELDS[model]
    with pytest.raises(ValidationError):
        model(**MODEL_FACTORIES[model](), unexpected="value")


@pytest.mark.parametrize(
    "model,field",
    [(model, field) for model, fields in REQUIRED_FIELDS.items() for field in sorted(fields)],
    ids=lambda value: value if isinstance(value, str) else value.__name__,
)
def test_models_reject_each_missing_required_field(model, field):
    data = MODEL_FACTORIES[model]()
    data.pop(field)
    with pytest.raises(ValidationError):
        model(**data)


def test_versions_and_serialized_computed_message():
    versioned = [
        (ExecutionRequest, request_data(), "contract_version"),
        (ExecutionHandle, handle_data(), "contract_version"),
        (ExecutionResult, result_data(), "contract_version"),
        (ExecutionError, error_data(), "contract_version"),
        (EngineCapabilities, {}, "contract_version"),
        (AgentEvent, event_data(), "schema_version"),
    ]
    for model, data, field in versioned:
        assert getattr(model(**data), field) == "v1"
        with pytest.raises(ValidationError):
            model(**data, **{field: "v2"})

    error = make_error()
    assert error.model_dump()["message"] == "Execution failed internally."
    assert json.loads(error.model_dump_json())["message"] == "Execution failed internally."
    serialization_schema = error.model_json_schema(mode="serialization")
    assert serialization_schema["properties"]["message"]["readOnly"] is True
    with pytest.raises(ValidationError):
        make_error(message="caller text")


def test_exact_optional_and_status_defaults():
    request = make_request()
    assert request.conversation_id is None
    assert request.engine_session_id is None
    assert request.workspace_id is None
    assert request.trace_id is None
    assert request.execution_workdir is None
    assert request.timeout_seconds is None

    handle = make_handle()
    assert handle.provider_session_id is None
    assert handle.process_id is None
    assert handle.status == "running"
    with pytest.raises(ValidationError):
        make_handle(status="completed")

    result = make_result()
    assert result.output is None
    assert result.error is None

    error = make_error()
    assert error.retryable is False
    assert error.details == ExecutionErrorDetails()

    event = make_event()
    assert event.engine_session_id is None
    assert event.trace_id is None


@pytest.mark.parametrize("field", ["engine_id", "protocol_id"])
@pytest.mark.parametrize(
    "value",
    ["", "-bad", "_bad", "Upper", "has.dot", " bad", "bad ", "a" * 65, 7, None],
)
def test_engine_and_protocol_identity_grammar(field, value):
    with pytest.raises(ValidationError):
        make_request(**{field: value})


@pytest.mark.parametrize("value", ["latest", "v0", "v01", " v1", "v1 ", "V1", "1", 1, None])
def test_adapter_version_grammar(value):
    with pytest.raises(ValidationError):
        make_request(adapter_version=value)


@pytest.mark.parametrize("version", ["v1", "v2", "v10", "v999"])
def test_adapter_version_accepts_explicit_positive_versions(version):
    assert make_request(adapter_version=version).adapter_version == version


@pytest.mark.parametrize(
    "field,value",
    [
        ("engine_session_id", "session-1"),
        ("workspace_id", "workspace-1"),
        ("trace_id", "trace-1"),
        ("execution_workdir", "/not/required/to/exist"),
    ],
)
@pytest.mark.parametrize(
    "invalid", ["", " value", "value ", "bad\nvalue", "bad\x00value", "x" * 201, 5]
)
def test_request_opaque_fields_are_bounded_and_never_trimmed(field, value, invalid):
    assert getattr(make_request(**{field: value}), field) == value
    with pytest.raises(ValidationError):
        make_request(**{field: invalid})


@pytest.mark.parametrize("invalid", ["", " value", "value ", "bad\rvalue", "x" * 201, 5])
def test_handle_and_event_opaque_fields(invalid):
    with pytest.raises(ValidationError):
        make_handle(provider_session_id=invalid)
    for field in ("engine_session_id", "trace_id"):
        with pytest.raises(ValidationError):
            make_event(**{field: invalid})


def test_request_raw_input_tenant_and_strict_scalar_rules():
    request = make_request(tenant_id=" tenant ", input="  keep\r\n\tthis  ")
    assert request.tenant_id == " tenant "
    assert request.input == "  keep\r\n\tthis  "
    assert make_request(input=" ").input == " "
    for field, values in {
        "tenant_id": ["", "x" * 201, 4],
        "input": ["", "x" * 200001, 4],
        "agent_id": [str(AGENT_ID), 4],
        "conversation_id": [str(CONVERSATION_ID), 4],
        "execution_id": [str(EXECUTION_ID), 4],
    }.items():
        for value in values:
            with pytest.raises(ValidationError):
                make_request(**{field: value})


@pytest.mark.parametrize("field", ["timeout_seconds", "process_id"])
@pytest.mark.parametrize("value", [0, -1, True, 1.0, "1"])
def test_positive_integer_fields_are_strict(field, value):
    factory = make_request if field == "timeout_seconds" else make_handle
    with pytest.raises(ValidationError):
        factory(**{field: value})
    assert getattr(factory(**{field: 1}), field) == 1


def test_uuid_and_datetime_are_strict_in_python_but_idiomatic_in_json():
    for factory in (make_handle, make_result, make_event):
        with pytest.raises(ValidationError):
            factory(execution_id=str(EXECUTION_ID))
    with pytest.raises(ValidationError):
        make_event(event_id=str(EVENT_ID))
    with pytest.raises(ValidationError):
        make_event(timestamp=TIMESTAMP.isoformat())

    request = ExecutionRequest.model_validate_json(json.dumps(request_data(), default=str))
    assert request.execution_id == EXECUTION_ID
    event = AgentEvent.model_validate_json(json.dumps(event_data(), default=str))
    assert event.event_id == EVENT_ID
    assert request.model_json_schema()["properties"]["execution_id"]["format"] == "uuid"
    assert event.model_json_schema()["properties"]["timestamp"]["format"] == "date-time"


@pytest.mark.parametrize("factory", [make_request, make_handle, make_result, make_event])
def test_nested_json_values_reject_non_json_and_non_finite_numbers(factory):
    field = {
        make_request: "config",
        make_handle: "metadata",
        make_result: "usage",
        make_event: "payload",
    }[factory]
    for value in [{"bad": object()}, {"bad": {1, 2}}, {"bad": b"bytes"}]:
        with pytest.raises(ValidationError):
            factory(**{field: value})
    for value in [float("inf"), float("-inf"), float("nan")]:
        with pytest.raises(ValidationError):
            factory(**{field: {"nested": [value]}})


@pytest.mark.parametrize("value", [1, 0, "true", None])
def test_effective_capabilities_require_strict_boolean_values(value):
    with pytest.raises(ValidationError):
        make_request(effective_capabilities={"streaming": value})


def test_default_collections_are_not_shared_and_nested_values_remain_mutable():
    first_request, second_request = make_request(), make_request()
    first_request.config["nested"] = {"items": []}
    first_request.config["nested"]["items"].append("changed")
    first_request.effective_capabilities["streaming"] = True
    assert second_request.config == {}
    assert second_request.effective_capabilities == {}

    first_handle, second_handle = make_handle(), make_handle()
    first_handle.metadata["nested"] = []
    first_handle.metadata["nested"].append("changed")
    assert second_handle.metadata == {}

    first_result, second_result = make_result(), make_result()
    first_result.artifacts.append({"nested": []})
    first_result.artifacts[0]["nested"].append("changed")
    first_result.usage["nested"] = {"tokens": 1}
    first_result.engine_metadata["nested"] = []
    assert second_result.artifacts == []
    assert second_result.usage == {}
    assert second_result.engine_metadata == {}

    first_event, second_event = make_event(), make_event()
    first_event.payload["nested"] = {"items": []}
    first_event.payload["nested"]["items"].append("changed")
    assert second_event.payload == {}

    first_error, second_error = make_error(), make_error()
    assert first_error.details == ExecutionErrorDetails()
    assert first_error.details is not second_error.details


@pytest.mark.parametrize("field", ["execution_id", "engine_id", "protocol_id", "adapter_version"])
def test_handle_request_identity_boundary_rejects_every_key_mismatch(field):
    request = make_request()
    value = {
        "execution_id": AGENT_ID,
        "engine_id": "other-engine",
        "protocol_id": "other-protocol",
        "adapter_version": "v2",
    }[field]
    handle = make_handle(**{field: value})
    ensure_handle_identity(request, make_handle())
    with pytest.raises(ConfigurationError) as caught:
        ensure_handle_identity(request, handle)
    assert caught.value.error.code == ExecutionErrorCode.INVALID_HANDLE
    assert handle == make_handle(**{field: value})


class IdentityAdapter:
    @property
    def engine_id(self) -> str:
        return "local-test"

    @property
    def protocol_id(self) -> str:
        return "scripted"

    @property
    def adapter_version(self) -> str:
        return "v1"


@pytest.mark.parametrize(
    "field,value",
    [("engine_id", "other"), ("protocol_id", "other"), ("adapter_version", "v2")],
)
def test_request_adapter_identity_boundary(field, value):
    ensure_request_identity(make_request(), IdentityAdapter())
    request = make_request(**{field: value})
    with pytest.raises(ConfigurationError) as caught:
        ensure_request_identity(request, IdentityAdapter())
    assert caught.value.error.code == ExecutionErrorCode.INVALID_REQUEST


@pytest.mark.parametrize("model_name", ["result", "event"])
@pytest.mark.parametrize("field", ["execution_id", "engine_id", "protocol_id", "adapter_version"])
def test_result_and_event_handle_identity_boundary(model_name, field):
    value = {
        "execution_id": AGENT_ID,
        "engine_id": "other-engine",
        "protocol_id": "other-protocol",
        "adapter_version": "v2",
    }[field]
    handle = make_handle(provider_session_id="session-1")
    if model_name == "result":
        ensure_result_identity(handle, make_result())
        with pytest.raises(ConfigurationError) as caught:
            ensure_result_identity(handle, make_result(**{field: value}))
        assert caught.value.error.code == ExecutionErrorCode.INVALID_RESULT
    else:
        ensure_event_identity(handle, make_event(engine_session_id="session-1"))
        event = make_event(engine_session_id="session-1", **{field: value})
        with pytest.raises(ConfigurationError) as caught:
            ensure_event_identity(handle, event)
        assert caught.value.error.code == ExecutionErrorCode.INVALID_EVENT


@pytest.mark.parametrize(
    "provider_session_id,event_session_id",
    [(None, "session-1"), ("session-1", None), ("session-1", "session-2")],
)
def test_event_session_identity_boundary_includes_none(provider_session_id, event_session_id):
    ensure_event_identity(make_handle(), make_event())
    handle = make_handle(provider_session_id=provider_session_id)
    event = make_event(engine_session_id=event_session_id)
    with pytest.raises(ConfigurationError) as caught:
        ensure_event_identity(handle, event)
    assert caught.value.error.code == ExecutionErrorCode.INVALID_EVENT
    assert make_event(engine_session_id=event_session_id).engine_session_id == event_session_id


def test_handle_only_fields_are_not_exposed_by_terminal_or_event_public_dtos():
    handle = make_handle(process_id=123, metadata={"internal": True})
    assert handle.model_dump()["process_id"] == 123
    for serialized in (make_result().model_dump(), make_event().model_dump()):
        assert "process_id" not in serialized
        assert "metadata" not in serialized
        assert "provider_session_id" not in serialized


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
@pytest.mark.parametrize("output", [None, "output"])
@pytest.mark.parametrize("error_kind", [None, "internal", "cancelled"])
def test_every_result_output_error_combination(status, output, error_kind):
    error = None
    if error_kind == "internal":
        error = make_error()
    elif error_kind == "cancelled":
        error = make_error(category="cancelled", code="execution_cancelled")
    valid = (
        (status == "completed" and error is None)
        or (status == "failed" and output is None and error_kind == "internal")
        or (status == "cancelled" and output is None and error is None)
    )
    data = result_data(status=status, output=output, error=error)
    if valid:
        result = ExecutionResult(**data)
        assert result.status == status
        assert result.output == output
        assert result.error == error
    else:
        with pytest.raises(ValidationError):
            ExecutionResult(**data)


@pytest.mark.parametrize("status", ["running", "unknown"])
def test_result_rejects_non_terminal_or_unknown_status(status):
    with pytest.raises(ValidationError):
        make_result(status=status)


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_terminal_metadata_and_artifact_only_results_are_valid(status):
    error = make_error() if status == "failed" else None
    result = make_result(
        status=status,
        error=error,
        artifacts=[{"uri": "artifact-1", "metadata": {"safe": True}}],
        usage={"tokens": 3},
        engine_metadata={"native": {"value": 1}},
    )
    assert result.output is None
    assert result.artifacts == [{"uri": "artifact-1", "metadata": {"safe": True}}]
    assert result.usage == {"tokens": 3}
    assert result.engine_metadata == {"native": {"value": 1}}


def test_error_category_and_complete_static_code_catalog():
    assert {item.value for item in ExecutionErrorCategory} == {
        "configuration_error",
        "engine_unavailable",
        "protocol_error",
        "authentication_error",
        "permission_denied",
        "resource_exhausted",
        "timeout",
        "cancelled",
        "workspace_error",
        "internal_error",
    }
    assert len(ERROR_CATALOG) == 30
    assert len({code for _, code in ERROR_CATALOG}) == 30
    assert {item.value for item in ExecutionErrorCode} == {code for _, code in ERROR_CATALOG}
    for (category, code), message in ERROR_CATALOG.items():
        error = make_error(category=category, code=code)
        assert error.category.value == category
        assert error.code.value == code
        assert error.message == message
        assert error.retryable is False
        assert error.model_dump()["message"] == message
        assert json.loads(error.model_dump_json())["message"] == message


def test_execution_error_mapping_round_trip_preserves_static_message():
    error = make_error(category="timeout", code="execution_timeout")
    expected = error.model_dump()
    restored = ExecutionError.model_validate(expected)
    assert restored.model_dump() == expected
    assert restored.message == "Execution timed out."


def test_execution_error_json_round_trip_preserves_static_message():
    error = make_error(category="timeout", code="execution_timeout")
    expected = error.model_dump()
    restored = ExecutionError.model_validate_json(error.model_dump_json())
    assert restored.model_dump() == expected
    assert restored.message == "Execution timed out."


def test_failed_result_mapping_round_trip_preserves_nested_static_error():
    failed = make_result(
        status="failed",
        error=make_error(category="timeout", code="execution_timeout"),
        usage={"tokens": 2},
    )
    expected = failed.model_dump()
    restored = ExecutionResult.model_validate(expected)
    assert restored.model_dump() == expected
    assert restored.error is not None
    assert restored.error.message == "Execution timed out."


def test_failed_result_json_round_trip_preserves_nested_static_error():
    failed = make_result(
        status="failed",
        error=make_error(category="timeout", code="execution_timeout"),
        usage={"tokens": 2},
    )
    expected = failed.model_dump()
    restored = ExecutionResult.model_validate_json(failed.model_dump_json())
    assert restored.model_dump() == expected
    assert restored.error is not None
    assert restored.error.message == "Execution timed out."


def test_exact_direct_message_is_noop_integrity_token():
    message = "Execution timed out."
    error = ExecutionError(
        category="timeout",
        code="execution_timeout",
        message=message,
    )
    assert error.message == message
    assert "message" not in error.__dict__
    assert error.model_dump()["message"] == message


@pytest.mark.parametrize("mode", ["direct", "mapping", "json"])
@pytest.mark.parametrize(
    "message_case",
    ["arbitrary", "mismatched", "non_string", "missing_code", "invalid_code"],
)
def test_error_rejects_invalid_message_integrity_tokens(mode, message_case):
    data = error_data()
    if message_case == "arbitrary":
        data["message"] = "secret-" + "marker"
    elif message_case == "mismatched":
        data["message"] = "Execution timed out."
    elif message_case == "non_string":
        data["message"] = 7
    elif message_case == "missing_code":
        data.pop("code")
        data["message"] = "Execution failed internally."
    else:
        data["code"] = "unknown"
        data["message"] = "Execution failed internally."

    if mode == "direct":
        with pytest.raises(ValidationError):
            ExecutionError(**data)
    elif mode == "mapping":
        with pytest.raises(ValidationError):
            ExecutionError.model_validate(data)
    else:
        with pytest.raises(ValidationError):
            ExecutionError.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("mode", ["mapping", "json"])
def test_failed_result_rejects_nested_arbitrary_message(mode):
    data = result_data(
        status="failed",
        error=error_data(message="secret-" + "marker"),
    )
    if mode == "mapping":
        with pytest.raises(ValidationError):
            ExecutionResult.model_validate(data)
    else:
        with pytest.raises(ValidationError):
            ExecutionResult.model_validate_json(json.dumps(data, default=str))


@pytest.mark.parametrize("category,code", list(ERROR_CATALOG))
def test_error_rejects_category_code_mismatch(category, code):
    wrong_category = next(item for item in ExecutionErrorCategory if item.value != category)
    with pytest.raises(ValidationError):
        make_error(category=wrong_category, code=code)


@pytest.mark.parametrize(
    "category,code",
    [
        (category, code)
        for category, code in ERROR_CATALOG
        if category in {"engine_unavailable", "resource_exhausted"}
    ],
)
def test_retryable_is_limited_to_explicit_retry_categories(category, code):
    error = make_error(category=category, code=code, retryable=True)
    assert error.retryable is True


def test_non_retryable_codes_reject_retryable_true():
    for category, code in ERROR_CATALOG:
        if category in {"engine_unavailable", "resource_exhausted"}:
            continue
        with pytest.raises(ValidationError):
            make_error(category=category, code=code, retryable=True)
    for value in [1, 0, "true", None]:
        with pytest.raises(ValidationError):
            make_error(retryable=value)


@pytest.mark.parametrize(
    "data",
    [
        {"category": "unknown", "code": "internal_error"},
        {"category": "internal_error", "code": "unknown"},
        {"category": "internal_error", "code": 1},
        {"category": 1, "code": "internal_error"},
    ],
)
def test_error_rejects_unknown_or_non_string_enum_values(data):
    with pytest.raises(ValidationError):
        ExecutionError(**data)


@pytest.mark.parametrize(
    "field",
    ["reason", "exception", "config", "input", "provider_response", "message", "stack", "extra"],
)
def test_error_details_reject_arbitrary_diagnostics(field):
    with pytest.raises(ValidationError):
        make_error(details={field: "secret-marker"})


def test_error_details_allow_only_bounded_identity_and_slugs():
    details = ExecutionErrorDetails(
        engine_id="local-test",
        protocol_id="scripted",
        adapter_version="v2",
        field="request.input",
        operation="start_execution",
    )
    assert details.field == "request.input"
    assert details.operation == "start_execution"
    for field, values in {
        "engine_id": ["Bad", " bad", "a" * 65, 1],
        "protocol_id": ["Bad", "bad ", "a" * 65, 1],
        "adapter_version": ["latest", "v0", "v01", " v1", 1],
        "field": ["", "Bad", " bad", "bad ", "bad..slug", "a" * 201, 1],
        "operation": ["", "Bad", " bad", "bad ", "bad..slug", "a" * 201, 1],
    }.items():
        for value in values:
            with pytest.raises(ValidationError):
                ExecutionErrorDetails(**{field: value})


def test_adapter_exceptions_and_normalization_never_expose_raw_exception_text():
    marker = "secret-marker"
    original = make_error(category="workspace_error", code="workspace_error")
    existing = AdapterExecutionError(original)
    assert normalize_adapter_exception(existing) is existing
    assert existing.error is original
    assert str(existing) == "Engine workspace operation failed."

    timeout = normalize_adapter_exception(TimeoutError(marker))
    assert timeout.error.category == ExecutionErrorCategory.TIMEOUT
    assert timeout.error.code == ExecutionErrorCode.EXECUTION_TIMEOUT
    assert timeout.error.message == "Execution timed out."

    unknown = normalize_adapter_exception(RuntimeError(f"{marker}\nstack trace"))
    assert unknown.error.category == ExecutionErrorCategory.INTERNAL_ERROR
    assert unknown.error.code == ExecutionErrorCode.INTERNAL_ERROR
    assert unknown.error.message == "Execution failed internally."
    for exception in (existing, timeout, unknown, ConfigurationError(original)):
        serialized = exception.error.model_dump_json()
        dumped = str(exception.error.model_dump())
        assert marker not in str(exception)
        assert marker not in repr(exception)
        assert marker not in serialized
        assert marker not in dumped
        assert "Traceback" not in serialized
        assert "stack trace" not in serialized
        assert "RuntimeError" not in serialized


@pytest.mark.parametrize("mode", ["unknown", "existing", "direct"])
def test_safe_exceptions_suppress_implicit_context_in_formatted_tracebacks(mode):
    marker = "secret-" + "marker"
    original_text = "original-stack-" + marker
    safe_error = make_error(category="workspace_error", code="workspace_error")
    existing = AdapterExecutionError(safe_error)
    try:
        try:
            raise RuntimeError(original_text)
        except Exception as exc:  # noqa: BLE001 - exercise the generic adapter boundary.
            if mode == "unknown":
                raise normalize_adapter_exception(exc)
            if mode == "existing":
                raise normalize_adapter_exception(existing)
            raise ConfigurationError(safe_error)
    except AdapterExecutionError as caught_exception:
        safe_exception = caught_exception
        rendered = "".join(traceback.format_exception(safe_exception))

    expected_message = (
        "Execution failed internally."
        if mode == "unknown"
        else "Engine workspace operation failed."
    )
    assert expected_message in rendered
    assert marker not in rendered
    assert "original-stack-" not in rendered
    assert "RuntimeError" not in rendered
    assert safe_exception.__suppress_context__ is True


@pytest.mark.parametrize(
    "exception",
    [asyncio.CancelledError(), KeyboardInterrupt(), SystemExit(), GeneratorExit()],
    ids=["cancelled", "keyboard_interrupt", "system_exit", "generator_exit"],
)
def test_control_flow_exceptions_propagate_unchanged(exception):
    with pytest.raises(type(exception)) as caught:
        normalize_adapter_exception(exception)
    assert caught.value is exception


def test_capabilities_have_exact_strict_defaults_and_no_implications():
    capabilities = EngineCapabilities()
    capability_fields = EXPECTED_FIELDS[EngineCapabilities] - {"contract_version"}
    assert len(capability_fields) == 11
    assert all(getattr(capabilities, field) is False for field in capability_fields)
    for field in capability_fields:
        for value in [1, 0, "true", None]:
            with pytest.raises(ValidationError):
                EngineCapabilities(**{field: value})


@pytest.mark.parametrize(
    "field",
    sorted(EXPECTED_FIELDS[EngineCapabilities] - {"contract_version"}),
)
def test_each_capability_true_declaration_is_independent(field):
    declared = EngineCapabilities(**{field: True})
    capability_fields = EXPECTED_FIELDS[EngineCapabilities] - {"contract_version"}
    assert getattr(declared, field) is True
    assert all(getattr(declared, other) is False for other in capability_fields - {field})


@pytest.mark.parametrize(
    "event_type",
    ["output", "engine.output_delta", "engine-native.event_type", "a1.b2-c3_d4"],
)
def test_event_type_valid_grammar(event_type):
    assert make_event(event_type=event_type).event_type == event_type


@pytest.mark.parametrize(
    "event_type",
    ["", "Engine.output", ".bad", "bad.", "bad..type", "bad type", "bad/type", "a" * 101, 1],
)
def test_event_type_invalid_grammar(event_type):
    with pytest.raises(ValidationError):
        make_event(event_type=event_type)


@pytest.mark.parametrize("sequence", [0, -1, True, 1.0, "1", None])
def test_event_sequence_is_required_strict_and_positive(sequence):
    with pytest.raises(ValidationError):
        make_event(sequence=sequence)


@pytest.mark.parametrize("source", ["platform", "engine_native"])
def test_event_source_and_version(source):
    event = make_event(source=source, schema_version="v1")
    assert event.source == source
    assert event.schema_version == "v1"
    for invalid in ["engine", "Platform", None, 1]:
        with pytest.raises(ValidationError):
            make_event(source=invalid)


@pytest.mark.parametrize(
    "timestamp",
    [
        None,
        "2026-01-02T03:04:05Z",
        datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC).replace(tzinfo=None),
        1,
    ],
)
def test_event_requires_aware_datetime(timestamp):
    with pytest.raises(ValidationError):
        make_event(timestamp=timestamp)


def test_event_timestamp_is_normalized_to_utc_without_supplying_defaults():
    offset = timezone(timedelta(hours=8))
    event = make_event(timestamp=datetime(2026, 1, 2, 11, 4, 5, tzinfo=offset))
    assert event.timestamp == TIMESTAMP
    assert event.timestamp.tzinfo is UTC
    assert AgentEvent.model_fields["event_id"].is_required()
    assert AgentEvent.model_fields["timestamp"].is_required()
    assert AgentEvent.model_fields["event_id"].default_factory is None
    assert AgentEvent.model_fields["timestamp"].default_factory is None


def test_adapter_protocol_has_required_properties_and_async_signatures():
    for name in ("engine_id", "protocol_id", "adapter_version"):
        protocol_property = inspect.getattr_static(AgentEngineAdapter, name)
        assert isinstance(protocol_property, property)
        assert get_type_hints(protocol_property.fget)["return"] is str

    for name in ("get_capabilities", "start", "cancel", "collect_result"):
        assert inspect.iscoroutinefunction(getattr(AgentEngineAdapter, name))
    assert not inspect.iscoroutinefunction(AgentEngineAdapter.stream_events)
    hints = get_type_hints(AgentEngineAdapter.stream_events)
    assert hints["handle"] is ExecutionHandle
    assert hints["return"] == AsyncIterator[AgentEvent]
    assert get_type_hints(AgentEngineAdapter.start)["request"] is ExecutionRequest
    assert get_type_hints(AgentEngineAdapter.start)["return"] is ExecutionHandle
    assert get_type_hints(AgentEngineAdapter.collect_result)["return"] is ExecutionResult
    assert get_type_hints(AgentEngineAdapter.get_capabilities)["return"] is EngineCapabilities


def test_current_contract_and_package_dependencies_stay_one_directional():
    package_root = (
        Path(__file__).parents[1] / "src" / "agent_platform" / "core_platform" / "agent_execution"
    )
    expected_modules = {
        "__init__.py",
        "contracts/__init__.py",
        "contracts/base.py",
        "contracts/common.py",
        "contracts/request.py",
        "contracts/handle.py",
        "contracts/result.py",
        "contracts/events.py",
        "contracts/capabilities.py",
        "contracts/config.py",
        "contracts/errors.py",
        "contracts/adapter.py",
        "contracts/snapshots.py",
        "contracts/instructions.py",
    }
    actual_t2_modules = {
        str(path.relative_to(package_root))
        for path in (
            *package_root.glob("*.py"),
            *(package_root / "contracts").rglob("*.py"),
        )
    }
    assert actual_t2_modules == expected_modules

    forbidden_parts = (
        ".registry",
        ".adapters",
        ".orchestration",
        ".instructions",
        ".worker",
        ".repository",
        ".factory",
        "business_capabilities",
        "applications",
        "agent_runtime",
        "langgraph",
        "langchain",
        "openai",
    )
    implementation_packages = {
        "registry",
        "adapters",
        "orchestration",
        "capability",
        "instructions",
    }
    execution_marker = "agent_platform.core_platform.agent_execution."

    def escapes_into_implementation(name: str, level: int, own_escape_level: int) -> bool:
        """Whether one import leaves its own package for an implementation package.

        ``.split(".")[0]`` on the path after ``agent_execution.`` is deliberate:
        the contracts layer owns ``contracts.capabilities`` while
        ``agent_execution.capability`` is a separate implementation package, and a
        substring check would conflate the two.
        """
        if level:
            return level >= own_escape_level and name.split(".")[0] in implementation_packages
        return name.startswith(execution_marker) and (
            name.removeprefix(execution_marker).split(".")[0] in implementation_packages
        )

    for relative_path in sorted(expected_modules):
        source_file = package_root / relative_path
        assert source_file.is_file()
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        imports: list[tuple[str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend((alias.name, 0) for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append((node.module, node.level))
        names = [name for name, _ in imports]
        assert not any(part in name for name in names for part in forbidden_parts), (
            relative_path,
            imports,
        )
        # The contracts layer is a leaf: nothing in it may reach an execution
        # implementation package, whether the import is absolute or relative.
        escape_level = 1 if relative_path == "__init__.py" else 2
        assert not [
            (name, level)
            for name, level in imports
            if escapes_into_implementation(name, level, escape_level)
        ], (relative_path, imports)
        extension_imports = [
            name for name in names if name.startswith("agent_platform.extension_contracts")
        ]
        assert all(name == "agent_platform.extension_contracts.base" for name in extension_imports)

    assert not hasattr(execution_package, "LocalTestAdapter")
    assert not hasattr(execution_package, "EngineRegistry")
