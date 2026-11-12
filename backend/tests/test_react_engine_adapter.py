import asyncio
import inspect
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from agent_execution.adapter_contract_suite import AdapterContractSuite

from agent_platform.core_platform.agent_execution.adapters.react import ReactAdapter
from agent_platform.core_platform.agent_execution.adapters.react.adapter import _Execution
from agent_platform.core_platform.agent_execution.adapters.react.error_mapper import (
    ReactErrorMapping,
    map_execution_error,
    map_protocol_error,
)
from agent_platform.core_platform.agent_execution.contracts import (
    AdapterExecutionError,
    AgentEngineAdapter,
    AgentEvent,
    ConfigurationError,
    EngineCapabilities,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionHandle,
    ExecutionRequest,
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
    ExecutionOutcome,
    as_acknowledging_event_stream,
    as_outcome_collecting_adapter,
)
from agent_platform.core_platform.agent_runtime.schemas import RuntimeFault

SENSITIVE_DIAGNOSTIC = "provider-raw-" + "diagnostic"

INVALID_REQUEST = (ExecutionErrorCategory.CONFIGURATION_ERROR, ExecutionErrorCode.INVALID_REQUEST)
RESOURCE_EXHAUSTED = (
    ExecutionErrorCategory.RESOURCE_EXHAUSTED,
    ExecutionErrorCode.RESOURCE_EXHAUSTED,
)
PROTOCOL_ERROR = (ExecutionErrorCategory.PROTOCOL_ERROR, ExecutionErrorCode.PROTOCOL_ERROR)
ENGINE_UNAVAILABLE = (
    ExecutionErrorCategory.ENGINE_UNAVAILABLE,
    ExecutionErrorCode.ENGINE_UNAVAILABLE,
)
PERMISSION_DENIED = (ExecutionErrorCategory.PERMISSION_DENIED, ExecutionErrorCode.PERMISSION_DENIED)
AUTHENTICATION_FAILED = (
    ExecutionErrorCategory.AUTHENTICATION_ERROR,
    ExecutionErrorCode.AUTHENTICATION_FAILED,
)
TIMEOUT = (ExecutionErrorCategory.TIMEOUT, ExecutionErrorCode.EXECUTION_TIMEOUT)
INTERNAL_ERROR = (ExecutionErrorCategory.INTERNAL_ERROR, ExecutionErrorCode.INTERNAL_ERROR)

ERROR_MATRIX = [
    *(("agent_model_required", INVALID_REQUEST), ("configuration_changed", INVALID_REQUEST)),
    ("model_resource_not_found", INVALID_REQUEST),
    ("model_resource_disabled", INVALID_REQUEST),
    ("model_profile_version_not_found", INVALID_REQUEST),
    ("model_input_too_large", RESOURCE_EXHAUSTED),
    ("model_tools_not_supported", INVALID_REQUEST),
    ("invalid_model_response", PROTOCOL_ERROR),
    ("empty_model_response", PROTOCOL_ERROR),
    ("duplicate_tool_call_id", PROTOCOL_ERROR),
    ("repeated_tool_call", PROTOCOL_ERROR),
    ("model_round_limit", RESOURCE_EXHAUSTED),
    ("tool_call_limit", RESOURCE_EXHAUSTED),
    ("model_output_too_large", RESOURCE_EXHAUSTED),
    ("model_provider_unavailable", ENGINE_UNAVAILABLE),
    ("model_rate_limited", ENGINE_UNAVAILABLE),
    ("model_provider_rejected", ENGINE_UNAVAILABLE),
    ("model_transport_error", ENGINE_UNAVAILABLE),
    ("content_blocked_input", PERMISSION_DENIED),
    ("content_blocked_output", PERMISSION_DENIED),
    ("gateway_concurrency_exceeded", RESOURCE_EXHAUSTED),
    ("gateway_request_quota_exceeded", RESOURCE_EXHAUSTED),
    ("model_credential_unavailable", AUTHENTICATION_FAILED),
    ("model_response_too_large", RESOURCE_EXHAUSTED),
    ("model_stream_interrupted", ENGINE_UNAVAILABLE),
    ("model_timeout", TIMEOUT),
    ("model_not_configured", INVALID_REQUEST),
]


@pytest.mark.parametrize("legacy_code,expected", ERROR_MATRIX)
def test_phase_zero_runtime_fault_matrix_preserves_legacy_and_maps_safe_public_error(
    legacy_code: str,
    expected: tuple[ExecutionErrorCategory, ExecutionErrorCode],
):
    fault = RuntimeFault(legacy_code)
    fault.add_note(SENSITIVE_DIAGNOSTIC)

    mapped = map_execution_error(fault)

    category, code = expected
    assert mapped.legacy_error_code == legacy_code
    assert mapped.error.category is category
    assert mapped.error.code is code
    assert mapped.error.message == ExecutionError(category=category, code=code).message
    public_dump = mapped.error.model_dump()
    public_json = mapped.error.model_dump_json()
    assert public_dump["message"] == mapped.error.message
    assert SENSITIVE_DIAGNOSTIC not in public_json
    assert str(fault) not in public_json
    assert mapped.error.retryable is False


def test_outer_timeout_is_run_timeout_not_model_timeout():
    mapped = map_execution_error(TimeoutError(SENSITIVE_DIAGNOSTIC))
    assert mapped.legacy_error_code == "run_timeout"
    assert mapped.error.category is ExecutionErrorCategory.TIMEOUT
    assert mapped.error.code is ExecutionErrorCode.EXECUTION_TIMEOUT
    assert mapped.legacy_error_code != "model_timeout"
    assert SENSITIVE_DIAGNOSTIC not in mapped.error.model_dump_json()


def test_model_timeout_runtime_fault_remains_distinct_from_outer_run_timeout():
    mapped = map_execution_error(RuntimeFault("model_timeout"))
    assert mapped.legacy_error_code == "model_timeout"
    assert mapped.error.code is ExecutionErrorCode.EXECUTION_TIMEOUT


def test_future_unknown_runtime_fault_uses_safe_fallback_and_verbatim_private_code():
    future_code = "future_provider_" + "private_detail"
    mapped = map_execution_error(RuntimeFault(future_code))
    assert mapped.legacy_error_code == future_code
    assert mapped.error.category is ExecutionErrorCategory.INTERNAL_ERROR
    assert mapped.error.code is ExecutionErrorCode.INTERNAL_ERROR
    assert future_code not in mapped.error.model_dump_json()
    assert mapped.error.message == "Execution failed internally."


def test_model_stream_not_supported_has_safe_fallback_without_losing_legacy_code():
    mapped = map_execution_error(RuntimeFault("model_stream_not_supported"))
    assert mapped.legacy_error_code == "model_stream_not_supported"
    assert mapped.error.category is ExecutionErrorCategory.INTERNAL_ERROR
    assert mapped.error.code is ExecutionErrorCode.INTERNAL_ERROR


def test_unknown_regular_exception_is_safe_execution_error():
    mapped = map_execution_error(RuntimeError(SENSITIVE_DIAGNOSTIC))
    assert mapped.legacy_error_code == "execution_error"
    assert mapped.error.category is ExecutionErrorCategory.INTERNAL_ERROR
    assert mapped.error.code is ExecutionErrorCode.INTERNAL_ERROR
    assert SENSITIVE_DIAGNOSTIC not in mapped.error.model_dump_json()
    assert SENSITIVE_DIAGNOSTIC not in str(mapped.error)


def assert_safe_execution_error(mapped: ReactErrorMapping) -> None:
    assert mapped.legacy_error_code == "execution_error"
    assert mapped.error.category is ExecutionErrorCategory.INTERNAL_ERROR
    assert mapped.error.code is ExecutionErrorCode.INTERNAL_ERROR
    assert SENSITIVE_DIAGNOSTIC not in mapped.error.model_dump_json()
    assert SENSITIVE_DIAGNOSTIC not in str(mapped.error)


def test_runtime_fault_subclass_uses_real_class_identity():
    class DerivedRuntimeFault(RuntimeFault):
        pass

    mapped = map_execution_error(DerivedRuntimeFault("model_timeout"))
    assert mapped.legacy_error_code == "model_timeout"
    assert mapped.error.code is ExecutionErrorCode.EXECUTION_TIMEOUT


def test_same_module_and_name_fake_runtime_fault_is_not_trusted():
    class FakeRuntimeFault(Exception):
        code = SENSITIVE_DIAGNOSTIC

    FakeRuntimeFault.__name__ = RuntimeFault.__name__
    FakeRuntimeFault.__module__ = RuntimeFault.__module__

    assert_safe_execution_error(map_execution_error(FakeRuntimeFault(SENSITIVE_DIAGNOSTIC)))


