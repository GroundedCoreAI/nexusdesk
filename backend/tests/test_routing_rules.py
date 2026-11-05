import logging

import pytest
from pydantic import ValidationError

from agent_platform.business_capabilities.customer_service.routing.rules import (
    match_handoff,
    normalize_text,
)
from agent_platform.business_capabilities.customer_service.routing.settings import (
    CustomerServiceRoutingSettings,
    RoutingRule,
    default_handoff_rules,
    load_customer_service_routing_settings,
)


def test_default_rules_cover_four_locales_and_exact_default_words():
    settings = CustomerServiceRoutingSettings(_env_file=None)

    assert settings.trace_enabled is False
    assert [(rule.id, rule.locale) for rule in settings.handoff_rules] == [
        ("zh_human_request_001", "zh-CN"),
        ("zhtw_human_request_001", "zh-TW"),
        ("en_human_request_001", "en"),
        ("hi_human_request_001", "hi"),
    ]
    assert match_handoff("客服", settings) == "zh_human_request_001"
    assert match_handoff("轉人工", settings) == "zhtw_human_request_001"
    assert match_handoff("representative", settings) == "en_human_request_001"
    assert match_handoff("मानव", settings) == "hi_human_request_001"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  HUMAN  ", "human"),
        ("ＨＵＭＡＮ", "human"),
        ("Human.", "human"),
        ("human。", "human"),
        (" human! ", "human"),
    ],
)
def test_normalize_text_strips_case_whitespace_fullwidth_and_one_final_mark(raw, expected):
    assert normalize_text(raw) == expected


def test_normalize_text_removes_only_one_trailing_punctuation_mark():
    assert normalize_text("human!!") == "human!"
    assert normalize_text("human...") == "human.."


def test_match_handoff_is_exact_and_never_uses_substring_matching():
    settings = CustomerServiceRoutingSettings(_env_file=None)

    assert match_handoff("human", settings) == "en_human_request_001"
    assert match_handoff("HUMAN.", settings) == "en_human_request_001"
    assert match_handoff("human agent", settings) == "en_human_request_001"
    assert match_handoff("your agent platform is slow", settings) is None
    assert match_handoff("human being", settings) is None
    assert match_handoff("I want to speak to a human", settings) is None
    assert match_handoff("agent", settings) is None


def test_rule_ids_and_normalized_phrases_must_be_globally_unique():
    with pytest.raises(ValidationError, match="duplicate routing rule id"):
        CustomerServiceRoutingSettings(
            handoff_rules=[
                RoutingRule(id="one", locale="en", phrases=["human"]),
                RoutingRule(id="one", locale="en", phrases=["representative"]),
            ]
        )

    with pytest.raises(ValidationError, match="globally unique"):
        CustomerServiceRoutingSettings(
            handoff_rules=[
                RoutingRule(id="one", locale="en", phrases=["human"]),
                RoutingRule(id="two", locale="zh-CN", phrases=["ＨＵＭＡＮ."]),
            ]
        )


def test_matched_rule_id_is_stable_when_rule_list_is_reordered():
    rules = default_handoff_rules()
    reordered = CustomerServiceRoutingSettings(handoff_rules=list(reversed(rules)))

    assert match_handoff("human", reordered) == "en_human_request_001"
    assert match_handoff("转人工", reordered) == "zh_human_request_001"


def test_invalid_environment_config_warns_and_falls_back_to_defaults(monkeypatch, caplog):
    monkeypatch.setenv("AGENT_CS_ROUTING_HANDOFF_RULES", "{not-json")

    with caplog.at_level(logging.WARNING):
        settings = load_customer_service_routing_settings()

    assert "using defaults" in caplog.text
    assert settings.trace_enabled is False
    assert match_handoff("human", settings) == "en_human_request_001"
