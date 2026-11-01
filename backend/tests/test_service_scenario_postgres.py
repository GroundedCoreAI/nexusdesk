"""PostgreSQL integration tests for the service-scenario platform."""

from uuid import uuid4

import pytest
from test_platform_postgres import create_agent
from test_platform_postgres import platform as _platform

from agent_platform.extension_contracts import BusinessScope

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


def _config(
    *,
    name: str = "查询订单",
    agent_id: str | None = None,
    agent_version: int | None = None,
) -> dict:
    handlers = []
    if agent_id:
        handlers.append(
            {
                "key": "complex-agent",
                "type": "agent",
                "label": "复杂问题 Agent",
                "priority": 10,
                "agent_id": agent_id,
                "agent_version": agent_version,
                "agent_name": "测试 Agent",
                "when": {"message_terms": ["复杂"]},
            }
        )
    handlers.append(
        {
            "key": "human-handoff",
            "type": "human",
            "label": "人工客服",
            "priority": 20,
            "queue": "order-support",
        }
    )
    return {
        "name": name,
        "description": "服务场景集成测试",
        "domain": "购物消费",
        "category": "订单服务",
        "template": "query",
        "channels": ["web"],
        "entries": [
            {
                "key": "natural",
                "type": "natural_language",
                "label": "自然语言",
            }
        ],
        "facts": [],
        "decisions": [],
        "recommendations": [],
        "handlers": handlers,
        "fallback_order": [handler["key"] for handler in handlers],
        "matching": {
            "keywords": ["订单"],
            "intents": [],
            "negative_keywords": [],
        },
    }


