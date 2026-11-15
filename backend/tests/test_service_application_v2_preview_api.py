"""API-level checks for previews that run the real customer chain.

A preview opens a ``kind='preview'`` application session and submits the
message through the same routing, queue and worker path a customer message
takes. The tests below assert the persisted trace, source isolation and the
write-skill gates; the worker is driven manually because the platform fixture
runs with ``embedded_worker=False``.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from test_platform_postgres import create_agent
from test_platform_postgres import platform as _platform

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


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


async def _runtime_conversation(runtime, conversation_id):
    async with runtime.groups.runtime.engine.connect() as connection:
        return (
            await connection.execute(
                text(
                    "SELECT source,application_id,application_version,agent_id,agent_version"
                    " FROM runtime_conversations WHERE id=CAST(:id AS uuid)",
                ),
                {"id": conversation_id},
            )
        ).mappings().one()


async def _drive_worker(runtime, settings, run_id):
    row = await runtime.repository.claim(runtime.worker.owner, 30, settings.tenant_id)
    assert row is not None, "run was not queued"
    assert str(row["id"]) == str(run_id)
    await runtime.worker._execute(row)  # noqa: SLF001 - tests drive the worker directly
    return row


async def test_preview_runs_the_real_chain_and_persists_kind_preview(platform):
    client, runtime, settings = platform
    settings.service_app_preview_wait_seconds = 0
    agent, _ = await create_agent(client)
    application = await _create_application(client, agent)

    response = await client.post(
        f"/api/v1/service-apps/{application['key']}/preview",
        json={"message": "预览真实链路", "session_key": "sess-1"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["draft"] is True
    assert payload["trace"]["conversation_id"]
    assert payload["trace"]["ledger_conversation_id"]
    assert payload["trace"]["simulation"] is False
    run_id = payload["trace"]["run_id"]
    assert run_id
    # wait=0: the run is queued but not executed yet.
    assert payload["status"] == "timeout"

    await _drive_worker(runtime, settings, run_id)

    history = (
        await client.get(f"/api/v1/service-apps/{application['key']}/previews")
    ).json()
    assert history["total"] == 1
    item = history["items"][0]
    assert item["run_id"] == run_id
    assert item["status"] == "completed"
    assert item["draft"] is True
    assert item["input"] == "预览真实链路"

    detail = (
        await client.get(
            f"/api/v1/service-apps/{application['key']}/previews/{item['id']}",
        )
    ).json()
    assert detail["status"] == "completed"
    assert isinstance(detail["reply"], str)
    assert detail["trace"]["run_id"] == run_id
    # A refreshed drawer must show the same identity as the live payload: the
    # trace is rebuilt from the run snapshot, not from the summary row.
    assert detail["trace"]["application_key"] == application["key"]
    assert detail["trace"]["application_version"] == (
        payload["trace"]["application_version"]
    )
    assert detail["trace"]["ledger_conversation_id"] == (
        payload["trace"]["ledger_conversation_id"]
    )
    assert detail["trace"]["status"] == "submitted"
    assert detail["trace"]["simulation"] is False
    assert detail["trace"]["skills"] == payload["trace"]["skills"]

    conv = await _runtime_conversation(runtime, payload["trace"]["conversation_id"])
    assert conv["source"] == "debug"

    async with runtime.groups.runtime.engine.connect() as connection:
        ledger_kind = (
            await connection.execute(
                text(
                    "SELECT kind FROM service_application_conversations"
                    " WHERE id=CAST(:id AS uuid)",
                ),
                {"id": payload["trace"]["ledger_conversation_id"]},
            )
        ).scalar()
    assert ledger_kind == "debug"

    # Workbench isolation: the preview conversation never appears in the
    # customer conversation list or counts.
    workbench = (await client.get("/api/v1/conversations?page=1&page_size=50")).json()
    assert all(
        str(item["id"]) != payload["trace"]["conversation_id"]
        for item in workbench["items"]
    )


async def test_preview_session_reuses_the_same_debug_conversation(platform):
    client, runtime, settings = platform
    settings.service_app_preview_wait_seconds = 0
    agent, _ = await create_agent(client)
    application = await _create_application(client, agent)

    first = (
        await client.post(
            f"/api/v1/service-apps/{application['key']}/preview",
            json={"message": "第一句", "session_key": "cont-1"},
        )
    ).json()
    # One active run per conversation (real-chain rule): finish the first
    # debug turn before sending the second, exactly like the drawer does.
    await _drive_worker(runtime, settings, first["trace"]["run_id"])
    second = (
        await client.post(
            f"/api/v1/service-apps/{application['key']}/preview",
            json={"message": "第二句", "session_key": "cont-1"},
        )
    ).json()
    assert second["trace"]["conversation_id"] == first["trace"]["conversation_id"]
    assert second["trace"]["ledger_conversation_id"] == first["trace"]["ledger_conversation_id"]

    fresh = (
        await client.post(
            f"/api/v1/service-apps/{application['key']}/preview",
            json={"message": "新会话", "session_key": "cont-2"},
        )
    ).json()
    assert fresh["trace"]["conversation_id"] != first["trace"]["conversation_id"]

    history = (
        await client.get(f"/api/v1/service-apps/{application['key']}/previews")
    ).json()
    assert history["total"] == 3


async def test_preview_history_filters_by_session_key(platform):
    """A refreshed browser restores only its own session's turns."""

    client, runtime, settings = platform
    settings.service_app_preview_wait_seconds = 0
    agent, _ = await create_agent(client)
    application = await _create_application(client, agent)

    first = (
        await client.post(
            f"/api/v1/service-apps/{application['key']}/preview",
            json={"message": "会话一句", "session_key": "filter-1"},
        )
    ).json()
    await _drive_worker(runtime, settings, first["trace"]["run_id"])
    (
        await client.post(
            f"/api/v1/service-apps/{application['key']}/preview",
            json={"message": "新会话一句", "session_key": "filter-2"},
        )
    )
    # The second turn's run stays queued; the ledger turn exists either way.

    session_history = (
        await client.get(
            f"/api/v1/service-apps/{application['key']}/previews",
            params={"session_key": "filter-1"},
        )
    ).json()
    assert session_history["total"] == 1
    assert session_history["items"][0]["input"] == "会话一句"

    other = (
        await client.get(
            f"/api/v1/service-apps/{application['key']}/previews",
            params={"session_key": "filter-2"},
        )
    ).json()
    assert other["total"] == 1
    assert other["items"][0]["input"] == "新会话一句"

    unknown = (
        await client.get(
            f"/api/v1/service-apps/{application['key']}/previews",
            params={"session_key": "never-used"},
        )
    ).json()
    assert unknown["total"] == 0

    # Without the filter everything (all debug sessions) is listed.
    everything = (
        await client.get(f"/api/v1/service-apps/{application['key']}/previews")
    ).json()
    assert everything["total"] == 2


