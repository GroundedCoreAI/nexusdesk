import ast
import asyncio
import json
import math
import os
import time
from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import httpx
import pytest

from agent_platform.applications.platform_runtime import runtime_composition
from agent_platform.applications.platform_runtime.react_adapter_factory import (
    ReactAdapterFactory,
)
from agent_platform.applications.platform_runtime.runtime_composition import (
    _build_execution_orchestrator,
    _runtime_fingerprint,
)
from agent_platform.applications.platform_runtime.runtime_factory import RuntimeFactory
from agent_platform.core_platform.agent_execution.adapters.testing.local_test_adapter import (
    LocalTestAdapter,
    LocalTestEventSpec,
    LocalTestScenario,
)
from agent_platform.core_platform.agent_execution.contracts import (
    AdapterExecutionError,
    AgentEvent,
    ConfigurationError,
    EngineCapabilities,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionHandle,
    ExecutionResult,
)
from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
    ExecutionContext,
    build_execution_context,
    build_execution_request,
    capture_execution_context,
    resolve_with_execution_context,
)
from agent_platform.core_platform.agent_execution.orchestration.execution_lifecycle import (
    AcknowledgingEventStream,
    ExecutionOutcome,
    OutcomeCollectingAdapter,
    as_acknowledging_event_stream,
    as_outcome_collecting_adapter,
)
from agent_platform.core_platform.agent_execution.orchestration.orchestrator import (
    ExecutionOrchestrator,
)
from agent_platform.core_platform.agent_execution.registry import (
    AdapterDescriptor,
    AdapterRegistry,
    EngineDescriptor,
    EngineRegistry,
    ProtocolDescriptor,
    ProtocolRegistry,
)
from agent_platform.core_platform.agent_runtime.engine import RuntimeEngine
from agent_platform.core_platform.agent_runtime.schemas import RuntimeFault
from agent_platform.core_platform.agent_runtime.worker import RuntimeWorker
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.core_platform.tool_gateway.service import ToolGateway
from agent_platform.extension_contracts import RuntimeBindings

ASYNC_WATCHDOG_SECONDS = 5
RUN_ID = UUID("10000000-0000-4000-8000-000000000001")
AGENT_ID = UUID("20000000-0000-4000-8000-000000000002")
CONVERSATION_ID = UUID("30000000-0000-4000-8000-000000000003")
OTHER_RUN_ID = UUID("40000000-0000-4000-8000-000000000004")
RESULT_KEY = {
    "execution_id": RUN_ID,
    "engine_id": "react",
    "protocol_id": "native",
    "adapter_version": "v1",
}


def make_row(*, run_id: UUID = RUN_ID, agent: object = None) -> dict[str, object]:
    config = {} if agent is None else {"agent": agent}
    return {
        "id": run_id,
        "tenant_id": "tenant-a",
        "conversation_id": CONVERSATION_ID,
        "input": "current question",
        "config": config,
    }


def make_context(*, run_id: UUID = RUN_ID, agent: object = None) -> ExecutionContext:
    return build_execution_context(
        make_row(run_id=run_id, agent=agent),
        history=[{"role": "user", "content": "earlier question"}],
        summary_message="rendered summary",
        customer_memory="rendered customer memory",
        trace_id="trace-a",
        timeout_seconds=30,
    )


class ExplodingMapping(Mapping[str, object]):
    def __init__(self, values: dict[str, object], failure_key: str, failure: BaseException):
        self._values = values
        self._failure_key = failure_key
        self._failure = failure

    def __getitem__(self, key: str) -> object:
        if key == self._failure_key:
            raise self._failure
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def assert_invalid_request(caught: pytest.ExceptionInfo[ConfigurationError]) -> None:
    assert caught.value.error.code is ExecutionErrorCode.INVALID_REQUEST


def test_snapshot_request_uses_claimed_row_and_real_agent_uuid_without_stringifying():
    context = make_context(agent={"id": str(AGENT_ID)})

    request = build_execution_request(context)

    assert type(request.execution_id) is UUID
    assert request.execution_id is RUN_ID
    assert type(request.agent_id) is UUID
    assert request.agent_id == AGENT_ID
    assert request.agent_id not in {RUN_ID, CONVERSATION_ID}
    assert (request.engine_id, request.protocol_id, request.adapter_version) == (
        "react",
        "native",
        "v1",
    )
    assert request.tenant_id == "tenant-a"
    assert request.conversation_id is CONVERSATION_ID
    assert request.input == "current question"
    assert request.trace_id == "trace-a"
    assert request.timeout_seconds == 30
    assert request.config == {}
    assert request.effective_capabilities == {}
    assert not hasattr(request, "engine_metadata")


@pytest.mark.parametrize("agent_id", [AGENT_ID, str(AGENT_ID)])
def test_snapshot_agent_uuid_accepts_only_real_uuid_values(agent_id: object):
    request = build_execution_request(make_context(agent={"id": agent_id}))
    assert request.agent_id == AGENT_ID
    assert type(request.agent_id) is UUID


@pytest.mark.parametrize(
    "agent",
    [
        {},
        [],
        "snapshot",
        {"id": None},
        {"id": ""},
        {"id": "not-a-uuid"},
        {"id": 123},
        {"id": str(UUID(int=0))},
        {"id": UUID(int=0)},
    ],
)
def test_missing_malformed_or_nil_snapshot_agent_identity_fails_closed(agent: object):
    with pytest.raises(ConfigurationError) as caught:
        build_execution_request(make_context(agent=agent))
    assert_invalid_request(caught)
    assert str(caught.value) == caught.value.error.message


@pytest.mark.parametrize("config", [None, [], "bad", {"agent": {"config": {}}}])
def test_malformed_run_config_or_snapshot_never_falls_back_to_legacy(config: object):
    context = make_context()
    context.row["config"] = config
    with pytest.raises(ConfigurationError) as caught:
        build_execution_request(context)
    assert_invalid_request(caught)


@pytest.mark.parametrize("failure_key", ["tenant_id", "conversation_id", "input"])
def test_request_mapping_access_failures_are_safe_invalid_requests(failure_key: str):
    diagnostic = "claimed-row-" + "private-diagnostic"
    row = ExplodingMapping(make_row(agent={"id": AGENT_ID}), failure_key, RuntimeError(diagnostic))
    context = build_execution_context(row, history=[])

    with pytest.raises(ConfigurationError) as caught:
        build_execution_request(context)
    assert_invalid_request(caught)
    assert diagnostic not in str(caught.value)


def test_request_snapshot_config_access_failure_is_safe_invalid_request():
    diagnostic = "snapshot-config-" + "private-diagnostic"
    row = make_row()
    row["config"] = ExplodingMapping({"agent": {"id": AGENT_ID}}, "agent", RuntimeError(diagnostic))
    context = build_execution_context(row, history=[])

    with pytest.raises(ConfigurationError) as caught:
        build_execution_request(context)
    assert_invalid_request(caught)
    assert diagnostic not in str(caught.value)


@pytest.mark.parametrize("control_flow", [asyncio.CancelledError(), KeyboardInterrupt()])
def test_request_mapping_control_flow_is_not_swallowed(control_flow: BaseException):
    row = ExplodingMapping(make_row(agent={"id": AGENT_ID}), "tenant_id", control_flow)
    context = build_execution_context(row, history=[])

    with pytest.raises(type(control_flow)):
        build_execution_request(context)


def test_only_react_no_snapshot_legacy_request_uses_internal_anonymous_sentinel():
    request = build_execution_request(make_context())

    assert request.agent_id == UUID(int=0)
    assert request.agent_id not in {RUN_ID, CONVERSATION_ID}
    assert request.execution_id == RUN_ID
    assert request.config == {}
    assert request.effective_capabilities == {}
    assert not hasattr(request, "engine_metadata")


@pytest.mark.parametrize("run_id", [str(RUN_ID), None, 1])
def test_claimed_execution_id_must_be_a_uuid(run_id: object):
    with pytest.raises(ConfigurationError) as caught:
        build_execution_context(make_row(run_id=run_id), history=[])
    assert_invalid_request(caught)


def test_uuid_subclass_is_normalized_without_rewriting_claimed_row_identity():
    class DerivedUUID(UUID):
        pass

    row_id = DerivedUUID(str(RUN_ID))
    supplied_id = DerivedUUID(str(RUN_ID))
    row = make_row(run_id=row_id)

    context = ExecutionContext(row=row, execution_id=supplied_id, history=[])
    request = build_execution_request(context)

    assert type(context.execution_id) is UUID
    assert context.execution_id == row_id
    assert context.execution_id is not supplied_id
    assert context.row is row
    assert context.row["id"] is row_id
    assert type(context.row["id"]) is DerivedUUID
    assert type(request.execution_id) is UUID
    assert request.execution_id == row_id


def test_execution_context_rejects_mismatched_uuid_values():
    with pytest.raises(ConfigurationError) as caught:
        ExecutionContext(row=make_row(), execution_id=OTHER_RUN_ID, history=[])
    assert_invalid_request(caught)


def test_non_uuid_fake_with_uuid_string_is_rejected():
    class FakeUUID:
        def __str__(self) -> str:
            return str(RUN_ID)

    with pytest.raises(ConfigurationError) as caught:
        build_execution_context(make_row(run_id=FakeUUID()), history=[])
    assert_invalid_request(caught)


def test_malicious_uuid_subclass_string_failure_is_safe_and_redacted():
    diagnostic = "uuid-subclass-" + "private-diagnostic"

    class ExplodingUUID(UUID):
        def __str__(self) -> str:
            raise RuntimeError(diagnostic)

    with pytest.raises(ConfigurationError) as caught:
        build_execution_context(make_row(run_id=ExplodingUUID(str(RUN_ID))), history=[])
    assert_invalid_request(caught)
    assert str(caught.value) == caught.value.error.message
    assert diagnostic not in str(caught.value)


def test_uuid_type_descriptor_failure_is_safe_and_redacted():
    diagnostic = "uuid-descriptor-" + "private-diagnostic"

    class ExplodingDescriptor:
        @property
        def __class__(self) -> type:
            raise RuntimeError(diagnostic)

    with pytest.raises(ConfigurationError) as caught:
        build_execution_context(make_row(run_id=ExplodingDescriptor()), history=[])
    assert_invalid_request(caught)
    assert str(caught.value) == caught.value.error.message
    assert diagnostic not in str(caught.value)


@pytest.mark.parametrize("control_flow", [asyncio.CancelledError(), KeyboardInterrupt()])
def test_uuid_subclass_string_control_flow_is_rethrown(control_flow: BaseException):
    class ControlFlowUUID(UUID):
        def __str__(self) -> str:
            raise control_flow

    value = ControlFlowUUID(str(RUN_ID))
    with pytest.raises(type(control_flow)) as caught:
        build_execution_context(make_row(run_id=value), history=[])
    assert caught.value is control_flow


def test_private_context_has_no_emit_or_public_serialization_surface():
    context = make_context(agent={"id": AGENT_ID})

    assert context.execution_id is RUN_ID
    assert context.row["id"] is RUN_ID
    assert context.summary_message == "rendered summary"
    assert context.customer_memory == "rendered customer memory"
    assert not hasattr(context, "worker_emit")
    assert not hasattr(context, "runtime_emit")
    assert not any("emit" in field for field in vars(type(context)))
    for name in ("model_dump", "model_dump_json", "dict", "json"):
        assert not hasattr(context, name)
    with pytest.raises(FrozenInstanceError):
        context.execution_id = OTHER_RUN_ID


def test_direct_context_preserves_claimed_row_and_detaches_nested_history():
    agent = {"id": AGENT_ID}
    row = make_row()
    row["config"] = {"agent": agent}
    nested_content = {"parts": ["original"]}
    history = [{"role": "user", "content": nested_content}]

    context = ExecutionContext(row=row, execution_id=RUN_ID, history=history)

    assert context.row is row
    row["input"] = "mutated input"
    agent["id"] = OTHER_RUN_ID
    nested_content["parts"].append("mutated")
    history.append("invalid later item")

    assert context.row["input"] == "mutated input"
    assert context.row["config"] == {"agent": {"id": OTHER_RUN_ID}}
    assert context.history == [{"role": "user", "content": {"parts": ["original"]}}]


