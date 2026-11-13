"""Internal Runtime Host DTOs (Phase 4, 02 FR-1, 03 §2/§4).

These models are platform-internal: they never join the public contracts
surface (``contracts/__init__.py``), never serialize into AgentEvents, OpenAPI
schemas or Run metadata, and carry OS identity (PID/PGID/start token), relative
Workdir paths and minimal environments only between the Host, Runner,
Supervisor and Registry (03 §4.1, 08 R-4). A pin test in the Phase 4 runner
suite keeps them out of the public module.

State names mirror the ``runtime_host_processes.status`` CHECK constraint
exactly (03 §3.2) so Registry persistence and the in-memory handle cannot
drift apart.
"""

import hashlib
import json
from collections.abc import Sequence
from typing import Annotated, Literal, NamedTuple
from uuid import UUID

from pydantic import Field, StringConstraints

from agent_platform.core_platform.agent_execution.contracts.base import ExecutionContractModel

# ---------------------------------------------------------------------------
# Stable reason codes (02 FR-9)
#
# Low-cardinality, path-free, PID-free and secret-free identifiers for start,
# cancel, cleanup and recovery failures. Names are frozen for metrics and
# ``last_error_code`` columns; never interpolate raw exceptions or OS paths.
# ---------------------------------------------------------------------------

REASON_UNTRUSTED_TARGET = "runtime_host_untrusted_target"
REASON_SPAWN_FAILED = "runtime_host_spawn_failed"
REASON_PIPE_SETUP_FAILED = "runtime_host_pipe_setup_failed"
REASON_OUTPUT_LIMIT_EXCEEDED = "runtime_host_output_limit_exceeded"
REASON_RESOURCE_EXCEEDED = "runtime_host_resource_exceeded"
REASON_WALL_TIMEOUT = "runtime_host_wall_timeout"
REASON_CANCELLED = "runtime_host_cancelled"
REASON_IDENTITY_MISMATCH = "runtime_host_identity_mismatch"
REASON_MANUAL_REMEDIATION = "runtime_host_manual_remediation"
REASON_CLEANUP_FAILED = "runtime_host_cleanup_failed"
REASON_CLEANUP_RACE = "runtime_host_cleanup_race"
REASON_SUPPORT_UNSUPPORTED = "runtime_host_support_unsupported"
REASON_WORKDIR_UNAVAILABLE = "runtime_host_workdir_unavailable"
REASON_EXITED = "runtime_host_exited"
REASON_ADMISSION_CLOSED = "runtime_host_admission_closed"
REASON_RECOVERY_TERMINATED = "runtime_host_recovery_terminated"

HostReasonCode = Literal[
    "runtime_host_untrusted_target",
    "runtime_host_spawn_failed",
    "runtime_host_pipe_setup_failed",
    "runtime_host_output_limit_exceeded",
    "runtime_host_resource_exceeded",
    "runtime_host_wall_timeout",
    "runtime_host_cancelled",
    "runtime_host_identity_mismatch",
    "runtime_host_manual_remediation",
    "runtime_host_cleanup_failed",
    "runtime_host_cleanup_race",
    "runtime_host_support_unsupported",
    "runtime_host_workdir_unavailable",
    "runtime_host_exited",
    "runtime_host_admission_closed",
    "runtime_host_recovery_terminated",
]

HOST_REASON_CODES: frozenset[str] = frozenset(
    {
        REASON_UNTRUSTED_TARGET,
        REASON_SPAWN_FAILED,
        REASON_PIPE_SETUP_FAILED,
        REASON_OUTPUT_LIMIT_EXCEEDED,
        REASON_RESOURCE_EXCEEDED,
        REASON_WALL_TIMEOUT,
        REASON_CANCELLED,
        REASON_IDENTITY_MISMATCH,
        REASON_MANUAL_REMEDIATION,
        REASON_CLEANUP_FAILED,
        REASON_CLEANUP_RACE,
        REASON_SUPPORT_UNSUPPORTED,
        REASON_WORKDIR_UNAVAILABLE,
        REASON_EXITED,
        REASON_ADMISSION_CLOSED,
        REASON_RECOVERY_TERMINATED,
    }
)

