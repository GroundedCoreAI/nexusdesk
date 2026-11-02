"""Handoff business-context aggregation tests."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from test_platform_postgres import conversation as _conversation
from test_platform_postgres import platform as _platform

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]

platform = _platform


def _scenario_config() -> dict:
    return {
        "name": "订单物流查询",
        "description": "查询订单状态并确认处理方式",
        "domain": "购物消费",
        "category": "订单服务",
        "template": "query",
        "entries": [{"key": "chat", "type": "natural_language", "label": "自然语言"}],
        "facts": [
            {
                "key": "order-status",
                "label": "订单状态",
                "source": "status",
                "order": 10,
                "audiences": ["customer", "agent", "human"],
            },
            {
                "key": "receiver-phone",
                "label": "收件手机号",
                "source": "phone",
                "order": 20,
                "masked": True,
                "audiences": ["customer", "agent", "human"],
            },
            {
                "key": "internal-note",
                "label": "客户可见备注",
                "source": "note",
                "order": 30,
                "audiences": ["customer"],
            },
        ],
        "object": {
            "type": "order",
            "provider": "internal-order-data",
            "required": True,
            "mode": "required",
            "candidate_strategy": {
                "sort": "recent_desc",
                "limit": 5,
                "filters": [],
                "empty_state": "没有找到订单",
                "unavailable_state": "订单暂时不可用",
            },
        },
        "decisions": [
            {
                "key": "confirm-return",
                "kind": "confirm_action",
                "label": "确认退货",
                "confirm": True,
                "options": [
                    {"value": "yes", "label": "确认退货"},
                    {"value": "no", "label": "暂不退货"},
                ],
            }
        ],
        "recommendations": [],
        "handlers": [
            {
                "key": "answer",
                "type": "direct",
                "label": "固定应答",
                "reply": "已为您查询订单状态。",
            },
            {
                "key": "human-support",
                "type": "human",
                "label": "人工客服",
                "queue": "support-queue",
            },
        ],
        "fallback_order": ["answer", "human-support"],
        "matching": {"keywords": ["订单", "物流"], "intents": [], "negative_keywords": []},
    }


async def _published_scenario(client) -> str:
    key = "context-scene-" + uuid4().hex[:10]
    created = await client.post(
        "/api/v1/service-scenarios",
        json={"key": key, "config": _scenario_config()},
    )
    assert created.status_code == 201, created.text
    published = await client.post(
        f"/api/v1/service-scenarios/{key}/publish",
        json={"revision": created.json()["revision"]},
    )
    assert published.status_code == 200, published.text
    return key


async def _handoff(client):
    conv = await _conversation(client)
    await client.post(
        f"/api/v1/conversations/{conv['id']}/messages",
        json={"content": "我的订单到哪了"},
    )
    response = await client.post(
        f"/api/v1/conversations/{conv['id']}/handoffs",
        json={"reason": "客户要求人工核实物流"},
    )
    assert response.status_code in (200, 201), response.text
    return conv, response.json()


async def test_context_without_traces_is_honest_and_empty(platform):
    client, _services, _settings = platform
    conv, handoff = await _handoff(client)

    response = await client.get(f"/api/v1/handoffs/{handoff['id']}/context")
    assert response.status_code == 200, response.text
    context = response.json()

    assert context["handoff"]["id"] == handoff["id"]
    assert context["handoff"]["status"] == "waiting"
    assert context["handoff"]["reason"] == "客户要求人工核实物流"
    assert context["conversation"]["id"] == conv["id"]
    assert context["conversation"]["mode"] == "waiting"
    # The customer identity stays a boolean; the raw id never leaves the server.
    assert context["conversation"]["has_customer"] is False
    assert context["scenario"] is None
    assert context["application"] is None
    assert context["object"] is None
    assert context["facts"] == []
    assert context["decisions"] == []
    assert context["traces"] == []
    # Routing evidence only exists once an ingress path has decided something;
    # an API-created conversation has none, and the aggregator must say so
    # instead of inventing a reason.
    assert context["routing"] == []
    assert context["runs"]
    assert context["runs"][0]["status"] == "cancelled"


async def test_context_restores_scenario_object_facts_and_decisions(platform):
    client, _services, _settings = platform
    scenario_key = await _published_scenario(client)
    conv, handoff = await _handoff(client)

    simulated = await client.post(
        f"/api/v1/service-scenarios/simulate?scenario_key={scenario_key}",
        json={
            "message": "我要退货",
            "conversation_id": conv["id"],
            "selected_decision": "confirm-return",
            "object": {
                "id": "SO-20261102-001",
                "type": "order",
                "status": "已发货",
                "facts": {
                    "status": "已发货",
                    "phone": "13800001111",
                    "note": "客户已来电两次",
                },
            },
        },
    )
    assert simulated.status_code == 200, simulated.text
    assert simulated.json()["conversation_id"] == conv["id"]

    response = await client.get(f"/api/v1/handoffs/{handoff['id']}/context")
    assert response.status_code == 200, response.text
    context = response.json()

    assert context["scenario"]["key"] == scenario_key
    assert context["scenario"]["version"] == 1
    assert context["scenario"]["handler_type"] in {"direct", "human"}
    assert context["object"] == {
        "type": "order",
        "id": "SO-20261102-001",
        "status": "已发货",
    }

    facts = {item["key"]: item for item in context["facts"]}
    assert set(facts) == {"order-status", "receiver-phone"}
    assert facts["order-status"]["label"] == "订单状态"
    assert facts["order-status"]["value"] == "已发货"
    assert facts["receiver-phone"]["masked"] is True
    assert facts["receiver-phone"]["value"].endswith("1111")
    assert facts["receiver-phone"]["value"].startswith("*")
    # Customer-only projections and provider-shaped fields must not leak.
    serialized = json.dumps(context, ensure_ascii=False)
    assert "internal-note" not in serialized
    assert "客户已来电两次" not in serialized
    assert "internal-order-data" not in serialized
    assert "support-queue" not in serialized
    assert "source" not in json.dumps(facts, ensure_ascii=False)

    decisions = {item["key"]: item for item in context["decisions"]}
    assert decisions["confirm-return"]["state"] == "selected"
    assert decisions["confirm-return"]["confirm"] is True
    assert [option["value"] for option in decisions["confirm-return"]["options"]] == [
        "yes",
        "no",
    ]

    assert len(context["traces"]) == 1
    assert context["traces"][0]["scenario_key"] == scenario_key
    assert context["traces"][0]["outcome"] in {"succeeded", "delegated", "needs_input"}


async def test_context_requires_trace_bound_to_this_conversation(platform):
    client, _services, _settings = platform
    scenario_key = await _published_scenario(client)
    other_conv, _other_handoff = await _handoff(client)
    _conv, handoff = await _handoff(client)
    # Bound to a different conversation: it must not appear in this context.
    await client.post(
        f"/api/v1/service-scenarios/simulate?scenario_key={scenario_key}",
        json={
            "message": "别人的订单",
            "conversation_id": other_conv["id"],
            "object": {
                "id": "SO-OTHER",
                "type": "order",
                "status": "已签收",
                "facts": {"status": "已签收", "phone": "13900002222"},
            },
        },
    )

    response = await client.get(f"/api/v1/handoffs/{handoff['id']}/context")
    assert response.status_code == 200, response.text
    context = response.json()
    assert context["scenario"] is None
    assert context["traces"] == []
    assert context["facts"] == []


async def test_context_rejects_unknown_or_foreign_handoff(platform):
    client, _services, _settings = platform
    missing = await client.get(f"/api/v1/handoffs/{uuid4()}/context")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "handoff_not_found"


async def test_context_is_readable_by_viewer_but_not_writable(platform):
    client, _services, _settings = platform
    _conv, handoff = await _handoff(client)

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


async def test_simulation_rejects_foreign_conversation(platform):
    client, _services, _settings = platform
    scenario_key = await _published_scenario(client)
    response = await client.post(
        f"/api/v1/service-scenarios/simulate?scenario_key={scenario_key}",
        json={"message": "订单", "conversation_id": str(uuid4())},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "conversation_not_found"
