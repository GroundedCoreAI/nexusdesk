"""Handoff business-context aggregation tests."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from test_platform_postgres import conversation as _conversation
from test_platform_postgres import create_agent, create_published_application
from test_platform_postgres import platform as _platform

from agent_platform.core_platform.platform_services.persistence.store import execute, one

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]

platform = _platform


async def _handoff(client):
    conversation = await _conversation(client)
    await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "我的订单到哪了"},
    )
    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/handoffs",
        json={"reason": "客户要求人工核实物流"},
    )
    assert response.status_code in (200, 201), response.text
    return conversation, response.json()


async def _published_application(client):
    agent, _body = await create_agent(client)
    return await create_published_application(
        client,
        agent,
        key="handoff-context-" + uuid4().hex[:10],
        name="订单物流助手",
    )


async def _insert_application_trace(services, settings, conversation_id, application):
    async with services.groups.runtime.engine.begin() as connection:
        application_row = await one(
            connection,
            """
SELECT id,application_key,name,business_id,workspace_id,agent_id,agent_version,
       published_version,origin
FROM service_applications
WHERE id=:id AND tenant_id=:tenant
""",
            id=application["id"],
            tenant=settings.tenant_id,
        )
        assert application_row is not None
        trace = {
            "application_key": application_row["application_key"],
            "application_version": application_row["published_version"],
            "agent_id": str(application_row["agent_id"]),
            "agent_version": application_row["agent_version"],
            "skills": [
                {
                    "key": "handoff",
                    "type": "handoff",
                    "connection_key": None,
                }
            ],
            "connections": [],
            "status": "submitted",
        }
        await execute(
            connection,
            """
INSERT INTO service_application_traces(
    id,tenant_id,business_id,workspace_id,application_id,application_version,
    conversation_id,run_id,agent_id,agent_version,trace
) VALUES(
    :id,:tenant,:business,:workspace,:application_id,:application_version,
    :conversation_id,NULL,:agent_id,:agent_version,CAST(:trace AS jsonb)
)
""",
            id=uuid4(),
            tenant=settings.tenant_id,
            business=application_row["business_id"],
            workspace=application_row["workspace_id"],
            application_id=application_row["id"],
            application_version=application_row["published_version"],
            conversation_id=conversation_id,
            agent_id=application_row["agent_id"],
            agent_version=application_row["agent_version"],
            trace=json.dumps(trace, ensure_ascii=False),
        )
        return trace


async def test_context_without_traces_is_honest_and_empty(platform):
    client, _services, _settings = platform
    conversation, handoff = await _handoff(client)

    response = await client.get(f"/api/v1/handoffs/{handoff['id']}/context")
    assert response.status_code == 200, response.text
    context = response.json()

    assert context["handoff"]["id"] == handoff["id"]
    assert context["handoff"]["status"] == "waiting"
    assert context["handoff"]["reason"] == "客户要求人工核实物流"
    assert context["conversation"]["id"] == conversation["id"]
    assert context["conversation"]["mode"] == "waiting"
    # The customer identity stays a boolean; the raw id never leaves the server.
    assert context["conversation"]["has_customer"] is False
    assert context["application"] is None
    assert context["object"] is None
    assert context["facts"] == []
    assert context["decisions"] == []
    assert context["traces"] == []
    # The v1 scenario projection is gone rather than returned as null forever.
    assert "scenario" not in context
    # Routing evidence only exists once an ingress path has decided something;
    # an API-created conversation has none, and the aggregator must say so
    # instead of inventing a reason.
    assert context["routing"] == []
    assert context["runs"]
    assert context["runs"][0]["status"] == "cancelled"


async def test_context_projects_v2_application_trace(platform):
    client, services, settings = platform
    application = await _published_application(client)
    conversation, handoff = await _handoff(client)
    inserted = await _insert_application_trace(
        services,
        settings,
        conversation["id"],
        application,
    )

    response = await client.get(f"/api/v1/handoffs/{handoff['id']}/context")
    assert response.status_code == 200, response.text
    context = response.json()

    assert context["application"] == {
        "key": application["key"],
        "name": application["name"],
        "version": application["published_version"],
        "source": application["origin"],
    }
    assert len(context["traces"]) == 1
    trace = context["traces"][0]
    assert trace["application_key"] == inserted["application_key"]
    assert trace["application_version"] == inserted["application_version"]
    assert trace["agent_id"] == inserted["agent_id"]
    assert trace["agent_version"] == inserted["agent_version"]
    assert trace["status"] == "submitted"
    assert trace["skills"] == [
        {
            "key": "handoff",
            "type": "handoff",
            "connection_key": None,
        }
    ]
    assert trace["connections"] == []
    assert "scenario" not in context
    # Facts and decisions are operator projections from the contract payload,
    # not values reconstructed from the retired scenario table.
    assert context["facts"] == []
    assert context["decisions"] == []


async def test_context_requires_trace_bound_to_this_conversation(platform):
    client, services, settings = platform
    application = await _published_application(client)
    other_conversation, _other_handoff = await _handoff(client)
    _conversation, handoff = await _handoff(client)
    await _insert_application_trace(
        services,
        settings,
        other_conversation["id"],
        application,
    )

    response = await client.get(f"/api/v1/handoffs/{handoff['id']}/context")
    assert response.status_code == 200, response.text
    context = response.json()
    assert context["application"] is None
    assert context["traces"] == []
    assert context["facts"] == []
    assert context["decisions"] == []


async def test_context_rejects_unknown_handoff(platform):
    client, _services, _settings = platform
    missing = await client.get(f"/api/v1/handoffs/{uuid4()}/context")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "handoff_not_found"


async def test_context_is_readable_by_viewer_but_not_writable(platform):
    client, _services, _settings = platform
    _conversation, handoff = await _handoff(client)

    viewer = await client.get(
        f"/api/v1/handoffs/{handoff['id']}/context",
        headers={"Authorization": "Bearer platform-viewer"},
    )
    assert viewer.status_code == 200, viewer.text
    assert viewer.json()["handoff"]["id"] == handoff["id"]

    blocked = await client.post(
        f"/api/v1/handoffs/{handoff['id']}/transition",
        json={"operation": "claim"},
        headers={"Authorization": "Bearer platform-viewer"},
    )
    assert blocked.status_code == 403