def test_runtime_fault_code_property_failure_is_safe_and_does_not_leak():
    class ExplodingCodeRuntimeFault(RuntimeFault):
        def __init__(self) -> None:
            Exception.__init__(self, SENSITIVE_DIAGNOSTIC)

        @property
        def code(self) -> str:
            raise RuntimeError(SENSITIVE_DIAGNOSTIC)

    assert_safe_execution_error(map_execution_error(ExplodingCodeRuntimeFault()))


def test_runtime_fault_code_subclass_failure_is_safe_and_does_not_leak():
    class ExplodingCode(str):
        def __bool__(self) -> bool:
            raise RuntimeError(SENSITIVE_DIAGNOSTIC)

    class SubclassCodeRuntimeFault(RuntimeFault):
        def __init__(self) -> None:
            Exception.__init__(self, SENSITIVE_DIAGNOSTIC)
            self.code = ExplodingCode("model_timeout")

    assert_safe_execution_error(map_execution_error(SubclassCodeRuntimeFault()))


def test_runtime_fault_mro_failure_is_safe_and_does_not_leak():
    class ExplodingMROMeta(type):
        @property
        def __mro__(cls) -> tuple[type, ...]:
            raise RuntimeError(SENSITIVE_DIAGNOSTIC)

    class ExplodingMROException(Exception, metaclass=ExplodingMROMeta):
        code = SENSITIVE_DIAGNOSTIC

    assert_safe_execution_error(map_execution_error(ExplodingMROException(SENSITIVE_DIAGNOSTIC)))


@pytest.mark.parametrize("control_flow", [asyncio.CancelledError(), KeyboardInterrupt()])
def test_code_property_control_flow_is_not_swallowed(control_flow: BaseException):
    class ControlFlowCodeRuntimeFault(RuntimeFault):
        def __init__(self) -> None:
            Exception.__init__(self)

        @property
        def code(self) -> str:
            raise control_flow

    with pytest.raises(type(control_flow)) as caught:
        map_execution_error(ControlFlowCodeRuntimeFault())
    assert caught.value is control_flow


def test_protocol_failure_is_safe_and_defaults_to_execution_error():
    mapped = map_protocol_error()
    assert mapped.legacy_error_code == "execution_error"
    assert mapped.error.category is ExecutionErrorCategory.PROTOCOL_ERROR
    assert mapped.error.code is ExecutionErrorCode.PROTOCOL_ERROR


def test_protocol_failure_preserves_an_explicit_legacy_code():
    mapped = map_protocol_error(legacy_error_code="model_protocol_identity")
    assert mapped.legacy_error_code == "model_protocol_identity"
    assert mapped.error.code is ExecutionErrorCode.PROTOCOL_ERROR
    assert "model_protocol_identity" not in mapped.error.model_dump_json()


def test_existing_safe_adapter_error_is_preserved_without_exception_chain_or_raw_text():
    safe = ExecutionError(
        category=ExecutionErrorCategory.PROTOCOL_ERROR,
        code=ExecutionErrorCode.PROTOCOL_ERROR,
    )
    try:
        raise RuntimeError(SENSITIVE_DIAGNOSTIC)
    except RuntimeError as raw:
        exception = AdapterExecutionError(safe)
        exception.__cause__ = raw
        exception.__context__ = raw

    mapped = map_execution_error(exception, legacy_error_code="event_identity")
    assert mapped.error is safe
    assert mapped.legacy_error_code == "event_identity"
    assert SENSITIVE_DIAGNOSTIC not in mapped.error.model_dump_json()


@pytest.mark.parametrize(
    "exception",
    [asyncio.CancelledError(), KeyboardInterrupt(), SystemExit(), GeneratorExit()],
)
def test_control_flow_is_never_mapped_to_regular_failure(exception: BaseException):
    with pytest.raises(type(exception)) as caught:
        map_execution_error(exception)
    assert caught.value is exception


@pytest.mark.parametrize(
    "failure,expected_code,expected_legacy",
    [
        (
            RuntimeFault("model_provider_unavailable"),
            ExecutionErrorCode.ENGINE_UNAVAILABLE,
            "model_provider_unavailable",
        ),
        (
            RuntimeFault("invalid_model_response"),
            ExecutionErrorCode.PROTOCOL_ERROR,
            "invalid_model_response",
        ),
        (TimeoutError(SENSITIVE_DIAGNOSTIC), ExecutionErrorCode.EXECUTION_TIMEOUT, "run_timeout"),
        (
            AdapterExecutionError(
                ExecutionError(
                    category=ExecutionErrorCategory.PROTOCOL_ERROR,
                    code=ExecutionErrorCode.PROTOCOL_ERROR,
                )
            ),
            ExecutionErrorCode.PROTOCOL_ERROR,
            "execution_error",
        ),
    ],
)
def test_nested_single_exception_group_preserves_original_runtime_mapping(
    failure, expected_code, expected_legacy
):
    grouped = ExceptionGroup(
        SENSITIVE_DIAGNOSTIC,
        [ExceptionGroup(SENSITIVE_DIAGNOSTIC, [failure])],
    )

    mapped = map_execution_error(grouped)

    assert mapped.error.code is expected_code
    assert mapped.legacy_error_code == expected_legacy
    assert SENSITIVE_DIAGNOSTIC not in mapped.error.model_dump_json()


def test_same_leaf_mapping_in_multi_exception_group_is_stable():
    grouped = ExceptionGroup(
        SENSITIVE_DIAGNOSTIC,
        [
            RuntimeFault("model_timeout"),
            ExceptionGroup(SENSITIVE_DIAGNOSTIC, [RuntimeFault("model_timeout")]),
        ],
    )

    mapped = map_execution_error(grouped)

    assert mapped.error.code is ExecutionErrorCode.EXECUTION_TIMEOUT
    assert mapped.legacy_error_code == "model_timeout"


def test_mixed_leaf_mapping_in_multi_exception_group_uses_safe_fallback():
    grouped = ExceptionGroup(
        SENSITIVE_DIAGNOSTIC,
        [RuntimeFault("model_timeout"), RuntimeFault("model_provider_unavailable")],
    )

    mapped = map_execution_error(grouped)

    assert mapped.error.code is ExecutionErrorCode.INTERNAL_ERROR
    assert mapped.legacy_error_code == "execution_error"
    assert SENSITIVE_DIAGNOSTIC not in mapped.error.model_dump_json()


def test_same_public_code_but_different_legacy_codes_also_use_safe_fallback():
    grouped = ExceptionGroup(
        SENSITIVE_DIAGNOSTIC,
        [RuntimeFault("future_private_a"), RuntimeFault("future_private_b")],
    )

    mapped = map_execution_error(grouped)

    assert mapped.error.code is ExecutionErrorCode.INTERNAL_ERROR
    assert mapped.legacy_error_code == "execution_error"
    assert "future_private" not in mapped.error.model_dump_json()


@pytest.mark.parametrize(
    "control_flow", [asyncio.CancelledError(), KeyboardInterrupt(), SystemExit()]
)
def test_exception_group_never_swallows_nested_control_flow(control_flow: BaseException):
    grouped = BaseExceptionGroup(
        SENSITIVE_DIAGNOSTIC,
        [ExceptionGroup(SENSITIVE_DIAGNOSTIC, [RuntimeFault("model_timeout")]), control_flow],
    )
    with pytest.raises(BaseExceptionGroup) as caught:
        map_execution_error(grouped)
    assert caught.value is grouped


# T3 runtime doubles are test-only: the production adapter sees neither worker_emit nor
# any repository/notifier. Every public-suite stream is wrapped with explicit delivery.
REACT_RUN_ID = UUID("50000000-0000-4000-8000-000000000001")
REACT_AGENT_ID = UUID("50000000-0000-4000-8000-000000000002")
REACT_OTHER_RUN_ID = UUID("50000000-0000-4000-8000-000000000003")


@dataclass(frozen=True)
class _ReactEventSpec:
    kind: str = "engine.output_delta"
    payload: object = field(default_factory=dict)
    gate: asyncio.Event | None = field(default=None, compare=False, repr=False)


class _ReactManualClock:
    def __init__(self) -> None:
        self.expired = asyncio.Event()

    def advance(self, seconds: int) -> None:
        assert seconds > 0
        self.expired.set()


class _HostileCodeRuntimeFault(RuntimeFault):
    def __init__(self, control_flow: BaseException) -> None:
        Exception.__init__(self, SENSITIVE_DIAGNOSTIC)
        self._control_flow = control_flow

    @property
    def code(self) -> str:
        raise self._control_flow


