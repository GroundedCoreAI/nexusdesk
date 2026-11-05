"""Pure ingress decision construction and the routed ingress result."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from agent_platform.business_capabilities.agent_config.memory import resolve_agent_memory

from .rules import match_handoff
from .settings import CustomerServiceRoutingSettings

DECIDER = "cs_routing_v1"

DISPOSITION_REJECT = "reject"
DISPOSITION_HANDOFF = "handoff"
DISPOSITION_DEFER = "defer"
DISPOSITION_CONTINUE = "continue"

ACTION_REJECT = "reject"
ACTION_REQUEST_HANDOFF = "request_handoff"
ACTION_DEFER = "defer"
ACTION_SUBMIT_AGENT_RUN = "submit_agent_run"


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """A routing decision ready to be persisted.

    ``id`` and ``created_at`` are database-owned. A caller-supplied creation
    timestamp is supported for query/test helpers, but the normal insert leaves
    both columns to their database defaults.
    """

    tenant_id: str
    business_id: str
    workspace_id: str
    conversation_id: UUID
    request_id: UUID
    disposition: str
    execution_tier: str | None
    action: str
    reason_code: str
    matched_rule_id: str | None
    decider: str
    message_length: int
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IngressResult:
    """Decision plus any agent snapshot already fetched while deciding."""

    decision: RoutingDecision
    agent_snapshot: dict[str, Any] | None


def _decision(
    *,
    conv: dict[str, Any],
    request_id: UUID,
    message_length: int,
    disposition: str,
    execution_tier: str | None,
    action: str,
    reason_code: str,
    matched_rule_id: str | None = None,
) -> RoutingDecision:
    return RoutingDecision(
        tenant_id=str(conv["tenant_id"]),
        business_id=str(conv["business_id"]),
        workspace_id=str(conv["workspace_id"]),
        conversation_id=conv["id"],
        request_id=request_id,
        disposition=disposition,
        execution_tier=execution_tier,
        action=action,
        reason_code=reason_code,
        matched_rule_id=matched_rule_id,
        decider=DECIDER,
        message_length=message_length,
    )


async def decide_ingress(
    *,
    conn: Any,
    conv: dict[str, Any],
    message: str,
    request_id: UUID,
    agents: Any,
    memory: Any,
    settings: Any,
    routing_settings: CustomerServiceRoutingSettings,
) -> IngressResult:
    """Decide an inbound message without applying any side effects.

    The order is intentionally fixed: closed, exact handoff rule, human/waiting
    mode, blacklist, unconfigured model, then normal agent submission. The agent
    snapshot is fetched only after the first three branches and is returned to
    the caller for run construction so the main path never queries it twice.
    """

    message_length = len(message)

    if conv.get("mode") == "closed":
        return IngressResult(
            decision=_decision(
                conv=conv,
                request_id=request_id,
                message_length=message_length,
                disposition=DISPOSITION_REJECT,
                execution_tier=None,
                action=ACTION_REJECT,
                reason_code="conversation_closed",
            ),
            agent_snapshot=None,
        )

    matched_rule_id = match_handoff(message, routing_settings)
    if matched_rule_id is not None:
        return IngressResult(
            decision=_decision(
                conv=conv,
                request_id=request_id,
                message_length=message_length,
                disposition=DISPOSITION_HANDOFF,
                execution_tier=None,
                action=ACTION_REQUEST_HANDOFF,
                reason_code="user_requested_human",
                matched_rule_id=matched_rule_id,
            ),
            agent_snapshot=None,
        )

    if conv.get("mode") == "human":
        return IngressResult(
            decision=_decision(
                conv=conv,
                request_id=request_id,
                message_length=message_length,
                disposition=DISPOSITION_DEFER,
                execution_tier=None,
                action=ACTION_DEFER,
                reason_code="human_mode_active",
            ),
            agent_snapshot=None,
        )

    if conv.get("mode") == "waiting":
        return IngressResult(
            decision=_decision(
                conv=conv,
                request_id=request_id,
                message_length=message_length,
                disposition=DISPOSITION_DEFER,
                execution_tier=None,
                action=ACTION_DEFER,
                reason_code="waiting_mode_active",
            ),
            agent_snapshot=None,
        )

    agent_snapshot: dict[str, Any] | None = None
    if conv.get("agent_id"):
        agent_snapshot = await agents.snapshot(
            str(conv["tenant_id"]),
            conv["agent_id"],
            conn,
        )

    if memory is not None and conv.get("customer_id"):
        effective = resolve_agent_memory(
            agent_snapshot.get("config") if agent_snapshot else None,
            settings,
        )
        if effective.blacklist_auto_handoff:
            flags = await memory.active_flags(
                str(conv["tenant_id"]),
                conv["customer_id"],
                getattr(settings, "memory_flag_inject_max", 3),
            )
            if any(flag["key"] == "blacklist" for flag in flags):
                return IngressResult(
                    decision=_decision(
                        conv=conv,
                        request_id=request_id,
                        message_length=message_length,
                        disposition=DISPOSITION_HANDOFF,
                        execution_tier=None,
                        action=ACTION_REQUEST_HANDOFF,
                        reason_code="blacklist_flag",
                    ),
                    agent_snapshot=agent_snapshot,
                )

    if agent_snapshot is None and settings.model_backend == "unconfigured":
        return IngressResult(
            decision=_decision(
                conv=conv,
                request_id=request_id,
                message_length=message_length,
                disposition=DISPOSITION_REJECT,
                execution_tier=None,
                action=ACTION_REJECT,
                reason_code="model_not_configured",
            ),
            agent_snapshot=None,
        )

    return IngressResult(
        decision=_decision(
            conv=conv,
            request_id=request_id,
            message_length=message_length,
            disposition=DISPOSITION_CONTINUE,
            execution_tier="agent",
            action=ACTION_SUBMIT_AGENT_RUN,
            reason_code="default_agent",
        ),
        agent_snapshot=agent_snapshot,
    )


__all__ = [
    "ACTION_DEFER",
    "ACTION_REJECT",
    "ACTION_REQUEST_HANDOFF",
    "ACTION_SUBMIT_AGENT_RUN",
    "DECIDER",
    "DISPOSITION_CONTINUE",
    "DISPOSITION_DEFER",
    "DISPOSITION_HANDOFF",
    "DISPOSITION_REJECT",
    "IngressResult",
    "RoutingDecision",
    "decide_ingress",
]
