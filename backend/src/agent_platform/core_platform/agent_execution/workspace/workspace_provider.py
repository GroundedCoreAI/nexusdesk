"""Execution Workdir provider contract (Phase 4, 08 T6, 02 FR-5).

The type-level gate is the point: every entry takes trusted platform ids
only - Run/Workdir UUIDs and tenant/business/workspace strings - and no
method accepts a path, so a client-controlled location is unrepresentable at
this interface (AC-7). Implementations must persist the state machine below
and make every cleanup idempotent (03 §4.5, §5.1).
"""

from typing import Annotated, Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import Field, StringConstraints

from agent_platform.core_platform.agent_execution.contracts.base import ExecutionContractModel

WorkdirStatus = Literal[
    "preparing", "ready", "active", "retained", "cleaning", "deleted", "cleanup_failed"
]

# Mirrors the execution_workdirs.status CHECK exactly (03 §3.2). Rules:
# forward-only through the lifecycle; ``deleted`` is the terminal Tombstone;
# ``cleanup_failed`` is honest (never folded into deleted) yet retryable into
# ``cleaning`` (03 §4.3 "cleanup_failed is not exited").
WORKDIR_STATE_TRANSITIONS: dict[WorkdirStatus, frozenset[WorkdirStatus]] = {
    "preparing": frozenset({"ready", "cleaning", "cleanup_failed"}),
    "ready": frozenset({"active", "retained", "cleaning", "cleanup_failed"}),
    "active": frozenset({"retained", "cleaning", "cleanup_failed"}),
    "retained": frozenset({"cleaning", "cleanup_failed"}),
    # cleaning -> cleaning re-entry is the crash-retry path: a Host restart
    # can find an interrupted cleaning row and must converge, not loop.
    "cleaning": frozenset({"deleted", "cleanup_failed", "cleaning"}),
    "cleanup_failed": frozenset({"cleaning"}),
    "deleted": frozenset(),
}

TERMINAL_WORKDIR_STATES: frozenset[WorkdirStatus] = frozenset({"deleted"})

# Stable last_error_code values (03 §3.2: no raw paths, no exception text).
# These strings are kept equal to the ``workdir_*`` constants in
# execution_workdir.py by a pin test; ``workdir_state_invalid`` and
# ``workdir_persistence_conflict`` are manager-level codes.
WorkdirErrorCode = Literal[
    "workdir_root_invalid",
    "workdir_path_rejected",
    "workdir_link_denied",
    "workdir_hardlink_denied",
    "workdir_mount_denied",
    "workdir_owner_mismatch",
    "workdir_race",
    "workdir_unsupported_object",
    "workdir_scope_mismatch",
    "workdir_state_invalid",
    "workdir_persistence_conflict",
    "workdir_fs_failed",
]

RetainOutcome = Literal["success", "failed"]

# Length bound matches the ExecutionRequest.execution_workdir contract column;
# the path grammar itself is owned by workspace_policy (single authority).
RelativeWorkdirPath = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class WorkdirRecord(ExecutionContractModel):
    """Durable snapshot of one ``execution_workdirs`` row (internal DTO)."""

    workdir_id: UUID
    run_id: UUID
    tenant_id: str = Field(min_length=1, max_length=200)
    business_id: str = Field(min_length=1, max_length=200)
    workspace_id: str = Field(min_length=1, max_length=200)
    relative_path: RelativeWorkdirPath
    status: WorkdirStatus
    quota_bytes: int = Field(gt=0)
    size_bytes: int = Field(ge=0)
    file_count: int = Field(ge=0)
    expires_at_posix: float | None = Field(default=None, ge=0)
    last_error_code: WorkdirErrorCode | None = None
    created_at_posix: float = Field(ge=0)


class WorkdirStats(ExecutionContractModel):
    """Aggregated live Workdir footprint for FR-9 health (08 T15).

    Internal DTO like every other workspace type: joined into ``HostHealth``
    only, never serialized into events or Run metadata.
    """

    live_bytes: int = Field(ge=0)
    retained_count: int = Field(ge=0)
    cleanup_failed_count: int = Field(ge=0)
    oldest_retention_age_seconds: float | None = Field(default=None, ge=0)


@runtime_checkable
class WorkspaceProvider(Protocol):
    """Prepare/activate/retain/cleanup contract for Execution Workdirs.

    Every method is idempotent per Run: a repeated call for an already
    transitioned record returns the current record rather than re-running the
    effect, and failure paths must leave the durable record retryable
    (02 FR-5 failure row - cleanup failure never pretends success and never
    repoints the path).
    """

    async def prepare(
        self,
        *,
        run_id: UUID,
        tenant_id: str,
        business_id: str,
        workspace_id: str,
    ) -> WorkdirRecord:
        """Generate the platform path, persist ``preparing``, build the tree, ``ready``.

        R-11 ready-or-refuse with self-convergence: the call never returns a
        ``preparing`` record and never blocks - a conflicted slow/crashed
        winner is converged by the late caller itself (rerun of the
        idempotent build plus the guarded conditional update), and anything
        that cannot reach ``ready``/``active`` raises a stable error so the
        start is prevented (FR-5 failure row).
        """
        ...

    async def activate(self, *, workdir_id: UUID, run_id: UUID, tenant_id: str) -> WorkdirRecord:
        """``ready`` -> ``active`` immediately before a process/adapter starts."""
        ...

    async def retain(
        self,
        *,
        workdir_id: UUID,
        run_id: UUID,
        tenant_id: str,
        outcome: RetainOutcome,
    ) -> WorkdirRecord:
        """Terminal decision bookkeeping: ``active`` -> ``retained`` with the outcome window."""
        ...

    async def cleanup(self, *, workdir_id: UUID, run_id: UUID, tenant_id: str) -> WorkdirRecord:
        """Idempotent safe removal: ``retained``/``cleanup_failed`` -> ``deleted``.

        On an unprovable removal scope the record enters ``cleanup_failed``
        with the stable code and stays alertable/retryable; the recorded
        relative path is never rewritten.
        """
        ...

    async def get(self, *, run_id: UUID, tenant_id: str) -> WorkdirRecord | None:
        """Current durable state for a Run, for restart recovery and barriers."""
        ...