@dataclass
class _ReactScenario:
    events: tuple[_ReactEventSpec, ...] = ()
    output: str | None = "scripted output"
    history: list[dict[str, object]] = field(
        default_factory=lambda: [{"role": "assistant", "content": "scripted output"}]
    )
    dropped: list[dict[str, object]] = field(default_factory=list)
    capabilities: EngineCapabilities | None = None
    usage: dict[str, object] = field(default_factory=dict)
    artifacts: tuple[dict[str, object], ...] = ()
    engine_metadata: dict[str, object] = field(default_factory=dict)
    completion_gate: asyncio.Event | None = None
    stream_error: ExecutionError | BaseException | None = None
    task_group_errors: tuple[BaseException, ...] = ()
    prestart_error: ExecutionError | Exception | None = None
    manual_timeout: bool = False
    queue_capacity: int = 1
    worker_error: BaseException | None = None
    worker_gate: asyncio.Event | None = None
    clock: _ReactManualClock = field(default_factory=_ReactManualClock)

    def __post_init__(self) -> None:
        self.runtime_emissions: list[tuple[object, object]] = []
        self.worker_emissions: list[tuple[str, dict[str, object]]] = []
        self.acknowledgements: list[AgentEvent] = []
        self.order: list[str] = []
        self.factory_entered = asyncio.Event()
        self.runtime_entered = asyncio.Event()


class _ScriptedRuntime:
    def __init__(self, scenario: _ReactScenario) -> None:
        self.scenario = scenario
        self.calls: list[tuple[object, ...]] = []

    async def run(
        self,
        message: object,
        history: object,
        emit: object,
        *,
        summary_message: object = None,
        customer_memory: object = None,
    ) -> tuple[str | None, list[dict[str, object]], list[dict[str, object]]]:
        self.calls.append((message, history, emit, summary_message, customer_memory))
        self.scenario.runtime_entered.set()
        for spec in self.scenario.events:
            if spec.gate is not None:
                await spec.gate.wait()
            self.scenario.runtime_emissions.append((spec.kind, spec.payload))
            self.scenario.order.append(f"runtime:{spec.kind}")
            await emit(spec.kind, spec.payload)  # type: ignore[operator]
        if self.scenario.manual_timeout:
            await self.scenario.clock.expired.wait()
            raise TimeoutError(SENSITIVE_DIAGNOSTIC)
        if self.scenario.completion_gate is not None:
            await self.scenario.completion_gate.wait()
        if self.scenario.task_group_errors:
            async with asyncio.TaskGroup() as task_group:
                for task_error in self.scenario.task_group_errors:

                    async def fail(error: BaseException = task_error) -> None:
                        raise error

                    task_group.create_task(fail())
        if self.scenario.stream_error is not None:
            error = self.scenario.stream_error
            if isinstance(error, ExecutionError):
                error_type = (
                    ConfigurationError
                    if error.category is ExecutionErrorCategory.CONFIGURATION_ERROR
                    else AdapterExecutionError
                )
                raise error_type(error)
            raise error
        return self.scenario.output, self.scenario.history, self.scenario.dropped


class _ScriptedRuntimeFactory:
    def __init__(self, scenario: _ReactScenario) -> None:
        self.scenario = scenario
        self.runtime = _ScriptedRuntime(scenario)
        self.calls: list[tuple[object, object]] = []

    async def for_run(self, row: object, emit: object) -> _ScriptedRuntime:
        self.calls.append((row, emit))
        self.scenario.factory_entered.set()
        if self.scenario.prestart_error is not None:
            error = self.scenario.prestart_error
            if isinstance(error, ExecutionError):
                raise AdapterExecutionError(error)
            raise error
        return self.runtime


class _ReactTestAdapter:
    def __init__(self, scenario: _ReactScenario, context: ExecutionContext) -> None:
        self.scenario = scenario
        self.context = context
        self.factory = _ScriptedRuntimeFactory(scenario)
        self.raw = ReactAdapter(context, self.factory, queue_capacity=scenario.queue_capacity)

    @property
    def engine_id(self) -> str:
        return self.raw.engine_id

    @property
    def protocol_id(self) -> str:
        return self.raw.protocol_id

    @property
    def adapter_version(self) -> str:
        return self.raw.adapter_version

    @property
    def _execution(self) -> object:
        return self.raw._execution

    @property
    def _owned_tasks(self) -> set[asyncio.Task[Any]]:
        return self.raw._owned_tasks

    async def get_capabilities(self) -> EngineCapabilities:
        return await self.raw.get_capabilities()

    async def start(self, request: ExecutionRequest) -> ExecutionHandle:
        return await self.raw.start(request)

    def stream_events(self, handle: ExecutionHandle) -> AsyncIterator[AgentEvent]:
        return self.raw.stream_events(handle)

    async def cancel(self, handle: ExecutionHandle) -> None:
        await self.raw.cancel(handle)

    async def collect_result(self, handle: ExecutionHandle) -> ExecutionResult:
        return await self.raw.collect_result(handle)


class _WorkerEmitStream:
    """The exact Orchestrator-shaped harness required by the frozen T3 design."""

    def __init__(self, raw: Any, scenario: _ReactScenario) -> None:
        self.raw = raw
        self.scenario = scenario

    def __aiter__(self) -> "_WorkerEmitStream":
        return self

    async def __anext__(self) -> AgentEvent:
        event = await anext(self.raw)
        self.scenario.order.append(f"yield:{event.event_type}")
        try:
            if self.scenario.worker_gate is not None:
                await self.scenario.worker_gate.wait()
            if self.scenario.worker_error is not None:
                raise self.scenario.worker_error
            payload = dict(event.payload)
            self.scenario.worker_emissions.append((event.event_type, payload))
            self.scenario.order.append(f"worker:{event.event_type}")
        except BaseException as error:
            await self.raw.abort(error)
            raise
        await self.raw.acknowledge(event)
        self.scenario.acknowledgements.append(event)
        self.scenario.order.append(f"ack:{event.event_type}")
        return event

    async def acknowledge(self, event: AgentEvent) -> None:
        await self.raw.acknowledge(event)

    async def abort(self, error: BaseException) -> None:
        await self.raw.abort(error)

    async def aclose(self) -> None:
        await self.raw.aclose()


def _react_context(run_id: UUID = REACT_RUN_ID) -> ExecutionContext:
    row: dict[str, object] = {
        "id": run_id,
        "tenant_id": "tenant-1",
        "conversation_id": None,
        "input": "input",
        "config": {"agent": {"id": REACT_AGENT_ID}},
        "engine_session_id": None,
        "workspace_id": None,
        "execution_workdir": None,
    }
    return build_execution_context(
        row,
        history=[{"role": "user", "content": "history"}],
        summary_message="summary",
        customer_memory="memory",
        trace_id=None,
        timeout_seconds=None,
    )


async def _wait_for_condition(condition: Any) -> None:
    async def poll() -> None:
        while not condition():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=0.5)


