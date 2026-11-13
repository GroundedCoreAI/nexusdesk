"""React runtime adapter with explicit downstream delivery acknowledgement."""

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast
from uuid import UUID

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
    PreparedInstructions,
    ensure_handle_identity,
    ensure_request_identity,
)
from ...orchestration.execution_context import ExecutionContext, build_execution_request
from ...orchestration.execution_lifecycle import ExecutionOutcome
from .error_mapper import ReactErrorMapping, map_execution_error, map_protocol_error
from .event_mapper import ReactEventMapper

RuntimeEmit = Callable[[object, object], Awaitable[None]]


class RuntimeEngine(Protocol):
    """Structural runtime capability; no concrete runtime implementation is imported.

    ``prepared_instructions`` is the Phase 3 addition (R-32): the instruction
    provider output computed before ``start``. It defaults to ``None`` so the
    Phase 2 off path stays byte-identical, and the implementation signature in
    ``core_platform.agent_runtime.engine`` is pinned to this shape by a test - a
    five-parameter Protocol with a six-parameter implementation would let the
    prepared input be dropped silently.
    """

    async def run(
        self,
        message: object,
        history: list[dict[str, object]],
        emit: RuntimeEmit,
        summary_message: str | None = None,
        customer_memory: str | None = None,
        prepared_instructions: PreparedInstructions | None = None,
    ) -> tuple[object, object, object]: ...


class RuntimeFactory(Protocol):
    """Application-injected per-run runtime construction capability."""

    async def for_run(self, row: object, emit: RuntimeEmit) -> RuntimeEngine: ...


def _is_control_flow(error: BaseException) -> bool:
    if isinstance(error, BaseExceptionGroup):
        return any(_is_control_flow(member) for member in error.exceptions)
    return not isinstance(error, Exception)


@dataclass(frozen=True, slots=True)
class _StreamFailure:
    exception: AdapterExecutionError


class _Execution:
    """All mutable state for one claimed row and one runner."""

    def __init__(
        self,
        context: ExecutionContext,
        request: ExecutionRequest,
        handle: ExecutionHandle,
        queue_capacity: int,
    ) -> None:
        self.context = context
        self.request = request
        self.handle = handle
        self.mapper = ReactEventMapper(request)
        self.queue_capacity = queue_capacity
        self.queue: deque[AgentEvent | _StreamFailure] = deque()
        self.condition = asyncio.Condition()
        self.first_gate = asyncio.Event()
        self.terminal: asyncio.Future[ExecutionResult] = asyncio.get_running_loop().create_future()
        self.task: asyncio.Task[None] | None = None
        self.stream_state: Literal["never-claimed", "claimed-active", "closed"] = "never-claimed"
        self.no_stream = False
        self.producer_finished = False
        self.pending_result: ExecutionResult | None = None
        self.pending_outcome: ExecutionOutcome | None = None
        self.outcome: ExecutionOutcome | None = None
        self.in_flight: AgentEvent | None = None
        # Active-period O(events) storage is intentional: any settled identity may be
        # acknowledged again idempotently. Identities belong only to this execution and
        # are released on every terminal transition; closed streams retain no ack history.
        self.settled_acks: set[tuple[UUID, UUID]] = set()
        self.consumer_active = False
        self.collectors = 0

    @property
    def undelivered(self) -> int:
        """A popped event remains undelivered until its explicit acknowledgement."""
        return len(self.queue) + (self.in_flight is not None)


