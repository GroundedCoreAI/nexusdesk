"""Resource Manager: declared application, sampling and release (08 T12).

Applies the per-Execution ResourcePolicy through the mechanisms the Sandbox
Provider declared (never its own opinion), samples usage for the reactive
path, classifies excess into stable reason codes, and releases idempotently
(P4-UT-16). Honesty rules mirror 03 §4.6 and 08 R-3:

- RLIMIT_CPU / RLIMIT_AS / RLIMIT_FSIZE are applied child-side through the
  runner preexec seam and are labeled approximate: per-process, not group
  hard ceilings.
- Supervisor-side descendant counting and RSS sampling come from a bounded
  ``ps`` observation of the process group: reactive, not isolation; the
  host-wide NPROC substitution is never used.
- cgroup v2 per-Execution memory/PID hard limits and filesystem quotas
  report unsupported here; the Linux branches exist in the probes and their
  live experiments stay pending_env (skip-with-attribution in tests).
- Workdir total/per-file disk control composes the workspace accounting
  hooks (08 R-12 persistence semantics live in the Workspace manager; this
  module supplies the excess decision and reason code).

Nothing sampled or logged carries paths, environment values, or secrets:
samples are aggregate numbers plus stable codes.
"""

import asyncio
import logging
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .host_models import REASON_EXITED, REASON_RESOURCE_EXCEEDED, ProcessResult, ResourcePolicy
from .sandbox_provider import SandboxReservation

logger = logging.getLogger(__name__)

# Signals whose default disposition is the kernel enforcing an applied rlimit.
_RLIMIT_SIGNALS = {24, 25}  # SIGXCPU, SIGXFSZ

# Trusted-target normalized excess contract: hosts differ in whether
# RLIMIT_FSIZE kills with SIGXFSZ or the write fails with EFBIG first, so the
# repository-fixed target converts either into exit code 86 with a stable
# stderr marker; classifying it keeps the excess honest on both behaviours.
TARGET_EXIT_RESOURCE_EXCEEDED = 86


@dataclass(frozen=True)
class UsageSample:
    """Aggregate observed usage for one sample; no per-path detail."""

    process_count: int
    rss_bytes: int
    cpu_seconds: float
    workdir_bytes: int | None
    workdir_files: int | None
    observed_at_posix: float


@dataclass(frozen=True)
class ResourceExcess:
    dimension: str  # cpu | memory | pid | disk | wall | output
    reason_code: str
    mechanism: str
    strength: str


class GroupObserver(Protocol):
    """Injectable observation port so tests substitute and Linux paths stay honest."""

    def __call__(self, pgid: int) -> tuple[int, int, float]:
        """Return (process_count, rss_bytes, cpu_seconds_total) for the group."""
        ...


