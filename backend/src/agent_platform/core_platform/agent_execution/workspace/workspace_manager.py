"""Durable Execution Workspace manager (Phase 4, 08 T6, 02 FR-5, AC-6).

Implements the WorkspaceProvider contract over ``execution_workdirs`` with the
raw-SQL repository style of ``agent_runtime/repository.py`` (08 R-9): every
state move is a conditional UPDATE whose WHERE clause re-asserts the trusted
run/tenant identity, so records can never be transitioned - or cleaned - by a
caller that addresses another tenant's Workdir id. Filesystem effects run off
the event loop through the handle-based ``execution_workdir`` operations; the
record is the only authority for what may be deleted, and cleanup failures
retain the record for retry/alert instead of ever faking success (03 §4.5
rule 5, FR-5 failure row). Retention uses the injected POSIX clock (Phase 3
R-49 precedent) with success/failed windows from FR-10.
"""

import asyncio
import logging
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import time
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from . import execution_workdir as workdir_ops
from . import workspace_policy as policy
from .workspace_provider import WorkdirRecord

logger = logging.getLogger(__name__)

_SELECT_COLUMNS = (
    "SELECT id, run_id, tenant_id, business_id, workspace_id, relative_path, status,"
    " quota_bytes, size_bytes, file_count, expires_at, last_error_code, created_at"
    " FROM execution_workdirs"
)


