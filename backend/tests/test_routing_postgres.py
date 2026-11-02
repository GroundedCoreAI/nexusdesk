"""Phase 1 routing decision persistence and API integration tests."""

import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_platform_postgres import create_agent
from test_platform_postgres import platform as _platform

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


@pytest.fixture(autouse=True)
def _enable_trace(platform):
    customer = platform[1].groups.business.customer
    customer.routing_settings = customer.routing_settings.model_copy(update={"trace_enabled": True})


async def _rows(engine, sql: str, **params):
    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        return [dict(row) for row in result.mappings().all()]


async def _conversation(client, *, agent_id=None):
    response = await client.post(
        "/api/v1/conversations",
        json={"external_id": str(uuid4()), "agent_id": agent_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_closed_reject_persists_decision_without_message(platform):
    client, services, _settings = platform
    conversation = await _conversation(client)
    engine = services.repository.engine
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_conversations SET mode='closed' WHERE id=:id"),
            {"id": conversation["id"]},
        )

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "closed session"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "conversation_closed"
    decisions = await _rows(
        engine,
        "SELECT * FROM routing_decisions WHERE conversation_id=:id",
        id=conversation["id"],
    )
    assert len(decisions) == 1
    assert decisions[0]["disposition"] == "reject"
    assert decisions[0]["action"] == "reject"
    assert decisions[0]["reason_code"] == "conversation_closed"
    assert decisions[0]["execution_tier"] is None
    messages = await _rows(
        engine,
        "SELECT id FROM conversation_messages WHERE conversation_id=:id",
        id=conversation["id"],
    )
    assert messages == []


async def test_model_not_configured_reject_persists_decision(platform):
    client, services, settings = platform
    conversation = await _conversation(client)
    customer = services.groups.business.customer
    customer.settings = settings.model_copy(update={"model_backend": "unconfigured"})

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "hello"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "model_not_configured"
    decisions = await _rows(
        services.repository.engine,
        "SELECT * FROM routing_decisions WHERE conversation_id=:id",
        id=conversation["id"],
    )
    assert len(decisions) == 1
    assert decisions[0]["disposition"] == "reject"
    assert decisions[0]["reason_code"] == "model_not_configured"


async def test_english_human_request_records_handoff(platform):
    client, services, _settings = platform
    conversation = await _conversation(client)

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "human"},
    )

    assert response.status_code == 202, response.text
    assert response.json()["run"] is None
    assert response.json()["handoff"] is not None
    decisions = await _rows(
        services.repository.engine,
        "SELECT * FROM routing_decisions WHERE conversation_id=:id",
        id=conversation["id"],
    )
    assert len(decisions) == 1
    assert decisions[0]["disposition"] == "handoff"
    assert decisions[0]["action"] == "request_handoff"
    assert decisions[0]["reason_code"] == "user_requested_human"
    assert decisions[0]["matched_rule_id"] == "en_human_request_001"


async def test_trace_disabled_keeps_reject_contract_without_row(platform):
    client, services, _settings = platform
    conversation = await _conversation(client)
    engine = services.repository.engine
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_conversations SET mode='closed' WHERE id=:id"),
            {"id": conversation["id"]},
        )
    customer = services.groups.business.customer
    customer.routing_settings = customer.routing_settings.model_copy(
        update={"trace_enabled": False}
    )

    response = await client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "closed session"},
    )

    assert response.status_code == 409
    assert (
        await _rows(
            engine,
            "SELECT id FROM routing_decisions WHERE conversation_id=:id",
            id=conversation["id"],
        )
        == []
    )


async def test_decision_write_failure_does_not_break_business(platform):
    client, services, settings = platform
    conversation = await _conversation(client)
    engine = services.repository.engine
    suffix = uuid4().hex
    function_name = f"routing_fail_{suffix}"
    trigger_name = f"routing_fail_{suffix}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                f"CREATE FUNCTION {function_name}() RETURNS trigger LANGUAGE plpgsql AS "
                "$$ BEGIN RAISE EXCEPTION 'injected routing failure'; END; $$"
            )
        )
        await conn.execute(
            text(
                f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON routing_decisions "
                f"FOR EACH ROW EXECUTE FUNCTION {function_name}()"
            )
        )
    try:
        response = await client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            json={"content": "human"},
        )
        assert response.status_code == 202, response.text
        assert response.json()["handoff"] is not None
        assert (
            services.groups.business.customer.routing_write_failure_count(settings.tenant_id) == 1
        )
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name} ON routing_decisions"))
            await conn.execute(text(f"DROP FUNCTION IF EXISTS {function_name}()"))