def test_runtime_memory_reinforce_is_immediately_visible_on_original_worker_row():
    row = make_row()
    context = build_execution_context(row, history=[])
    memory_hits = [{"chunk_id": "chunk-1"}]

    context.row["_memory_reinforce"] = memory_hits

    assert row["_memory_reinforce"] is memory_hits


def test_scope_captures_context_into_new_object_without_later_contextvar_reads():
    context = make_context()

    class CapturedFactory:
        def __init__(self, captured: ExecutionContext) -> None:
            self.context = captured

    captured = resolve_with_execution_context(
        context, lambda: CapturedFactory(capture_execution_context())
    )

    assert captured.context is context
    with pytest.raises(ConfigurationError):
        capture_execution_context()
    assert captured.context.row["input"] == "current question"


def test_nested_scope_restores_outer_context_and_finally_clears_it():
    outer = make_context()
    inner = make_context(run_id=OTHER_RUN_ID)

    def nested_resolution() -> tuple[ExecutionContext, ExecutionContext, ExecutionContext]:
        before = capture_execution_context()
        during = resolve_with_execution_context(inner, capture_execution_context)
        after = capture_execution_context()
        return before, during, after

    before, during, after = resolve_with_execution_context(outer, nested_resolution)
    assert before is outer
    assert during is inner
    assert after is outer
    with pytest.raises(ConfigurationError):
        capture_execution_context()


def test_scope_resets_after_resolve_failure_without_leaking_raw_context():
    context = make_context()

    def fail_resolution() -> None:
        assert capture_execution_context() is context
        raise RuntimeError("factory diagnostic")

    with pytest.raises(RuntimeError, match="factory diagnostic"):
        resolve_with_execution_context(context, fail_resolution)
    with pytest.raises(ConfigurationError) as caught:
        capture_execution_context()
    assert caught.value.error.code is ExecutionErrorCode.ADAPTER_FACTORY_FAILED
    assert "current question" not in str(caught.value)


def test_missing_or_wrong_context_fails_safely():
    with pytest.raises(ConfigurationError) as missing:
        capture_execution_context()
    assert missing.value.error.code is ExecutionErrorCode.ADAPTER_FACTORY_FAILED

    with pytest.raises(ConfigurationError) as wrong:
        resolve_with_execution_context("not-a-context", capture_execution_context)
    assert wrong.value.error.code is ExecutionErrorCode.ADAPTER_FACTORY_FAILED
    with pytest.raises(ConfigurationError):
        capture_execution_context()


@pytest.mark.asyncio
async def test_context_scope_is_isolated_between_concurrent_tasks():
    first = make_context()
    second = make_context(run_id=OTHER_RUN_ID)
    both_entered = asyncio.Event()
    entered = 0
    lock = asyncio.Lock()

    async def worker(expected: ExecutionContext) -> UUID:
        nonlocal entered
        async with lock:
            entered += 1
            if entered == 2:
                both_entered.set()

        def synchronous_resolve() -> ExecutionContext:
            return capture_execution_context()

        captured = resolve_with_execution_context(expected, synchronous_resolve)
        assert captured is expected
        await both_entered.wait()
        captured_after_gate = resolve_with_execution_context(expected, synchronous_resolve)
        assert captured_after_gate is expected
        return captured.execution_id

    assert await asyncio.gather(worker(first), worker(second)) == [RUN_ID, OTHER_RUN_ID]
    with pytest.raises(ConfigurationError):
        capture_execution_context()


def make_result(status: str, **overrides: object) -> ExecutionResult:
    values: dict[str, object] = {**RESULT_KEY, "status": status}
    if status == "failed":
        values["error"] = ExecutionError(
            category=ExecutionErrorCategory.INTERNAL_ERROR,
            code=ExecutionErrorCode.INTERNAL_ERROR,
        )
    values.update(overrides)
    return ExecutionResult(**values)


def test_completed_outcome_carries_memory_values_and_react_v1_empty_usage():
    history = [{"role": "assistant", "content": "answer"}]
    dropped = [{"role": "user", "content": "old"}]
    result = make_result("completed", output="", usage={})

    outcome = ExecutionOutcome.from_result(result, history=history, dropped=dropped)

    assert outcome.status == "completed"
    assert outcome.output == ""
    assert outcome.history == history
    assert outcome.dropped == dropped
    assert outcome.legacy_error_code is None
    assert outcome.usage == {}
    assert result.usage == {}
    assert result.engine_metadata == {}
    assert "history" not in result.model_dump()
    assert "dropped" not in result.model_dump()


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_non_completed_outcomes_never_carry_memory_values(status: str):
    result = make_result(status)
    outcome = ExecutionOutcome.from_result(
        result,
        legacy_error_code="model_timeout" if status == "failed" else None,
    )
    assert outcome.output is None
    assert outcome.history is None
    assert outcome.dropped is None
    assert outcome.usage == {}
    assert outcome.legacy_error_code == ("model_timeout" if status == "failed" else None)


def test_explicit_cancelled_result_and_outcome_have_no_error_or_output():
    result = make_result("cancelled")
    outcome = ExecutionOutcome.from_result(result)
    assert result.error is None
    assert result.output is None
    assert outcome.status == "cancelled"
    assert outcome.legacy_error_code is None


@pytest.mark.parametrize(
    "values",
    [
        {"status": "completed", "history": None, "dropped": []},
        {"status": "completed", "history": [], "dropped": None},
        {"status": "completed", "history": [], "dropped": [], "legacy_error_code": "x"},
        {"status": "failed", "legacy_error_code": None},
        {"status": "failed", "legacy_error_code": "x", "history": []},
        {"status": "failed", "legacy_error_code": "x", "dropped": []},
        {"status": "cancelled", "output": "late"},
        {"status": "cancelled", "legacy_error_code": "x"},
        {"status": "completed", "history": [], "dropped": [], "usage": None},
    ],
)
def test_outcome_rejects_invalid_terminal_combinations(values: dict[str, object]):
    with pytest.raises((TypeError, ValueError)):
        ExecutionOutcome(**values)


def test_direct_outcome_detaches_nested_memory_and_usage_from_caller_mutation():
    nested_history = {"values": ["original"]}
    nested_dropped = {"values": ["dropped"]}
    nested_usage = {"counts": [1]}
    history = [{"nested": nested_history}]
    dropped = [{"nested": nested_dropped}]
    usage = {"nested": nested_usage}

    outcome = ExecutionOutcome(status="completed", history=history, dropped=dropped, usage=usage)

    nested_history["values"].append("mutated")
    nested_dropped["values"].append("mutated")
    nested_usage["counts"].append(2)
    history.append("invalid later item")
    dropped.append(None)
    usage["later"] = {"not": "visible"}

    assert outcome.history == [{"nested": {"values": ["original"]}}]
    assert outcome.dropped == [{"nested": {"values": ["dropped"]}}]
    assert outcome.usage == {"nested": {"counts": [1]}}


def test_from_result_detaches_nested_usage_from_later_result_mutation():
    result = make_result("completed", usage={"nested": {"counts": [1]}})
    outcome = ExecutionOutcome.from_result(result)

    result.usage["nested"]["counts"].append(2)
    result.usage["later"] = True

    assert outcome.usage == {"nested": {"counts": [1]}}


def test_private_outcome_has_no_public_serialization_surface():
    outcome = ExecutionOutcome.from_result(make_result("completed"))
    assert outcome.history == []
    assert outcome.dropped == []
    assert outcome.usage == {}
    for name in ("model_dump", "model_dump_json", "dict", "json"):
        assert not hasattr(outcome, name)


class PlainEventStream:
    def __aiter__(self) -> "PlainEventStream":
        return self

    async def __anext__(self) -> AgentEvent:
        raise StopAsyncIteration


class AckEventStream(PlainEventStream):
    async def acknowledge(self, event: AgentEvent) -> None:
        return None

    async def abort(self, error: BaseException) -> None:
        return None

    async def aclose(self) -> None:
        return None


def test_acknowledging_event_stream_is_runtime_checkable_and_detected_structurally():
    acknowledging = AckEventStream()
    plain = PlainEventStream()

    assert isinstance(acknowledging, AcknowledgingEventStream)
    assert not isinstance(plain, AcknowledgingEventStream)
    assert as_acknowledging_event_stream(acknowledging) is acknowledging
    assert as_acknowledging_event_stream(plain) is None


class SynchronousAckEventStream(PlainEventStream):
    def acknowledge(self, event: AgentEvent) -> None:
        return None

    def abort(self, error: BaseException) -> None:
        return None

    def aclose(self) -> None:
        return None


class PartiallySynchronousAckEventStream(AckEventStream):
    def aclose(self) -> None:
        return None


class SynchronousNextEventStream(AckEventStream):
    def __anext__(self) -> None:
        return None


class AsyncCallable:
    def __init__(self, error: BaseException | None = None):
        self._error = error

    async def __call__(self, *args: object) -> None:
        if self._error is not None:
            raise self._error


class SynchronousCallable:
    def __call__(self, *args: object) -> None:
        return None


class CallableObjectEventStream:
    __anext__ = AsyncCallable(StopAsyncIteration())
    acknowledge = AsyncCallable()
    abort = AsyncCallable()
    aclose = AsyncCallable()

    def __aiter__(self) -> "CallableObjectEventStream":
        return self


class SynchronousCallableObjectEventStream(CallableObjectEventStream):
    aclose = SynchronousCallable()


class AsyncCallableObjectAiterEventStream(CallableObjectEventStream):
    __aiter__ = AsyncCallable()


@pytest.mark.asyncio
async def test_async_callable_object_capabilities_are_accepted_and_awaitable():
    stream = CallableObjectEventStream()

    assert as_acknowledging_event_stream(stream) is stream
    with pytest.raises(StopAsyncIteration):
        await stream.__anext__()
    await stream.acknowledge(None)
    await stream.abort(RuntimeError("abort"))
    await stream.aclose()


@pytest.mark.parametrize(
    "stream",
    [
        SynchronousAckEventStream(),
        PartiallySynchronousAckEventStream(),
        SynchronousNextEventStream(),
        SynchronousCallableObjectEventStream(),
        AsyncCallableObjectAiterEventStream(),
    ],
)
def test_non_async_acknowledgement_capabilities_are_rejected(stream: object):
    assert isinstance(stream, AcknowledgingEventStream)
    assert as_acknowledging_event_stream(stream) is None


