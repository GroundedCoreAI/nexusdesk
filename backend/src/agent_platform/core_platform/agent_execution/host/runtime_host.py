"""RuntimeHost contract: start/cancel/wait/reconcile/health/close (08 T10).

One Host object owns admission, the durable process records, supervision and
recovery for a single execution root. Adapters only ever talk through this
contract (AC-1): the Host parses no engine output, commits no Run terminal
state, and its public-facing artifacts never carry PID/PGID/start tokens,
absolute host paths or environment values - ``ExecutionHandle.process_id``
stays unset for Host-managed executions (08 R-4b). The composition entry
takes Runner/Supervisor/Registry plus optional Workspace/Resource/Sandbox
ports (slots arrive in T11-T13); with ``execution_runtime_host_enabled=false``
admission refuses everything (REASON_ADMISSION_CLOSED) while ``reconcile``
stays usable so the recovery/cleanup path keeps working (03 §5.1).
"""

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .host_models import (
    HOST_REASON_CODES,
    REASON_ADMISSION_CLOSED,
    REASON_CLEANUP_FAILED,
    REASON_IDENTITY_MISMATCH,
    REASON_MANUAL_REMEDIATION,
    REASON_SPAWN_FAILED,
    REASON_UNTRUSTED_TARGET,
    HostHealth,
    ManagedProcess,
    ProcessResult,
    ProcessSpec,
)
from .observability import (
    EVENT_MANUAL_REMEDIATION,
    EVENT_PROCESS_EXITED,
    EVENT_RECONCILE_DEFERRED,
    EVENT_RECOVERY_BATCH,
    EVENT_START_FAILED,
    EVENT_START_REFUSED,
    AlertSink,
    ObservabilityRecord,
)
from .process_identity import capture_start_token_async, group_alive
from .process_registry import (
    ProcessRecordRow,
    ProcessRegistry,
    RegistryUnavailableError,
    orphan_decision,
)
from .process_runner import ProcessRunner, StartedProcess, UntrustedTargetError
from .process_supervisor import GroupHandle, ProcessSupervisor, SupervisorStateError
from .sandbox_provider import SandboxPolicyError

logger = logging.getLogger(__name__)

# The manager-level Workdir vocabulary is the second frozen code space for
# alerts (workspace_provider.WorkdirErrorCode); anything outside the two
# vocabularies collapses in _stable_code.
_WORKDIR_CODE_RE = re.compile(r"workdir_[a-z0-9_]+")


class HostAdmissionError(RuntimeError):
    """Admission gate refusal before any spawn or record side effect."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code


class HostStartError(RuntimeError):
    """Fail-closed start failure after pre-spawn validation or spawn."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True)
class ReconcileSummary:
    """Honest per-run outcomes; skipped rows are current-boot supervised live."""

    terminated: int = 0
    manual_remediation: int = 0
    absent: int = 0
    skipped_current_boot: int = 0
    db_unavailable: bool = False


@dataclass
class _Tracked:
    started: StartedProcess
    result: ProcessResult | None = None
    reservation: object | None = None


