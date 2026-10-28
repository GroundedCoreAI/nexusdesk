import json
import logging
from uuid import uuid4

from agent_platform.core_platform.platform_services.integrations.channels.base import (
    CHANNEL_WORK_CHANNEL,
    chunk_text,
)
from agent_platform.core_platform.platform_services.integrations.channels.registry import (
    chunk_size_for,
)
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
    persisted_scope,
    resolve_scope,
    scope_predicate,
)
from agent_platform.extension_contracts import BusinessScope

logger = logging.getLogger(__name__)


async def add_message(c, cid, role, content, run_id=None):
    result = await execute(
        c,
        """INSERT INTO conversation_messages(id,conversation_id,role,content,run_id)
        VALUES(:id,:cid,:role,:content,:run) RETURNING id""",
        id=uuid4(),
        cid=cid,
        role=role,
        content=content,
        run=run_id,
    )
    message_id = result.scalar_one()
    if role != "user":
        targets = await many(
            c,
            """SELECT cc.channel_id,cc.conversation_id,cc.target,ch.provider
            FROM channel_conversations cc
            JOIN channels ch ON ch.id=cc.channel_id
            WHERE cc.conversation_id=:cid AND ch.enabled
                AND ch.provider <> 'generic_webhook'""",
            cid=cid,
        )
        for target in targets:
            parts = chunk_text(content, chunk_size_for(target["provider"]))
            for seq, part in enumerate(parts):
                await execute(
                    c,
                    """INSERT INTO channel_deliveries(
                        id,channel_id,conversation_id,message_id,role,content,target,seq
                    ) VALUES(
                        :delivery_id,:channel_id,:conversation_id,:message_id,:role,:content,
                        CAST(:target AS jsonb),:seq
                    )
                    ON CONFLICT(channel_id,message_id,seq) DO NOTHING""",
                    delivery_id=uuid4(),
                    channel_id=target["channel_id"],
                    conversation_id=target["conversation_id"],
                    message_id=message_id,
                    role=role,
                    content=part,
                    target=json.dumps(target["target"]),
                    seq=seq,
                )
        if targets:
            # Transactional wakeup for the delivery worker; a spurious notify is harmless.
            await execute(
                c, "SELECT pg_notify(:ch, :kind)", ch=CHANNEL_WORK_CHANNEL, kind="delivery"
            )
    await execute(c, "UPDATE runtime_conversations SET updated_at=now() WHERE id=:id", id=cid)
    return message_id


