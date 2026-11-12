"""Fixed-selector execution orchestration with exclusive Worker event delivery."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from typing import TypeAlias

from pydantic import JsonValue

from ..contracts import (
    AdapterExecutionError,
    AgentEngineAdapter,
    AgentEvent,
    ExecutionErrorCode,
    ExecutionHandle,
    ExecutionResult,
)
from ..registry import AdapterRegistry
from .execution_context import (
    ExecutionContext,
    build_execution_request,
    resolve_with_execution_context,
)
from .execution_lifecycle import (
    AcknowledgingEventStream,
    ExecutionOutcome,
    OutcomeCollectingAdapter,
    as_acknowledging_event_stream,
    as_outcome_collecting_adapter,
)

WorkerEmit: TypeAlias = Callable[[str, dict[str, JsonValue]], Awaitable[None]]
AdapterSelector: TypeAlias = tuple[str, str, str]
_PRODUCTION_SELECTOR: AdapterSelector = ("react", "native", "v1")


def _failed_outcome(legacy_error_code: str) -> ExecutionOutcome:
    return ExecutionOutcome(status="failed", legacy_error_code=legacy_error_code)


def _safe_legacy_code(exception: BaseException) -> str:
    if isinstance(exception, AdapterExecutionError):
        return exception.error.code.value
    return "execution_error"


def _public_result_outcome(result: ExecutionResult) -> ExecutionOutcome:
    """Apply the deliberately lossy fallback only to protocol-free public Results."""
    if result.status == "completed":
        return ExecutionOutcome.from_result(result)
    if result.status == "cancelled":
        return ExecutionOutcome.from_result(result)
    legacy_error_code = "execution_error"
    if result.error is not None and result.error.code is ExecutionErrorCode.EXECUTION_TIMEOUT:
        legacy_error_code = "run_timeout"
    return ExecutionOutcome.from_result(result, legacy_error_code=legacy_error_code)


async def _close_plain_stream(stream: AsyncIterator[AgentEvent]) -> None:
    close = getattr(stream, "aclose", None)
    if close is not None:
        await close()


async def _abort_and_close(
    stream: AsyncIterator[AgentEvent],
    acknowledging: AcknowledgingEventStream | None,
    error: BaseException,
) -> bool:
    """Finish both cleanup steps and report ordinary cleanup failure."""
    cleanup_failed = False
    if acknowledging is None:
        try:
            await _close_plain_stream(stream)
        except Exception:  # noqa: BLE001 - cleanup failure is normalized by the caller.
            cleanup_failed = True
        return cleanup_failed
    try:
        await acknowledging.abort(error)
    except Exception:  # noqa: BLE001 - aclose must still run after an abort failure.
        cleanup_failed = True
    finally:
        try:
            await acknowledging.aclose()
        except Exception:  # noqa: BLE001 - cleanup failure is normalized by the caller.
            cleanup_failed = True
    return cleanup_failed


class ExecutionOrchestrator:
    """Resolve one trusted selector and own the only path to Worker event emission."""

    def __init__(
        self,
        registry: AdapterRegistry,
        *,
        selector: AdapterSelector = _PRODUCTION_SELECTOR,
    ) -> None:
        if (
            not isinstance(selector, tuple)
            or len(selector) != 3
            or not all(isinstance(value, str) and value for value in selector)
        ):
            raise ValueError("selector must be one exact engine/protocol/version tuple")
        self._registry = registry
        self._selector = selector

    @property
    def selector(self) -> AdapterSelector:
        return self._selector

    async def execute(
        self,
        context: ExecutionContext,
        worker_emit: WorkerEmit,
    ) -> ExecutionOutcome:
        try:
            request = build_execution_request(context)
            if self._selector != _PRODUCTION_SELECTOR:
                request = request.model_copy(
                    update={
                        "engine_id": self._selector[0],
                        "protocol_id": self._selector[1],
                        "adapter_version": self._selector[2],
                    }
                )
            adapter = resolve_with_execution_context(
                context,
                lambda: self._registry.resolve(*self._selector),
            )
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit):
            raise
        except Exception as exception:  # noqa: BLE001 - assembly crosses a safe boundary.
            return _failed_outcome(_safe_legacy_code(exception))

        outcome_collector = as_outcome_collecting_adapter(adapter)
        try:
            handle = await adapter.start(request)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit):
            raise
        except Exception as exception:  # noqa: BLE001 - start crosses a safe boundary.
            return _failed_outcome(_safe_legacy_code(exception))

        stream: AsyncIterator[AgentEvent] | None = None
        acknowledging: AcknowledgingEventStream | None = None
        collect_attempted = False
        stage = "claim"
        try:
            stream = adapter.stream_events(handle)
            acknowledging = as_acknowledging_event_stream(stream)
            while True:
                stage = "stream"
                try:
                    event = await anext(stream)
                except StopAsyncIteration:
                    break
                stage = "worker_emit"
                await worker_emit(event.event_type, event.payload)
                if acknowledging is not None:
                    stage = "acknowledge"
                    await acknowledging.acknowledge(event)
            stage = "collect"
            collect_attempted = True
            if outcome_collector is not None:
                return await outcome_collector.collect_outcome(handle)
            return _public_result_outcome(await adapter.collect_result(handle))
        # Pure ExceptionGroups are ordinary failures; groups containing control flow
        # do not subclass Exception and reach the following re-raise boundary.
        except Exception as exception:  # noqa: BLE001 - normalize stage failures safely.
            if stream is None:
                # A claim failure has no iterator to abort. Cancellation only cleans
                # the runner; its terminal state must not become the execution outcome.
                with suppress(Exception):
                    await adapter.cancel(handle)
                return _failed_outcome("execution_error")
            cleanup_failed = await _abort_and_close(stream, acknowledging, exception)
            return await self._collect_failure(
                adapter,
                outcome_collector,
                handle,
                collect_attempted=collect_attempted,
                failure_from_stream=stage == "stream",
                cleanup_failed=cleanup_failed,
            )
        except (
            asyncio.CancelledError,
            KeyboardInterrupt,
            SystemExit,
            GeneratorExit,
            BaseExceptionGroup,
        ) as exception:
            if stream is not None:
                await _abort_and_close(stream, acknowledging, exception)
            else:
                await adapter.cancel(handle)
            raise

    async def _collect_failure(
        self,
        adapter: AgentEngineAdapter,
        outcome_collector: OutcomeCollectingAdapter | None,
        handle: ExecutionHandle,
        *,
        collect_attempted: bool,
        failure_from_stream: bool,
        cleanup_failed: bool,
    ) -> ExecutionOutcome:
        if collect_attempted:
            # A collector exception is not a successfully collected public Result;
            # public error codes must never become private legacy codes here.
            return _failed_outcome("execution_error")
        if cleanup_failed and not failure_from_stream:
            return _failed_outcome("execution_error")
        if outcome_collector is not None:
            try:
                outcome = await outcome_collector.collect_outcome(handle)
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit):
                raise
            except Exception:  # noqa: BLE001 - private collection cannot fall back publicly.
                return _failed_outcome("execution_error")
            if failure_from_stream and cleanup_failed and outcome.status != "failed":
                return _failed_outcome("execution_error")
            return outcome
        if failure_from_stream:
            try:
                outcome = _public_result_outcome(await adapter.collect_result(handle))
            except (asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit):
                raise
            except Exception:  # noqa: BLE001 - public stream/collection failure is safe.
                return _failed_outcome("execution_error")
            if cleanup_failed and outcome.status != "failed":
                return _failed_outcome("execution_error")
            return outcome
        # Worker/acknowledgement failures are ordinary execution failures. Public
        # ExecutionErrorCode values are not private legacy codes; only a completed
        # public collect_result fallback may apply the R14 timeout translation.
        return _failed_outcome("execution_error")
