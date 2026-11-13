import importlib.util
import inspect
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_platform_postgres import (
    create_agent,
    create_published_application,
    execute_next,
)
from test_platform_postgres import platform as _platform

from agent_platform.business_capabilities.customer_service.service_apps.business_conversations import (
    BusinessConversationService,
)
from agent_platform.business_capabilities.customer_service.service_apps.conversations import (
    ApplicationConversationService,
)
from agent_platform.core_platform.platform_services.integrations.channels.base import (
    IncomingEnvelope,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError, one
from agent_platform.extension_contracts import BusinessScope

platform = _platform
pytestmark = pytest.mark.postgres

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "0059_service_application_conversation_ledger.py"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "service_application_conversation_ledger",
        MIGRATION_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_0059_declares_shared_ledger_tables_and_short_revision():
    module = _migration_module()
    assert module.revision == "0059_service_app_conversation"
    assert len(module.revision) <= 32
    assert module.down_revision == "0058_service_application_v2"

    upgrade = inspect.getsource(module.upgrade).lower()
    for table in (
        "service_application_conversations",
        "service_application_messages",
        "service_application_turns",
    ):
        assert f"create table {table}" in upgrade
    assert "kind in ('customer', 'debug')" in upgrade
    assert "runtime_run_id uuid null unique" in upgrade
    assert "idempotency_key" in upgrade
    assert "r.source='business'" in upgrade


async def _create_channel(client, agent):
    application = await create_published_application(client, agent)
    response = await client.post(
        "/api/v1/channels",
        json={
            "name": "对话账本测试渠道",
            "application_id": application["id"],
            "application_version": application["published_version"],
            "provider": "generic_webhook",
            "config": {},
            "credentials": {},
        },
    )
    assert response.status_code == 201, response.text
    return application, response.json()


@pytest.mark.asyncio
async def test_channel_run_materializes_customer_ledger_and_excludes_debug(platform):
    client, services, settings = platform
    agent, _ = await create_agent(client)
    application, channel_response = await _create_channel(client, agent)

    async with services.groups.runtime.engine.connect() as connection:
        channel = await one(
            connection,
            "SELECT * FROM channels WHERE id=:id",
            id=channel_response["id"],
        )
        application_row = await one(
            connection,
            "SELECT id FROM service_applications WHERE application_key=:key",
            key=application["key"],
        )

    envelope = IncomingEnvelope(
        external_message_id="ledger-message-1",
        external_conversation_id="ledger-session-1",
        external_user_id="customer-1",
        external_thread_id=None,
        text="请帮我查询订单",
        target={"user_name": "张小明"},
    )
    accepted = await services.groups.business.channels._accept_envelope(
        channel,
        envelope,
        application_id=application["id"],
        application_version=application["published_version"],
        scope=BusinessScope(
            tenant_id=settings.tenant_id,
            business_id=channel["business_id"],
            workspace_id=channel["workspace_id"],
        ),
    )
    assert accepted["run_id"] is not None

    duplicate = await services.groups.business.channels._accept_envelope(
        channel,
        envelope,
        application_id=application["id"],
        application_version=application["published_version"],
        scope=BusinessScope(
            tenant_id=settings.tenant_id,
            business_id=channel["business_id"],
            workspace_id=channel["workspace_id"],
        ),
    )
    assert duplicate["duplicate"] is True

    async with services.groups.runtime.engine.connect() as connection:
        conversation = await one(
            connection,
            """
            SELECT *
            FROM service_application_conversations
            WHERE application_id=:application
              AND kind='customer'
              AND channel_id=:channel
              AND external_conversation_id=:external
            """,
            application=application_row["id"],
            channel=channel["id"],
            external=envelope.external_conversation_id,
        )
        messages = await connection.execute(
            text(
                """
                SELECT role,content
                FROM service_application_messages
                WHERE conversation_id=:conversation
                ORDER BY seq
                """
            ),
            {"conversation": conversation["id"]},
        )
        assert [(row.role, row.content) for row in messages.mappings()] == [
            ("customer", envelope.text)
        ]

    run = await execute_next(services, settings)
    assert run["status"] == "completed"

    async with services.groups.runtime.engine.connect() as connection:
        messages = await connection.execute(
            text(
                """
                SELECT role,content
                FROM service_application_messages
                WHERE conversation_id=:conversation
                ORDER BY seq
                """
            ),
            {"conversation": conversation["id"]},
        )
        turns = await connection.execute(
            text(
                """
                SELECT status,assistant_message_id,runtime_run_id
                FROM service_application_turns
                WHERE conversation_id=:conversation
                """
            ),
            {"conversation": conversation["id"]},
        )
        message_rows = [dict(row) for row in messages.mappings()]
        turn_rows = [dict(row) for row in turns.mappings()]

    assert [row["role"] for row in message_rows] == ["customer", "assistant"]
    assert len(turn_rows) == 1
    assert turn_rows[0]["status"] == "completed"
    assert turn_rows[0]["assistant_message_id"] is not None
    assert str(turn_rows[0]["runtime_run_id"]) == str(run["id"])

    debug_conversation = None
    async with services.groups.runtime.engine.begin() as connection:
        debug_conversation = await BusinessConversationService.ensure_conversation(
            connection,
            tenant=settings.tenant_id,
            scope=BusinessScope(
                tenant_id=settings.tenant_id,
                business_id=channel["business_id"],
                workspace_id=channel["workspace_id"],
            ),
            application_id=application_row["id"],
            kind="debug",
            external_conversation_id="debug-conversation-" + uuid4().hex,
            agent_id=agent["id"],
            agent_version=1,
            created_by="test",
        )
        await BusinessConversationService.append_message(
            connection,
            debug_conversation,
            role="customer",
            content="客户界面调试会话不应出现",
        )

    listed = await client.get(
        f"/api/v1/service-apps/{application['key']}/conversations",
        params={"page": 1, "page_size": 10, "status": "all"},
    )
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["total"] == 1
    assert payload["items"][0]["kind"] == "customer"
    assert payload["items"][0]["turn_count"] == 1
    assert payload["items"][0]["last_turn_status"] == "completed"

    detail = await client.get(
        f"/api/v1/service-apps/{application['key']}/conversations/"
        f"{conversation['id']}"
    )
    assert detail.status_code == 200, detail.text
    detail_payload = detail.json()
    assert [message["role"] for message in detail_payload["messages"]] == [
        "customer",
        "assistant",
    ]
    assert detail_payload["turns"][0]["runtime_run_id"] == str(run["id"])
    assert detail_payload["runs"][0]["id"] == str(run["id"])

    with pytest.raises(DomainError) as error:
        await ApplicationConversationService(services.groups.runtime.engine).list(
            settings.tenant_id,
            application["key"],
            scope=BusinessScope(
                tenant_id=settings.tenant_id,
                business_id="other-business",
                workspace_id=channel["workspace_id"],
            ),
        )
    assert error.value.status == 404


@pytest.mark.asyncio
async def test_runtime_failure_marks_business_turn_failed(platform):
    client, services, settings = platform
    agent, _ = await create_agent(client)
    application, channel_response = await _create_channel(client, agent)

    async with services.groups.runtime.engine.connect() as connection:
        channel = await one(
            connection,
            "SELECT * FROM channels WHERE id=:id",
            id=channel_response["id"],
        )

    envelope = IncomingEnvelope(
        external_message_id="ledger-failure-1",
        external_conversation_id="ledger-failure-session-1",
        external_user_id="customer-1",
        external_thread_id=None,
        text="触发失败测试",
        target={},
    )
    accepted = await services.groups.business.channels._accept_envelope(
        channel,
        envelope,
        application_id=application["id"],
        application_version=application["published_version"],
        scope=BusinessScope(
            tenant_id=settings.tenant_id,
            business_id=channel["business_id"],
            workspace_id=channel["workspace_id"],
        ),
    )
    claimed = await services.repository.claim(
        services.worker.owner,
        30,
        settings.tenant_id,
    )
    assert claimed is not None
    assert str(claimed["id"]) == str(accepted["run_id"])

    await services.repository.finish(
        claimed["id"],
        services.worker.owner,
        "failed",
        error="controlled_failure",
    )

    async with services.groups.runtime.engine.connect() as connection:
        turn = await one(
            connection,
            """
            SELECT status,error_code
            FROM service_application_turns
            WHERE runtime_run_id=:run
            """,
            run=accepted["run_id"],
        )
    assert turn["status"] == "failed"
    assert turn["error_code"] == "controlled_failure"

    listed = await client.get(
        f"/api/v1/service-apps/{application['key']}/conversations"
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "failed"
    assert items[0]["last_turn_status"] == "failed"


@pytest.mark.asyncio
async def test_human_reply_is_mirrored_to_customer_business_ledger(platform):
    client, services, settings = platform
    agent, _ = await create_agent(client)
    application, channel_response = await _create_channel(client, agent)

    async with services.groups.runtime.engine.connect() as connection:
        channel = await one(
            connection,
            "SELECT * FROM channels WHERE id=:id",
            id=channel_response["id"],
        )

    envelope = IncomingEnvelope(
        external_message_id="ledger-human-1",
        external_conversation_id="ledger-human-session-1",
        external_user_id="customer-1",
        external_thread_id=None,
        text="我要人工客服",
        target={},
    )
    accepted = await services.groups.business.channels._accept_envelope(
        channel,
        envelope,
        application_id=application["id"],
        application_version=application["published_version"],
        scope=BusinessScope(
            tenant_id=settings.tenant_id,
            business_id=channel["business_id"],
            workspace_id=channel["workspace_id"],
        ),
    )
    run = await execute_next(services, settings)
    assert run["status"] == "completed"

    handoff_response = await client.post(
        f"/api/v1/conversations/{accepted['conversation_id']}/handoffs",
        json={"reason": "客户要求人工"},
    )
    assert handoff_response.status_code == 200, handoff_response.text
    handoff = handoff_response.json()
    claimed = await client.post(
        f"/api/v1/handoffs/{handoff['id']}/transition",
        json={"operation": "claim", "assignee": "客服甲"},
    )
    assert claimed.status_code == 200, claimed.text
    replied = await client.post(
        f"/api/v1/conversations/{accepted['conversation_id']}/human-replies",
        json={"content": "人工客服已接入"},
    )
    assert replied.status_code == 200, replied.text

    async with services.groups.runtime.engine.connect() as connection:
        business_conversation = await one(
            connection,
            """
            SELECT c.id
            FROM service_application_conversations c
            JOIN service_application_turns t ON t.conversation_id=c.id
            WHERE t.runtime_conversation_id=:conversation
            LIMIT 1
            """,
            conversation=accepted["conversation_id"],
        )
        messages = await connection.execute(
            text(
                """
                SELECT role,content
                FROM service_application_messages
                WHERE conversation_id=:conversation
                ORDER BY seq
                """
            ),
            {"conversation": business_conversation["id"]},
        )
        message_rows = [dict(row) for row in messages.mappings()]

    assert any(
        row["role"] == "human" and row["content"] == "人工客服已接入"
        for row in message_rows
    )


@pytest.mark.asyncio
async def test_handoff_cancels_queued_business_turn(platform):
    client, services, settings = platform
    agent, _ = await create_agent(client)
    application, channel_response = await _create_channel(client, agent)

    async with services.groups.runtime.engine.connect() as connection:
        channel = await one(
            connection,
            "SELECT * FROM channels WHERE id=:id",
            id=channel_response["id"],
        )

    envelope = IncomingEnvelope(
        external_message_id="ledger-queued-handoff-1",
        external_conversation_id="ledger-queued-handoff-session-1",
        external_user_id="customer-1",
        external_thread_id=None,
        text="请人工处理",
        target={},
    )
    accepted = await services.groups.business.channels._accept_envelope(
        channel,
        envelope,
        application_id=application["id"],
        application_version=application["published_version"],
        scope=BusinessScope(
            tenant_id=settings.tenant_id,
            business_id=channel["business_id"],
            workspace_id=channel["workspace_id"],
        ),
    )
    handoff_response = await client.post(
        f"/api/v1/conversations/{accepted['conversation_id']}/handoffs",
        json={"reason": "排队中转人工"},
    )
    assert handoff_response.status_code == 200, handoff_response.text

    async with services.groups.runtime.engine.connect() as connection:
        turn = await one(
            connection,
            """
            SELECT status
            FROM service_application_turns
            WHERE runtime_run_id=:run
            """,
            run=accepted["run_id"],
        )
    assert turn["status"] == "cancelled"
