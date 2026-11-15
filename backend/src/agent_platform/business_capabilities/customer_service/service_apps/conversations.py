"""Application-scoped read model for the customer-visible business ledger.

Runtime messages and runs remain available as diagnostics, but they are no
longer the source of the customer conversation timeline.  Only ``kind=customer``
rows are returned from this module.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    many,
    one,
    required,
)
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    persisted_scope,
    scope_predicate,
)
from agent_platform.extension_contracts import BusinessScope

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100
MAX_DETAIL_MESSAGES = 500
ANSWER_STATUSES = {
    "completed",
    "failed",
    "queued",
    "running",
    "cancelled",
    "bot",
    "waiting",
    "human",
    "closed",
}


def _page_args(page: int, page_size: int) -> tuple[int, int]:
    if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise DomainError("service_application_conversations_page_invalid", 422)
    return page, page_size


def _channel_id(value: UUID | str | None) -> str:
    if value is None or value == "":
        return ""
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise DomainError(
            "service_application_conversation_channel_id_invalid",
            422,
        ) from None


def _uuid_or_not_found(value: UUID | str, error: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise DomainError(error, 404) from None


def _duration_ms(started: Any, finished: Any) -> int | None:
    if started is None or finished is None:
        return None
    return max(0, int((finished - started).total_seconds() * 1000))


def _public_item(row: dict[str, Any]) -> dict[str, Any]:
    question = row.get("question")
    answer = row.get("answer")
    title = question or row.get("external_conversation_id")
    return {
        "id": str(row["id"]),
        "question": str(question or ""),
        "answer": str(answer or ""),
        "status": str(row.get("answer_status") or "unknown"),
        "mode": str(row.get("business_status") or "open"),
        "source": str(row.get("provider") or "unknown"),
        "kind": "customer",
        "channel_id": str(row["channel_id"]) if row.get("channel_id") else "",
        "channel_name": str(row.get("channel_name") or ""),
        "account": str(row.get("external_user_id") or ""),
        "user_name": row.get("user_name"),
        "conversation_title": str(title or ""),
        "message_count": int(row.get("message_count") or 0),
        "turn_count": int(row.get("turn_count") or 0),
        "last_turn_status": row.get("last_turn_status"),
        "run_id": str(row["run_id"]) if row.get("run_id") else None,
        "application_version": row.get("application_version"),
        "agent_version": row.get("agent_version"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "feedback_type": None,
        "feedback_status": "none",
        "qa_saved": False,
    }


class ApplicationConversationService:
    """Application-scoped read service for persisted customer conversations."""

    def __init__(self, engine: object) -> None:
        self.engine = engine

    @staticmethod
    def _base_sql(scope_sql: str) -> str:
        return f"""
SELECT
    c.id,
    c.external_conversation_id,
    c.status AS business_status,
    c.channel_id,
    c.external_user_id,
    c.user_name,
    c.created_at,
    c.updated_at,
    ch.name AS channel_name,
    ch.provider,
    COALESCE(latest_turn.status, NULL) AS last_turn_status,
    COALESCE(latest_turn.runtime_run_id, NULL) AS run_id,
    COALESCE(latest_turn.application_version, NULL) AS application_version,
    c.agent_version,
    (
        SELECT count(*)::int
        FROM service_application_turns t
        WHERE t.tenant_id=c.tenant_id
          AND t.business_id=c.business_id
          AND t.workspace_id=c.workspace_id
          AND t.conversation_id=c.id
    ) AS turn_count,
    (
        SELECT m.content
        FROM service_application_messages m
        WHERE m.tenant_id=c.tenant_id
          AND m.business_id=c.business_id
          AND m.workspace_id=c.workspace_id
          AND m.conversation_id=c.id
          AND m.role='customer'
        ORDER BY m.seq
        LIMIT 1
    ) AS question,
    (
        SELECT m.content
        FROM service_application_messages m
        WHERE m.tenant_id=c.tenant_id
          AND m.business_id=c.business_id
          AND m.workspace_id=c.workspace_id
          AND m.conversation_id=c.id
          AND m.role IN ('assistant', 'human')
        ORDER BY m.seq DESC
        LIMIT 1
    ) AS answer,
    (
        SELECT count(*)::int
        FROM service_application_messages m
        WHERE m.tenant_id=c.tenant_id
          AND m.business_id=c.business_id
          AND m.workspace_id=c.workspace_id
          AND m.conversation_id=c.id
    ) AS message_count,
    CASE
        WHEN c.status IN ('waiting', 'human', 'closed') THEN c.status
        WHEN latest_turn.status IS NOT NULL THEN latest_turn.status
        ELSE 'bot'
    END AS answer_status