async def _create_scenario(client, key: str, config: dict) -> dict:
    response = await client.post(
        "/api/v1/service-scenarios",
        json={"key": key, "config": config},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _publish(client, key: str, revision: int) -> dict:
    response = await client.post(
        f"/api/v1/service-scenarios/{key}/publish",
        json={"revision": revision},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_seed_defaults_is_idempotent_and_references_the_demo_agent(platform):
    client, services, settings = platform
    agent, _ = await create_agent(client)
    scenarios = services.groups.business.scenarios

    first = await scenarios.seed_defaults(settings.tenant_id)
    second = await scenarios.seed_defaults(settings.tenant_id)

    assert first == {"scenarios": 6, "versions": 10}
    assert second == {"scenarios": 0, "versions": 0}

    listed = (await client.get("/api/v1/service-scenarios")).json()
    assert listed["total"] == 6
    assert {item["key"] for item in listed["items"]} == {
        "query-orders",
        "order-rules",
        "track-logistics",
        "after-sales",
        "invoice",
        "complaints",
    }

    detail = (await client.get("/api/v1/service-scenarios/query-orders")).json()
    agent_handler = next(item for item in detail["config"]["handlers"] if item["type"] == "agent")
    assert agent_handler["agent_id"] == agent["id"]
    assert agent_handler["agent_version"] == 1

    usage = (await client.get(f"/api/v1/agents/{agent['id']}/service-scenarios")).json()
    assert {item["key"] for item in usage["items"]} == {"query-orders"}
    assert usage["items"][0]["handler_key"] == "agent-complex"
    assert usage["items"][0]["volume"] == 0
    assert usage["items"][0]["metrics"]["volume"] == 0


async def test_create_duplicate_key_conflicts_without_leaking_an_integrity_error(platform):
    client, _services, _settings = platform
    key = "dup-" + uuid4().hex[:10]

    await _create_scenario(client, key, _config())
    response = await client.post(
        "/api/v1/service-scenarios",
        json={"key": key, "config": _config(name="重复场景")},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "scenario_key_conflict"


async def test_publish_pins_agent_version_and_versions_are_immutable(platform):
    client, _services, _settings = platform
    agent, agent_body = await create_agent(client)
    key = "agent-pin-" + uuid4().hex[:10]

    created = await _create_scenario(
        client,
        key,
        _config(agent_id=agent["id"]),
    )
    first = await _publish(client, key, created["revision"])
    first_handler = next(item for item in first["config"]["handlers"] if item["type"] == "agent")
    assert first["version"] == 1
    assert first_handler["agent_version"] == 1

    agent_body["config"]["system_prompt"] = "第二版 Agent 指令"
    updated_agent = await client.put(
        f"/api/v1/agents/{agent['id']}",
        json={**agent_body, "revision": agent["draft_revision"]},
    )
    assert updated_agent.status_code == 200, updated_agent.text
    agent_revision = updated_agent.json()["draft_revision"]
    published_agent = await client.post(
        f"/api/v1/agents/{agent['id']}/publish",
        json={"revision": agent_revision},
    )
    assert published_agent.status_code == 200, published_agent.text
    assert published_agent.json()["version"] == 2

    scenario = (await client.get(f"/api/v1/service-scenarios/{key}")).json()
    stale_handler = next(item for item in scenario["config"]["handlers"] if item["type"] == "agent")
    assert stale_handler["agent_version"] == 1

    upgraded_config = _config(agent_id=agent["id"], agent_version=2)
    response = await client.put(
        f"/api/v1/service-scenarios/{key}",
        json={"config": upgraded_config, "revision": first["revision"]},
    )
    assert response.status_code == 200, response.text
    second = await _publish(client, key, response.json()["revision"])
    second_handler = next(item for item in second["config"]["handlers"] if item["type"] == "agent")
    assert second["version"] == 2
    assert second_handler["agent_version"] == 2

    versions = (await client.get(f"/api/v1/service-scenarios/{key}/versions")).json()
    by_version = {item["version"]: item for item in versions["items"]}
    assert by_version[1]["config"]["handlers"][0]["agent_version"] == 1
    assert by_version[2]["config"]["handlers"][0]["agent_version"] == 2
    assert by_version[2]["published"] is True


async def test_rollback_restores_an_immutable_published_version(platform):
    client, _services, _settings = platform
    key = "rollback-" + uuid4().hex[:10]
    created = await _create_scenario(client, key, _config(name="第一版场景"))
    first = await _publish(client, key, created["revision"])
    assert first["version"] == 1

    response = await client.put(
        f"/api/v1/service-scenarios/{key}",
        json={"config": _config(name="第二版场景"), "revision": first["revision"]},
    )
    assert response.status_code == 200, response.text
    second = await _publish(client, key, response.json()["revision"])
    assert second["name"] == "第二版场景"
    assert second["version"] == 2

    rolled_back = await client.post(
        f"/api/v1/service-scenarios/{key}/rollback",
        json={"version": 1, "revision": second["revision"]},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    payload = rolled_back.json()
    assert payload["name"] == "第一版场景"
    assert payload["published_version"] == 1
    assert payload["rollback_version"] == 1


async def test_simulation_persists_structured_trace_with_valid_outcome(platform):
    client, _services, _settings = platform
    key = "simulate-" + uuid4().hex[:10]
    created = await _create_scenario(client, key, _config(name="人工承接场景"))
    await _publish(client, key, created["revision"])

    response = await client.post(
        f"/api/v1/service-scenarios/{key}/simulate",
        json={"message": "请帮我处理订单问题"},
    )
    assert response.status_code == 200, response.text
    simulation = response.json()
    assert simulation["scenario_key"] == key
    assert simulation["result"]["status"] == "handoff"
    assert simulation["trace_id"]

    traces = (await client.get(f"/api/v1/service-scenarios/{key}/traces")).json()
    assert len(traces["items"]) == 1
    trace = traces["items"][0]
    assert trace["handler_type"] == "human"
    assert trace["outcome"] == "delegated"
    assert trace["trace"]["result"]["status"] == "handoff"
    assert trace["trace"]["steps"][0]["step"] == "scene"


async def test_catalog_and_trace_reads_are_tenant_and_workspace_scoped(platform):
    client, services, settings = platform
    key = "scope-" + uuid4().hex[:10]
    await _create_scenario(client, key, _config())
    scenarios = services.groups.business.scenarios
    own_scope = BusinessScope(
        tenant_id=settings.tenant_id,
        business_id="customer-service",
        workspace_id="default",
    )
    other_workspace = BusinessScope(
        tenant_id=settings.tenant_id,
        business_id="customer-service",
        workspace_id="another-workspace",
    )
    other_tenant = BusinessScope(
        tenant_id="another-tenant",
        business_id="customer-service",
        workspace_id="default",
    )

    own = await scenarios.list(settings.tenant_id, scope=own_scope)
    workspace = await scenarios.list(settings.tenant_id, scope=other_workspace)
    tenant = await scenarios.list("another-tenant", scope=other_tenant)

    assert {item["key"] for item in own["items"]} == {key}
    assert workspace["items"] == []
    assert tenant["items"] == []