class TestReactAdapter(AdapterContractSuite):
    __test__ = True

    def make_scenario(self, **controls: Any) -> _ReactScenario:
        return _ReactScenario(**controls)

    def make_event_spec(self, **controls: Any) -> _ReactEventSpec:
        if "event_type" in controls:
            controls["kind"] = controls.pop("event_type")
        # External event envelope controls are deliberately not part of React raw input.
        controls.pop("sequence", None)
        controls.pop("trace_id", None)
        controls.pop("source", None)
        return _ReactEventSpec(**controls)

    def make_gate(self) -> asyncio.Event:
        return asyncio.Event()

    def build_adapter(self, scenario: object) -> _ReactTestAdapter:
        assert isinstance(scenario, _ReactScenario)
        self._latest = _ReactTestAdapter(scenario, _react_context())
        return self._latest

    def make_request(self, **overrides: Any) -> ExecutionRequest:
        context = self._latest.context
        row = cast(dict[str, object], context.row)
        for key in ("tenant_id", "input", "engine_session_id", "workspace_id", "execution_workdir"):
            if key in overrides:
                row[key] = overrides[key]
        for key in ("trace_id", "timeout_seconds"):
            if key in overrides:
                object.__setattr__(context, key, overrides[key])
        data: dict[str, Any] = {
            "execution_id": context.execution_id,
            "engine_id": "react",
            "protocol_id": "native",
            "adapter_version": "v1",
            "tenant_id": row["tenant_id"],
            "agent_id": REACT_AGENT_ID,
            "conversation_id": row["conversation_id"],
            "input": row["input"],
            "engine_session_id": row["engine_session_id"],
            "workspace_id": row["workspace_id"],
            "execution_workdir": row["execution_workdir"],
            "trace_id": context.trace_id,
            "timeout_seconds": context.timeout_seconds,
        }
        data.update(overrides)
        return ExecutionRequest(**data)

    def stream(
        self, adapter: AgentEngineAdapter, handle: ExecutionHandle
    ) -> AsyncIterator[AgentEvent]:
        assert isinstance(adapter, _ReactTestAdapter)
        raw = adapter.stream_events(handle)
        acknowledging = as_acknowledging_event_stream(raw)
        assert acknowledging is not None
        wrapped = _WorkerEmitStream(acknowledging, adapter.scenario)
        self._streams.append(wrapped)
        return wrapped

    def advance_clock(self, adapter: AgentEngineAdapter, seconds: int) -> None:
        assert isinstance(adapter, _ReactTestAdapter)
        adapter.scenario.clock.advance(seconds)

    def assert_owned_tasks_finished(self, adapter: AgentEngineAdapter) -> None:
        assert isinstance(adapter, _ReactTestAdapter)
        assert all(task.done() for task in adapter._owned_tasks), adapter._owned_tasks

    # Six frozen private replacements. The other nineteen functions are inherited verbatim.
    @pytest.mark.asyncio
    async def test_capabilities_start_stream_collect_success(self) -> None:
        adapter = self.adapter(
            self.success_scenario(
                events=(self.event(kind="engine.output_delta", payload={"text": "hello"}),)
            )
        )
        request = self.make_request(
            tenant_id=" tenant ",
            input="  raw input\n",
            config={"nested": {"unchanged": True}},
            effective_capabilities={"streaming": True},
            engine_session_id="provider-session",
            workspace_id="workspace",
            trace_id="trace",
            execution_workdir="/not/inspected",
        )
        original = request.model_copy(deep=True)
        assert await adapter.get_capabilities() == EngineCapabilities(
            streaming=True, cancellation=True, tool_calling=True, native_events=True
        )
        handle = await self.start(adapter, request)
        assert request == original
        assert handle.execution_id is request.execution_id
        assert handle.provider_session_id == "provider-session"
        assert handle.process_id is None
        with pytest.raises(ConfigurationError) as caught:
            await adapter.start(request)
        assert caught.value.error.code is ExecutionErrorCode.INVALID_ADAPTER_STATE
        events = await self.events(self.stream(adapter, handle))
        assert [event.payload for event in events] == [{"text": "hello"}]
        result = await adapter.collect_result(handle)
        assert (result.status, result.output) == ("completed", "scripted output")
        assert result.usage == {} and result.artifacts == [] and result.engine_metadata == {}

    @pytest.mark.asyncio
    async def test_prestart_errors_precede_handle_and_preserve_retryability(self) -> None:
        adapter = self.adapter(self.success_scenario())
        mismatch = self.make_request(execution_id=REACT_OTHER_RUN_ID)
        with pytest.raises(ConfigurationError) as caught:
            await adapter.start(mismatch)
        assert caught.value.error.code is ExecutionErrorCode.INVALID_REQUEST
        assert adapter._execution is None
        with pytest.raises(ConfigurationError):
            await adapter.start(cast(ExecutionRequest, {"secret": SENSITIVE_DIAGNOSTIC}))
        handle = await self.start(adapter, self.make_request())
        with pytest.raises(ConfigurationError) as duplicate:
            await adapter.start(self.make_request())
        assert duplicate.value.error.code is ExecutionErrorCode.INVALID_ADAPTER_STATE
        await adapter.cancel(handle)

        other_context = _react_context(REACT_OTHER_RUN_ID)
        mismatched = ReactAdapter(other_context, _ScriptedRuntimeFactory(_ReactScenario()))
        with pytest.raises(ConfigurationError) as context_caught:
            await mismatched.start(self.make_request())
        assert context_caught.value.error.code is ExecutionErrorCode.INVALID_REQUEST

    @pytest.mark.asyncio
    async def test_unknown_exception_and_simulated_process_failure_are_distinct_and_safe(
        self,
    ) -> None:
        adapter = self.adapter(self.scenario(stream_error=RuntimeError(SENSITIVE_DIAGNOSTIC)))
        handle = await self.start(adapter, self.make_request())
        collector = self.task(adapter.collect_result(handle))
        with pytest.raises(AdapterExecutionError) as caught:
            await self.events(self.stream(adapter, handle))
        assert caught.value.error.code is ExecutionErrorCode.INTERNAL_ERROR
        assert SENSITIVE_DIAGNOSTIC not in repr(caught.value)
        result = await collector
        assert result.status == "failed"
        assert result.error is not None and result.error.code is ExecutionErrorCode.INTERNAL_ERROR
        outcome = adapter._execution.outcome
        assert outcome.legacy_error_code == "execution_error"

    @pytest.mark.asyncio
    async def test_duplicates_late_events_gaps_and_timestamps_follow_sequence_rules(self) -> None:
        payload = {"kind": "duplicate"}
        adapter = self.adapter(
            self.success_scenario(events=(self.event(payload=payload), self.event(payload=payload)))
        )
        handle = await self.start(adapter, self.make_request())
        events = await self.events(self.stream(adapter, handle))
        assert [event.sequence for event in events] == [1, 2]
        assert events[0].event_id != events[1].event_id
        assert events[0].payload == events[1].payload == payload
        assert all(event.timestamp.tzinfo is UTC for event in events)
        assert (await adapter.collect_result(handle)).status == "completed"

    @pytest.mark.asyncio
    async def test_same_event_id_with_different_content_is_never_repaired(self) -> None:
        for kind, payload in (
            ("run.completed", {}),
            ("tool.replay", {}),
            ("engine.output_delta", {"event_id": str(uuid4()), "text": "forged"}),
            ("engine.output_delta", {"sequence": 99}),
        ):
            adapter = self.adapter(
                self.success_scenario(events=(self.event(kind=kind, payload=payload),))
            )
            handle = await self.start(adapter, self.make_request())
            collector = self.task(adapter.collect_result(handle))
            with pytest.raises(AdapterExecutionError) as caught:
                await self.events(self.stream(adapter, handle))
            assert caught.value.error.code is ExecutionErrorCode.PROTOCOL_ERROR
            assert adapter.scenario.worker_emissions == []
            result = await collector
            assert result.status == "failed"
            assert (
                result.error is not None and result.error.code is ExecutionErrorCode.PROTOCOL_ERROR
            )

    @pytest.mark.asyncio
    async def test_deterministic_fresh_runs_have_no_cross_instance_high_water(self) -> None:
        observations = []
        executions = []
        for _ in range(2):
            adapter = self.adapter(
                self.success_scenario(events=(self.event(payload={"run": "same"}),))
            )
            handle = await self.start(adapter, self.make_request())
            events = await self.events(self.stream(adapter, handle))
            result = await adapter.collect_result(handle)
            observations.append((events, result))
            executions.append(adapter._execution)
        assert [event.sequence for event in observations[0][0]] == [1]
        assert [event.sequence for event in observations[1][0]] == [1]
        assert observations[0][0][0].event_id != observations[1][0][0].event_id
        assert observations[0][1] == observations[1][1]
        assert observations[0][1] is not observations[1][1]
        first, second = executions
        assert first.queue is not second.queue
        assert first.task is not second.task
        assert first.first_gate is not second.first_gate
        assert first.terminal is not second.terminal


PUBLIC_SUITE_FUNCTIONS = {
    name
    for name, function in vars(AdapterContractSuite).items()
    if name.startswith("test_") and inspect.isfunction(function)
}
PRIVATE_REPLACEMENTS = {
    "test_capabilities_start_stream_collect_success",
    "test_prestart_errors_precede_handle_and_preserve_retryability",
    "test_unknown_exception_and_simulated_process_failure_are_distinct_and_safe",
    "test_duplicates_late_events_gaps_and_timestamps_follow_sequence_rules",
    "test_same_event_id_with_different_content_is_never_repaired",
    "test_deterministic_fresh_runs_have_no_cross_instance_high_water",
}


def test_public_contract_has_exactly_nineteen_reuses_and_six_private_replacements():
    assert len(PUBLIC_SUITE_FUNCTIONS) == 25
    assert PRIVATE_REPLACEMENTS <= PUBLIC_SUITE_FUNCTIONS
    own_tests = {
        name
        for name, function in vars(TestReactAdapter).items()
        if name.startswith("test_") and inspect.isfunction(function)
    }
    assert own_tests == PRIVATE_REPLACEMENTS
    assert len(PUBLIC_SUITE_FUNCTIONS - own_tests) == 19