def test_t2_core_modules_do_not_import_applications_business_or_react_adapter():
    source_root = (
        Path(__file__).parents[1] / "src" / "agent_platform" / "core_platform" / "agent_execution"
    )
    paths = [
        source_root / "orchestration" / "__init__.py",
        source_root / "orchestration" / "execution_context.py",
        source_root / "orchestration" / "execution_lifecycle.py",
        source_root / "adapters" / "react" / "error_mapper.py",
    ]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = [
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        ] + [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        assert not any(
            "agent_platform.applications" in name or "agent_platform.business_capabilities" in name
            for name in imports
        ), path


def test_public_result_schema_has_no_t2_private_or_engine_metadata_extensions():
    assert set(ExecutionResult.model_fields) == {
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
    }
    serialized = make_result("completed").model_dump()
    assert serialized["usage"] == {}
    assert serialized["engine_metadata"] == {}
    assert not {"history", "dropped", "legacy_error_code", "context", "outcome"} & set(serialized)


class OutcomeCapability:
    async def collect_outcome(self, handle: ExecutionHandle) -> ExecutionOutcome:
        return ExecutionOutcome(status="cancelled")


class SynchronousOutcomeCapability:
    def collect_outcome(self, handle: ExecutionHandle) -> ExecutionOutcome:
        return ExecutionOutcome(status="cancelled")


class AsyncOutcomeCallable:
    async def __call__(self, handle: ExecutionHandle) -> ExecutionOutcome:
        return ExecutionOutcome(status="cancelled")


class CallableObjectOutcomeCapability:
    collect_outcome = AsyncOutcomeCallable()


class ExplodingOutcomeDescriptor:
    @property
    def collect_outcome(self) -> object:
        raise RuntimeError("private descriptor diagnostic")


def test_outcome_collecting_adapter_is_private_runtime_checkable_and_async_verified():
    capable = OutcomeCapability()
    callable_capable = CallableObjectOutcomeCapability()

    assert isinstance(capable, OutcomeCollectingAdapter)
    assert as_outcome_collecting_adapter(capable) is capable
    assert as_outcome_collecting_adapter(callable_capable) is callable_capable
    assert as_outcome_collecting_adapter(SynchronousOutcomeCapability()) is None
    assert as_outcome_collecting_adapter(ExplodingOutcomeDescriptor()) is None
    assert as_outcome_collecting_adapter(object()) is None
    assert not hasattr(OutcomeCollectingAdapter, "model_dump")


class _StubEventStream:
    def __init__(
        self,
        events: list[AgentEvent],
        order: list[str],
        *,
        stream_error: BaseException | None = None,
        acknowledge_error: BaseException | None = None,
        abort_error: BaseException | None = None,
        aclose_error: BaseException | None = None,
    ) -> None:
        self._events = events
        self._order = order
        self._stream_error = stream_error
        self._acknowledge_error = acknowledge_error
        self._abort_error = abort_error
        self._aclose_error = aclose_error
        self._index = 0
        self.acknowledged: list[AgentEvent] = []
        self.abort_errors: list[BaseException] = []
        self.close_calls = 0

    def __aiter__(self) -> "_StubEventStream":
        return self

    async def __anext__(self) -> AgentEvent:
        if self._stream_error is not None:
            error = self._stream_error
            self._stream_error = None
            self._order.append("stream:error")
            raise error
        if self._index == len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        self._order.append(f"yield:{event.event_type}")
        return event

    async def acknowledge(self, event: AgentEvent) -> None:
        self._order.append(f"ack:{event.event_type}")
        if self._acknowledge_error is not None:
            raise self._acknowledge_error
        self.acknowledged.append(event)

    async def abort(self, error: BaseException) -> None:
        self.abort_errors.append(error)
        self._order.append("abort")
        if self._abort_error is not None:
            raise self._abort_error

    async def aclose(self) -> None:
        self.close_calls += 1
        self._order.append("aclose")
        if self._aclose_error is not None:
            raise self._aclose_error


class _StubAdapter:
    def __init__(
        self,
        *,
        result: ExecutionResult | None = None,
        events: list[AgentEvent] | None = None,
        start_error: BaseException | None = None,
        claim_error: BaseException | None = None,
        stream_error: BaseException | None = None,
        acknowledge_error: BaseException | None = None,
        abort_error: BaseException | None = None,
        aclose_error: BaseException | None = None,
        collect_error: BaseException | None = None,
        identity: tuple[str, str, str] = ("react", "native", "v1"),
    ) -> None:
        self.engine_id, self.protocol_id, self.adapter_version = identity
        self.result = result
        self.events = events or []
        self.start_error = start_error
        self.claim_error = claim_error
        self.stream_error = stream_error
        self.acknowledge_error = acknowledge_error
        self.abort_error = abort_error
        self.aclose_error = aclose_error
        self.collect_error = collect_error
        self.order: list[str] = []
        self.requests = []
        self.handles: list[ExecutionHandle] = []
        self.streams: list[_StubEventStream] = []
        self.cancel_calls = 0
        self.public_collect_calls = 0

    async def get_capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(streaming=True, cancellation=True)

    async def start(self, request) -> ExecutionHandle:
        self.requests.append(request)
        if self.start_error is not None:
            raise self.start_error
        handle = ExecutionHandle(
            execution_id=request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
        )
        self.handles.append(handle)
        self.order.append("start")
        return handle

    def stream_events(self, handle: ExecutionHandle) -> _StubEventStream:
        self.order.append("claim")
        if self.claim_error is not None:
            raise self.claim_error
        stream = _StubEventStream(
            self.events,
            self.order,
            stream_error=self.stream_error,
            acknowledge_error=self.acknowledge_error,
            abort_error=self.abort_error,
            aclose_error=self.aclose_error,
        )
        self.streams.append(stream)
        return stream

    async def cancel(self, handle: ExecutionHandle) -> None:
        self.cancel_calls += 1
        self.order.append("cancel")

    async def collect_result(self, handle: ExecutionHandle) -> ExecutionResult:
        self.public_collect_calls += 1
        self.order.append("public-collect")
        if self.collect_error is not None:
            raise self.collect_error
        assert self.result is not None
        return self.result


class _PrivateStubAdapter(_StubAdapter):
    def __init__(self, *, outcome: ExecutionOutcome, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.outcome = outcome
        self.private_collect_calls = 0

    @property
    def _execution(self) -> object:
        raise AssertionError("Orchestrator must not access React _execution")

    async def collect_outcome(self, handle: ExecutionHandle) -> ExecutionOutcome:
        self.private_collect_calls += 1
        self.order.append("private-collect")
        if self.collect_error is not None:
            raise self.collect_error
        return self.outcome


def _make_event(*, run_id: UUID = RUN_ID, kind: str = "model.delta") -> AgentEvent:
    return AgentEvent(
        execution_id=run_id,
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        event_id=UUID("50000000-0000-4000-8000-000000000001"),
        sequence=1,
        event_type=kind,
        source="engine_native",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        payload={"value": 1},
    )


def _completed_outcome(output: str = "done") -> ExecutionOutcome:
    return ExecutionOutcome(
        status="completed",
        output=output,
        history=[{"role": "assistant", "content": output}],
        dropped=[{"reason": "trimmed"}],
        usage={"tokens": 3},
    )


def _registry(
    factory,
    *,
    identity: tuple[str, str, str] = ("react", "native", "v1"),
    engine_enabled: bool = True,
    protocol_enabled: bool = True,
    adapter_enabled: bool = True,
) -> AdapterRegistry:
    engine_id, protocol_id, version = identity
    engines = EngineRegistry()
    protocols = ProtocolRegistry()
    engines.register(EngineDescriptor(engine_id=engine_id, enabled=engine_enabled))
    protocols.register(ProtocolDescriptor(protocol_id=protocol_id, enabled=protocol_enabled))
    adapters = AdapterRegistry(engines, protocols)
    adapters.register(
        AdapterDescriptor(
            engine_id=engine_id,
            protocol_id=protocol_id,
            adapter_version=version,
            enabled=adapter_enabled,
        ),
        factory,
    )
    return adapters


def _unknown_protocol_registry() -> AdapterRegistry:
    engines = EngineRegistry()
    engines.register(EngineDescriptor(engine_id="react"))
    return AdapterRegistry(engines, ProtocolRegistry())


def test_react_adapter_factory_synchronously_captures_fresh_context_without_running_runtime():
    calls = []

    class RuntimeFactorySpy:
        async def for_run(self, row: object, emit: object) -> object:
            calls.append((row, emit))
            raise AssertionError("for_run must not execute in synchronous factory")

    factory = ReactAdapterFactory(RuntimeFactorySpy())
    first_context = make_context()
    second_context = make_context(run_id=OTHER_RUN_ID)

    first = resolve_with_execution_context(first_context, factory)
    second = resolve_with_execution_context(second_context, factory)

    assert first is not second
    assert first._context is first_context
    assert second._context is second_context
    assert calls == []
    with pytest.raises(ConfigurationError) as caught:
        capture_execution_context()
    assert caught.value.error.code is ExecutionErrorCode.ADAPTER_FACTORY_FAILED


@pytest.mark.asyncio
async def test_orchestrator_fixed_selector_ack_order_and_single_private_outcome_collection():
    adapter = _PrivateStubAdapter(
        outcome=_completed_outcome(),
        events=[_make_event()],
    )
    registry = _registry(lambda: adapter)
    orchestrator = ExecutionOrchestrator(registry)
    order = adapter.order

    async def worker_emit(kind: str, payload: dict[str, object]) -> None:
        assert (kind, payload) == ("model.delta", {"value": 1})
        order.append(f"worker:{kind}")

    outcome = await orchestrator.execute(make_context(), worker_emit)

    assert outcome == adapter.outcome
    assert outcome.history == [{"role": "assistant", "content": "done"}]
    assert outcome.dropped == [{"reason": "trimmed"}]
    assert outcome.usage == {"tokens": 3}
    assert adapter.private_collect_calls == 1
    assert adapter.public_collect_calls == 0
    assert len(adapter.requests) == 1
    assert (
        adapter.requests[0].engine_id,
        adapter.requests[0].protocol_id,
        adapter.requests[0].adapter_version,
    ) == ("react", "native", "v1")
    assert order == [
        "start",
        "claim",
        "yield:model.delta",
        "worker:model.delta",
        "ack:model.delta",
        "private-collect",
    ]


@pytest.mark.asyncio
async def test_orchestrator_uses_fresh_adapters_and_isolates_concurrent_runs():
    adapters: list[_PrivateStubAdapter] = []

    def factory() -> _PrivateStubAdapter:
        index = len(adapters)
        run_id = RUN_ID if index == 0 else OTHER_RUN_ID
        adapter = _PrivateStubAdapter(
            outcome=_completed_outcome(f"done-{index}"),
            events=[_make_event(run_id=run_id, kind=f"extension.event.{index}")],
        )
        adapters.append(adapter)
        return adapter

    orchestrator = ExecutionOrchestrator(_registry(factory))
    first_emits = []
    second_emits = []

    async def first_emit(kind: str, payload: dict[str, object]) -> None:
        first_emits.append((kind, payload))
        await asyncio.sleep(0)

    async def second_emit(kind: str, payload: dict[str, object]) -> None:
        second_emits.append((kind, payload))

    first, second = await asyncio.gather(
        orchestrator.execute(make_context(), first_emit),
        orchestrator.execute(make_context(run_id=OTHER_RUN_ID), second_emit),
    )

    assert len(adapters) == 2
    assert adapters[0] is not adapters[1]
    assert first.output == "done-0"
    assert second.output == "done-1"
    assert first_emits == [("extension.event.0", {"value": 1})]
    assert second_emits == [("extension.event.1", {"value": 1})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,code,expected_legacy",
    [
        ("completed", None, None),
        ("failed", ExecutionErrorCode.EXECUTION_TIMEOUT, "run_timeout"),
        ("failed", ExecutionErrorCode.INTERNAL_ERROR, "execution_error"),
        ("failed", ExecutionErrorCode.PROTOCOL_ERROR, "execution_error"),
        ("failed", ExecutionErrorCode.SIMULATED_PROCESS_FAILURE, "execution_error"),
        ("cancelled", None, None),
    ],
)
async def test_protocol_free_public_result_fallback_is_deterministic(status, code, expected_legacy):
    """P2-IT14/R14: LocalTest fallback uses only status and public error code."""
    result = make_result(status)
    if code is not None:
        result = make_result(
            status,
            error=ExecutionError(
                category=(
                    ExecutionErrorCategory.TIMEOUT
                    if code is ExecutionErrorCode.EXECUTION_TIMEOUT
                    else (
                        ExecutionErrorCategory.PROTOCOL_ERROR
                        if code is ExecutionErrorCode.PROTOCOL_ERROR
                        else ExecutionErrorCategory.INTERNAL_ERROR
                    )
                ),
                code=code,
            ),
        )
    adapter = _StubAdapter(result=result)
    outcome = await ExecutionOrchestrator(_registry(lambda: adapter)).execute(
        make_context(), _discard_worker_emit
    )

    assert outcome.status == status
    assert outcome.legacy_error_code == expected_legacy
    assert adapter.public_collect_calls == 1
    if status == "completed":
        assert outcome.history == []
        assert outcome.dropped == []
    else:
        assert outcome.history is None
        assert outcome.dropped is None


async def _discard_worker_emit(kind: str, payload: dict[str, object]) -> None:
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario,expected_status,expected_legacy",
    [
        (
            LocalTestScenario(
                events=(LocalTestEventSpec(event_type="extension.local", payload={"x": 1}),),
                output="local done",
            ),
            "completed",
            None,
        ),
        (
            LocalTestScenario(
                error=ExecutionError(
                    category=ExecutionErrorCategory.PROTOCOL_ERROR,
                    code=ExecutionErrorCode.PROTOCOL_ERROR,
                )
            ),
            "failed",
            "execution_error",
        ),
    ],
)
async def test_real_local_test_uses_separate_selector_public_collect_and_no_private_ack(
    scenario, expected_status, expected_legacy
):
    """P2-IT14: independent LocalTest succeeds/fails without ack or private Outcome."""
    identity = ("local-test", "scripted", "v1")
    adapter = LocalTestAdapter(scenario)
    registry = _registry(lambda: adapter, identity=identity)
    orchestrator = ExecutionOrchestrator(registry, selector=identity)
    emitted = []

    async def worker_emit(kind: str, payload: dict[str, object]) -> None:
        emitted.append((kind, payload))

    outcome = await orchestrator.execute(make_context(), worker_emit)

    assert outcome.status == expected_status
    assert outcome.legacy_error_code == expected_legacy
    if expected_status == "completed":
        assert outcome.output == "local done"
        assert outcome.history == []
        assert outcome.dropped == []
        assert emitted == [("extension.local", {"x": 1})]
    assert as_outcome_collecting_adapter(adapter) is None
    assert not hasattr(adapter, "collect_outcome")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "registry_factory,expected_code",
    [
        (lambda: AdapterRegistry(EngineRegistry(), ProtocolRegistry()), "unknown_engine"),
        (_unknown_protocol_registry, "unknown_protocol"),
        (
            lambda: _registry(
                lambda: _StubAdapter(result=make_result("completed")), engine_enabled=False
            ),
            "engine_disabled",
        ),
        (
            lambda: _registry(
                lambda: _StubAdapter(result=make_result("completed")), protocol_enabled=False
            ),
            "protocol_disabled",
        ),
        (
            lambda: _registry(
                lambda: _StubAdapter(result=make_result("completed")),
                identity=("react", "native", "v2"),
            ),
            "unknown_adapter_version",
        ),
        (
            lambda: _registry(
                lambda: _StubAdapter(result=make_result("completed")), adapter_enabled=False
            ),
            "adapter_disabled",
        ),
    ],
)
async def test_resolution_failures_return_safe_failed_outcomes_without_fallback(
    registry_factory, expected_code
):
    """P2-IT13: deleted/disabled/exact-version misses fail safely with no legacy fallback."""
    outcome = await ExecutionOrchestrator(registry_factory()).execute(
        make_context(), _discard_worker_emit
    )
    assert outcome.status == "failed"
    assert outcome.legacy_error_code == expected_code
    assert outcome.output is None