class WorkspaceStateError(RuntimeError):
    """Manager-level rejection carrying a stable WorkdirErrorCode."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _as_posix(value: datetime | None) -> float | None:
    return None if value is None else value.timestamp()


class ExecutionWorkspaceManager:
    """The WorkspaceProvider implementation backed by PG + the Workdir root."""

    def __init__(
        self,
        engine,
        *,
        root: Path | str,
        quota_bytes: int,
        retention_seconds: int,
        failed_retention_seconds: int,
        clock: Callable[[], float] | None = None,
        mount_probe: Callable[[int, int], bool] | None = None,
    ) -> None:
        if quota_bytes <= 0:
            raise ValueError("quota_bytes must be positive")
        if retention_seconds < 0 or failed_retention_seconds < 0:
            raise ValueError("retention windows must be nonnegative")
        self._engine = engine
        self._root = Path(root)
        self._quota_bytes = quota_bytes
        self._retention_seconds = retention_seconds
        self._failed_retention_seconds = failed_retention_seconds
        self._clock = clock or time
        # Substituted in tests and (for live mount experiments) pending_env
        # environments; the default is the device-comparison probe.
        self._mount_probe = mount_probe or policy.default_mount_probe

    # ------------------------------------------------------------------
    # WorkspaceProvider contract
    # ------------------------------------------------------------------

    async def prepare(
        self,
        *,
        run_id: UUID,
        tenant_id: str,
        business_id: str,
        workspace_id: str,
    ) -> WorkdirRecord:
        """Persist ``preparing``, build the tree from the verified root, ``ready``.

        The relative path is generated exclusively from the trusted tenant
        digest and Run UUID; nothing here accepts a location from a caller.
        R-11 contract - ready-or-refuse with self-convergence: ``prepare``
        never returns a ``preparing`` record and never blocks or polls. On an
        ON CONFLICT race whose existing row is still ``preparing`` (a slow or
        crashed winner), a caller whose trusted ids match re-runs the same
        convergent handle build and the same guarded ``preparing -> ready``
        update exactly once, then refetches; trusted-id mismatch is a stable
        ``workdir_persistence_conflict``, and any post-condition outside
        ``ready``/``active`` refuses start (FR-5 failure row). A filesystem
        failure is recorded as ``cleanup_failed`` for alert/retry before the
        error surfaces.
        """
        relative_path = self._generated_path(tenant_id, run_id)
        workdir_id = uuid4()
        try:
            async with self._engine.begin() as conn:
                inserted = (
                    await conn.execute(
                        text(
                            "INSERT INTO execution_workdirs"
                            " (id, run_id, tenant_id, business_id, workspace_id,"
                            " relative_path, status, quota_bytes)"
                            " VALUES (:id, :run_id, :tenant_id, :business_id, :workspace_id,"
                            " :relative_path, 'preparing', :quota)"
                            " ON CONFLICT (run_id) DO NOTHING"
                            " RETURNING id"
                        ),
                        {
                            "id": workdir_id,
                            "run_id": run_id,
                            "tenant_id": tenant_id,
                            "business_id": business_id,
                            "workspace_id": workspace_id,
                            "relative_path": relative_path,
                            "quota": self._quota_bytes,
                        },
                    )
                ).first()
        except IntegrityError as exc:
            raise WorkspaceStateError(
                "workdir_persistence_conflict",
                "run identity not present or conflicting",
            ) from exc
        if inserted is None:
            existing = await self._fetch(where="run_id=:run_id", params={"run_id": run_id})
            if existing is None:  # pragma: no cover - conflict implies the row
                raise WorkspaceStateError("workdir_persistence_conflict", "conflict without row")
            if (
                existing.tenant_id != tenant_id
                or existing.business_id != business_id
                or existing.workspace_id != workspace_id
            ):
                # Same Run, different trusted scope: refuse, never adopt.
                raise WorkspaceStateError(
                    "workdir_persistence_conflict",
                    "trusted ids disagree with the durable record",
                )
            if existing.status == "preparing":
                return await self._converge_preparing(
                    run_id=run_id, tenant_id=tenant_id, relative_path=relative_path
                )
            if existing.status in ("ready", "active"):
                return existing
            raise WorkspaceStateError(
                "workdir_state_invalid", f"prepare cannot return {existing.status}"
            )

        try:
            await asyncio.to_thread(self._fs_prepare, relative_path)
        except workdir_ops.WorkdirOperationError as exc:
            await self._conditional_update(
                to_status="cleanup_failed",
                where_status_in=("preparing",),
                run_id=run_id,
                tenant_id=tenant_id,
                set_extra=", last_error_code=:error_code",
                extra_params={"error_code": exc.code},
            )
            logger.error(
                "execution workdir prepare failed code=%s run_id=%s tenant=%s",
                exc.code,
                run_id,
                tenant_id,
            )
            raise WorkspaceStateError(exc.code) from exc

        await self._conditional_update(
            to_status="ready",
            where_status_in=("preparing",),
            run_id=run_id,
            tenant_id=tenant_id,
        )
        record = await self._fetch(
            where="run_id=:run_id AND tenant_id=:tenant_id",
            params={"run_id": run_id, "tenant_id": tenant_id},
        )
        if record is None or record.status not in ("ready", "active"):
            raise WorkspaceStateError("workdir_state_invalid", "prepare did not reach ready")
        return record

    async def activate(self, *, workdir_id: UUID, run_id: UUID, tenant_id: str) -> WorkdirRecord:
        """``ready`` -> ``active``; already-active rows return idempotently."""
        await self._conditional_update(
            to_status="active",
            where_status_in=("ready",),
            run_id=run_id,
            tenant_id=tenant_id,
            workdir_id=workdir_id,
        )
        return await self._require_current(workdir_id, run_id, tenant_id, acceptable=("active",))

    async def retain(
        self,
        *,
        workdir_id: UUID,
        run_id: UUID,
        tenant_id: str,
        outcome: str,
    ) -> WorkdirRecord:
        """Record the terminal decision with the success/failed retention window.

        Usage observation is best-effort: an accounting violation (link/mount)
        keeps the recorded size unchanged with a warning rather than losing
        the retention decision, and cleanup will re-enforce the scope later.
        """
        if outcome not in ("success", "failed"):
            raise WorkspaceStateError("workdir_state_invalid", "unknown retain outcome")
        window = self._retention_seconds if outcome == "success" else self._failed_retention_seconds
        record = await self._fetch(
            where="id=:workdir_id AND run_id=:run_id AND tenant_id=:tenant_id",
            params={"workdir_id": workdir_id, "run_id": run_id, "tenant_id": tenant_id},
        )
        if record is None:
            raise WorkspaceStateError("workdir_persistence_conflict", "unknown workdir")
        if record.status == "retained":
            return record  # idempotent: the decision already landed
        if record.status not in ("ready", "active"):
            raise WorkspaceStateError("workdir_state_invalid", f"cannot retain {record.status}")
        size_params: dict[str, object] = {}
        try:
            usage = await asyncio.to_thread(self._fs_account, record.relative_path)
            size_params = {"size_bytes": usage.total_bytes, "file_count": usage.file_count}
            # R-12: a successful observation always persists, including an
            # over-quota one; the excess signal is the persisted row plus
            # this structured alert with the stable reason code, never a
            # warn-only stale record. Over-quota never flips the retain
            # decision and never touches last_error_code.
            self._alert_over_quota(record, usage, run_id=run_id, tenant_id=tenant_id)
        except workdir_ops.WorkdirOperationError as exc:
            # A failed/partial observation never overwrites the last
            # successful one (fail-closed, 04 Principle 3).
            logger.warning(
                "workdir usage accounting skipped code=%s run_id=%s tenant=%s",
                exc.code,
                run_id,
                tenant_id,
            )
        await self._conditional_update(
            to_status="retained",
            where_status_in=("ready", "active"),
            run_id=run_id,
            tenant_id=tenant_id,
            workdir_id=workdir_id,
            set_extra=", expires_at=:expires"
            + (", size_bytes=:size_bytes, file_count=:file_count" if size_params else ""),
            extra_params={
                "expires": datetime.fromtimestamp(self._clock() + window, UTC),
                **size_params,
            },
        )
        return await self._require_current(workdir_id, run_id, tenant_id, acceptable=("retained",))

    async def cleanup(self, *, workdir_id: UUID, run_id: UUID, tenant_id: str) -> WorkdirRecord:
        """Idempotent safe cleanup; honest retry/alert on unprovable scope.

        The removal scope is re-derived from the durable record and re-checked
        against the generator before any filesystem call, so a tampered or
        mispointed row is refused (never "cleaned somewhere else"). Failures
        leave the row ``cleanup_failed`` with the stable code and surface the
        error to the caller. Every physical deletion path - interval sweeper,
        cleanup_failed retry and the direct retain->clean branch all enter
        here - performs one best-effort usage re-observation before removal
        and persists it on success (08 R-12), so the Tombstone carries the
        final successful observation for audit.
        """
        record = await self._fetch(
            where="id=:workdir_id AND run_id=:run_id AND tenant_id=:tenant_id",
            params={"workdir_id": workdir_id, "run_id": run_id, "tenant_id": tenant_id},
        )
        if record is None:
            raise WorkspaceStateError("workdir_persistence_conflict", "unknown workdir")
        if record.status == "deleted":
            return record  # Tombstone: cleanup is idempotent forever after

        try:
            expected_path = self._generated_path(record.tenant_id, record.run_id)
        except policy.WorkspacePathError as exc:
            await self._mark_cleanup_failed(
                record, "workdir_path_rejected", run_id=run_id, tenant_id=tenant_id
            )
            raise WorkspaceStateError("workdir_path_rejected") from exc
        if record.relative_path != expected_path:
            await self._mark_cleanup_failed(
                record, "workdir_scope_mismatch", run_id=run_id, tenant_id=tenant_id
            )
            logger.error("execution workdir scope mismatch run_id=%s tenant=%s", run_id, tenant_id)
            raise WorkspaceStateError("workdir_scope_mismatch")

        entered = await self._conditional_update(
            to_status="cleaning",
            where_status_in=(
                "preparing",
                "ready",
                "active",
                "retained",
                "cleaning",
                "cleanup_failed",
            ),
            run_id=run_id,
            tenant_id=tenant_id,
            workdir_id=workdir_id,
        )
        if not entered:
            current = await self._fetch(where="id=:workdir_id", params={"workdir_id": workdir_id})
            if current is not None and current.status == "deleted":
                return current
            raise WorkspaceStateError("workdir_state_invalid", "cannot enter cleaning")

        try:
            usage = await asyncio.to_thread(self._fs_account, record.relative_path)
            persisted = await self._persist_observation(
                workdir_id=workdir_id, run_id=run_id, tenant_id=tenant_id, usage=usage
            )
            if persisted:
                self._alert_over_quota(record, usage, run_id=run_id, tenant_id=tenant_id)
        except workdir_ops.WorkdirOperationError as exc:
            # R-12: a failed pre-delete re-observation is tolerated - the
            # deletion proceeds under its own scope rechecks and the row
            # keeps the last successful observation.
            logger.warning(
                "workdir pre-delete observation skipped code=%s run_id=%s tenant=%s",
                exc.code,
                run_id,
                tenant_id,
            )

        try:
            await asyncio.to_thread(self._fs_remove, record.relative_path)
        except workdir_ops.WorkdirOperationError as exc:
            await self._conditional_update(
                to_status="cleanup_failed",
                where_status_in=("cleaning",),
                run_id=run_id,
                tenant_id=tenant_id,
                workdir_id=workdir_id,
                set_extra=", last_error_code=:error_code",
                extra_params={"error_code": exc.code},
            )
            logger.error(
                "execution workdir cleanup failed code=%s run_id=%s tenant=%s",
                exc.code,
                run_id,
                tenant_id,
            )
            raise WorkspaceStateError(exc.code) from exc

        await self._conditional_update(
            to_status="deleted",
            where_status_in=("cleaning",),
            run_id=run_id,
            tenant_id=tenant_id,
            workdir_id=workdir_id,
            set_extra=", cleaned_at=now()",
        )
        current = await self._fetch(where="id=:workdir_id", params={"workdir_id": workdir_id})
        assert current is not None
        return current

    async def get(self, *, run_id: UUID, tenant_id: str) -> WorkdirRecord | None:
        return await self._fetch(
            where="run_id=:run_id AND tenant_id=:tenant_id",
            params={"run_id": run_id, "tenant_id": tenant_id},
        )

    async def sweep_expired(
        self,
        *,
        now_posix: float | None = None,
        batch_size: int = 32,
        tenant_id: str | None = None,
    ) -> Sequence[WorkdirRecord]:
        """Candidates for the interval scan: expired retained rows plus retries.

        cleanup_failed rows are always candidates (retry with alert), retained
        rows once ``expires_at`` has passed. Callers drive each candidate
        through :meth:`cleanup`, which is idempotent and race-safe. The
        optional tenant filter keeps operational scans scoped in tests and
        multi-tenant deployments without changing the global default.
        """
        now = self._clock() if now_posix is None else now_posix
        sql = (
            _SELECT_COLUMNS + " WHERE ((status = 'retained' AND expires_at IS NOT NULL"
            " AND expires_at <= :now) OR status = 'cleanup_failed')"
        )
        params: dict[str, object] = {
            "now": datetime.fromtimestamp(now, UTC),
            "batch": batch_size,
        }
        if tenant_id is not None:
            sql += " AND tenant_id = :tenant_id"
            params["tenant_id"] = tenant_id
        sql += " ORDER BY expires_at ASC NULLS FIRST LIMIT :batch"
        async with self._engine.begin() as conn:
            rows = (await conn.execute(text(sql), params)).mappings()
            return [self._to_record(row) for row in rows]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _generated_path(self, tenant_id: str, run_id: UUID) -> str:
        try:
            return policy.build_relative_path(tenant_id, str(run_id))
        except policy.WorkspacePathError as exc:
            raise WorkspaceStateError("workdir_path_rejected", "trusted ids unusable") from exc

    async def _converge_preparing(
        self, *, run_id: UUID, tenant_id: str, relative_path: str
    ) -> WorkdirRecord:
        """R-11 self-convergence for a conflicted ``preparing`` row.

        One rerun of the convergent build (create_workdir/ensure_layout are
        idempotent by construction, so a concurrent winner's partial tree
        converges or is found complete) plus one guarded ``preparing ->
        ready`` update, then a refetch. No polling, no waiting: if the
        guarded update loses to the winner, the winner's landing is visible
        in the refetch; anything still unusable refuses start.
        """
        try:
            await asyncio.to_thread(self._fs_prepare, relative_path)
        except workdir_ops.WorkdirOperationError as exc:
            await self._conditional_update(
                to_status="cleanup_failed",
                where_status_in=("preparing",),
                run_id=run_id,
                tenant_id=tenant_id,
                set_extra=", last_error_code=:error_code",
                extra_params={"error_code": exc.code},
            )
            logger.error(
                "execution workdir prepare convergence failed code=%s run_id=%s tenant=%s",
                exc.code,
                run_id,
                tenant_id,
            )
            raise WorkspaceStateError(exc.code) from exc

        await self._conditional_update(
            to_status="ready",
            where_status_in=("preparing",),
            run_id=run_id,
            tenant_id=tenant_id,
        )
        current = await self._fetch(
            where="run_id=:run_id AND tenant_id=:tenant_id",
            params={"run_id": run_id, "tenant_id": tenant_id},
        )
        if current is not None and current.status in ("ready", "active"):
            return current
        raise WorkspaceStateError("workdir_state_invalid", "prepare could not converge")

    def _alert_over_quota(
        self,
        record: WorkdirRecord,
        usage,
        *,
        run_id: UUID,
        tenant_id: str,
    ) -> None:
        """Structured excess alert (08 R-12): the persisted observation plus
        this log carrying the stable resource-excess reason code from the
        host reason vocabulary. No paths, no exception text."""
        if usage.total_bytes <= record.quota_bytes:
            return
        logger.warning(
            "execution workdir over quota code=runtime_host_resource_exceeded"
            " run_id=%s tenant_id=%s observed_bytes=%s quota_bytes=%s",
            run_id,
            tenant_id,
            usage.total_bytes,
            record.quota_bytes,
        )

    async def _persist_observation(
        self,
        *,
        workdir_id: UUID,
        run_id: UUID,
        tenant_id: str,
        usage,
    ) -> bool:
        """Persist a successful observation while the row stays in cleaning."""
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE execution_workdirs"
                    " SET size_bytes=:size, file_count=:files, updated_at=now()"
                    " WHERE id=:id AND run_id=:run_id AND tenant_id=:tenant_id"
                    " AND status = 'cleaning'"
                ),
                {
                    "size": usage.total_bytes,
                    "files": usage.file_count,
                    "id": workdir_id,
                    "run_id": run_id,
                    "tenant_id": tenant_id,
                },
            )
        return result.rowcount > 0

    def _fs_prepare(self, relative_path: str) -> None:
        root_fd = workdir_ops.ensure_execution_root(self._root)
        try:
            handles = workdir_ops.create_workdir(root_fd, relative_path)
            try:
                workdir_ops.ensure_layout(handles.run_fd)
            finally:
                handles.close()
        finally:
            os.close(root_fd)

    def _fs_account(self, relative_path: str):
        root_fd = workdir_ops.ensure_execution_root(self._root)
        try:
            handles = workdir_ops.open_workdir(root_fd, relative_path)
            try:
                return workdir_ops.account_usage(handles.run_fd, mount_probe=self._mount_probe)
            finally:
                handles.close()
        finally:
            os.close(root_fd)

    def _fs_remove(self, relative_path: str) -> None:
        root_fd = workdir_ops.ensure_execution_root(self._root)
        try:
            workdir_ops.remove_workdir(root_fd, relative_path, mount_probe=self._mount_probe)
        finally:
            os.close(root_fd)

    async def _fetch(self, *, where: str, params: dict[str, object]) -> WorkdirRecord | None:
        async with self._engine.begin() as conn:
            row = (await conn.execute(text(_SELECT_COLUMNS + " WHERE " + where), params)).mappings()
            first = row.first()
        return None if first is None else self._to_record(first)

    async def _require_current(
        self,
        workdir_id: UUID,
        run_id: UUID,
        tenant_id: str,
        *,
        acceptable: tuple[str, ...],
    ) -> WorkdirRecord:
        record = await self._fetch(
            where="id=:workdir_id AND run_id=:run_id AND tenant_id=:tenant_id",
            params={"workdir_id": workdir_id, "run_id": run_id, "tenant_id": tenant_id},
        )
        if record is None:
            raise WorkspaceStateError("workdir_persistence_conflict", "unknown workdir")
        if record.status not in acceptable:
            raise WorkspaceStateError(
                "workdir_state_invalid", f"status {record.status} not in {acceptable}"
            )
        return record

    async def _conditional_update(
        self,
        *,
        to_status: str,
        where_status_in: tuple[str, ...],
        run_id: UUID,
        tenant_id: str,
        workdir_id: UUID | None = None,
        set_extra: str = "",
        extra_params: dict[str, object] | None = None,
    ) -> bool:
        params: dict[str, object] = {
            "status": to_status,
            "run_id": run_id,
            "tenant_id": tenant_id,
            **(extra_params or {}),
        }
        identity = "id=:workdir_id AND " if workdir_id is not None else ""
        if workdir_id is not None:
            params["workdir_id"] = workdir_id
        placeholders = ", ".join(f":ws_{index}" for index in range(len(where_status_in)))
        for index, status in enumerate(where_status_in):
            params[f"ws_{index}"] = status
        async with self._engine.begin() as conn:
            result = await conn.execute(
                text(
                    "UPDATE execution_workdirs"
                    f" SET status=:status, updated_at=now(){set_extra}"
                    f" WHERE {identity}run_id=:run_id AND tenant_id=:tenant_id"
                    f" AND status IN ({placeholders})"
                ),
                params,
            )
        return result.rowcount > 0

    async def _mark_cleanup_failed(
        self,
        record: WorkdirRecord,
        code: str,
        *,
        run_id: UUID,
        tenant_id: str,
    ) -> None:
        entered = await self._conditional_update(
            to_status="cleanup_failed",
            where_status_in=(record.status,),
            run_id=run_id,
            tenant_id=tenant_id,
            workdir_id=record.workdir_id,
            set_extra=", last_error_code=:error_code",
            extra_params={"error_code": code},
        )
        if not entered:
            logger.warning(
                "workdir cleanup_failed marking raced run_id=%s tenant=%s code=%s",
                run_id,
                tenant_id,
                code,
            )

    @staticmethod
    def _to_record(row) -> WorkdirRecord:
        return WorkdirRecord(
            workdir_id=row["id"],
            run_id=row["run_id"],
            tenant_id=row["tenant_id"],
            business_id=row["business_id"],
            workspace_id=row["workspace_id"],
            relative_path=row["relative_path"],
            status=row["status"],
            quota_bytes=row["quota_bytes"],
            size_bytes=row["size_bytes"],
            file_count=row["file_count"],
            expires_at_posix=_as_posix(row["expires_at"]),
            last_error_code=row["last_error_code"],
            created_at_posix=_as_posix(row["created_at"]) or 0.0,
        )
