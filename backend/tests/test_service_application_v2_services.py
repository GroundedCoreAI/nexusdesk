import asyncio
import json
from uuid import uuid4

import pytest
from test_platform_postgres import (
    create_agent,
    create_published_application,
    execute_next,
)
from test_platform_postgres import platform as _platform

from agent_platform.core_platform.platform_services.persistence.store import execute, one

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


async def _create_application(client, agent, *, key=None, name="测试应用"):
    application_key = key or "test-app-" + uuid4().hex[:12]
    response = await client.post(
        "/api/v1/service-apps",
        json={
            "key": application_key,
            "name": name,
            "description": "",
            "agent_id": agent["id"],
            "agent_version": 1,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _add_handoff_skill(client, application_key, *, skill_key="handoff"):
    response = await client.post(
        f"/api/v1/service-apps/{application_key}/skills",
        json={
            "key": skill_key,
            "name": "转人工",
            "type": "handoff",
            "description": "需要人工处理时进入默认队列",
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


async def _add_http_connection(client, application_key, *, connection_key="orders"):
    response = await client.post(
        f"/api/v1/service-apps/{application_key}/connections",
        json={
            "key": connection_key,
            "name": "订单接口",
            "executor_kind": "http",
            "endpoint": "https://business.example.com/orders",
            "method": "GET",
            "public_headers": {},
            "auth_kind": "bearer",
            "timeout_seconds": 5,
            "max_response_bytes": 2048,
            "config": {},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _add_query_skill(client, application_key, *, connection_key="orders"):
    response = await client.post(
        f"/api/v1/service-apps/{application_key}/skills",
        json={
            "key": "order_lookup",
            "name": "订单查询",
            "type": "query",
            "connection_key": connection_key,
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"order_no": {"type": "string"}},
                "required": ["order_no"],
            },
            "result_schema": {"type": "object", "additionalProperties": True},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _wait_for_inbound(services, channel_id, *, limit=80):
    event = None
    for _ in range(limit):
        async with services.groups.runtime.engine.connect() as connection:
            event = await one(
                connection,
                """
SELECT id,status,conversation_id,run_id,error_code,application_id,application_version
FROM channel_inbound_events
WHERE channel_id=:channel
ORDER BY created_at DESC
LIMIT 1
""",
                channel=channel_id,
            )
        if event and event["status"] == "processed" and event["run_id"]:
            return event
        if event and event["status"] == "failed":
            raise AssertionError(f"inbound failed: {event['error_code']}")
        await asyncio.sleep(0.1)
    raise AssertionError(f"inbound not processed: {event}")


def _assert_no_plaintext(payload, secret):
    serialized = json.dumps(payload, ensure_ascii=False, default=str)
    assert secret not in serialized
    assert "encrypted_secret" not in serialized


async def test_examples_are_immutable_and_copy_into_user_owned_application(platform):
    client, runtime, settings = platform
    agent, _ = await create_agent(client)
    result = await runtime.groups.business.service_apps.seed_defaults(
        settings.tenant_id,
        actor="test-seed",
    )
    assert result["applications"] == 4
    repeated = await runtime.groups.business.service_apps.seed_defaults(
        settings.tenant_id,
        actor="test-seed",
    )
    assert repeated["applications"] == 0

    examples = (await client.get("/api/v1/service-apps?origin=example")).json()
    source = examples["items"][0]
    update = await client.put(
        f"/api/v1/service-apps/{source['key']}",
        json={
            "name": "不应修改的示例",
            "description": "",
            "agent_id": agent["id"],
            "agent_version": 1,
            "revision": source["revision"],
        },
    )
    assert update.status_code == 403, update.text
    assert update.json()["detail"] == "service_application_example_immutable"

    default_key = source["key"].removeprefix("example-") + "-copy"
    default_copy = await client.post(
        f"/api/v1/service-apps/{source['key']}/copy",
        json={"name": "默认命名的副本"},
    )
    assert default_copy.status_code == 201, default_copy.text
    assert default_copy.json()["key"] == default_key

    copied_key = "user-copy-" + uuid4().hex[:10]
    copied = await client.post(
        f"/api/v1/service-apps/{source['key']}/copy",
        json={"key": copied_key, "name": "我的客服应用"},
    )
    assert copied.status_code == 201, copied.text
    body = copied.json()
    assert body["origin"] == "user"
    assert body["immutable"] is False
    assert body["is_example"] is False
    assert body["template_key"] == source["template_key"]
    assert body["published_version"] is None

    updated = await client.put(
        f"/api/v1/service-apps/{copied_key}",
        json={
            "name": "我的客服应用（已编辑）",
            "description": "",
            "agent_id": agent["id"],
            "agent_version": 1,
            "revision": body["revision"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "我的客服应用（已编辑）"


async def test_examples_initialize_distinct_experience_and_copy_inherits_it(platform):
    client, runtime, settings = platform
    await create_agent(client)
    result = await runtime.groups.business.service_apps.seed_defaults(
        settings.tenant_id,
        actor="test-seed",
    )
    assert result["applications"] == 4
    assert result["updated"] == 0
    repeated = await runtime.groups.business.service_apps.seed_defaults(
        settings.tenant_id,
        actor="test-seed",
    )
    assert repeated["updated"] == 0

    examples = (await client.get("/api/v1/service-apps?origin=example&page_size=10")).json()
    by_key = {item["key"]: item for item in examples["items"]}
    shopping = by_key["example-shopping-support"]
    game = by_key["example-game-player-support"]
    shopping_experience = (
        await client.get(f"/api/v1/service-apps/{shopping['key']}/experience")
    ).json()
    game_experience = (await client.get(f"/api/v1/service-apps/{game['key']}/experience")).json()
    assert shopping_experience["immutable"] is True
    assert game_experience["immutable"] is True
    assert {category["label"] for category in shopping_experience["experience"]["categories"]} != {
        category["label"] for category in game_experience["experience"]["categories"]
    }
    assert shopping_experience["experience"]["categories"][1]["entries"][1]["binding"] == (
        "refund_create"
    )

    copied = await client.post(
        f"/api/v1/service-apps/{shopping['key']}/copy",
        json={"key": "experience-copy-" + uuid4().hex[:8], "name": "客户交互副本"},
    )
    assert copied.status_code == 201, copied.text
    copied_key = copied.json()["key"]
    copied_experience = (await client.get(f"/api/v1/service-apps/{copied_key}/experience")).json()
    assert copied_experience["immutable"] is False
    assert (
        copied_experience["experience"]["welcome_text"]
        == (shopping_experience["experience"]["welcome_text"])
    )

    payload = copied_experience["experience"]
    payload["welcome_text"] = "您好，这里是后端持久化后的欢迎语。"
    updated = await client.put(
        f"/api/v1/service-apps/{copied_key}/experience",
        json={"experience": payload, "revision": copied_experience["revision"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == copied_experience["revision"] + 1
    assert updated.json()["experience"]["welcome_text"] == payload["welcome_text"]

    published = await _publish(client, copied_key)
    version = (await client.get(f"/api/v1/service-apps/{copied_key}/versions?page_size=10")).json()[
        "items"
    ][0]
    assert version["config"]["experience"]["welcome_text"] == payload["welcome_text"]
    assert published["published_version"] == 1


async def test_seed_refreshes_outdated_example_draft_without_touching_user_copies(platform):
    client, runtime, settings = platform
    await create_agent(client)
    await runtime.groups.business.service_apps.seed_defaults(
        settings.tenant_id,
        actor="test-seed",
    )
    shopping = (await client.get("/api/v1/service-apps/example-shopping-support")).json()
    copy = await client.post(
        "/api/v1/service-apps/example-shopping-support/copy",
        json={"key": "seed-refresh-copy-" + uuid4().hex[:8], "name": "不应刷新的副本"},
    )
    assert copy.status_code == 201, copy.text
    copied_experience = (
        await client.get(f"/api/v1/service-apps/{copy.json()['key']}/experience")
    ).json()

    async with runtime.groups.business.service_apps.engine.begin() as connection:
        await execute(
            connection,
            """
UPDATE service_applications
SET template_version='2026-11-12',draft=draft - 'experience'
WHERE tenant_id=:tenant AND application_key='example-shopping-support'
""",
            tenant=settings.tenant_id,
        )
    refreshed = await runtime.groups.business.service_apps.seed_defaults(
        settings.tenant_id,
        actor="test-seed",
    )
    assert refreshed["updated"] == 1
    current = (await client.get("/api/v1/service-apps/example-shopping-support/experience")).json()
    assert current["experience"]["categories"]
    assert current["revision"] > shopping["revision"]

    unchanged_copy = (
        await client.get(f"/api/v1/service-apps/{copy.json()['key']}/experience")
    ).json()
    assert unchanged_copy["experience"] == copied_experience["experience"]


async def test_unpublished_agent_cannot_be_bound_to_an_application(platform):
    client, _runtime, _settings = platform
    agent, _ = await create_agent(client, publish=False)
    response = await client.post(
        "/api/v1/service-apps",
        json={
            "key": "unpublished-" + uuid4().hex[:10],
            "name": "未发布 Agent 应用",
            "agent_id": agent["id"],
            "agent_version": 1,
        },
    )
    # An unpublished Agent has no persisted version yet, so the service rejects
    # the missing version before it can reach the separate "not published" guard.
    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "service_application_agent_version_not_found"


async def test_readiness_requires_agent_version_connection_and_credentials(platform):
    client, _runtime, _settings = platform
    agent, _ = await create_agent(client)
    application = await _create_application(client, agent, name="就绪检查应用")
    await _add_http_connection(client, application["key"])
    await _add_query_skill(client, application["key"])

    readiness = await client.get(f"/api/v1/service-apps/{application['key']}/readiness")
    assert readiness.status_code == 200, readiness.text
    blocked = readiness.json()
    assert blocked["can_publish"] is False
    assert blocked["status"] == "blocked"
    assert any(
        item["resource"] == "orders" and item["status"] == "blocked" for item in blocked["checks"]
    )
    publish = await client.post(
        f"/api/v1/service-apps/{application['key']}/publish",
        json={"revision": blocked["revision"]},
    )
    assert publish.status_code == 409, publish.text
    assert publish.json()["detail"] == "service_application_readiness_blocked"

    secret = "readiness-secret-value"
    credential = await client.put(
        f"/api/v1/service-apps/{application['key']}/connections/orders/credentials",
        json={"credentials": {"type": "bearer", "token": secret}},
    )
    assert credential.status_code == 200, credential.text
    assert credential.json()["credentials_configured"] is True
    assert secret not in credential.text

    ready = (await client.get(f"/api/v1/service-apps/{application['key']}/readiness")).json()
    assert ready["can_publish"] is True
    assert ready["status"] == "pass"


async def test_credentials_are_write_only_and_reads_never_echo_plaintext(platform):
    client, _runtime, _settings = platform
    agent, _ = await create_agent(client)
    application = await _create_application(client, agent, name="凭据测试应用")
    await _add_http_connection(client, application["key"])
    secret = "credential-" + uuid4().hex

    saved = await client.put(
        f"/api/v1/service-apps/{application['key']}/connections/orders/credentials",
        json={"credentials": {"type": "bearer", "token": secret}},
    )
    assert saved.status_code == 200, saved.text
    assert secret not in saved.text

    detail = (await client.get(f"/api/v1/service-apps/{application['key']}")).json()
    connections = (
        await client.get(f"/api/v1/service-apps/{application['key']}/connections")
    ).json()
    _assert_no_plaintext(detail, secret)
    _assert_no_plaintext(connections, secret)
    assert connections["items"][0]["credentials_configured"] is True
    assert "encrypted_secret" not in connections["items"][0]


async def test_rollback_appends_a_new_release_without_plaintext(platform):
    client, _runtime, _settings = platform
    agent, _ = await create_agent(client)
    application = await _create_application(client, agent, name="发布与回滚应用")
    await _add_http_connection(client, application["key"])
    await _add_query_skill(client, application["key"])
    await _add_handoff_skill(client, application["key"])
    secret = "release-secret-" + uuid4().hex
    saved = await client.put(
        f"/api/v1/service-apps/{application['key']}/connections/orders/credentials",
        json={"credentials": {"type": "bearer", "token": secret}},
    )
    assert saved.status_code == 200, saved.text

    first = await _publish(client, application["key"])
    assert first["published_version"] == 1
    assert first["config_digest"].startswith("sha256:")
    _assert_no_plaintext(first, secret)

    await _add_handoff_skill(client, application["key"], skill_key="human_takeover")
    detail = (await client.get(f"/api/v1/service-apps/{application['key']}")).json()
    second = await client.post(
        f"/api/v1/service-apps/{application['key']}/publish",
        json={"revision": detail["revision"]},
    )
    assert second.status_code == 200, second.text
    assert second.json()["published_version"] == 2
    target_revision = detail["revision"]

    versions = (
        await client.get(f"/api/v1/service-apps/{application['key']}/versions?page_size=10")
    ).json()
    assert versions["total"] == 2
    by_version = {item["version"]: item for item in versions["items"]}
    assert by_version[1]["config_digest"] != by_version[2]["config_digest"]
    _assert_no_plaintext(versions, secret)

    rolled_back = await client.post(
        f"/api/v1/service-apps/{application['key']}/rollback",
        json={"version": 1, "revision": target_revision},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    assert rolled_back.json()["published_version"] == 3
    assert rolled_back.json()["source_version"] == 1
    _assert_no_plaintext(rolled_back.json(), secret)

    appended = (
        await client.get(f"/api/v1/service-apps/{application['key']}/versions?page_size=10")
    ).json()
    assert appended["total"] == 3
    rolled = next(item for item in appended["items"] if item["version"] == 3)
    assert rolled["source_version"] == 1
    assert rolled["config_digest"] == by_version[1]["config_digest"]


async def test_same_agent_applications_keep_skills_isolated(platform):
    client, _runtime, _settings = platform
    agent, _ = await create_agent(client)
    first = await _create_application(client, agent, name="应用一")
    second = await _create_application(client, agent, name="应用二")
    await _add_handoff_skill(client, first["key"], skill_key="first_handoff")
    await _add_handoff_skill(client, second["key"], skill_key="second_handoff")
    await _publish(client, first["key"])
    await _publish(client, second["key"])

    first_skills = (await client.get(f"/api/v1/service-apps/{first['key']}/skills")).json()
    second_skills = (await client.get(f"/api/v1/service-apps/{second['key']}/skills")).json()
    assert {item["key"] for item in first_skills["items"]} == {"first_handoff"}
    assert {item["key"] for item in second_skills["items"]} == {"second_handoff"}

    first_versions = (await client.get(f"/api/v1/service-apps/{first['key']}/versions")).json()
    second_versions = (await client.get(f"/api/v1/service-apps/{second['key']}/versions")).json()
    assert {item["key"] for item in first_versions["items"][0]["config"]["skills"]} == {
        "first_handoff"
    }
    assert {item["key"] for item in second_versions["items"][0]["config"]["skills"]} == {
        "second_handoff"
    }


async def test_channels_pin_a_published_application_version(platform):
    client, _runtime, _settings = platform
    agent, _ = await create_agent(client)
    application = await _create_application(client, agent, name="渠道版本应用")
    await _add_handoff_skill(client, application["key"])
    await _publish(client, application["key"])

    missing_version = await client.post(
        "/api/v1/channels",
        json={
            "name": "缺少版本",
            "application_id": application["id"],
        },
    )
    assert missing_version.status_code == 422

    channel = await client.post(
        "/api/v1/channels",
        json={
            "name": "固定版本渠道",
            "application_id": application["id"],
            "application_version": 1,
        },
    )
    assert channel.status_code == 201, channel.text
    channel_body = channel.json()
    assert channel_body["application_version"] == 1

    await _add_handoff_skill(client, application["key"], skill_key="handoff_v2")
    published = await _publish(client, application["key"])
    assert published["published_version"] == 2
    channels = (await client.get("/api/v1/channels")).json()
    pinned = next(item for item in channels if item["id"] == channel_body["id"])
    assert pinned["application_version"] == 1

    switched = await client.put(
        f"/api/v1/channels/{channel_body['id']}/application-version",
        json={"application_version": 2},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["application_version"] == 2


async def test_conversation_run_and_trace_capture_application_context(platform):
    client, services, settings = platform
    agent, _ = await create_agent(client)
    application = await create_published_application(client, agent)
    channel_response = await client.post(
        "/api/v1/channels",
        json={
            "name": "应用上下文渠道",
            "application_id": application["id"],
            "application_version": application["published_version"],
        },
    )
    assert channel_response.status_code == 201, channel_response.text
    channel = channel_response.json()
    ingress = await client.post(
        f"/api/v1/ingress/channels/{channel['id']}/messages",
        headers={"X-Channel-Token": channel["token"]},
        json={
            "message_id": "context-" + uuid4().hex,
            "session_id": "context-session-" + uuid4().hex,
            "text": "请帮我查询订单",
        },
    )
    assert ingress.status_code == 202, ingress.text
    event = await _wait_for_inbound(services, channel["id"])
    assert str(event["application_id"]) == application["id"]
    assert event["application_version"] == application["published_version"]

    result = await execute_next(services, settings)
    assert result["status"] == "completed", result.get("error_code")
    run_id = event["run_id"]
    async with services.groups.runtime.engine.connect() as connection:
        conversation = await one(
            connection,
            """
SELECT application_id,application_version,agent_id,agent_version
FROM runtime_conversations
WHERE id=:id
""",
            id=event["conversation_id"],
        )
        run = await one(
            connection,
            "SELECT config FROM runtime_runs WHERE id=:id",
            id=run_id,
        )
        trace = await one(
            connection,
            """
SELECT application_id,application_version,conversation_id,run_id,
       agent_id,agent_version,trace
FROM service_application_traces
WHERE run_id=:run
""",
            run=run_id,
        )

    assert str(conversation["application_id"]) == application["id"]
    assert conversation["application_version"] == 1
    assert str(conversation["agent_id"]) == agent["id"]
    assert conversation["agent_version"] == 1
    assert run["config"]["application"]["id"] == application["id"]
    assert run["config"]["application"]["version"] == 1
    assert str(trace["application_id"]) == application["id"]
    assert trace["application_version"] == 1
    assert str(trace["conversation_id"]) == str(event["conversation_id"])
    assert str(trace["run_id"]) == str(run_id)
    assert str(trace["agent_id"]) == agent["id"]
    assert trace["agent_version"] == 1
    assert trace["trace"]["application_key"] == application["key"]

    playground = await client.post(
        "/api/v1/conversations",
        json={
            "external_id": "playground-" + uuid4().hex,
            "agent_id": agent["id"],
            "source": "playground",
        },
    )
    assert playground.status_code == 201, playground.text

    listed = await client.get(
        f"/api/v1/service-apps/{application['key']}/conversations"
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 10
    item = body["items"][0]
    business_conversation_id = item["id"]
    async with services.groups.runtime.engine.connect() as connection:
        business_link = await one(
            connection,
            """
SELECT t.runtime_conversation_id
FROM service_application_turns t
WHERE t.conversation_id=:conversation
ORDER BY t.created_at DESC
LIMIT 1
""",
            conversation=business_conversation_id,
        )
    assert str(business_link["runtime_conversation_id"]) == str(event["conversation_id"])
    assert item["question"] == "请帮我查询订单"
    assert item["channel_id"] == channel["id"]
    assert item["channel_name"] == "应用上下文渠道"
    assert item["source"] == "generic_webhook"
    assert item["status"] == "completed"
    assert item["feedback_type"] is None

    searched = await client.get(
        f"/api/v1/service-apps/{application['key']}/conversations",
        params={"q": "不存在的订单"},
    )
    assert searched.status_code == 200, searched.text
    assert searched.json()["total"] == 0

    detail = await client.get(
        f"/api/v1/service-apps/{application['key']}/conversations/"
        f"{business_conversation_id}"
    )
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body["id"] == business_conversation_id
    assert any(
        message["role"] == "customer" and message["content"] == "请帮我查询订单"
        for message in detail_body["messages"]
    )
    assert detail_body["runs"][0]["id"] == str(run_id)