FROM service_application_conversations c
LEFT JOIN channels ch
  ON ch.id=c.channel_id
 AND ch.tenant_id=c.tenant_id
 AND ch.business_id=c.business_id
 AND ch.workspace_id=c.workspace_id
 AND ch.application_id=c.application_id
LEFT JOIN LATERAL (
    SELECT t.status,t.runtime_run_id,t.application_version
    FROM service_application_turns t
    WHERE t.tenant_id=c.tenant_id
      AND t.business_id=c.business_id
      AND t.workspace_id=c.workspace_id
      AND t.conversation_id=c.id
    ORDER BY t.created_at DESC, t.id DESC
    LIMIT 1
) latest_turn ON TRUE
WHERE c.tenant_id=:tenant
  AND {scope_sql}
  AND c.application_id=:application
  AND c.kind='customer'
"""

    async def _application(
        self,
        connection: Any,
        tenant: str,
        key: str,
        scope: BusinessScope,
    ) -> dict[str, Any]:
        scope_sql, scope_params = scope_predicate(scope, alias="a")
        row = await one(
            connection,
            f"""
SELECT a.id,a.application_key,a.name
FROM service_applications a
WHERE a.tenant_id=:tenant
  AND {scope_sql}
  AND a.application_key=:key
  AND NOT a.archived
""",
            tenant=tenant,
            key=key,
            **scope_params,
        )
        return required(row, "service_application_not_found")

    async def list(
        self,
        tenant: str,
        key: str,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        q: str = "",
        channel_id: UUID | str | None = None,
        status: str = "all",
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        page, page_size = _page_args(page, page_size)
        if status != "all" and status not in ANSWER_STATUSES:
            raise DomainError("service_application_conversations_status_invalid", 422)
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="c")
        selected_channel = _channel_id(channel_id)
        filters = """
WHERE (
    :q=''
    OR COALESCE(question,'') ILIKE :pattern
    OR COALESCE(answer,'') ILIKE :pattern
    OR COALESCE(user_name,'') ILIKE :pattern
    OR COALESCE(external_user_id,'') ILIKE :pattern
    OR COALESCE(channel_name,'') ILIKE :pattern
    OR COALESCE(external_conversation_id,'') ILIKE :pattern
)
  AND (:channel_id='' OR channel_id::text=:channel_id)
  AND (:status='all' OR answer_status=:status)
"""
        base = self._base_sql(scope_sql)
        async with self.engine.connect() as connection:
            application = await self._application(connection, tenant, key, resolved)
            total_row = await one(
                connection,
                f"SELECT count(*)::int AS total FROM ({base}) c {filters}",
                tenant=tenant,
                application=application["id"],
                q=q,
                pattern=f"%{q}%",
                channel_id=selected_channel,
                status=status,
                **scope_params,
            )
            rows = await many(
                connection,
                f"""
SELECT *
FROM ({base}) c
{filters}
ORDER BY updated_at DESC,id DESC
LIMIT :limit OFFSET :offset
""",
                tenant=tenant,
                application=application["id"],
                q=q,
                pattern=f"%{q}%",
                channel_id=selected_channel,
                status=status,
                limit=page_size,
                offset=(page - 1) * page_size,
                **scope_params,
            )
        total = int((total_row or {}).get("total", 0))
        return {
            "items": [_public_item(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    async def get(
        self,
        tenant: str,
        key: str,
        conversation_id: UUID | str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        try:
            selected_id = str(UUID(str(conversation_id)))
        except (TypeError, ValueError, AttributeError):
            raise DomainError(
                "service_application_conversation_not_found",
                404,
            ) from None
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="c")
        base = self._base_sql(scope_sql)
        async with self.engine.connect() as connection:
            application = await self._application(connection, tenant, key, resolved)
            row = await one(
                connection,
                f"""
