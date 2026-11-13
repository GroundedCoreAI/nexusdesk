"""Durable process registry (Phase 4, 08 T9, 02 FR-4, 03 §4.4).

Raw-SQL repository over ``runtime_host_processes`` in the ``agent_runtime``
style (08 R-9): every move is a conditional UPDATE re-asserting ``host_id`` so
records can never be touched across hosts, and reconcile pulls small batches
with ``SELECT ... FOR UPDATE SKIP LOCKED`` so concurrent recovery passes never
double-process a row. The orphan decision table is a pure function
(``orphan_decision``): any identity mismatch or unavailable identity means
zero signals plus manual remediation (core rule, 03 §4.4). DB failures raise
``RegistryUnavailableError`` for bounded connection retries; there is no code
path that scans host processes on failure (never blind-scan, 02 FR-4).
"""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import time
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from .host_models import (
    HostReasonCode,
    ManagedProcess,
    ProcessState,
)

logger = logging.getLogger(__name__)

_PENDING_STATUSES: tuple[ProcessState, ...] = (
    "starting",
    "running",
    "terminating",
    "orphaned",
    "cleanup_failed",
)

_SELECT_COLUMNS = (
    "SELECT id, run_id, tenant_id, host_id, host_instance_id, sandbox_provider, status,"
    " pid, process_group_id, process_start_token, command_digest, workdir_id,"
    " cancel_requested_at, cleanup_deadline_at, exit_code, last_error_code,"
    " last_observed_at, created_at, updated_at, started_at, exited_at, metadata"
    " FROM runtime_host_processes"
)


class RegistryUnavailableError(RuntimeError):
    """DB outage: retry the connection only - never scan or kill by proxy."""


@dataclass(frozen=True)
class ProcessRecordRow:
    """One durable row: OS identity fields plus scope metadata."""

    managed: ManagedProcess
    host_instance_id: str
    sandbox_provider_label: str
    workdir_id: UUID | None
    metadata: dict

    @property
    def managed_id(self) -> UUID:
        return self.managed.managed_id


@dataclass(frozen=True)
class OrphanDecision:
    decision: str  # "terminate" | "no_signal" | "absent"
    reason_code: HostReasonCode | None = None


def orphan_decision(
    *,
    stored_token: str | None,
    probed_token: str | None,
    alive: bool,
) -> OrphanDecision:
    """The decision table of 03 §4.4 as one pure function (P4-UT-08).

    - group gone: ``absent`` - nothing to signal, record closed honestly;
    - alive and the start token matches exactly: ``terminate`` - the orphan is
      ours, escalate it through the same TERM/KILL machine;
    - alive but the token mismatches, is missing on either side, or cannot be
      parsed: ``no_signal`` - this is PID reuse or unverifiable identity, so
      zero signals plus manual remediation (never a heuristic kill).
    """
    if not alive:
        return OrphanDecision(decision="absent")
    if stored_token is not None and probed_token is not None and stored_token == probed_token:
        return OrphanDecision(decision="terminate")
    return OrphanDecision(decision="no_signal", reason_code="runtime_host_identity_mismatch")