async def test_frozen_release_preview_pins_release_agent_and_version(platform):
    client, runtime, settings = platform
    settings.service_app_preview_wait_seconds = 0
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
    )
    assert updated["agent_id"] == replacement_agent["id"]

    frozen = await client.post(
        f"/api/v1/service-apps/{application['key']}/preview",
        json={"message": "测试固定版本", "version": 1, "session_key": "frozen"},
    )
    assert frozen.status_code == 200, frozen.text
    frozen_conv = await _runtime_conversation(
        runtime,
        frozen.json()["trace"]["conversation_id"],
    )
    assert str(frozen_conv["agent_id"]) == original_agent["id"]
    assert frozen_conv["agent_version"] == 1
    assert frozen_conv["application_version"] == 1

    draft = await client.post(
        f"/api/v1/service-apps/{application['key']}/preview",
        json={"message": "测试当前草稿", "session_key": "draft"},
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["draft"] is True
    draft_conv = await _runtime_conversation(
        runtime,
        draft.json()["trace"]["conversation_id"],
    )
    assert str(draft_conv["agent_id"]) == replacement_agent["id"]
    assert draft_conv["application_version"] == 0


async def test_preview_excludes_write_skills_unless_both_gates_allow_them(platform):
    client, runtime, settings = platform
    settings.service_app_preview_wait_seconds = 0
    agent, _ = await create_agent(client)
    application = await _create_application(client, agent)
    await _add_http_connection(client, application["key"])
    await _add_write_skill(client, application["key"])

    read_only = await client.post(
        f"/api/v1/service-apps/{application['key']}/preview",
        json={"message": "默认预览"},
    )
    assert read_only.status_code == 200, read_only.text

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


async def test_preview_history_requires_the_application_scope(platform):
    client, runtime, settings = platform
    settings.service_app_preview_wait_seconds = 0
    agent, _ = await create_agent(client)
    application = await _create_application(client, agent)

    missing = await client.get(
        f"/api/v1/service-apps/{application['key']}/previews/{
            uuid4()
        }",
    )
    assert missing.status_code == 404, missing.text
