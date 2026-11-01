import base64
import binascii
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from agent_platform.business_capabilities.conversation.service import add_message
from agent_platform.business_capabilities.customer_service.routing.decision import (
    RoutingDecision,
    decide_ingress,
)
from agent_platform.business_capabilities.customer_service.routing.repository import (
    list_decisions,
    record,
    summarize_decisions,
)
from agent_platform.business_capabilities.customer_service.routing.settings import (
    CustomerServiceRoutingSettings,
    load_customer_service_routing_settings,
)
from agent_platform.business_capabilities.memory.events import enqueue_event_task
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    audit,
    execute,
    many,
    one,
    required,
    transaction,
)
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    resolve_scope,
    scope_predicate,
)
from agent_platform.extension_contracts import BusinessScope, EventEnvelope, EventPublisher


class TicketProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=8000)


TICKET_VIEW = """SELECT t.*,d.description,d.resolution,
    COALESCE((SELECT l.content FROM ticket_process_log l WHERE l.ticket_id=t.id
        AND l.tenant_id=t.tenant_id AND l.business_id=t.business_id
        AND l.workspace_id=t.workspace_id
        AND l.action_type IN ('remark','legacy_note')
        ORDER BY l.id DESC LIMIT 1),'') AS note,
    EXISTS(SELECT 1 FROM memory_customers mc
        WHERE mc.tenant_id=t.tenant_id
          AND mc.business_id=t.business_id AND mc.workspace_id=t.workspace_id
          AND mc.id::text=t.customer_id) AS customer_active
    FROM tickets t JOIN tickets_detail d
        ON d.ticket_id=t.id AND d.tenant_id=t.tenant_id
        AND d.business_id=t.business_id AND d.workspace_id=t.workspace_id """

# Sentinel for "the caller did not mention due_at" — distinct from an
# explicit None, which clears the column (R12).
UNSET = object()


