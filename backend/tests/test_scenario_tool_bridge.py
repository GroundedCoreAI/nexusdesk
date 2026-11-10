"""Unit tests for provider executor declarations and the tool bridge.

These stay database-free: the declaration parser and the template renderer are
pure, and the merge helper is exercised directly so a failing assertion points
at the mapping rule rather than at fixture plumbing.  The end-to-end gateway
call lives in ``test_scenario_tool_bridge_postgres.py``.
"""

import pytest

from agent_platform.business_capabilities.customer_service.providers.executors import (
    ExecutorSpec,
    parse_executors,
    validate_executors,
)
from agent_platform.business_capabilities.customer_service.scenarios.models import (
    SimulatedObject,
)
from agent_platform.business_capabilities.customer_service.scenarios.tool_bridge import (
    ScenarioToolBridge,
    ToolOutcome,
    _at_root,
    _context,
    _lookup,
    _render,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError


def object_ref(**kw):
    values = {
        "id": "order-1",
        "type": "order",
        "status": "运输中",
        "facts": {"amount": 99, "items": [{"title": "马克杯"}]},
    }
    values.update(kw)
    return SimulatedObject.model_validate(values)


def test_executor_defaults_are_conservative():
    spec = ExecutorSpec.parse({"tool": "order_status"})

    assert spec == ExecutorSpec(tool="order_status", arguments={}, result_root="", on_error="human")


def test_executor_keeps_templates_and_declared_root():
    spec = ExecutorSpec.parse(
        {
            "tool": "order_status",
            "arguments": {"order_id": "$object.id", "note": "literal"},
            "result_root": "data.order",
            "on_error": "fail",
        }
    )

    assert spec.arguments == {"order_id": "$object.id", "note": "literal"}
    assert spec.result_root == "data.order"
    assert spec.on_error == "fail"


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        # The gateway refuses dotted names, so a semantic identifier cannot be
        # persisted as a callable tool.
        ({"tool": "shopping.order.status"}, "provider_executor_tool_invalid"),
        ({"tool": "1bad"}, "provider_executor_tool_invalid"),
        ({"tool": ""}, "provider_executor_tool_invalid"),
        ({"tool": "ok", "arguments": []}, "provider_executor_arguments_invalid"),
        (
            {"tool": "ok", "arguments": {"order_id": "$bogus.id"}},
            "provider_executor_template_invalid",
        ),
        ({"tool": "ok", "result_root": "a..b"}, "provider_executor_result_root_invalid"),
        ({"tool": "ok", "on_error": "explode"}, "provider_executor_error_policy_invalid"),
        ({"tool": "ok", "endpoint": "http://x"}, "provider_executor_unknown_field"),
        ("not-a-mapping", "provider_executor_invalid"),
    ],
)
def test_executor_rejects_invalid_declarations(raw, code):
    with pytest.raises(DomainError) as excinfo:
        ExecutorSpec.parse(raw)

    assert excinfo.value.code == code


@pytest.mark.parametrize("raw", [None, "", {}])
def test_empty_declaration_means_placeholder(raw):
    assert ExecutorSpec.parse(raw) is None


@pytest.mark.parametrize(
    "config",
    [None, {}, {"description": "订单数据"}, {"executors": {}}],
)
def test_missing_executors_keep_the_label_only_simulation(config):
    assert parse_executors(config) == {}


def test_legacy_single_executor_means_the_read_path():
    executors = parse_executors({"executor": {"tool": "order_status"}})

    assert list(executors) == ["get"]
    assert executors["get"].tool == "order_status"


def test_executors_declare_each_role_independently():
    executors = parse_executors(
        {
            "executors": {
                "get": {"tool": "order_status", "arguments": {"order_id": "$object.id"}},
                "list": {"tool": "order_list", "result_root": "data.items"},
            }
        }
    )

    assert set(executors) == {"get", "list"}
    assert executors["list"].result_root == "data.items"


def test_executors_reject_an_unknown_role():
    with pytest.raises(DomainError) as excinfo:
        parse_executors({"executors": {"delete": {"tool": "order_status"}}})

    assert excinfo.value.code == "provider_executor_role_invalid"


def test_validate_executors_is_the_persist_gate():
    validate_executors({"executors": {"get": {"tool": "order_status"}}})

    with pytest.raises(DomainError):
        validate_executors({"executors": {"get": {"tool": "order-status"}}})