class ProcessRegistry:
    """Persist and reconcile managed process records for one stable host_id."""

    def __init__(
        self,
        engine,
        *,
        host_id: str,
        host_instance_id: str,
        sandbox_provider: str = "local/v1",
        clock=None,
    ) -> None:
        self._engine = engine
        self._host_id = host_id
        self._host_instance_id = host_instance_id
        self._sandbox_provider = sandbox_provider
        self._clock = clock or time

    @property
    def host_instance_id(self) -> str:
        return self._host_instance_id

    @property
    def host_id(self) -> str:
        return self._host_id

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def register_starting(
        self,
        *,
        managed_id: UUID,
        run_id: UUID,
        tenant_id: str,
        command_digest: str,
        workdir_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Persist the ``starting`` record before the spawn attempt (03 §4.2)."""
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO runtime_host_processes"
                        " (id, run_id, workdir_id, tenant_id, host_id, host_instance_id,"
                        " sandbox_provider, status, command_digest, metadata)"
                        " VALUES (:id, :run_id, :workdir_id, :tenant_id, :host_id,"
                        " :host_instance_id, :sandbox_provider, 'starting', :digest,"
                        " CAST(:metadata AS jsonb))"
                    ),
                    {
                        "id": managed_id,
                        "run_id": run_id,
                        "tenant_id": tenant_id,
                        "host_id": self._host_id,
                        "host_instance_id": self._host_instance_id,
                        "sandbox_provider": self._sandbox_provider,
                        "digest": command_digest,
                        "workdir_id": workdir_id,
                        "metadata": json.dumps(metadata or {}),
                    },
                )
        except (DBAPIError, OSError) as exc:
            raise RegistryUnavailableError("register failed") from exc

    async def attach_spawn(self, *, managed: ManagedProcess) -> bool:
        """Fill in pid/pgid/start token/digest once the group exists."""
        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(
                    text(
                        "UPDATE runtime_host_processes"
                        " SET pid=:pid, process_group_id=:pgid,"
                        " process_start_token=:token, command_digest=:digest,"
                        " status='running', started_at=:started_at,"
                        " last_observed_at=now(), updated_at=now()"
                        " WHERE id=:id AND host_id=:host_id AND status='starting'"
                    ),
                    {
                        "pid": managed.os_pid,
                        "pgid": managed.process_group_id,
                        "token": managed.start_token,
                        "digest": managed.command_digest,
                        "started_at": _dt(managed.started_at_posix),
                        "id": managed.managed_id,
                        "host_id": self._host_id,
                    },
                )
                return result.rowcount > 0
        except (DBAPIError, OSError) as exc:
            raise RegistryUnavailableError("attach failed") from exc

    async def mark_state(
        self,
        *,
        managed_id: UUID,
        from_states: Sequence[ProcessState],
        to_status: ProcessState,
        exit_code: int | None = None,
        term_signal: int | None = None,
        last_error_code: str | None = None,
        cancel_requested: bool = False,
        cleanup_deadline_posix: float | None = None,
        metadata_merge: dict | None = None,
    ) -> bool:
        """Conditional state move; ``term_signal`` lands in exit_code as -signal."""
        placeholders = ", ".join(f":fs_{index}" for index in range(len(from_states)))
        params: dict[str, object] = {
            "id": managed_id,
            "host_id": self._host_id,
            "status": to_status,
            "exit_code": exit_code if term_signal is None else -term_signal,
            "last_error_code": last_error_code,
            "cleanup_deadline_at": _dt(cleanup_deadline_posix),
        }
        for index, state in enumerate(from_states):
            params[f"fs_{index}"] = state
        exited_clause = ", exited_at=now()" if to_status == "exited" else ""
        cancel_clause = ", cancel_requested_at=now()" if cancel_requested else ""
        metadata_clause = ""
        if metadata_merge:
            metadata_clause = ", metadata = metadata || CAST(:merge AS jsonb)"
            params["merge"] = json.dumps(metadata_merge)
        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(
                    text(
                        "UPDATE runtime_host_processes"
                        " SET status=:status, updated_at=now(), last_observed_at=now(),"
                        " exit_code=COALESCE(:exit_code, exit_code),"
                        " cleanup_deadline_at=COALESCE(:cleanup_deadline_at,"
                        " cleanup_deadline_at),"
                        " last_error_code=COALESCE(:last_error_code, last_error_code)"
                        f"{exited_clause}{cancel_clause}{metadata_clause}"
                        f" WHERE id=:id AND host_id=:host_id"
                        f" AND status IN ({placeholders})"
                    ),
                    params,
                )
                return result.rowcount > 0
        except (DBAPIError, OSError) as exc:
            raise RegistryUnavailableError("mark failed") from exc

    async def observe(self, managed_id: UUID) -> None:
        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE runtime_host_processes"
                        " SET last_observed_at=now(), updated_at=now()"
                        " WHERE id=:id AND host_id=:host_id"
                    ),
                    {"id": managed_id, "host_id": self._host_id},
                )
        except (DBAPIError, OSError) as exc:
            raise RegistryUnavailableError("observe failed") from exc

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def fetch_pending(
        self,
        *,
        statuses: Sequence[ProcessState] = _PENDING_STATUSES,
        batch_size: int = 16,
        for_update: bool = True,
    ) -> list[ProcessRecordRow]:
        """Bounded recovery batch for this host_id only (03 §4.4 scan limit)."""
        placeholders = ", ".join(f":st_{index}" for index in range(len(statuses)))
        params: dict[str, object] = {"host_id": self._host_id, "batch": batch_size}
        for index, state in enumerate(statuses):
            params[f"st_{index}"] = state
        lock = " FOR UPDATE SKIP LOCKED" if for_update else ""
        try:
            async with self._engine.begin() as conn:
                rows = (
                    await conn.execute(
                        text(
                            _SELECT_COLUMNS
                            + " WHERE host_id=:host_id AND status IN ("
                            + placeholders
                            + ")"
                            + f" ORDER BY last_observed_at ASC LIMIT :batch{lock}"
                        ),
                        params,
                    )
                ).mappings()
                fetched = [self._to_row(row) for row in rows]
                if fetched:
                    ids = [row.managed_id for row in fetched]
                    await conn.execute(
                        text(
                            "UPDATE runtime_host_processes"
                            " SET last_observed_at=now(), updated_at=now()"
                            " WHERE host_id=:host_id AND id = ANY(:ids)"
                        ),
                        {"host_id": self._host_id, "ids": ids},
                    )
                return fetched
        except (DBAPIError, OSError) as exc:
            raise RegistryUnavailableError("fetch failed") from exc

    async def fetch_one(self, managed_id: UUID) -> ProcessRecordRow | None:
        try:
            async with self._engine.begin() as conn:
                row = (
                    await conn.execute(
                        text(_SELECT_COLUMNS + " WHERE id=:id AND host_id=:host_id"),
                        {"id": managed_id, "host_id": self._host_id},
                    )
                ).mappings()
                first = row.first()
        except (DBAPIError, OSError) as exc:
            raise RegistryUnavailableError("fetch failed") from exc
        return None if first is None else self._to_row(first)

    async def count_by_state(self) -> dict[ProcessState, int]:
        try:
            async with self._engine.begin() as conn:
                rows = await conn.execute(
                    text(
                        "SELECT status, count(*) FROM runtime_host_processes"
                        " WHERE host_id=:host_id GROUP BY status"
                    ),
                    {"host_id": self._host_id},
                )
                return {row[0]: row[1] for row in rows}
        except (DBAPIError, OSError) as exc:
            raise RegistryUnavailableError("count failed") from exc

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _to_row(row) -> ProcessRecordRow:
        managed = ManagedProcess(
            managed_id=row["id"],
            run_id=row["run_id"],
            host_id=row["host_id"],
            host_instance_id=row["host_instance_id"],
            sandbox_provider=row["sandbox_provider"],
            state=row["status"],
            os_pid=row["pid"],
            process_group_id=row["process_group_id"],
            start_token=row["process_start_token"],
            command_digest=row["command_digest"],
            workdir_relative_path=None,
            started_at_posix=_posix(row["started_at"]),
            cancel_requested_at_posix=_posix(row["cancel_requested_at"]),
            last_observed_at_posix=_posix(row["last_observed_at"]),
        )
        metadata = row["metadata"] if isinstance(row["metadata"], dict) else {}
        return ProcessRecordRow(
            managed=managed,
            host_instance_id=row["host_instance_id"],
            sandbox_provider_label=row["sandbox_provider"],
            workdir_id=row["workdir_id"],
            metadata=metadata,
        )


def _dt(posix: float | None) -> datetime | None:
    return None if posix is None else datetime.fromtimestamp(posix, UTC)


def _posix(value) -> float | None:
    return None if value is None else value.timestamp()