# ---------------------------------------------------------------------------
# Process state machine (mirrors runtime_host_processes.status, 03 §3.2/§4.3)
# ---------------------------------------------------------------------------

ProcessState = Literal["starting", "running", "terminating", "exited", "orphaned", "cleanup_failed"]

# Monotone rules: ``exited`` and ``cleanup_failed`` are terminal; a record never
# returns from them, and ``cleanup_failed`` is never reported as ``exited``
# (03 §4.3). Recovery observes orphans, escalates them through the same
# TERM/KILL machine, and can only finish at exited or cleanup_failed (03 §4.4).
PROCESS_STATE_TRANSITIONS: dict[ProcessState, frozenset[ProcessState]] = {
    "starting": frozenset({"running", "terminating", "exited", "orphaned", "cleanup_failed"}),
    "running": frozenset({"terminating", "exited", "orphaned", "cleanup_failed"}),
    "terminating": frozenset({"exited", "orphaned", "cleanup_failed"}),
    "orphaned": frozenset({"terminating", "exited", "cleanup_failed"}),
    "exited": frozenset(),
    "cleanup_failed": frozenset(),
}

TERMINAL_PROCESS_STATES: frozenset[ProcessState] = frozenset({"exited", "cleanup_failed"})


class ProcessStateTransitionError(ValueError):
    """Raised when a ManagedProcess transition violates the monotone machine."""