SELECT *
FROM ({base}) c
WHERE c.id=:conversation_id
""",
                tenant=tenant,
                application=application["id"],
                conversation_id=selected_id,
                **scope_params,
            )
            conversation = required(
                row,
                "service_application_conversation_not_found",
            )
            messages = await many(
                connection,
                """
SELECT id,seq,role,content,content_type,payload,runtime_message_id,created_at,
       NULL::uuid AS run_id
FROM (
    SELECT id,seq,role,content,content_type,payload,runtime_message_id,created_at
    FROM service_application_messages
    WHERE conversation_id=:conversation_id
      AND tenant_id=:tenant
      AND business_id=:scope_business
      AND workspace_id=:scope_workspace
    ORDER BY seq DESC
    LIMIT :limit
) recent
ORDER BY seq
""",
                conversation_id=selected_id,
                tenant=tenant,
                limit=MAX_DETAIL_MESSAGES + 1,
                **scope_params,
            )
            turns = await many(
                connection,
                """
SELECT id,status,customer_message_id,assistant_message_id,
       runtime_conversation_id,runtime_run_id,application_version,
       agent_id,agent_version,error_code,created_at,finished_at
FROM service_application_turns
WHERE conversation_id=:conversation_id
  AND tenant_id=:tenant
  AND business_id=:scope_business
  AND workspace_id=:scope_workspace
ORDER BY created_at,id
""",
                conversation_id=selected_id,
                tenant=tenant,
                **scope_params,
            )
            run_scope_sql, run_scope_params = scope_predicate(resolved, alias="rr")
            run_query_params = {**scope_params, **run_scope_params}
            runs = await many(
                connection,
                f"""
SELECT rr.id,rr.status,rr.output,rr.error_code,rr.cancel_requested,
       rr.created_at,rr.started_at,rr.finished_at
FROM runtime_runs rr
JOIN service_application_turns t ON t.runtime_run_id=rr.id
WHERE t.conversation_id=:conversation_id
  AND t.tenant_id=:tenant
  AND t.business_id=:scope_business
  AND t.workspace_id=:scope_workspace
  AND rr.tenant_id=:tenant
  AND {run_scope_sql}
ORDER BY rr.created_at DESC, rr.id DESC
LIMIT 20
""",
                conversation_id=selected_id,
                tenant=tenant,
                **run_query_params,
            )
        truncated = len(messages) > MAX_DETAIL_MESSAGES
        result = _public_item(conversation)
        result.update(
            {
                "messages": messages[-MAX_DETAIL_MESSAGES:],
                "turns": turns,
                "runs": runs,
                "messages_truncated": truncated,
            }
        )
        return result

    async def turn_diagnostics(
        self,
        tenant: str,
        key: str,
        conversation_id: UUID | str,
        turn_id: UUID | str,
        *,
        scope: BusinessScope | None = None,
    ) -> dict[str, Any]:
        """Rebuild one customer turn's run trace on demand.

        The conversation detail endpoint stays a light read model; the trace is
        only paid for when an operator opens it. ``runtime_events`` already
        records every stage, so no new instrumentation is needed — the same
        builder the debug preview uses produces an identical payload here.

        Turns that never reached the runtime (queued and then cancelled, or a
        closed conversation) have no run at all and say so explicitly instead
        of returning an empty trace that looks like a broken run.
        """

        selected_conversation = _uuid_or_not_found(
            conversation_id,
            "service_application_conversation_not_found",
        )
        selected_turn = _uuid_or_not_found(
            turn_id,
            "service_application_turn_not_found",
        )
        # Imported here because the application service owns the trace builder
        # and imports this read model lazily in return.
        from .service import ServiceApplicationService, _preview_status
        resolved = persisted_scope(tenant, scope)
        scope_sql, scope_params = scope_predicate(resolved, alias="t")
        async with self.engine.connect() as connection:
            application = await self._application(connection, tenant, key, resolved)
            row = await one(
                connection,
                f"""
