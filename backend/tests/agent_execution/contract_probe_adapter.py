"""Independent deterministic adapter used to probe the public execution contract."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Callable, Coroutine
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID, uuid5

from agent_platform.core_platform.agent_execution.contracts import (
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

_EVENT_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
_CLOSED = object()


@dataclass(frozen=True)
class ContractProbeEventSpec:
    """One declarative event, optionally released by an external gate."""

    sequence: int | None = None
    event_id: UUID | None = None
    timestamp: datetime | None = None
    event_type: str = "engine.output_delta"
    source: Literal["platform", "engine_native"] = "engine_native"
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str | None = None
    gate: asyncio.Event | None = field(default=None, compare=False, repr=False)
    duplicate_of: int | None = None


@dataclass(frozen=True)
class ContractProbeScenario:
    """A complete deterministic program for one probe execution."""

    capabilities: EngineCapabilities = field(default_factory=EngineCapabilities)
    events: tuple[ContractProbeEventSpec, ...] = ()
    output: str | None = None
    error: ExecutionError | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[dict[str, Any], ...] = ()
    engine_metadata: dict[str, Any] = field(default_factory=dict)
    prestart_error: ExecutionError | Exception | None = field(
        default=None, compare=False, repr=False
    )
    stream_error: ExecutionError | Exception | None = field(default=None, compare=False, repr=False)
    completion_gate: asyncio.Event | None = field(default=None, compare=False, repr=False)
    manual_timeout: bool = False
    simulated_process_failure: bool = False


@dataclass(eq=False)
class _Deadline:
    when: int
    fired: asyncio.Future[None]


class ContractProbeClock:
    """An integer clock advanced exclusively by the test."""

    def __init__(self) -> None:
        self._elapsed = 0
        self._deadlines: set[_Deadline] = set()

    def deadline(self, delay: int) -> _Deadline:
        fired = asyncio.get_running_loop().create_future()
        deadline = _Deadline(self._elapsed + delay, fired)
        self._deadlines.add(deadline)
        if delay <= 0:
            fired.set_result(None)
        return deadline

    def advance(self, seconds: int) -> None:
        if isinstance(seconds, bool) or not isinstance(seconds, int) or seconds < 0:
            raise ValueError("seconds must be a non-negative integer")
        self._elapsed += seconds
        for deadline in tuple(self._deadlines):
            if deadline.when <= self._elapsed and not deadline.fired.done():
                deadline.fired.set_result(None)

    async def expire(self, deadline: _Deadline) -> None:
        try:
            await deadline.fired
        finally:
            self._deadlines.discard(deadline)
        raise TimeoutError


class _ScriptedCrash(Exception):
    """Internal marker for a declared simulated process failure."""


@dataclass(frozen=True)
class _FailureItem:
    exception: AdapterExecutionError


class _Channel:
    """A small close-broadcasting channel owned by one execution."""

    def __init__(self) -> None:
        self.buffer: deque[object] = deque()
        self.receivers: set[asyncio.Future[object]] = set()
        self.closed = False

    def send(self, item: object) -> None:
        if self.closed:
            return
        for receiver in tuple(self.receivers):
            if not receiver.done():
                receiver.set_result(item)
                return
        self.buffer.append(item)

    async def receive(self, acknowledge: Callable[[object], None]) -> object:
        if self.buffer:
            return self.buffer.popleft()
        if self.closed:
            return _CLOSED
        receiver = asyncio.get_running_loop().create_future()
        self.receivers.add(receiver)
        try:
            return await receiver
        except asyncio.CancelledError:
            if receiver.done() and not receiver.cancelled():
                item = receiver.result()
                if item is not _CLOSED:
                    # A cancelled consumer suppresses its assigned item exactly once.
                    acknowledge(item)
            raise
        finally:
            self.receivers.discard(receiver)

    def close(self) -> list[object]:
        self.closed = True
        discarded = list(self.buffer)
        self.buffer.clear()
        for receiver in tuple(self.receivers):
            if not receiver.done():
                receiver.set_result(_CLOSED)
        return discarded


class _ProbeRun:
    """Mutable execution-local state; no mutable state is shared by adapters."""

    def __init__(
        self,
        request: ExecutionRequest,
        handle: ExecutionHandle,
        scenario: ContractProbeScenario,
        deadline: _Deadline | None,
    ) -> None:
        self.request = request
        self.handle = handle
        self.scenario = scenario
        self.deadline = deadline
        self.result: asyncio.Future[ExecutionResult] = asyncio.get_running_loop().create_future()
        self.channel = _Channel()
        self.drained = asyncio.Event()
        self.drained.set()
        self.outstanding = 0
        self.claimed = False
        self.closed = False
        self.program_finished = False
        self.collectors = 0
        self.producer: asyncio.Task[None] | None = None
        self.created_events: list[AgentEvent] = []
        self.events_by_id: dict[UUID, AgentEvent] = {}
        self.highest_sequence = 0

    def enqueue(self, item: AgentEvent | _FailureItem) -> None:
        self.outstanding += 1
        self.drained.clear()
        self.channel.send(item)

    def acknowledge(self, item: object) -> None:
        if item is _CLOSED:
            return
        self.outstanding -= 1
        if self.outstanding == 0:
            self.drained.set()

    def close_channel(self) -> None:
        for item in self.channel.close():
            self.acknowledge(item)


class _ProbeStream:
    """The sole permitted consumer for one probe run."""

    def __init__(self, adapter: "ContractProbeAdapter", run: _ProbeRun) -> None:
        self._owner = adapter
        self._run = run

    def __aiter__(self) -> "_ProbeStream":
        return self

    async def __anext__(self) -> AgentEvent:
        run = self._run
        if run.closed or run.result.done():
            self._close_channel()
            raise StopAsyncIteration
        item = await run.channel.receive(run.acknowledge)
        run.acknowledge(item)
        if run.closed or run.result.done() or item is _CLOSED:
            self._close_channel()
            raise StopAsyncIteration
        if isinstance(item, _FailureItem):
            self._close_channel()
            raise item.exception
        return cast(AgentEvent, item)

    def _close_channel(self) -> None:
        if self._run.closed:
            return
        self._run.closed = True
        self._run.close_channel()

    async def aclose(self) -> None:
        run = self._run
        if run.closed:
            return
        self._close_channel()
        if run.program_finished:
            await self._owner._drain(run, cancel=False)
        elif not run.result.done():
            await self._owner._terminate(run)


class ContractProbeAdapter:
    """Single-active-execution adapter implemented only against public contracts."""

    EVENT_NAMESPACE = UUID("f1041a6e-5946-4b6f-9bd2-cb2c8f34b0ee")

    def __init__(
        self, scenario: ContractProbeScenario, *, clock: ContractProbeClock | None = None
    ) -> None:
        self.scenario = scenario
        self.clock = clock or ContractProbeClock()
        self._active: _ProbeRun | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def engine_id(self) -> str:
        return "contract-probe"

    @property
    def protocol_id(self) -> str:
        return "contract-scripted"

    @property
    def adapter_version(self) -> str:
        return "v1"

    async def get_capabilities(self) -> EngineCapabilities:
        if not isinstance(self.scenario, ContractProbeScenario) or not isinstance(
            self.scenario.capabilities, EngineCapabilities
        ):
            raise self._config(ExecutionErrorCode.INVALID_SCENARIO)
        return self.scenario.capabilities

    async def start(self, request: ExecutionRequest) -> ExecutionHandle:
        if not isinstance(request, ExecutionRequest):
            raise self._config(ExecutionErrorCode.INVALID_REQUEST)
        ensure_request_identity(request, self)
        if self._active is not None:
            raise self._config(ExecutionErrorCode.INVALID_ADAPTER_STATE)
        scenario = self._validated_snapshot(request)
        if scenario.prestart_error is not None:
            raise self._declared_exception(scenario.prestart_error) from None

        handle = ExecutionHandle(
            execution_id=request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            provider_session_id=request.engine_session_id,
            process_id=None,
        )
        deadline = (
            self.clock.deadline(request.timeout_seconds or 1) if scenario.manual_timeout else None
        )
        run = _ProbeRun(request, handle, scenario, deadline)
        run.producer = self._spawn(self._produce(run))
        self._active = run
        return handle

    def stream_events(self, handle: ExecutionHandle) -> AsyncIterator[AgentEvent]:
        run = self._resolve(handle)
        if run.claimed:
            raise self._config(ExecutionErrorCode.INVALID_ADAPTER_STATE)
        run.claimed = True
        return _ProbeStream(self, run)

    async def cancel(self, handle: ExecutionHandle) -> None:
        run = self._resolve(handle)
        if not run.result.done():
            await self._terminate(run)

    async def collect_result(self, handle: ExecutionHandle) -> ExecutionResult:
        run = self._resolve(handle)
        run.collectors += 1
        try:
            return await asyncio.shield(run.result)
        except asyncio.CancelledError:
            stream_active = run.claimed and not run.closed
            if run.collectors == 1 and not stream_active and not run.result.done():
                await self._terminate(run)
            raise
        finally:
            run.collectors -= 1

    def _spawn(self, coroutine: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        return task

    async def _produce(self, run: _ProbeRun) -> None:
        try:
            if run.deadline is None:
                await self._run_program(run)
            else:
                await self._run_before_deadline(run)
            result = self._declared_result(run)
            run.program_finished = True
            if run.claimed:
                await run.drained.wait()
            self._publish(run, result)
        except asyncio.CancelledError:
            self._publish(run, self._cancelled_result(run))
            raise
        except Exception as exception:  # noqa: BLE001 - engine boundaries expose safe errors only.
            safe = self._runtime_exception(exception)
            run.program_finished = True
            if isinstance(exception, TimeoutError):
                self._publish(run, self._failure_result(run, safe.error))
                return
            if run.claimed and not run.closed:
                run.enqueue(_FailureItem(safe))
            if run.claimed:
                await run.drained.wait()
            self._publish(run, self._failure_result(run, safe.error))

    async def _run_before_deadline(self, run: _ProbeRun) -> None:
        assert run.deadline is not None
        program = self._spawn(self._run_program(run))
        timer = self._spawn(self.clock.expire(run.deadline))
        try:
            await asyncio.wait((program, timer), return_when=asyncio.FIRST_COMPLETED)
            if program.done():
                await program
            else:
                await timer
        finally:
            for task in (program, timer):
                if not task.done():
                    task.cancel()
            await asyncio.gather(program, timer, return_exceptions=True)

    async def _run_program(self, run: _ProbeRun) -> None:
        for index, spec in enumerate(run.scenario.events):
            if run.result.done():
                return
            if spec.gate is not None:
                await spec.gate.wait()
            if run.result.done():
                return
            run.enqueue(self._event_for(run, spec, index))
        if run.scenario.completion_gate is not None:
            await run.scenario.completion_gate.wait()
        if run.result.done():
            return
        if run.scenario.stream_error is not None:
            raise self._declared_exception(run.scenario.stream_error)
        if run.scenario.simulated_process_failure:
            raise _ScriptedCrash

    def _event_for(self, run: _ProbeRun, spec: ContractProbeEventSpec, index: int) -> AgentEvent:
        if spec.duplicate_of is not None:
            duplicate = run.created_events[spec.duplicate_of]
            run.created_events.append(duplicate)
            return duplicate

        event = self._build_event(run.request, spec, index)
        previous = run.events_by_id.get(event.event_id)
        if previous is not None:
            if previous != event:
                raise AdapterExecutionError(
                    ExecutionError(
                        category=ExecutionErrorCategory.PROTOCOL_ERROR,
                        code=ExecutionErrorCode.EVENT_IDENTITY_CONFLICT,
                    )
                )
            run.created_events.append(previous)
            return previous
        run.events_by_id[event.event_id] = event
        run.created_events.append(event)
        run.highest_sequence = max(run.highest_sequence, event.sequence)
        return event

    def _build_event(
        self, request: ExecutionRequest, spec: ContractProbeEventSpec, index: int
    ) -> AgentEvent:
        return AgentEvent(
            event_id=spec.event_id
            or uuid5(self.EVENT_NAMESPACE, f"{request.execution_id}:{index}"),
            execution_id=request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            engine_session_id=request.engine_session_id,
            sequence=spec.sequence if spec.sequence is not None else index + 1,
            event_type=spec.event_type,
            source=spec.source,
            timestamp=spec.timestamp or _EVENT_EPOCH + timedelta(milliseconds=index),
            payload=deepcopy(spec.payload),
            trace_id=spec.trace_id if spec.trace_id is not None else request.trace_id,
        )

    def _validated_snapshot(self, request: ExecutionRequest) -> ContractProbeScenario:
        try:
            scenario = self.scenario
            if not isinstance(scenario, ContractProbeScenario):
                raise TypeError
            if not isinstance(scenario.capabilities, EngineCapabilities):
                raise TypeError
            if not isinstance(scenario.events, tuple) or not all(
                isinstance(spec, ContractProbeEventSpec) for spec in scenario.events
            ):
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

            specs: list[ContractProbeEventSpec] = []
            for index, spec in enumerate(scenario.events):
                if spec.gate is not None and not isinstance(spec.gate, asyncio.Event):
                    raise TypeError
                if spec.duplicate_of is not None:
                    if (
                        isinstance(spec.duplicate_of, bool)
                        or not isinstance(spec.duplicate_of, int)
                        or not 0 <= spec.duplicate_of < index
                    ):
                        raise ValueError
                else:
                    self._build_event(request, spec, index)
                specs.append(
                    ContractProbeEventSpec(
                        sequence=spec.sequence,
                        event_id=spec.event_id,
                        timestamp=spec.timestamp,
                        event_type=spec.event_type,
                        source=spec.source,
                        payload=deepcopy(spec.payload),
                        trace_id=spec.trace_id,
                        gate=spec.gate,
                        duplicate_of=spec.duplicate_of,
                    )
                )

            snapshot = ContractProbeScenario(
                capabilities=scenario.capabilities,
                events=tuple(specs),
                output=scenario.output,
                error=scenario.error,
                usage=deepcopy(scenario.usage),
                artifacts=tuple(deepcopy(scenario.artifacts)),
                engine_metadata=deepcopy(scenario.engine_metadata),
                prestart_error=scenario.prestart_error,
                stream_error=scenario.stream_error,
                completion_gate=scenario.completion_gate,
                manual_timeout=scenario.manual_timeout,
                simulated_process_failure=scenario.simulated_process_failure,
            )
            self._result_for(request, snapshot)
            return snapshot
        except Exception:  # noqa: BLE001 - malformed test programs have one safe failure.
            raise self._config(ExecutionErrorCode.INVALID_SCENARIO) from None

    def _declared_result(self, run: _ProbeRun) -> ExecutionResult:
        return self._result_for(run.request, run.scenario)

    def _result_for(
        self, request: ExecutionRequest, scenario: ContractProbeScenario
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

    def _failure_result(self, run: _ProbeRun, error: ExecutionError) -> ExecutionResult:
        return ExecutionResult(
            execution_id=run.request.execution_id,
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

    def _cancelled_result(self, run: _ProbeRun) -> ExecutionResult:
        return ExecutionResult(
            execution_id=run.request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            status="cancelled",
            output=None,
            error=None,
        )

    def _resolve(self, handle: ExecutionHandle) -> _ProbeRun:
        run = self._active
        if run is None or not isinstance(handle, ExecutionHandle):
            raise self._config(ExecutionErrorCode.INVALID_HANDLE)
        ensure_handle_identity(run.request, handle)
        if handle.provider_session_id != run.handle.provider_session_id:
            raise self._config(ExecutionErrorCode.INVALID_HANDLE)
        return run

    async def _terminate(self, run: _ProbeRun) -> None:
        self._publish(run, self._cancelled_result(run))
        await self._drain(run, cancel=True)

    async def _drain(self, run: _ProbeRun, *, cancel: bool) -> None:
        producer = run.producer
        caller = asyncio.current_task()
        if producer is None or producer is caller:
            return
        cancellation_count = caller.cancelling() if caller is not None else 0
        caller_cancelled: asyncio.CancelledError | None = None
        if cancel and not producer.done():
            producer.cancel()
        while not producer.done():
            try:
                await asyncio.shield(producer)
            except asyncio.CancelledError as exception:
                if caller is not None and caller.cancelling() > cancellation_count:
                    caller_cancelled = exception
                    cancellation_count = caller.cancelling()
        if caller_cancelled is not None:
            raise caller_cancelled

    def _publish(self, run: _ProbeRun, result: ExecutionResult) -> None:
        if run.result.done():
            return
        run.result.set_result(result)
        if run.scenario.completion_gate is not None:
            run.scenario.completion_gate.set()
        for spec in run.scenario.events:
            if spec.gate is not None:
                spec.gate.set()
        run.close_channel()

    def _runtime_exception(self, exception: Exception) -> AdapterExecutionError:
        if isinstance(exception, _ScriptedCrash):
            return AdapterExecutionError(
                ExecutionError(
                    category=ExecutionErrorCategory.INTERNAL_ERROR,
                    code=ExecutionErrorCode.SIMULATED_PROCESS_FAILURE,
                )
            )
        return self._scrub(normalize_adapter_exception(exception))

    def _declared_exception(self, exception: ExecutionError | Exception) -> AdapterExecutionError:
        if isinstance(exception, ExecutionError):
            error_type = (
                ConfigurationError
                if exception.category is ExecutionErrorCategory.CONFIGURATION_ERROR
                else AdapterExecutionError
            )
            return error_type(exception)
        return self._scrub(normalize_adapter_exception(exception))

    @staticmethod
    def _scrub(exception: AdapterExecutionError) -> AdapterExecutionError:
        exception.__cause__ = None
        exception.__context__ = None
        exception.__traceback__ = None
        exception.__suppress_context__ = True
        return exception

    @staticmethod
    def _config(code: ExecutionErrorCode) -> ConfigurationError:
        return ConfigurationError(
            ExecutionError(category=ExecutionErrorCategory.CONFIGURATION_ERROR, code=code)
        )
