"""Deterministic customer-service ingress routing."""

from .decision import IngressResult, RoutingDecision, decide_ingress
from .repository import list_decisions, record, summarize_decisions
from .rules import match_handoff, normalize_text
from .settings import (
    CustomerServiceRoutingSettings,
    RoutingRule,
    load_customer_service_routing_settings,
)

__all__ = [
    "CustomerServiceRoutingSettings",
    "IngressResult",
    "RoutingDecision",
    "RoutingRule",
    "decide_ingress",
    "list_decisions",
    "load_customer_service_routing_settings",
    "match_handoff",
    "normalize_text",
    "record",
    "summarize_decisions",
]