@pytest.mark.asyncio
async def test_p2_it20_forged_or_nil_agent_fails_before_registry_or_legacy_query():
    """P2-IT20 non-PG: invalid identity never reaches authorization/registry resolution."""
    resolve_calls = 0

    def forbidden_factory():
        nonlocal resolve_calls
        resolve_calls += 1
        raise AssertionError("invalid Agent identity must not resolve an adapter or legacy runtime")

    for agent in ({"id": None}, {"id": UUID(int=0)}, {"id": "forged-agent"}):
        outcome = await ExecutionOrchestrator(_registry(forbidden_factory)).execute(
            make_context(agent=agent), _discard_worker_emit
        )
        assert outcome.status == "failed"
        assert outcome.legacy_error_code == "invalid_request"
        assert "forged-agent" not in repr(outcome)
        assert "row" not in repr(outcome)
        assert "context" not in repr(outcome).lower()
    assert resolve_calls == 0


@pytest.mark.asyncio
async def test_factory_and_unknown_assembly_failures_are_safe_and_reset_context():
    def broken_factory() -> _StubAdapter:
        raise RuntimeError("private factory diagnostic")

    factory_outcome = await ExecutionOrchestrator(_registry(broken_factory)).execute(
        make_context(), _discard_worker_emit
    )
    assert factory_outcome.legacy_error_code == "adapter_factory_failed"
    with pytest.raises(ConfigurationError):
        capture_execution_context()

    class UnknownRegistry:
        def resolve(self, engine_id: str, protocol_id: str, version: str) -> _StubAdapter:
            raise RuntimeError("private registry diagnostic")

    unknown_outcome = await ExecutionOrchestrator(UnknownRegistry()).execute(
        make_context(), _discard_worker_emit
    )
    assert unknown_outcome.status == "failed"
    assert unknown_outcome.legacy_error_code == "execution_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["start", "claim", "stream", "worker_emit", "collect"])
async def test_each_execution_stage_failure_cleans_stream_and_returns_safe_failed(stage):
    error = RuntimeError("private stage diagnostic")
    adapter = _PrivateStubAdapter(
        outcome=(
            _completed_outcome()
            if stage == "claim"
            else ExecutionOutcome(status="failed", legacy_error_code="execution_error")
        ),
        events=[_make_event()],
        start_error=error if stage == "start" else None,
        claim_error=error if stage == "claim" else None,
        stream_error=error if stage == "stream" else None,
        collect_error=error if stage == "collect" else None,
    )

    async def worker_emit(kind: str, payload: dict[str, object]) -> None:
        if stage == "worker_emit":
            raise error

    outcome = await ExecutionOrchestrator(_registry(lambda: adapter)).execute(
        make_context(), worker_emit
    )

    assert outcome.status == "failed"
    assert outcome.legacy_error_code == "execution_error"
    if stage not in {"start", "claim"}:
        stream = adapter.streams[0]
        assert len(stream.abort_errors) == 1
        assert stream.close_calls == 1
    if stage == "claim":
        assert adapter.streams == []
        assert adapter.cancel_calls == 1
        assert adapter.private_collect_calls == 0
        assert adapter.public_collect_calls == 0
    if stage == "worker_emit":
        assert stream.acknowledged == []
        assert adapter.private_collect_calls == 1


@pytest.mark.asyncio
async def test_append_cancelled_error_is_not_acknowledged_and_rethrows_after_cleanup():
    adapter = _PrivateStubAdapter(outcome=_completed_outcome(), events=[_make_event()])
    cancellation = asyncio.CancelledError()

    async def append_cancelled(kind: str, payload: dict[str, object]) -> None:
        raise cancellation

    with pytest.raises(asyncio.CancelledError) as caught:
        await ExecutionOrchestrator(_registry(lambda: adapter)).execute(
            make_context(), append_cancelled
        )

    assert caught.value is cancellation
    stream = adapter.streams[0]
    assert stream.acknowledged == []
    assert stream.abort_errors == [cancellation]
    assert stream.close_calls == 1
    assert adapter.private_collect_calls == 0


@pytest.mark.asyncio
async def test_caller_cancellation_during_worker_emit_rethrows_without_ack_or_outcome():
    adapter = _PrivateStubAdapter(outcome=_completed_outcome(), events=[_make_event()])
    entered = asyncio.Event()

    async def blocked_worker_emit(kind: str, payload: dict[str, object]) -> None:
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        ExecutionOrchestrator(_registry(lambda: adapter)).execute(
            make_context(), blocked_worker_emit
        )
    )
    await asyncio.wait_for(entered.wait(), timeout=0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    stream = adapter.streams[0]
    assert stream.acknowledged == []
    assert len(stream.abort_errors) == 1
    assert isinstance(stream.abort_errors[0], asyncio.CancelledError)
    assert stream.close_calls == 1
    assert adapter.private_collect_calls == 0
    assert task.done()


@pytest.mark.asyncio
async def test_real_react_orchestration_preserves_dual_emit_order_and_unknown_legacy_code():
    factory_calls = []
    runtime_calls = []

    class Runtime:
        async def run(
            self,
            message: object,
            history: list[dict[str, object]],
            emit: object,
            *,
            summary_message: str | None = None,
            customer_memory: str | None = None,
        ) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
            runtime_calls.append((message, history, emit, summary_message, customer_memory))
            await emit("model.delta", {"text": "A"})
            return "answer", [{"role": "assistant", "content": "answer"}], [{"old": True}]

    class Factory:
        async def for_run(self, row: object, emit: object) -> Runtime:
            factory_calls.append((row, emit))
            await asyncio.sleep(0)
            return Runtime()

    runtime_factory = Factory()
    registry = _registry(ReactAdapterFactory(runtime_factory))
    emitted = []

    async def worker_emit(kind: str, payload: dict[str, object]) -> None:
        emitted.append((kind, payload))

    outcome = await ExecutionOrchestrator(registry).execute(make_context(), worker_emit)

    assert outcome.status == "completed"
    assert outcome.history == [{"role": "assistant", "content": "answer"}]
    assert outcome.dropped == [{"old": True}]
    assert emitted == [("model.delta", {"text": "A"})]
    assert len(factory_calls) == len(runtime_calls) == 1
    assert factory_calls[0][1] is runtime_calls[0][2]
    assert factory_calls[0][0] is not None

    class FaultFactory:
        async def for_run(self, row: object, emit: object) -> Runtime:
            raise RuntimeFault("future_orchestrator_" + "legacy_code")

    failed = await ExecutionOrchestrator(_registry(ReactAdapterFactory(FaultFactory()))).execute(
        make_context(run_id=OTHER_RUN_ID), worker_emit
    )
    assert failed.status == "failed"
    assert failed.legacy_error_code == "future_orchestrator_legacy_code"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "control_flow",
    [False, True],
    ids=["nested-ordinary-exception-group", "nested-control-exception-group"],
)
async def test_real_react_worker_exception_groups_follow_control_flow_membership(control_flow):
    adapters = []
    acknowledge_calls = []
    runtime_gate = asyncio.Event()

    class Runtime:
        async def run(
            self,
            message: object,
            history: list[dict[str, object]],
            emit: object,
            *,
            summary_message: str | None = None,
            customer_memory: str | None = None,
        ) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
            await emit("model.delta", {"text": "A"})
            await runtime_gate.wait()
            raise AssertionError("cancelled runtime must not complete")

    class Factory:
        async def for_run(self, row: object, emit: object) -> Runtime:
            return Runtime()

    react_factory = ReactAdapterFactory(Factory())

    def factory():
        adapter = react_factory()
        adapters.append(adapter)
        original_stream_events = adapter.stream_events

        def stream_events(handle: ExecutionHandle):
            stream = original_stream_events(handle)
            original_acknowledge = stream.acknowledge

            async def acknowledge(event: AgentEvent) -> None:
                acknowledge_calls.append(event)
                await original_acknowledge(event)

            stream.acknowledge = acknowledge
            return stream

        adapter.stream_events = stream_events
        return adapter

    if control_flow:
        worker_group = BaseExceptionGroup(
            "probe",
            [
                ExceptionGroup("ordinary member", [RuntimeError("worker")]),
                BaseExceptionGroup("nested control", [asyncio.CancelledError()]),
            ],
        )
    else:
        worker_group = ExceptionGroup(
            "ordinary worker group",
            [RuntimeError("one"), ExceptionGroup("nested ordinary", [ValueError("two")])],
        )

    async def worker_emit(kind: str, payload: dict[str, object]) -> None:
        raise worker_group

    outcome = None
    if control_flow:
        with pytest.raises(BaseExceptionGroup) as caught:
            await ExecutionOrchestrator(_registry(factory)).execute(make_context(), worker_emit)
        assert caught.value is worker_group
    else:
        outcome = await ExecutionOrchestrator(_registry(factory)).execute(
            make_context(), worker_emit
        )
        assert outcome.status == "failed"
        assert outcome.legacy_error_code == "execution_error"

    adapter = adapters[0]
    execution = adapter._execution
    assert execution is not None
    assert execution.stream_state == "closed"
    assert acknowledge_calls == []
    assert execution.in_flight is None
    assert execution.settled_acks == set()
    assert execution.terminal.done()
    expected_status = "cancelled" if control_flow else "failed"
    assert execution.terminal.result().status == expected_status
    assert execution.task is not None and execution.task.done()
    assert all(task.done() for task in adapter._owned_tasks)
    assert not runtime_gate.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code,category",
    [
        (ExecutionErrorCode.PERMISSION_DENIED, ExecutionErrorCategory.PERMISSION_DENIED),
        (ExecutionErrorCode.INTERNAL_ERROR, ExecutionErrorCategory.INTERNAL_ERROR),
        (ExecutionErrorCode.PROTOCOL_ERROR, ExecutionErrorCategory.PROTOCOL_ERROR),
        (ExecutionErrorCode.EXECUTION_TIMEOUT, ExecutionErrorCategory.TIMEOUT),
    ],
)
async def test_real_local_worker_safe_errors_always_map_to_execution_error(code, category):
    identity = ("local-test", "scripted", "v1")
    adapter = LocalTestAdapter(
        LocalTestScenario(
            events=(LocalTestEventSpec(event_type="extension.local"),),
            completion_gate=asyncio.Event(),
        )
    )
    failure = AdapterExecutionError(ExecutionError(category=category, code=code))

    async def worker_emit(kind: str, payload: dict[str, object]) -> None:
        raise failure

    outcome = await ExecutionOrchestrator(
        _registry(lambda: adapter, identity=identity), selector=identity
    ).execute(make_context(), worker_emit)

    assert outcome.status == "failed"
    assert outcome.legacy_error_code == "execution_error"
    assert adapter._execution is not None
    assert adapter._execution.terminal.done()
    assert all(task.done() for task in adapter._owned_tasks)
    assert as_outcome_collecting_adapter(adapter) is None
    assert not hasattr(adapter, "acknowledge")
    assert not hasattr(adapter, "collect_outcome")


