"""Deterministic scripted adapter for local execution contract tests."""

import asyncio
from collections.abc import AsyncIterator, Coroutine
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid5

from pydantic import JsonValue

from ...contracts import (
    AdapterExecutionError,
    AgentEvent,
    ConfigurationError,
    EngineCapabilities,
    ExecutionError,
    ExecutionErrorCategory,
    ExecutionErrorCode,
    ExecutionHandle,
    ExecutionRequest,
    ExecutionResult,
    ensure_handle_identity,
    ensure_request_identity,
    normalize_adapter_exception,
)

_FIXED_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
_END = object()


@dataclass(frozen=True)
class LocalTestEventSpec:
    """Declarative event controls; gates are never used for ordering."""

    sequence: int | None = None
    event_id: UUID | None = None
    timestamp: datetime | None = None
    event_type: str = "engine.output_delta"
    source: Literal["platform", "engine_native"] = "engine_native"
    payload: dict[str, JsonValue] = field(default_factory=dict)
    trace_id: str | None = None
    gate: asyncio.Event | None = field(default=None, compare=False, repr=False)
    duplicate_of: int | None = None


@dataclass(frozen=True)
class LocalTestScenario:
    """Complete deterministic behavior for one adapter instance."""

    capabilities: EngineCapabilities = field(default_factory=EngineCapabilities)
    events: tuple[LocalTestEventSpec, ...] = ()
    output: str | None = None
    error: ExecutionError | None = None
    usage: dict[str, JsonValue] = field(default_factory=dict)
    artifacts: tuple[dict[str, JsonValue], ...] = ()
    engine_metadata: dict[str, JsonValue] = field(default_factory=dict)
    prestart_error: ExecutionError | Exception | None = field(
        default=None, compare=False, repr=False
    )
    stream_error: ExecutionError | Exception | None = field(default=None, compare=False, repr=False)
    completion_gate: asyncio.Event | None = field(default=None, compare=False, repr=False)
    manual_timeout: bool = False
    simulated_process_failure: bool = False


@dataclass(eq=False)
class _ClockDeadline:
    clock: "LocalTestClock"
    at: float
    future: asyncio.Future[None]


class LocalTestClock:
    """A manually advanced clock; no wall-clock source is consulted."""

    def __init__(self) -> None:
        self._now = 0.0
        self._deadlines: set[_ClockDeadline] = set()

    def after(self, seconds: int) -> _ClockDeadline:
        """Schedule a timeout relative to the current manual time."""
        future = asyncio.get_running_loop().create_future()
        deadline = _ClockDeadline(self, self._now + seconds, future)
        self._deadlines.add(deadline)
        if seconds <= 0:
            future.set_result(None)
        return deadline

    def advance(self, seconds: int) -> None:
        """Advance time and release every newly expired timeout."""
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
            raise ValueError("seconds must be a non-negative integer")
        self._now += seconds
        for deadline in tuple(self._deadlines):
            if deadline.at <= self._now and not deadline.future.done():
                deadline.future.set_result(None)

    async def wait(self, deadline: _ClockDeadline) -> None:
        """Raise the built-in timeout when the supplied deadline expires."""
        try:
            await deadline.future
        finally:
            self._deadlines.discard(deadline)
        raise TimeoutError


class _SimulatedProcessFailure(Exception):
    pass


@dataclass(frozen=True)
class _StreamFailure:
    error: AdapterExecutionError