class RuntimeHost:
    """Composition entry: Host contract plus durable record ownership."""

    def __init__(
        self,
        *,
        enabled: bool,
        host_id: str,
        runner: ProcessRunner,
        supervisor: ProcessSupervisor,
        registry: ProcessRegistry,
        wall_timeout_seconds: float,
        resource_enforcement_required: bool = True,
        sandbox_provider_id: str = "local/v1",
        resource_manager: Any | None = None,
        sandbox_provider: Any | None = None,
        workspace_manager: Any | None = None,
        identity_probe: Callable[[int], Any] | None = None,
        clock: Callable[[], float] | None = None,
        alert_sink: AlertSink | None = None,
    ) -> None:
        if enabled and not host_id.strip():
            raise ValueError("enabled RuntimeHost requires a stable host id")
        if wall_timeout_seconds <= 0:
            raise ValueError("wall timeout must be positive")
        self._enabled = enabled
        self._host_id = host_id
        self._runner = runner
        self._supervisor = supervisor
        self._registry = registry
        self._wall_timeout = wall_timeout_seconds
        self._resource_enforcement_required = resource_enforcement_required
        self._sandbox_provider_id = sandbox_provider_id
        # Ports B4/B5 fill in; unset slots skip their gate (Phase 3 seam rule).
        self.resource_manager = resource_manager
        self.sandbox_provider = sandbox_provider
        self.workspace_manager = workspace_manager
        self._identity_probe = identity_probe or capture_start_token_async
        self._clock = clock or time.time
        # T15 FR-9 seam: cumulative, low-cardinality observability counters
        # keyed only by frozen code strings plus one alert sink shared with
        # the supervisor/registry/workspace lanes.
        self._alert_sink = alert_sink
        self._start_failures: dict[str, int] = {}
        self._exit_reasons: dict[str, int] = {}
        self._recovery_terminated = 0
        self._recovery_manual = 0
        self._admitting = enabled
        self._closed = False
        self._tracked: dict[UUID, _Tracked] = {}
        self._last_reconcile_at: float | None = None

    @property
    def host_instance_id(self) -> str:
        return self._registry.host_instance_id

    @property
    def registry(self) -> ProcessRegistry:
        """Read-only port for health/audit consumers (T15); never for bypassing."""
        return self._registry

    # ------------------------------------------------------------------
    # Contract operations (03 §4.1)
    # ------------------------------------------------------------------

    async def start(
        self,
        spec: ProcessSpec,
        *,
        run_id: UUID,
        tenant_id: str,
        working_dir: Path,
        workdir_id: UUID | None = None,
        managed_id: UUID | None = None,
    ) -> ManagedProcess:
        """Validate the trusted target, register, spawn and attach - fail closed.

        Pre-spawn rejections (untrusted target, admission closed) leave zero
        side effects: no record, no process, no directory touch. Post-record
        failures are cleaned in reverse order through the same managed handle
        (03 §4.2) and the record is closed honestly.
        """
        if not self._admitting or self._closed:
            raise HostAdmissionError(REASON_ADMISSION_CLOSED)
        try:
            self._runner.resolve_trusted(spec)  # allowlist gate before any side effect
        except UntrustedTargetError as exc:
            logger.warning(
                "runtime host rejected untrusted target executable_id=%s run_id=%s",
                spec.executable_id,
                run_id,
            )
            self._record_start_failure(REASON_UNTRUSTED_TARGET)
            self._alert(
                EVENT_START_REFUSED,
                "warning",
                REASON_UNTRUSTED_TARGET,
                run_id=run_id,
                fields={"executable_id": spec.executable_id},
            )
            raise HostStartError(REASON_UNTRUSTED_TARGET, exc.detail) from exc

        # B4 ports: with a Sandbox/Resource Provider wired, support checks and
        # the untrusted gate run here before any durable side effect (03 §4.2
        # barrier order); unset slots skip the gate (Phase 3 seam rule).
        reservation = await self._admit_resources(spec, run_id)

        record_id = managed_id or uuid4()
        await self._registry.register_starting(
            managed_id=record_id,
            run_id=run_id,
            tenant_id=tenant_id,
            command_digest=spec.command_digest,
            workdir_id=workdir_id,
            metadata={"executable_id": spec.executable_id},
        )
        try:
            started = await self._runner.start(
                spec,
                run_id=run_id,
                managed_id=record_id,
                host_id=self._host_id,
                host_instance_id=self._registry.host_instance_id,
                sandbox_provider=self._sandbox_provider_id,
                working_dir=working_dir,
                preexec=self._preexec_for(reservation),
            )
        except Exception as exc:
            code = self._stable_code(getattr(exc, "code", REASON_SPAWN_FAILED))
            self._record_start_failure(code)
            self._alert(EVENT_START_FAILED, "error", code, run_id=run_id, managed_id=record_id)
            await self._release(reservation)
            await self._registry.mark_state(
                managed_id=record_id,
                from_states=("starting",),
                to_status="exited",
                last_error_code=code,
                metadata_merge={"recovery": "start-failed"},
                run_id=run_id,
            )
            raise HostStartError(code) from exc

        await self._registry.attach_spawn(managed=started.managed)
        self._tracked[record_id] = _Tracked(started=started, reservation=reservation)
        return started.managed

    async def wait(
        self,
        managed_id: UUID,
        *,
        wall_seconds: float | None = None,
        run_deadline_monotonic: float | None = None,
    ) -> ProcessResult:
        """Supervised wait racing the earlier of wall ceiling and Run deadline."""
        tracked = self._require_tracked(managed_id)
        if tracked.result is not None:
            return tracked.result
        ceiling = wall_seconds if wall_seconds is not None else self._wall_timeout
        result = await self._supervisor.wait(
            tracked.started,
            wall_seconds=ceiling,
            run_deadline_monotonic=run_deadline_monotonic,
        )
        result = self._classify(tracked, result)
        tracked.result = result
        self._observe_result(result)
        await self._persist_result(result)
        await self._release(tracked.reservation)
        self._untrack(managed_id)
        return result

    async def cancel(self, managed_id: UUID, *, reason: str | None = None) -> ProcessResult:
        """Idempotent cancellation of one managed group through the supervisor."""
        tracked = self._require_tracked(managed_id)
        if tracked.result is not None:
            return tracked.result
        result = await self._supervisor.cancel(
            tracked.started,
            **({"reason": reason} if reason is not None else {}),
        )
        result = self._classify(tracked, result)
        tracked.result = result
        self._observe_result(result)
        await self._persist_result(result)
        await self._release(tracked.reservation)
        self._untrack(managed_id)
        return result

    async def reconcile(self, *, batch_size: int = 16) -> ReconcileSummary:
        """Identity-verified recovery of durable records for this host_id.

        Bounded batches with FOR UPDATE SKIP LOCKED; records from the current
        boot instance are live supervision and only observed; foreign-boot rows
        run the 03 §4.4 decision table: match -> TERM/KILL through the group
        handle, mismatch/unverifiable -> zero signals plus manual remediation,
        group gone -> honest closure. DB outage retries the connection and
        never triggers a host-wide scan.
        """
        try:
            rows = await self._registry.fetch_pending(batch_size=batch_size)
        except RegistryUnavailableError:
            logger.error("runtime host reconcile deferred: registry unavailable")
            self._alert(EVENT_RECONCILE_DEFERRED, "warning", None)
            return ReconcileSummary(db_unavailable=True)
        terminated = manual = absent = skipped = 0
        for row in rows:
            if row.host_instance_id == self._registry.host_instance_id:
                skipped += 1  # current boot: supervised live work, not an orphan
                continue
            outcome = await self._decide(row)
            if outcome == "terminate":
                await self._terminate_row(row)
                terminated += 1
            elif outcome == "manual":
                manual += 1
            else:
                absent += 1
        self._last_reconcile_at = self._clock()
        self._recovery_terminated += terminated
        self._recovery_manual += manual
        if rows:
            # FR-9 recovery batch fact: one info record per nonempty pass,
            # counts only - ids stay on the per-row alerts.
            self._alert(
                EVENT_RECOVERY_BATCH,
                "info",
                None,
                fields={
                    "terminated": terminated,
                    "manual_remediation": manual,
                    "absent": absent,
                    "current_boot_skipped": skipped,
                },
            )
        return ReconcileSummary(
            terminated=terminated,
            manual_remediation=manual,
            absent=absent,
            skipped_current_boot=skipped,
        )

    def health(self) -> HostHealth:
        """Aggregated snapshot over tracked live groups (T15 extends)."""
        counts: dict[str, int] = {}
        for tracked in self._tracked.values():
            state = (
                tracked.started.managed.state
                if tracked.result is None
                else tracked.result.final_state
            )
            counts[state] = counts.get(state, 0) + 1
        age = (
            None
            if self._last_reconcile_at is None
            else max(0.0, self._clock() - self._last_reconcile_at)
        )
        return HostHealth(
            host_id=self._host_id,
            host_instance_id=self._registry.host_instance_id,
            sandbox_provider=self._sandbox_provider_id,
            admission_enabled=self._admitting and not self._closed,
            resource_enforcement_required=self._resource_enforcement_required,
            starting_count=counts.get("starting", 0),
            running_count=counts.get("running", 0),
            terminating_count=counts.get("terminating", 0),
            orphaned_count=counts.get("orphaned", 0),
            cleanup_failed_count=counts.get("cleanup_failed", 0),
            last_reconcile_age_seconds=age,
            start_failure_count=sum(self._start_failures.values()),
            exit_reason_counts=dict(self._exit_reasons),
            recovery_terminated_count=self._recovery_terminated,
            recovery_manual_remediation_count=self._recovery_manual,
        )

    async def health_report(self) -> HostHealth:
        """Health snapshot joined with the durable Workdir footprint (T15).

        The synchronous :meth:`health` carries only in-process truth; this
        read adds the FR-9 disk usage / retention-age / cleanup-failure
        columns from the workspace port when one is wired. Operational reads
        use this object; no public HTTP surface is added in Phase 4 (08 §6
        defers an internal endpoint to an issue candidate).
        """
        health = self.health()
        if self.workspace_manager is None:
            return health
        stats = await self.workspace_manager.stats()
        return health.model_copy(
            update={
                "workdir_cleanup_failed_count": stats.cleanup_failed_count,
                "workdir_live_bytes": stats.live_bytes,
                "workdir_retained_count": stats.retained_count,
                "workdir_oldest_retention_age_seconds": stats.oldest_retention_age_seconds,
            }
        )

    async def close(self) -> int:
        """Stop admission, cancel/drain tracked groups, report survivors.

        Worker-stop semantics: every tracked group goes through the same
        bounded TERM/KILL machine (default 5s + 5s fits the 45s stop grace,
        03 §4.3); zero active is the precondition for full Supervisor
        shutdown at the composition root (T14).
        """
        self._admitting = False
        pending = [
            managed_id for managed_id, tracked in self._tracked.items() if tracked.result is None
        ]
        await asyncio.gather(
            *(self.cancel(managed_id) for managed_id in pending),
            return_exceptions=True,
        )
        self._closed = True
        remaining = sum(1 for tracked in self._tracked.values() if tracked.result is None)
        if remaining:
            # Drain left survivors: manual remediation is owed (FR-9 alert,
            # never a silently swallowed shutdown).
            self._alert(
                EVENT_MANUAL_REMEDIATION,
                "error",
                REASON_MANUAL_REMEDIATION,
                fields={"survivors": remaining},
            )
        return remaining

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _admit_resources(self, spec: ProcessSpec, run_id: UUID):
        if self.resource_manager is not None:
            admit = self.resource_manager.admit
        elif self.sandbox_provider is not None:
            admit = self.sandbox_provider.prepare
        else:
            return None
        try:
            return await admit(spec, run_id=run_id)
        except SandboxPolicyError as exc:
            logger.warning("runtime host refused admission run_id=%s code=%s", run_id, exc.code)
            self._record_start_failure(self._stable_code(exc.code))
            self._alert(EVENT_START_REFUSED, "warning", self._stable_code(exc.code), run_id=run_id)
            raise HostStartError(exc.code) from exc

    def _preexec_for(self, reservation):
        if reservation is None:
            return None
        if self.resource_manager is not None:
            return self.resource_manager.preexec_for(reservation)
        if self.sandbox_provider is not None:
            return self.sandbox_provider.preexec_for(reservation)
        return None

    async def _release(self, reservation) -> None:
        if reservation is None:
            return
        if self.resource_manager is not None:
            await self.resource_manager.release(reservation)
        elif self.sandbox_provider is not None:
            await self.sandbox_provider.release(reservation)

    def _classify(self, tracked: _Tracked, result: ProcessResult) -> ProcessResult:
        """Relabel kernel-enforced rlimit kills via the resource port (T12).

        Purely a reason relabel (EXITED + SIGXCPU/SIGXFSZ -> resource
        excess); states and the exit machine itself are untouched, and an
        unset resource port passes the Supervisor's reason through.
        """
        if self.resource_manager is None or tracked.reservation is None:
            return result
        return self.resource_manager.classify_result(result, tracked.reservation)

    def _require_tracked(self, managed_id: UUID) -> _Tracked:
        tracked = self._tracked.get(managed_id)
        if tracked is None:
            raise SupervisorStateError(f"managed id {managed_id} is not tracked on this host")
        return tracked

    def _untrack(self, managed_id: UUID) -> None:
        self._tracked.pop(managed_id, None)
        self._supervisor.forget(managed_id)

    async def _persist_result(self, result: ProcessResult) -> None:
        if result.final_state == "cleanup_failed":
            await self._registry.mark_state(
                managed_id=result.managed_id,
                from_states=(
                    "starting",
                    "running",
                    "terminating",
                    "orphaned",
                    "cleanup_failed",
                ),
                to_status="cleanup_failed",
                last_error_code=result.reason_code,
                run_id=result.run_id,
            )
            return
        await self._registry.mark_state(
            managed_id=result.managed_id,
            from_states=("starting", "running", "terminating", "orphaned"),
            to_status="exited",
            exit_code=result.exit_code,
            term_signal=result.term_signal,
            last_error_code=(
                None if result.reason_code == "runtime_host_exited" else result.reason_code
            ),
            run_id=result.run_id,
        )

    async def _decide(self, row: ProcessRecordRow) -> str:
        """Apply the decision table with the injected probe; returns a kind."""
        managed = row.managed
        if managed.process_group_id is None or managed.os_pid is None:
            await self._registry.mark_state(
                managed_id=managed.managed_id,
                from_states=("starting", "running"),
                to_status="exited",
                last_error_code=REASON_SPAWN_FAILED,
                metadata_merge={"recovery": "no-os-identity"},
            )
            return "absent"
        alive = await asyncio.to_thread(group_alive, managed.process_group_id)
        probed_token = await self._identity_probe(managed.os_pid) if alive else None
        decision = orphan_decision(
            stored_token=managed.start_token,
            probed_token=probed_token,
            alive=alive,
        )
        if decision.decision == "terminate":
            await self._registry.mark_state(
                managed_id=managed.managed_id,
                from_states=(
                    "starting",
                    "running",
                    "terminating",
                    "orphaned",
                    "cleanup_failed",
                ),
                to_status="orphaned",
                cancel_requested=True,
            )
            return "terminate"
        if decision.decision == "no_signal":
            await self._registry.mark_state(
                managed_id=managed.managed_id,
                from_states=(
                    "starting",
                    "running",
                    "terminating",
                    "orphaned",
                    "cleanup_failed",
                ),
                to_status="cleanup_failed",
                last_error_code=decision.reason_code or REASON_IDENTITY_MISMATCH,
                metadata_merge={"recovery": "identity-unverified"},
                run_id=managed.run_id,
            )
            logger.error(
                "runtime host identity mismatch managed_id=%s: manual remediation required",
                managed.managed_id,
            )
            self._alert(
                EVENT_MANUAL_REMEDIATION,
                "error",
                decision.reason_code or REASON_IDENTITY_MISMATCH,
                run_id=managed.run_id,
                managed_id=managed.managed_id,
            )
            return "manual"
        if managed.state == "cleanup_failed":
            # Gone but the failure record stays alertable until manual close.
            return "manual"
        await self._registry.mark_state(
            managed_id=managed.managed_id,
            from_states=("starting", "running", "terminating", "orphaned"),
            to_status="exited",
            metadata_merge={"recovery": "group-absent"},
        )
        return "absent"

    async def _terminate_row(self, row: ProcessRecordRow) -> None:
        result = await self._supervisor.terminate_orphan(GroupHandle(row.managed))
        if result.final_state == "cleanup_failed":
            await self._registry.mark_state(
                managed_id=row.managed_id,
                from_states=("orphaned", "terminating", "cleanup_failed"),
                to_status="cleanup_failed",
                last_error_code=REASON_CLEANUP_FAILED,
                run_id=row.managed.run_id,
            )
            return
        await self._registry.mark_state(
            managed_id=row.managed_id,
            from_states=("orphaned", "terminating"),
            to_status="exited",
            exit_code=result.exit_code,
            term_signal=result.term_signal,
            metadata_merge={"recovery": "terminated"},
        )

    # ------------------------------------------------------------------
    # T15 observability helpers (02 FR-9)
    # ------------------------------------------------------------------

    @staticmethod
    def _stable_code(value: object) -> str:
        """Map any failure string onto the frozen low-cardinality vocabularies.

        Unknown shapes collapse to ``runtime_host_spawn_failed`` so a stray
        exception text can never become a metric label or alert code (C7,
        P4-UT-22 no-high-cardinality guarantee).
        """
        if isinstance(value, str) and (
            value in HOST_REASON_CODES or _WORKDIR_CODE_RE.fullmatch(value)
        ):
            return value
        return REASON_SPAWN_FAILED

    def _record_start_failure(self, code: str) -> None:
        stable = self._stable_code(code)
        self._start_failures[stable] = self._start_failures.get(stable, 0) + 1

    def _observe_result(self, result: ProcessResult) -> None:
        """One exit fact per terminal result: counter plus info record."""
        stable = self._stable_code(result.reason_code)
        self._exit_reasons[stable] = self._exit_reasons.get(stable, 0) + 1
        fields: dict[str, str | int | float] = {"final_state": result.final_state}
        if result.exit_code is not None:
            fields["exit_code"] = result.exit_code
        if result.term_signal is not None:
            fields["term_signal"] = result.term_signal
        self._alert(
            EVENT_PROCESS_EXITED,
            "info" if result.final_state != "cleanup_failed" else "error",
            stable,
            run_id=result.run_id,
            managed_id=result.managed_id,
            fields=fields,
        )

    def _alert(
        self,
        event: str,
        severity: str,
        code: str | None,
        *,
        run_id: UUID | None = None,
        managed_id: UUID | None = None,
        fields: dict[str, str | int | float] | None = None,
    ) -> None:
        if self._alert_sink is None:
            return
        self._alert_sink.emit(
            ObservabilityRecord(
                event=event,
                severity=severity,  # type: ignore[arg-type]
                code=self._stable_code(code) if code is not None else None,
                host_id=self._host_id,
                run_id=run_id,
                managed_id=managed_id,
                fields=fields or {},
            )
        )
