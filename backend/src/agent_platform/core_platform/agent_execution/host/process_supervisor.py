"""Process-group supervisor: TERM -> grace -> KILL -> reap (08 T8, 02 FR-3).

One cleanup state machine owns every cancellation, wall-timeout and output
breach path (03 §4.3): repeated calls return the same progress and never
duplicate signals ("single cleanup owner under races", P4-UT-05); escalation
applies to the whole process group so TERM-ignoring descendants are taken by
KILL (P4-IT-05/06); a group that cannot be confirmed gone ends in
``cleanup_failed`` with an alert, never a false cleanup success (core rule,
08 §6). Deadlines use the injected monotonic clock while persisted fields use
the POSIX source (Phase 3 R-49 precedent). Run terminal state is never
touched here: the Worker/Repository keep sole ownership (FR-1).
"""

import asyncio
import logging
import os
import signal
import time
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from .host_models import (
    REASON_CANCELLED,
    REASON_CLEANUP_FAILED,
    REASON_EXITED,
    REASON_OUTPUT_LIMIT_EXCEEDED,
    REASON_PIPE_SETUP_FAILED,
    REASON_RECOVERY_TERMINATED,
    REASON_WALL_TIMEOUT,
    ExitObservation,
    HostReasonCode,
    ManagedProcess,
    ProcessResult,
)
from .process_identity import group_alive
from .process_runner import StartedProcess

logger = logging.getLogger(__name__)

_TERMINATE_REASON_BY_BREACH: dict[str, HostReasonCode] = {
    "output_limit": REASON_OUTPUT_LIMIT_EXCEEDED,
    "pipe_failure": REASON_PIPE_SETUP_FAILED,
    "wall_timeout": REASON_WALL_TIMEOUT,
    "cancelled": REASON_CANCELLED,
    "recovery": REASON_RECOVERY_TERMINATED,
}


class SupervisorStateError(RuntimeError):
    """Illegal supervisor operation against a terminal or identity-less handle."""


class CleanupTarget(Protocol):
    """What the escalation machine needs from any live or recovered handle."""

    managed: ManagedProcess

    async def wait_exit(self, timeout: float) -> ExitObservation: ...


class GroupHandle:
    """Recovery-side handle: group identity only, no adopted pipes (03 §4.4).

    Recovery can neither reap nor read a foreign process, so ``wait_exit``
    observes group liveness only and reports ``absent``/``alive`` honestly -
    the exit code of an orphan is never fabricated.
    """

    def __init__(self, managed: ManagedProcess) -> None:
        if managed.process_group_id is None:  # pragma: no cover - guard
            raise SupervisorStateError("orphan handle carries no process group identity")
        self.managed = managed

    async def wait_exit(self, timeout: float) -> ExitObservation:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if not await asyncio.to_thread(group_alive, self.managed.process_group_id):
                return ExitObservation("absent", None)
            await asyncio.sleep(0.02)
        return ExitObservation("alive", None)