class ConversationService:
    def __init__(self, engine, history_turns=10, memory=None):
        self.engine = engine
        self.history_limit = history_turns * 2
        self.memory = memory

    async def list(self, tenant, limit=50, offset=0, scope: BusinessScope | None = None):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved)
        async with self.engine.connect() as c:
            return await many(
                c,
                """SELECT id,external_id,mode,agent_id,deleted_agent,assigned_to,created_at,updated_at
                FROM runtime_conversations
                WHERE tenant_id=:t AND """
                + scope_sql
                + """
                ORDER BY updated_at DESC LIMIT :lim OFFSET :off""",
                t=tenant,
                **scope_params,
                lim=limit,
                off=offset,
            )

    async def list_paginated(
        self,
        tenant,
        page=1,
        page_size=10,
        agent_id: str | None = None,
        status: str = "all",
        scope: BusinessScope | None = None,
    ):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved)
        page = max(page, 1)
        page_size = max(1, min(page_size, 100))
        where = "tenant_id=:t AND " + scope_sql
        params = {
            "t": tenant,
            **scope_params,
            "lim": page_size,
            "off": (page - 1) * page_size,
        }
        if agent_id:
            where += " AND agent_id=:aid"
            params["aid"] = agent_id
        if status and status != "all":
            where += " AND mode=:status"
            params["status"] = status
        async with self.engine.connect() as c:
            total = await one(
                c,
                "SELECT count(*) AS total FROM runtime_conversations WHERE " + where,
                **{k: v for k, v in params.items() if k not in ("lim", "off")},
            )
            items = await many(
                c,
                """SELECT id,external_id,mode,agent_id,deleted_agent,assigned_to,created_at,updated_at
                FROM runtime_conversations WHERE """
                + where
                + " ORDER BY updated_at DESC,id DESC LIMIT :lim OFFSET :off",
                **params,
            )
            return {
                "items": items,
                "total": total["total"],
                "page": page,
                "page_size": page_size,
            }

    async def agent_counts(
        self, tenant, agent_id: str | None = None, scope: BusinessScope | None = None
    ):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved)
        where = "tenant_id=:t AND " + scope_sql
        params = {
            "t": tenant,
            **scope_params,
        }
        if agent_id:
            where += " AND agent_id=:aid"
            params["aid"] = agent_id
        async with self.engine.connect() as c:
            row = await one(
                c,
                """SELECT
                    count(*)::int AS total,
                    count(*) FILTER (WHERE mode='bot')::int AS bot,
                    count(*) FILTER (WHERE mode='waiting')::int AS waiting,
                    count(*) FILTER (WHERE mode='human')::int AS human,
                    count(*) FILTER (WHERE mode='closed')::int AS closed
                FROM runtime_conversations WHERE """
                + where,
                **params,
            )
            return row

    async def counts_by_agent(self, tenant, scope: BusinessScope | None = None):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, "r")
        async with self.engine.connect() as c:
            rows = await many(
                c,
                """SELECT
                    r.agent_id,
                    COALESCE(a.name, r.agent_id::text) AS name,
                    count(*)::int AS total,
                    count(*) FILTER (WHERE r.mode='bot')::int AS bot,
                    count(*) FILTER (WHERE r.mode='waiting')::int AS waiting,
                    count(*) FILTER (WHERE r.mode='human')::int AS human,
                    count(*) FILTER (WHERE r.mode='closed')::int AS closed
                FROM runtime_conversations r
                LEFT JOIN agents a ON a.id = r.agent_id AND a.tenant_id = r.tenant_id
                    AND a.business_id=r.business_id AND a.workspace_id=r.workspace_id
                WHERE r.tenant_id=:t AND """
                + scope_sql
                + """
                GROUP BY r.agent_id, a.name
                ORDER BY total DESC, r.agent_id""",
                t=tenant,
                **scope_params,
            )
            return {"items": rows, "total": len(rows)}

    async def agent_records(
        self,
        tenant,
        aid,
        source="all",
        q="",
        page=1,
        page_size=12,
        scope: BusinessScope | None = None,
    ):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved)
        where = (
            """tenant_id=:t AND """
            + scope_sql
            + """ AND agent_id=:aid
                   AND (:source='all' OR source=:source)
                   AND (:q='' OR external_id ILIKE :pattern)"""
        )
        params = {
            "t": tenant,
            **scope_params,
            "aid": aid,
            "source": source,
            "q": q,
            "pattern": "%" + q + "%",
        }
        async with self.engine.connect() as c:
            required(
                await one(
                    c,
                    """SELECT id FROM agents
                    WHERE id=:aid AND tenant_id=:t AND """
                    + scope_sql,
                    **{**params, "aid": aid},
                ),
                "agent_not_found",
            )
            total = await one(
                c, "SELECT count(*) AS total FROM runtime_conversations WHERE " + where, **params
            )
            items = await many(
                c,
                """SELECT id,external_id,mode,agent_id,source,created_at,updated_at,
                (SELECT content FROM conversation_messages WHERE conversation_id=runtime_conversations.id
                 ORDER BY seq DESC LIMIT 1) AS last_message
                FROM runtime_conversations WHERE """
                + where
                + " ORDER BY updated_at DESC,id DESC LIMIT :lim OFFSET :off",
                **params,
                lim=page_size,
                off=(page - 1) * page_size,
            )
            return {"items": items, "total": total["total"], "page": page, "page_size": page_size}

    async def history(self, tenant, cid, before=None, limit=50, scope: BusinessScope | None = None):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved)
        async with self.engine.connect() as c:
            required(
                await one(
                    c,
                    """SELECT id FROM runtime_conversations
                    WHERE id=:id AND tenant_id=:t AND """
                    + scope_sql,
                    id=cid,
                    t=tenant,
                    **scope_params,
                )
            )
            rows = await many(
                c,
                """SELECT * FROM conversation_messages WHERE conversation_id=:id
                AND (:before=0 OR seq<:before) ORDER BY seq DESC LIMIT :lim""",
                id=cid,
                before=before or 0,
                lim=limit + 1,
            )
            return {"items": list(reversed(rows[:limit])), "has_more": len(rows) > limit}

    async def create(
        self,
        tenant,
        actor,
        external_id,
        agent_id=None,
        connection=None,
        source="business",
        identity=None,
        scope: BusinessScope | None = None,
    ):
        query_scope = resolve_scope(tenant, scope)
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(query_scope)
        if source not in {"business", "playground"}:
            raise DomainError("invalid_conversation_source", 422)
        if source == "playground" and not agent_id:
            raise DomainError("playground_agent_required", 422)
        async with transaction(self.engine, connection) as c:
            example_agent = False
            if source == "playground":
                agent = required(
                    await one(
                        c,
                        """SELECT published_version,archived FROM agents
                        WHERE id=:id AND tenant_id=:t AND """
                        + scope_sql
                        + " FOR SHARE",
                        id=agent_id,
                        t=tenant,
                        **scope_params,
                    ),
                    "agent_not_found",
                )
                if agent["archived"] or agent["published_version"] is None:
                    raise DomainError("agent_not_available", 409)
            if agent_id:
                agent = required(
                    await one(
                        c,
                        """SELECT id,is_example FROM agents
                        WHERE id=:id AND tenant_id=:t AND """
                        + scope_sql
                        + " FOR KEY SHARE",
                        id=agent_id,
                        t=tenant,
                        **scope_params,
                    ),
                    "agent_not_found",
                )
                example_agent = agent["is_example"]
            # Customer identity resolution (Phase 2, FR-1). Conservative by
            # design: playground conversations and example agents never resolve;
            # any failure leaves customer_id NULL and never blocks creation.
            customer_id = None
            if identity and source != "playground" and not example_agent and self.memory:
                try:
                    async with c.begin_nested():
                        customer_id = await self.memory.resolve_customer(
                            c, tenant, identity["source"], identity["external_key"]
                        )
                except Exception:
                    logger.warning(
                        "Customer identity resolution failed for source=%s; "
                        "conversation proceeds without a customer",
                        identity.get("source"),
                        exc_info=True,
                    )
                    customer_id = None
            row = await one(
                c,
                """INSERT INTO runtime_conversations(
                    id,tenant_id,business_id,workspace_id,external_id,agent_id,source,customer_id
                )
                VALUES(:id,:t,:business,:workspace,:external,:aid,:source,:customer)
                ON CONFLICT(tenant_id,business_id,workspace_id,external_id)
                DO NOTHING RETURNING *""",
                id=uuid4(),
                t=tenant,
                business=resolved.business_id,
                workspace=resolved.workspace_id,
                external=external_id,
                aid=agent_id,
                source=source,
                customer=customer_id,
            )
            if not row:
                raise DomainError("conversation_exists", 409)
            await audit(c, tenant, actor, "conversation.created", row["id"])
            return row

    async def detail(self, tenant, cid, after=0, scope: BusinessScope | None = None):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved)
        async with self.engine.connect() as c:
            row = required(
                await one(
                    c,
                    """SELECT * FROM runtime_conversations
                    WHERE id=:id AND tenant_id=:t AND """
                    + scope_sql,
                    id=cid,
                    t=tenant,
                    **scope_params,
                )
            )
            row["messages"] = await many(
                c,
                (
                    """SELECT * FROM (SELECT * FROM conversation_messages
                WHERE conversation_id=:id AND seq>:after ORDER BY seq DESC LIMIT 200) recent ORDER BY seq"""
                    if after == 0
                    else """SELECT * FROM conversation_messages
                WHERE conversation_id=:id AND seq>:after ORDER BY seq LIMIT 200"""
                ),
                id=cid,
                after=after,
            )
            row["runs"] = await many(
                c,
                """SELECT id,status,output,error_code,created_at,cancel_requested FROM runtime_runs
                WHERE conversation_id=:id AND tenant_id=:t AND """
                + scope_sql
                + """
                ORDER BY created_at DESC LIMIT 20""",
                id=cid,
                t=tenant,
                **scope_params,
            )
            row["actions"] = await many(
                c,
                """SELECT * FROM pending_actions WHERE conversation_id=:id
                AND tenant_id=:t AND """
                + scope_sql
                + """
                ORDER BY created_at DESC LIMIT 30""",
                id=cid,
                t=tenant,
                **scope_params,
            )
            return row

    async def human_reply(
        self,
        tenant,
        actor,
        cid,
        content,
        administrator=False,
        scope: BusinessScope | None = None,
    ):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved)
        async with self.engine.begin() as c:
            row = required(
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
            if row["mode"] != "human":
                raise DomainError("conversation_not_claimed", 409)
            if not administrator and row["assigned_to"] != actor:
                raise DomainError("conversation_assignee_required", 403)
            await add_message(c, cid, "human", content)
            await execute(
                c,
                """UPDATE runtime_conversations SET history=CAST(:msg AS jsonb)
                WHERE id=:id""",
                id=cid,
                msg=json.dumps(
                    (
                        [*row["history"], {"role": "assistant", "content": content}][
                            -self.history_limit :
                        ]
                    )
                    if self.history_limit
                    else []
                ),
            )
            await audit(c, tenant, actor, "conversation.human_reply", cid)
            return {"sent": True}

    async def transition(
        self, tenant, actor, cid, operation, revision, scope: BusinessScope | None = None
    ):
        resolved = resolve_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved)
        async with self.engine.begin() as c:
            row = required(
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
            if row.get("deleted_agent"):
                raise DomainError("conversation_agent_deleted", 409)
            if row["revision"] != revision:
                raise DomainError("conversation_revision_conflict", 409)
            if (
                operation == "close"
                and row["mode"] != "bot"
                or operation == "reopen"
                and row["mode"] != "closed"
            ):
                raise DomainError("invalid_conversation_transition", 409)
            if await one(
                c,
                """SELECT id FROM runtime_runs
                WHERE conversation_id=:id AND tenant_id=:t AND """
                + scope_sql
                + """
                  AND status IN ('queued','running')""",
                id=cid,
                t=tenant,
                **scope_params,
            ):
                raise DomainError("conversation_busy", 409)
            updated = await one(
                c,
                """UPDATE runtime_conversations
                SET mode=:mode,updated_at=now()
                WHERE id=:id AND tenant_id=:t AND """
                + scope_sql
                + """
                RETURNING *""",
                id=cid,
                t=tenant,
                **scope_params,
                mode="closed" if operation == "close" else "bot",
            )
            await add_message(
                c, cid, "system", "会话已关闭。" if operation == "close" else "会话已重新打开。"
            )
            await audit(c, tenant, actor, "conversation." + operation, cid)
            return updated