@pytest.mark.asyncio
async def test_real_local_external_adapter_cancel_returns_orchestrator_cancelled_fallback():
    """P2-IT14: LocalTest cancellation cleans its owned task and uses public collect."""
    identity = ("local-test", "scripted", "v1")
    adapter = LocalTestAdapter(
        LocalTestScenario(
            events=(LocalTestEventSpec(event_type="extension.local"),),
            completion_gate=asyncio.Event(),
        )
    )
    original_collect_result = adapter.collect_result
    public_collect_calls = 0

    async def collect_result(handle: ExecutionHandle) -> ExecutionResult:
        nonlocal public_collect_calls
        public_collect_calls += 1
        return await original_collect_result(handle)

    adapter.collect_result = collect_result
    worker_entered = asyncio.Event()
    release_worker = asyncio.Event()

    async def worker_emit(kind: str, payload: dict[str, object]) -> None:
        worker_entered.set()
        await release_worker.wait()

    task = asyncio.create_task(
        ExecutionOrchestrator(
            _registry(lambda: adapter, identity=identity), selector=identity
        ).execute(make_context(), worker_emit)
    )
    try:
        await asyncio.wait_for(worker_entered.wait(), timeout=ASYNC_WATCHDOG_SECONDS)
        execution = adapter._execution
        assert execution is not None
        await adapter.cancel(execution.handle)
        release_worker.set()

        outcome = await asyncio.wait_for(task, timeout=ASYNC_WATCHDOG_SECONDS)

        assert outcome.status == "cancelled"
        assert outcome.legacy_error_code is None
        assert outcome.output is None
        assert public_collect_calls == 1
        assert execution.stream_closed
        assert execution.task is not None and execution.task.done()
        assert all(owned.done() for owned in adapter._owned_tasks)
        assert as_outcome_collecting_adapter(adapter) is None
        assert not hasattr(adapter, "acknowledge")
        assert not hasattr(adapter, "collect_outcome")
    finally:
        release_worker.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,expected_status,expected_legacy",
    [
        ("completed", "completed", None),
        ("protocol_error", "failed", "execution_error"),
        ("execution_timeout", "failed", "run_timeout"),
        ("external_cancel", "cancelled", None),
    ],
)
async def test_p2_it14_real_local_test_orchestrator_worker_repository_end_to_end(
    mode, expected_status, expected_legacy, monkeypatch
):
    """P2-IT14: a fresh public-only LocalTest drives the real Worker terminal path."""
    identity = ("local-test", "scripted", "v1")
    needs_gate = mode in {"execution_timeout", "external_cancel"}
    scenario = LocalTestScenario(
        events=(LocalTestEventSpec(event_type="extension.local", payload={"mode": mode}),),
        output="local done" if mode == "completed" else None,
        error=(
            ExecutionError(
                category=ExecutionErrorCategory.PROTOCOL_ERROR,
                code=ExecutionErrorCode.PROTOCOL_ERROR,
            )
            if mode == "protocol_error"
            else None
        ),
        completion_gate=asyncio.Event() if needs_gate else None,
        manual_timeout=mode == "execution_timeout",
    )
    adapters = []
    streams = []
    collect_calls = []
    adapter_started = asyncio.Event()

    def factory():
        adapter = LocalTestAdapter(scenario)
        original_start = adapter.start
        original_stream_events = adapter.stream_events
        original_collect_result = adapter.collect_result

        async def start(request):
            handle = await original_start(request)
            adapter_started.set()
            return handle

        def stream_events(handle):
            stream = original_stream_events(handle)
            streams.append(stream)
            return stream

        async def collect_result(handle):
            collect_calls.append(handle)
            return await original_collect_result(handle)

        adapter.start = start
        adapter.stream_events = stream_events
        adapter.collect_result = collect_result
        adapters.append(adapter)
        return adapter

    orchestrator = ExecutionOrchestrator(_registry(factory, identity=identity), selector=identity)
    original_execute = orchestrator.execute
    outcomes = []

    async def execute(context, worker_emit):
        outcome = await original_execute(context, worker_emit)
        outcomes.append(outcome)
        return outcome

    orchestrator.execute = execute
    repository = ParityRepository()
    original_append = repository.append
    append_entered = asyncio.Event()
    release_append = asyncio.Event()

    async def append(run_id, owner, kind, data):
        if mode == "external_cancel" and kind == "extension.local":
            append_entered.set()
            await release_append.wait()
        await original_append(run_id, owner, kind, data)

    repository.append = append
    settings = Settings(
        _env_file=None,
        execution_orchestrator_enabled=True,
        run_timeout_seconds=1,
    )
    worker = RuntimeWorker(
        repository,
        object(),
        settings,
        "parity-fingerprint",
        orchestrator=orchestrator,
    )
    owned_tasks = []
    original_create_task = asyncio.create_task

    def create_task(coro, **kwargs):
        task = original_create_task(coro, **kwargs)
        owned_tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "create_task", create_task)
    worker_execution = asyncio.create_task(worker._execute(parity_worker_row()))
    try:
        await asyncio.wait_for(adapter_started.wait(), timeout=ASYNC_WATCHDOG_SECONDS)
        adapter = adapters[0]
        execution = adapter._execution
        assert execution is not None

        if mode == "execution_timeout":
            adapter.clock.advance(1)
        elif mode == "external_cancel":
            await asyncio.wait_for(append_entered.wait(), timeout=ASYNC_WATCHDOG_SECONDS)
            await adapter.cancel(execution.handle)
            release_append.set()
        await asyncio.wait_for(worker_execution, timeout=ASYNC_WATCHDOG_SECONDS)

        assert len(adapters) == 1
        assert len(outcomes) == 1
        assert outcomes[0].status == expected_status
        assert outcomes[0].legacy_error_code == expected_legacy
        if expected_status == "completed":
            assert outcomes[0].history == []
            assert outcomes[0].dropped == []
        assert collect_calls == [execution.handle]
        assert len(streams) == 1
        assert as_acknowledging_event_stream(streams[0]) is None
        assert as_outcome_collecting_adapter(adapter) is None
        assert not hasattr(adapter, "acknowledge")
        assert not hasattr(adapter, "collect_outcome")
        assert [event["type"] for event in repository.events] == [
            "extension.local",
            f"run.{expected_status}",
        ]
        assert repository.append_calls == 2
        assert len(repository.finishes) == 1
        finish = repository.finishes[0]
        assert finish["status"] == expected_status
        assert finish.get("error") == expected_legacy
        if expected_status == "completed":
            assert finish["output"] == "local done"
            assert finish["history"] == []
        assert execution.stream_closed
        assert execution.task is not None and execution.task.done()
        assert all(task.done() for task in adapter._owned_tasks)
        assert all(task.done() for task in owned_tasks)
        assert worker.tasks == set()
    finally:
        release_append.set()
        if not worker_execution.done():
            worker_execution.cancel()
        await asyncio.gather(worker_execution, return_exceptions=True)
        for created_adapter in adapters:
            created_execution = created_adapter._execution
            if created_execution is not None and not created_execution.terminal.done():
                await created_adapter.cancel(created_execution.handle)
            for owned_task in created_adapter._owned_tasks:
                if not owned_task.done():
                    owned_task.cancel()
            await asyncio.gather(*created_adapter._owned_tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["worker_emit", "acknowledge"])
@pytest.mark.parametrize(
    "abort_fails,aclose_fails",
    [(True, False), (False, True), (True, True)],
)
async def test_worker_or_ack_failure_with_cleanup_failure_never_returns_completed(
    stage, abort_fails, aclose_fails
):
    original = RuntimeError("private-worker-diagnostic")
    adapter = _PrivateStubAdapter(
        outcome=_completed_outcome(),
        events=[_make_event()],
        acknowledge_error=original if stage == "acknowledge" else None,
        abort_error=RuntimeError("private-abort-diagnostic") if abort_fails else None,
        aclose_error=RuntimeError("private-close-diagnostic") if aclose_fails else None,
    )

    async def worker_emit(kind: str, payload: dict[str, object]) -> None:
        if stage == "worker_emit":
            raise original

    outcome = await ExecutionOrchestrator(_registry(lambda: adapter)).execute(
        make_context(), worker_emit
    )

    assert outcome.status == "failed"
    assert outcome.legacy_error_code == "execution_error"
    assert "private-worker-diagnostic" not in repr(outcome)
    assert "private-abort-diagnostic" not in repr(outcome)
    assert "private-close-diagnostic" not in repr(outcome)
    stream = adapter.streams[0]
    assert stream.acknowledged == []
    assert stream.abort_errors == [original]
    assert stream.close_calls == 1
    assert adapter.private_collect_calls == 0
    assert adapter.public_collect_calls == 0


@pytest.mark.asyncio
async def test_stream_failure_preserves_original_legacy_after_cleanup_failure():
    adapter = _PrivateStubAdapter(
        outcome=ExecutionOutcome(status="failed", legacy_error_code="model_timeout"),
        stream_error=RuntimeError("private-stream-diagnostic"),
        aclose_error=RuntimeError("private-close-diagnostic"),
    )

    outcome = await ExecutionOrchestrator(_registry(lambda: adapter)).execute(
        make_context(), _discard_worker_emit
    )

    assert outcome.status == "failed"
    assert outcome.legacy_error_code == "model_timeout"
    assert adapter.private_collect_calls == 1
    assert adapter.public_collect_calls == 0
    assert adapter.streams[0].close_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("private_capability", [False, True])
