import asyncio
import logging
from math import isfinite
from time import monotonic
from uuid import uuid4

from agent_platform.core_platform.agent_execution.events.envelope import from_agent_event
from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
    build_execution_context,
    enforce_execution_rollout,
)
from agent_platform.core_platform.agent_runtime.notify import QUEUE_CHANNEL
from agent_platform.core_platform.agent_runtime.schemas import RuntimeFault
from agent_platform.core_platform.platform_services.tenant_isolation.context import (
    bind_scope,
    reset_scope,
)
from agent_platform.extension_contracts import (
    DEFAULT_BUSINESS_ID,
    DEFAULT_WORKSPACE_ID,
    BusinessScope,
    MemoryInjectionPort,
)

logger = logging.getLogger(__name__)


class RuntimeWorker:
    def __init__(
        self,
        repository,
        runtime,
        settings,
        fingerprint,
        notifier=None,
        listener=None,
        memory: MemoryInjectionPort | None = None,
        orchestrator=None,
    ):
        self.repository, self.runtime, self.settings = repository, runtime, settings
        self.fingerprint = fingerprint
        self.owner = uuid4()
        self.tasks = set()
        self.stopping = asyncio.Event()
        self.notifier = notifier
        self.listener = listener
        # Injected by the application composition root. The Runtime never
        # constructs a memory implementation itself.
        self.memory = memory
        self.orchestrator = orchestrator

    def _log_orchestrator_terminal(self, row, status, started_at):
        selector = getattr(self.orchestrator, "selector", None)
        execution_tuple = (
            "/".join(selector)
            if isinstance(selector, tuple) and all(isinstance(item, str) for item in selector)
            else "unavailable"
        )
        duration_ms = (monotonic() - started_at) * 1000.0
        if not isfinite(duration_ms) or duration_ms < 0:
            duration_ms = 0.0
        if status == "failed":
            logger.info(
                "Run %s execution path=orchestrator tuple=%s status=failed "
                "error=execution_failed duration_ms=%.3f",
                row["id"],
                execution_tuple,
                duration_ms,
            )
        else:
            logger.info(
                "Run %s execution path=orchestrator tuple=%s status=%s duration_ms=%.3f",
                row["id"],
                execution_tuple,
                status,
                duration_ms,
            )

    async def _execute(self, row):
        started_at = monotonic()
        monitor_failure = False
        scope = BusinessScope(
            tenant_id=row["tenant_id"],
            business_id=row.get("business_id") or DEFAULT_BUSINESS_ID,
            workspace_id=row.get("workspace_id") or DEFAULT_WORKSPACE_ID,
        )
        scope_token = bind_scope(scope)
        # The claim's database-owned Fencing tuple. None only on the pre-0068
        # legacy shape; production always carries it after the 0068 claim.
        lease_epoch = row.get("lease_epoch")
        # Only the post-0068 production row carries the tuple. Omitting the
        # keyword for the legacy shape keeps old test/compat repository seams
        # callable while production always sends it.
        epoch_kwargs = {} if lease_epoch is None else {"lease_epoch": lease_epoch}

        async def emit(kind, data):
            if kind == "model.delta":
                # Transient best-effort telemetry; never touches the durable log.
                if self.notifier is not None:
                    await self.notifier.send(row["id"], {"k": "delta", **data})
                return
            await self.repository.append(row["id"], self.owner, kind, data, **epoch_kwargs)

        append_event = getattr(self.repository, "append_event", None)

        async def emit_envelope(event):
            """Persist one AgentEvent through the deduplicating Repository path."""
            if event.event_type == "model.delta":
                # Transient telemetry stays outside the durable cursor.
                if self.notifier is not None:
                    await self.notifier.send(row["id"], {"k": "delta", **event.payload})
                return
            if not callable(append_event):
                # Legacy/compat repository seam without the T-04 method keeps
                # the two-argument path (including its pre-migration shape).
                await emit(event.event_type, event.payload)
                return
            await append_event(
                row["id"],
                self.owner,
                from_agent_event(event),
                **epoch_kwargs,
            )

        class _WorkerEventSink:
            async def __call__(self, kind, data):
                return await emit(kind, data)

            async def emit_event(self, event):
                return await emit_envelope(event)

        event_sink = _WorkerEventSink()

        async def monitor(task):
            nonlocal monitor_failure
            while True:
                await asyncio.sleep(1)
                try:
                    stop = await self.repository.heartbeat(
                        row["id"],
                        self.owner,
                        self.settings.lease_seconds,
                        **epoch_kwargs,
                    )
                except Exception:  # noqa: BLE001 - isolate failures at the worker boundary
                    stop = "lost"  # Fail closed if lease ownership cannot be established.
                if stop != "ok":
                    monitor_failure = stop == "lost"
                    task.cancel()
                    return

        # Both rollout flags are read exactly once per claim, before any other
        # decision, and kept in locals: the matrix, the selected path and every
        # later log line - including the exception and terminal branches below -
        # read these values instead of self.settings, so flipping a flag mid-Run
        # cannot re-decide a claimed row (03 §4.3, R-11/R-48). Reading them ahead
        # of the fingerprint guard is what keeps the earlier failure paths bound.
        #
        # The compared triple is the production registration, never
        # ``orchestrator.selector``: a double-injected selector is a test seam
        # for an Engine-specific adapter, and treating a published React row as
        # a mismatch under that seam would refuse the legacy path P2-IT-14
        # freezes. The refusal R-11/AC-10 requires is of a published
        # configuration that does not name the engine this deployment
        # registered (R-50).
        phase3_enabled = self.settings.execution_phase3_enabled
        orchestrator_enabled = self.settings.execution_orchestrator_enabled
        execution = None
        watcher = None
        try:
            if row["config"]["fingerprint"] != self.fingerprint:
                raise RuntimeFault("configuration_changed")
            enforce_execution_rollout(
                row,
                phase3_enabled=phase3_enabled,
                orchestrator_enabled=orchestrator_enabled,
                fault=RuntimeFault,
            )
            if orchestrator_enabled:
                if self.orchestrator is None:
                    raise RuntimeFault("execution_error")
                context = build_execution_context(
                    row,
                    history=row["history"],
                    summary_message=self._summary_message(row),
                    customer_memory=await self._customer_memory(row),
                    trace_id=row.get("trace_id"),
                    timeout_seconds=self.settings.run_timeout_seconds,
                    owner=self.owner,
                    lease_epoch=lease_epoch,
                    scope=scope,
                    execution_phase3_enabled=phase3_enabled,
                )
                execution = asyncio.create_task(self.orchestrator.execute(context, event_sink))
                watcher = asyncio.create_task(monitor(execution))
                outcome = await execution
                if outcome.status == "completed":
                    await self.repository.finish(
                        row["id"],
                        self.owner,
                        "completed",
                        output=outcome.output,
                        history=outcome.history,
                        completion=self._memory_context(row, outcome.dropped),
                        **epoch_kwargs,
                        usage=outcome.usage,
                    )
                else:
                    await self.repository.finish(
                        row["id"],
                        self.owner,
                        outcome.status,
                        error=outcome.legacy_error_code,
                        **epoch_kwargs,
                        usage=outcome.usage,
                    )
                self._log_orchestrator_terminal(row, outcome.status, started_at)
            else:
                runtime = (
                    await self.runtime.for_run(row, emit)
                    if hasattr(self.runtime, "for_run")
                    else self.runtime
                )
                execution = asyncio.create_task(
                    runtime.run(
                        row["input"],
                        row["history"],
                        emit,
                        summary_message=self._summary_message(row),
                        customer_memory=await self._customer_memory(row),
                    )
                )
                watcher = asyncio.create_task(monitor(execution))
                output, history, dropped = await execution
                await self.repository.finish(
                    row["id"],
                    self.owner,
                    "completed",
                    output=output,
                    history=history,
                    completion=self._memory_context(row, dropped),
                    **epoch_kwargs,
                )
        except asyncio.CancelledError:
            if execution:
                execution.cancel()
            if orchestrator_enabled:
                self._log_orchestrator_terminal(
                    row, "failed" if monitor_failure else "cancelled", started_at
                )
            await self.repository.finish(
                row["id"],
                self.owner,
                "failed" if monitor_failure else "cancelled",
                error="worker_lost" if monitor_failure else None,
                **epoch_kwargs,
            )
        except RuntimeFault as exc:
            if orchestrator_enabled:
                self._log_orchestrator_terminal(row, "failed", started_at)
            await self.repository.finish(
                row["id"], self.owner, "failed", error=exc.code, **epoch_kwargs
            )
        except TimeoutError:
            if orchestrator_enabled:
                self._log_orchestrator_terminal(row, "failed", started_at)
            await self.repository.finish(
                row["id"], self.owner, "failed", error="run_timeout", **epoch_kwargs
            )
        except Exception:  # noqa: BLE001 - isolate failures at the worker boundary
            # Provider errors may contain credentials or customer data; never expose raw messages.
            if orchestrator_enabled:
                self._log_orchestrator_terminal(row, "failed", started_at)
            else:
                logger.error("Run %s failed", row["id"])
            await self.repository.finish(
                row["id"],
                self.owner,
                "failed",
                error="execution_error",
                **epoch_kwargs,
            )
        finally:
            if watcher:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
            if execution:
                await asyncio.gather(execution, return_exceptions=True)
            reset_scope(scope_token)

    async def _customer_memory(self, row):
        if self.memory is None:
            return None
        return await self.memory.customer_memory(row, self.settings)

    def _summary_message(self, row):
        if self.memory is None:
            return None
        return self.memory.render_summary(row.get("summary"))

    def _memory_context(self, row, dropped):
        if self.memory is None:
            return None
        return self.memory.memory_context(row, dropped, self.settings)

    def _done(self, task):
        self.tasks.discard(task)
        if not task.cancelled() and task.exception():
            logger.error("Worker could not persist final state; lease reaper will recover it")

    async def serve(self):
        # A submitted run is claimed as soon as it is queued rather than at the next
        # poll, which removes most of the queue wait a customer sits through. The
        # timeout stays as the safety net for a missed notification.
        wake = asyncio.Event()

        def notified(_payload):
            wake.set()

        if self.listener is not None:
            await self.listener.on(QUEUE_CHANNEL, notified)
        try:
            while not self.stopping.is_set():
                # Cleared before claiming so a run queued while we are claiming still
                # wakes the wait below.
                wake.clear()
                try:
                    await self.repository.reap(self.settings.tenant_id)
                    while len(self.tasks) < self.settings.worker_concurrency:
                        row = await self.repository.claim(
                            self.owner, self.settings.lease_seconds, self.settings.tenant_id
                        )
                        if row is None:
                            break
                        task = asyncio.create_task(self._execute(row))
                        self.tasks.add(task)
                        task.add_done_callback(self._done)
                except Exception:  # noqa: BLE001 - isolate failures at the worker boundary
                    logger.error("Runtime database unavailable; retrying dispatcher")
                # Wake on a queue notification, on stop, or after the safety-net
                # timeout. Cancelling an Event waiter is safe: the set flag persists.
                pending = {
                    asyncio.ensure_future(wake.wait()),
                    asyncio.ensure_future(self.stopping.wait()),
                }
                _done, waiting = await asyncio.wait(
                    pending, timeout=0.5, return_when=asyncio.FIRST_COMPLETED
                )
                for task in waiting:
                    task.cancel()
                await asyncio.gather(*waiting, return_exceptions=True)
        finally:
            if self.listener is not None:
                await self.listener.off(QUEUE_CHANNEL, notified)
            tasks = list(self.tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def stop(self):
        self.stopping.set()
