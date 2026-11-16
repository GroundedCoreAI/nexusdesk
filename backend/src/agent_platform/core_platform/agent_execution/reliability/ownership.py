"""Internal execution ownership evidence and Fencing denial audit (T-01/T-03).

The value objects here are deliberately private: a Fencing Token is database
evidence bound to one claim, never a client DTO, AgentConfig field, or public
event. ``(run_id, owner, lease_epoch)`` is the one tuple every Worker/Host/
Workspace/Repository write must assert, and ``FencingDenial`` is a bounded,
payload-free record written in a *separate* transaction after a stale
business transaction rolled back (08 R-14, 03 §6.1).
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

OwnershipOperation = Literal[
    "snapshot",
    "append",
    "finish",
    "heartbeat",
    "usage",
    "tool_replay",
    "process",
    "workdir",
    "resource_release",
]
OWNERSHIP_OPERATIONS: frozenset[str] = frozenset(
    {
        "snapshot",
        "append",
        "finish",
        "heartbeat",
        "usage",
        "tool_replay",
        "process",
        "workdir",
        "resource_release",
    }
)

DenialReason = Literal[
    "owner_mismatch",
    "stale_epoch",
    "lease_lost",
    "run_terminal",
    "run_missing",
]
FENCING_DENIAL_REASONS: frozenset[str] = frozenset(
    {"owner_mismatch", "stale_epoch", "lease_lost", "run_terminal", "run_missing"}
)


def _is_uuid(value: object) -> bool:
    return isinstance(value, UUID) and (
        type(value) is UUID or any(base is UUID for base in type(value).__mro__)
    )


def _optional_uuid(value: object) -> bool:
    return value is None or _is_uuid(value)


def _optional_epoch(value: object) -> bool:
    return value is None or (type(value) is int and value >= 0)


@dataclass(frozen=True, slots=True)
class ExecutionOwnership:
    """One claim's database-owned Fencing evidence.

    ``lease_epoch`` starts at 1 on the first claim and only the database
    increments it on every new claim/takeover. Construction validates the whole
    tuple so a malformed row can never become authorization.
    """

    run_id: UUID
    owner: UUID
    lease_epoch: int

    def __post_init__(self) -> None:
        if not _is_uuid(self.run_id) or not _is_uuid(self.owner):
            raise ValueError("execution ownership requires run and owner UUIDs")
        if type(self.lease_epoch) is not int or self.lease_epoch < 1:
            raise ValueError("execution ownership requires a positive integer lease epoch")

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> "ExecutionOwnership | None":
        """Project a claimed-row mapping, returning None for the legacy shape.

        A row written before 0068 (or an explicit no-snapshot test double) has no
        complete tuple. Returning None keeps the pre-migration path readable
        while production always carries the tuple after the new claim.
        """
        run_id = row.get("id")
        owner = row.get("owner")
        epoch = row.get("lease_epoch")
        if not _is_uuid(run_id) or not _is_uuid(owner) or type(epoch) is not int:
            return None
        if epoch < 1:
            return None
        return cls(run_id=run_id, owner=owner, lease_epoch=epoch)


@dataclass(frozen=True, slots=True)
class FencingDenial:
    """One bounded stale-write record; never carries business payload text."""

    run_id: UUID
    operation: OwnershipOperation
    reason: DenialReason
    stale_owner: UUID | None = None
    stale_lease_epoch: int | None = None
    current_owner: UUID | None = None
    current_lease_epoch: int | None = None

    def __post_init__(self) -> None:
        if not _is_uuid(self.run_id):
            raise ValueError("fencing denial requires a run UUID")
        if self.operation not in OWNERSHIP_OPERATIONS:
            raise ValueError("fencing denial operation is outside the closed vocabulary")
        if self.reason not in FENCING_DENIAL_REASONS:
            raise ValueError("fencing denial reason is outside the closed vocabulary")
        if not _optional_uuid(self.stale_owner) or not _optional_uuid(self.current_owner):
            raise ValueError("fencing denial owners must be UUIDs or None")
        if not _optional_epoch(self.stale_lease_epoch) or not _optional_epoch(
            self.current_lease_epoch
        ):
            raise ValueError("fencing denial epochs must be nonnegative integers or None")


class FencingDenialRecorder:
    """Write one denial in its own transaction (08 R-14).

    A stale conditional write must roll back its business transaction, so an
    audit row inserted beside the denied write would disappear with it. This
    helper opens a fresh transaction after the caller's rollback. Audit failure
    is logged and never turns a denied write into an allowed one.
    """

    def __init__(self, engine) -> None:
        self._engine = engine

    async def record(self, denial: FencingDenial) -> bool:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    text(
                        """INSERT INTO execution_fencing_denials
                        (run_id, operation, reason, stale_owner, stale_lease_epoch,
                         current_owner, current_lease_epoch)
                        VALUES (:run_id, :operation, :reason, :stale_owner,
                        :stale_lease_epoch, :current_owner, :current_lease_epoch)"""
                    ),
                    {
                        "run_id": denial.run_id,
                        "operation": denial.operation,
                        "reason": denial.reason,
                        "stale_owner": denial.stale_owner,
                        "stale_lease_epoch": denial.stale_lease_epoch,
                        "current_owner": denial.current_owner,
                        "current_lease_epoch": denial.current_lease_epoch,
                    },
                )
        except (SQLAlchemyError, OSError, TimeoutError):
            # The business decision was already made by SQL rowcount; a missing
            # audit table or outage only loses the record, never the denial.
            logger.warning("fencing denial audit unavailable operation=%s", denial.operation)
            return False
        return True