class CustomerService:
    def __init__(
        self,
        engine,
        repository,
        agents,
        handoffs,
        settings,
        snapshot,
        memory=None,
        events: EventPublisher | None = None,
        routing_settings: CustomerServiceRoutingSettings | None = None,
    ):
        self.engine, self.repository, self.agents, self.handoffs = (
            engine,
            repository,
            agents,
            handoffs,
        )
        self.settings, self.snapshot = settings, snapshot
        # Phase 4 (R13): optional memory service for the blacklist auto
        # handoff; None keeps every legacy wiring unchanged.
        self.memory = memory
        self.events = events
        self.routing_settings = routing_settings or load_customer_service_routing_settings()
        # Process-local diagnostics. The durable routing table remains the source
        # of truth; this counter makes isolated insert failures visible without
        # turning observability into a second persistence system.
        self._routing_write_failures: Counter[str] = Counter()

    async def _publish_ticket_event(
        self,
        event_type: str,
        tenant_id: str,
        aggregate_id: UUID | str,
        payload: dict[str, object],
        idempotency_key: str,
        scope: BusinessScope | None = None,
    ) -> None:
        if self.events is None:
            return
        resolved = resolve_scope(tenant_id, scope)
        await self.events.publish(
            EventEnvelope(
                event_type=event_type,
                tenant_id=tenant_id,
                aggregate_type="ticket",
                aggregate_id=str(aggregate_id),
                payload={
                    **payload,
                    "business_id": resolved.business_id,
                    "workspace_id": resolved.workspace_id,
                },
                idempotency_key=idempotency_key,
            )
        )

    async def send(
        self,
        tenant,
        actor,
        cid,
        message,
        connection=None,
        scope: BusinessScope | None = None,
    ):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved)
        async with transaction(self.engine, connection) as c:
            # Admission lock precedes conversation lock everywhere to avoid inverse lock ordering.
            await execute(c, "SELECT pg_advisory_xact_lock(71432019)")
            conv = required(
                await one(
                    c,
                    """SELECT * FROM runtime_conversations
                    WHERE id=:id AND tenant_id=:t AND """
                    + scope_sql
                    + " FOR UPDATE",
                    id=cid,
                    t=tenant,
                    **scope_params,
                )
            )
            ingress = await decide_ingress(
                conn=c,
                conv=conv,
                message=message,
                request_id=uuid4(),
                agents=self.agents,
                memory=self.memory,
                settings=self.settings,
                routing_settings=self.routing_settings,
            )
            await self._record_decision(c, ingress.decision)
            return await self._apply_decision(
                c,
                conv,
                ingress.decision,
                ingress.agent_snapshot,
                message,
                tenant,
                actor,
                resolved,
            )

    async def _record_decision(self, conn, decision: RoutingDecision) -> bool:
        if not self.routing_settings.trace_enabled:
            return False
        recorded = await record(conn, decision)
        if not recorded:
            self._routing_write_failures[decision.tenant_id] += 1
        return recorded

    async def _apply_decision(
        self,
        conn,
        conv: dict[str, object],
        decision: RoutingDecision,
        agent_snapshot: dict[str, object] | None,
        message: str,
        tenant: str,
        actor: str,
        resolved: BusinessScope,
    ) -> dict[str, object]:
        cid = conv["id"]
        if decision.action == "reject":
            return {
                "conversation_id": cid,
                "run": None,
                "rejected": decision.reason_code,
            }
        if decision.action == "request_handoff":
            await add_message(conn, cid, "user", message)
            reason = (
                "黑名单客户自动转人工"
                if decision.reason_code == "blacklist_flag"
                else "用户请求人工服务"
            )
            handoff = await self.handoffs.request(
                tenant,
                actor,
                cid,
                reason,
                conn,
                scope=resolved,
            )
            return {"conversation_id": cid, "run": None, "handoff": handoff}
        if decision.action == "defer":
            await add_message(conn, cid, "user", message)
            await execute(
                conn,
                "UPDATE runtime_conversations SET history=CAST(:msg AS jsonb) WHERE id=:id",
                id=cid,
                msg=json.dumps(
                    (
                        [*conv["history"], {"role": "user", "content": message}][
                            -self.settings.history_turns * 2 :
                        ]
                    )
                    if self.settings.history_turns
                    else []
                ),
            )
            return {"conversation_id": cid, "run": None}
        if decision.action == "submit_agent_run":
            return await self._submit_run(
                conn,
                conv,
                agent_snapshot,
                message,
                tenant,
                actor,
            )
        raise DomainError("routing_action_unhandled", 500)

    async def _submit_run(
        self,
        conn,
        conv: dict[str, object],
        agent_snapshot: dict[str, object] | None,
        message: str,
        tenant: str,
        actor: str,
    ) -> dict[str, object]:
        snapshot = dict(self.snapshot)
        if agent_snapshot is not None:
            snapshot["agent"] = agent_snapshot
        elif self.settings.model_backend == "unconfigured":
            # Defensive only: decide_ingress turns this path into a persisted reject.
            raise DomainError("model_not_configured", 409)
        row = await self.repository.submit(
            tenant,
            RunRequest(conversation_id=conv["external_id"], message=message),
            snapshot,
            self.settings.queue_capacity,
            self.settings.tenant_capacity,
            self.settings.queue_timeout_seconds,
            scope=BusinessScope(
                tenant_id=conv["tenant_id"],
                business_id=conv["business_id"],
                workspace_id=conv["workspace_id"],
            ),
            connection=conn,
        )
        await audit(conn, tenant, actor, "run.submitted", row["id"])
        return {
            "conversation_id": conv["id"],
            "run": {"id": row["id"], "status": row["status"]},
        }

    async def list_routing_decisions(
        self,
        tenant: str,
        cid: UUID,
        *,
        before: str | None,
        limit: int,
        scope: BusinessScope | None = None,
    ) -> dict[str, object]:
        resolved = resolve_scope(tenant, scope)
        if limit < 1 or limit > 200:
            raise DomainError("routing_limit_invalid", 400)
        before_at, before_id = self._decode_routing_cursor(before)
        async with self.engine.connect() as conn:
            items = await list_decisions(
                conn,
                tenant_id=resolved.tenant_id,
                business_id=resolved.business_id,
                workspace_id=resolved.workspace_id,
                conversation_id=cid,
                before_at=before_at,
                before_id=before_id,
                limit=limit,
            )
        next_before = self._encode_routing_cursor(items[-1]) if len(items) == limit else None
        return {"items": items, "next_before": next_before}

    async def routing_summary(
        self,
        tenant: str,
        *,
        since: datetime | None,
        until: datetime | None,
        scope: BusinessScope | None = None,
    ) -> dict[str, object]:
        resolved = resolve_scope(tenant, scope)
        since, until = self._resolve_summary_window(since, until)
        async with self.engine.connect() as conn:
            summary = await summarize_decisions(
                conn,
                tenant_id=resolved.tenant_id,
                business_id=resolved.business_id,
                workspace_id=resolved.workspace_id,
                since=since,
                until=until,
            )
        return {
            **summary,
            "since": since,
            "until": until,
            "routing_write_failures": self.routing_write_failure_count(tenant),
        }

    def routing_write_failure_count(self, tenant: str) -> int:
        return self._routing_write_failures[tenant]

    @staticmethod
    def _encode_routing_cursor(row: dict[str, object]) -> str:
        raw = f"{row['created_at'].isoformat()}|{row['id']}"
        return base64.urlsafe_b64encode(raw.encode()).decode()

    @staticmethod
    def _decode_routing_cursor(before: str | None) -> tuple[datetime | None, UUID | None]:
        if before is None:
            return None, None
        try:
            padded = before + "=" * (-len(before) % 4)
            raw = base64.urlsafe_b64decode(padded.encode()).decode()
            timestamp, cursor_id = raw.split("|", 1)
            before_at = datetime.fromisoformat(timestamp)
            if before_at.tzinfo is None:
                before_at = before_at.replace(tzinfo=UTC)
            return before_at, UUID(cursor_id)
        except (binascii.Error, ValueError, UnicodeDecodeError, TypeError) as exc:
            raise DomainError("routing_cursor_invalid", 400) from exc

    @staticmethod
    def _resolve_summary_window(
        since: datetime | None,
        until: datetime | None,
    ) -> tuple[datetime, datetime]:
        resolved_until = until or datetime.now(UTC)
        resolved_since = since or (resolved_until - timedelta(days=7))
        if resolved_since.tzinfo is None:
            resolved_since = resolved_since.replace(tzinfo=UTC)
        if resolved_until.tzinfo is None:
            resolved_until = resolved_until.replace(tzinfo=UTC)
        if resolved_since >= resolved_until:
            raise DomainError("routing_time_range_invalid", 400)
        if resolved_until - resolved_since > timedelta(days=31):
            raise DomainError("routing_time_range_too_large", 400)
        return resolved_since, resolved_until

    async def propose(self, tenant, cid, run_id, body, scope: BusinessScope | None = None):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved)
        async with self.engine.begin() as c:
            conversation = required(
                await one(
                    c,
                    """SELECT id,customer_id,business_id,workspace_id FROM runtime_conversations
                    WHERE id=:id AND tenant_id=:t AND """
                    + scope_sql,
                    id=cid,
                    t=tenant,
                    **scope_params,
                )
            )
            # The proposal carries the customer link forward so approving it
            # writes tickets.customer_id without a second lookup (FR-5).
            payload = json.dumps(
                {
                    **body.model_dump(),
                    "customer_id": str(conversation["customer_id"])
                    if conversation["customer_id"]
                    else None,
                },
                ensure_ascii=False,
            )
            key = hashlib.sha256((str(run_id) + payload).encode()).hexdigest()
            row = await one(
                c,
                """INSERT INTO pending_actions(
                    id,tenant_id,business_id,workspace_id,conversation_id,kind,payload,dedup_key,expires_at
                )
                VALUES(:id,:t,:business,:workspace,:cid,'create_ticket',
                    CAST(:payload AS jsonb),:key,now()+interval '30 minutes')
                ON CONFLICT(tenant_id,business_id,workspace_id,dedup_key)
                DO UPDATE SET dedup_key=EXCLUDED.dedup_key RETURNING *""",
                id=uuid4(),
                t=tenant,
                business=conversation["business_id"],
                workspace=conversation["workspace_id"],
                cid=cid,
                payload=payload,
                key=key,
            )
            await audit(c, tenant, "runtime", "ticket.proposed", row["id"])
            result = {
                "action_id": str(row["id"]),
                "status": row["status"],
                "requires_confirmation": True,
                "message": "工单仅已拟定，需在工作台确认后才会创建。",
            }
        await self._publish_ticket_event(
            "ticket.proposed",
            tenant,
            row["id"],
            {
                "conversation_id": str(cid),
                "action_id": str(row["id"]),
                "status": row["status"],
                "title": body.title,
            },
            f"ticket.proposed:{tenant}:{row['id']}",
            scope=resolved,
        )
        return result

    async def decide(self, tenant, actor, aid, approve, scope: BusinessScope | None = None):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved)
        event_type = None
        event_payload: dict[str, object] = {}
        async with self.engine.begin() as c:
            ref = required(
                await one(
                    c,
                    """SELECT conversation_id FROM pending_actions
                    WHERE id=:id AND tenant_id=:t AND """
                    + scope_sql,
                    id=aid,
                    t=tenant,
                    **scope_params,
                )
            )
            conv = await one(
                c,
                """SELECT * FROM runtime_conversations
                    WHERE id=:id AND tenant_id=:t AND """
                + scope_sql
                + " FOR UPDATE",
                id=ref["conversation_id"],
                t=tenant,
                **scope_params,
            )
            resolved = BusinessScope(
                tenant_id=tenant,
                business_id=conv["business_id"],
                workspace_id=conv["workspace_id"],
            )
            scope_sql, scope_params = scope_predicate(resolved)
            ticket_scope_sql, _ = scope_predicate(resolved, alias="t")
            action = required(
                await one(
                    c,
                    """SELECT *,expires_at>now() AS valid FROM pending_actions
                    WHERE id=:id AND tenant_id=:t AND """
                    + scope_sql
                    + " FOR UPDATE",
                    id=aid,
                    t=tenant,
                    **scope_params,
                )
            )
            existing = await one(
                c,
                TICKET_VIEW + " WHERE t.action_id=:id AND t.tenant_id=:t AND " + ticket_scope_sql,
                id=aid,
                t=tenant,
                **scope_params,
            )
            if existing:
                return existing
            if action["status"] != "pending":
                raise DomainError("action_already_decided", 409)
            if not action["valid"]:
                raise DomainError("action_expired", 409)
            if await one(
                c,
                """SELECT id FROM runtime_runs
                WHERE conversation_id=:id AND tenant_id=:t AND """
                + scope_sql
                + """
                  AND status IN ('queued','running')""",
                id=conv["id"],
                t=tenant,
                **scope_params,
            ):
                raise DomainError("conversation_busy", 409)
            if not approve:
                await execute(
                    c,
                    "UPDATE pending_actions SET status='rejected' "
                    "WHERE id=:id AND tenant_id=:t AND " + scope_sql,
                    id=aid,
                    t=tenant,
                    **scope_params,
                )
                await audit(c, tenant, actor, "ticket.rejected", aid)
                result = {"id": aid, "status": "rejected"}
                event_type = "ticket.rejected"
                event_payload = {
                    "conversation_id": str(action["conversation_id"]),
                    "action_id": str(aid),
                    "status": "rejected",
                    "actor_id": str(actor),
                }
                event_id = aid
            else:
                proposal = dict(action["payload"])
                # str(UUID) or None; rides in the proposal payload since Phase 2
                # and lands on the VARCHAR(100) tickets.customer_id column (FR-5).
                customer_id = proposal.pop("customer_id", None)
                body = TicketProposal.model_validate(proposal)
                kind = await one(
                    c,
                    """INSERT INTO ticket_types(
                        tenant_id,business_id,workspace_id,code,name
                    )
                    VALUES(:t,:business,:workspace,'general','通用工单')
                    ON CONFLICT(tenant_id,business_id,workspace_id,code)
                    DO UPDATE SET code=EXCLUDED.code RETURNING id,enabled""",
                    t=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                )
                if not kind["enabled"]:
                    raise DomainError("ticket_type_disabled", 409)
                await execute(
                    c,
                    """INSERT INTO ticket_type_versions(
                        tenant_id,business_id,workspace_id,type_id,version,
                        name,definition,created_by
                    )
                    VALUES(:t,:business,:workspace,:id,1,'通用工单','{"fields":[]}',:actor)
                    ON CONFLICT DO NOTHING""",
                    t=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                    id=kind["id"],
                    actor=actor,
                )
                await execute(
                    c,
                    """UPDATE ticket_types SET published_version=1
                    WHERE id=:id AND tenant_id=:t
                      AND business_id=:business AND workspace_id=:workspace
                      AND published_version IS NULL""",
                    id=kind["id"],
                    t=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                )
                tid = uuid4()
                await execute(
                    c,
                    """INSERT INTO tickets(
                        id,tenant_id,business_id,workspace_id,conversation_id,action_id,
                        title,ticket_no,type_id,type_version,created_by,customer_id
                    )
                    VALUES(
                        :id,:t,:business,:workspace,:cid,:aid,:title,:number,
                        :kind,1,:actor,:customer
                    )""",
                    id=tid,
                    t=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                    cid=conv["id"],
                    aid=aid,
                    title=body.title,
                    number="TK-" + tid.hex,
                    kind=kind["id"],
                    actor=actor,
                    customer=customer_id,
                )
                await execute(
                    c,
                    """INSERT INTO tickets_detail(
                        ticket_id,tenant_id,business_id,workspace_id,description
                    ) VALUES(:id,:t,:business,:workspace,:description)""",
                    id=tid,
                    t=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                    description=body.description,
                )
                await execute(
                    c,
                    """INSERT INTO ticket_process_log(
                        tenant_id,business_id,workspace_id,ticket_id,
                        actor_type,actor_id,action_type,content
                    )
                    VALUES(:t,:business,:workspace,:id,'staff',:actor,'created',:title)""",
                    t=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                    id=tid,
                    actor=actor,
                    title=body.title,
                )
                row = required(
                    await one(
                        c,
                        TICKET_VIEW + " WHERE t.id=:id AND t.tenant_id=:t AND " + ticket_scope_sql,
                        id=tid,
                        t=tenant,
                        **scope_params,
                    )
                )
                await execute(
                    c,
                    "UPDATE pending_actions SET status='confirmed' "
                    "WHERE id=:id AND tenant_id=:t AND " + scope_sql,
                    id=aid,
                    t=tenant,
                    **scope_params,
                )
                content = f"工单 {row['id']} 已创建：{body.title}"
                await add_message(c, conv["id"], "system", content)
                history = (
                    (
                        [*conv["history"], {"role": "assistant", "content": content}][
                            -self.settings.history_turns * 2 :
                        ]
                    )
                    if self.settings.history_turns
                    else []
                )
                await execute(
                    c,
                    "UPDATE runtime_conversations SET history=CAST(:h AS jsonb) "
                    "WHERE id=:id AND tenant_id=:t AND " + scope_sql,
                    id=conv["id"],
                    t=tenant,
                    **scope_params,
                    h=json.dumps(history),
                )
                await audit(c, tenant, actor, "ticket.created", row["id"], action_id=str(aid))
                # Phase 3 event memory: dispatch inside this transaction so the
                # event task can never reference an uncommitted ticket. Gated on
                # the write-side kill switch and the customer link (R6/R10).
                if self.settings.memory_event_enabled and customer_id:
                    await enqueue_event_task(c, tenant, tid, "created")
                result = row
                event_type = "ticket.created"
                event_payload = {
                    "conversation_id": str(conv["id"]),
                    "action_id": str(aid),
                    "ticket_id": str(tid),
                    "ticket_no": row["ticket_no"],
                    "title": body.title,
                    "status": row["status"],
                    "actor_id": str(actor),
                }
                event_id = tid
        if event_type is not None:
            await self._publish_ticket_event(
                event_type,
                tenant,
                event_id,
                event_payload,
                f"{event_type}:{tenant}:{event_id}",
                scope=resolved,
            )
        return result

    async def tickets(self, tenant, scope: BusinessScope | None = None):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="t")
        async with self.engine.connect() as c:
            return await many(
                c,
                TICKET_VIEW
                + " WHERE t.tenant_id=:t AND "
                + scope_sql
                + " ORDER BY t.created_at DESC,t.id DESC LIMIT 100",
                t=tenant,
                **scope_params,
            )

    async def lookup(self, tenant, cid, tid, scope: BusinessScope | None = None):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="t")
        async with self.engine.connect() as c:
            return required(
                await one(
                    c,
                    """SELECT t.id,t.title,d.description,t.status,t.revision,t.updated_at
                    FROM tickets t JOIN tickets_detail d
                      ON d.ticket_id=t.id AND d.tenant_id=t.tenant_id
                     AND d.business_id=t.business_id AND d.workspace_id=t.workspace_id
                    WHERE t.tenant_id=:t AND t.conversation_id=:cid AND t.id=:id AND """
                    + scope_sql,
                    t=tenant,
                    cid=cid,
                    id=tid,
                    **scope_params,
                ),
                "ticket_not_found",
            )

    async def update_ticket(
        self,
        tenant,
        actor,
        tid,
        status,
        note,
        revision,
        is_commitment=False,
        due_at=UNSET,
        scope: BusinessScope | None = None,
    ):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved)
        transitions = {
            "open": {"in_progress", "closed"},
            "in_progress": {"waiting_customer", "resolved", "closed"},
            "waiting_customer": {"in_progress", "closed"},
            "resolved": {"in_progress", "closed"},
            "closed": set(),
        }
        events: list[tuple[str, dict[str, object], str]] = []
        async with self.engine.begin() as c:
            row = required(
                await one(
                    c,
                    "SELECT * FROM tickets WHERE id=:id AND tenant_id=:t AND "
                    + scope_sql
                    + " FOR UPDATE",
                    id=tid,
                    t=tenant,
                    **scope_params,
                )
            )
            resolved = BusinessScope(
                tenant_id=tenant,
                business_id=row["business_id"],
                workspace_id=row["workspace_id"],
            )
            scope_sql, scope_params = scope_predicate(resolved)
            ticket_scope_sql, _ = scope_predicate(resolved, alias="t")
            if row["revision"] != revision:
                raise DomainError("ticket_revision_conflict", 409)
            if status != row["status"] and status not in transitions[row["status"]]:
                raise DomainError("invalid_ticket_transition", 409)
            if row["status"] == "closed":
                raise DomainError("ticket_closed", 409)
            if status != row["status"] and status in {"resolved", "closed"} and not note.strip():
                raise DomainError("ticket_resolution_or_close_reason_required")
            await execute(
                c,
                """UPDATE tickets SET status=:status,revision=revision+1,updated_at=now(),
                resolved_at=CASE WHEN :status='resolved' THEN COALESCE(resolved_at,now())
                    WHEN :status='in_progress' THEN NULL ELSE resolved_at END,
                closed_at=CASE WHEN :status='closed' THEN now() ELSE closed_at END
                WHERE id=:id AND tenant_id=:t AND """
                + scope_sql,
                id=tid,
                t=tenant,
                status=status,
                **scope_params,
            )
            if status == "resolved":
                await execute(
                    c,
                    "UPDATE tickets_detail SET resolution=:note "
                    "WHERE ticket_id=:id AND tenant_id=:t AND " + scope_sql,
                    note=note,
                    id=tid,
                    t=tenant,
                    **scope_params,
                )
            if status != row["status"]:
                await execute(
                    c,
                    """INSERT INTO ticket_process_log(
                        tenant_id,business_id,workspace_id,ticket_id,
                        actor_type,actor_id,action_type,old_status,new_status,content
                    )
                    VALUES(
                        :t,:business,:workspace,:id,'staff',:actor,
                        'status_changed',:old,:new,:note
                    )""",
                    t=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                    id=tid,
                    actor=actor,
                    old=row["status"],
                    new=status,
                    note=note,
                )
            # Phase 4 (R12): operators may set or clear due_at; the built-in
            # complaint-risk rule scans this column. Every change is logged
            # with the field-change action type.
            if due_at is not UNSET and due_at != row["due_at"]:
                await execute(
                    c,
                    "UPDATE tickets SET due_at=:due WHERE id=:id AND tenant_id=:t AND " + scope_sql,
                    due=due_at,
                    id=tid,
                    t=tenant,
                    **scope_params,
                )
                await execute(
                    c,
                    """INSERT INTO ticket_process_log(
                        tenant_id,business_id,workspace_id,ticket_id,
                        actor_type,actor_id,action_type,content
                    )
                    VALUES(:t,:business,:workspace,:id,'staff',:actor,'detail_changed',:content)""",
                    t=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                    id=tid,
                    actor=actor,
                    content=(
                        "设置响应期限 " + due_at.isoformat()
                        if due_at is not None
                        else "清除响应期限"
                    ),
                )
            if note.strip():
                remark = await one(
                    c,
                    """INSERT INTO ticket_process_log(
                        tenant_id,business_id,workspace_id,ticket_id,
                        actor_type,actor_id,action_type,content,is_commitment
                    )
                    VALUES(
                        :t,:business,:workspace,:id,'staff',:actor,
                        'remark',:note,:commitment
                    ) RETURNING id""",
                    t=tenant,
                    business=resolved.business_id,
                    workspace=resolved.workspace_id,
                    id=tid,
                    actor=actor,
                    note=note,
                    commitment=bool(is_commitment),
                )
            result = required(
                await one(
                    c,
                    TICKET_VIEW + " WHERE t.id=:id AND t.tenant_id=:t AND " + ticket_scope_sql,
                    id=tid,
                    t=tenant,
                    **scope_params,
                )
            )
            await audit(c, tenant, actor, "ticket.updated", tid, status=status)
            if status != row["status"]:
                events.append(
                    (
                        "ticket.status_changed",
                        {
                            "ticket_id": str(tid),
                            "old_status": row["status"],
                            "new_status": status,
                            "revision": result["revision"],
                            "actor_id": str(actor),
                            "note": note,
                        },
                        f"status:{result['revision']}",
                    )
                )
            if due_at is not UNSET and due_at != row["due_at"]:
                events.append(
                    (
                        "ticket.due_at_changed",
                        {
                            "ticket_id": str(tid),
                            "due_at": due_at.isoformat() if due_at is not None else None,
                            "revision": result["revision"],
                            "actor_id": str(actor),
                        },
                        f"due-at:{result['revision']}",
                    )
                )
            if is_commitment and note.strip():
                events.append(
                    (
                        "ticket.commitment_added",
                        {
                            "ticket_id": str(tid),
                            "revision": result["revision"],
                            "actor_id": str(actor),
                            "note": note,
                        },
                        f"commitment:{remark['id']}",
                    )
                )
            # Phase 3 event memory: lifecycle transitions and commitment
            # remarks dispatch event_write tasks in this same transaction.
            # Gated on the write-side kill switch and the customer link.
            if self.settings.memory_event_enabled and row["customer_id"]:
                if status != row["status"] and status in {"resolved", "closed"}:
                    await enqueue_event_task(c, tenant, tid, status)
                if is_commitment and note.strip():
                    await enqueue_event_task(c, tenant, tid, "commitment", remark["id"])
        for event_type, payload, suffix in events:
            await self._publish_ticket_event(
                event_type,
                tenant,
                tid,
                payload,
                f"{event_type}:{tenant}:{tid}:{suffix}",
                scope=resolved,
            )
        return result
