import asyncio
import json
from collections.abc import Mapping
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from agent_platform.core_platform.agent_execution.contracts.snapshots import (
    SNAPSHOT_COLUMNS,
    ExecutionSnapshotError,
    deserialize_execution_snapshots,
)
from agent_platform.core_platform.agent_runtime.hooks import RuntimePersistenceHooks
from agent_platform.core_platform.agent_runtime.notify import QUEUE_CHANNEL, channel
from agent_platform.core_platform.agent_runtime.schemas import (
    TERMINAL,
    BusyError,
    CapacityError,
    ExecutionSnapshotPayloads,
    SnapshotWriteOutcome,
    SnapshotWriteResult,
)
from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    transaction,
)
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    persisted_scope,
    resolve_scope,
    scope_predicate,
)
from agent_platform.extension_contracts import BusinessScope


class RunRepository:
    def __init__(self, engine, hooks: RuntimePersistenceHooks):
        # Required, not defaulted: Core cannot persist a conversation or dispatch
        # memory work by itself, so the composition root must supply an adapter.
        self.engine = engine
        self.hooks = hooks

    async def _event(self, conn, run_id, kind, data):
        seq = await conn.scalar(
            text("""UPDATE runtime_runs SET event_seq=event_seq+1
            WHERE id=:id RETURNING event_seq"""),
            {"id": run_id},
        )
        await conn.execute(
            text("""INSERT INTO runtime_events(run_id,seq,type,data)
            VALUES (:id,:seq,:type,CAST(:data AS jsonb))"""),
            {"id": run_id, "seq": seq, "type": kind, "data": json.dumps(data)},
        )
        # Wake the live console. pg_notify fires on commit, so a rolled-back
        # transaction never produces a phantom notification.
        await conn.execute(
            text("SELECT pg_notify(:ch, :payload)"),
            {
                "ch": channel(run_id),
                "payload": json.dumps({"k": "durable", "seq": seq, "type": kind}),
            },
        )
        if kind == "run.queued":
            # Wake an idle worker so the run does not wait for its next poll. Same
            # transaction, so it fires exactly when the run becomes claimable.
            await conn.execute(text("SELECT pg_notify(:ch, '')"), {"ch": QUEUE_CHANNEL})

    async def submit(
        self,
        tenant,
        request,
        config,
        capacity,
        tenant_capacity,
        queue_timeout,
        connection=None,
        scope: BusinessScope | None = None,
    ):
        resolved_scope = persisted_scope(tenant, scope)
        try:
            async with transaction(self.engine, connection) as conn:
                # Serialize only short admission transactions, across API replicas.
                await conn.execute(text("SELECT pg_advisory_xact_lock(71432019)"))
                counts = (
                    (
                        await conn.execute(
                            text("""SELECT count(*) AS total,
                    count(*) FILTER (WHERE tenant_id=:tenant) AS tenant_count
                    FROM runtime_runs WHERE status IN ('queued','running')"""),
                            {"tenant": tenant},
                        )
                    )
                    .mappings()
                    .one()
                )
                if counts["total"] >= capacity or counts["tenant_count"] >= tenant_capacity:
                    raise CapacityError()
                cid = await conn.scalar(
                    text("""INSERT INTO runtime_conversations
                    (id,tenant_id,business_id,workspace_id,external_id)
                    VALUES (:id,:tenant,:business,:workspace,:external)
                    ON CONFLICT(tenant_id,business_id,workspace_id,external_id)
                    DO NOTHING RETURNING id"""),
                    {
                        "id": uuid4(),
                        "tenant": tenant,
                        "business": resolved_scope.business_id,
                        "workspace": resolved_scope.workspace_id,
                        "external": request.conversation_id,
                    },
                )
                if cid is None:
                    cid = await conn.scalar(
                        text(
                            """SELECT id FROM runtime_conversations
                            WHERE tenant_id=:tenant AND business_id=:business
                              AND workspace_id=:workspace AND external_id=:external"""
                        ),
                        {
                            "tenant": tenant,
                            "business": resolved_scope.business_id,
                            "workspace": resolved_scope.workspace_id,
                            "external": request.conversation_id,
                        },
                    )
                mode = await conn.scalar(
                    text("SELECT mode FROM runtime_conversations WHERE id=:id FOR UPDATE"),
                    {"id": cid},
                )
                if mode != "bot":
                    raise DomainError("conversation_not_in_bot_mode", 409)
                run_id = uuid4()
                row = (
                    (
                        await conn.execute(
                            text("""INSERT INTO runtime_runs
                    (id,conversation_id,tenant_id,business_id,workspace_id,input,config,status,queue_expires_at)
                    VALUES (:id,:cid,:tenant,:business,:workspace,:input,
                    CAST(:config AS jsonb),'queued',
                    now() + :seconds * interval '1 second') RETURNING *"""),
                            {
                                "id": run_id,
                                "cid": cid,
                                "tenant": tenant,
                                "business": resolved_scope.business_id,
                                "workspace": resolved_scope.workspace_id,
                                "input": request.message,
                                "config": json.dumps(config),
                                "seconds": queue_timeout,
                            },
                        )
                    )
                    .mappings()
                    .one()
                )
                await self.hooks.add_message(conn, cid, "user", request.message, run_id)
                await self._event(conn, run_id, "run.queued", {})
                return dict(row)
        except IntegrityError as exc:
            if "runtime_one_active_conversation" in str(exc.orig):
                raise BusyError() from exc
            raise

    async def get(self, run_id: UUID, tenant: str, scope: BusinessScope | None = None):
        resolved_scope = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved_scope)
        async with self.engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """SELECT *, lease_until>now() AS lease_valid FROM runtime_runs
                            WHERE id=:id AND tenant_id=:tenant AND """
                            + scope_sql
                        ),
                        {
                            "id": run_id,
                            "tenant": tenant,
                            **scope_params,
                        },
                    )
                )
                .mappings()
                .first()
            )
            return dict(row) if row else None

    async def events(self, run_id, tenant, after=0, scope: BusinessScope | None = None):
        resolved_scope = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved_scope, "r")
        async with self.engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            """SELECT e.* FROM runtime_events e
                JOIN runtime_runs r ON r.id=e.run_id
                WHERE e.run_id=:id AND r.tenant_id=:tenant AND """
                            + scope_sql
                            + """ AND e.seq>:after
                ORDER BY e.seq LIMIT 200"""
                        ),
                        {
                            "id": run_id,
                            "tenant": tenant,
                            **scope_params,
                            "after": after,
                        },
                    )
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]

    async def claim(self, owner, lease_seconds, tenant):
        async with self.engine.begin() as conn:
            row = (
                (
                    await conn.execute(
                        text("""SELECT *, lease_until>now() AS lease_valid FROM runtime_runs
                WHERE status='queued' AND tenant_id=:tenant AND queue_expires_at>now()
                ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"""),
                        {"tenant": tenant},
                    )
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            row = (
                (
                    await conn.execute(
                        text("""UPDATE runtime_runs SET status='running',
                owner=:owner, started_at=now(),
                lease_until=now()+:lease * interval '1 second' WHERE id=:id RETURNING *"""),
                        {"id": row["id"], "owner": owner, "lease": lease_seconds},
                    )
                )
                .mappings()
                .one()
            )
            history = (
                (
                    await conn.execute(
                        text(
                            "SELECT history,summary,customer_id FROM runtime_conversations WHERE id=:id"
                        ),
                        {"id": row["conversation_id"]},
                    )
                )
                .mappings()
                .one()
            )
            await self._event(conn, row["id"], "run.started", {})
            # The rolling summary and the customer link ride along with the
            # claimed run so the engine can inject both without a round-trip.
            return {
                **dict(row),
                "history": history["history"],
                "summary": history["summary"],
                "customer_id": history["customer_id"],
            }

    async def write_execution_snapshots(
        self, run_id: UUID, owner: UUID, payloads: ExecutionSnapshotPayloads
    ) -> SnapshotWriteResult:
        """Write-once barrier for the five Phase 3 startup snapshots (03 §5.3).

        Entry validation first (the payloads are the caller's handiwork, so
        nothing is trusted): every column must be a JSON object string, and the
        startup identity inside the DTO *and* inside each payload must be this
        row's ``run_id`` (R-9: the identity lives in the snapshot, so a foreign
        ``execution_id`` could otherwise be parked in an empty row and read back
        as this run's authorization). A malformed payload raises
        :class:`ExecutionSnapshotError`; an identity that is not this run's is
        reported as ``audit_conflict`` without touching the database.

        The write itself stays one conditional UPDATE in one transaction: the
        row must be a live, running, lease-held claim by this owner and either
        (a) all five snapshot columns are still NULL — the write then lands
        atomically, so a statement or commit failure can never leave a partial
        row — or (b) the row already carries this startup ``execution_id`` and
        the same five payloads, so a retry of the same startup validates and
        reuses without rewriting. Comparison (b) is PostgreSQL ``jsonb`` value
        equality: the stored documents have to carry the same semantics, not the
        same bytes, because ``jsonb`` re-encodes key order and whitespace. The
        SQL enforces the identity invariant from both sides: every incoming
        payload body — ``:config``, ``:declared``, ``:available``,
        ``:effective``, ``:policy`` — is bound to the ``id`` of the row being
        updated, while the stored branch accepts only a row whose
        ``execution_config_snapshot`` already names this startup. The payload
        side is the independent anchor: ``:execution_id`` is itself taken from
        the caller's payloads, so binding to it would prove nothing. With all
        five bodies bound, even a caller that skipped the entry guard cannot
        land a column naming another run, and cannot point a row at another
        run.

        The result is a :class:`SnapshotWriteResult` (D-3), because a plain
        boolean collapsed four different conditions into one word. Mapping for
        the orchestration caller: ``audit_conflict`` -> fail closed with
        ``Adapter.start`` at zero; ``not_claimed`` / ``lease_lost`` -> the
        existing lost-lease / cancellation path, never a configuration error.
        When the UPDATE matches no row a second, read-only statement classifies
        why in the same transaction; that classification only picks the label,
        it never decides whether the write happens. Historical rows keep NULL
        snapshots; reads never backfill.
        """

        bodies = self._validated_snapshot_bodies(payloads)
        if payloads.execution_id != run_id or any(
            body.get("execution_id") != str(run_id) for body in bodies.values()
        ):
            # R-9: the identity inside the snapshot *is* this row's startup
            # identity, so a foreign one is an audit conflict, never a write.
            # This runs before the cleaning gate on purpose: whose row this is
            # stays a controlled outcome (D-3's distinguishable ``audit_conflict``)
            # and must not be re-reported as a payload-shape error.
            return SnapshotWriteResult("audit_conflict")
        # R-51: nothing below this line may reach SQL without the strict gate.
        self._clean_snapshot_payloads(payloads)
        async with self.engine.begin() as conn:
            row = (
                (
                    await conn.execute(
                        text("""WITH target AS (
                SELECT execution_config_snapshot IS NULL
                AND declared_capabilities_snapshot IS NULL
                AND available_capabilities_snapshot IS NULL
                AND effective_capabilities_snapshot IS NULL
                AND execution_policy_snapshot IS NULL AS was_absent
                FROM runtime_runs WHERE id=:id),
                applied AS (
                UPDATE runtime_runs SET execution_config_snapshot=CAST(:config AS jsonb),
                declared_capabilities_snapshot=CAST(:declared AS jsonb),
                available_capabilities_snapshot=CAST(:available AS jsonb),
                effective_capabilities_snapshot=CAST(:effective AS jsonb),
                execution_policy_snapshot=CAST(:policy AS jsonb)
                WHERE id=:id AND owner=:owner AND status='running' AND lease_until>now()
                AND CAST(:config AS jsonb)->>'execution_id'=CAST(id AS TEXT)
                AND CAST(:declared AS jsonb)->>'execution_id'=CAST(id AS TEXT)
                AND CAST(:available AS jsonb)->>'execution_id'=CAST(id AS TEXT)
                AND CAST(:effective AS jsonb)->>'execution_id'=CAST(id AS TEXT)
                AND CAST(:policy AS jsonb)->>'execution_id'=CAST(id AS TEXT)
                AND (execution_config_snapshot IS NULL
                     OR execution_config_snapshot->>'execution_id'=:execution_id)
                AND ((execution_config_snapshot IS NULL
                      AND declared_capabilities_snapshot IS NULL
                      AND available_capabilities_snapshot IS NULL
                      AND effective_capabilities_snapshot IS NULL
                      AND execution_policy_snapshot IS NULL)
                  OR (execution_config_snapshot->>'execution_id'=:execution_id
                      AND execution_config_snapshot=CAST(:config AS jsonb)
                      AND declared_capabilities_snapshot=CAST(:declared AS jsonb)
                      AND available_capabilities_snapshot=CAST(:available AS jsonb)
                      AND effective_capabilities_snapshot=CAST(:effective AS jsonb)
                      AND execution_policy_snapshot=CAST(:policy AS jsonb)))
                RETURNING id)
                SELECT EXISTS(SELECT 1 FROM applied) AS applied,
                (SELECT was_absent FROM target) AS was_absent"""),
                        {
                            "id": run_id,
                            "owner": owner,
                            "execution_id": str(payloads.execution_id),
                            "config": payloads.execution_config_snapshot,
                            "declared": payloads.declared_capabilities_snapshot,
                            "available": payloads.available_capabilities_snapshot,
                            "effective": payloads.effective_capabilities_snapshot,
                            "policy": payloads.execution_policy_snapshot,
                        },
                    )
                )
                .mappings()
                .one()
            )
            if row["applied"]:
                # ``was_absent`` is the state this statement itself saw before
                # writing, so it cannot be shifted by our own UPDATE. A
                # concurrent writer that committed in between can still make
                # both sides report ``written``; the label is diagnostic only
                # and the stored row is identical either way.
                return SnapshotWriteResult("written" if row["was_absent"] else "reused")
            classified = (
                (
                    await conn.execute(
                        text("""SELECT status, owner, lease_until>now() AS lease_valid
                FROM runtime_runs WHERE id=:id"""),
                        {"id": run_id},
                    )
                )
                .mappings()
                .first()
            )
            return SnapshotWriteResult(self._snapshot_write_diagnosis(classified, owner))

    @staticmethod
    def _clean_snapshot_payloads(payloads: ExecutionSnapshotPayloads) -> None:
        """The R-51 cleaning gate: strict re-validation, before any SQL.

        Shape checking alone cannot see the two classes 04 P3-IT-08 requires
        refused on their own - a *missing* entry and a *duplicated* one - because
        ``assert_snapshot_payload_clean`` only walks keys and value shapes. Re-
        running the public deserializer per column adds exactly that coverage:
        the denylist and value scans, the strict ``extra="forbid"`` schema with
        full capability coverage, the canonical round-trip (which is what catches
        a de-duplicated or truncated collection) and cross-column identity.

        It stays in Python and in front of ``engine.begin()``, so a refused
        payload performs no statement at all and the row keeps its five NULL
        columns, and it is a domain ``ExecutionSnapshotError`` naming only the
        column, never the rejected content.
        """

        deserialize_execution_snapshots(
            {column: getattr(payloads, column) for column in SNAPSHOT_COLUMNS}
        )

    @staticmethod
    def _validated_snapshot_bodies(payloads: ExecutionSnapshotPayloads) -> dict[str, dict]:
        """Reject non-canonical payload input before it reaches ``CAST(... AS jsonb)``.

        A caller that bypasses ``serialize_execution_snapshots`` would otherwise
        get a database-level ``invalid input syntax for type json`` instead of a
        domain error, and the fail-closed mapping in the orchestrator would never
        see it. Only the column name and a stable code are reported — never the
        offending content.

        This is the shape half of the entry guard; the strict half is
        :meth:`_clean_snapshot_payloads`, which runs after the identity comparison
        so that a foreign startup keeps its own distinguishable outcome.
        """

        bodies: dict[str, dict] = {}
        for column in SNAPSHOT_COLUMNS:
            value = getattr(payloads, column)
            if not isinstance(value, str):
                raise ExecutionSnapshotError("snapshot_payload_type_invalid", (column,)) from None
            try:
                body = json.loads(value)
            except ValueError:
                raise ExecutionSnapshotError("snapshot_field_invalid", (column,)) from None
            if not isinstance(body, dict):
                raise ExecutionSnapshotError("snapshot_field_invalid", (column,)) from None
            bodies[column] = body
        return bodies

    @staticmethod
    def _snapshot_write_diagnosis(
        classified: Mapping[str, object] | None, owner: UUID
    ) -> SnapshotWriteOutcome:
        """Label for a conditional UPDATE that matched no row.

        Read-only and diagnostic only — the write decision was already made by
        the statement's own WHERE. Order matters: an absent or non-running row is
        never a configuration fault, a foreign owner/expired lease is the
        existing lost-lease condition, and only a live owned claim that still
        refused the row means the stored audit disagrees with this startup.
        """

        if classified is None:
            return "not_claimed"
        if classified["status"] != "running":
            return "not_claimed"
        if classified["owner"] != owner or not classified["lease_valid"]:
            return "lease_lost"
        return "audit_conflict"

    async def append(self, run_id, owner, kind, data):
        async with self.engine.begin() as conn:
            current = (
                (
                    await conn.execute(
                        text("""SELECT *, lease_until>now() AS lease_valid FROM runtime_runs
                WHERE id=:id FOR UPDATE"""),
                        {"id": run_id},
                    )
                )
                .mappings()
                .one()
            )
            if current["status"] != "running" or current["owner"] != owner:
                raise asyncio.CancelledError()
            if current["cancel_requested"] or not current["lease_valid"]:
                raise asyncio.CancelledError()
            await self._event(conn, run_id, kind, data)

    async def heartbeat(self, run_id, owner, lease_seconds):
        async with self.engine.begin() as conn:
            cancelled = await conn.scalar(
                text("""UPDATE runtime_runs SET
                lease_until=now()+:lease * interval '1 second'
                WHERE id=:id AND owner=:owner AND status='running' AND lease_until>now()
                RETURNING cancel_requested"""),
                {"id": run_id, "owner": owner, "lease": lease_seconds},
            )
            return "lost" if cancelled is None else ("cancel" if cancelled else "ok")

    async def finish(
        self, run_id, owner, status, output=None, error=None, history=None, completion=None
    ):
        async with self.engine.begin() as conn:
            cid = await conn.scalar(
                text("SELECT conversation_id FROM runtime_runs WHERE id=:id"), {"id": run_id}
            )
            # Lock the conversation, but do not read summary/customer_id/source:
            # those are business columns, so the hook adapter loads them itself
            # inside this same transaction.
            await conn.execute(
                text("SELECT id FROM runtime_conversations WHERE id=:id FOR UPDATE"),
                {"id": cid},
            )
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT *, lease_until>now() AS lease_valid FROM runtime_runs WHERE id=:id FOR UPDATE"
                        ),
                        {"id": run_id},
                    )
                )
                .mappings()
                .one()
            )
            if row["status"] in TERMINAL or row["owner"] != owner or not row["lease_valid"]:
                return
            if row["cancel_requested"]:
                status, output, error = "cancelled", None, None
            await conn.execute(
                text("""UPDATE runtime_runs SET status=:status,output=:output,
                error_code=:error,finished_at=now(),lease_until=NULL WHERE id=:id"""),
                {"id": run_id, "status": status, "output": output, "error": error},
            )
            if status == "completed":
                for kind, data in await self.hooks.on_completed(
                    conn, row, cid, output, history, completion
                ):
                    await self._event(conn, run_id, kind, data)
            await self._event(
                conn, run_id, "run." + status, {"output": output, "error_code": error}
            )

    async def cancel(self, run_id, tenant, scope: BusinessScope | None = None):
        resolved_scope = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved_scope)
        async with self.engine.begin() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """SELECT *, lease_until>now() AS lease_valid FROM runtime_runs
                            WHERE id=:id AND tenant_id=:tenant AND """
                            + scope_sql
                            + " FOR UPDATE"
                        ),
                        {
                            "id": run_id,
                            "tenant": tenant,
                            **scope_params,
                        },
                    )
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            if row["status"] not in TERMINAL and not row["cancel_requested"]:
                await conn.execute(
                    text("UPDATE runtime_runs SET cancel_requested=true WHERE id=:id"),
                    {"id": run_id},
                )
                if row["status"] == "queued":
                    await conn.execute(
                        text("""UPDATE runtime_runs SET status='cancelled',
                        finished_at=now() WHERE id=:id"""),
                        {"id": run_id},
                    )
                    await self._event(conn, run_id, "run.cancelled", {})
                else:
                    await self._event(conn, run_id, "run.cancel_requested", {})
        return await self.get(run_id, tenant, resolved_scope)

    async def reap(self, tenant):
        async with self.engine.begin() as conn:
            rows = (
                (
                    await conn.execute(
                        text("""SELECT * FROM runtime_runs WHERE tenant_id=:tenant
                AND ((status='running' AND lease_until<now())
                OR (status='queued' AND queue_expires_at<now()))
                FOR UPDATE SKIP LOCKED LIMIT 100"""),
                        {"tenant": tenant},
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                status = "cancelled" if row["cancel_requested"] else "failed"
                error = "worker_lost" if row["status"] == "running" else "queue_timeout"
                await conn.execute(
                    text("""UPDATE runtime_runs SET status=:status,error_code=:error,
                    finished_at=now(),lease_until=NULL WHERE id=:id"""),
                    {"id": row["id"], "status": status, "error": error},
                )
                await self._event(conn, row["id"], "run." + status, {"error_code": error})
