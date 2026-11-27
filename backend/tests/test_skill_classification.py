"""Contract tests for the advisory Skill weight and risk classification."""

import json
from uuid import uuid4

import pytest

from agent_platform.business_capabilities.skill_library.classification import (
    LARGE_AMOUNT_THRESHOLD,
    PackageFacts,
    as_definition_payload,
    classify_skill,
    effective_risk,
    weight_of,
)
from agent_platform.business_capabilities.skill_library.models import SkillDefinition


def definition(**overrides):
    payload = SkillDefinition().model_dump(mode="json", by_alias=True)
    payload.update(overrides)
    return payload


def codes(result):
    return [reason.code for reason in result.risk_reasons]


@pytest.mark.parametrize(
    ("package", "expected"),
    [
        (None, "declarative"),
        (PackageFacts(), "declarative"),
        (PackageFacts(present=True), "packaged"),
        (PackageFacts(present=True, entrypoint="   "), "packaged"),
        (PackageFacts(present=True, entrypoint="scripts/main.py"), "executable"),
        (PackageFacts(present=True, has_scripts=True, entrypoint="scripts/main.py"), "executable"),
    ],
)
def test_weight_follows_package_facts(package, expected):
    assert weight_of(package) == expected


@pytest.mark.parametrize(
    ("skill_type", "expected"),
    [
        ("instruction", "r0"),
        ("knowledge", "r0"),
        ("query", "r1"),
        ("handoff", "r1"),
        ("action", "r2"),
    ],
)
def test_type_sets_the_risk_baseline(skill_type, expected):
    result = classify_skill(definition(type=skill_type))
    assert result.risk_level == expected


def test_declarative_skill_carries_no_reason_noise():
    assert codes(classify_skill(definition(type="instruction"))) == []


@pytest.mark.parametrize(
    ("dependency", "value", "code"),
    [
        ("tool_names", ["order_lookup"], "tool_capability"),
        ("knowledge_base_ids", [str(uuid4())], "knowledge_access"),
        ("handoff_queue", "support", "human_handoff"),
    ],
)
def test_dependencies_raise_a_prompt_only_skill_to_r1(dependency, value, code):
    payload = definition(type="instruction")
    payload["dependencies"][dependency] = value
    result = classify_skill(payload)
    assert result.risk_level == "r1"
    assert code in codes(result)


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (None, "r0"),
        (0, "r0"),
        (0.5, "r2"),
        (LARGE_AMOUNT_THRESHOLD - 1, "r2"),
        (LARGE_AMOUNT_THRESHOLD, "r3"),
        (100_000, "r3"),
    ],
)
def test_amount_raises_and_caps_the_label(amount, expected):
    payload = definition(type="instruction")
    payload["runtime"]["max_amount"] = amount
    result = classify_skill(payload)
    assert result.risk_level == expected
    if amount and amount > 0:
        assert "money_action" in codes(result)
    if amount and amount >= LARGE_AMOUNT_THRESHOLD:
        assert "large_amount" in codes(result)


def test_risk_takes_the_highest_signal_not_the_last_one():
    payload = definition(type="action")
    payload["dependencies"]["tool_names"] = ["order_lookup"]
    payload["runtime"]["max_amount"] = 10_000
    result = classify_skill(payload)
    assert result.risk_level == "r3"
    assert {"type_action", "tool_capability", "money_action", "large_amount"} <= set(codes(result))


def test_data_scope_names_every_plane_touched():
    payload = definition(type="action")
    payload["dependencies"]["model_profile_id"] = str(uuid4())
    payload["dependencies"]["knowledge_base_ids"] = [str(uuid4())]
    payload["dependencies"]["tool_names"] = ["order_lookup"]
    payload["dependencies"]["handoff_queue"] = "support"
    payload["runtime"]["max_amount"] = 100
    result = classify_skill(payload, PackageFacts(present=True, has_scripts=True))
    assert result.data_scope == ("model", "kb", "tool", "handoff", "money", "code")


def test_executable_packages_are_scoped_as_code_without_raising_risk():
    result = classify_skill(
        definition(type="instruction"),
        PackageFacts(present=True, has_scripts=True),
    )
    assert result.weight_class == "executable"
    assert result.risk_level == "r0"
    assert result.data_scope == ("code",)


def test_accepts_a_validated_definition_instance():
    model = SkillDefinition(type="query", dependencies={"tool_names": ["order_lookup"]})
    result = classify_skill(model, PackageFacts(present=True))
    assert result.weight_class == "packaged"
    assert result.risk_level == "r1"
    assert result.reasons_payload() == [
        {"code": "type_query", "level": "r1"},
        {"code": "tool_capability", "level": "r1"},
    ]


@pytest.mark.parametrize(
    ("declared", "expected"),
    [("r0", "r0"), ("r3", "r3"), (None, "r2"), ("bogus", "r2"), ("", "r2")],
)
def test_effective_risk_prefers_a_valid_stored_label(declared, expected):
    assert effective_risk(declared, "r2") == expected


def test_payload_accepts_json_text_and_rejects_garbage():
    assert as_definition_payload(json.dumps({"type": "action"})) == {"type": "action"}
    assert as_definition_payload("{not json") == {}
    assert as_definition_payload("[1,2]") == {}
    assert as_definition_payload(None) == {}


def test_reasons_are_json_serialisable():
    payload = definition(type="action")
    payload["runtime"]["max_amount"] = 1
    reasons = classify_skill(payload).reasons_payload()
    assert json.loads(json.dumps(reasons)) == reasons
