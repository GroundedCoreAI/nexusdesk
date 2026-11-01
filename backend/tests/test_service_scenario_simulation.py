from uuid import uuid4

import pytest

from agent_platform.business_capabilities.customer_service.scenarios.models import (
    BusinessObjectConfig,
    CandidateStrategy,
    FactField,
    HandlerCondition,
    HandlerDefinition,
    ScenarioConfig,
    ScenarioEntry,
    ScenarioMatching,
    UserDecision,
    UserDecisionKind,
)
from agent_platform.business_capabilities.customer_service.scenarios.simulation import (
    simulate,
)


def _candidate_strategy() -> CandidateStrategy:
    return CandidateStrategy(
        empty_state="没有可选对象。",
        unavailable_state="对象服务不可用。",
    )


def _object(
    *,
    mode: str = "optional",
    required: bool = False,
) -> BusinessObjectConfig:
    return BusinessObjectConfig(
        type="order",
        provider="orders",
        required=required,
        mode=mode,
        candidate_strategy=_candidate_strategy(),
    )


def _handler(
    key: str = "answer",
    *,
    kind: str = "direct",
    priority: int = 10,
    when: HandlerCondition | None = None,
    reply: str | None = "已处理。",
    config: dict | None = None,
    **overrides,
) -> HandlerDefinition:
    return HandlerDefinition(
        key=key,
        type=kind,
        label=key,
        priority=priority,
        when=when or HandlerCondition(),
        reply=reply if kind == "direct" else None,
        config=config or {},
        **overrides,
    )


def _config(
    *,
    name: str = "查询订单",
    keywords: list[str] | None = None,
    intents: list[str] | None = None,
    negative_keywords: list[str] | None = None,
    entries: list[ScenarioEntry] | None = None,
    facts: list[FactField] | None = None,
    object: BusinessObjectConfig | None = None,
    decisions: list[UserDecision] | None = None,
    recommendations: list[dict] | None = None,
    handlers: list[HandlerDefinition] | None = None,
    fallback_order: list[str] | None = None,
) -> ScenarioConfig:
    handlers = handlers or [_handler()]
    return ScenarioConfig(
        name=name,
        description=f"{name}描述",
        domain="购物消费",
        template="query",
        entries=entries or [],
        facts=facts or [],
        object=object,
        decisions=decisions or [],
        recommendations=recommendations or [],
        handlers=handlers,
        fallback_order=fallback_order or [handler.key for handler in handlers],
        matching=ScenarioMatching(
            keywords=keywords or [],
            intents=intents or [],
            negative_keywords=negative_keywords or [],
        ),
    )


def _trace(
    config: ScenarioConfig,
    request: dict | None = None,
    *,
    key: str = "query-orders",
    name: str = "查询订单",
    all_scenarios=None,
):
    return simulate(
        key,
        name,
        1,
        "published",
        config,
        request or {"message": "我的订单状态"},
        all_scenarios=all_scenarios,
    )


def test_target_simulation_returns_a_complete_deterministic_trace():
    trace = _trace(
        _config(handlers=[_handler(reply="当前订单已发货。")]),
        {"message": "订单到哪了"},
    )

    assert trace.resolved_by == "target"
    assert trace.schema_version == "v1"
    assert trace.simulated is True
    assert [step["step"] for step in trace.steps] == [
        "scene",
        "object",
        "facts",
        "decision",
        "handler",
        "result",
    ]
    assert trace.result["status"] == "succeeded"
    assert trace.result["reason"] == "direct_reply"
    assert trace.result["content"] == "当前订单已发货。"
    assert trace.handler["key"] == "answer"


def test_keyword_resolution_prefers_the_more_specific_scene():
    broad = _config(name="订单", keywords=["订单"])
    specific = _config(name="订单状态", keywords=["订单状态"])
    scenarios = [
        {"key": "broad", "name": "订单", "version": 1, "status": "published", "config": broad},
        {
            "key": "specific",
            "name": "订单状态",
            "version": 2,
            "status": "published",
            "config": specific,
        },
    ]

    trace = _trace(
        broad,
        {"message": "帮我查订单状态"},
        key="broad",
        name="订单",
        all_scenarios=scenarios,
    )

    assert trace.scenario_key == "specific"
    assert trace.scenario_version == 2
    assert trace.resolved_by == "keyword"


def test_negative_keywords_reject_a_scene_and_no_match_returns_needs_input():
    config = _config(
        name="订单状态",
        keywords=["订单状态"],
        negative_keywords=["退款"],
    )

    trace = _trace(
        config,
        {"message": "退款订单状态"},
        all_scenarios=[
            {
                "key": "query-orders",
                "name": "订单状态",
                "version": 1,
                "status": "published",
                "config": config,
            }
        ],
    )

    assert trace.resolved_by == "none"
    assert trace.result["status"] == "needs_input"
    assert trace.result["reason"] == "scene_not_matched"
    assert trace.steps[0]["status"] == "not_matched"


def test_non_natural_language_entry_strongly_matches_the_target_key():
    target = _config(
        name="目标场景",
        keywords=["目标"],
        entries=[
            ScenarioEntry(
                key="order-card",
                type="object_card",
                label="订单卡片",
            )
        ],
    )
    other = _config(name="其他场景", keywords=["订单卡片入口"])

    trace = _trace(
        target,
        {"message": "订单卡片入口", "entry": "object_card"},
        key="target",
        name="目标场景",
        all_scenarios=[
            {
                "key": "other",
                "name": "其他场景",
                "version": 1,
                "status": "published",
                "config": other,
            }
        ],
    )

    assert trace.scenario_key == "target"
    assert trace.resolved_by == "target"