@pytest.mark.asyncio
async def test_double_emit_first_gate_runtime_inputs_and_private_outcome():
    scenario = _ReactScenario(
        events=(
            _ReactEventSpec("model.delta", {"text": "a"}),
            _ReactEventSpec("knowledge.retrieved", {"documents": [{"id": "d1"}]}),
            _ReactEventSpec("memory_search.completed", {"count": 1}),
            _ReactEventSpec("extension.custom", {"nested": {"allowed": True}}),
            _ReactEventSpec("model.completed", {"usage": {"prompt_tokens": 7, "future": "x"}}),
        ),
        history=[{"role": "assistant", "content": "answer"}],
        dropped=[{"role": "user", "content": "old"}],
    )
    context = _react_context()
    adapter = _ReactTestAdapter(scenario, context)
    request = build_execution_request(context)
    handle = await adapter.start(request)
    await asyncio.wait_for(scenario.runtime_entered.wait(), timeout=0.2)
    assert not adapter._execution.first_gate.is_set()
    assert len(adapter._execution.queue) == 0
    assert scenario.worker_emissions == []
    raw = adapter.stream_events(handle)
    stream = _WorkerEmitStream(raw, scenario)
    events = [event async for event in stream]
    result = await adapter.collect_result(handle)
    assert len(events) == 5
    assert scenario.worker_emissions == [(event.event_type, event.payload) for event in events]
    assert [event.sequence for event in events] == [1, 2, 3, 4, 5]
    assert all(event.source == "engine_native" for event in events)
    assert events[-1].payload["usage"] == {"prompt_tokens": 7, "future": "x"}
    assert result.usage == {}
    assert adapter.factory.calls[0][0] is context.row
    runtime_call = adapter.factory.runtime.calls[0]
    assert runtime_call[0] == context.row["input"]
    assert runtime_call[1] == context.history
    assert runtime_call[2] is adapter.factory.calls[0][1]
    assert runtime_call[3:] == ("summary", "memory")
    assert not hasattr(context, "worker_emit") and not hasattr(context, "runtime_emit")
    outcome = adapter._execution.outcome
    assert outcome.history == scenario.history and outcome.dropped == scenario.dropped
    assert outcome.usage == {}
    assert all(task.done() for task in adapter._owned_tasks)


@pytest.mark.asyncio
async def test_adapter_never_reads_contextvar_after_explicit_capture():
    context = _react_context()
    captured = resolve_with_execution_context(
        context,
        lambda: _ReactTestAdapter(
            _ReactScenario(events=(_ReactEventSpec(),)), capture_execution_context()
        ),
    )
    handle = await captured.start(build_execution_request(context))
    with pytest.raises(ConfigurationError):
        capture_execution_context()
    stream = _WorkerEmitStream(captured.stream_events(handle), captured.scenario)
    assert len([event async for event in stream]) == 1
    assert (await captured.collect_result(handle)).status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,payload",
    [
        ("NOT VALID", {}),
        ("run.started", {}),
        ("tool.replay", {}),
        ("engine.output_delta", ["not", "json", "object"]),
        ("engine.output_delta", {"bad": object()}),
        ("engine.output_delta", {"timestamp": datetime.now(UTC)}),
        ("engine.output_delta", {"execution_id": str(REACT_RUN_ID)}),
        ("engine.output_delta", {"source": "platform"}),
    ],
)
async def test_malformed_reserved_and_non_json_events_fail_before_worker_emit(kind, payload):
    scenario = _ReactScenario(events=(_ReactEventSpec(kind, payload),))
    adapter = _ReactTestAdapter(scenario, _react_context())
    handle = await adapter.start(build_execution_request(adapter.context))
    stream = _WorkerEmitStream(adapter.stream_events(handle), scenario)
    collector = asyncio.create_task(adapter.collect_result(handle))
    with pytest.raises(AdapterExecutionError) as caught:
        await anext(stream)
    assert caught.value.error.code is ExecutionErrorCode.PROTOCOL_ERROR
    assert scenario.worker_emissions == []
    assert SENSITIVE_DIAGNOSTIC not in repr(caught.value)
    assert (await collector).status == "failed"
    assert all(task.done() for task in adapter._owned_tasks)


@pytest.mark.asyncio
async def test_capacity_one_slow_delivery_backpressure_and_exactly_once_ack():
    scenario = _ReactScenario(
        events=tuple(_ReactEventSpec(payload={"index": index}) for index in range(4))
    )
    adapter = _ReactTestAdapter(scenario, _react_context())
    handle = await adapter.start(build_execution_request(adapter.context))
    raw = adapter.stream_events(handle)
    execution = adapter._execution
    first = await asyncio.wait_for(anext(raw), timeout=0.2)
    worker_started = asyncio.Event()
    release_worker = asyncio.Event()

    async def slow_worker_emit() -> None:
        worker_started.set()
        await release_worker.wait()
        scenario.worker_emissions.append((first.event_type, dict(first.payload)))
        await raw.acknowledge(first)

    worker = asyncio.create_task(slow_worker_emit())
    await asyncio.wait_for(worker_started.wait(), timeout=0.2)
    await _wait_for_condition(lambda: len(execution.queue) == 1)
    assert execution.in_flight is first
    assert execution.undelivered == 2
    collector = asyncio.create_task(adapter.collect_result(handle))
    await asyncio.sleep(0)
    assert not collector.done()
    assert not worker.done()
    assert scenario.worker_emissions == []
    assert len(scenario.runtime_emissions) <= 3

    release_worker.set()
    await asyncio.wait_for(worker, timeout=0.2)
    await raw.acknowledge(first)
    assert execution.undelivered == 1
    second = await asyncio.wait_for(anext(raw), timeout=0.2)
    await _wait_for_condition(lambda: len(execution.queue) == 1)
    scenario.worker_emissions.append((second.event_type, dict(second.payload)))
    await raw.acknowledge(second)
    third = await asyncio.wait_for(anext(raw), timeout=0.2)
    scenario.worker_emissions.append((third.event_type, dict(third.payload)))
    await raw.acknowledge(third)
    fourth = await asyncio.wait_for(anext(raw), timeout=0.2)
    assert execution.producer_finished
    assert not collector.done()
    scenario.worker_emissions.append((fourth.event_type, dict(fourth.payload)))
    await raw.acknowledge(fourth)
    assert (await asyncio.wait_for(collector, timeout=0.2)).status == "completed"
    assert [payload["index"] for _, payload in scenario.worker_emissions] == [0, 1, 2, 3]
    with pytest.raises(StopAsyncIteration):
        await anext(raw)
    assert worker.done()
    assert all(task.done() for task in adapter._owned_tasks)


@pytest.mark.asyncio
async def test_ack_rejects_no_inflight_wrong_identity_and_cross_execution_then_aborts():
    first_adapter = _ReactTestAdapter(_ReactScenario(events=(_ReactEventSpec(),)), _react_context())
    first_handle = await first_adapter.start(build_execution_request(first_adapter.context))
    first_stream = first_adapter.stream_events(first_handle)
    event = await asyncio.wait_for(anext(first_stream), timeout=0.2)
    forged = event.model_copy(update={"event_id": uuid4()})
    with pytest.raises(AdapterExecutionError) as wrong:
        await first_stream.acknowledge(forged)
    assert wrong.value.error.code is ExecutionErrorCode.PROTOCOL_ERROR
    result = await first_adapter.collect_result(first_handle)
    assert result.status == "failed"
    assert result.error is not None and result.error.code is ExecutionErrorCode.PROTOCOL_ERROR
    with pytest.raises(AdapterExecutionError):
        await first_stream.acknowledge(event)

    second_adapter = _ReactTestAdapter(_ReactScenario(), _react_context(REACT_OTHER_RUN_ID))
    second_handle = await second_adapter.start(build_execution_request(second_adapter.context))
    second_stream = second_adapter.stream_events(second_handle)
    with pytest.raises(AdapterExecutionError):
        await second_stream.acknowledge(event)
    assert (await second_adapter.collect_result(second_handle)).status == "failed"
    await first_adapter.cancel(first_handle)
    await second_adapter.cancel(second_handle)
    assert all(task.done() for task in (*first_adapter._owned_tasks, *second_adapter._owned_tasks))


