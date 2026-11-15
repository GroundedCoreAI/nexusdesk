"""Open-platform delivery of a Service Application.

The open platform historically authorised a list of agents and submitted each
message straight to the Runtime. An application that delivers a published
Service Application instead reuses the in-product customer session entry, so a
turn goes through the same routing, admission, queue, worker and ledger path —
skills, connections, rules and knowledge included.

These tests assert the binding rules, the public contract (``/targets`` and
``/conversations`` without ``agent_id``) and the persisted result: a real
customer ledger row, ``source='open_platform'`` on the Runtime conversation and
an ``open_runs`` row the run endpoints can resolve.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from test_platform_postgres import (
    create_agent,
    create_published_application,
    execute_next,
)
from test_platform_postgres import (
    platform as _platform,
)

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]

ROOT = "/api/v1/open-platform/applications"
PUBLIC = "/openapi/v1"


def headers(key, user="employee-1", idem="message-1"):
    return {"Authorization": "Bearer " + key, "X-External-User-ID": user, "Idempotency-Key": idem}


async def _bound_application(client, application, **options):
    """Create an open-platform application that delivers ``application``."""

    response = await client.post(
        ROOT,
        json={
            "name": "应用交付",
            "service_application_id": application["id"],
            **options,
        },
    )
    assert response.status_code == 201, response.text
    app = response.json()
    response = await client.post(f"{ROOT}/{app['id']}/keys", json={})
    assert response.status_code == 201, response.text
    return app, response.json()


async def _draft_application(client, agent):
    key = "draft-" + uuid4().hex[:12]
    response = await client.post(
        "/api/v1/service-apps",
        json={
            "key": key,
            "name": "草稿应用",
            "description": "",
            "agent_id": agent["id"],
            "agent_version": 1,
        },
    )
    assert response.status_code == 201, response.text
    return (await client.get(f"/api/v1/service-apps/{key}")).json()


async def test_binding_rules_and_delivery_target(platform):
    client, _services, _settings = platform
    agent, _ = await create_agent(client)
    published = await create_published_application(client, agent)
    draft = await _draft_application(client, agent)

    # Only a released, live application can be delivered.
    assert (
        await client.post(ROOT, json={"name": "draft", "service_application_id": draft["id"]})
    ).status_code == 422
    # An agent grant is derived from the subject: the wrapped agent is
    # associated automatically, whatever the request carries.
    derived = await client.post(
        ROOT,
        json={
            "name": "derived",
            "agent_ids": [agent["id"], str(uuid4())],
            "service_application_id": published["id"],
        },
    )
    assert derived.status_code == 201, derived.text
    assert derived.json()["agent_ids"] == [published["agent_id"]]
    # A pin must be a real release.
    assert (
        await client.post(
            ROOT,
            json={
                "name": "bad-pin",
                "service_application_id": published["id"],
                "service_application_version": 99,
            },
        )
    ).status_code == 422
    # A pin without a subject is meaningless.
    assert (
        await client.post(ROOT, json={"name": "pin-only", "service_application_version": 1})
    ).status_code == 422

    app, key = await _bound_application(client, published)
    # The wrapped agent is associated automatically on binding.
    assert app["agent_ids"] == [published["agent_id"]]
    assert app["target"]["target_kind"] == "service_application"
    assert app["target"]["version_pin"] is None
    # The subject is resolved to a readable identity for management UIs.
    assert app["target"]["name"] == published["name"]
    assert app["target"]["key"] == published["key"]
    assert app["target"]["version"] == published["published_version"]
    assert app["target"]["pinned"] is False

    detail = (await client.get(f"{ROOT}/{app['id']}")).json()
    assert detail["target"]["target_id"] == published["id"]
    assert detail["target"]["name"] == published["name"]

    listing = (await client.get(ROOT)).json()
    card = next(item for item in listing["items"] if item["id"] == app["id"])
    assert card["target"]["target_kind"] == "service_application"
    assert card["target"]["name"] == published["name"]

    # An update that omits the delivery subject keeps the binding: partial
    # writers (integration settings) must not silently unbind.
    body = {
        field: detail[field]
        for field in ("name", "description", "enabled", "rpm", "max_concurrency", "revision")
    }
    body["knowledge_base_ids"] = []
    preserved = await client.put(f"{ROOT}/{app['id']}", json=body)
    assert preserved.status_code == 200, preserved.text
    assert preserved.json()["target"]["target_kind"] == "service_application"
    assert preserved.json()["target"]["target_id"] == published["id"]

    # Switching back to an agent list requires clearing the subject
    # explicitly; that drops the delivery row.
    detail = (await client.get(f"{ROOT}/{app['id']}")).json()
    body = {
        field: detail[field]
        for field in (
            "name",
            "description",
            "enabled",
            "rpm",
            "max_concurrency",
            "revision",
        )
    }
    body["agent_ids"] = [agent["id"]]
    body["service_application_id"] = None
    updated = await client.put(f"{ROOT}/{app['id']}", json=body)
    assert updated.status_code == 200, updated.text
    assert updated.json()["target"]["target_kind"] == "agent"
    assert updated.json()["target"]["target_id"] == agent["id"]
    # The key survives the switch; it now authorises the agent.
    assert (await client.get(PUBLIC + "/targets", headers=headers(key["key"]))).json()[
        "mode"
    ] == "agent"


async def test_delivery_runs_the_real_customer_chain(platform):
    client, services, settings = platform
    agent, _ = await create_agent(client)
    application = await create_published_application(client, agent)
    _app, key = await _bound_application(client, application)
    h = headers(key["key"])

    targets = await client.get(PUBLIC + "/targets", headers=h)
    assert targets.status_code == 200, targets.text
    assert targets.json()["mode"] == "service_application"
    assert targets.json()["target"]["key"] == application["key"]
    assert targets.json()["target"]["version"] == application["published_version"]

    created = await client.post(
        PUBLIC + "/conversations", headers=h, json={"external_session_id": "session-1"}
    )
    assert created.status_code == 201, created.text
    cid = created.json()["conversation_id"]
    assert created.json()["agent_id"] is None
    assert created.json()["application_key"] == application["key"]
    # Same external session reuses the conversation.
    again = await client.post(
        PUBLIC + "/conversations", headers=h, json={"external_session_id": "session-1"}
    )
    assert again.json()["conversation_id"] == cid
    # An agent id is not applicable to an application-delivered key.
    assert (
        await client.post(
            PUBLIC + "/conversations",
            headers=h,
            json={"agent_id": agent["id"], "external_session_id": "session-2"},
        )
    ).status_code == 422

    response = await client.post(
        f"{PUBLIC}/conversations/{cid}/messages",
        headers=headers(key["key"], idem="turn-1"),
        json={"message": "我的订单到哪了", "wait_seconds": 0},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]

    final = await execute_next(services, settings)
    assert final["status"] == "completed", final["error_code"]
    run = await client.get(f"{PUBLIC}/runs/{run_id}", headers=h)
    assert run.status_code == 200 and run.json()["status"] == "completed"

    replay = await client.post(
        f"{PUBLIC}/conversations/{cid}/messages",
        headers=headers(key["key"], idem="turn-1"),
        json={"message": "我的订单到哪了", "wait_seconds": 0},
    )
    assert replay.json()["id"] == run_id
    assert (
        await client.post(
            f"{PUBLIC}/conversations/{cid}/messages",
            headers=headers(key["key"], idem="turn-1"),
            json={"message": "换一条内容", "wait_seconds": 0},
        )
    ).status_code == 409
    # Another external user cannot read this conversation.
    assert (
        await client.get(
            f"{PUBLIC}/conversations/{cid}/messages", headers=headers(key["key"], "employee-2")
        )
    ).status_code == 404

    async with services.groups.runtime.engine.connect() as connection:
        conversation = (
            await connection.execute(
                text(
                    """SELECT source,application_id,application_version
                    FROM runtime_conversations WHERE id=CAST(:id AS uuid)"""
                ),
                {"id": cid},
            )
        ).mappings().one()
        assert conversation["source"] == "open_platform"
        assert str(conversation["application_id"]) == application["id"]
        assert conversation["application_version"] == application["published_version"]

        ledger = (
            await connection.execute(
                text(
                    """SELECT bc.id,bc.kind,bc.external_user_id,bc.metadata->>'source' AS marker,
                    bc.metadata->>'open_app_id' AS open_app_id
                    FROM service_application_conversations bc
                    JOIN service_application_turns t ON t.conversation_id=bc.id
                    WHERE bc.application_id=CAST(:a AS uuid)
                      AND t.runtime_conversation_id=CAST(:c AS uuid)
                    LIMIT 1"""
                ),
                {"a": application["id"], "c": cid},
            )
        ).mappings().one()
        assert ledger["kind"] == "customer"
        assert ledger["external_user_id"] == "employee-1"
        assert ledger["marker"] == "open_platform"
        assert ledger["open_app_id"] == str(_app["id"])

        open_run = (
            await connection.execute(
                text("SELECT conversation_id FROM open_runs WHERE run_id=CAST(:r AS uuid)"),
                {"r": run_id},
            )
        ).mappings().one()
        assert str(open_run["conversation_id"]) == cid

    # The turn also lands in the in-product conversation list (real customer
    # session, unlike debug previews).
    listing = await client.get(
        f"/api/v1/service-apps/{application['key']}/conversations", params={"q": ""}
    )
    assert listing.status_code == 200, listing.text
    assert any(item["id"] == str(ledger["id"]) for item in listing.json()["items"])


async def test_pinned_version_and_offline_blocking(platform):
    client, services, _settings = platform
    agent, _ = await create_agent(client)
    application = await create_published_application(client, agent)
    _app, key = await _bound_application(
        client, application, service_application_version=application["published_version"]
    )
    h = headers(key["key"])

    targets = (await client.get(PUBLIC + "/targets", headers=h)).json()
    assert targets["target"]["pinned"] is True
    assert targets["target"]["version"] == application["published_version"]

    async with services.groups.runtime.engine.begin() as connection:
        await connection.execute(
            text("UPDATE service_applications SET status='offline' WHERE id=CAST(:id AS uuid)"),
            {"id": application["id"]},
        )

    # Delivery stops for every entry point, including the public description.
    assert (await client.get(PUBLIC + "/targets", headers=h)).status_code == 409
    assert (
        await client.post(
            PUBLIC + "/conversations", headers=h, json={"external_session_id": "session-off"}
        )
    ).status_code == 409
    # The in-product session entry refuses a new session on an offline app.
    assert (
        await client.post(
            f"/api/v1/service-apps/{application['key']}/sessions", json={"external_user_id": "u-1"}
        )
    ).status_code == 409