@pytest.mark.parametrize("collected_status", ["completed", "cancelled"])
async def test_stream_failure_with_cleanup_failure_rejects_non_failed_collection(
    private_capability, collected_status
):
    original = RuntimeError("private-stream-diagnostic")
    if private_capability:
        collected = (
            _completed_outcome()
            if collected_status == "completed"
            else ExecutionOutcome(status="cancelled")
        )
        adapter = _PrivateStubAdapter(
            outcome=collected,
            stream_error=original,
            aclose_error=RuntimeError("private-close-diagnostic"),
        )
    else:
        adapter = _StubAdapter(
            result=make_result(collected_status),
            stream_error=original,
            aclose_error=RuntimeError("private-close-diagnostic"),
        )

    outcome = await ExecutionOrchestrator(_registry(lambda: adapter)).execute(
        make_context(), _discard_worker_emit
    )

    assert outcome.status == "failed"
    assert outcome.legacy_error_code == "execution_error"
    assert "private-stream-diagnostic" not in repr(outcome)
    assert "private-close-diagnostic" not in repr(outcome)
    stream = adapter.streams[0]
    assert stream.abort_errors == [original]
    assert stream.close_calls == 1
    if private_capability:
        assert adapter.private_collect_calls == 1
        assert adapter.public_collect_calls == 0
    else:
        assert adapter.public_collect_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("private_capability", [False, True])
@pytest.mark.parametrize(
    "code",
    [ExecutionErrorCode.EXECUTION_TIMEOUT, ExecutionErrorCode.PROTOCOL_ERROR],
)
async def test_collect_call_failures_are_execution_error_without_second_collection(
    private_capability, code
):
    category = (
        ExecutionErrorCategory.TIMEOUT
        if code is ExecutionErrorCode.EXECUTION_TIMEOUT
        else ExecutionErrorCategory.PROTOCOL_ERROR
    )
    failure = AdapterExecutionError(ExecutionError(category=category, code=code))
    if private_capability:
        adapter = _PrivateStubAdapter(
            outcome=_completed_outcome(),
            result=make_result("completed"),
            collect_error=failure,
        )
    else:
        adapter = _StubAdapter(result=make_result("completed"), collect_error=failure)

    outcome = await ExecutionOrchestrator(_registry(lambda: adapter)).execute(
        make_context(), _discard_worker_emit
    )

    assert outcome.status == "failed"
    assert outcome.legacy_error_code == "execution_error"
    assert adapter.streams[0].abort_errors == [failure]
    assert adapter.streams[0].close_calls == 1
    if private_capability:
        assert adapter.private_collect_calls == 1
        assert adapter.public_collect_calls == 0
    else:
        assert adapter.public_collect_calls == 1


@pytest.mark.asyncio
async def test_real_react_claim_failure_cancels_owned_runner_without_collection():
    adapters = []
    claimed_streams = []
    runtime_gate = asyncio.Event()

    class Runtime:
        async def run(
            self,
            message: object,
            history: list[dict[str, object]],
            emit: object,
            *,
            summary_message: str | None = None,
            customer_memory: str | None = None,
        ) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
            await runtime_gate.wait()
            raise AssertionError("claim failure must cancel the gated runtime")

    class Factory:
        async def for_run(self, row: object, emit: object) -> Runtime:
            return Runtime()

    react_factory = ReactAdapterFactory(Factory())

    def factory():
        adapter = react_factory()
        adapters.append(adapter)
        original_stream_events = adapter.stream_events
        original_cancel = adapter.cancel
        original_collect_outcome = adapter.collect_outcome
        adapter.cancel_calls = 0
        adapter.private_collect_calls = 0

        def stream_events(handle: ExecutionHandle):
            stream = original_stream_events(handle)
            claimed_streams.append(stream)
            raise RuntimeError("private-claim-diagnostic")

        async def cancel(handle: ExecutionHandle) -> None:
            adapter.cancel_calls += 1
            await original_cancel(handle)

        async def collect_outcome(handle: ExecutionHandle) -> ExecutionOutcome:
            adapter.private_collect_calls += 1
            return await original_collect_outcome(handle)

        adapter.stream_events = stream_events
        adapter.cancel = cancel
        adapter.collect_outcome = collect_outcome
        return adapter

    outcome = await ExecutionOrchestrator(_registry(factory)).execute(
        make_context(), _discard_worker_emit
    )

    assert outcome.status == "failed"
    assert outcome.legacy_error_code == "execution_error"
    adapter = adapters[0]
    execution = adapter._execution
    assert execution is not None
    assert len(claimed_streams) == 1
    assert adapter.cancel_calls == 1
    assert adapter.private_collect_calls == 0
    assert execution.stream_state == "closed"
    assert execution.terminal.done()
    assert execution.terminal.result().status == "cancelled"
    assert execution.task is not None and execution.task.done()
    assert all(task.done() for task in adapter._owned_tasks)


def test_execution_orchestrator_settings_default_and_process_lifetime(monkeypatch):
    monkeypatch.delenv("AGENT_EXECUTION_ORCHESTRATOR_ENABLED", raising=False)
    settings = Settings(_env_file=None)
    assert settings.execution_orchestrator_enabled is False

    monkeypatch.setenv("AGENT_EXECUTION_ORCHESTRATOR_ENABLED", "true")
    assert settings.execution_orchestrator_enabled is False
    assert Settings(_env_file=None).execution_orchestrator_enabled is True


@pytest.mark.parametrize(
    "value,expected", [("true", True), ("false", False), ("1", True), ("0", False)]
)
def test_execution_orchestrator_settings_parse_environment(monkeypatch, value, expected):
    monkeypatch.setenv("AGENT_EXECUTION_ORCHESTRATOR_ENABLED", value)
    assert Settings(_env_file=None).execution_orchestrator_enabled is expected


def test_execution_orchestrator_settings_reject_invalid_environment(monkeypatch):
    monkeypatch.setenv("AGENT_EXECUTION_ORCHESTRATOR_ENABLED", "not-a-boolean")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_runtime_fingerprint_excludes_both_rollout_flags_and_the_phase3_tuning_family():
    """R-48 repair of 03 §4.3: operational tuning must not invalidate queued Runs.

    Two faces are pinned at once. An already-queued Run may never report
    ``configuration_changed`` because an operator flipped ``execution_phase3_enabled``
    or re-tuned a capability knob, while a change that really alters Runtime
    assembly - the model, the retained window, the round budget - must still change
    the fingerprint, otherwise the exclude set would be swallowing inputs the
    Runtime is built from.
    """
    base = Settings(_env_file=None)
    off = Settings(_env_file=None, execution_orchestrator_enabled=False)
    on = Settings(_env_file=None, execution_orchestrator_enabled=True)
    phase3 = Settings(_env_file=None, execution_phase3_enabled=not base.execution_phase3_enabled)
    tuned = Settings(
        _env_file=None,
        execution_capability_probe_cache_seconds=base.execution_capability_probe_cache_seconds + 1,
        execution_capability_policy_cache_seconds=(
            base.execution_capability_policy_cache_seconds + 1
        ),
        execution_capability_probe_timeout_seconds=(
            base.execution_capability_probe_timeout_seconds + 0.5
        ),
        execution_capability_policy_timeout_seconds=(
            base.execution_capability_policy_timeout_seconds + 0.5
        ),
        execution_capability_probe_max_concurrency=(
            base.execution_capability_probe_max_concurrency + 1
        ),
        execution_capability_cache_capacity=base.execution_capability_cache_capacity + 16,
        execution_capability_cache_retry_seconds=(
            base.execution_capability_cache_retry_seconds + 1
        ),
        execution_capability_warm_refresh_seconds=(
            base.execution_capability_warm_refresh_seconds + 1
        ),
        execution_capability_deployment_identity="a-different-deployment",
        execution_capability_policy_version="v2",
        execution_snapshot_max_bytes=base.execution_snapshot_max_bytes + 4096,
    )
    changed_runtime = Settings(
        _env_file=None,
        execution_orchestrator_enabled=True,
        model_name="different-runtime-model",
    )
    changed_history = Settings(_env_file=None, history_turns=base.history_turns + 1)
    changed_rounds = Settings(_env_file=None, max_model_rounds=base.max_model_rounds + 1)

    for unchanged in (off, on, phase3, tuned):
        assert _runtime_fingerprint(base, []) == _runtime_fingerprint(unchanged, [])
    for changed in (changed_runtime, changed_history, changed_rounds):
        assert _runtime_fingerprint(base, []) != _runtime_fingerprint(changed, [])


def test_runtime_fingerprint_exclude_set_names_every_phase3_field():
    """The exclude set is a rule, not a coincidence: every Phase 3 field is listed."""
    excluded = runtime_composition._runtime_fingerprint_exclude_fields()
    phase3_fields = {name for name in Settings.model_fields if name.startswith("execution_")} - {
        "execution_orchestrator_enabled"
    }

    assert excluded >= phase3_fields | {"execution_phase3_enabled"}
    assert "execution_orchestrator_enabled" in excluded
    # A field that really changes Runtime assembly may never join the exclude set.
    for assembly_field in ("model_name", "model_backend", "history_turns", "max_model_rounds"):
        assert assembly_field not in excluded


def test_shared_composition_registers_fixed_descriptors_without_per_run_execution():
    class ExplodingRuntimeFactory:
        async def for_run(self, row, emit):
            raise AssertionError("composition must not resolve or run a runtime")

    runtime_factory = ExplodingRuntimeFactory()
    orchestrator = _build_execution_orchestrator(runtime_factory, settings=Settings(_env_file=None))

    assert orchestrator.selector == ("react", "native", "v1")
    engine = orchestrator._registry._engines.get("react")
    protocol = orchestrator._registry._protocols.get("native")
    assert engine == EngineDescriptor(engine_id="react", enabled=True)
    assert protocol == ProtocolDescriptor(protocol_id="native", enabled=True)

    adapter = resolve_with_execution_context(
        make_context(),
        lambda: orchestrator._registry.resolve("react", "native", "v1"),
    )
    assert (adapter.engine_id, adapter.protocol_id, adapter.adapter_version) == (
        "react",
        "native",
        "v1",
    )
    assert adapter._runtime_factory is runtime_factory
    assert adapter._execution is None


def test_worker_source_has_no_concrete_engine_branch_and_composition_injects_only_when_on():
    worker_source = Path("src/agent_platform/core_platform/agent_runtime/worker.py").read_text(
        encoding="utf-8"
    )
    composition_source = Path(
        "src/agent_platform/applications/platform_runtime/runtime_composition.py"
    ).read_text(encoding="utf-8")

    assert "ReactAdapter" not in worker_source
    assert "LocalTestAdapter" not in worker_source
    assert "orchestrator=orchestrator if settings.execution_orchestrator_enabled else None" in (
        composition_source
    )


class ParityRepository:
    """In-memory durable Run log with the repository-owned terminal frame."""

    def __init__(self):
        self.events = []
        self.transient = []
        self.finishes = []
        self.append_calls = 0

    async def append(self, run_id, owner, kind, data):
        self.append_calls += 1
        self.events.append(
            {
                "run_id": run_id,
                "event_id": f"{run_id}:{len(self.events) + 1}",
                "timestamp": datetime.now(UTC),
                "seq": len(self.events) + 1,
                "type": kind,
                "data": deepcopy(data),
            }
        )

    async def finish(self, run_id, owner, status, **details):
        self.finishes.append({"status": status, **deepcopy(details)})
        kind = f"run.{status}"
        data = {"output": details.get("output"), "error_code": details.get("error")}
        await self.append(run_id, owner, kind, data)

    async def heartbeat(self, run_id, owner, lease_seconds):
        return "ok"

    def capture(self, *, model_calls=None, outcome=None, raw_latency=None):
        finish = self.finishes[-1]
        durable = deepcopy(self.events)
        usage = [
            deepcopy(event["data"]["usage"])
            for event in durable
            if event["type"] == "model.completed"
        ]
        return {
            "run_id": durable[0]["run_id"] if durable else RUN_ID,
            "event_id": "run-instance",
            "timestamp": "run-instance-time",
            "output": finish.get("output"),
            "error_code": finish.get("error"),
            "status": finish["status"],
            "usage": usage,
            "aggregate_usage": outcome.usage if outcome is not None else {},
            "history": finish.get("history"),
            "dropped": (finish.get("completion") or {}).get("dropped"),
            "memory_context": finish.get("completion"),
            "events": durable[:-1],
            "terminal": durable[-1],
            "replay": durable,
            "transient": self.transient,
            "model_calls": model_calls or [],
            "raw_latency": raw_latency or {},
        }