def test_required_object_missing_existing_and_permission_states_are_explicit():
    config = _config(
        object=_object(mode="required", required=True),
        handlers=[_handler(kind="query")],
    )

    missing = _trace(config)
    assert missing.result["status"] == "needs_input"
    assert missing.result["reason"] == "object_required"

    nonexistent = _trace(
        config,
        {
            "message": "查订单",
            "object": {
                "id": "order-1",
                "type": "order",
                "exists": False,
            },
        },
    )
    assert nonexistent.result["status"] == "needs_input"
    assert nonexistent.result["reason"] == "object_missing"

    forbidden = _trace(
        config,
        {
            "message": "查订单",
            "object": {
                "id": "order-1",
                "type": "order",
                "accessible": False,
            },
        },
    )
    assert forbidden.result["status"] == "denied"
    assert forbidden.result["reason"] == "object_forbidden"
    assert forbidden.facts == []


def test_facts_are_projected_from_configured_fields_only_and_masked():
    config = _config(
        object=_object(),
        facts=[
            FactField(
                key="amount",
                label="金额",
                source="payment.amount",
                order=20,
                masked=True,
            ),
            FactField(
                key="status",
                label="状态",
                source="status",
                order=10,
            ),
        ],
        handlers=[_handler(kind="query")],
    )
    request = {
        "message": "查订单",
        "object": {
            "id": "order-1",
            "type": "order",
            "status": "已发货",
            "facts": {
                "status": "已发货",
                "payment": {"amount": "6222020200113434"},
                "customer_phone": "13812345678",
            },
        },
    }

    trace = _trace(config, request)

    assert [fact["key"] for fact in trace.facts] == ["status", "amount"]
    amount = next(fact for fact in trace.facts if fact["key"] == "amount")
    assert amount["value"].endswith("3434")
    assert "622202020011" not in amount["value"]
    assert {fact["key"] for fact in trace.facts} == {"status", "amount"}
    assert all("customer_phone" not in fact for fact in trace.facts)


def test_handler_priority_and_conditions_choose_the_first_matching_handler():
    shipped = _handler(
        "shipped",
        kind="query",
        priority=10,
        when=HandlerCondition(object_statuses=["已发货"]),
    )
    fallback = _handler("fallback", kind="knowledge", priority=20)
    config = _config(
        object=_object(),
        handlers=[shipped, fallback],
    )

    pending = _trace(
        config,
        {
            "message": "查订单",
            "object": {"id": "order-1", "type": "order", "status": "待付款"},
        },
    )
    assert pending.handler["key"] == "fallback"

    shipped_trace = _trace(
        config,
        {
            "message": "查订单",
            "object": {"id": "order-1", "type": "order", "status": "已发货"},
        },
    )
    assert shipped_trace.handler["key"] == "shipped"


def test_explicit_handler_with_unmet_condition_returns_needs_input():
    config = _config(
        object=_object(),
        handlers=[
            _handler(
                "shipped",
                kind="query",
                when=HandlerCondition(object_statuses=["已发货"]),
            )
        ],
    )

    trace = _trace(
        config,
        {
            "message": "查订单",
            "object": {"id": "order-1", "type": "order", "status": "待付款"},
            "selected_handler": "shipped",
        },
    )

    assert trace.result["status"] == "needs_input"
    assert trace.result["reason"] == "handler_condition_not_met"


def test_action_requires_a_selected_confirm_action_decision():
    confirm = UserDecision(
        key="confirm_submit",
        kind=UserDecisionKind.CONFIRM_ACTION,
        label="确认提交",
        confirm=True,
    )
    action = _handler("submit", kind="action", config={"requires_confirmation": True})
    config = _config(decisions=[confirm], handlers=[action])

    unconfirmed = _trace(config, {"message": "提交申请"})
    assert unconfirmed.result["status"] == "needs_input"
    assert unconfirmed.result["reason"] == "action_confirmation_required"
    assert unconfirmed.handler["key"] == "submit"

    confirmed = _trace(
        config,
        {"message": "提交申请", "selected_decision": "confirm_submit"},
    )
    assert confirmed.result["status"] == "succeeded"
    assert confirmed.result["reason"] == "action_confirmed"


@pytest.mark.parametrize(
    ("kind", "status", "reason", "extra"),
    [
        ("direct", "succeeded", "direct_reply", {}),
        ("knowledge", "succeeded", "knowledge_answer", {}),
        ("query", "succeeded", "query_executed", {}),
        (
            "action",
            "succeeded",
            "action_executed",
            {"config": {"requires_confirmation": False}},
        ),
        (
            "agent",
            "succeeded",
            "agent_routed",
            {"agent_id": uuid4(), "agent_version": 3, "agent_name": "售后 Agent"},
        ),
        ("human", "handoff", "human_handoff", {"queue": "order-support"}),
        (
            "tracking",
            "tracking",
            "tracking_created",
            {"config": {"tracking_type": "order"}},
        ),
    ],
)
def test_every_handler_type_has_a_deterministic_result(kind, status, reason, extra):
    config = _config(handlers=[_handler("handler", kind=kind, **extra)])

    trace = _trace(config, {"message": "处理订单"})

    assert trace.result["status"] == status
    assert trace.result["reason"] == reason
    assert trace.result["content"]
    assert trace.handler["type"] == kind
