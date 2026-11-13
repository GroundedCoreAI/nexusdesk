"""API-level immutability and safety checks for side-effect-free previews."""

from uuid import uuid4

import pytest
from test_platform_postgres import create_agent
from test_platform_postgres import platform as _platform

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


class PreviewRunnerSpy:
    def __init__(self, settings):
        self.settings = settings
        self.contexts = []

    async def preview_application(self, context, message, *, allow_write):
        self.contexts.append(
            {
                "context": context,
                "message": message,
                "allow_write": allow_write,
            }
        )
        return {"reply": "预览执行完成。", "tools": [], "violations": []}


async def _create_application(client, agent, *, key=None):
    application_key = key or "preview-" + uuid4().hex[:12]
    response = await client.post(
        "/api/v1/service-apps",
        json={
            "key": application_key,
            "name": "预览测试应用",
            "description": "",
            "agent_id": agent["id"],
            "agent_version": 1,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _add_handoff_skill(client, application_key):
    response = await client.post(
        f"/api/v1/service-apps/{application_key}/skills",
        json={
            "key": "handoff",
            "name": "转人工",
            "type": "handoff",
            "description": "进入人工队列",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _publish(client, application_key):
    detail = (await client.get(f"/api/v1/service-apps/{application_key}")).json()
    response = await client.post(
        f"/api/v1/service-apps/{application_key}/publish",
        json={"revision": detail["revision"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _add_http_connection(client, application_key):
    response = await client.post(
        f"/api/v1/service-apps/{application_key}/connections",
        json={
            "key": "tickets",
            "name": "工单接口",
            "executor_kind": "http",
            "endpoint": "https://business.example.com/tickets",
            "method": "POST",
            "public_headers": {},
            "auth_kind": "none",
            "timeout_seconds": 5,
            "max_response_bytes": 2048,
            "config": {},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _add_write_skill(client, application_key):
    response = await client.post(
        f"/api/v1/service-apps/{application_key}/skills",
        json={
            "key": "ticket_create",
            "name": "创建工单",
            "type": "action",
            "connection_key": "tickets",
            "write_operation": True,
            "safety": {"requires_confirmation": True},
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
            },
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _update_application(client, application_key, detail, **overrides):
    payload = {
        "agent_id": detail["agent_id"],
        "agent_version": detail["agent_version"],
        "revision": detail["revision"],
        **overrides,
    }
    response = await client.put(
        f"/api/v1/service-apps/{application_key}",
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_versioned_experience_uses_the_published_snapshot(platform):
    client, _, _ = platform
    agent, _ = await create_agent(client)
    application = await _create_application(client, agent)

    draft = (await client.get(
        f"/api/v1/service-apps/{application['key']}/experience",
    )).json()
    updated = await client.put(
        f"/api/v1/service-apps/{application['key']}/experience",
        json={
            "revision": draft["revision"],
            "experience": {"welcome_text": "发布版本欢迎语"},
        },
    )
    assert updated.status_code == 200, updated.text
    await _publish(client, application["key"])

    detail = (await client.get(
        f"/api/v1/service-apps/{application['key']}/experience",
    )).json()
    changed = await client.put(
        f"/api/v1/service-apps/{application['key']}/experience",
        json={
            "revision": detail["revision"],
            "experience": {"welcome_text": "当前草稿欢迎语"},
        },
    )
    assert changed.status_code == 200, changed.text

    published = await client.get(
        f"/api/v1/service-apps/{application['key']}/experience?version=1",
    )
    assert published.status_code == 200, published.text
    assert published.json()["version"] == 1
    assert published.json()["immutable"] is True
    assert published.json()["experience"]["welcome_text"] == "发布版本欢迎语"

    draft_response = await client.get(
        f"/api/v1/service-apps/{application['key']}/experience",
    )
    assert draft_response.status_code == 200, draft_response.text
    assert draft_response.json()["experience"]["welcome_text"] == "当前草稿欢迎语"


async def test_frozen_release_preview_uses_release_agent_and_rules(platform, monkeypatch):
    client, runtime, settings = platform
    original_agent, _ = await create_agent(client)
    application = await _create_application(client, original_agent)
    await _add_handoff_skill(client, application["key"])
    first_release = await _publish(client, application["key"])
    assert first_release["published_version"] == 1

    replacement_agent, _ = await create_agent(client)
    detail = (await client.get(f"/api/v1/service-apps/{application['key']}")).json()
    updated = await _update_application(
        client,
        application["key"],
        detail,
        agent_id=replacement_agent["id"],
        agent_version=1,
        rules={
            "fallback": "handoff",
            "handoff_queue": "customer-service",
            "handoff_message": "草稿规则",
            "require_confirmation": True,
            "preview_write_enabled": True,
            "validate_results": True,
        },
    )
    assert updated["agent_id"] == replacement_agent["id"]

    spy = PreviewRunnerSpy(settings)
    runner = runtime.groups.business.service_apps.preview_runner
    monkeypatch.setattr(runner, "preview_application", spy.preview_application)
    settings.service_app_preview_write_enabled = True

    frozen_write = await client.post(
        f"/api/v1/service-apps/{application['key']}/preview",
        json={"message": "测试写预览", "version": 1, "allow_write": True},
    )
    assert frozen_write.status_code == 403, frozen_write.text
    assert frozen_write.json()["detail"] == "service_application_preview_write_disabled"

    frozen = await client.post(
        f"/api/v1/service-apps/{application['key']}/preview",
        json={"message": "测试固定版本", "version": 1},
    )
    assert frozen.status_code == 200, frozen.text
    frozen_context = spy.contexts[-1]["context"]
    assert str(frozen_context.agent_id) == original_agent["id"]
    assert frozen_context.agent_version == 1
    assert frozen.json()["trace"]["agent_id"] == original_agent["id"]
    assert frozen.json()["trace"]["agent_version"] == 1
    assert frozen.json()["trace"]["upstream_called"] is False

    draft = await client.post(
        f"/api/v1/service-apps/{application['key']}/preview",
        json={"message": "测试当前草稿", "allow_write": True},
    )
    assert draft.status_code == 200, draft.text
    draft_context = spy.contexts[-1]["context"]
    assert str(draft_context.agent_id) == replacement_agent["id"]
    assert draft_context.agent_version == 1
    assert draft.json()["draft"] is True


async def test_preview_excludes_write_skills_unless_both_gates_allow_them(
    platform,
    monkeypatch,
):
    client, runtime, settings = platform
    agent, _ = await create_agent(client)
    application = await _create_application(client, agent)
    await _add_http_connection(client, application["key"])
    await _add_write_skill(client, application["key"])

    spy = PreviewRunnerSpy(settings)
    runner = runtime.groups.business.service_apps.preview_runner
    monkeypatch.setattr(runner, "preview_application", spy.preview_application)

    read_only = await client.post(
        f"/api/v1/service-apps/{application['key']}/preview",
        json={"message": "默认预览"},
    )
    assert read_only.status_code == 200, read_only.text
    preview_context = spy.contexts[-1]["context"]
    assert preview_context.skills == ()
    assert preview_context.connections == ()
    assert read_only.json()["trace"]["upstream_called"] is False

    setting_only = await client.post(
        f"/api/v1/service-apps/{application['key']}/preview",
        json={"message": "测试写预览", "allow_write": True},
    )
    assert setting_only.status_code == 403, setting_only.text

    detail = (await client.get(f"/api/v1/service-apps/{application['key']}")).json()
    await _update_application(
        client,
        application["key"],
        detail,
        rules={
            "fallback": "handoff",
            "handoff_queue": "customer-service",
            "handoff_message": "",
            "require_confirmation": True,
            "preview_write_enabled": True,
            "validate_results": True,
        },
    )

    application_only = await client.post(
        f"/api/v1/service-apps/{application['key']}/preview",
        json={"message": "测试写预览", "allow_write": True},
    )
    assert application_only.status_code == 403, application_only.text

    settings.service_app_preview_write_enabled = True
    enabled = await client.post(
        f"/api/v1/service-apps/{application['key']}/preview",
        json={"message": "测试写预览", "allow_write": True},
    )
    assert enabled.status_code == 200, enabled.text
    enabled_context = spy.contexts[-1]["context"]
    assert [skill["key"] for skill in enabled_context.skills] == ["ticket_create"]
    assert [connection["key"] for connection in enabled_context.connections] == ["tickets"]
    assert enabled.json()["trace"]["upstream_called"] is False