class ParityMemory:
    def render_summary(self, summary):
        return None if summary is None else f"SUMMARY: {summary}"

    async def customer_memory(self, row, settings):
        row["_memory_injected"] = {"items": 1}
        row["_memory_reinforce"] = {"memory-item": 2}
        return "CUSTOMER: preference-a"

    def memory_context(self, row, dropped, settings):
        return {
            "dropped": deepcopy(dropped),
            "injected": deepcopy(row["_memory_injected"]),
            "reinforce": deepcopy(row["_memory_reinforce"]),
        }


class _OutcomeRecordingOrchestrator:
    def __init__(self, runtime_factory):
        self.inner = _build_execution_orchestrator(
            runtime_factory, settings=Settings(_env_file=None)
        )
        self.selector = self.inner.selector
        self.outcomes = []

    async def execute(self, context, worker_emit):
        outcome = await self.inner.execute(context, worker_emit)
        self.outcomes.append(outcome)
        return outcome


def _message_capture(messages):
    return [
        [
            {
                "type": message.type,
                "content": message.content,
                "additional_kwargs": deepcopy(message.additional_kwargs),
            }
            for message in round_messages
        ]
        for round_messages in messages
    ]


def parity_worker_row(**updates):
    row = {
        "id": RUN_ID,
        "tenant_id": "tenant-a",
        "business_id": "customer-service",
        "workspace_id": "default",
        "conversation_id": CONVERSATION_ID,
        "config": {"fingerprint": "parity-fingerprint"},
        "input": "current question",
        "history": [],
        "summary": None,
    }
    row.update(updates)
    return row


async def run_real_worker_path(
    *,
    enabled: bool,
    model,
    specs=(),
    transport=None,
    row=None,
    memory=None,
    settings_overrides=None,
    factory_builder=None,
    runtime_wrapper=None,
):
    """Run the real RuntimeFactory, RuntimeEngine, and enabled Orchestrator path."""
    overrides = {"execution_orchestrator_enabled": enabled, **(settings_overrides or {})}
    settings = Settings(_env_file=None, **overrides)
    model_call_offset = len(model.seen)
    repository = ParityRepository()
    repository.transient = []

    class Notifier:
        async def send(self, run_id, data):
            repository.transient.append(deepcopy(data))

    async with httpx.AsyncClient(transport=transport) as client:
        engine = RuntimeEngine(model, ToolGateway(client, list(specs)), settings)
        runtime = runtime_wrapper(engine) if runtime_wrapper is not None else engine
        factory = (
            factory_builder(client, settings, engine)
            if factory_builder is not None
            else RuntimeFactory(runtime, RuntimeBindings(), client, settings, engine.tools.limit)
        )
        orchestrator = _OutcomeRecordingOrchestrator(factory) if enabled else None
        worker = RuntimeWorker(
            repository,
            factory,
            settings,
            "parity-fingerprint",
            notifier=Notifier(),
            memory=memory,
            orchestrator=orchestrator,
        )
        actual_row = deepcopy(row) if row is not None else parity_worker_row()
        await worker._execute(actual_row)
    outcome = orchestrator.outcomes[-1] if orchestrator is not None else None
    return repository.capture(
        model_calls=_message_capture(model.seen[model_call_offset:]), outcome=outcome
    )


async def run_real_worker_pair(*, model, specs=(), transport=None, row=None, memory=None, **kwargs):
    off = await run_real_worker_path(
        enabled=False,
        model=model,
        specs=specs,
        transport=transport,
        row=row,
        memory=memory,
        **kwargs,
    )
    on = await run_real_worker_path(
        enabled=True,
        model=model,
        specs=specs,
        transport=transport,
        row=row,
        memory=memory,
        **kwargs,
    )
    return off, on


def assert_real_worker_parity(off, on, *, parallel=False):
    assert off["model_calls"] == on["model_calls"]
    assert canonicalize_parity_capture(off, parallel=parallel) == canonicalize_parity_capture(
        on, parallel=parallel
    )


def _nearest_rank_p95(values: list[float]) -> float:
    if not values:
        raise ValueError("p95 requires samples")
    ordered = sorted(values)
    return ordered[math.ceil(0.95 * len(ordered)) - 1]


async def _performance_old_path(context, worker_emit):
    started = time.perf_counter_ns()
    first_token = None

    async def emit(kind, payload):
        nonlocal first_token
        if first_token is None:
            first_token = (time.perf_counter_ns() - started) / 1_000_000
        await worker_emit(kind, payload)

    await emit("model.delta", {"text": "fixed"})
    outcome = _completed_outcome("fixed")
    return {
        "end_to_end_ms": (time.perf_counter_ns() - started) / 1_000_000,
        "first_token_ms": first_token,
        "adapter_overhead_ms": 0.0,
        "error": None,
        "outcome": outcome,
    }


async def _performance_new_path(context, worker_emit):
    started = time.perf_counter_ns()
    first_token = None

    async def emit(kind, payload):
        nonlocal first_token
        if first_token is None:
            first_token = (time.perf_counter_ns() - started) / 1_000_000
        await worker_emit(kind, payload)

    adapter = _PrivateStubAdapter(
        outcome=_completed_outcome("fixed"),
        events=[_make_event(kind="model.delta")],
    )
    outcome = await ExecutionOrchestrator(_registry(lambda: adapter)).execute(context, emit)
    elapsed = (time.perf_counter_ns() - started) / 1_000_000
    return {
        "end_to_end_ms": elapsed,
        "first_token_ms": first_token,
        "adapter_overhead_ms": elapsed,
        "error": None,
        "outcome": outcome,
    }


async def measure_test_double_performance(*, pairs: int = 30, warmups: int = 5) -> dict:
    """05 section 4 paired sampling; explicitly not production performance evidence."""
    if pairs < 30 or warmups != 5:
        raise ValueError("performance evidence requires five warm-ups and at least 30 pairs")

    async def discard(kind, payload):
        return None

    async def sample(pair: int, warmup: bool) -> dict:
        context = make_context()
        record = {"pair": pair, "warmup": warmup, "order": [], "errors": []}
        paths = (
            (("old", _performance_old_path), ("new", _performance_new_path))
            if pair % 2 == 0
            else (("new", _performance_new_path), ("old", _performance_old_path))
        )
        for name, path in paths:
            record["order"].append(name)
            try:
                record[name] = await path(context, discard)
                outcome = record[name].pop("outcome")
                if outcome.status != "completed" or outcome.output != "fixed":
                    raise AssertionError("fixed performance scenario returned wrong outcome")
            except Exception as exc:  # noqa: BLE001 - retain every measurement failure
                record["errors"].append({"path": name, "type": type(exc).__name__})
                record[name] = {
                    "end_to_end_ms": None,
                    "first_token_ms": None,
                    "adapter_overhead_ms": None,
                    "error": type(exc).__name__,
                }
        old = record["old"]["end_to_end_ms"]
        new = record["new"]["end_to_end_ms"]
        record["paired_delta_ms"] = new - old if old is not None and new is not None else None
        record["paired_ratio"] = new / old if old else None
        record["valid"] = not record["errors"]
        return record

    warmup_samples = [await sample(index, True) for index in range(warmups)]
    measured = [await sample(index, False) for index in range(pairs)]
    valid = [sample for sample in measured if sample["valid"]]
    if len(valid) < 30:
        raise AssertionError("fewer than 30 valid matched pairs")
    old_e2e = [sample["old"]["end_to_end_ms"] for sample in valid]
    new_e2e = [sample["new"]["end_to_end_ms"] for sample in valid]
    old_first = [sample["old"]["first_token_ms"] for sample in valid]
    new_first = [sample["new"]["first_token_ms"] for sample in valid]
    errors = [
        {"pair": sample["pair"], "errors": sample["errors"]}
        for sample in [*warmup_samples, *measured]
        if sample["errors"]
    ]
    return {
        "schema_version": 1,
        "scenario": "fixed-local-test-double",
        "environment": "non-sensitive-local-measurement",
        "evidence_scope": "functional-and-measurement-method-only",
        "production_performance_status": "pending_env",
        "production_target_claimed": False,
        "external_latency_subtracted": False,
        "nearest_rank": "1-based ceil(0.95*N); N=30 selects sorted item 29",
        "warmup_pairs": warmup_samples,
        "samples": measured,
        "summary": {
            "valid_pairs": len(valid),
            "error_count": len(errors),
            "error_rate": len(errors) / (warmups + pairs),
            "old_end_to_end_p95_ms": _nearest_rank_p95(old_e2e),
            "new_end_to_end_p95_ms": _nearest_rank_p95(new_e2e),
            "old_first_token_p95_ms": _nearest_rank_p95(old_first),
            "new_first_token_p95_ms": _nearest_rank_p95(new_first),
            "paired_delta_p95_ms": _nearest_rank_p95(
                [sample["paired_delta_ms"] for sample in valid]
            ),
            "adapter_overhead_p95_ms": _nearest_rank_p95(
                [sample["new"]["adapter_overhead_ms"] for sample in valid]
            ),
            "p95_end_to_end_ratio": _nearest_rank_p95(new_e2e) / _nearest_rank_p95(old_e2e),
        },
        "errors": errors,
    }


@pytest.mark.asyncio
async def test_p2_cm08_performance_sampler_records_raw_pairs_and_pending_environment():
    """P2-CM08/05 section 4: local method evidence never claims the production <=5% target."""
    evidence = await measure_test_double_performance()
    assert len(evidence["warmup_pairs"]) == 5
    assert len(evidence["samples"]) == 30
    assert all(sample["warmup"] for sample in evidence["warmup_pairs"])
    assert all(not sample["warmup"] for sample in evidence["samples"])
    assert all(sample["order"] for sample in evidence["samples"])
    assert evidence["summary"]["valid_pairs"] == 30
    assert evidence["production_performance_status"] == "pending_env"
    assert evidence["production_target_claimed"] is False
    assert evidence["external_latency_subtracted"] is False
    assert _nearest_rank_p95(list(range(1, 31))) == 29
    output = os.environ.get("AGENT_PHASE2_T6A_PERFORMANCE_JSON")
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")


def _require_duration(data: dict[str, object], name: str, *, nullable: bool = False) -> None:
    if name not in data:
        raise ValueError(f"missing {name}")
    value = data[name]
    if value is None and nullable:
        return
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be nonnegative")


def _canonical_event(event: dict[str, object], *, parallel: bool, model_round: int) -> dict:
    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
        raise TypeError("event must have a string type")
    normalized = deepcopy(event)
    for name in ("run_id", "event_id", "timestamp"):
        if name in normalized:
            value = normalized[name]
            if name in {"run_id", "event_id"} and not isinstance(value, (str, UUID)):
                raise TypeError(f"{name} must be a string or UUID")
            if name == "timestamp" and not isinstance(value, (str, datetime)):
                raise TypeError("timestamp must be a string or datetime")
            normalized[name] = f"<{name}>"
    data = normalized.get("data", {})
    if not isinstance(data, dict):
        raise TypeError("event data must be a mapping")
    kind = normalized["type"]
    if kind in {"model.completed", "tool.completed"}:
        if "gateway_call_id" not in data:
            raise ValueError("missing gateway_call_id")
        if data["gateway_call_id"] is not None and not isinstance(data["gateway_call_id"], str):
            raise TypeError("gateway_call_id must be nullable string")
        data["gateway_call_id"] = "<gateway_call_id>"
        _require_duration(data, "duration_ms")
        data["duration_ms"] = 0
    if kind == "model.completed":
        _require_duration(data, "first_token_ms", nullable=True)
        data["first_token_ms"] = 0 if data["first_token_ms"] is not None else None
    if parallel:
        normalized["_model_round"] = model_round
        if kind.startswith("tool.") or not kind.startswith("model."):
            normalized["seq"] = "<parallel-sequence>"
    return normalized