def test_render_resolves_references_and_escapes_literals():
    context = _context(object_ref(), {"id": "customer-9"}, "confirm_object")

    assert _render(
        {
            "order_id": "$object.id",
            "amount": "$object.amount",
            "customer": "$customer.id",
            "decision": "$decision.selected",
            "literal": "普通文本",
            "escaped": "$$5 off",
            "nested": {"type": "$object.type"},
            "items": ["$object.status"],
        },
        context,
    ) == {
        "order_id": "order-1",
        "amount": 99,
        "customer": "customer-9",
        "decision": "confirm_object",
        "literal": "普通文本",
        "escaped": "$5 off",
        "nested": {"type": "order"},
        "items": ["运输中"],
    }


def test_render_returns_none_for_an_absent_path():
    context = _context(object_ref(), None, None)

    assert _render({"missing": "$object.absent.field"}, context) == {"missing": None}


def test_render_rejects_an_unknown_reference():
    with pytest.raises(DomainError) as excinfo:
        _render({"order_id": "$bogus.id"}, _context(object_ref(), None, None))

    assert excinfo.value.code == "provider_executor_template_invalid"


def test_lookup_supports_list_indices():
    values = {"items": [{"title": "马克杯"}]}

    assert _lookup(values, "items.0.title") == "马克杯"
    assert _lookup(values, "items.3.title") is None
    assert _lookup(values, "items.notanindex.title") is None
    assert _at_root({"data": {"items": [1, 2]}}, "data.items") == [1, 2]
    assert _at_root({"data": 1}, "") == {"data": 1}


def test_successful_read_replaces_facts_but_keeps_request_extras():
    request_object = object_ref(facts={"amount": 99})
    outcome = ToolOutcome(
        tool="order_status",
        ok=True,
        data={"status": "已签收", "logistics": {"status": "已到站"}},
    )

    resolution = ScenarioToolBridge._merged(
        request_object,
        outcome,
        ExecutorSpec(tool="order_status"),
    )

    assert resolution.object is not None
    assert resolution.object.status == "已签收"
    assert resolution.object.facts == {
        "amount": 99,
        "status": "已签收",
        "logistics": {"status": "已到站"},
    }
    assert resolution.outcome is outcome


def test_missing_object_is_reported_not_faked():
    outcome = ToolOutcome(
        tool="order_status", ok=False, error="upstream_http_error", error_status=404
    )

    resolution = ScenarioToolBridge._merged(
        object_ref(),
        outcome,
        ExecutorSpec(tool="order_status", on_error="fail"),
    )

    assert resolution.object is not None
    assert resolution.object.exists is False
    assert resolution.object.facts == {}
    assert resolution.on_error == "fail"


def test_forbidden_object_is_reported_not_dropped():
    outcome = ToolOutcome(
        tool="order_status", ok=False, error="upstream_http_error", error_status=403
    )

    resolution = ScenarioToolBridge._merged(
        object_ref(),
        outcome,
        ExecutorSpec(tool="order_status"),
    )

    assert resolution.object is not None
    assert resolution.object.accessible is False


def test_failed_read_keeps_the_request_object_intact():
    outcome = ToolOutcome(tool="order_status", ok=False, error="tool_timeout")

    resolution = ScenarioToolBridge._merged(
        object_ref(),
        outcome,
        ExecutorSpec(tool="order_status"),
    )

    assert resolution.object is not None
    assert resolution.object.exists is True
    assert resolution.object.facts == {"amount": 99, "items": [{"title": "马克杯"}]}


def test_candidates_normalise_a_list_payload():
    outcome = ToolOutcome(
        tool="order_list",
        ok=True,
        data=[{"id": "order-1", "name": "订单 1", "status": "运输中"}, {"key": "order-2"}, "junk"],
    )

    assert ScenarioToolBridge._candidates(outcome) == [
        {"id": "order-1", "title": "订单 1", "status": "运输中"},
        {"id": "order-2", "title": "order-2", "status": ""},
    ]


def test_candidates_are_empty_for_a_failed_read():
    outcome = ToolOutcome(tool="order_list", ok=False, error="tool_timeout")

    assert ScenarioToolBridge._candidates(outcome) == []
