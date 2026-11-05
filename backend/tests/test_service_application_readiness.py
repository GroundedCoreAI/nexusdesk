"""Publish-readiness and release-gate tests for service applications."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from test_platform_postgres import platform as _platform

from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
)
from agent_platform.extension_contracts import BusinessScope

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


def _scenario_config(
    *,
    ready: bool = True,
    with_business_context: bool = True,
) -> dict:
    handlers = [
        {
            "key": "answer",
            "type": "direct",
            "label": "固定应答",
            "reply": "已为您查询。",
        }
    ]
    fallback = ["answer"]
    if ready:
        handlers.append(
            {
                "key": "human-support",
                "type": "human",
                "label": "人工客服",
                "queue": "support-queue",
            }
        )
        fallback.append("human-support")

    config = {
        "name": "测试订单查询",
        "description": "查询订单状态",
        "domain": "购物消费",
        "category": "订单服务",
        "template": "query",
        "entries": [{"key": "chat", "type": "natural_language", "label": "自然语言"}],
        "facts": (
            [
                {
                    "key": "status",
                    "label": "订单状态",
                    "source": "order_status",
                    "order": 10,
                }
            ]
            if with_business_context
            else []
        ),
        "object": (
            {
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
            }
            if with_business_context
            else None
        ),
        "decisions": [],
        "recommendations": [],
        "handlers": handlers,
        "fallback_order": fallback,
        "matching": {"keywords": ["订单状态"], "intents": [], "negative_keywords": []},
    }
    return config


def _application_config(scenario_key: str) -> dict:
    return {
        "name": "测试服务应用",
        "description": "发布门禁测试",
        "scenarios": [{"key": scenario_key, "enabled": True}],
        "capabilities": [],
        "channels": [
            {
                "key": "web",
                "name": "官网帮助中心",
                "type": "web",
                "status": "active",
            }
        ],
    }


async def _create_published_scenario(
    client,
    *,
    ready: bool = True,
    with_business_context: bool = True,
) -> tuple[str, dict]:
    key = "readiness-scene-" + uuid4().hex[:10]
    created = await client.post(
        "/api/v1/service-scenarios",
        json={
            "key": key,
            "config": _scenario_config(
                ready=ready,
                with_business_context=with_business_context,
            ),
        },
    )
    assert created.status_code == 201, created.text
    published = await client.post(
        f"/api/v1/service-scenarios/{key}/publish",
        json={"revision": created.json()["revision"]},
    )
    assert published.status_code == 200, published.text
    return key, published.json()


async def _create_application(client, scenario_key: str) -> tuple[str, dict]:
    key = "readiness-app-" + uuid4().hex[:10]
    response = await client.post(
        "/api/v1/service-apps",
        json={"key": key, "config": _application_config(scenario_key)},
    )
    assert response.status_code == 201, response.text
    return key, response.json()


async def test_ready_application_exposes_business_checks_and_can_publish(platform):
    client, _services, _settings = platform
    scenario_key, _scenario = await _create_published_scenario(client)
    app_key, application = await _create_application(client, scenario_key)

    response = await client.get(f"/api/v1/service-apps/{app_key}/readiness")
    assert response.status_code == 200, response.text
    readiness = response.json()
    assert readiness["status"] == "ready"
    assert readiness["can_publish"] is True
    assert readiness["can_simulate"] is True
    assert readiness["counts"] == {"pass": 2, "warning": 0, "blocked": 0}

    scenario = readiness["scenarios"][0]
    assert scenario["key"] == scenario_key
    assert scenario["status"] == "ready"
    assert {item["key"] for item in scenario["checks"]} == {
        "application-link",
        "business-object",
        "business-facts",
        "handlers",
        "action-confirmation",
        "fallback-order",
        "human-handoff",
        "customer-channels",
        "publication",
    }
    serialized = json.dumps(readiness, ensure_ascii=False)
    assert "internal-order-data" not in serialized
    assert "support-queue" not in serialized
    assert "order_status" not in serialized

    published = await client.post(
        f"/api/v1/service-apps/{app_key}/publish",
        json={"revision": application["revision"]},
    )
    assert published.status_code == 200, published.text
    assert published.json()["version"] == 1
    assert published.json()["config"]["scenarios"][0]["version"] == 1


async def test_blocked_readiness_prevents_application_publish(platform):
    client, _services, _settings = platform
    scenario_key, _scenario = await _create_published_scenario(
        client,
        ready=False,
        with_business_context=False,
    )
    app_key, application = await _create_application(client, scenario_key)

    response = await client.get(f"/api/v1/service-apps/{app_key}/readiness")
    assert response.status_code == 200, response.text
    readiness = response.json()
    assert readiness["status"] == "blocked"
    assert readiness["can_publish"] is False
    assert readiness["can_simulate"] is False
    checks = {item["key"]: item["status"] for item in readiness["scenarios"][0]["checks"]}
    assert checks["business-object"] == "blocked"
    assert checks["business-facts"] == "blocked"

    published = await client.post(
        f"/api/v1/service-apps/{app_key}/publish",
        json={"revision": application["revision"]},
    )
    assert published.status_code == 409
    assert published.json()["detail"] == "service_application_readiness_blocked"
    detail = await client.get(f"/api/v1/service-apps/{app_key}")
    assert detail.json()["status"] == "draft"
    assert detail.json()["revision"] == application["revision"]
    assert detail.json()["published_version"] is None
    versions = await client.get(f"/api/v1/service-apps/{app_key}/versions")
    assert versions.json()["items"] == []


async def test_simulate_only_readiness_prevents_formal_publish(platform):
    client, _services, _settings = platform
    scenario_key, _scenario = await _create_published_scenario(
        client,
        ready=False,
    )
    app_key, application = await _create_application(client, scenario_key)

    response = await client.get(f"/api/v1/service-apps/{app_key}/readiness")
    assert response.status_code == 200, response.text
    readiness = response.json()
    assert readiness["status"] == "simulate_only"
    assert readiness["can_publish"] is False
    assert readiness["can_simulate"] is True
    checks = {item["key"]: item["status"] for item in readiness["scenarios"][0]["checks"]}
    assert checks["human-handoff"] == "warning"

    published = await client.post(
        f"/api/v1/service-apps/{app_key}/publish",
        json={"revision": application["revision"]},
    )
    assert published.status_code == 409
    assert published.json()["detail"] == "service_application_readiness_simulate_only"
    detail = await client.get(f"/api/v1/service-apps/{app_key}")
    assert detail.json()["status"] == "draft"
    assert detail.json()["revision"] == application["revision"]
    assert detail.json()["published_version"] is None
    versions = await client.get(f"/api/v1/service-apps/{app_key}/versions")
    assert versions.json()["items"] == []


async def test_readiness_uses_reader_permission_and_persisted_scope(platform):
    client, services, settings = platform
    scenario_key, _scenario = await _create_published_scenario(client)
    app_key, application = await _create_application(client, scenario_key)

    viewer_headers = {"Authorization": "Bearer platform-viewer"}
    readable = await client.get(
        f"/api/v1/service-apps/{app_key}/readiness",
        headers=viewer_headers,
    )
    assert readable.status_code == 200, readable.text
    denied = await client.post(
        f"/api/v1/service-apps/{app_key}/publish",
        json={"revision": application["revision"]},
        headers=viewer_headers,
    )
    assert denied.status_code == 403

    applications = services.groups.business.service_apps
    other_workspace = BusinessScope(
        tenant_id=settings.tenant_id,
        business_id="customer-service",
        workspace_id="another-workspace",
    )
    with pytest.raises(DomainError) as missing:
        await applications.readiness(
            settings.tenant_id,
            app_key,
            scope=other_workspace,
        )
    assert missing.value.status == 404

    foreign_scope = BusinessScope(
        tenant_id="another-tenant",
        business_id="customer-service",
        workspace_id="default",
    )
    with pytest.raises(DomainError) as foreign:
        await applications.readiness(
            settings.tenant_id,
            app_key,
            scope=foreign_scope,
        )
    assert foreign.value.status == 403
