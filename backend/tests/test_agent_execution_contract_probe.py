"""ContractProbeAdapter suite hooks and T5 independence/integration checks."""

import ast
import asyncio
import inspect
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import pytest
from agent_execution.adapter_contract_suite import AdapterContractSuite
from agent_execution.contract_probe_adapter import (
    ContractProbeAdapter,
    ContractProbeClock,
    ContractProbeEventSpec,
    ContractProbeScenario,
)

from agent_platform.core_platform.agent_execution.contracts import (
    AgentEngineAdapter,
    EngineCapabilities,
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

EXECUTION_ID = UUID("30000000-0000-4000-8000-000000000001")
AGENT_ID = UUID("30000000-0000-4000-8000-000000000002")


class TestContractProbeAdapter(AdapterContractSuite):
    """Run every common adapter behavior against the independent probe."""

    __test__ = True

    def make_scenario(self, **controls: Any) -> ContractProbeScenario:
        return ContractProbeScenario(**controls)

    def make_event_spec(self, **controls: Any) -> ContractProbeEventSpec:
        return ContractProbeEventSpec(**controls)

    def make_gate(self) -> asyncio.Event:
        return asyncio.Event()

    def build_adapter(self, scenario: object) -> ContractProbeAdapter:
        assert isinstance(scenario, ContractProbeScenario)
        return ContractProbeAdapter(scenario)

    def make_request(self, **overrides: Any) -> ExecutionRequest:
        values: dict[str, Any] = {
            "execution_id": EXECUTION_ID,
            "engine_id": "contract-probe",
            "protocol_id": "contract-scripted",
            "adapter_version": "v1",
            "tenant_id": "tenant-probe",
            "agent_id": AGENT_ID,
            "input": "probe input",
        }
        values.update(overrides)
        return ExecutionRequest(**values)

    def advance_clock(self, adapter: AgentEngineAdapter, seconds: int) -> None:
        assert isinstance(adapter, ContractProbeAdapter)
        adapter.clock.advance(seconds)

    def assert_owned_tasks_finished(self, adapter: AgentEngineAdapter) -> None:
        assert isinstance(adapter, ContractProbeAdapter)
        assert all(task.done() for task in adapter._tasks), adapter._tasks


def test_identity_capabilities_protocol_shape_and_weakref_support() -> None:
    capabilities = EngineCapabilities(streaming=True, cancellation=True, native_events=True)
    clock = ContractProbeClock()
    adapter = ContractProbeAdapter(ContractProbeScenario(capabilities=capabilities), clock=clock)

    assert (adapter.engine_id, adapter.protocol_id, adapter.adapter_version) == (
        "contract-probe",
        "contract-scripted",
        "v1",
    )
    assert adapter.clock is clock
    assert weakref.ref(adapter)() is adapter
    assert inspect.iscoroutinefunction(adapter.get_capabilities)
    assert inspect.iscoroutinefunction(adapter.start)
    assert inspect.iscoroutinefunction(adapter.cancel)
    assert inspect.iscoroutinefunction(adapter.collect_result)
    assert not inspect.iscoroutinefunction(adapter.stream_events)


@pytest.mark.asyncio
async def test_capabilities_are_scenario_declared() -> None:
    capabilities = EngineCapabilities(streaming=True, cancellation=True, native_events=True)
    adapter = ContractProbeAdapter(ContractProbeScenario(capabilities=capabilities))
    assert await adapter.get_capabilities() == capabilities


def test_probe_has_no_local_test_inheritance_import_or_delegation() -> None:
    source_path = Path(__file__).parent / "agent_execution" / "contract_probe_adapter.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))
    probe_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ContractProbeAdapter"
    )

    assert probe_class.bases == []
    assert ContractProbeAdapter.__mro__ == (ContractProbeAdapter, object)
    assert "LocalTest" not in source
    assert "local_test" not in source
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)
    assert not any(
        ".adapters" in name or ".registry" in name or "local_test" in name
        for name in imported_modules
    )
    delegated_attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and node.attr in {"adapter", "delegate", "wrapped", "local_adapter"}
    }
    assert delegated_attributes == set()


@pytest.mark.asyncio
async def test_fixed_event_derivation_and_fresh_runs_are_deterministic() -> None:
    scenario = ContractProbeScenario(
        output="done",
        events=(ContractProbeEventSpec(sequence=4), ContractProbeEventSpec(sequence=2)),
    )
    observations = []
    for _ in range(2):
        adapter = ContractProbeAdapter(scenario)
        request = TestContractProbeAdapter().make_request()
        handle = await adapter.start(request)
        try:
            events = [event async for event in adapter.stream_events(handle)]
            result = await adapter.collect_result(handle)
            observations.append((events, result))
        finally:
            await adapter.cancel(handle)

    assert observations[0] == observations[1]
    assert [event.event_id for event in observations[0][0]] == [
        uuid5(ContractProbeAdapter.EVENT_NAMESPACE, f"{EXECUTION_ID}:0"),
        uuid5(ContractProbeAdapter.EVENT_NAMESPACE, f"{EXECUTION_ID}:1"),
    ]
    assert observations[0][0][0] is not observations[1][0][0]


