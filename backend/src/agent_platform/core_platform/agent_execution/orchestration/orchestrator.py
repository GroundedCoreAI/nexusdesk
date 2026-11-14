"""Fixed-selector execution orchestration with exclusive Worker event delivery."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import TypeAlias

from pydantic import JsonValue

from ..capability.resolver import (
    CapabilityResolution,
    CapabilityResolver,
    PolicySourceUnavailableError,
)
from ..capability.snapshots import build_capability_snapshots
from ..contracts import (
    AdapterExecutionError,
    AgentEngineAdapter,
    AgentEvent,
    ConfigurationError,
    ExecutionErrorCode,
    ExecutionHandle,
    ExecutionRequest,
    ExecutionResult,
    ExecutionSnapshotError,
    build_execution_config_snapshot,
    effective_capability_flags,
    serialize_execution_snapshots,
)
from ..contracts.capabilities import NO_EXECUTION_RESTRICTIONS
from ..contracts.config import ExecutionConfig
from ..instructions import resolve_instruction_provider
from ..registry import AdapterRegistry
from .execution_context import (
    PRODUCTION_ADAPTER_SELECTOR,
    ExecutionContext,
    ExecutionSnapshotBarrier,
    InstructionPreparer,
    build_execution_request,
    disabled_capabilities_digest,
    execution_config_from_context,
    execution_rollout_fault,
    published_agent_identity,
    resolve_execution_capabilities,
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
_PRODUCTION_SELECTOR: AdapterSelector = PRODUCTION_ADAPTER_SELECTOR

# The Run-side vocabulary the Phase 3 barrier may emit. These are the codes the
# frontend already translates in four languages, so inventing a new one here is
# forbidden: an unmapped failure keeps its own existing code instead (R-50).
_BARRIER_SUCCESS_OUTCOMES = frozenset({"written", "reused"})
_ENGINE_UNAVAILABLE_CODE = "execution_engine_unavailable"
_CONFIG_INVALID_CODE = "execution_configuration_invalid"
_POLICY_UNAVAILABLE_CODE = "execution_policy_unavailable"
_PHASE3_DISABLED_CODE = "execution_phase3_disabled"
# ``not_claimed``/``lease_lost`` are the existing lost-lease/cancellation
# conditions and must never be reported as a configuration error (R-50/D5).
_LOST_LEASE_CODE = "worker_lost"
# Anything outside the table above keeps the pre-existing generic code; the wide
# boundary below may only apply this fallback to failures it cannot classify.


@dataclass(frozen=True, slots=True)
class _BarrierSuccess:
    """The barrier produced a runnable Phase 3 path for this claim.

    Carrying the prepared context, the fresh Adapter and the Phase 3 request is
    what keeps ``adapter.start`` after the snapshot commit and the public event
    order at claim intact (R-8/R-51): the orchestrator must not re-resolve with a
    context that has no prepared instructions, because that Adapter would consume
    no provider output at all.
    """

    context: ExecutionContext
    adapter: AgentEngineAdapter
    request: ExecutionRequest


@dataclass(frozen=True, slots=True)
class _BarrierFailure:
    """The barrier classified a failure inside its own Phase 3 step.

    The outcome is returned rather than raised so the wide ``except Exception``
    boundary in ``execute`` never sees these codes and cannot degrade them to
    ``execution_error`` (P3-IT-22 evidence face, R-45).
    """

    outcome: ExecutionOutcome


@dataclass(frozen=True, slots=True)
class _BarrierFault(Exception):
    """One classified Phase 3 barrier refusal carrying a stable Run code."""

    code: str


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
        capabilities: CapabilityResolver | None = None,
        snapshot_barrier: ExecutionSnapshotBarrier | None = None,
        snapshot_max_bytes: int | None = None,
        instruction_preparer: InstructionPreparer | None = None,
    ) -> None:
        if (
            not isinstance(selector, tuple)
            or len(selector) != 3
            or not all(isinstance(value, str) and value for value in selector)
        ):
            raise ValueError("selector must be one exact engine/protocol/version tuple")
        self._registry = registry
        self._selector = selector
        # Phase 3 wiring arrives as injected seams only. Without them the Run
        # keeps the exact Phase 2 path (off states must stay byte-identical), so
        # an unset barrier can never be read as "Phase 3 disabled" (R-50/D5).
        self._capabilities = capabilities
        self._snapshot_barrier = snapshot_barrier
        self._snapshot_max_bytes = snapshot_max_bytes
        self._instruction_preparer = instruction_preparer

    @property
    def selector(self) -> AdapterSelector:
        return self._selector

    @property
    def phase3_enabled(self) -> bool:
        """True only when every Phase 3 seam the barrier needs is wired."""
        return (
            self._capabilities is not None
            and self._snapshot_barrier is not None
            and self._snapshot_max_bytes is not None
            and self._instruction_preparer is not None
        )

    async def execute(
        self,
        context: ExecutionContext,
        worker_emit: WorkerEmit,
    ) -> ExecutionOutcome:
        if self.phase3_enabled:
            # The Phase 3 barrier returns the adapter and request it resolved on
            # the prepared path, and it classifies every failure itself. The wide
            # ``except Exception`` below would otherwise degrade each classified
            # code to ``execution_error``, which is exactly the P3-IT-22/A6
            # evidence loss (R-45).
            barrier = await self._phase3_barrier(context)
            if isinstance(barrier, _BarrierFailure):
                return barrier.outcome
            context, adapter, request = barrier.context, barrier.adapter, barrier.request
        else:
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

    async def _phase3_barrier(self, context: ExecutionContext) -> _BarrierSuccess | _BarrierFailure:
        """Run the frozen D6 data flow and classify every failure explicitly.

        The order is fixed by 03 §5.3 and 08 R-51/R-52: rollout re-check, capability
        resolution, the ``startup_allowed`` gate (R-16), the declaration-divergence
        comparison, the five snapshot DTOs, canonical serialization under the
        settings-derived byte ceiling, the write-once barrier, only then
        instruction preparation, the prepared context, the fresh Adapter and
        finally ``start``. Public ``run.started`` stays at claim and is never
        touched here (R-8).
        """
        try:
            code = execution_rollout_fault(
                context.row,
                phase3_enabled=True,
                orchestrator_enabled=True,
                selector=self._selector,
            )
            if code is not None:
                raise _BarrierFault(code)
            execution_config = execution_config_from_context(context)
            descriptor = self._registry.metadata(*self._selector)
            agent_identity = published_agent_identity(context)
            resolution = await resolve_execution_capabilities(
                self._capabilities,
                context,
                execution_config,
            )
            if not resolution.startup_allowed:
                raise _BarrierFault(_required_missing_code(resolution))
            await self._assert_declared(context)
            snapshots = build_capability_snapshots(
                context.execution_id,
                resolution,
                disabled_capabilities_digest=disabled_capabilities_digest(
                    execution_config.disabled_capabilities
                ),
                execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
            )
            config_snapshot = build_execution_config_snapshot(
                execution_id=context.execution_id,
                config=execution_config,
                agent_id=agent_identity[0],
                agent_version=agent_identity[1],
                provider_id=descriptor.instruction_provider_id,
                provider_version=descriptor.provider_version,
            )
            serialized = serialize_execution_snapshots(
                config=config_snapshot,
                declared=snapshots.declared,
                available=snapshots.available,
                policy=snapshots.policy,
                effective=snapshots.effective,
                # R-52: the ceiling is always passed explicitly. The serializer
                # default is a module constant that settings may legitimately
                # override, and omitting it would silently store payloads above
                # the deployment bound with no error at all.
                max_bytes=self._snapshot_max_bytes,
            )
            outcome = await self._snapshot_barrier.write(
                run_id=context.execution_id,
                owner=context.owner,
                execution_id=context.execution_id,
                payloads=serialized.payloads,
            )
            if outcome not in _BARRIER_SUCCESS_OUTCOMES:
                raise _BarrierFault(_barrier_outcome_code(outcome))
            instruction = self._instruction_preparer.prepare_instructions(
                context.row,
                history=context.history,
                summary_message=context.summary_message,
                customer_memory=context.customer_memory,
            )
            prepared = resolve_instruction_provider(
                descriptor.instruction_provider_id, descriptor.provider_version
            ).prepare(instruction)
            phase3_context = replace(context, prepared_instructions=prepared)
            request = self._phase3_request(phase3_context, execution_config, resolution)
            adapter = resolve_with_execution_context(
                phase3_context,
                lambda: self._registry.resolve(*self._selector),
            )
            return _BarrierSuccess(phase3_context, adapter, request)
        except (asyncio.CancelledError, KeyboardInterrupt, SystemExit, GeneratorExit):
            raise
        except Exception as exception:  # noqa: BLE001 - the barrier classifies its own face.
            return _BarrierFailure(_failed_outcome(_classify_barrier_failure(exception)))

    async def _assert_declared(self, context: ExecutionContext) -> None:
        """Compare an instance declaration against the registered declaration.

        This is the one genuinely reachable deployment-divergence signal in Phase 3
        (R-43): the Registry declaration is code data, while a fresh Adapter answers
        ``get_capabilities()`` itself, so a mismatch means the running Engine does
        not ship what the deployment registered. It runs on the Run path after the
        resolution and before any snapshot write or ``adapter.start``, so divergence
        fails closed with ``Adapter.start`` at zero (03 §3.1).
        """
        descriptor = self._registry.metadata(*self._selector)
        instance = resolve_with_execution_context(
            context,
            lambda: self._registry.resolve(*self._selector),
        )
        declared = await instance.get_capabilities()
        if declared != descriptor.declared:
            raise _BarrierFault(_CONFIG_INVALID_CODE)

    def _phase3_request(
        self,
        context: ExecutionContext,
        execution_config: ExecutionConfig,
        resolution: CapabilityResolution,
    ) -> ExecutionRequest:
        """Build the Phase 3 request: identity first, then the two projections.

        ``effective_capabilities`` is the unique R-21 flags projection of the same
        ``CapabilityResolution`` the snapshots were built from; an inline dict
        comprehension or a raw cache read is the P1 defect R-22 names. ``config``
        carries the canonical execution config, which stays ``{}`` on every off
        path because the barrier never runs there.
        """
        request = build_execution_request(context)
        if self._selector != _PRODUCTION_SELECTOR:
            request = request.model_copy(
                update={
                    "engine_id": self._selector[0],
                    "protocol_id": self._selector[1],
                    "adapter_version": self._selector[2],
                }
            )
        return request.model_copy(
            update={
                "config": execution_config.model_dump(mode="json"),
                "effective_capabilities": effective_capability_flags(resolution.effective),
            }
        )

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


def _classify_barrier_failure(failure: BaseException) -> str:
    """Map one barrier failure onto the existing Run-side vocabulary (R-50/D5).

    Every branch returns a code the frontend already translates; nothing new is
    invented, and nothing classified here may degrade to ``execution_error``.
    """
    if isinstance(failure, _BarrierFault):
        return failure.code
    if isinstance(failure, PolicySourceUnavailableError):
        # The trusted revision read failed outright: policy, never configuration.
        return _POLICY_UNAVAILABLE_CODE
    if isinstance(failure, ExecutionSnapshotError):
        # serialization / denylist / missing-or-duplicate item / oversize
        return _CONFIG_INVALID_CODE
    if isinstance(failure, ConfigurationError):
        if isinstance(failure, AdapterExecutionError) and _is_registry_identity_fault(failure):
            return _CONFIG_INVALID_CODE
        return _ENGINE_UNAVAILABLE_CODE
    if isinstance(failure, AdapterExecutionError):
        # A fresh Adapter refused the request: its public code is already the
        # classification, exactly as on the Phase 2 path.
        return failure.error.code.value
    return "execution_error"


_REGISTRY_IDENTITY_CODES = frozenset(
    {
        "invalid_request",
        "adapter_identity_mismatch",
        "adapter_contract_mismatch",
        "adapter_factory_failed",
    }
)


def _is_registry_identity_fault(failure: ConfigurationError) -> bool:
    return failure.error.code.value in _REGISTRY_IDENTITY_CODES


def _required_missing_code(resolution: CapabilityResolution) -> str:
    """Classify a required-capability gap as policy or engine, per its reason.

    ``policy_unavailable`` (a cold or failed policy layer, including a refresh
    that stayed cold) maps to the policy code; every infrastructure reason
    (probe unavailable/timed out/stale, workspace unavailable) maps to the engine
    code. Benign narrowing never reaches this helper at all because
    ``startup_allowed`` stayed true (R-16).
    """
    reasons = {
        item.reason_code
        for item in resolution.effective.items
        if item.name in set(resolution.effective.required_capabilities_missing)
    }
    if reasons == {"policy_unavailable"}:
        return _POLICY_UNAVAILABLE_CODE
    return _ENGINE_UNAVAILABLE_CODE


def _barrier_outcome_code(outcome: str) -> str:
    """Map one controlled write outcome onto a Run code (R-50/D5).

    ``not_claimed`` and ``lease_lost`` are the existing lost-lease/cancellation
    conditions and must never be reported as a configuration error;
    ``audit_conflict`` is a startup-identity disagreement and fails closed as one.
    """
    if outcome in _BARRIER_SUCCESS_OUTCOMES:
        raise AssertionError("success outcomes never reach the failure mapper")
    if outcome == "audit_conflict":
        return _CONFIG_INVALID_CODE
    if outcome in ("not_claimed", "lease_lost"):
        return _LOST_LEASE_CODE
    return _CONFIG_INVALID_CODE
