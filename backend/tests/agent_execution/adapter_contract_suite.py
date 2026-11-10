"""Reusable behavioral contract suite for AgentEngineAdapter implementations."""

import asyncio
import traceback
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Coroutine
from contextlib import suppress
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, TypeVar, cast
from uuid import UUID

import pytest
import pytest_asyncio

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

SECRET_MARKER = "synthetic-" + "secret-marker"
T = TypeVar("T")


class AdapterContractSuite(ABC):
    """Abstract adapter suite; subclasses provide only scenario and clock controls."""

    __test__ = False

    @abstractmethod
    def make_scenario(self, **controls: Any) -> object:
        """Build one declarative scenario without constructing an adapter."""

    @abstractmethod
    def make_event_spec(self, **controls: Any) -> object:
        """Build one ordered event specification."""

    @abstractmethod
    def make_gate(self) -> Any:
        """Build a manually controlled gate compatible with scenario controls."""

    @abstractmethod
    def build_adapter(self, scenario: object) -> AgentEngineAdapter:
        """Construct a fresh adapter for a scenario."""

    @abstractmethod
    def make_request(self, **overrides: Any) -> ExecutionRequest:
        """Construct an identity-matching request."""

    @abstractmethod
    def advance_clock(self, adapter: AgentEngineAdapter, seconds: int) -> None:
        """Advance the adapter's manual clock without wall-clock waiting."""

    @abstractmethod
    def assert_owned_tasks_finished(self, adapter: AgentEngineAdapter) -> None:
        """Assert that all tasks owned by an adapter have finished."""

    @pytest_asyncio.fixture(autouse=True)
    async def cleanup(self) -> AsyncIterator[None]:
        self._adapters: list[AgentEngineAdapter] = []
        self._handles: list[tuple[AgentEngineAdapter, ExecutionHandle]] = []
        self._streams: list[AsyncIterator[AgentEvent]] = []
        self._tasks: set[asyncio.Task[Any]] = set()
        baseline = asyncio.all_tasks()
        yield
        for stream in reversed(self._streams):
            with suppress(BaseException):
                await cast(Any, stream).aclose()
        for adapter, handle in reversed(self._handles):
            with suppress(BaseException):
                await asyncio.wait_for(adapter.cancel(handle), timeout=1)
        await self._drain_test_tasks()
        await asyncio.sleep(0)
        for adapter in self._adapters:
            self.assert_owned_tasks_finished(adapter)
        current = asyncio.current_task()
        leaked = [
            task
            for task in asyncio.all_tasks()
            if task not in baseline and task is not current and not task.done()
        ]
        assert leaked == [], f"pending test or adapter tasks: {leaked!r}"

    def adapter(self, scenario: object) -> AgentEngineAdapter:
        instance = self.build_adapter(scenario)
        self._adapters.append(instance)
        return instance

    async def start(
        self, adapter: AgentEngineAdapter, request: ExecutionRequest
    ) -> ExecutionHandle:
        handle = await adapter.start(request)
        self._handles.append((adapter, handle))
        return handle

    def stream(
        self, adapter: AgentEngineAdapter, handle: ExecutionHandle
    ) -> AsyncIterator[AgentEvent]:
        stream = adapter.stream_events(handle)
        self._streams.append(stream)
        return stream

    def task(self, coroutine: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        return task

    async def _drain_test_tasks(self) -> None:
        pending = [task for task in self._tasks if not task.done()]
        for task in pending:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def events(self, stream: AsyncIterator[AgentEvent]) -> list[AgentEvent]:
        async def collect() -> list[AgentEvent]:
            return [event async for event in stream]

        return await asyncio.wait_for(collect(), timeout=1)

    def scenario(self, **controls: Any) -> object:
        return self.make_scenario(**controls)

    def event(self, **controls: Any) -> object:
        return self.make_event_spec(**controls)

    def success_scenario(self, **controls: Any) -> object:
        return self.scenario(output="scripted output", **controls)

    @staticmethod
    def assert_safe_error(
        caught: pytest.ExceptionInfo[AdapterExecutionError],
        category: ExecutionErrorCategory,
        code: ExecutionErrorCode,
        message: str,
        *,
        retryable: bool = False,
        error_type: type[AdapterExecutionError] = AdapterExecutionError,
    ) -> None:
        error = caught.value
        assert isinstance(error, error_type)
        assert error.error.category == category
        assert error.error.code == code
        assert error.error.message == message
        assert str(error) == message
        assert error.error.retryable is retryable
        assert error.__suppress_context__ is True

    @pytest.mark.asyncio
    async def test_capabilities_start_stream_collect_success(self) -> None:
        capabilities = EngineCapabilities(streaming=True, cancellation=True, native_events=True)
        adapter = self.adapter(
            self.success_scenario(
                capabilities=capabilities,
                events=(
                    self.event(
                        sequence=1,
                        event_type="engine.output_delta",
                        payload={"text": "hello"},
                    ),
                ),
                usage={"tokens": 3},
                artifacts=({"name": "result.txt"},),
                engine_metadata={"mode": "scripted"},
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
        original_request = deepcopy(request)
        assert await adapter.get_capabilities() == capabilities
        handle = await self.start(adapter, request)
        assert request == original_request
        assert handle.execution_id == request.execution_id
        assert handle.engine_id == request.engine_id
        assert handle.protocol_id == request.protocol_id
        assert handle.adapter_version == request.adapter_version
        assert handle.provider_session_id == request.engine_session_id
        assert handle.process_id is None
        assert handle.status == "running"

        with pytest.raises(ConfigurationError) as caught:
            await adapter.start(request)
        self.assert_safe_error(
            caught,
            ExecutionErrorCategory.CONFIGURATION_ERROR,
            ExecutionErrorCode.INVALID_ADAPTER_STATE,
            "Adapter state does not allow this operation.",
            error_type=ConfigurationError,
        )

        events = await self.events(self.stream(adapter, handle))
        assert len(events) == 1
        assert events[0].payload == {"text": "hello"}
        assert events[0].engine_session_id == "provider-session"
        assert events[0].trace_id == "trace"
        result = await asyncio.wait_for(adapter.collect_result(handle), timeout=1)
        assert result.status == "completed"
        assert result.output == "scripted output"
        assert result.error is None
        assert result.usage == {"tokens": 3}
        assert result.artifacts == [{"name": "result.txt"}]
        assert result.engine_metadata == {"mode": "scripted"}

    @pytest.mark.asyncio
    async def test_immediate_concurrent_and_repeated_collectors_share_result(self) -> None:
        gate = self.make_gate()
        adapter = self.adapter(self.success_scenario(completion_gate=gate))
        handle = await self.start(adapter, self.make_request())
        collectors = [self.task(adapter.collect_result(handle)) for _ in range(3)]
        gate.set()
        results = await asyncio.wait_for(asyncio.gather(*collectors), timeout=1)
        assert results == [results[0]] * 3
        assert results[0].status == "completed"
        repeated = await asyncio.gather(
            adapter.collect_result(handle), adapter.collect_result(handle)
        )
        assert repeated == [results[0], results[0]]
        self.assert_owned_tasks_finished(adapter)

    @pytest.mark.asyncio
    async def test_concurrent_second_consumer_and_claim_after_aclose_are_rejected(self) -> None:
        gate = self.make_gate()
        adapter = self.adapter(self.success_scenario(completion_gate=gate))
        handle = await self.start(adapter, self.make_request())

        async def claim() -> AsyncIterator[AgentEvent]:
            return self.stream(adapter, handle)

        claims = await asyncio.gather(
            self.task(claim()), self.task(claim()), return_exceptions=True
        )
        winners = [claim for claim in claims if not isinstance(claim, BaseException)]
        losers = [claim for claim in claims if isinstance(claim, BaseException)]
        assert len(winners) == 1
        assert len(losers) == 1
        assert isinstance(losers[0], ConfigurationError)
        assert losers[0].error.code == ExecutionErrorCode.INVALID_ADAPTER_STATE

        await cast(Any, winners[0]).aclose()
        with pytest.raises(ConfigurationError) as caught:
            adapter.stream_events(handle)
        self.assert_safe_error(
            caught,
            ExecutionErrorCategory.CONFIGURATION_ERROR,
            ExecutionErrorCode.INVALID_ADAPTER_STATE,
            "Adapter state does not allow this operation.",
            error_type=ConfigurationError,
        )
        gate.set()

    @pytest.mark.asyncio
    async def test_multiple_events_preserve_order_payload_and_empty_stream_terminates(self) -> None:
        specs = tuple(
            self.event(sequence=index, payload={"index": index}, event_type="engine.progress")
            for index in range(1, 5)
        )
        adapter = self.adapter(self.success_scenario(events=specs))
        handle = await self.start(adapter, self.make_request())
        events = await self.events(self.stream(adapter, handle))
        assert [event.sequence for event in events] == [1, 2, 3, 4]
        assert [event.payload for event in events] == [{"index": index} for index in range(1, 5)]
        assert (await adapter.collect_result(handle)).status == "completed"

        empty_adapter = self.adapter(self.success_scenario(events=()))
        empty_handle = await self.start(empty_adapter, self.make_request())
        assert await self.events(self.stream(empty_adapter, empty_handle)) == []
        assert (await empty_adapter.collect_result(empty_handle)).output == "scripted output"

    @pytest.mark.asyncio
    async def test_request_identity_mismatch_fails_before_handle(self) -> None:
        adapter = self.adapter(self.success_scenario())
        for field, value in (
            ("engine_id", "other-engine"),
            ("protocol_id", "other-protocol"),
            ("adapter_version", "v2"),
        ):
            request = self.make_request(**{field: value})
            with pytest.raises(ConfigurationError) as caught:
                await adapter.start(request)
            self.assert_safe_error(
                caught,
                ExecutionErrorCategory.CONFIGURATION_ERROR,
                ExecutionErrorCode.INVALID_REQUEST,
                "Execution request is invalid.",
                error_type=ConfigurationError,
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "category,code,message,retryable",
        [
            (
                ExecutionErrorCategory.ENGINE_UNAVAILABLE,
                ExecutionErrorCode.ENGINE_UNAVAILABLE,
                "Engine is unavailable.",
                True,
            ),
            (
                ExecutionErrorCategory.ENGINE_UNAVAILABLE,
                ExecutionErrorCode.ENGINE_UNAVAILABLE,
                "Engine is unavailable.",
                False,
            ),
            (
                ExecutionErrorCategory.RESOURCE_EXHAUSTED,
                ExecutionErrorCode.RESOURCE_EXHAUSTED,
                "Engine resources are exhausted.",
                True,
            ),
            (
                ExecutionErrorCategory.RESOURCE_EXHAUSTED,
                ExecutionErrorCode.RESOURCE_EXHAUSTED,
                "Engine resources are exhausted.",
                False,
            ),
        ],
    )
    async def test_prestart_errors_precede_handle_and_preserve_retryability(
        self,
        category: ExecutionErrorCategory,
        code: ExecutionErrorCode,
        message: str,
        retryable: bool,
    ) -> None:
        expected = ExecutionError(category=category, code=code, retryable=retryable)
        adapter = self.adapter(self.scenario(prestart_error=expected))
        with pytest.raises(AdapterExecutionError) as caught:
            await adapter.start(self.make_request())
        self.assert_safe_error(caught, category, code, message, retryable=retryable)
        self.assert_owned_tasks_finished(adapter)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "category,code,message,error_type",
        [
            (
                ExecutionErrorCategory.CONFIGURATION_ERROR,
                ExecutionErrorCode.INVALID_REQUEST,
                "Execution request is invalid.",
                ConfigurationError,
            ),
            (
                ExecutionErrorCategory.PROTOCOL_ERROR,
                ExecutionErrorCode.PROTOCOL_ERROR,
                "Adapter protocol failed.",
                AdapterExecutionError,
            ),
            (
                ExecutionErrorCategory.AUTHENTICATION_ERROR,
                ExecutionErrorCode.AUTHENTICATION_FAILED,
                "Engine authentication failed.",
                AdapterExecutionError,
            ),
            (
                ExecutionErrorCategory.PERMISSION_DENIED,
                ExecutionErrorCode.PERMISSION_DENIED,
                "Engine permission was denied.",
                AdapterExecutionError,
            ),
            (
                ExecutionErrorCategory.WORKSPACE_ERROR,
                ExecutionErrorCode.WORKSPACE_ERROR,
                "Engine workspace operation failed.",
                AdapterExecutionError,
            ),
            (
                ExecutionErrorCategory.INTERNAL_ERROR,
                ExecutionErrorCode.INTERNAL_ERROR,
                "Execution failed internally.",
                AdapterExecutionError,
            ),
        ],
    )
    async def test_stream_errors_are_safe_for_stream_and_all_collectors(
        self,
        category: ExecutionErrorCategory,
        code: ExecutionErrorCode,
        message: str,
        error_type: type[AdapterExecutionError],
    ) -> None:
        expected = ExecutionError(category=category, code=code)
        adapter = self.adapter(self.scenario(stream_error=expected))
        handle = await self.start(adapter, self.make_request())
        collector = self.task(adapter.collect_result(handle))
        stream = self.stream(adapter, handle)
        with pytest.raises(AdapterExecutionError) as caught:
            await self.events(stream)
        self.assert_safe_error(caught, category, code, message, error_type=error_type)
        result = await asyncio.wait_for(collector, timeout=1)
        assert result.status == "failed"
        assert result.output is None
        assert result.error == expected
        assert result.error is not None and result.error.retryable is False
        assert SECRET_MARKER not in repr(result)
        self.assert_owned_tasks_finished(adapter)

    @pytest.mark.asyncio
    async def test_pre_chained_safe_stream_error_does_not_retain_raw_exception_chain(self) -> None:
        expected = ExecutionError(
            category=ExecutionErrorCategory.INTERNAL_ERROR,
            code=ExecutionErrorCode.INTERNAL_ERROR,
        )

        def _original_failure_frame(error: AdapterExecutionError) -> None:
            try:
                raise RuntimeError(SECRET_MARKER)
            except RuntimeError as original:
                raise error from original

        pre_chained = AdapterExecutionError(expected)
        try:
            _original_failure_frame(pre_chained)
        except AdapterExecutionError as caught:
            pre_chained = caught

        adapter = self.adapter(self.scenario(stream_error=pre_chained))
        handle = await self.start(adapter, self.make_request())
        collector = self.task(adapter.collect_result(handle))
        with pytest.raises(AdapterExecutionError) as caught:
            await self.events(self.stream(adapter, handle))
        rendered = "".join(traceback.format_exception(caught.value))
        assert SECRET_MARKER not in rendered
        assert "RuntimeError" not in rendered
        assert "_original_failure_frame" not in rendered
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert caught.value.__suppress_context__ is True
        assert caught.value.error == expected
        result = await asyncio.wait_for(collector, timeout=1)
        assert result.status == "failed"
        assert result.error == expected

    @pytest.mark.asyncio
    async def test_unknown_exception_and_simulated_process_failure_are_distinct_and_safe(
        self,
    ) -> None:
        unknown_adapter = self.adapter(self.scenario(stream_error=RuntimeError(SECRET_MARKER)))
        unknown_handle = await self.start(unknown_adapter, self.make_request())
        unknown_collector = self.task(unknown_adapter.collect_result(unknown_handle))
        with pytest.raises(AdapterExecutionError) as caught:
            await self.events(self.stream(unknown_adapter, unknown_handle))
        self.assert_safe_error(
            caught,
            ExecutionErrorCategory.INTERNAL_ERROR,
            ExecutionErrorCode.INTERNAL_ERROR,
            "Execution failed internally.",
        )
        rendered = "".join(traceback.format_exception(caught.value))
        assert SECRET_MARKER not in rendered
        assert "RuntimeError" not in rendered
        unknown_result = await asyncio.wait_for(unknown_collector, timeout=1)
        assert unknown_result.error == ExecutionError(
            category=ExecutionErrorCategory.INTERNAL_ERROR,
            code=ExecutionErrorCode.INTERNAL_ERROR,
        )
        assert SECRET_MARKER not in unknown_result.model_dump_json()

        failure_adapter = self.adapter(self.scenario(simulated_process_failure=True))
        failure_handle = await self.start(failure_adapter, self.make_request())
        failure_collector = self.task(failure_adapter.collect_result(failure_handle))
        with pytest.raises(AdapterExecutionError) as failure_caught:
            await self.events(self.stream(failure_adapter, failure_handle))
        self.assert_safe_error(
            failure_caught,
            ExecutionErrorCategory.INTERNAL_ERROR,
            ExecutionErrorCode.SIMULATED_PROCESS_FAILURE,
            "Simulated process failure occurred.",
        )
        failure_result = await asyncio.wait_for(failure_collector, timeout=1)
        assert failure_result.status == "failed"
        assert failure_result.error is not None
        assert failure_result.error.code == ExecutionErrorCode.SIMULATED_PROCESS_FAILURE
        assert failure_result.error.retryable is False

    @pytest.mark.asyncio
    async def test_manual_clock_timeout_wakes_collectors_without_real_waiting(self) -> None:
        gate = self.make_gate()
        adapter = self.adapter(self.success_scenario(completion_gate=gate, manual_timeout=True))
        request = self.make_request(timeout_seconds=3600)
        handle = await self.start(adapter, request)
        collectors = [self.task(adapter.collect_result(handle)) for _ in range(2)]
        self.advance_clock(adapter, 3600)
        results = await asyncio.wait_for(asyncio.gather(*collectors), timeout=1)
        assert results[0] == results[1]
        assert results[0].status == "failed"
        assert results[0].output is None
        assert results[0].error == ExecutionError(
            category=ExecutionErrorCategory.TIMEOUT,
            code=ExecutionErrorCode.EXECUTION_TIMEOUT,
            retryable=False,
        )
        gate.set()
        await adapter.cancel(handle)
        assert (await adapter.collect_result(handle)).status == "failed"
        self.assert_owned_tasks_finished(adapter)

    @pytest.mark.asyncio
    async def test_repeated_concurrent_cancel_closes_stream_and_collectors(self) -> None:
        completion_gate = self.make_gate()
        event_gate = self.make_gate()
        adapter = self.adapter(
            self.success_scenario(
                completion_gate=completion_gate,
                events=(self.event(gate=event_gate, payload={"late": True}),),
            )
        )
        handle = await self.start(adapter, self.make_request())
        stream = self.stream(adapter, handle)
        next_event = self.task(anext(stream))
        collectors = [self.task(adapter.collect_result(handle)) for _ in range(2)]
        cancels = [self.task(adapter.cancel(handle)) for _ in range(4)]
        await asyncio.wait_for(asyncio.gather(*cancels), timeout=1)
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(next_event, timeout=1)
        results = await asyncio.wait_for(asyncio.gather(*collectors), timeout=1)
        assert results[0] == results[1]
        assert results[0].status == "cancelled"
        assert results[0].output is None
        assert results[0].error is None
        completion_gate.set()
        event_gate.set()
        await adapter.cancel(handle)
        assert await self.events(stream) == []
        assert (await adapter.collect_result(handle)).status == "cancelled"
        self.assert_owned_tasks_finished(adapter)

    @pytest.mark.asyncio
    async def test_cancel_wins_gate_race_and_suppresses_late_events_and_success(self) -> None:
        completion_gate = self.make_gate()
        event_gate = self.make_gate()
        adapter = self.adapter(
            self.success_scenario(
                completion_gate=completion_gate,
                events=(self.event(gate=event_gate),),
            )
        )
        handle = await self.start(adapter, self.make_request())
        await adapter.cancel(handle)
        completion_gate.set()
        event_gate.set()
        assert await self.events(self.stream(adapter, handle)) == []
        result = await adapter.collect_result(handle)
        assert result.status == "cancelled"
        assert result.output is None
        self.assert_owned_tasks_finished(adapter)

    @pytest.mark.asyncio
    async def test_success_wins_gate_race_and_is_never_retroactively_cancelled(self) -> None:
        gate = self.make_gate()
        adapter = self.adapter(self.success_scenario(completion_gate=gate))
        handle = await self.start(adapter, self.make_request())
        collector = self.task(adapter.collect_result(handle))
        gate.set()
        result = await asyncio.wait_for(collector, timeout=1)
        assert result.status == "completed"
        await asyncio.gather(*(adapter.cancel(handle) for _ in range(3)))
        assert await adapter.collect_result(handle) == result
        assert result.status == "completed"
        self.assert_owned_tasks_finished(adapter)

    @pytest.mark.asyncio
    async def test_duplicates_late_events_gaps_and_timestamps_follow_sequence_rules(self) -> None:
        overridden_id = UUID("10000000-0000-4000-8000-000000000001")
        late_id = UUID("10000000-0000-4000-8000-000000000002")
        specs = (
            self.event(
                event_id=overridden_id,
                sequence=2,
                timestamp=datetime(2030, 1, 1, tzinfo=UTC),
                payload={"kind": "original"},
            ),
            self.event(duplicate_of=0),
            self.event(
                event_id=late_id,
                sequence=1,
                timestamp=datetime(2040, 1, 1, tzinfo=UTC),
                payload={"kind": "late"},
            ),
            self.event(
                sequence=7,
                timestamp=datetime(2020, 1, 1, tzinfo=UTC),
                payload={"kind": "gap"},
            ),
            self.event(sequence=3, payload={"kind": "still-late"}),
            self.event(sequence=8, payload={"kind": "new-high-water"}),
        )
        adapter = self.adapter(self.success_scenario(events=specs))
        handle = await self.start(adapter, self.make_request())
        events = await self.events(self.stream(adapter, handle))
        assert [event.sequence for event in events] == [2, 2, 1, 7, 3, 8]
        assert events[1] == events[0]
        assert events[1] is events[0]
        assert events[2].event_id != events[0].event_id
        assert events[2].timestamp > events[3].timestamp
        assert (await adapter.collect_result(handle)).status == "completed"

    @pytest.mark.asyncio
    async def test_same_event_id_with_different_content_is_never_repaired(self) -> None:
        event_id = UUID("10000000-0000-4000-8000-000000000010")
        adapter = self.adapter(
            self.success_scenario(
                events=(
                    self.event(event_id=event_id, sequence=1, payload={"version": 1}),
                    self.event(event_id=event_id, sequence=2, payload={"version": 2}),
                )
            )
        )
        handle = await self.start(adapter, self.make_request())
        collector = self.task(adapter.collect_result(handle))
        stream = self.stream(adapter, handle)
        first = await asyncio.wait_for(anext(stream), timeout=1)
        assert first.payload == {"version": 1}
        with pytest.raises(AdapterExecutionError) as caught:
            await asyncio.wait_for(anext(stream), timeout=1)
        self.assert_safe_error(
            caught,
            ExecutionErrorCategory.PROTOCOL_ERROR,
            ExecutionErrorCode.EVENT_IDENTITY_CONFLICT,
            "Event identity conflicts with different content.",
        )
        result = await asyncio.wait_for(collector, timeout=1)
        assert result.status == "failed"
        assert result.error is not None
        assert result.error.code == ExecutionErrorCode.EVENT_IDENTITY_CONFLICT
        self.assert_owned_tasks_finished(adapter)

    @pytest.mark.asyncio
    async def test_terminal_visibility_never_precedes_queued_or_active_stream_events(self) -> None:
        specs = tuple(self.event(sequence=index, payload={"index": index}) for index in range(1, 6))
        active_adapter = self.adapter(self.success_scenario(events=specs))
        active_handle = await self.start(active_adapter, self.make_request())
        observations: list[str] = []
        active_stream = self.stream(active_adapter, active_handle)

        async def consume() -> None:
            async for event in active_stream:
                observations.append(f"event:{event.sequence}")
            result = await active_adapter.collect_result(active_handle)
            observations.append(f"result:{result.status}")

        await asyncio.wait_for(consume(), timeout=1)
        assert observations == [f"event:{index}" for index in range(1, 6)] + ["result:completed"]

        immediate_adapter = self.adapter(self.success_scenario(events=specs))
        immediate_handle = await self.start(immediate_adapter, self.make_request())
        result = await asyncio.wait_for(
            immediate_adapter.collect_result(immediate_handle), timeout=1
        )
        assert result.status == "completed"
        assert await self.events(self.stream(immediate_adapter, immediate_handle)) == []

    @pytest.mark.asyncio
    async def test_early_aclose_cleans_owned_tasks_and_does_not_permit_replay(self) -> None:
        second_gate = self.make_gate()
        adapter = self.adapter(
            self.success_scenario(
                events=(
                    self.event(sequence=1, payload={"index": 1}),
                    self.event(sequence=2, gate=second_gate, payload={"index": 2}),
                )
            )
        )
        handle = await self.start(adapter, self.make_request())
        stream = self.stream(adapter, handle)
        assert (await asyncio.wait_for(anext(stream), timeout=1)).sequence == 1
        await cast(Any, stream).aclose()
        second_gate.set()
        with pytest.raises(ConfigurationError) as caught:
            adapter.stream_events(handle)
        assert caught.value.error.code == ExecutionErrorCode.INVALID_ADAPTER_STATE
        self.assert_owned_tasks_finished(adapter)

    @pytest.mark.asyncio
    async def test_one_cancelled_collector_does_not_cancel_shared_execution(self) -> None:
        gate = self.make_gate()
        adapter = self.adapter(self.success_scenario(completion_gate=gate))
        handle = await self.start(adapter, self.make_request())
        cancelled = self.task(adapter.collect_result(handle))
        survivors = [self.task(adapter.collect_result(handle)) for _ in range(2)]
        await asyncio.sleep(0)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        gate.set()
        results = await asyncio.wait_for(asyncio.gather(*survivors), timeout=1)
        assert results[0] == results[1]
        assert results[0].status == "completed"
        self.assert_owned_tasks_finished(adapter)

    @pytest.mark.asyncio
    async def test_lone_collector_cancellation_cleans_owned_work_before_propagation(self) -> None:
        gate = self.make_gate()
        adapter = self.adapter(self.success_scenario(completion_gate=gate))
        handle = await self.start(adapter, self.make_request())
        collector = self.task(adapter.collect_result(handle))
        await asyncio.sleep(0)
        collector.cancel()
        with pytest.raises(asyncio.CancelledError):
            await collector
        self.assert_owned_tasks_finished(adapter)
        gate.set()
        await asyncio.sleep(0)
        self.assert_owned_tasks_finished(adapter)

    @pytest.mark.asyncio
    async def test_deterministic_fresh_runs_have_no_cross_instance_high_water(self) -> None:
        specs = (
            self.event(sequence=5, payload={"run": "same"}),
            self.event(sequence=2, payload={"late": True}),
        )
        observations: list[tuple[list[AgentEvent], ExecutionResult]] = []
        for _ in range(2):
            adapter = self.adapter(self.success_scenario(events=specs))
            handle = await self.start(adapter, self.make_request())
            events = await self.events(self.stream(adapter, handle))
            result = await adapter.collect_result(handle)
            observations.append((events, result))
        assert observations[0] == observations[1]
        assert [event.sequence for event in observations[1][0]] == [5, 2]
        for first, second in zip(observations[0][0], observations[1][0], strict=True):
            assert first is not second

    @pytest.mark.asyncio
    async def test_pending_anext_is_woken_by_aclose_without_external_cancel(self) -> None:
        gate = self.make_gate()
        adapter = self.adapter(self.success_scenario(events=(self.event(gate=gate),)))
        handle = await self.start(adapter, self.make_request())
        stream = self.stream(adapter, handle)
        pending = self.task(anext(stream))
        await asyncio.sleep(0)
        try:
            await asyncio.wait_for(cast(Any, stream).aclose(), timeout=0.2)
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(pending, timeout=0.2)
        finally:
            gate.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await adapter.cancel(handle)

    @pytest.mark.asyncio
    async def test_claimed_empty_stream_does_not_block_successful_collection(self) -> None:
        adapter = self.adapter(self.success_scenario(events=()))
        handle = await self.start(adapter, self.make_request())
        stream = self.stream(adapter, handle)
        collector = self.task(adapter.collect_result(handle))
        try:
            result = await asyncio.wait_for(collector, timeout=0.2)
            assert result.status == "completed"
            assert result.output == "scripted output"
        finally:
            if not collector.done():
                collector.cancel()
            await asyncio.gather(collector, return_exceptions=True)
            await cast(Any, stream).aclose()
            await adapter.cancel(handle)

    @pytest.mark.asyncio
    async def test_delivered_only_event_does_not_require_an_extra_poll_before_result(self) -> None:
        adapter = self.adapter(
            self.success_scenario(events=(self.event(sequence=1, payload={"only": True}),))
        )
        handle = await self.start(adapter, self.make_request())
        stream = self.stream(adapter, handle)
        collector: asyncio.Task[ExecutionResult] | None = None
        try:
            event = await asyncio.wait_for(anext(stream), timeout=0.2)
            assert event.payload == {"only": True}
            collector = self.task(adapter.collect_result(handle))
            result = await asyncio.wait_for(collector, timeout=0.2)
            assert result.status == "completed"
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(stream), timeout=0.2)
            assert await adapter.collect_result(handle) == result
        finally:
            if collector is not None:
                if not collector.done():
                    collector.cancel()
                await asyncio.gather(collector, return_exceptions=True)
            await cast(Any, stream).aclose()
            await adapter.cancel(handle)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "overrides",
        [
            {"execution_id": UUID("20000000-0000-4000-8000-000000000001")},
            {"engine_id": "other-engine"},
            {"protocol_id": "other-protocol"},
            {"adapter_version": "v2"},
            {"provider_session_id": "forged-session"},
        ],
    )
    async def test_invalid_handles_are_rejected_by_stream_collect_and_cancel(
        self, overrides: dict[str, Any]
    ) -> None:
        adapter = self.adapter(self.success_scenario(completion_gate=self.make_gate()))
        handle = await self.start(adapter, self.make_request(engine_session_id="real-session"))
        forged = handle.model_copy(update=overrides)
        for operation in (adapter.stream_events,):
            with pytest.raises(ConfigurationError) as caught:
                operation(forged)
            assert caught.value.error.code == ExecutionErrorCode.INVALID_HANDLE
        for operation in (adapter.collect_result, adapter.cancel):
            with pytest.raises(ConfigurationError) as caught:
                await operation(forged)
            assert caught.value.error.code == ExecutionErrorCode.INVALID_HANDLE
        await adapter.cancel(handle)

    @pytest.mark.asyncio
    async def test_raw_request_and_handle_values_fail_safely(self) -> None:
        adapter = self.adapter(self.success_scenario(completion_gate=self.make_gate()))
        raw_request = cast(ExecutionRequest, {"secret": SECRET_MARKER})
        with pytest.raises(ConfigurationError) as request_caught:
            await adapter.start(raw_request)
        self.assert_safe_error(
            request_caught,
            ExecutionErrorCategory.CONFIGURATION_ERROR,
            ExecutionErrorCode.INVALID_REQUEST,
            "Execution request is invalid.",
            error_type=ConfigurationError,
        )
        assert SECRET_MARKER not in repr(request_caught.value)

        handle = await self.start(adapter, self.make_request())
        raw_handle = cast(ExecutionHandle, {"secret": SECRET_MARKER})
        with pytest.raises(ConfigurationError) as stream_caught:
            adapter.stream_events(raw_handle)
        assert stream_caught.value.error.code == ExecutionErrorCode.INVALID_HANDLE
        for operation in (adapter.collect_result, adapter.cancel):
            with pytest.raises(ConfigurationError) as caught:
                await operation(raw_handle)
            assert caught.value.error.code == ExecutionErrorCode.INVALID_HANDLE
            assert SECRET_MARKER not in repr(caught.value)
        await adapter.cancel(handle)
