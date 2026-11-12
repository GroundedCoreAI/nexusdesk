"""LocalTestAdapter implementation hooks and cumulative static architecture checks."""

import ast
import asyncio
import inspect
import traceback
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import pytest
from agent_execution.adapter_contract_suite import AdapterContractSuite

import agent_platform.core_platform.agent_execution as execution_package
from agent_platform.core_platform.agent_execution.adapters.testing import (
    LocalTestAdapter,
    LocalTestClock,
    LocalTestEventSpec,
    LocalTestScenario,
)
from agent_platform.core_platform.agent_execution.contracts import (
    AdapterExecutionError,
    AgentEngineAdapter,
    ConfigurationError,
    EngineCapabilities,
    ExecutionContractModel,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionRequest,
)
from agent_platform.core_platform.agent_execution.registry import (
    AdapterDescriptor,
    AdapterRegistry,
    EngineDescriptor,
    EngineRegistry,
    ProtocolDescriptor,
    ProtocolRegistry,
)
from agent_platform.extension_contracts.base import ContractModel

EXECUTION_ID = UUID("00000000-0000-4000-8000-000000000101")
AGENT_ID = UUID("00000000-0000-4000-8000-000000000102")


class TestLocalTestAdapter(AdapterContractSuite):
    __test__ = True

    def make_scenario(self, **controls: Any) -> LocalTestScenario:
        return LocalTestScenario(**controls)

    def make_event_spec(self, **controls: Any) -> LocalTestEventSpec:
        return LocalTestEventSpec(**controls)

    def make_gate(self) -> asyncio.Event:
        return asyncio.Event()

    def build_adapter(self, scenario: object) -> LocalTestAdapter:
        assert isinstance(scenario, LocalTestScenario)
        return LocalTestAdapter(scenario)

    def make_request(self, **overrides: Any) -> ExecutionRequest:
        data: dict[str, Any] = {
            "execution_id": EXECUTION_ID,
            "engine_id": "local-test",
            "protocol_id": "scripted",
            "adapter_version": "v1",
            "tenant_id": "tenant-1",
            "agent_id": AGENT_ID,
            "input": "input",
        }
        data.update(overrides)
        return ExecutionRequest(**data)

    def advance_clock(self, adapter: AgentEngineAdapter, seconds: int) -> None:
        assert isinstance(adapter, LocalTestAdapter)
        adapter.clock.advance(seconds)

    def assert_owned_tasks_finished(self, adapter: AgentEngineAdapter) -> None:
        assert isinstance(adapter, LocalTestAdapter)
        assert all(task.done() for task in adapter._owned_tasks), adapter._owned_tasks


@pytest.mark.parametrize(
    "scenario",
    [
        LocalTestScenario(capabilities={"streaming": True}),
        LocalTestScenario(
            output="not-allowed",
            error=ExecutionError(
                category=ExecutionErrorCategory.INTERNAL_ERROR,
                code=ExecutionErrorCode.INTERNAL_ERROR,
            ),
        ),
        LocalTestScenario(events=(LocalTestEventSpec(sequence=0),)),
        LocalTestScenario(events=(LocalTestEventSpec(duplicate_of=0),)),
        LocalTestScenario(events=(LocalTestEventSpec(), LocalTestEventSpec(duplicate_of=1))),
        LocalTestScenario(events=(LocalTestEventSpec(event_type="NOT VALID"),)),
        LocalTestScenario(events=[LocalTestEventSpec(source="platform")]),
        LocalTestScenario(manual_timeout="yes"),
        LocalTestScenario(simulated_process_failure=1),
    ],
    ids=[
        "capabilities",
        "output-and-error",
        "sequence",
        "self-duplicate",
        "forward-duplicate",
        "event-type",
        "events-not-tuple",
        "timeout-flag",
        "process-failure-flag",
    ],
)
@pytest.mark.asyncio
async def test_invalid_scenarios_fail_safely_before_any_execution(scenario: LocalTestScenario):
    adapter = LocalTestAdapter(scenario)
    request = TestLocalTestAdapter().make_request()
    with pytest.raises(ConfigurationError) as caught:
        await adapter.start(request)
    assert caught.value.error.category == ExecutionErrorCategory.CONFIGURATION_ERROR
    assert caught.value.error.code == ExecutionErrorCode.INVALID_SCENARIO
    assert str(caught.value) == "Local test scenario is invalid."
    assert adapter._execution is None
    assert adapter._owned_tasks == set()