class _CopyControlFlow(BaseException):
    pass


class _ControlFlowPayload:
    def __deepcopy__(self, memo: object) -> object:
        raise _CopyControlFlow


@pytest.mark.asyncio
async def test_base_exception_during_scenario_snapshot_propagates() -> None:
    scenario = ContractProbeScenario(
        events=(ContractProbeEventSpec(payload={"control": _ControlFlowPayload()}),)
    )
    adapter = ContractProbeAdapter(scenario)
    with pytest.raises(_CopyControlFlow):
        await adapter.start(TestContractProbeAdapter().make_request())
    assert adapter._active is None
    assert adapter._tasks == set()


@pytest.mark.asyncio
async def test_registry_resolves_fresh_probe_instances_with_isolated_executions() -> None:
    engines = EngineRegistry()
    protocols = ProtocolRegistry()
    engines.register(EngineDescriptor(engine_id="contract-probe"))
    protocols.register(ProtocolDescriptor(protocol_id="contract-scripted"))
    registry = AdapterRegistry(engines, protocols)
    registry.register(
        AdapterDescriptor(
            engine_id="contract-probe",
            protocol_id="contract-scripted",
            adapter_version="v1",
        ),
        lambda: ContractProbeAdapter(
            ContractProbeScenario(
                output="registered",
                events=(ContractProbeEventSpec(sequence=3),),
            )
        ),
    )

    first = registry.resolve("contract-probe", "contract-scripted", "v1")
    second = registry.resolve("contract-probe", "contract-scripted", "v1")
    assert isinstance(first, ContractProbeAdapter)
    assert isinstance(second, ContractProbeAdapter)
    assert first is not second
    assert weakref.ref(first)() is first
    assert weakref.ref(second)() is second

    requests = TestContractProbeAdapter()
    first_handle = await first.start(requests.make_request())
    second_handle = await second.start(
        requests.make_request(execution_id=UUID("30000000-0000-4000-8000-000000000099"))
    )
    try:
        assert first._active is not None
        assert second._active is not None
        assert first._active is not second._active
        first_stream = first.stream_events(first_handle)
        second_stream = second.stream_events(second_handle)
        first_events = [event async for event in first_stream]
        second_events = [event async for event in second_stream]
        assert first_events[0] is not second_events[0]
        assert first_events[0].event_id != second_events[0].event_id
        assert (await first.collect_result(first_handle)).output == "registered"
        assert (await second.collect_result(second_handle)).output == "registered"
    finally:
        await first.cancel(first_handle)
        await second.cancel(second_handle)


async def _yield_until(condition: Callable[[], bool]) -> None:
    async def poll() -> None:
        while not condition():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=0.2)


@pytest.mark.parametrize(
    "stream_error,expected_status",
    [
        (None, "completed"),
        (
            ExecutionError(
                category=ExecutionErrorCategory.INTERNAL_ERROR,
                code=ExecutionErrorCode.INTERNAL_ERROR,
            ),
            "failed",
        ),
    ],
    ids=["successful-completion", "following-stream-failure"],
)
@pytest.mark.asyncio
async def test_cancelled_anext_after_channel_handoff_does_not_strand_item(
    stream_error: ExecutionError | None, expected_status: str
) -> None:
    gate = asyncio.Event()
    adapter = ContractProbeAdapter(
        ContractProbeScenario(
            output="done",
            events=(ContractProbeEventSpec(gate=gate),),
            stream_error=stream_error,
        )
    )
    handle = await adapter.start(TestContractProbeAdapter().make_request())
    run = adapter._active
    assert run is not None
    stream = adapter.stream_events(handle)
    waiter = asyncio.create_task(anext(stream))
    collector: asyncio.Task[object] | None = None
    closer: asyncio.Task[None] | None = None
    try:
        await _yield_until(lambda: len(run.channel.receivers) == 1)
        gate.set()
        asyncio.get_running_loop().call_soon(waiter.cancel)
        waiter_outcomes = await asyncio.wait_for(
            asyncio.gather(waiter, return_exceptions=True), timeout=0.2
        )
        assert len(waiter_outcomes) == 1
        assert isinstance(waiter_outcomes[0], asyncio.CancelledError)

        await _yield_until(lambda: run.program_finished)
        collector = asyncio.create_task(adapter.collect_result(handle))
        closer = asyncio.create_task(stream.aclose())
        for _ in range(3):
            await asyncio.sleep(0)

        result = await asyncio.wait_for(collector, timeout=0.2)
        await asyncio.wait_for(closer, timeout=0.2)
        assert result.status == expected_status
        assert run.result.done()
        assert run.producer is not None and run.producer.done()
        assert run.outstanding == 0
        assert not run.channel.buffer
        assert not run.channel.receivers
        assert all(task.done() for task in adapter._tasks)
        assert all(task.done() for task in (waiter, collector, closer))
    finally:
        gate.set()
        if not run.result.done():
            await asyncio.wait_for(adapter.cancel(handle), timeout=0.2)
        tasks = [task for task in (waiter, collector, closer) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if run.producer is not None and not run.producer.done():
            run.producer.cancel()
        if run.producer is not None:
            await asyncio.gather(run.producer, return_exceptions=True)