SELECT t.id, t.status AS turn_status, t.error_code,
       t.application_version, t.agent_version, t.created_at,
       t.runtime_run_id, t.runtime_conversation_id,
       bc.id AS ledger_conversation_id,
       m.content AS input,
       rr.status AS run_status, rr.error_code AS run_error,
       rr.output AS reply, rr.started_at, rr.finished_at,
       rr.config AS run_config
FROM service_application_turns t
JOIN service_application_conversations bc
  ON bc.tenant_id=t.tenant_id
 AND bc.business_id=t.business_id
 AND bc.workspace_id=t.workspace_id
 AND bc.id=t.conversation_id
LEFT JOIN service_application_messages m
  ON m.tenant_id=t.tenant_id
 AND m.business_id=t.business_id
 AND m.workspace_id=t.workspace_id
 AND m.conversation_id=t.conversation_id
 AND m.id=t.customer_message_id
LEFT JOIN runtime_runs rr ON rr.id=t.runtime_run_id
WHERE t.tenant_id=:tenant
  AND {scope_sql}
  AND bc.application_id=CAST(:application AS uuid)
  AND bc.kind='customer'
  AND t.conversation_id=CAST(:conversation_id AS uuid)
  AND t.id=CAST(:turn_id AS uuid)
""",
                tenant=tenant,
                application=str(application["id"]),
                conversation_id=selected_conversation,
                turn_id=selected_turn,
                **scope_params,
            )
            row = required(row, "service_application_turn_not_found")
            run_id = str(row["runtime_run_id"]) if row.get("runtime_run_id") else None
            events: list[dict[str, Any]] = []
            gateway: list[dict[str, Any]] = []
            snapshot: dict[str, Any] | None = None
            if run_id:
                events = await many(
                    connection,
                    """
SELECT seq,type,data,created_at FROM runtime_events
WHERE run_id=CAST(:run_id AS uuid)
ORDER BY seq
""",
                    run_id=run_id,
                )
                if events:
                    gateway = await ServiceApplicationService._gateway_meta(
                        connection,
                        tenant,
                        run_id,
                        events,
                    )
                else:
                    # Published runs also leave a trace snapshot behind, so a
                    # pruned event log still degrades to something readable.
                    stored = await one(
                        connection,
                        """
SELECT trace FROM service_application_traces
WHERE tenant_id=:tenant AND run_id=CAST(:run_id AS uuid)
ORDER BY created_at DESC
LIMIT 1
""",
                        tenant=tenant,
                        run_id=run_id,
                    )
                    snapshot = (stored or {}).get("trace")

        trace: dict[str, Any] = {}
        skills: list[dict[str, Any]] = []
        available = False
        reason: str | None = None
        degraded = False
        if run_id is None:
            reason = "not_dispatched"
        elif events:
            trace, skills = ServiceApplicationService._preview_history_trace(
                row,
                events,
                gateway,
            )
            available = True
        elif snapshot:
            trace = snapshot
            available = True
            degraded = True
        else:
            reason = "run_events_missing"
        return {
            "available": available,
            "reason": reason,
            "degraded": degraded,
            "turn_id": str(row["id"]),
            "run_id": run_id,
            "status": _preview_status(row),
            "error_code": row.get("run_error") or row.get("error_code"),
            "application_version": row.get("application_version"),
            "agent_version": row.get("agent_version"),
            "input": str(row.get("input") or ""),
            "reply": str(row.get("reply") or ""),
            "duration_ms": _duration_ms(row.get("started_at"), row.get("finished_at")),
            "created_at": row.get("created_at"),
            "skills": skills,
            "trace": trace,
        }
