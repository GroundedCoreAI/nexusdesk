from __future__ import annotations

from typing import Any

from agent_platform.business_capabilities.customer_service.industry_packs.merge import (
    MergeConflict,
    MergeResult,
    three_way_merge,
)
from agent_platform.business_capabilities.customer_service.scenarios.models import (
    ScenarioConfig,
)


def _payload() -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "name": "订单进度查询",
        "description": "基础描述",
        "domain": "订单服务",
        "category": "订单查询",
        "template": "query",
        "channels": ["web"],
        "entries": [
            {
                "key": "natural-language",
                "type": "natural_language",
                "label": "自然语言",
                "description": "",
            }
        ],
        "facts": [
            {"key": "status", "label": "订单状态", "source": "status"},
            {"key": "amount", "label": "订单金额", "source": "amount"},
            {"key": "updated", "label": "更新时间", "source": "updated_at"},
        ],
        "decisions": [],
        "recommendations": [
            {"key": "hint", "label": "提示", "message": "基础提示"},
        ],
        "handlers": [
            {
                "key": "answer",
                "type": "direct",
                "label": "直接回答",
                "reply": "请稍后重试。",
            }
        ],
        "fallback_order": ["answer"],
        "matching": {"keywords": ["订单"], "intents": [], "negative_keywords": []},
        "config": {
            "industry_pack": {
                "pack_key": "local-life",
                "pack_version": "1.0.0",
                "template_key": "order-progress-query",
                "template_version": "1.0.0",
                "maturity": "ga",
            },
            "feature": {"enabled": True},
        },
    }


def _scenario(**overrides: Any) -> ScenarioConfig:
    payload = _payload()
    payload.update(overrides)
    return ScenarioConfig.model_validate(payload)


def _assert_valid(config: ScenarioConfig) -> None:
    assert ScenarioConfig.model_validate(config.model_dump(mode="json")) == config


def test_non_overlapping_changes_merge_cleanly_with_provenance():
    base = _scenario()
    local = _scenario(description="租户自定义描述")
    incoming = _scenario(name="订单进度查询新版")

    result = three_way_merge(base, local, incoming)

    assert isinstance(result, MergeResult)
    assert result.status == "clean"
    assert result.conflicts == []
    assert result.merged_config.name == "订单进度查询新版"
    assert result.merged_config.description == "租户自定义描述"
    assert "name" in result.incoming_fields
    assert "description" in result.kept_local_fields
    assert {"name", "description"} <= set(result.auto_merged_fields)
    _assert_valid(result.merged_config)
    assert base.description == "基础描述"
    assert local.name == "订单进度查询"


def test_keyed_entries_merge_additions_and_disjoint_field_changes():
    base = _scenario()
    local = _scenario(
        entries=[
            {
                "key": "natural-language",
                "type": "natural_language",
                "label": "本地自然语言入口",
                "description": "",
            },
            {
                "key": "local-shortcut",
                "type": "external_link",
                "label": "本地快捷入口",
            },
        ]
    )
    incoming = _scenario(
        entries=[
            {
                "key": "natural-language",
                "type": "natural_language",
                "label": "自然语言",
                "description": "模板新增说明",
            },
            {
                "key": "incoming-shortcut",
                "type": "external_link",
                "label": "模板快捷入口",
            },
        ]
    )

    result = three_way_merge(base, local, incoming)

    assert result.status == "clean"
    merged_entries = {entry.key: entry for entry in result.merged_config.entries}
    assert set(merged_entries) == {
        "natural-language",
        "local-shortcut",
        "incoming-shortcut",
    }
    assert merged_entries["natural-language"].label == "本地自然语言入口"
    assert merged_entries["natural-language"].description == "模板新增说明"
    assert "entries[natural-language].label" in result.kept_local_fields
    assert "entries[natural-language].description" in result.incoming_fields
    _assert_valid(result.merged_config)


def test_decision_options_merge_by_value_without_using_array_indexes():
    base = _scenario(
        decisions=[
            {
                "key": "choose-action",
                "kind": "select_intent",
                "label": "选择操作",
                "options": [
                    {"value": "yes", "label": "是", "description": ""},
                    {"value": "no", "label": "否"},
                ],
            }
        ]
    )
    local = _scenario(
        decisions=[
            {
                "key": "choose-action",
                "kind": "select_intent",
                "label": "选择操作",
                "options": [
                    {"value": "yes", "label": "确认", "description": ""},
                    {"value": "local-extra", "label": "本地新增"},
                ],
            }
        ]
    )
    incoming = _scenario(
        decisions=[
            {
                "key": "choose-action",
                "kind": "select_intent",
                "label": "选择操作",
                "options": [
                    {"value": "yes", "label": "是", "description": "模板新增说明"},
                    {"value": "incoming-extra", "label": "模板新增"},
                ],
            }
        ]
    )

    result = three_way_merge(base, local, incoming)

    assert result.status == "clean"
    options = {option.value: option for option in result.merged_config.decisions[0].options}
    assert set(options) == {"yes", "local-extra", "incoming-extra"}
    assert options["yes"].label == "确认"
    assert options["yes"].description == "模板新增说明"
    assert "decisions[choose-action].options[yes].label" in result.kept_local_fields
    assert "decisions[choose-action].options[yes].description" in result.incoming_fields
    _assert_valid(result.merged_config)