def compute_command_digest(executable_id: str, argv: Sequence[str]) -> str:
    """SHA-256 digest of the normalized executable id and argv (08 R-6).

    The single source for the ``command_digest`` column and the recovery
    verification chain (T7/T9): it is deterministic across processes and
    platforms, contains no environment values, and an unregistered or replaced
    command can be detected from the digest alone.
    """
    payload = json.dumps(
        {"executable_id": executable_id, "argv": list(argv)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Internal identifier grammars reuse the public slug/executable shapes inlined
# here so this module never widens the public contract surface (02 FR-1).
TrustedExecutableId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$"),
]
ArgvValue = Annotated[str, StringConstraints(max_length=4096)]
EnvironmentKey = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
]
EnvironmentValue = Annotated[str, StringConstraints(max_length=8192)]
HostIdentity = Annotated[
    str, StringConstraints(min_length=1, max_length=200, pattern=r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
]
CommandDigest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
# Length-only bound here; the path acceptance rules themselves belong to
# workspace/workspace_policy.py (T5), the single validation authority (FR-6).
RelativeWorkdirPath = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class ResourcePolicy(ExecutionContractModel):
    """Per-Execution resource ceilings resolved from the FR-10 settings.

    Values are strictly positive by construction: 0 or negative limits are
    rejected before admission (03 §5.1). Which ceilings are hard versus
    approximate is the Sandbox support matrix's decision (T11/T12), never this
    DTO's.
    """

    cpu_seconds: int = Field(gt=0, le=86_400)
    memory_bytes: int = Field(gt=0, le=68_719_476_736)
    max_processes: int = Field(gt=0, le=4096)
    workdir_total_bytes: int = Field(gt=0, le=1_099_511_627_776)
    workdir_file_bytes: int = Field(gt=0, le=1_099_511_627_776)
    wall_seconds: int = Field(gt=0, le=86_400)
    output_max_bytes_per_stream: int = Field(gt=0, le=268_435_456)


class ProcessSpec(ExecutionContractModel):
    """Server-built start description for one trusted engine process (FR-1/FR-2).

    Only allowlisted executable ids are admitted and the Host validates the
    registry membership before spawn (T7/T10); the argv list is fixed by the
    platform, never a client command line. ``environment`` is minimal and stays
    internal: it is never persisted to DB rows nor logged (FR-2, FR-9).
    """

    executable_id: TrustedExecutableId
    argv: tuple[ArgvValue, ...] = ()
    environment: dict[EnvironmentKey, EnvironmentValue] = Field(default_factory=dict)
    workdir_relative_path: RelativeWorkdirPath
    resource_policy: ResourcePolicy

    @property
    def command_digest(self) -> str:
        """Digest of the normalized executable id and argv (single source R-6)."""
        return compute_command_digest(self.executable_id, self.argv)


class ManagedProcess(ExecutionContractModel):
    """Internal handle to one supervised process group (03 §4.1).

    The OS identity (``os_pid``/``process_group_id``/``start_token``) lives
    only here: the Adapter-facing ``ExecutionHandle.process_id`` stays unset
    for Host-managed executions (08 R-4). ``*_posix`` timestamps come from the
    injected POSIX clock source (Phase 3 R-49 precedent); deadline comparisons
    elsewhere use monotonic time, not these.
    """

    managed_id: UUID
    run_id: UUID
    host_id: HostIdentity
    host_instance_id: HostIdentity
    sandbox_provider: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    state: ProcessState = "starting"
    os_pid: int | None = Field(default=None, gt=0, le=4_194_304)
    process_group_id: int | None = Field(default=None, gt=0, le=4_194_304)
    start_token: Annotated[str, StringConstraints(max_length=512)] | None = None
    command_digest: CommandDigest
    workdir_relative_path: RelativeWorkdirPath | None = None
    started_at_posix: float | None = Field(default=None, ge=0)
    cancel_requested_at_posix: float | None = Field(default=None, ge=0)
    last_observed_at_posix: float | None = Field(default=None, ge=0)

    def transition_to(self, state: ProcessState) -> "ManagedProcess":
        """Return the handle in ``state``; illegal moves raise, terminals are frozen."""
        if state not in PROCESS_STATE_TRANSITIONS[self.state]:
            raise ProcessStateTransitionError(f"{self.state} -> {state} is not allowed")
        return self.model_copy(update={"state": state})


class ExitObservation(NamedTuple):
    """One bounded wait for process termination.

    ``exited`` carries the reaped exit code (own children only); ``absent``
    is the honest recovery-side observation that the process group vanished
    without a reapable status; ``alive`` means the window elapsed with the
    group still running, so escalation decides the next signal.
    """

    status: Literal["exited", "alive", "absent"]
    exit_code: int | None = None


class ProcessResult(ExecutionContractModel):
    """Structured outcome of one supervised process (FR-1 output row).

    Internal only: the Run-facing result and terminal state stay on the
    existing Orchestrator/Repository path; this DTO feeds Host-side audit,
    metrics and ``exit_code`` persistence.
    """

    managed_id: UUID
    run_id: UUID
    final_state: Literal["exited", "cleanup_failed"]
    reason_code: HostReasonCode
    exit_code: int | None = None
    term_signal: int | None = Field(default=None, ge=1, le=64)
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    wall_seconds: float = Field(ge=0)
    # Bounded protocol payload for the Adapter's parser: already capped by
    # the per-stream limit, never logged, and never part of a public event.
    stdout: bytes = b""
    stderr: bytes = b""


class HostHealth(ExecutionContractModel):
    """Aggregated Host health snapshot (02 FR-9, 03 §4.1 health row).

    Counts are per state with low-cardinality labels only; the support-matrix
    rows join this snapshot in T11/T12. ``last_reconcile_age_seconds`` feeds
    the stalled-reconcile alert (P4-UT-22).
    """

    host_id: HostIdentity
    host_instance_id: HostIdentity
    sandbox_provider: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    admission_enabled: bool
    resource_enforcement_required: bool
    starting_count: int = Field(default=0, ge=0)
    running_count: int = Field(default=0, ge=0)
    terminating_count: int = Field(default=0, ge=0)
    orphaned_count: int = Field(default=0, ge=0)
    cleanup_failed_count: int = Field(default=0, ge=0)
    workdir_cleanup_failed_count: int = Field(default=0, ge=0)
    last_reconcile_age_seconds: float | None = Field(default=None, ge=0)

    @property
    def active_count(self) -> int:
        """Processes not yet at a terminal state (03 §5.1 drain condition)."""
        return (
            self.starting_count + self.running_count + self.terminating_count + self.orphaned_count
        )