def default_group_observer(pgid: int) -> tuple[int, int, float]:
    """Bounded ``ps`` sampling of one process group (darwin-measurable half).

    Aggregates group members' resident size and CPU time; a probe failure
    yields an empty observation, which the caller must treat as "no data",
    never as "zero usage".
    """
    try:
        completed = subprocess.run(  # fixed argv, numeric pgid only
            ["ps", "-o", "pid=,rss=,time=", "-g", str(int(pgid))],
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return 0, 0, 0.0
    if completed.returncode != 0:
        return 0, 0, 0.0
    count = 0
    rss_total = 0
    cpu_total = 0.0
    for line in completed.stdout.decode("utf-8", "ignore").splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        try:
            rss_total += int(fields[1]) * 1024  # ps rss is KB
        except ValueError:
            continue
        cpu_total += _parse_cpu_time(fields[2])
        count += 1
    return count, rss_total, cpu_total


def _parse_cpu_time(text: str) -> float:
    """Parse ps time= values: [DD-]HH:MM:SS, MM:SS or bare seconds."""
    body = text.strip()
    days = 0.0
    if "-" in body:
        day_part, _, body = body.partition("-")
        try:
            days = float(day_part) * 86_400
        except ValueError:
            return 0.0
    try:
        parts = [float(value) for value in body.split(":")]
    except ValueError:
        return 0.0
    seconds = 0.0
    for value in parts:
        seconds = seconds * 60 + value
    return seconds + days


WorkdirAccountant = Callable[[], "WorkdirUsage"]


@dataclass(frozen=True)
class WorkdirUsage:
    total_bytes: int
    file_count: int


class ResourceManager:
    """Declared-mechanism application, sampling loop support, excess codes."""

    def __init__(
        self,
        sandbox,
        *,
        sample_interval_seconds: float,
        group_observer: GroupObserver | None = None,
        clock: Callable[[], float] | None = None,
        monotonic: Callable[[], float] | None = None,
        alert: Callable[[ResourceExcess], None] | None = None,
    ) -> None:
        if sample_interval_seconds <= 0:
            raise ValueError("sample interval must be positive")
        self._sandbox = sandbox
        self._sample_interval = sample_interval_seconds
        self._group_observer = group_observer or default_group_observer
        self._clock = clock or time.time
        self._monotonic = monotonic or time.monotonic
        self._alert = alert
        # One release per reservation id (P4-UT-16): usage release is
        # idempotent and repeat calls are observable no-ops.
        self._released: set[object] = set()

    # ------------------------------------------------------------------
    # Admission / child hooks
    # ------------------------------------------------------------------

    async def admit(self, spec, *, run_id, **untrusted_flags) -> SandboxReservation:
        """Delegate admission so the Host sees one resource voice (support gate)."""
        return await self._sandbox.prepare(spec, run_id=run_id, **untrusted_flags)

    def preexec_for(self, reservation: SandboxReservation) -> Callable[[], None] | None:
        return self._sandbox.preexec_for(reservation)

    # ------------------------------------------------------------------
    # Sampling and excess decisions
    # ------------------------------------------------------------------

    async def observe(
        self,
        pgid: int,
        *,
        workdir_accountant: WorkdirAccountant | None = None,
    ) -> UsageSample:
        """One aggregate sample; workdir accounting is supplied by the caller."""
        count, rss, cpu = await asyncio.to_thread(self._group_observer, pgid)
        workdir_bytes: int | None = None
        workdir_files: int | None = None
        if workdir_accountant is not None:
            usage = await asyncio.to_thread(workdir_accountant)
            workdir_bytes, workdir_files = usage.total_bytes, usage.file_count
        return UsageSample(
            process_count=count,
            rss_bytes=rss,
            cpu_seconds=cpu,
            workdir_bytes=workdir_bytes,
            workdir_files=workdir_files,
            observed_at_posix=self._clock(),
        )

    def excess(
        self,
        sample: UsageSample,
        policy: ResourcePolicy,
        reservation: SandboxReservation,
    ) -> ResourceExcess | None:
        """Reactive excess decision for the sampled dimensions.

        Sampling windows never make an approximate mechanism look hard: the
        returned mechanism and strength are exactly what admission declared
        (03 §4.6), and the caller (T13) routes the excess through the
        Supervisor's one termination machine.
        """
        resolved = {r.dimension: r for r in reservation.resolutions}

        def label(dimension: str, fallback: str) -> tuple[str, str]:
            resolution = resolved.get(dimension)
            if resolution is None:
                return fallback, "unenforced"
            return resolution.capability, resolution.strength

        if sample.process_count > policy.max_processes:
            capability, mode = label("pid", "descendant_count")
            # Reactive counting can only bound the observed group, and the
            # observation itself must be non-empty to accuse (no-data reads
            # as zero members, which can never exceed a positive ceiling).
            return ResourceExcess("pid", REASON_RESOURCE_EXCEEDED, f"{capability}:{mode}", mode)
        if sample.workdir_bytes is not None and sample.workdir_bytes > policy.workdir_total_bytes:
            capability, mode = label("disk", "workdir_accounting")
            return ResourceExcess("disk", REASON_RESOURCE_EXCEEDED, f"{capability}:{mode}", mode)
        cpu_capability, cpu_mode = label("cpu", "cpu_rlimit")
        if cpu_mode == "hard" and sample.cpu_seconds > policy.cpu_seconds:
            # Group accounting (Linux pending_env) is the only CPU ceiling the
            # sampler may enforce reactively; the rlimit approximation is the
            # kernel's job (SIGXCPU via classify_result), never a sampling kill.
            return ResourceExcess(
                "cpu", REASON_RESOURCE_EXCEEDED, f"{cpu_capability}:{cpu_mode}", cpu_mode
            )
        return None

    async def watch(
        self,
        pgid: int,
        policy: ResourcePolicy,
        reservation: SandboxReservation,
        *,
        until: asyncio.Future,
        workdir_accountant: WorkdirAccountant | None = None,
    ) -> ResourceExcess | None:
        """Sample loop racing completion: returns the first excess, else None.

        The interval is the FR-10 sample period - a reactive observation
        window, explicitly not an escape-prevention promise (02 FR-10 row).
        """
        while not until.done():
            sample = await self.observe(pgid, workdir_accountant=workdir_accountant)
            decision = self.excess(sample, policy, reservation)
            if decision is not None:
                if self._alert is not None:
                    self._alert(decision)
                logger.warning(
                    "runtime host resource excess dimension=%s mechanism=%s strength=%s",
                    decision.dimension,
                    decision.mechanism,
                    decision.strength,
                )
                return decision
            try:
                await asyncio.wait_for(asyncio.shield(until), timeout=self._sample_interval)
            except TimeoutError:
                continue
            return None

    # ------------------------------------------------------------------
    # Outcome classification and release
    # ------------------------------------------------------------------

    def classify_result(
        self, result: ProcessResult, reservation: SandboxReservation
    ) -> ProcessResult:
        """Relabel kernel-enforced rlimit kills as resource excess.

        SIGXCPU/SIGXFSZ terminations of an admitted Execution are the applied
        approximation doing its job; they leave the exit machine with the
        stable excess code instead of a bare signal death (P4-IT-19/21
        measurable halves). Anything else keeps the Supervisor's reason.
        """
        if (
            result.final_state == "exited"
            and (
                result.term_signal in _RLIMIT_SIGNALS
                or result.exit_code == TARGET_EXIT_RESOURCE_EXCEEDED
            )
            and result.reason_code == REASON_EXITED
        ):
            return result.model_copy(update={"reason_code": REASON_RESOURCE_EXCEEDED})
        return result

    async def release(self, reservation: SandboxReservation) -> None:
        """Idempotent usage release: applied rlimits died with the group."""
        if reservation.reservation_id in self._released:
            return
        self._released.add(reservation.reservation_id)
        await self._sandbox.release(reservation)