def test_identity_capabilities_and_manual_controls_are_explicit():
    clock = LocalTestClock()
    capabilities = EngineCapabilities(streaming=True)
    adapter = LocalTestAdapter(LocalTestScenario(capabilities=capabilities), clock=clock)
    assert (adapter.engine_id, adapter.protocol_id, adapter.adapter_version) == (
        "local-test",
        "scripted",
        "v1",
    )
    assert adapter.clock is clock
    assert weakref.ref(adapter)() is adapter
    assert inspect.iscoroutinefunction(adapter.get_capabilities)
    assert inspect.iscoroutinefunction(adapter.start)
    assert inspect.iscoroutinefunction(adapter.collect_result)
    assert inspect.iscoroutinefunction(adapter.cancel)
    assert not inspect.iscoroutinefunction(adapter.stream_events)
    assert not {"engine_id", "protocol_id", "adapter_version"} & set(
        LocalTestScenario.__dataclass_fields__
    )


@pytest.mark.asyncio
async def test_default_event_ids_and_timestamps_have_fixed_uuid5_and_epoch_derivation():
    scenario = LocalTestScenario(events=(LocalTestEventSpec(), LocalTestEventSpec()))
    adapter = LocalTestAdapter(scenario)
    request = TestLocalTestAdapter().make_request()
    handle = await adapter.start(request)
    try:
        events = [event async for event in adapter.stream_events(handle)]
        assert [event.event_id for event in events] == [
            uuid5(LocalTestAdapter.EVENT_ID_NAMESPACE, f"{request.execution_id}:0"),
            uuid5(LocalTestAdapter.EVENT_ID_NAMESPACE, f"{request.execution_id}:1"),
        ]
        assert events[0].timestamp.isoformat() == "2000-01-01T00:00:00+00:00"
        assert (events[1].timestamp - events[0].timestamp).total_seconds() == 0.001
        assert (await adapter.collect_result(handle)).status == "completed"
    finally:
        await adapter.cancel(handle)


@pytest.mark.asyncio
async def test_registry_resolves_exact_identity_with_two_live_isolated_instances():
    engines = EngineRegistry()
    protocols = ProtocolRegistry()
    engines.register(EngineDescriptor(engine_id="local-test"))
    protocols.register(ProtocolDescriptor(protocol_id="scripted"))
    registry = AdapterRegistry(engines, protocols)

    def factory() -> LocalTestAdapter:
        return LocalTestAdapter(
            LocalTestScenario(
                output="done",
                events=(LocalTestEventSpec(sequence=3), LocalTestEventSpec(sequence=1)),
            )
        )

    registry.register(
        AdapterDescriptor(engine_id="local-test", protocol_id="scripted", adapter_version="v1"),
        factory,
    )
    first = registry.resolve("local-test", "scripted", "v1")
    second = registry.resolve("local-test", "scripted", "v1")
    assert isinstance(first, LocalTestAdapter)
    assert isinstance(second, LocalTestAdapter)
    assert first is not second
    assert weakref.ref(first)() is first
    assert weakref.ref(second)() is second

    request_factory = TestLocalTestAdapter()
    first_request = request_factory.make_request()
    second_request = request_factory.make_request(
        execution_id=UUID("00000000-0000-4000-8000-000000000999")
    )
    first_handle = await first.start(first_request)
    second_handle = await second.start(second_request)
    try:
        first_stream = first.stream_events(first_handle)
        second_stream = second.stream_events(second_handle)
        first_events = [event async for event in first_stream]
        second_events = [event async for event in second_stream]
        assert [event.sequence for event in first_events] == [3, 1]
        assert [event.sequence for event in second_events] == [3, 1]
        assert first_events[0].event_id != second_events[0].event_id
        assert (await first.collect_result(first_handle)).status == "completed"
        assert (await second.collect_result(second_handle)).status == "completed"
        assert first._execution is not second._execution
        assert first._execution.events_by_id is not second._execution.events_by_id
    finally:
        await first.cancel(first_handle)
        await second.cancel(second_handle)


def test_reusable_suite_has_no_concrete_adapter_import():
    suite_path = Path(__file__).parent / "agent_execution" / "adapter_contract_suite.py"
    source = suite_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(suite_path))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert not any("local_test_adapter" in name or ".adapters" in name for name in imported)
    assert "LocalTestAdapter" not in source


def test_reusable_suite_uses_abstract_gate_construction():
    suite_path = Path(__file__).parent / "agent_execution" / "adapter_contract_suite.py"
    tree = ast.parse(suite_path.read_text(encoding="utf-8"), filename=str(suite_path))
    direct_gate_construction = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "asyncio"
        and node.func.attr == "Event"
    ]
    assert direct_gate_construction == []
    assert "make_gate" in AdapterContractSuite.__abstractmethods__