class ProcessSupervisor:
    """TERM/KILL escalation, races and idempotent cleanup for managed groups."""

    def __init__(
        self,
        *,
        cancel_grace_seconds: float,
        kill_timeout_seconds: float,
        clock: Callable[[], float] | None = None,
        monotonic: Callable[[], float] | None = None,
        alert: Callable[[str, UUID], None] | None = None,
    ) -> None:
        if cancel_grace_seconds <= 0 or kill_timeout_seconds <= 0:
            raise ValueError("grace and kill windows must be positive")
        # Public so the composition stop-timeout guard (T14) can assert the
        # windows fit the deployment stop grace (03 §4.3).
        self.cancel_grace_seconds = cancel_grace_seconds
        self.kill_timeout_seconds = kill_timeout_seconds
        self._clock = clock or time.time
        self._monotonic = monotonic or time.monotonic
        self._alert = alert
        # One cleanup owner per managed id plus one retained result per id:
        # repeated cancel/reconcile enters the same machine and returns the
        # same progress (P4-UT-05, 03 §4.3).
        self._cleanups: dict[UUID, asyncio.Task[ProcessResult]] = {}
        self._results: dict[UUID, ProcessResult] = {}

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    async def wait(
        self,
        started: StartedProcess,
        *,
        wall_seconds: float | None = None,
        run_deadline_monotonic: float | None = None,
    ) -> ProcessResult:
        """Await exit racing wall timeout, earlier-deadline-wins, and output flood.

        The earlier of the process wall ceiling and the Run deadline wins
        (03 §4.3); an output breach or pipe read failure terminates the group
        with its stable reason (FR-2 failure row).
        """
        managed_id = started.managed.managed_id
        if managed_id in self._cleanups:
            return await asyncio.shield(self._cleanups[managed_id])
        if managed_id in self._results:
            return self._results[managed_id]
        if started.managed.state not in ("starting", "running", "terminating"):
            raise SupervisorStateError(f"process {managed_id} already {started.managed.state}")

        task = asyncio.create_task(self._wait_once(started, wall_seconds, run_deadline_monotonic))
        return await self._track(managed_id, task)

    async def cancel(
        self, target: CleanupTarget, *, reason: HostReasonCode = REASON_CANCELLED
    ) -> ProcessResult:
        """Idempotent cancellation through the shared cleanup machine."""
        managed_id = target.managed.managed_id
        if managed_id in self._results:
            return self._results[managed_id]
        if managed_id in self._cleanups:
            return await asyncio.shield(self._cleanups[managed_id])
        if target.managed.state in ("exited", "cleanup_failed"):
            raise SupervisorStateError(
                f"process {managed_id} already {target.managed.state} with no retained result"
            )
        task = asyncio.create_task(self._escalate(target, reason=reason))
        return await self._track(managed_id, task)

    async def terminate_orphan(self, handle: GroupHandle) -> ProcessResult:
        """Recovery termination of an identity-matched orphan (03 §4.4)."""
        return await self.cancel(handle, reason=REASON_RECOVERY_TERMINATED)

    def forget(self, managed_id: UUID) -> None:
        """Drop retained progress bookkeeping when the Host closes the record."""
        self._results.pop(managed_id, None)
        self._cleanups.pop(managed_id, None)

    async def _track(self, managed_id: UUID, task: asyncio.Task[ProcessResult]) -> ProcessResult:
        self._cleanups[managed_id] = task
        try:
            result = await asyncio.shield(task)
        finally:
            if task.done() and not task.cancelled():
                self._results[managed_id] = task.result()
            self._cleanups.pop(managed_id, None)
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _wait_once(
        self,
        started: StartedProcess,
        wall_seconds: float | None,
        run_deadline_monotonic: float | None,
    ) -> ProcessResult:
        deadlines = [
            value
            for value in (
                self._monotonic() + wall_seconds if wall_seconds is not None else None,
                run_deadline_monotonic,
            )
            if value is not None
        ]
        deadline = min(deadlines) if deadlines else None

        pump = started.pump
        exit_task = asyncio.create_task(started.process.wait())
        watch: dict[asyncio.Future, HostReasonCode] = {exit_task: REASON_EXITED}
        watch[asyncio.create_task(pump.stdout.overflowed.wait())] = REASON_OUTPUT_LIMIT_EXCEEDED
        watch[asyncio.create_task(pump.stderr.overflowed.wait())] = REASON_OUTPUT_LIMIT_EXCEEDED
        watch[asyncio.create_task(pump.stdout.error_event.wait())] = REASON_PIPE_SETUP_FAILED
        watch[asyncio.create_task(pump.stderr.error_event.wait())] = REASON_PIPE_SETUP_FAILED

        try:
            timeout = None if deadline is None else max(0.0, deadline - self._monotonic())
            done, _ = await asyncio.wait(
                set(watch), timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if exit_task in done:  # a natural exit always wins the race
                exit_code = exit_task.result()
                await pump.drain()
                return await self._attach_async(
                    started,
                    self._finish(
                        started.managed,
                        final_state="exited",
                        exit_code=exit_code,
                        reason=REASON_EXITED,
                    ),
                )
            breach = next(
                (watch[future] for future in done if watch[future] != REASON_EXITED), None
            )
            if breach is not None:
                return await self._escalate(started, reason=breach)
            # Deadline expired before any completion: terminate the group.
            return await self._escalate(started, reason=REASON_WALL_TIMEOUT)
        finally:
            for future in watch:
                if not future.done():
                    future.cancel()
            await pump.aclose()

    async def _escalate(self, target: CleanupTarget, *, reason: HostReasonCode) -> ProcessResult:
        managed = target.managed
        pgid = managed.process_group_id or managed.os_pid
        if pgid is None:
            raise SupervisorStateError("cannot signal a handle without process group identity")

        if managed.state in ("starting", "running", "orphaned"):
            self._signal_group(pgid, signal.SIGTERM)
        observation = await target.wait_exit(self.cancel_grace_seconds)
        if observation.status in ("exited", "absent"):
            return await self._attach_async(
                target,
                self._finish(
                    managed, final_state="exited", exit_code=observation.exit_code, reason=reason
                ),
            )
        self._signal_group(pgid, signal.SIGKILL)
        observation = await target.wait_exit(self.kill_timeout_seconds)
        if observation.status in ("exited", "absent"):
            return await self._attach_async(
                target,
                self._finish(
                    managed, final_state="exited", exit_code=observation.exit_code, reason=reason
                ),
            )
        if not await asyncio.to_thread(group_alive, pgid):
            # KILL landed but the reaper cannot confirm the code: exited with
            # an honestly unknown exit code, never a fabricated status.
            return await self._attach_async(
                target, self._finish(managed, final_state="exited", exit_code=None, reason=reason)
            )
        return await self._attach_async(
            target, self._fail_cleanup(managed, pgid=pgid, reason=reason)
        )

    async def _attach_async(self, target: object, result: ProcessResult) -> ProcessResult:
        """Bounded pump drain, then attach output payloads for the Adapter parser."""
        pump = getattr(target, "pump", None)
        if pump is None:
            return result
        await pump.drain()
        return result.model_copy(
            update={
                "stdout": pump.stdout.payload(),
                "stderr": pump.stderr.payload(),
                "stdout_truncated": pump.stdout.truncated,
                "stderr_truncated": pump.stderr.truncated,
            }
        )

    def _signal_group(self, pgid: int, sig: int) -> None:
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass  # group already gone; the wait/probe path decides the state
        except PermissionError:  # pragma: no cover - foreign groups never get here
            logger.warning("runtime host signal refused")

    def _fail_cleanup(
        self, managed: ManagedProcess, *, pgid: int, reason: HostReasonCode
    ) -> ProcessResult:
        """KILL window exhausted: escalate visibly, never claim cleanup success."""
        logger.error(
            "runtime host cleanup failed trigger=%s managed_id=%s pgid=%s",
            _TERMINATE_REASON_BY_BREACH.get(reason, reason),
            managed.managed_id,
            pgid,
        )
        if self._alert is not None:
            self._alert(REASON_CLEANUP_FAILED, managed.managed_id)
        return self._finish(
            managed, final_state="cleanup_failed", exit_code=None, reason=REASON_CLEANUP_FAILED
        )

    def _finish(
        self,
        managed: ManagedProcess,
        *,
        final_state: str,
        exit_code: int | None,
        reason: HostReasonCode,
    ) -> ProcessResult:
        """Close out through the transition map - it judges legality (pin R-4)."""
        current = managed
        if current.state != "terminating":
            current = current.transition_to("terminating")
        current = current.transition_to(final_state)  # type: ignore[arg-type]
        term_signal = -exit_code if exit_code is not None and exit_code < 0 else None
        wall_seconds = max(
            0.0,
            self._clock() - (managed.started_at_posix or self._clock()),
        )
        return ProcessResult(
            managed_id=current.managed_id,
            run_id=current.run_id,
            final_state=final_state,  # type: ignore[arg-type]
            reason_code=reason,
            exit_code=None if term_signal is not None else exit_code,
            term_signal=term_signal,
            wall_seconds=wall_seconds,
        )
