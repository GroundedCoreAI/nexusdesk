"""Persistence helpers for routing decisions."""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from agent_platform.core_platform.platform_services.persistence.store import many

from .decision import RoutingDecision

logger = logging.getLogger(__name__)

MAX_LIST_LIMIT = 200

_INSERT_SQL = """
INSERT INTO routing_decisions (
    tenant_id,
    business_id,
    workspace_id,
    conversation_id,
    request_id,
    disposition,
    execution_tier,
    action,
    reason_code,
    matched_rule_id,
    decider,
    message_length
) VALUES (
    :tenant_id,
    :business_id,
    :workspace_id,
    :conversation_id,
    :request_id,
    :disposition,
    :execution_tier,
    :action,
    :reason_code,
    :matched_rule_id,
    :decider,
    :message_length
)
"""

_LIST_SELECT = """
SELECT
    id,
    tenant_id,
    business_id,
    workspace_id,
    conversation_id,
    request_id,
    disposition,
    execution_tier,
    action,
    reason_code,
    matched_rule_id,
    decider,
    message_length,
    created_at
FROM routing_decisions
"""


def _scope_clause(workspace_id: str | None) -> str:
    clause = """WHERE tenant_id = :tenant_id
  AND business_id = :business_id"""
    if workspace_id is not None:
        clause += "\n  AND workspace_id = :workspace_id"
    return clause


async def record(conn: Any, decision: RoutingDecision) -> bool:
    """Insert one decision inside a SAVEPOINT.

    Observability writes must not poison the surrounding transaction. A
    statement-level failure is rolled back to the savepoint and reported as a
    warning; a broken connection still follows the existing transaction error
    path.
    """

    try:
        async with conn.begin_nested():
            await conn.execute(
                text(_INSERT_SQL),
                {
                    "tenant_id": decision.tenant_id,
                    "business_id": decision.business_id,
                    "workspace_id": decision.workspace_id,
                    "conversation_id": decision.conversation_id,
                    "request_id": decision.request_id,
                    "disposition": decision.disposition,
                    "execution_tier": decision.execution_tier,
                    "action": decision.action,
                    "reason_code": decision.reason_code,
                    "matched_rule_id": decision.matched_rule_id,
                    "decider": decision.decider,
                    "message_length": decision.message_length,
                },
            )
        return True
    except Exception:
        logger.warning("routing decision not recorded", exc_info=True)
        return False


async def list_decisions(
    conn: Any,
    *,
    tenant_id: str,
    business_id: str,
    workspace_id: str | None,
    conversation_id: UUID,
    before_at: datetime | None = None,
    before_id: UUID | None = None,
    limit: int = 50,
) -> list[dict]:
    """List one conversation's decisions using a descending compound cursor."""

    if (before_at is None) != (before_id is None):
        raise ValueError("before_at and before_id must be provided together")

    safe_limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    sql = (
        _LIST_SELECT
        + "\n"
        + _scope_clause(workspace_id)
        + "\n  AND conversation_id = :conversation_id"
    )
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "business_id": business_id,
        "conversation_id": conversation_id,
        "limit": safe_limit,
    }
    if workspace_id is not None:
        params["workspace_id"] = workspace_id
    if before_at is not None and before_id is not None:
        sql += """
  AND (created_at, id) < (
      CAST(:before_at AS timestamptz),
      CAST(:before_id AS uuid)
  )
"""
        params["before_at"] = before_at
        params["before_id"] = before_id
    sql += "\nORDER BY created_at DESC, id DESC\nLIMIT :limit"
    return await many(conn, sql, **params)


async def summarize_decisions(
    conn: Any,
    *,
    tenant_id: str,
    business_id: str,
    workspace_id: str | None,
    since: datetime,
    until: datetime,
) -> dict[str, list[dict]]:
    """Aggregate decisions by disposition and reason in a half-open window."""

    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "business_id": business_id,
        "since": since,
        "until": until,
    }
    if workspace_id is not None:
        params["workspace_id"] = workspace_id
    scope = _scope_clause(workspace_id)
    by_disposition = await many(
        conn,
        f"""
SELECT disposition AS key, count(*)::int AS count
FROM routing_decisions
{scope}
  AND created_at >= CAST(:since AS timestamptz)
  AND created_at < CAST(:until AS timestamptz)
GROUP BY disposition
ORDER BY count DESC, disposition ASC
""",
        **params,
    )
    by_reason_code = await many(
        conn,
        f"""
SELECT reason_code AS key, count(*)::int AS count
FROM routing_decisions
{scope}
  AND created_at >= CAST(:since AS timestamptz)
  AND created_at < CAST(:until AS timestamptz)
GROUP BY reason_code
ORDER BY count DESC, reason_code ASC
""",
        **params,
    )
    return {
        "by_disposition": by_disposition,
        "by_reason_code": by_reason_code,
    }


__all__ = ["list_decisions", "record", "summarize_decisions"]
