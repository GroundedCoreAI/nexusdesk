from uuid import uuid4

from agent_platform.business_capabilities.customer_service.scenarios.models import ScenarioConfig
from agent_platform.business_capabilities.customer_service.scenarios.seed import default_scenarios
from agent_platform.business_capabilities.customer_service.scenarios.service import (
    _public_row,
    _trace_outcome,
)


def test_default_scenarios_are_contract_valid_without_an_agent():
    scenarios = default_scenarios()

    assert len(scenarios) == 6
    for scenario in scenarios:
        config = ScenarioConfig.model_validate(scenario["config"])
        assert all(handler.type != "agent" for handler in config.handlers)


def test_default_query_scene_binds_a_published_agent_when_available():
    agent = {
        "id": uuid4(),
        "name": "示例客服 Agent",
        "version": 5,
    }
    scenario = default_scenarios(agent=agent)[0]
    config = ScenarioConfig.model_validate(scenario["config"])
    handler = next(item for item in config.handlers if item.type == "agent")

    assert handler.agent_id == agent["id"]
    assert handler.agent_version == 5
    assert handler.agent_name == agent["name"]
    assert scenario["key"] == "query-orders"


def test_public_row_uses_stable_api_field_names():
    row = _public_row(
        {
            "scenario_key": "query-orders",
            "draft_revision": 3,
            "draft": {"name": "查询订单"},
        }
    )

    assert row["key"] == "query-orders"
    assert row["revision"] == 3
    assert row["config"] == {"name": "查询订单"}


def test_simulator_result_shapes_map_to_persisted_trace_outcomes():
    assert _trace_outcome("succeeded") == "succeeded"
    assert _trace_outcome("needs_input") == "needs_input"
    assert _trace_outcome("denied") == "denied"
    assert _trace_outcome("handoff") == "delegated"
    assert _trace_outcome("tracking") == "succeeded"
    assert _trace_outcome("unknown") == "simulated"
    assert _trace_outcome(None) == "simulated"