async def test_routing_decision_list_and_summary(platform):
    client, services, _settings = platform
    conversation = await _conversation(client)
    engine = services.repository.engine
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_conversations SET mode='closed' WHERE id=:id"),
            {"id": conversation["id"]},
        )
    for index in range(3):
        response = await client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            json={"content": f"closed-{index}"},
        )
        assert response.status_code == 409

    first = await client.get(
        f"/api/v1/conversations/{conversation['id']}/routing-decisions",
        params={"limit": 2},
    )
    assert first.status_code == 200, first.text
    first_page = first.json()
    assert len(first_page["items"]) == 2
    assert first_page["next_before"]

    second = await client.get(
        f"/api/v1/conversations/{conversation['id']}/routing-decisions",
        params={"limit": 2, "before": first_page["next_before"]},
    )
    assert second.status_code == 200, second.text
    second_page = second.json()
    assert len(second_page["items"]) == 1
    assert {item["id"] for item in first_page["items"] + second_page["items"]} == {
        str(row["id"])
        for row in await _rows(
            engine,
            "SELECT id FROM routing_decisions WHERE conversation_id=:id",
            id=conversation["id"],
        )
    }

    summary = await client.get("/api/v1/routing-decisions/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["routing_write_failures"] == 0
    assert body["by_disposition"] == [{"key": "reject", "count": 3}]

    invalid = await client.get(
        "/api/v1/routing-decisions/summary",
        params={
            "since": "2026-01-01T00:00:00Z",
            "until": "2026-01-01T00:00:00Z",
        },
    )
    assert invalid.status_code == 422


async def test_closed_channel_message_is_processed_without_retry(platform):
    client, services, _settings = platform
    customer = services.groups.business.customer
    assert services.groups.business.channels.customer is customer
    assert customer.routing_settings.trace_enabled is True
    agent, _ = await create_agent(client)
    channel = (
        await client.post(
            "/api/v1/channels",
            json={
                "name": "Telegram routing 测试",
                "agent_id": agent["id"],
                "provider": "telegram",
                "config": {},
                "credentials": {"bot_token": "123:abc", "secret_token": "shh"},
            },
        )
    ).json()
    engine = services.repository.engine
    url = f"/api/v1/ingress/channels/{channel['id']}/webhook/telegram"
    headers = {
        "content-type": "application/json",
        "x-telegram-bot-api-secret-token": "shh",
    }

    def telegram(update_id: int, message_id: int, text_value: str) -> bytes:
        return json.dumps(
            {
                "update_id": update_id,
                "message": {
                    "message_id": message_id,
                    "from": {"id": 1},
                    "chat": {"id": 2},
                    "text": text_value,
                },
            }
        ).encode()

    first = await client.post(
        url,
        content=telegram(11, 21, "hello"),
        headers=headers,
    )
    assert first.status_code == 200, first.text

    conversation_id = None
    for _ in range(80):
        rows = await _rows(
            engine,
            "SELECT conversation_id FROM channel_conversations WHERE channel_id=:c",
            c=channel["id"],
        )
        if rows:
            conversation_id = rows[0]["conversation_id"]
            break
        await asyncio.sleep(0.1)
    assert conversation_id is not None
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_conversations SET mode='closed' WHERE id=:id"),
            {"id": conversation_id},
        )

    second = await client.post(
        url,
        content=telegram(12, 22, "closed session"),
        headers=headers,
    )
    assert second.status_code == 200, second.text

    event = None
    for _ in range(80):
        rows = await _rows(
            engine,
            "SELECT status,attempts,error_code,run_id,conversation_id"
            " FROM channel_inbound_events"
            " WHERE channel_id=:c AND external_message_id=:m",
            c=channel["id"],
            m="2:22",
        )
        event = rows[0] if rows else None
        if event and event["status"] == "processed":
            break
        if event and event["status"] == "failed":
            raise AssertionError(f"permanent 409 retried until failure: {event}")
        await asyncio.sleep(0.1)
    assert event is not None and event["status"] == "processed", event
    assert event["attempts"] == 1
    assert event["error_code"] is None
    assert event["run_id"] is None
    assert event["conversation_id"] == conversation_id

    receipts = await _rows(
        engine,
        "SELECT run_id FROM channel_receipts WHERE channel_id=:c AND message_id=:m",
        c=channel["id"],
        m="2:22",
    )
    assert len(receipts) == 1
    assert receipts[0]["run_id"] is None

    channel_row = (
        await _rows(
            engine,
            "SELECT last_activity_at,last_error_code FROM channels WHERE id=:c",
            c=channel["id"],
        )
    )[0]
    assert channel_row["last_activity_at"] is not None
    assert channel_row["last_error_code"] is None

    decisions = await _rows(
        engine,
        "SELECT disposition,execution_tier,action,reason_code,matched_rule_id,decider,"
        "message_length,request_id FROM routing_decisions"
        " WHERE conversation_id=:id ORDER BY created_at,id",
        id=conversation_id,
    )
    assert len(decisions) == 2
    by_disposition = {row["disposition"]: row for row in decisions}
    assert set(by_disposition) == {"continue", "reject"}
    assert by_disposition["continue"]["reason_code"] == "default_agent"
    assert by_disposition["continue"]["execution_tier"] == "agent"

    reject = by_disposition["reject"]
    assert reject["action"] == "reject"
    assert reject["reason_code"] == "conversation_closed"
    assert reject["execution_tier"] is None
    assert reject["matched_rule_id"] is None
    assert reject["decider"] == "cs_routing_v1"
    assert reject["message_length"] == len("closed session")
    assert reject["request_id"] is not None