def _canonical_sort_key(event: dict[str, object]) -> str:
    return json.dumps(event, sort_keys=True, default=str, separators=(",", ":"))


def _canonical_parallel_events(events: list[dict[str, object]]) -> list[dict[str, object]]:
    output = []
    pending = []
    model_round = 0
    started = set()
    completed = set()

    def flush() -> None:
        nonlocal pending, started, completed
        for event in pending:
            if event["type"] == "tool.started":
                call_id = event["data"].get("call_id")
                if not isinstance(call_id, str) or not call_id:
                    raise ValueError("parallel tool.started requires call_id")
                if call_id in started:
                    raise ValueError("duplicate tool.started call_id")
                started.add(call_id)
            elif event["type"] == "tool.completed":
                call_id = event["data"].get("call_id")
                if call_id not in started:
                    raise ValueError("tool.completed before tool.started")
                if call_id in completed:
                    raise ValueError("duplicate tool.completed call_id")
                completed.add(call_id)
        if started != completed:
            missing = started - completed
            extra = completed - started
            raise ValueError(f"tool calls must be started and completed: {missing or extra}")
        output.extend(sorted(pending, key=_canonical_sort_key))
        pending = []
        started = set()
        completed = set()

    for original in events:
        kind = original.get("type") if isinstance(original, dict) else None
        if kind == "model.started":
            flush()
            data = original.get("data", {})
            if type(data.get("round")) is not int or data["round"] < 1:
                raise ValueError("model.started requires a positive round")
            model_round = data["round"]
        event = _canonical_event(original, parallel=True, model_round=model_round)
        if kind in {"model.started", "model.completed"}:
            flush()
            output.append(event)
        else:
            pending.append(event)
    flush()
    return output


def canonicalize_parity_capture(capture: dict[str, object], *, parallel: bool = False) -> dict:
    """Canonicalize only 03 section 7.3 instance/timing fields for parity assertions."""
    normalized = deepcopy(capture)
    for name in ("run_id", "event_id", "timestamp", "owner", "started_at", "finished_at"):
        if name in normalized:
            value = normalized[name]
            if name in {"run_id", "event_id", "owner"} and not isinstance(value, (str, UUID)):
                raise TypeError(f"{name} must be a string or UUID")
            if name in {"timestamp", "started_at", "finished_at"} and not isinstance(
                value, (str, datetime)
            ):
                raise TypeError(f"{name} must be a string or datetime")
            normalized[name] = f"<{name}>"
    events = normalized.get("events", [])
    if not isinstance(events, list):
        raise TypeError("events must be a list")
    if parallel:
        normalized["events"] = _canonical_parallel_events(events)
    else:
        normalized["events"] = [
            _canonical_event(event, parallel=False, model_round=0) for event in events
        ]
    for key in ("terminal",):
        if normalized.get(key) is not None:
            normalized[key] = _canonical_event(normalized[key], parallel=False, model_round=0)
    replay = normalized.get("replay", [])
    if not isinstance(replay, list):
        raise TypeError("replay must be a list")
    if parallel and replay and replay[-1].get("type", "").startswith("run."):
        normalized["replay"] = [
            *_canonical_parallel_events(replay[:-1]),
            _canonical_event(replay[-1], parallel=False, model_round=0),
        ]
    else:
        normalized["replay"] = [
            _canonical_event(event, parallel=False, model_round=0) for event in replay
        ]
    # Raw timings are retained in the original capture/performance JSON, never diffed.
    normalized.pop("raw_latency", None)
    return normalized


# P2-UT22: the only timing/identity normalization permitted by 03 section 7.3.
def _parity_capture(events=None):
    return {
        "run_id": RUN_ID,
        "event_id": "run-instance-a",
        "timestamp": "2026-01-01T00:00:00Z",
        "output": "answer",
        "error_code": None,
        "usage": {"input_tokens": 3, "output_tokens": 2},
        "history": [{"role": "assistant", "content": "answer"}],
        "dropped": [],
        "events": list(events or []),
        "terminal": {"seq": 9, "type": "run.completed", "data": {"output": "answer"}},
        "replay": [{"seq": 1, "type": "model.started", "data": {"round": 1}}],
    }


def _model_completed(**updates):
    data = {
        "round": 1,
        "usage": {"input_tokens": 3},
        "gateway_call_id": "gateway-a",
        "first_token_ms": 2,
        "duration_ms": 8,
    }
    data.update(updates)
    return {
        "run_id": RUN_ID,
        "event_id": "event-a",
        "timestamp": "time-a",
        "seq": 2,
        "type": "model.completed",
        "data": data,
    }


def _tool_event(kind, call_id, **updates):
    data = {"name": "lookup", "call_id": call_id}
    if kind == "tool.completed":
        data.update(
            {
                "ok": True,
                "error": None,
                "gateway_call_id": f"gateway-{call_id}",
                "duration_ms": 5,
                "result": {"document_id": "business-document-a"},
            }
        )
    data.update(updates)
    return {"seq": 3, "type": kind, "data": data}


def test_p2_ut22_serial_canonicalizer_normalizes_only_documented_instance_fields():
    left = _parity_capture([_model_completed()])
    right = deepcopy(left)
    right.update(run_id=OTHER_RUN_ID, event_id="run-instance-b", timestamp="time-b")
    right["events"][0].update(run_id=OTHER_RUN_ID, event_id="event-b", timestamp="time-b", seq=2)
    right["events"][0]["data"].update(gateway_call_id="gateway-b", first_token_ms=9, duration_ms=19)

    assert canonicalize_parity_capture(left) == canonicalize_parity_capture(right)
    assert left["run_id"] == RUN_ID
    assert left["events"][0]["data"]["gateway_call_id"] == "gateway-a"


@pytest.mark.parametrize(
    "path,value",
    [
        (
            ("model_calls", 0),
            [
                {"type": "system", "content": "original prompt", "additional_kwargs": {}},
                {
                    "type": "human",
                    "content": "original content",
                    "additional_kwargs": {"business_id": "business-a"},
                },
                {"type": "ai", "content": "extra message", "additional_kwargs": {}},
            ],
        ),
        (("model_calls", 0, 0, "content"), "different prompt"),
        (("model_calls", 0, 1, "content"), "different content"),
        (("model_calls", 0, 1, "additional_kwargs", "business_id"), "business-b"),
    ],
)
def test_p2_ut22_model_call_messages_prompt_content_and_business_remain_diffs(path, value):
    left = _parity_capture()
    left["model_calls"] = [
        [
            {"type": "system", "content": "original prompt", "additional_kwargs": {}},
            {
                "type": "human",
                "content": "original content",
                "additional_kwargs": {"business_id": "business-a"},
            },
        ]
    ]
    right = deepcopy(left)
    target = right
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    assert canonicalize_parity_capture(left) != canonicalize_parity_capture(right)


@pytest.mark.parametrize(
    "path,value",
    [
        (("output",), "different answer"),
        (("error_code",), "provider_error"),
        (("usage", "input_tokens"), 99),
        (("history", 0, "content"), "different history"),
        (("dropped",), [{"role": "user", "content": "not dropped"}]),
        (("terminal", "data", "output"), "different terminal"),
        (("replay", 0, "seq"), 7),
        (("events", 0, "seq"), 8),
        (("events", 0, "data", "usage", "input_tokens"), 99),
    ],
)
def test_p2_ut22_serial_business_order_sequence_usage_and_replay_remain_diffs(path, value):
    left = _parity_capture([_model_completed()])
    right = deepcopy(left)
    target = right
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    assert canonicalize_parity_capture(left) != canonicalize_parity_capture(right)


@pytest.mark.parametrize(
    "path,value",
    [
        (("events", 0, "data", "duration_ms"), -1),
        (("events", 0, "data", "first_token_ms"), -1),
        (("events", 0, "data", "duration_ms"), "8"),
        (("events", 0, "data", "first_token_ms"), False),
        (("events", 0, "data", "gateway_call_id"), 42),
        (("events", 0, "event_id"), 42),
        (("events", 0, "run_id"), 42),
        (("events", 0, "timestamp"), 42),
    ],
)
def test_p2_ut22_rejects_wrong_types_and_negative_durations_before_normalizing(path, value):
    capture = _parity_capture([_model_completed()])
    target = capture
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises((TypeError, ValueError)):
        canonicalize_parity_capture(capture)


@pytest.mark.parametrize("missing", ["gateway_call_id", "first_token_ms", "duration_ms"])
def test_p2_ut22_rejects_missing_model_timing_fields(missing):
    capture = _parity_capture([_model_completed()])
    del capture["events"][0]["data"][missing]
    with pytest.raises(ValueError, match=missing):
        canonicalize_parity_capture(capture)


def test_p2_ut22_parallel_tools_compare_by_call_id_and_preserve_model_rounds():
    first = _parity_capture(
        [
            {"seq": 1, "type": "model.started", "data": {"round": 1}},
            _model_completed(tool_calls=2),
            _tool_event("tool.started", "call-a"),
            _tool_event("tool.started", "call-b"),
            _tool_event("tool.completed", "call-b"),
            _tool_event("tool.completed", "call-a"),
        ]
    )
    reordered = deepcopy(first)
    reordered["events"][2:] = [
        _tool_event("tool.started", "call-b"),
        _tool_event("tool.completed", "call-b"),
        _tool_event("tool.started", "call-a"),
        _tool_event("tool.completed", "call-a"),
    ]
    assert canonicalize_parity_capture(first, parallel=True) == canonicalize_parity_capture(
        reordered, parallel=True
    )

    changed_id = deepcopy(reordered)
    changed_id["events"][-2]["data"]["call_id"] = "business-call-changed"
    changed_id["events"][-1]["data"]["call_id"] = "business-call-changed"
    assert canonicalize_parity_capture(first, parallel=True) != canonicalize_parity_capture(
        changed_id, parallel=True
    )

    changed_document = deepcopy(reordered)
    changed_document["events"][-1]["data"]["result"]["document_id"] = "business-document-b"
    assert canonicalize_parity_capture(first, parallel=True) != canonicalize_parity_capture(
        changed_document, parallel=True
    )


def test_p2_ut22_parallel_rejects_completion_before_start_and_round_movement():
    capture = _parity_capture(
        [
            {"seq": 1, "type": "model.started", "data": {"round": 1}},
            _tool_event("tool.completed", "call-a"),
            _tool_event("tool.started", "call-a"),
        ]
    )
    with pytest.raises(ValueError, match="before"):
        canonicalize_parity_capture(capture, parallel=True)

    missing_start = _parity_capture([_tool_event("tool.completed", "call-a")])
    with pytest.raises(ValueError, match="started"):
        canonicalize_parity_capture(missing_start, parallel=True)


def test_p2_ut22_unowned_parallel_events_are_per_round_multisets_not_global():
    left = _parity_capture(
        [
            {"seq": 1, "type": "model.started", "data": {"round": 1}},
            {"seq": 2, "type": "business.progress", "data": {"value": "a"}},
            {"seq": 3, "type": "business.progress", "data": {"value": "a"}},
            {"seq": 4, "type": "model.completed", "data": _model_completed()["data"]},
            {"seq": 5, "type": "model.started", "data": {"round": 2}},
            {"seq": 6, "type": "business.progress", "data": {"value": "b"}},
        ]
    )
    same = deepcopy(left)
    same["events"][1:3] = reversed(same["events"][1:3])
    assert canonicalize_parity_capture(left, parallel=True) == canonicalize_parity_capture(
        same, parallel=True
    )

    moved = deepcopy(left)
    moved["events"].append(moved["events"].pop(1))
    assert canonicalize_parity_capture(left, parallel=True) != canonicalize_parity_capture(
        moved, parallel=True
    )

    changed = deepcopy(left)
    changed["events"][1]["data"]["value"] = "b"
    assert canonicalize_parity_capture(left, parallel=True) != canonicalize_parity_capture(
        changed, parallel=True
    )
