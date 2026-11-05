"""Business context aggregation for the human workbench.

The aggregator only reads, trims and projects.  It never re-derives business
facts and never branches on industry: everything it returns already exists in
the conversation, the routing decisions, the scenario traces or the pending
actions written by the service runtime.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from agent_platform.core_platform.platform_services.persistence.store import many, one
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    scope_predicate,
)
from agent_platform.extension_contracts import BusinessScope

TRACE_LIMIT = 10
ROUTING_LIMIT = 20
RUN_LIMIT = 10
ACTION_LIMIT = 20

# The workbench speaks to a human operator; a fact projected only for the
# customer or for the model must not leak into the operator view.
_OPERATOR_AUDIENCES = ("human", "agent")


def _operator_facts(facts: Any) -> list[dict[str, Any]]:
    if not isinstance(facts, list):
        return []
    visible: list[dict[str, Any]] = []
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        audiences = fact.get("audiences")
        if audiences and not set(audiences) & set(_OPERATOR_AUDIENCES):
            continue
        # ``source`` and other provider-shaped keys stay server-side.
        visible.append(
            {
                "key": fact.get("key"),
                "label": fact.get("label") or fact.get("key"),
                "value": fact.get("value"),
                "format": fact.get("format") or "text",
                "masked": bool(fact.get("masked")),
            }
        )
    return visible


def _operator_decisions(decisions: Any) -> list[dict[str, Any]]:
    if not isinstance(decisions, list):
        return []
    projected: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        options = decision.get("options")
        projected.append(
            {
                "key": decision.get("key"),
                "kind": decision.get("kind"),
                "label": decision.get("label") or decision.get("key"),
                "required": bool(decision.get("required")),
                "confirm": bool(decision.get("confirm")),
                # ``selected`` is what the customer already chose; everything
                # else is still open, which is what the operator must confirm.
                "state": "selected" if decision.get("selected") else "pending",
                "options": [
                    {"value": option.get("value"), "label": option.get("label")}
                    for option in (options if isinstance(options, list) else [])
                    if isinstance(option, dict)
                ],
            }
        )
    return projected


def _safe_object_ref(object_ref: Any) -> dict[str, Any] | None:
    if not isinstance(object_ref, dict) or not object_ref.get("id"):
        return None
    return {
        "type": object_ref.get("type"),
        "id": object_ref.get("id"),
        "status": object_ref.get("status") or "",
    }


def _safe_application(application: Any) -> dict[str, Any] | None:
    if not isinstance(application, dict) or not application.get("key"):
        return None
    return {
        "key": application.get("key"),
        "name": application.get("name"),
        "version": application.get("version"),
        "source": application.get("source"),
    }


def _action_summary(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    title = payload.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    description = payload.get("description")
    if isinstance(description, str):
        return description.strip()[:120]
    return ""


def _trace_projection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "scenario_key": row["scenario_key"],
        "scenario_version": row.get("scenario_version"),
        "simulation": row.get("simulation"),
        "entry": row.get("entry"),
        "handler_type": row.get("handler_type"),
        "outcome": row.get("outcome"),
        "reason_code": row.get("reason_code"),
        "result_summary": row.get("result_summary") or "",
        "message_excerpt": row.get("message_excerpt") or "",
        "created_at": row.get("created_at"),
    }


async def build_handoff_context(
    connection: Any,
    tenant: str,
    scope: BusinessScope,
    handoff: dict[str, Any],
) -> dict[str, Any]:
    """Return the operator-facing context for one handoff.

    ``handoff`` must already have been loaded with tenant/scope filtering by the
    caller, so a missing conversation here means the row was tampered with.
    """

    conversation_id: UUID = handoff["conversation_id"]
    scope_sql, scope_params = scope_predicate(scope)

    conversation = await one(
        connection,
        f"""SELECT id,external_id,mode,source,assigned_to,customer_id,summary,
                   created_at,updated_at
        FROM runtime_conversations
        WHERE id=:cid AND tenant_id=:tenant AND {scope_sql}""",
        cid=conversation_id,
        tenant=tenant,
        **scope_params,
    )

    traces = await many(
        connection,
        f"""SELECT id,conversation_id,scenario_key,scenario_version,simulation,entry,
                   message_length,message_excerpt,object_ref,facts,decisions,
                   handler_type,outcome,reason_code,result_summary,trace,created_at
        FROM service_scenario_traces
        WHERE conversation_id=:cid AND tenant_id=:tenant AND {scope_sql}
        ORDER BY created_at DESC,id DESC
        LIMIT :limit""",
        cid=conversation_id,
        tenant=tenant,
        limit=TRACE_LIMIT,
        **scope_params,
    )

    routing = await many(
        connection,
        f"""SELECT disposition,action,execution_tier,reason_code,matched_rule_id,
                   decider,created_at
        FROM routing_decisions
        WHERE conversation_id=:cid AND tenant_id=:tenant AND {scope_sql}
        ORDER BY created_at DESC,id DESC
        LIMIT :limit""",
        cid=conversation_id,
        tenant=tenant,
        limit=ROUTING_LIMIT,
        **scope_params,
    )

    actions = await many(
        connection,
        f"""SELECT id,kind,payload,status,expires_at,created_at,
                   (status='pending' AND expires_at>now()) AS valid
        FROM pending_actions
        WHERE conversation_id=:cid AND tenant_id=:tenant AND {scope_sql}
        ORDER BY created_at DESC,id DESC
        LIMIT :limit""",
        cid=conversation_id,
        tenant=tenant,
        limit=ACTION_LIMIT,
        **scope_params,
    )

    runs = await many(
        connection,
        f"""SELECT id,status,error_code,cancel_requested,created_at,finished_at
        FROM runtime_runs
        WHERE conversation_id=:cid AND tenant_id=:tenant AND {scope_sql}
        ORDER BY created_at DESC,id DESC
        LIMIT :limit""",
        cid=conversation_id,
        tenant=tenant,
        limit=RUN_LIMIT,
        **scope_params,
    )

    latest = next(
        (row for row in traces if not row.get("simulation")),
        traces[0] if traces else None,
    )
    trace_body = (latest or {}).get("trace") or {}
    application = _safe_application((trace_body or {}).get("application"))

    scenario = None
    if latest is not None:
        scenario = {
            "key": latest["scenario_key"],
            "name": (trace_body or {}).get("scenario_name") or latest["scenario_key"],
            "version": latest.get("scenario_version"),
            "status": (trace_body or {}).get("scenario_status"),
            "resolved_by": (trace_body or {}).get("resolved_by"),
            "handler_type": latest.get("handler_type"),
            "outcome": latest.get("outcome"),
            "reason_code": latest.get("reason_code"),
        }

    return {
        "handoff": {
            "id": str(handoff["id"]),
            "conversation_id": str(conversation_id),
            "status": handoff["status"],
            "assignee": handoff.get("assignee"),
            "reason": handoff.get("reason"),
            "summary": handoff.get("summary") or "",
            "revision": handoff.get("revision"),
            "created_at": handoff.get("created_at"),
            "closed_at": handoff.get("closed_at"),
        },
        "conversation": (
            {
                "id": str(conversation["id"]),
                "external_id": conversation["external_id"],
                "mode": conversation.get("mode"),
                "source": conversation.get("source"),
                "assigned_to": conversation.get("assigned_to"),
                "has_customer": bool(conversation.get("customer_id")),
                "summary": conversation.get("summary") or "",
                "created_at": conversation.get("created_at"),
                "updated_at": conversation.get("updated_at"),
            }
            if conversation
            else None
        ),
        # Everything below is only meaningful once a trace is bound to the
        # conversation; empty lists are the honest answer before that.
        "application": application,
        "scenario": scenario,
        "object": _safe_object_ref((trace_body or {}).get("object_ref")),
        "facts": _operator_facts((trace_body or {}).get("facts")),
        "decisions": _operator_decisions((trace_body or {}).get("decisions")),
        "actions": [
            {
                "id": str(row["id"]),
                "kind": row["kind"],
                "status": row["status"],
                "valid": bool(row.get("valid")),
                "summary": _action_summary(row.get("payload")),
                "created_at": row.get("created_at"),
                "expires_at": row.get("expires_at"),
            }
            for row in actions
        ],
        "runs": [
            {
                "id": str(row["id"]),
                "status": row["status"],
                "error_code": row.get("error_code"),
                "cancel_requested": bool(row.get("cancel_requested")),
                "created_at": row.get("created_at"),
                "finished_at": row.get("finished_at"),
            }
            for row in runs
        ],
        "routing": [
            {
                "disposition": row["disposition"],
                "action": row["action"],
                "execution_tier": row.get("execution_tier"),
                "reason_code": row["reason_code"],
                "matched_rule_id": row.get("matched_rule_id"),
                "decider": row.get("decider"),
                "created_at": row.get("created_at"),
            }
            for row in routing
        ],
        "traces": [_trace_projection(row) for row in traces],
    }


__all__ = ["build_handoff_context"]
