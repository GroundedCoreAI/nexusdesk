import pytest
from pydantic import ValidationError

from agent_platform.business_capabilities.customer_service.scenarios.models import (
    BusinessObjectConfig,
    CandidateStrategy,
    FactField,
    HandlerDefinition,
    HandlerType,
    ObjectMode,
    ScenarioConfig,
    ScenarioEntry,
    UserDecision,
    UserDecisionKind,
)


def _candidate_strategy() -> CandidateStrategy:
    return CandidateStrategy(
        empty_state="没有可选择的订单。",
        unavailable_state="订单服务暂时不可用。",
    )


def _object(
    *,
    mode: ObjectMode | str = ObjectMode.OPTIONAL,
    required: bool = False,
    object_type: str = "order",
) -> BusinessObjectConfig:
    return BusinessObjectConfig(
        type=object_type,
        provider="orders",
        required=required,
        mode=mode,
        candidate_strategy=_candidate_strategy(),
    )


def _direct_handler(
    *,
    key: str = "answer",
    reply: str | None = "这是配置化的直接回复。",
    enabled: bool = True,
) -> HandlerDefinition:
    return HandlerDefinition(
        key=key,
        type=HandlerType.DIRECT,
        label="直接回复",
        priority=10,
        enabled=enabled,
        reply=reply,
    )


def _config(**overrides) -> ScenarioConfig:
    values = {
        "name": "查询订单",
        "description": "查询当前客户的订单",
        "domain": "购物消费",
        "template": "query",
        "entries": [
            ScenarioEntry(
                key="natural",
                type="natural_language",
                label="自然语言",
            )
        ],
        "handlers": [_direct_handler()],
        "fallback_order": ["answer"],
    }
    values.update(overrides)
    return ScenarioConfig(**values)


def test_contracts_strip_strings_and_forbid_extra_fields():
    entry = ScenarioEntry(
        key="  natural  ",
        type="  natural_language  ",
        label="  自然语言  ",
        description="  描述  ",
    )

    assert entry.key == "natural"
    assert entry.label == "自然语言"
    assert entry.description == "描述"
    with pytest.raises(ValidationError):
        ScenarioEntry(
            key="natural",
            type="natural_language",
            label="自然语言",
            unexpected=True,
        )
    with pytest.raises(ValidationError):
        CandidateStrategy(
            limit=51,
            empty_state="空",
            unavailable_state="不可用",
        )


@pytest.mark.parametrize("field", ["entries", "facts", "decisions", "recommendations", "handlers"])
def test_scenario_collection_keys_must_be_unique(field):
    entries = [ScenarioEntry(key="same", type="natural_language", label="入口")]
    facts = [FactField(key="same", label="状态", source="status")]
    decisions = [UserDecision(key="same", kind=UserDecisionKind.SELECT_INTENT, label="选择")]
    recommendations = [{"key": "same", "label": "推荐", "message": "推荐"}]
    handlers = [_direct_handler(key="same")]
    duplicate = {
        "entries": entries * 2,
        "facts": facts * 2,
        "decisions": decisions * 2,
        "recommendations": recommendations * 2,
        "handlers": handlers * 2,
    }[field]

    with pytest.raises(ValidationError, match="duplicate .* key: same"):
        _config(**{field: duplicate})


def test_fallback_order_must_be_unique_and_reference_existing_handlers():
    with pytest.raises(ValidationError, match="duplicate fallback_order"):
        _config(fallback_order=["answer", "answer"])
    with pytest.raises(ValidationError, match="unknown handler key"):
        _config(fallback_order=["missing"])


def test_at_least_one_handler_must_be_enabled():
    with pytest.raises(ValidationError, match="at least one enabled handler"):
        _config(handlers=[_direct_handler(enabled=False)])


def test_direct_handler_requires_reply_and_agent_handler_requires_agent_id():
    with pytest.raises(ValidationError, match="requires a reply"):
        _config(handlers=[_direct_handler(reply="   ")])
    with pytest.raises(ValidationError, match="requires agent_id"):
        HandlerDefinition(
            key="agent",
            type=HandlerType.AGENT,
            label="Agent",
        )


def test_action_requires_confirmation_decision_unless_disabled():
    action = HandlerDefinition(
        key="submit",
        type=HandlerType.ACTION,
        label="提交",
        tool="submit_order",
    )
    with pytest.raises(ValidationError, match="requires a confirm_action decision"):
        _config(handlers=[action], fallback_order=["submit"])

    confirm = UserDecision(
        key="confirm_submit",
        kind=UserDecisionKind.CONFIRM_ACTION,
        label="确认提交",
        confirm=True,
    )
    config = _config(
        decisions=[confirm],
        handlers=[action],
        fallback_order=["submit"],
    )
    assert config.decisions[0].kind == UserDecisionKind.CONFIRM_ACTION

    no_confirm_action = action.model_copy(update={"config": {"requires_confirmation": False}})
    config = _config(
        handlers=[no_confirm_action],
        fallback_order=["submit"],
    )
    assert config.handlers[0].config["requires_confirmation"] is False


def test_object_mode_and_required_flags_cannot_conflict():
    with pytest.raises(ValidationError, match="required=false"):
        BusinessObjectConfig(
            type="order",
            provider="orders",
            required=False,
            mode=ObjectMode.REQUIRED,
            candidate_strategy=_candidate_strategy(),
        )
    with pytest.raises(ValidationError, match="mode 'none' cannot be required"):
        _config(object=_object(mode=ObjectMode.NONE, required=True))


def test_fact_audiences_must_not_be_empty():
    with pytest.raises(ValidationError, match="audiences must not be empty"):
        FactField(
            key="amount",
            label="金额",
            source="amount",
            audiences=[],
        )


def test_simulation_request_length_and_object_extras_are_validated():
    from agent_platform.business_capabilities.customer_service.scenarios.models import (
        SimulationRequest,
    )

    with pytest.raises(ValidationError):
        SimulationRequest(message="   ")
    with pytest.raises(ValidationError):
        SimulationRequest(message="x" * 8001)