class ReactAdapter:
    """Single-execution adapter around an injected RuntimeFactory capability."""

    def __init__(
        self,
        context: ExecutionContext,
        runtime_factory: RuntimeFactory,
        *,
        queue_capacity: int = 1,
    ) -> None:
        self._context = context
        self._runtime_factory = runtime_factory
        self._queue_capacity = queue_capacity
        self._execution: _Execution | None = None
        self._owned_tasks: set[asyncio.Task[Any]] = set()

    @property
    def engine_id(self) -> str:
        return "react"

    @property
    def protocol_id(self) -> str:
        return "native"

    @property
    def adapter_version(self) -> str:
        return "v1"

    async def get_capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            streaming=True,
            cancellation=True,
            tool_calling=True,
            native_events=True,
        )

    async def start(self, request: ExecutionRequest) -> ExecutionHandle:
        """Validate the fixed request, then start one gated runtime runner."""
        if not isinstance(request, ExecutionRequest):
            raise self._configuration_error(ExecutionErrorCode.INVALID_REQUEST)
        ensure_request_identity(request, self)
        self._validate_context_request(request)
        if self._execution is not None:
            raise self._configuration_error(ExecutionErrorCode.INVALID_ADAPTER_STATE)
        if type(self._queue_capacity) is not int or self._queue_capacity < 1:
            raise self._configuration_error(ExecutionErrorCode.INVALID_ADAPTER_STATE)

        handle = ExecutionHandle(
            execution_id=request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            provider_session_id=request.engine_session_id,
            process_id=None,
        )
        execution = _Execution(self._context, request, handle, self._queue_capacity)
        execution.task = self._create_task(self._run(execution))
        self._execution = execution
        return handle

    def stream_events(self, handle: ExecutionHandle) -> AsyncIterator[AgentEvent]:
        """Atomically claim the sole stream before returning its iterator."""
        execution = self._execution_for(handle)
        if execution.stream_state != "never-claimed":
            raise self._configuration_error(ExecutionErrorCode.INVALID_ADAPTER_STATE)
        if execution.no_stream or execution.terminal.done():
            execution.stream_state = "closed"
        else:
            execution.stream_state = "claimed-active"
            execution.first_gate.set()
        return _ReactEventStream(self, execution)

    async def cancel(self, handle: ExecutionHandle) -> None:
        """Publish cancellation once, suppress late work, and drain the runner."""
        execution = self._execution_for(handle)
        if not execution.terminal.done():
            await self._cancel_execution(execution)
        else:
            await self._drain_runner(execution, cancel_runner=False)

    async def collect_result(self, handle: ExecutionHandle) -> ExecutionResult:
        """Share terminal results while explicitly selecting no-stream when first."""
        execution = await self._collect_terminal(handle)
        return execution.terminal.result()

    async def collect_outcome(self, handle: ExecutionHandle) -> ExecutionOutcome:
        """Return the already-published private outcome through the shared collector path."""
        execution = await self._collect_terminal(handle)
        outcome = execution.outcome
        if outcome is None:
            raise self._configuration_error(ExecutionErrorCode.INVALID_RESULT)
        return outcome

    async def _collect_terminal(self, handle: ExecutionHandle) -> _Execution:
        execution = self._execution_for(handle)
        async with execution.condition:
            if execution.stream_state == "never-claimed" and not execution.terminal.done():
                execution.no_stream = True
                execution.first_gate.set()
                execution.condition.notify_all()
                self._maybe_publish_locked(execution)
            execution.collectors += 1
        try:
            await asyncio.shield(execution.terminal)
            return execution
        except asyncio.CancelledError:
            lone_waiter = execution.collectors == 1
            no_active_stream = execution.stream_state != "claimed-active"
            if lone_waiter and no_active_stream and not execution.terminal.done():
                await self._cancel_execution(execution)
            raise
        finally:
            async with execution.condition:
                execution.collectors -= 1
                execution.condition.notify_all()

    def _validate_context_request(self, request: ExecutionRequest) -> None:
        try:
            if not isinstance(self._context, ExecutionContext):
                raise TypeError
            expected = build_execution_request(self._context)
            fields = (
                "execution_id",
                "tenant_id",
                "agent_id",
                "conversation_id",
                "input",
                "engine_session_id",
                "workspace_id",
                "execution_workdir",
                "trace_id",
                "timeout_seconds",
            )
            if any(getattr(request, field) != getattr(expected, field) for field in fields):
                raise ValueError
            if not callable(getattr(self._runtime_factory, "for_run", None)):
                raise TypeError
        except ConfigurationError:
            raise
        except Exception:  # noqa: BLE001 - untrusted context/factory inputs must fail closed.
            raise self._configuration_error(ExecutionErrorCode.INVALID_REQUEST) from None

    def _create_task(self, coroutine: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(coroutine)
        self._owned_tasks.add(task)
        task.add_done_callback(self._retrieve_task_exception)
        return task

    @staticmethod
    def _retrieve_task_exception(task: asyncio.Task[None]) -> None:
        # Owned control-flow failures are rethrown for awaiters, but an execution may
        # finish without a draining caller. Retrieve every stored exception exactly at
        # task completion so asyncio never logs an unretrieved diagnostic.
        if not task.cancelled():
            task.exception()

    async def _run(self, execution: _Execution) -> None:
        try:
            try:
                async with asyncio.timeout(execution.request.timeout_seconds):
                    runtime_emit = self._runtime_emit(execution)
                    runtime = await self._runtime_factory.for_run(
                        execution.context.row, runtime_emit
                    )
                    prepared = execution.context.prepared_instructions
                    if prepared is None:
                        # The off path stays the literal Phase 2 call: five
                        # arguments, the same two rendered values, nothing added.
                        output, history, dropped = await runtime.run(
                            execution.context.row["input"],
                            execution.context.history,
                            runtime_emit,
                            summary_message=execution.context.summary_message,
                            customer_memory=execution.context.customer_memory,
                        )
                    else:
                        # R-41: the prepared path must not re-supply either
                        # rendered value. The Engine checks exactly that and fails
                        # closed, because a second copy of the business rendering
                        # would mean two sources of truth for one Run, and the
                        # retained window of a differently derived second copy is
                        # what this invariant exists to catch. The provider output
                        # is the only message source once it is present.
                        output, history, dropped = await runtime.run(
                            execution.context.row["input"],
                            execution.context.history,
                            runtime_emit,
                            summary_message=None,
                            customer_memory=None,
                            prepared_instructions=prepared,
                        )
                result, outcome = self._completed_result(execution, output, history, dropped)
                async with execution.condition:
                    if execution.terminal.done():
                        return
                    execution.pending_result = result
                    execution.pending_outcome = outcome
                    execution.producer_finished = True
                    self._maybe_publish_locked(execution)
                    execution.condition.notify_all()
            except Exception as exception:  # noqa: BLE001 - runtime failures cross a safe boundary.
                await self._finish_runner_failure(execution, exception)
        except (
            asyncio.CancelledError,
            KeyboardInterrupt,
            SystemExit,
            GeneratorExit,
            BaseExceptionGroup,
        ):
            # This outer boundary also covers control flow raised by the failure
            # mapper itself. Preserve first-terminal-wins, release all delivery
            # state and waiters, then propagate the original control flow unchanged.
            async with execution.condition:
                if not execution.terminal.done():
                    self._publish_cancelled_locked(execution)
                else:
                    self._suppress_locked(execution)
            raise

    def _runtime_emit(self, execution: _Execution) -> RuntimeEmit:
        async def emit(kind: object, data: object) -> None:
            await execution.first_gate.wait()
            async with execution.condition:
                if execution.terminal.done() or execution.producer_finished:
                    return
                if execution.no_stream:
                    # Suppression skips delivery and backpressure, not protocol validation.
                    execution.mapper.map(kind, data)
                    return
                while (
                    not execution.terminal.done()
                    and not execution.producer_finished
                    and not execution.no_stream
                    and execution.stream_state == "claimed-active"
                    and len(execution.queue) >= execution.queue_capacity
                ):
                    await execution.condition.wait()
                if execution.terminal.done() or execution.producer_finished or execution.no_stream:
                    return
                if execution.stream_state != "claimed-active":
                    return
                # Mapping and append are atomic, so concurrent runtime emitters cannot
                # enqueue a higher local sequence ahead of a lower one.
                event = execution.mapper.map(kind, data)
                execution.queue.append(event)
                execution.condition.notify_all()

        return emit

    async def _finish_runner_failure(self, execution: _Execution, exception: Exception) -> None:
        mapping = map_execution_error(exception)
        safe_exception = self._safe_exception(mapping)
        result, outcome = self._failed_result(execution, mapping)
        async with execution.condition:
            if execution.terminal.done():
                return
            execution.pending_result = result
            execution.pending_outcome = outcome
            execution.producer_finished = True
            # Wake emitters blocked by a full buffer so after-failure events are
            # suppressed rather than appended behind the terminal stream failure.
            execution.condition.notify_all()
            if execution.stream_state == "claimed-active" and not execution.no_stream:
                while (
                    not execution.terminal.done()
                    and execution.stream_state == "claimed-active"
                    and len(execution.queue) >= execution.queue_capacity
                ):
                    await execution.condition.wait()
                if not execution.terminal.done() and execution.stream_state == "claimed-active":
                    execution.queue.append(_StreamFailure(safe_exception))
            self._maybe_publish_locked(execution)
            execution.condition.notify_all()

    def _completed_result(
        self,
        execution: _Execution,
        output: object,
        history: object,
        dropped: object,
    ) -> tuple[ExecutionResult, ExecutionOutcome]:
        if not isinstance(output, str | None) or not isinstance(history, list):
            raise TypeError
        if not all(isinstance(item, dict) for item in history) or not isinstance(dropped, list):
            raise TypeError
        if not all(isinstance(item, dict) for item in dropped):
            raise TypeError
        result = ExecutionResult(
            execution_id=execution.request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            status="completed",
            output=output,
            artifacts=[],
            usage={},
            engine_metadata={},
            error=None,
        )
        outcome = ExecutionOutcome.from_result(result, history=history, dropped=dropped)
        return result, outcome

    def _failed_result(
        self, execution: _Execution, mapping: ReactErrorMapping
    ) -> tuple[ExecutionResult, ExecutionOutcome]:
        result = ExecutionResult(
            execution_id=execution.request.execution_id,
            engine_id=self.engine_id,
            protocol_id=self.protocol_id,
            adapter_version=self.adapter_version,
            status="failed",
            output=None,
            artifacts=[],
            usage={},
            engine_metadata={},
            error=mapping.error,
        )
        return result, ExecutionOutcome.from_result(
            result, legacy_error_code=mapping.legacy_error_code
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

    def _maybe_publish_locked(self, execution: _Execution) -> None:
        if execution.terminal.done() or not execution.producer_finished:
            return
        if (
            execution.stream_state == "claimed-active"
            and not execution.no_stream
            and execution.undelivered
        ):
            return
        result = execution.pending_result
        outcome = execution.pending_outcome
        if result is None or outcome is None:
            return
        execution.outcome = outcome
        execution.terminal.set_result(result)
        execution.settled_acks.clear()
        execution.first_gate.set()
        execution.condition.notify_all()

    def _publish_cancelled_locked(self, execution: _Execution) -> None:
        if execution.terminal.done():
            return
        result = self._cancelled_result(execution)
        execution.outcome = ExecutionOutcome.from_result(result)
        execution.terminal.set_result(result)
        self._suppress_locked(execution)

    def _suppress_locked(self, execution: _Execution) -> None:
        execution.queue.clear()
        execution.in_flight = None
        execution.settled_acks.clear()
        execution.first_gate.set()
        if execution.stream_state == "claimed-active":
            execution.stream_state = "closed"
        execution.condition.notify_all()

    async def _cancel_execution(self, execution: _Execution) -> None:
        async with execution.condition:
            if not execution.terminal.done():
                self._publish_cancelled_locked(execution)
            else:
                self._suppress_locked(execution)
        await self._drain_runner(execution, cancel_runner=not execution.producer_finished)

    async def _fail_from_consumer(self, execution: _Execution, mapping: ReactErrorMapping) -> None:
        result, outcome = self._failed_result(execution, mapping)
        async with execution.condition:
            if not execution.terminal.done():
                execution.outcome = outcome
                execution.terminal.set_result(result)
            self._suppress_locked(execution)
        await self._drain_runner(execution, cancel_runner=not execution.producer_finished)

    async def _protocol_failure(self, execution: _Execution) -> AdapterExecutionError:
        mapping = map_protocol_error()
        await self._fail_from_consumer(execution, mapping)
        return self._safe_exception(mapping)

    async def _drain_runner(self, execution: _Execution, *, cancel_runner: bool) -> None:
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

    @staticmethod
    def _safe_exception(mapping: ReactErrorMapping) -> AdapterExecutionError:
        error_type = (
            ConfigurationError
            if mapping.error.category is ExecutionErrorCategory.CONFIGURATION_ERROR
            else AdapterExecutionError
        )
        exception = error_type(mapping.error)
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

    def _execution_for(self, handle: ExecutionHandle) -> _Execution:
        execution = self._execution
        if execution is None or not isinstance(handle, ExecutionHandle):
            raise self._configuration_error(ExecutionErrorCode.INVALID_HANDLE)
        ensure_handle_identity(execution.request, handle)
        if handle.provider_session_id != execution.handle.provider_session_id:
            raise self._configuration_error(ExecutionErrorCode.INVALID_HANDLE)
        return execution


class _ReactEventStream:
    """One-claim stream whose acknowledgement settles exactly one in-flight event."""

    def __init__(self, adapter: ReactAdapter, execution: _Execution) -> None:
        self._adapter = adapter
        self._execution = execution

    def __aiter__(self) -> "_ReactEventStream":
        return self

    async def __anext__(self) -> AgentEvent:
        execution = self._execution
        async with execution.condition:
            while execution.consumer_active or execution.in_flight is not None:
                if execution.terminal.done() or execution.stream_state == "closed":
                    raise StopAsyncIteration
                await execution.condition.wait()
            if execution.stream_state == "closed":
                raise StopAsyncIteration
            execution.consumer_active = True
            try:
                while not execution.queue:
                    if execution.terminal.done():
                        if execution.stream_state == "claimed-active":
                            execution.stream_state = "closed"
                        raise StopAsyncIteration
                    await execution.condition.wait()
                item = execution.queue.popleft()
                if isinstance(item, _StreamFailure):
                    if execution.stream_state == "claimed-active":
                        execution.stream_state = "closed"
                    self._adapter._maybe_publish_locked(execution)
                    raise item.exception
                event = cast(AgentEvent, item)
                execution.in_flight = event
                return event
            finally:
                execution.consumer_active = False
                execution.condition.notify_all()

    async def acknowledge(self, event: AgentEvent) -> None:
        execution = self._execution
        try:
            if not isinstance(event, AgentEvent):
                raise TypeError
            identity = (event.execution_id, event.event_id)
            async with execution.condition:
                if identity in execution.settled_acks:
                    return
                current = execution.in_flight
                if current is None or identity != (current.execution_id, current.event_id):
                    raise ValueError
                execution.in_flight = None
                execution.settled_acks.add(identity)
                self._adapter._maybe_publish_locked(execution)
                execution.condition.notify_all()
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit):
            raise
        except Exception:  # noqa: BLE001 - malformed acknowledgements must fail closed.
            raise await self._adapter._protocol_failure(execution) from None

    async def abort(self, error: BaseException) -> None:
        execution = self._execution
        if _is_control_flow(error):
            await self._adapter._cancel_execution(execution)
            raise error
        # A worker/stream boundary failure is never a runtime-originated safe DTO:
        # normalize every ordinary exception to the frozen public/internal pair.
        mapping = map_execution_error(RuntimeError())
        await self._adapter._fail_from_consumer(execution, mapping)

    async def aclose(self) -> None:
        execution = self._execution
        async with execution.condition:
            if execution.stream_state == "closed" and execution.terminal.done():
                return
            if execution.stream_state == "claimed-active":
                execution.stream_state = "closed"
            execution.condition.notify_all()
        if not execution.terminal.done():
            await self._adapter._cancel_execution(execution)
        else:
            await self._adapter._drain_runner(execution, cancel_runner=False)
