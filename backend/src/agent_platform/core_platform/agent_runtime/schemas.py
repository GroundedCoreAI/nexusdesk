from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
TERMINAL = frozenset({"completed", "failed", "cancelled"})


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    conversation_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)


class RunView(BaseModel):
    id: UUID
    conversation_id: UUID
    status: RunStatus
    cancel_requested: bool
    output: str | None
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class ExecutionSnapshotPayloads:
    """Serialized Phase 3 startup snapshots, one canonical JSON per column.

    Internal-only private DTO: the five payloads are written to dedicated
    ``runtime_runs`` columns and must never be attached to ``RunView`` or any
    public response, event, or log line. ``execution_id`` is the startup
    identity carried inside every snapshot payload (R-9); it is duplicated
    here only as the write-once guard parameter, not as a sixth column.

    The repository does not trust that parameter blindly: ``write_execution_
    snapshots`` re-checks it against the run id and against the ``execution_id``
    each payload actually carries, so a caller cannot point a row at another
    run's identity (R-9).
    """

    execution_id: UUID
    execution_config_snapshot: str
    declared_capabilities_snapshot: str
    available_capabilities_snapshot: str
    effective_capabilities_snapshot: str
    execution_policy_snapshot: str


SnapshotWriteOutcome = Literal[
    "written",
    "reused",
    "audit_conflict",
    "not_claimed",
    "lease_lost",
]

# The closed vocabulary above, exposed so tests and callers can validate a
# mapping table against it instead of hard-coding a drifting copy.
SNAPSHOT_WRITE_OUTCOMES: frozenset[str] = frozenset(
    ("written", "reused", "audit_conflict", "not_claimed", "lease_lost")
)

# Outcomes that mean "the row now carries exactly these startup snapshots".
_SNAPSHOT_SUCCESS_OUTCOMES: frozenset[str] = frozenset({"written", "reused"})


@dataclass(frozen=True, slots=True)
class SnapshotWriteResult:
    """Categorical result of the write-once snapshot barrier.

    A controlled outcome literal and nothing else: the object deliberately
    carries no payload text, no field path, and no stored value, so it can be
    logged and surfaced by the worker without ever echoing snapshot content.

    Mapping for the caller (T7 orchestration):

    * ``written`` / ``reused`` -> the barrier is satisfied; ``Adapter.start``
      may proceed. ``reused`` is the retry-after-success path and must not
      rewrite anything (R-9).
    * ``audit_conflict`` -> the row (or the supplied payloads) disagrees with
      this startup identity or with the stored decisions. Fail the run closed
      with a configuration/audit error and keep ``Adapter.start`` at zero.
    * ``not_claimed`` / ``lease_lost`` -> the row was not a live, owned,
      lease-valid claim at statement time. These are the existing
      lost-lease/cancellation conditions: follow the current lease-loss path
      and never report them as a configuration error.
    """

    outcome: SnapshotWriteOutcome

    def __post_init__(self) -> None:
        # The vocabulary above is closed, not decorative: a typo must fail at
        # construction instead of spreading as a sixth category through logs
        # and the caller's mapping table. The rejection message never echoes
        # the rejected value, keeping this type's content-free guarantee even
        # on the error path.
        if self.outcome not in SNAPSHOT_WRITE_OUTCOMES:
            raise ValueError("snapshot write outcome is outside the controlled vocabulary")

    @property
    def succeeded(self) -> bool:
        """True only for ``written``/``reused`` (the barrier is satisfied)."""

        return self.outcome in _SNAPSHOT_SUCCESS_OUTCOMES

    def __str__(self) -> str:
        # Keep the representation content-free even if it reaches a log line.
        return self.outcome


class RuntimeFault(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class BusyError(Exception):
    pass


class CapacityError(Exception):
    pass