def test_stable_value_lists_merge_as_unions_and_keep_references_valid():
    base = _scenario()
    local = _scenario(
        channels=["web", "app"],
        handlers=[
            {
                "key": "answer",
                "type": "direct",
                "label": "直接回答",
                "reply": "请稍后重试。",
            },
            {
                "key": "local-fallback",
                "type": "direct",
                "label": "本地兜底",
                "reply": "转本地客服。",
            },
        ],
        fallback_order=["answer", "local-fallback"],
        matching={
            "keywords": ["订单", "退款"],
            "intents": [],
            "negative_keywords": [],
        },
    )
    incoming = _scenario(
        channels=["web", "wechat"],
        handlers=[
            {
                "key": "answer",
                "type": "direct",
                "label": "直接回答",
                "reply": "请稍后重试。",
            },
            {
                "key": "incoming-fallback",
                "type": "direct",
                "label": "模板兜底",
                "reply": "转模板客服。",
            },
        ],
        fallback_order=["answer", "incoming-fallback"],
        matching={
            "keywords": ["订单", "物流"],
            "intents": [],
            "negative_keywords": [],
        },
    )

    result = three_way_merge(base, local, incoming)

    assert result.status == "clean"
    assert result.merged_config.channels == ["web", "app", "wechat"]
    assert result.merged_config.fallback_order == [
        "answer",
        "local-fallback",
        "incoming-fallback",
    ]
    assert {handler.key for handler in result.merged_config.handlers} == {
        "answer",
        "local-fallback",
        "incoming-fallback",
    }
    assert result.merged_config.matching.keywords == ["订单", "退款", "物流"]
    _assert_valid(result.merged_config)


def test_concurrent_change_to_same_field_conflicts_and_retains_local():
    base = _scenario()
    local = _scenario(
        recommendations=[
            {"key": "hint", "label": "提示", "message": "本地提示"},
        ]
    )
    incoming = _scenario(
        name="模板新名称",
        recommendations=[
            {"key": "hint", "label": "提示", "message": "模板提示"},
        ],
    )

    result = three_way_merge(base, local, incoming)

    assert result.status == "conflicted"
    assert result.merged_config.name == "模板新名称"
    assert result.merged_config.recommendations[0].message == "本地提示"
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert isinstance(conflict, MergeConflict)
    assert conflict.path == "recommendations[hint].message"
    assert conflict.base == "基础提示"
    assert conflict.local == "本地提示"
    assert conflict.incoming == "模板提示"
    assert conflict.field == conflict.path
    _assert_valid(result.merged_config)


def test_deletions_from_opposite_sides_merge_cleanly():
    base = _scenario()
    local = _scenario(
        facts=[
            {"key": "status", "label": "订单状态", "source": "status"},
            {"key": "updated", "label": "更新时间", "source": "updated_at"},
        ],
        config={
            "industry_pack": {
                "pack_key": "local-life",
                "pack_version": "1.0.0",
                "template_key": "order-progress-query",
                "template_version": "1.0.0",
                "maturity": "ga",
            }
        },
    )
    incoming = _scenario(
        facts=[
            {"key": "amount", "label": "订单金额", "source": "amount"},
            {"key": "updated", "label": "更新时间", "source": "updated_at"},
        ]
    )

    result = three_way_merge(base, local, incoming)

    assert result.status == "clean"
    assert [fact.key for fact in result.merged_config.facts] == ["updated"]
    assert "feature" not in result.merged_config.config
    assert "facts[status]" in result.incoming_fields
    assert "facts[amount]" in result.kept_local_fields
    _assert_valid(result.merged_config)


def test_local_deletion_wins_conflict_when_incoming_modified_the_same_item():
    base = _scenario()
    local = _scenario(
        facts=[
            {"key": "status", "label": "订单状态", "source": "status"},
            {"key": "updated", "label": "更新时间", "source": "updated_at"},
        ]
    )
    incoming = _scenario(
        facts=[
            {"key": "status", "label": "订单状态", "source": "status"},
            {"key": "amount", "label": "订单金额（模板）", "source": "amount"},
            {"key": "updated", "label": "更新时间", "source": "updated_at"},
        ]
    )

    result = three_way_merge(base, local, incoming)

    assert result.status == "conflicted"
    assert [fact.key for fact in result.merged_config.facts] == ["status", "updated"]
    assert [conflict.path for conflict in result.conflicts] == ["facts[amount]"]
    assert result.conflicts[0].local is None
    assert result.conflicts[0].incoming["label"] == "订单金额（模板）"
    _assert_valid(result.merged_config)


def test_invalid_cross_field_merge_falls_back_to_valid_local_config():
    base = _scenario(
        handlers=[
            {
                "key": "answer",
                "type": "direct",
                "label": "直接回答",
                "reply": "回答。",
            },
            {
                "key": "tracking",
                "type": "direct",
                "label": "查询进度",
                "reply": "进度查询中。",
            },
        ],
        fallback_order=["answer", "tracking"],
    )
    local = _scenario(
        handlers=[
            {
                "key": "tracking",
                "type": "direct",
                "label": "查询进度",
                "reply": "进度查询中。",
            }
        ],
        fallback_order=["tracking"],
    )
    incoming = _scenario(
        handlers=[
            {
                "key": "answer",
                "type": "direct",
                "label": "直接回答",
                "reply": "回答。",
            }
        ],
        fallback_order=["answer"],
    )

    result = three_way_merge(base, local, incoming)

    assert result.status == "blocked"
    assert result.merged_config == local
    assert any(conflict.path == "$schema" for conflict in result.conflicts)
    _assert_valid(result.merged_config)


def test_identical_inputs_are_clean_and_do_not_report_changes():
    base = _scenario()

    result = three_way_merge(base, base, base)

    assert result.status == "clean"
    assert result.merged_config == base
    assert result.conflicts == []
    assert result.auto_merged_fields == []
    assert result.kept_local_fields == []
    assert result.incoming_fields == []
    _assert_valid(result.merged_config)