class _Execution:
    """All mutable state for one execution; no state is process-global."""

    def __init__(
        self,
        request: ExecutionRequest,
        handle: ExecutionHandle,
        scenario: LocalTestScenario,
        deadline: _ClockDeadline | None,
    ) -> None:
        self.request = request
        self.handle = handle
        self.scenario = scenario
        self.deadline = deadline
        self.queue: asyncio.Queue[object] = asyncio.Queue()
        self.terminal: asyncio.Future[ExecutionResult] = asyncio.get_running_loop().create_future()
        self.deliveries_done = asyncio.Event()
        self.deliveries_done.set()
        self.undelivered_items = 0
        self.queue_waiters = 0
        self.script_finished = False
        self.stream_claimed = False
        self.stream_closed = False
        self.collectors = 0
        self.task: asyncio.Task[None] | None = None
        self.events_by_id: dict[UUID, AgentEvent] = {}
        self.materialized_events: list[AgentEvent] = []
        self.high_water = 0

    def queue_delivery(self, item: AgentEvent | _StreamFailure) -> None:
        """Queue one item that must be yielded or suppressed before termination."""
        self.undelivered_items += 1
        self.deliveries_done.clear()
        self.queue.put_nowait(item)

    def acknowledge(self, item: object) -> None:
        """Linearize actual delivery or atomic suppression of one scripted item."""
        if item is _END:
            return
        self.undelivered_items -= 1
        if self.undelivered_items == 0:
            self.deliveries_done.set()

    def discard_queued_items(self) -> None:
        """Suppress queued items without leaving delivery waiters blocked."""
        while not self.queue.empty():
            self.acknowledge(self.queue.get_nowait())

    def notify_queue_waiters(self) -> None:
        """Broadcast close/terminal wakeups to every already accepted getter."""
        for _ in range(self.queue_waiters):
            self.queue.put_nowait(_END)


class _EventStream:
    """Single-claim iterator whose close operation owns execution cleanup."""

    def __init__(self, adapter: "LocalTestAdapter", execution: _Execution) -> None:
        self._adapter = adapter
        self._execution = execution

    def __aiter__(self) -> "_EventStream":
        return self

    async def __anext__(self) -> AgentEvent:
        execution = self._execution
        if execution.stream_closed:
            raise StopAsyncIteration
        if execution.terminal.done():
            self._close_without_cancelling()
            raise StopAsyncIteration
        execution.queue_waiters += 1
        try:
            item = await execution.queue.get()
        finally:
            execution.queue_waiters -= 1
        execution.acknowledge(item)
        if execution.terminal.done():
            self._close_without_cancelling()
            raise StopAsyncIteration
        if item is _END:
            self._close_without_cancelling()
            raise StopAsyncIteration
        if isinstance(item, _StreamFailure):
            self._close_without_cancelling()
            raise item.error
        return cast(AgentEvent, item)

    def _close_without_cancelling(self) -> None:
        execution = self._execution
        if execution.stream_closed:
            return
        execution.stream_closed = True
        execution.discard_queued_items()
        execution.notify_queue_waiters()

    async def aclose(self) -> None:
        """Close early and cancel only unfinished execution work."""
        execution = self._execution
        if execution.stream_closed:
            return
        self._close_without_cancelling()
        if not execution.terminal.done():
            await self._adapter._stop_execution(execution)