@pytest.mark.asyncio
async def test_no_stream_suppression_has_no_replay_and_unacked_event_gates_result():
    no_stream = _ReactTestAdapter(_ReactScenario(events=(_ReactEventSpec(),)), _react_context())
    no_stream_handle = await no_stream.start(build_execution_request(no_stream.context))
    result = await asyncio.wait_for(no_stream.collect_result(no_stream_handle), timeout=0.2)
    assert result.status == "completed"
    assert no_stream.scenario.worker_emissions == []
    empty = no_stream.stream_events(no_stream_handle)
    with pytest.raises(StopAsyncIteration):
        await anext(empty)
    assert no_stream._execution.undelivered == 0

    active = _ReactTestAdapter(
        _ReactScenario(events=(_ReactEventSpec(),)), _react_context(REACT_OTHER_RUN_ID)
    )
    active_handle = await active.start(build_execution_request(active.context))
    raw = active.stream_events(active_handle)
    event = await anext(raw)
    collector = asyncio.create_task(active.collect_result(active_handle))
    await _wait_for_condition(lambda: active._execution.producer_finished)
    assert not collector.done()
    await raw.acknowledge(event)
    assert (await collector).status == "completed"
    await no_stream.cancel(no_stream_handle)
    await active.cancel(active_handle)


@pytest.mark.asyncio
async def test_worker_emit_failure_and_append_cancellation_have_distinct_cleanup():
    ordinary = RuntimeError(SENSITIVE_DIAGNOSTIC)
    failed = _ReactTestAdapter(
        _ReactScenario(events=(_ReactEventSpec(),), worker_error=ordinary), _react_context()
    )
    failed_handle = await failed.start(build_execution_request(failed.context))
    failed_stream = _WorkerEmitStream(failed.stream_events(failed_handle), failed.scenario)
    with pytest.raises(RuntimeError) as caught:
        await anext(failed_stream)
    assert caught.value is ordinary
    failed_result = await failed.collect_result(failed_handle)
    assert failed_result.status == "failed"
    assert (
        failed_result.error is not None
        and failed_result.error.code is ExecutionErrorCode.INTERNAL_ERROR
    )
    assert failed._execution.outcome.legacy_error_code == "execution_error"
    assert failed.scenario.acknowledgements == []

    append_cancelled = asyncio.CancelledError()
    cancelled = _ReactTestAdapter(
        _ReactScenario(events=(_ReactEventSpec(),), worker_error=append_cancelled),
        _react_context(REACT_OTHER_RUN_ID),
    )
    cancelled_handle = await cancelled.start(build_execution_request(cancelled.context))
    cancelled_stream = _WorkerEmitStream(
        cancelled.stream_events(cancelled_handle), cancelled.scenario
    )
    with pytest.raises(asyncio.CancelledError) as control_flow:
        await anext(cancelled_stream)
    assert control_flow.value is append_cancelled
    assert (await cancelled.collect_result(cancelled_handle)).status == "cancelled"
    assert cancelled.scenario.acknowledgements == []
    assert all(task.done() for task in (*failed._owned_tasks, *cancelled._owned_tasks))


@pytest.mark.asyncio
async def test_swallowed_notifier_delta_failure_acks_but_other_emit_failure_fails():
    delta = _ReactTestAdapter(
        _ReactScenario(events=(_ReactEventSpec("model.delta", {"text": "x"}),)), _react_context()
    )
    # The test notifier has already swallowed its PG/OS error; worker_emit therefore succeeds.
    notifier_failures = ["simulated swallowed notifier failure"]
    delta_handle = await delta.start(build_execution_request(delta.context))
    delta_stream = _WorkerEmitStream(delta.stream_events(delta_handle), delta.scenario)
    event = await anext(delta_stream)
    assert event.event_type == "model.delta"
    assert len(delta.scenario.acknowledgements) == 1 and notifier_failures
    assert (await delta.collect_result(delta_handle)).status == "completed"

    other = _ReactTestAdapter(
        _ReactScenario(
            events=(_ReactEventSpec("knowledge.retrieved", {}),), worker_error=OSError("io")
        ),
        _react_context(REACT_OTHER_RUN_ID),
    )
    other_handle = await other.start(build_execution_request(other.context))
    other_stream = _WorkerEmitStream(other.stream_events(other_handle), other.scenario)
    with pytest.raises(OSError):
        await anext(other_stream)
    assert (await other.collect_result(other_handle)).status == "failed"


@pytest.mark.asyncio
async def test_cancel_blocked_producer_and_pending_consumer_suppresses_late_completion():
    completion_gate = asyncio.Event()
    scenario = _ReactScenario(
        events=tuple(_ReactEventSpec(payload={"index": index}) for index in range(5)),
        completion_gate=completion_gate,
    )
    adapter = _ReactTestAdapter(scenario, _react_context())
    handle = await adapter.start(build_execution_request(adapter.context))
    raw = adapter.stream_events(handle)
    event = await anext(raw)
    await _wait_for_condition(lambda: len(adapter._execution.queue) == 1)
    pending = asyncio.create_task(anext(raw))
    await asyncio.sleep(0)
    assert not pending.done()
    await asyncio.gather(*(adapter.cancel(handle) for _ in range(3)))
    with pytest.raises(StopAsyncIteration):
        await pending
    assert (await adapter.collect_result(handle)).status == "cancelled"
    completion_gate.set()
    await asyncio.sleep(0)
    assert adapter._execution.terminal.result().status == "cancelled"
    with pytest.raises(AdapterExecutionError):
        await raw.acknowledge(event)
    assert all(task.done() for task in adapter._owned_tasks)


@pytest.mark.asyncio
async def test_parallel_emit_preserves_sequence_and_queue_order_under_capacity_one():
    completion_gate = asyncio.Event()
    scenario = _ReactScenario(events=(), completion_gate=completion_gate)
    adapter = _ReactTestAdapter(scenario, _react_context())
    handle = await adapter.start(build_execution_request(adapter.context))
    raw = adapter.stream_events(handle)
    emit = adapter.factory.calls
    await _wait_for_condition(lambda: len(emit) == 1)
    runtime_emit = emit[0][1]
    producers = [
        asyncio.create_task(runtime_emit("extension.parallel", {"index": index}))
        for index in range(3)
    ]
    observed = []
    for _ in range(3):
        event = await asyncio.wait_for(anext(raw), timeout=0.2)
        observed.append((event.sequence, event.payload["index"]))
        await raw.acknowledge(event)
    await asyncio.gather(*producers)
    assert [sequence for sequence, _ in observed] == [1, 2, 3]
    assert [index for _, index in observed] == sorted([index for _, index in observed])
    completion_gate.set()
    with pytest.raises(StopAsyncIteration):
        await anext(raw)
    assert (await adapter.collect_result(handle)).status == "completed"


@pytest.mark.asyncio
async def test_safe_worker_emit_exception_abort_still_uses_internal_execution_error():
    safe = AdapterExecutionError(
        ExecutionError(
            category=ExecutionErrorCategory.PERMISSION_DENIED,
            code=ExecutionErrorCode.PERMISSION_DENIED,
        )
    )
    adapter = _ReactTestAdapter(
        _ReactScenario(events=(_ReactEventSpec(),), worker_error=safe), _react_context()
    )
    handle = await adapter.start(build_execution_request(adapter.context))
    stream = _WorkerEmitStream(adapter.stream_events(handle), adapter.scenario)
    with pytest.raises(AdapterExecutionError) as caught:
        await anext(stream)
    assert caught.value is safe
    result = await adapter.collect_result(handle)
    assert result.error is not None and result.error.code is ExecutionErrorCode.INTERNAL_ERROR
    assert adapter._execution.outcome.legacy_error_code == "execution_error"