def test_cumulative_t2_t3_t4_modules_and_dependency_direction_are_exact():
    package_root = (
        Path(__file__).parents[1] / "src" / "agent_platform" / "core_platform" / "agent_execution"
    )
    contract_modules = {
        "__init__.py",
        "contracts/__init__.py",
        "contracts/base.py",
        "contracts/common.py",
        "contracts/request.py",
        "contracts/handle.py",
        "contracts/result.py",
        "contracts/events.py",
        "contracts/capabilities.py",
        "contracts/errors.py",
        "contracts/adapter.py",
    }
    registry_modules = {
        "registry/__init__.py",
        "registry/engine_registry.py",
        "registry/protocol_registry.py",
        "registry/adapter_registry.py",
    }
    adapter_modules = {
        "adapters/__init__.py",
        "adapters/testing/__init__.py",
        "adapters/testing/local_test_adapter.py",
    }
    t2_modules = {
        "orchestration/__init__.py",
        "orchestration/execution_context.py",
        "orchestration/execution_lifecycle.py",
        "adapters/react/error_mapper.py",
    }
    t3_modules = {
        "adapters/react/__init__.py",
        "adapters/react/adapter.py",
        "adapters/react/event_mapper.py",
    }
    t4_modules = {"orchestration/orchestrator.py"}
    expected_modules = (
        contract_modules | registry_modules | adapter_modules | t2_modules | t3_modules | t4_modules
    )
    actual_modules = {str(path.relative_to(package_root)) for path in package_root.rglob("*.py")}
    assert actual_modules == expected_modules

    common_forbidden = (
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
    imports_by_module: dict[str, list[tuple[str, int]]] = {}
    for relative_path in sorted(expected_modules):
        source_file = package_root / relative_path
        assert source_file.is_file(), relative_path
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        imports: list[tuple[str, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend((alias.name, 0) for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append((node.module, node.level))
        imports_by_module[relative_path] = imports
        names = [name for name, _ in imports]
        assert not any(part in name for name in names for part in common_forbidden), (
            relative_path,
            imports,
        )
        if relative_path in contract_modules:
            forbidden = (*common_forbidden, ".registry", ".adapters")
            assert not any(part in name for name in names for part in forbidden), relative_path
        if relative_path in registry_modules - {"registry/__init__.py"}:
            forbidden = (*common_forbidden, ".adapters", ".testing")
            assert not any(part in name for name in names for part in forbidden), relative_path
        if relative_path == "adapters/testing/local_test_adapter.py":
            assert not any("registry" in name for name in names)
            forbidden_calls = {"uuid4", "now", "utcnow", "sleep", "random"}
            assert not any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in forbidden_calls
                for node in ast.walk(tree)
            )

    local_imports = imports_by_module["adapters/testing/local_test_adapter.py"]
    assert any(level == 3 and name.startswith("contracts") for name, level in local_imports)
    root_source = (package_root / "__init__.py").read_text(encoding="utf-8")
    adapters_source = (package_root / "adapters" / "__init__.py").read_text(encoding="utf-8")
    assert ".adapters" not in root_source
    assert ".testing" not in adapters_source
    assert not hasattr(execution_package, "LocalTestAdapter")
    assert issubclass(ExecutionContractModel, ContractModel)
    assert ExecutionContractModel.__bases__ == (ContractModel,)


SECRET_MARKER = "synthetic-" + "secret-marker"


class _DeepcopyFailure:
    def __init__(self, exception: BaseException) -> None:
        self.exception = exception

    def __deepcopy__(self, memo: object) -> object:
        raise self.exception


class _ScenarioControlFlow(BaseException):
    pass


async def _wait_until(condition: Callable[[], bool]) -> None:
    async def poll() -> None:
        while not condition():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=0.2)


async def _drain_tasks(*tasks: asyncio.Task[object]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_close_broadcasts_to_every_pending_anext_waiter():
    gate = asyncio.Event()
    adapter = LocalTestAdapter(
        LocalTestScenario(events=(LocalTestEventSpec(gate=gate),), output="done")
    )
    request = TestLocalTestAdapter().make_request()
    handle = await adapter.start(request)
    execution = adapter._execution
    assert execution is not None
    stream = adapter.stream_events(handle)
    waiters = [asyncio.create_task(anext(stream)) for _ in range(5)]
    try:
        await _wait_until(lambda: len(execution.queue._getters) == 5)
        await asyncio.wait_for(stream.aclose(), timeout=0.2)
        outcomes = await asyncio.wait_for(
            asyncio.gather(*waiters, return_exceptions=True), timeout=0.2
        )
        assert len(outcomes) == 5
        assert all(isinstance(outcome, StopAsyncIteration) for outcome in outcomes)
        assert all(task.done() for task in waiters)
        assert all(task.done() for task in adapter._owned_tasks)
    finally:
        gate.set()
        await _drain_tasks(*waiters)
        await adapter.cancel(handle)


@pytest.mark.asyncio
async def test_cancel_propagates_new_caller_cancellation_after_runner_cleanup():
    gate = asyncio.Event()
    adapter = LocalTestAdapter(LocalTestScenario(completion_gate=gate, output="done"))
    handle = await adapter.start(TestLocalTestAdapter().make_request())
    execution = adapter._execution
    assert execution is not None and execution.task is not None
    caller = asyncio.create_task(adapter.cancel(handle))
    execution.task.add_done_callback(lambda _: caller.cancel())
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(caller, timeout=0.2)
        assert caller.cancelled() is True
        assert execution.task.done() is True
        assert all(task.done() for task in adapter._owned_tasks)
    finally:
        gate.set()
        await _drain_tasks(caller)
        await adapter.cancel(handle)


@pytest.mark.asyncio
async def test_aclose_propagates_new_caller_cancellation_after_finished_runner_drains():
    adapter = LocalTestAdapter(LocalTestScenario(events=(LocalTestEventSpec(),), output="done"))
    handle = await adapter.start(TestLocalTestAdapter().make_request())
    execution = adapter._execution
    assert execution is not None and execution.task is not None
    stream = adapter.stream_events(handle)
    caller: asyncio.Task[None] | None = None
    try:
        await _wait_until(lambda: execution.script_finished)
        caller = asyncio.create_task(stream.aclose())
        execution.task.add_done_callback(lambda _: caller.cancel())
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(caller, timeout=0.2)
        assert caller.cancelled() is True
        assert execution.task.done() is True
        assert execution.terminal.done() is True
        assert execution.terminal.result().status == "completed"
        assert all(task.done() for task in adapter._owned_tasks)
    finally:
        if caller is not None:
            await _drain_tasks(caller)
        await stream.aclose()
        await adapter.cancel(handle)


@pytest.mark.asyncio
async def test_scenario_deepcopy_runtime_failure_is_safe_invalid_scenario():
    scenario = LocalTestScenario(
        events=(
            LocalTestEventSpec(payload={"invalid": _DeepcopyFailure(RuntimeError(SECRET_MARKER))}),
        )
    )
    adapter = LocalTestAdapter(scenario)
    with pytest.raises(ConfigurationError) as caught:
        await adapter.start(TestLocalTestAdapter().make_request())
    assert caught.value.error.code == ExecutionErrorCode.INVALID_SCENARIO
    rendered = "".join(traceback.format_exception(caught.value))
    assert SECRET_MARKER not in rendered
    assert "RuntimeError" not in rendered
    assert adapter._execution is None


@pytest.mark.asyncio
async def test_scenario_deepcopy_base_exception_propagates_unchanged():
    control_flow = _ScenarioControlFlow()
    scenario = LocalTestScenario(
        events=(LocalTestEventSpec(payload={"invalid": _DeepcopyFailure(control_flow)}),)
    )
    adapter = LocalTestAdapter(scenario)
    with pytest.raises(_ScenarioControlFlow) as caught:
        await adapter.start(TestLocalTestAdapter().make_request())
    assert caught.value is control_flow
    assert adapter._execution is None


class _FailingCompletionGate(asyncio.Event):
    def __init__(self, exception: AdapterExecutionError) -> None:
        super().__init__()
        self.exception = exception

    async def wait(self) -> bool:
        raise self.exception


@pytest.mark.asyncio
async def test_runtime_origin_safe_error_does_not_retain_raw_exception_chain():
    expected = ExecutionError(
        category=ExecutionErrorCategory.INTERNAL_ERROR,
        code=ExecutionErrorCode.INTERNAL_ERROR,
    )

    def original_failure_frame(error: AdapterExecutionError) -> None:
        try:
            raise RuntimeError(SECRET_MARKER)
        except RuntimeError as original:
            raise error from original

    pre_chained = AdapterExecutionError(expected)
    try:
        original_failure_frame(pre_chained)
    except AdapterExecutionError as caught:
        pre_chained = caught

    adapter = LocalTestAdapter(
        LocalTestScenario(completion_gate=_FailingCompletionGate(pre_chained), output="done")
    )
    handle = await adapter.start(TestLocalTestAdapter().make_request())
    stream = adapter.stream_events(handle)
    collector = asyncio.create_task(adapter.collect_result(handle))
    try:
        with pytest.raises(AdapterExecutionError) as caught:
            await asyncio.wait_for(anext(stream), timeout=0.2)
        rendered = "".join(traceback.format_exception(caught.value))
        assert SECRET_MARKER not in rendered
        assert "RuntimeError" not in rendered
        assert "original_failure_frame" not in rendered
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert caught.value.__suppress_context__ is True
        assert caught.value.error == expected
        result = await asyncio.wait_for(collector, timeout=0.2)
        assert result.status == "failed"
        assert result.error == expected
    finally:
        await _drain_tasks(collector)
        await stream.aclose()
        await adapter.cancel(handle)