class LocalTestAdapter:
    """Single-execution, in-memory implementation of the adapter protocol."""

    EVENT_ID_NAMESPACE = UUID("6ba7b810-9dad-41d1-80b4-00c04fd430c8")

    def __init__(self, scenario: LocalTestScenario, *, clock: LocalTestClock | None = None) -> None:
        self.scenario = scenario
        self.clock = clock or LocalTestClock()
        self._execution: _Execution | None = None
        self._owned_tasks: set[asyncio.Task[Any]] = set()

    @property
    def engine_id(self) -> str:
        return "local-test"

    @property
    def protocol_id(self) -> str:
        return "scripted"

    @property
    def adapter_version(self) -> str:
        return "v1"

    async def get_capabilities(self) -> EngineCapabilities:
        if not isinstance(self.scenario, LocalTestScenario) or not isinstance(
            self.scenario.capabilities, EngineCapabilities
        ):
            raise self._configuration_error(ExecutionErrorCode.INVALID_SCENARIO)
        return self.scenario.capabilities

    async def start(self, request: ExecutionRequest) -> ExecutionHandle:
        """Validate all scripted behavior before exposing a running handle."""
        if not isinstance(request, ExecutionRequest):
            raise self._configuration_error(ExecutionErrorCode.INVALID_REQUEST)
        ensure_request_identity(request, self)
        if self._execution is not None:
            raise self._configuration_error(ExecutionErrorCode.INVALID_ADAPTER_STATE)
        self._validate_scenario(request)
        if self.scenario.prestart_error is not None:
            raise self._safe_exception(self.scenario.prestart_error) from None

        handle = ExecutionHandle(
            execution_id=request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            provider_session_id=request.engine_session_id,
            process_id=None,
        )
        deadline = None
        if self.scenario.manual_timeout:
            deadline = self.clock.after(request.timeout_seconds or 1)
        execution = _Execution(request, handle, self.scenario, deadline)
        task = self._create_task(self._run(execution))
        execution.task = task
        self._execution = execution
        return handle

    def stream_events(self, handle: ExecutionHandle) -> AsyncIterator[AgentEvent]:
        """Claim the only consumer synchronously, before returning an iterator."""
        execution = self._execution_for(handle)
        if execution.stream_claimed:
            raise self._configuration_error(ExecutionErrorCode.INVALID_ADAPTER_STATE)
        execution.stream_claimed = True
        return _EventStream(self, execution)

    async def cancel(self, handle: ExecutionHandle) -> None:
        """Publish cancellation atomically, then clean up owned work."""
        execution = self._execution_for(handle)
        if execution.terminal.done():
            return
        self._publish_terminal(execution, self._cancelled_result(execution))
        await self._cancel_runner(execution)

    async def collect_result(self, handle: ExecutionHandle) -> ExecutionResult:
        """Share a shielded terminal future without leaking a lone cancelled waiter."""
        execution = self._execution_for(handle)
        execution.collectors += 1
        try:
            return await asyncio.shield(execution.terminal)
        except asyncio.CancelledError:
            lone_waiter = execution.collectors == 1
            no_active_stream = not execution.stream_claimed or execution.stream_closed
            if lone_waiter and no_active_stream and not execution.terminal.done():
                await self._stop_execution(execution)
            raise
        finally:
            execution.collectors -= 1

    def _create_task(self, coroutine: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        task = asyncio.create_task(coroutine)
        self._owned_tasks.add(task)
        return task

    async def _run(self, execution: _Execution) -> None:
        try:
            if execution.deadline is None:
                await self._run_script(execution)
            else:
                await self._run_with_timeout(execution)
            result = self._terminal_result(execution)
            execution.script_finished = True
            if execution.stream_claimed:
                await execution.deliveries_done.wait()
            self._publish_terminal(execution, result)
        except asyncio.CancelledError:
            self._publish_terminal(execution, self._cancelled_result(execution))
            raise
        except Exception as exception:  # noqa: BLE001 - normalize every engine failure safely.
            safe_error = self._safe_runtime_exception(exception)
            result = self._failed_result(execution, safe_error.error)
            if isinstance(exception, TimeoutError):
                self._publish_terminal(execution, result)
                return
            execution.script_finished = True
            if execution.stream_claimed and not execution.stream_closed:
                execution.queue_delivery(_StreamFailure(safe_error))
            if execution.stream_claimed:
                await execution.deliveries_done.wait()
            self._publish_terminal(execution, result)

    async def _run_with_timeout(self, execution: _Execution) -> None:
        deadline = execution.deadline
        assert deadline is not None
        script_task = self._create_task(self._run_script(execution))
        timeout_task = self._create_task(self.clock.wait(deadline))
        tasks = (script_task, timeout_task)
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if script_task.done():
                await script_task
            else:
                await timeout_task
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_script(self, execution: _Execution) -> None:
        for ordinal, spec in enumerate(execution.scenario.events):
            if execution.terminal.done():
                return
            if spec.gate is not None:
                await spec.gate.wait()
            if execution.terminal.done():
                return
            event = self._materialize_event(execution, spec, ordinal)
            execution.queue_delivery(event)
        if execution.scenario.completion_gate is not None:
            await execution.scenario.completion_gate.wait()
        if execution.terminal.done():
            return
        if execution.scenario.stream_error is not None:
            raise self._safe_exception(execution.scenario.stream_error)
        if execution.scenario.simulated_process_failure:
            raise _SimulatedProcessFailure

    def _materialize_event(
        self, execution: _Execution, spec: LocalTestEventSpec, ordinal: int
    ) -> AgentEvent:
        if spec.duplicate_of is not None:
            duplicate = execution.materialized_events[spec.duplicate_of]
            execution.materialized_events.append(duplicate)
            return duplicate

        event = self._build_event(execution.request, spec, ordinal)
        previous = execution.events_by_id.get(event.event_id)
        if previous is not None:
            if previous != event:
                raise AdapterExecutionError(
                    ExecutionError(
                        category=ExecutionErrorCategory.PROTOCOL_ERROR,
                        code=ExecutionErrorCode.EVENT_IDENTITY_CONFLICT,
                    )
                )
            execution.materialized_events.append(previous)
            return previous

        execution.events_by_id[event.event_id] = event
        execution.materialized_events.append(event)
        execution.high_water = max(execution.high_water, event.sequence)
        return event

    def _build_event(
        self, request: ExecutionRequest, spec: LocalTestEventSpec, ordinal: int
    ) -> AgentEvent:
        return AgentEvent(
            event_id=spec.event_id
            or uuid5(self.EVENT_ID_NAMESPACE, f"{request.execution_id}:{ordinal}"),
            execution_id=request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            engine_session_id=request.engine_session_id,
            sequence=spec.sequence if spec.sequence is not None else ordinal + 1,
            event_type=spec.event_type,
            source=spec.source,
            timestamp=spec.timestamp or _FIXED_EPOCH + timedelta(milliseconds=ordinal),
            payload=deepcopy(spec.payload),
            trace_id=spec.trace_id if spec.trace_id is not None else request.trace_id,
        )

    def _validate_scenario(self, request: ExecutionRequest) -> None:
        try:
            scenario = self.scenario
            if not isinstance(scenario, LocalTestScenario):
                raise TypeError
            if not isinstance(scenario.capabilities, EngineCapabilities):
                raise TypeError
            if not isinstance(scenario.events, tuple):
                raise TypeError
            if not all(isinstance(spec, LocalTestEventSpec) for spec in scenario.events):
                raise TypeError
            if scenario.output is not None and not isinstance(scenario.output, str):
                raise TypeError
            if scenario.error is not None and not isinstance(scenario.error, ExecutionError):
                raise TypeError
            if scenario.output is not None and scenario.error is not None:
                raise ValueError
            if not isinstance(scenario.manual_timeout, bool) or not isinstance(
                scenario.simulated_process_failure, bool
            ):
                raise TypeError
            if scenario.completion_gate is not None and not isinstance(
                scenario.completion_gate, asyncio.Event
            ):
                raise TypeError
            for control in (scenario.prestart_error, scenario.stream_error):
                if control is not None and not isinstance(control, (ExecutionError, Exception)):
                    raise TypeError
            for ordinal, spec in enumerate(scenario.events):
                if spec.gate is not None and not isinstance(spec.gate, asyncio.Event):
                    raise TypeError
                if spec.duplicate_of is not None:
                    if (
                        isinstance(spec.duplicate_of, bool)
                        or not isinstance(spec.duplicate_of, int)
                        or not 0 <= spec.duplicate_of < ordinal
                    ):
                        raise ValueError
                else:
                    self._build_event(request, spec, ordinal)
            self._terminal_result_for(request, scenario)
        except Exception:  # noqa: BLE001 - arbitrary scenario copying must fail safely.
            raise self._configuration_error(ExecutionErrorCode.INVALID_SCENARIO) from None

    def _terminal_result(self, execution: _Execution) -> ExecutionResult:
        return self._terminal_result_for(execution.request, execution.scenario)

    def _terminal_result_for(
        self, request: ExecutionRequest, scenario: LocalTestScenario
    ) -> ExecutionResult:
        return ExecutionResult(
            execution_id=request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            status="failed" if scenario.error is not None else "completed",
            output=None if scenario.error is not None else scenario.output,
            artifacts=deepcopy(list(scenario.artifacts)),
            usage=deepcopy(scenario.usage),
            engine_metadata=deepcopy(scenario.engine_metadata),
            error=scenario.error,
        )

    def _failed_result(self, execution: _Execution, error: ExecutionError) -> ExecutionResult:
        return ExecutionResult(
            execution_id=execution.request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            status="failed",
            output=None,
            artifacts=[],
            usage={},
            engine_metadata={},
            error=error,
        )

    def _cancelled_result(self, execution: _Execution) -> ExecutionResult:
        return ExecutionResult(
            execution_id=execution.request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            status="cancelled",
            output=None,
            error=None,
        )

    def _execution_for(self, handle: ExecutionHandle) -> _Execution:
        execution = self._execution
        if execution is None or not isinstance(handle, ExecutionHandle):
            raise self._configuration_error(ExecutionErrorCode.INVALID_HANDLE)
        ensure_handle_identity(execution.request, handle)
        if handle.provider_session_id != execution.handle.provider_session_id:
            raise self._configuration_error(ExecutionErrorCode.INVALID_HANDLE)
        return execution

    async def _stop_execution(self, execution: _Execution) -> None:
        if execution.script_finished:
            execution.discard_queued_items()
            execution.notify_queue_waiters()
            await self._await_runner(execution)
            return
        if not execution.terminal.done():
            self._publish_terminal(execution, self._cancelled_result(execution))
        await self._cancel_runner(execution)

    async def _cancel_runner(self, execution: _Execution) -> None:
        await self._drain_runner(execution, cancel_runner=True)

    async def _await_runner(self, execution: _Execution) -> None:
        await self._drain_runner(execution, cancel_runner=False)

    async def _drain_runner(self, execution: _Execution, *, cancel_runner: bool) -> None:
        """Drain owned work without mistaking caller cancellation for runner cancellation."""
        task = execution.task
        current = asyncio.current_task()
        if task is None or task is current:
            return
        cancellation_baseline = current.cancelling() if current is not None else 0
        caller_cancellation: asyncio.CancelledError | None = None
        if cancel_runner and not task.done():
            task.cancel()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as exception:
                if current is not None and current.cancelling() > cancellation_baseline:
                    caller_cancellation = exception
                    cancellation_baseline = current.cancelling()
        if caller_cancellation is not None:
            raise caller_cancellation

    def _publish_terminal(self, execution: _Execution, result: ExecutionResult) -> None:
        if execution.terminal.done():
            return
        execution.terminal.set_result(result)
        if execution.scenario.completion_gate is not None:
            execution.scenario.completion_gate.set()
        for spec in execution.scenario.events:
            if spec.gate is not None:
                spec.gate.set()
        execution.discard_queued_items()
        execution.notify_queue_waiters()

    def _safe_runtime_exception(self, exception: Exception) -> AdapterExecutionError:
        if isinstance(exception, _SimulatedProcessFailure):
            return AdapterExecutionError(
                ExecutionError(
                    category=ExecutionErrorCategory.INTERNAL_ERROR,
                    code=ExecutionErrorCode.SIMULATED_PROCESS_FAILURE,
                )
            )
        return self._sanitize_safe_exception(normalize_adapter_exception(exception))

    def _safe_exception(self, exception: ExecutionError | Exception) -> AdapterExecutionError:
        if isinstance(exception, AdapterExecutionError):
            return self._sanitize_safe_exception(exception)
        if isinstance(exception, ExecutionError):
            error_type = (
                ConfigurationError
                if exception.category is ExecutionErrorCategory.CONFIGURATION_ERROR
                else AdapterExecutionError
            )
            return error_type(exception)
        return normalize_adapter_exception(exception)

    @staticmethod
    def _sanitize_safe_exception(exception: AdapterExecutionError) -> AdapterExecutionError:
        """Discard caller-supplied chains while preserving the safe subtype and DTO."""
        exception.__cause__ = None
        exception.__context__ = None
        exception.__traceback__ = None
        exception.__suppress_context__ = True
        return exception

    @staticmethod
    def _configuration_error(code: ExecutionErrorCode) -> ConfigurationError:
        return ConfigurationError(
            ExecutionError(category=ExecutionErrorCategory.CONFIGURATION_ERROR, code=code)
        )