@pytest.mark.asyncio
async def test_runtime_fault_failure_preserves_private_legacy_code():
    adapter = _ReactTestAdapter(
        _ReactScenario(stream_error=RuntimeFault("agent_model_required")), _react_context()
    )
    handle = await adapter.start(build_execution_request(adapter.context))
    collector = asyncio.create_task(adapter.collect_result(handle))
    stream = adapter.stream_events(handle)
    with pytest.raises(ConfigurationError) as caught:
        await anext(stream)
    assert caught.value.error.code is ExecutionErrorCode.INVALID_REQUEST
    result = await collector
    assert result.status == "failed"
    assert adapter._execution.outcome.legacy_error_code == "agent_model_required"
    assert all(task.done() for task in adapter._owned_tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task_errors,expected_code,expected_legacy",
    [
        (
            (RuntimeFault("model_provider_unavailable"),),
            ExecutionErrorCode.ENGINE_UNAVAILABLE,
            "model_provider_unavailable",
        ),
        (
            (RuntimeFault("model_timeout"), RuntimeFault("model_timeout")),
            ExecutionErrorCode.EXECUTION_TIMEOUT,
            "model_timeout",
        ),
        (
            (RuntimeFault("model_timeout"), RuntimeFault("model_provider_unavailable")),
            ExecutionErrorCode.INTERNAL_ERROR,
            "execution_error",
        ),
    ],
)
async def test_taskgroup_failures_preserve_prior_events_and_stable_error_mapping(
    task_errors, expected_code, expected_legacy
):
    scenario = _ReactScenario(
        events=(_ReactEventSpec("model.delta", {"text": "kept"}),),
        task_group_errors=task_errors,
        queue_capacity=3,
    )
    adapter = _ReactTestAdapter(scenario, _react_context())
    handle = await adapter.start(build_execution_request(adapter.context))
    collector = asyncio.create_task(adapter.collect_result(handle))
    stream = _WorkerEmitStream(adapter.stream_events(handle), scenario)
    first = await asyncio.wait_for(anext(stream), timeout=0.2)
    assert first.payload == {"text": "kept"}
    with pytest.raises(AdapterExecutionError) as caught:
        await asyncio.wait_for(anext(stream), timeout=0.2)
    assert caught.value.error.code is expected_code
    assert SENSITIVE_DIAGNOSTIC not in repr(caught.value)
    result = await asyncio.wait_for(collector, timeout=0.2)
    assert result.status == "failed"
    assert result.error is not None and result.error.code is expected_code
    assert adapter._execution.outcome.legacy_error_code == expected_legacy
    assert scenario.worker_emissions == [("model.delta", {"text": "kept"})]
    assert adapter._execution.undelivered == 0
    assert all(task.done() for task in adapter._owned_tasks)


@pytest.mark.asyncio
async def test_nested_cancelled_base_exception_group_closes_real_runner_without_external_cancel():
    control_group = BaseExceptionGroup(
        SENSITIVE_DIAGNOSTIC,
        [
            ExceptionGroup(SENSITIVE_DIAGNOSTIC, [RuntimeFault("model_timeout")]),
            BaseExceptionGroup(SENSITIVE_DIAGNOSTIC, [asyncio.CancelledError()]),
        ],
    )
    scenario = _ReactScenario(
        events=(_ReactEventSpec("model.delta", {"text": "queued"}),),
        stream_error=control_group,
        queue_capacity=2,
    )
    adapter = _ReactTestAdapter(scenario, _react_context())
    handle = await adapter.start(build_execution_request(adapter.context))
    raw = adapter.stream_events(handle)
    collector = asyncio.create_task(adapter.collect_result(handle))
    pending = asyncio.create_task(anext(raw))
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    unhandled: list[dict[str, object]] = []
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
    try:
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(pending, timeout=0.2)
        result = await asyncio.wait_for(collector, timeout=0.2)
        assert result.status == "cancelled"
        assert result.output is None and result.error is None
        execution = adapter._execution
        assert execution.outcome.status == "cancelled"
        assert execution.terminal.result() is result
        assert len(execution.queue) == 0
        assert execution.in_flight is None
        assert execution.undelivered == 0
        assert execution.first_gate.is_set()
        assert all(task.done() for task in adapter._owned_tasks)
        await asyncio.sleep(0)
        assert [
            context for context in unhandled if "never retrieved" in context.get("message", "")
        ] == []
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        if not adapter._execution.terminal.done():
            await adapter.cancel(handle)
        if not collector.done():
            collector.cancel()
        await asyncio.gather(collector, return_exceptions=True)
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
async def test_failure_handler_cancelled_error_closes_real_runner_without_external_cancel():
    scenario = _ReactScenario(
        events=(_ReactEventSpec("model.delta", {"text": "queued"}),),
        stream_error=_HostileCodeRuntimeFault(asyncio.CancelledError()),
        queue_capacity=2,
    )
    adapter = _ReactTestAdapter(scenario, _react_context())
    handle = await adapter.start(build_execution_request(adapter.context))
    raw = adapter.stream_events(handle)
    collector = asyncio.create_task(adapter.collect_result(handle))
    pending = asyncio.create_task(anext(raw))
    loop = asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()
    unhandled: list[dict[str, object]] = []
    loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
    try:
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(pending, timeout=0.2)
        result = await asyncio.wait_for(collector, timeout=0.2)
        assert result.status == "cancelled"
        assert result.output is None and result.error is None
        execution = adapter._execution
        assert execution.outcome.status == "cancelled"
        assert execution.terminal.result() is result
        assert execution.stream_state == "closed"
        assert len(execution.queue) == 0
        assert execution.in_flight is None
        assert execution.settled_acks == set()
        assert execution.undelivered == 0
        assert execution.first_gate.is_set()
        assert all(task.done() for task in adapter._owned_tasks)
        await asyncio.sleep(0)
        assert [
            context for context in unhandled if "never retrieved" in context.get("message", "")
        ] == []
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        if not adapter._execution.terminal.done():
            await adapter.cancel(handle)
        if not collector.done():
            collector.cancel()
        await asyncio.gather(collector, return_exceptions=True)
        loop.set_exception_handler(previous_handler)


@pytest.mark.asyncio
@pytest.mark.parametrize("control_flow", [KeyboardInterrupt(), SystemExit(), GeneratorExit()])
async def test_failure_handler_control_flow_is_rethrown_after_cancellation_cleanup(
    control_flow: BaseException,
):
    adapter = _ReactTestAdapter(
        _ReactScenario(stream_error=_HostileCodeRuntimeFault(control_flow)), _react_context()
    )
    request = build_execution_request(adapter.context)
    handle = ExecutionHandle(
        execution_id=request.execution_id,
        engine_id=adapter.engine_id,
        protocol_id=adapter.protocol_id,
        adapter_version=adapter.adapter_version,
        provider_session_id=request.engine_session_id,
        process_id=None,
    )
    execution = _Execution(adapter.context, request, handle, adapter.scenario.queue_capacity)

    with pytest.raises(type(control_flow)) as caught:
        await adapter.raw._run(execution)

    assert caught.value is control_flow
    assert execution.terminal.done()
    assert execution.terminal.result().status == "cancelled"
    assert execution.outcome.status == "cancelled"
    assert execution.undelivered == 0
    assert execution.first_gate.is_set()


@pytest.mark.asyncio
async def test_emit_after_successful_return_is_suppressed_while_first_event_awaits_ack():
    adapter = _ReactTestAdapter(
        _ReactScenario(events=(_ReactEventSpec("model.delta", {"text": "first"}),)),
        _react_context(),
    )
    handle = await adapter.start(build_execution_request(adapter.context))
    raw = adapter.stream_events(handle)
    first = await asyncio.wait_for(anext(raw), timeout=0.2)
    execution = adapter._execution
    await _wait_for_condition(lambda: execution.producer_finished)
    collector = asyncio.create_task(adapter.collect_result(handle))
    runtime_emit = adapter.factory.calls[0][1]
    try:
        await asyncio.wait_for(runtime_emit("extension.after_return", {"late": True}), timeout=0.2)
        assert len(execution.queue) == 0
        assert execution.undelivered == 1
        assert not collector.done()
        adapter.scenario.worker_emissions.append((first.event_type, dict(first.payload)))
        await raw.acknowledge(first)
        result = await asyncio.wait_for(collector, timeout=0.2)
        assert result.status == "completed"
        assert execution.undelivered == 0
        assert all(
            kind != "extension.after_return" for kind, _ in adapter.scenario.worker_emissions
        )
    finally:
        await adapter.cancel(handle)
    assert all(task.done() for task in adapter._owned_tasks)


@pytest.mark.asyncio
async def test_blocked_emitter_wakes_on_producer_finished_without_joining_drained_events():
    completion_gate = asyncio.Event()
    scenario = _ReactScenario(
        events=(_ReactEventSpec(payload={"index": 1}), _ReactEventSpec(payload={"index": 2})),
        completion_gate=completion_gate,
    )
    adapter = _ReactTestAdapter(scenario, _react_context())
    handle = await adapter.start(build_execution_request(adapter.context))
    raw = adapter.stream_events(handle)
    first = await asyncio.wait_for(anext(raw), timeout=0.2)
    execution = adapter._execution
    await _wait_for_condition(lambda: len(execution.queue) == 1)
    runtime_emit = adapter.factory.calls[0][1]
    late_started = asyncio.Event()

    async def late_emit() -> None:
        late_started.set()
        await runtime_emit("extension.blocked_after_return", {})

    late = asyncio.create_task(late_emit())
    await asyncio.wait_for(late_started.wait(), timeout=0.2)
    await asyncio.sleep(0)
    assert not late.done()
    completion_gate.set()
    try:
        await asyncio.wait_for(late, timeout=0.2)
        await raw.acknowledge(first)
        second = await asyncio.wait_for(anext(raw), timeout=0.2)
        assert second.payload == {"index": 2}
        await raw.acknowledge(second)
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(anext(raw), timeout=0.2)
        result = await adapter.collect_result(handle)
        assert result.status == "completed"
        assert execution.settled_acks == set()
        assert execution.undelivered == 0
    finally:
        completion_gate.set()
        await adapter.cancel(handle)
        if not late.done():
            late.cancel()
        await asyncio.gather(late, return_exceptions=True)
    assert all(task.done() for task in adapter._owned_tasks)


@pytest.mark.asyncio
async def test_failure_with_spare_capacity_suppresses_late_emit_and_leaves_no_residue():
    scenario = _ReactScenario(
        events=(
            _ReactEventSpec("model.delta", {"index": 1}),
            _ReactEventSpec("knowledge.retrieved", {"index": 2}),
        ),
        task_group_errors=(RuntimeFault("model_provider_unavailable"),),
        queue_capacity=4,
    )
    adapter = _ReactTestAdapter(scenario, _react_context())
    handle = await adapter.start(build_execution_request(adapter.context))
    raw = adapter.stream_events(handle)
    collector = asyncio.create_task(adapter.collect_result(handle))
    first = await asyncio.wait_for(anext(raw), timeout=0.2)
    execution = adapter._execution
    await _wait_for_condition(lambda: execution.producer_finished)
    runtime_emit = adapter.factory.calls[0][1]
    try:
        await asyncio.wait_for(runtime_emit("extension.after_failure", {}), timeout=0.2)
        await raw.acknowledge(first)
        second = await asyncio.wait_for(anext(raw), timeout=0.2)
        assert second.event_type == "knowledge.retrieved"
        await raw.acknowledge(second)
        with pytest.raises(AdapterExecutionError) as caught:
            await asyncio.wait_for(anext(raw), timeout=0.2)
        assert caught.value.error.code is ExecutionErrorCode.ENGINE_UNAVAILABLE
        result = await asyncio.wait_for(collector, timeout=0.2)
        assert result.status == "failed"
        assert len(execution.queue) == 0
        assert execution.in_flight is None
        assert execution.undelivered == 0
    finally:
        await adapter.cancel(handle)
    assert all(task.done() for task in adapter._owned_tasks)


@pytest.mark.asyncio
async def test_settled_ack_idempotence_is_active_only_and_terminal_releases_identities():
    adapter = _ReactTestAdapter(
        _ReactScenario(events=(_ReactEventSpec(), _ReactEventSpec()), queue_capacity=2),
        _react_context(),
    )
    handle = await adapter.start(build_execution_request(adapter.context))
    raw = adapter.stream_events(handle)
    execution = adapter._execution
    first = await asyncio.wait_for(anext(raw), timeout=0.2)
    await raw.acknowledge(first)
    await raw.acknowledge(first)
    assert execution.settled_acks == {(first.execution_id, first.event_id)}
    second = await asyncio.wait_for(anext(raw), timeout=0.2)
    await raw.acknowledge(second)
    try:
        assert execution.settled_acks == set()
        assert (await adapter.collect_result(handle)).status == "completed"
        with pytest.raises(AdapterExecutionError) as caught:
            await raw.acknowledge(second)
        assert caught.value.error.code is ExecutionErrorCode.PROTOCOL_ERROR
        assert (await adapter.collect_result(handle)).status == "completed"
    finally:
        await adapter.cancel(handle)
    assert execution.settled_acks == set()
    assert all(task.done() for task in adapter._owned_tasks)


@pytest.mark.asyncio
async def test_collect_outcome_completed_reuses_terminal_path_and_keeps_public_result_clean():
    scenario = _ReactScenario(
        events=(_ReactEventSpec(kind="model.delta", payload={"text": "A"}),),
        output="answer",
        history=[{"role": "assistant", "content": "answer"}],
        dropped=[{"role": "user", "content": "old"}],
    )
    adapter = _ReactTestAdapter(scenario, _react_context())
    handle = await adapter.start(build_execution_request(adapter.context))
    stream = adapter.stream_events(handle)
    event = await asyncio.wait_for(anext(stream), timeout=0.2)
    scenario.worker_emissions.append((event.event_type, dict(event.payload)))
    await stream.acknowledge(event)

    outcome = await asyncio.wait_for(adapter.raw.collect_outcome(handle), timeout=0.2)
    result = await asyncio.wait_for(adapter.collect_result(handle), timeout=0.2)

    assert isinstance(outcome, ExecutionOutcome)
    assert outcome.status == "completed"
    assert outcome.output == "answer"
    assert outcome.history == scenario.history
    assert outcome.dropped == scenario.dropped
    assert outcome.usage == {}
    assert outcome.legacy_error_code is None
    assert result.status == "completed"
    assert result.output == "answer"
    assert result.model_dump()["engine_metadata"] == {}
    assert set(type(result).model_fields).isdisjoint(
        {"history", "dropped", "legacy_error_code", "outcome"}
    )
    assert as_outcome_collecting_adapter(adapter.raw) is adapter.raw


@pytest.mark.asyncio
async def test_collect_outcome_failed_preserves_unknown_runtime_fault_legacy_code():
    future_code = "future_runtime_" + "private_code"
    adapter = _ReactTestAdapter(
        _ReactScenario(prestart_error=RuntimeFault(future_code)), _react_context()
    )
    handle = await adapter.start(build_execution_request(adapter.context))

    outcome = await asyncio.wait_for(adapter.raw.collect_outcome(handle), timeout=0.2)
    result = await asyncio.wait_for(adapter.collect_result(handle), timeout=0.2)

    assert outcome.status == "failed"
    assert outcome.legacy_error_code == future_code
    assert outcome.output is None and outcome.history is None and outcome.dropped is None
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code is ExecutionErrorCode.INTERNAL_ERROR
    assert future_code not in result.model_dump_json()
    assert result.engine_metadata == {}


@pytest.mark.asyncio
async def test_collect_outcome_cancelled_has_no_code_and_handle_validation_is_shared():
    gate = asyncio.Event()
    adapter = _ReactTestAdapter(_ReactScenario(completion_gate=gate), _react_context())
    handle = await adapter.start(build_execution_request(adapter.context))
    collector = asyncio.create_task(adapter.raw.collect_outcome(handle))
    await asyncio.wait_for(adapter.scenario.runtime_entered.wait(), timeout=0.2)

    await adapter.cancel(handle)
    outcome = await asyncio.wait_for(collector, timeout=0.2)

    assert outcome.status == "cancelled"
    assert outcome.legacy_error_code is None
    assert outcome.output is None and outcome.history is None and outcome.dropped is None
    wrong_handle = handle.model_copy(update={"execution_id": uuid4()})
    with pytest.raises(ConfigurationError) as caught:
        await adapter.raw.collect_outcome(wrong_handle)
    assert caught.value.error.code is ExecutionErrorCode.INVALID_HANDLE
    assert all(task.done() for task in adapter._owned_tasks)


@pytest.mark.asyncio
async def test_collect_outcome_shared_collectors_and_lone_cancellation_match_public_semantics():
    shared_adapter = _ReactTestAdapter(_ReactScenario(), _react_context())
    shared_handle = await shared_adapter.start(build_execution_request(shared_adapter.context))
    first, second = await asyncio.wait_for(
        asyncio.gather(
            shared_adapter.raw.collect_outcome(shared_handle),
            shared_adapter.raw.collect_outcome(shared_handle),
        ),
        timeout=0.2,
    )
    assert first is second
    assert first.status == "completed"
    assert (await shared_adapter.collect_result(shared_handle)).status == "completed"

    lone_adapter = _ReactTestAdapter(
        _ReactScenario(completion_gate=asyncio.Event()), _react_context()
    )
    lone_handle = await lone_adapter.start(build_execution_request(lone_adapter.context))
    lone_collector = asyncio.create_task(lone_adapter.raw.collect_outcome(lone_handle))
    await asyncio.wait_for(lone_adapter.scenario.runtime_entered.wait(), timeout=0.2)
    lone_collector.cancel()
    with pytest.raises(asyncio.CancelledError):
        await lone_collector
    assert lone_adapter._execution.terminal.done()
    assert lone_adapter._execution.terminal.result().status == "cancelled"
    assert all(task.done() for task in lone_adapter._owned_tasks)
