import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from test_platform_postgres import platform as _platform

from agent_platform.applications import seed_execution_orchestrator as seed_module
from agent_platform.applications.seed_execution_orchestrator import (
    BATCH,
    LEGACY_EXTERNAL_ID,
    PUBLISHED_EXTERNAL_ID,
    resource_id,
    seed,
)
from agent_platform.core_platform.platform_services.persistence.store import execute, many, one

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]

CREATED = {
    "connections": 1,
    "models": 1,
    "profiles": 1,
    "agents": 1,
    "conversations": 2,
    "open_applications": 1,
}
PRESERVED = CREATED.copy()
ZERO = {key: 0 for key in CREATED}
OUTPUT_KEYS = {
    "created",
    "preserved",
    "agent_id",
    "agent_version",
    "published_external_id",
    "legacy_external_id",
    "open_application_id",
}


async def _conversation(platform, tenant, external_id):
    async with platform.runtime.engine.connect() as connection:
        return await one(
            connection,
            "SELECT * FROM runtime_conversations WHERE tenant_id=:tenant AND external_id=:external",
            tenant=tenant,
            external=external_id,
        )


async def _cleanup_additional_tenant(platform, tenant):
    """Remove only the extra tenant created by the isolation test."""

    async with platform.runtime.engine.begin() as connection:
        await execute(
            connection, "DELETE FROM open_request_logs WHERE tenant_id=:tenant", tenant=tenant
        )
        await execute(
            connection, "DELETE FROM open_applications WHERE tenant_id=:tenant", tenant=tenant
        )
        await execute(connection, "DELETE FROM runtime_runs WHERE tenant_id=:tenant", tenant=tenant)
        await execute(
            connection, "DELETE FROM runtime_conversations WHERE tenant_id=:tenant", tenant=tenant
        )
        await execute(
            connection,
            "DELETE FROM agent_versions WHERE agent_id IN (SELECT id FROM agents WHERE tenant_id=:tenant)",
            tenant=tenant,
        )
        await execute(connection, "DELETE FROM agents WHERE tenant_id=:tenant", tenant=tenant)
        await execute(
            connection,
            "DELETE FROM gateway_profile_versions WHERE profile_id IN (SELECT id FROM gateway_profiles WHERE tenant_id=:tenant)",
            tenant=tenant,
        )
        for table in ("gateway_profiles", "gateway_models", "gateway_connections", "audit_records"):
            await execute(connection, f"DELETE FROM {table} WHERE tenant_id=:tenant", tenant=tenant)


async def test_seed_creates_real_snapshots_and_preserves_operator_changes(platform):
    _client, runtime, settings = platform
    services, tenant = runtime.groups, settings.tenant_id

    first = await seed(services, tenant)

    assert first["created"] == CREATED
    assert first["preserved"] == ZERO
    agent_id = UUID(first["agent_id"])
    application_id = UUID(first["open_application_id"])
    assert agent_id == resource_id(tenant, "agent", "published-agent")
    assert application_id == resource_id(tenant, "open_application", "open-application")
    assert first["agent_version"] == 1
    assert first["published_external_id"] == PUBLISHED_EXTERNAL_ID
    assert first["legacy_external_id"] == LEGACY_EXTERNAL_ID

    profile_id = resource_id(tenant, "profile", "chat-profile")
    async with services.runtime.engine.connect() as connection:
        profile = await one(
            connection,
            "SELECT * FROM gateway_profiles WHERE tenant_id=:tenant AND id=:id",
            tenant=tenant,
            id=profile_id,
        )
        profile_versions = await many(
            connection,
            "SELECT * FROM gateway_profile_versions WHERE profile_id=:id",
            id=profile_id,
        )
        agent = await one(
            connection,
            "SELECT * FROM agents WHERE tenant_id=:tenant AND id=:id",
            tenant=tenant,
            id=agent_id,
        )
        agent_versions = await many(
            connection, "SELECT * FROM agent_versions WHERE agent_id=:id", id=agent_id
        )
        application = await one(
            connection,
            "SELECT * FROM open_applications WHERE tenant_id=:tenant AND id=:id",
            tenant=tenant,
            id=application_id,
        )
        side_effects = await one(
            connection,
            """SELECT
            (SELECT count(*) FROM conversation_messages m
                JOIN runtime_conversations c ON c.id=m.conversation_id
                WHERE c.tenant_id=:tenant) AS messages,
            (SELECT count(*) FROM runtime_runs WHERE tenant_id=:tenant) AS runs,
            (SELECT count(*) FROM runtime_events e JOIN runtime_runs r ON r.id=e.run_id
                WHERE r.tenant_id=:tenant) AS events,
            (SELECT count(*) FROM tickets WHERE tenant_id=:tenant) AS tickets,
            (SELECT count(*) FROM gateway_calls WHERE tenant_id=:tenant) AS calls,
            (SELECT count(*) FROM open_request_logs WHERE tenant_id=:tenant) AS request_logs,
            (SELECT count(*) FROM gateway_credentials WHERE tenant_id=:tenant) AS credentials,
            (SELECT count(*) FROM open_api_keys k JOIN open_applications a ON a.id=k.app_id
                WHERE a.tenant_id=:tenant) AS app_keys""",
            tenant=tenant,
        )

    assert profile["published_version"] == 1
    assert profile["spec"]["operation"] == "chat"
    assert len(profile_versions) == 1
    assert profile_versions[0]["snapshot"]["profile_id"] == str(profile_id)
    assert profile_versions[0]["snapshot"]["spec"]["operation"] == "chat"
    assert agent["is_example"] is True
    assert agent["published_version"] == first["agent_version"]
    assert len(agent_versions) == 1
    assert agent_versions[0]["config"]["model_profile_id"] == str(profile_id)
    assert agent_versions[0]["config"]["model_profile_version"] == 1
    assert application["enabled"] is True
    assert application["agent_ids"] == [agent_id]
    assert application["agent_versions"] == {}
    assert application["knowledge_base_ids"] == []
    assert set(side_effects.values()) == {0}

    published = await _conversation(services, tenant, PUBLISHED_EXTERNAL_ID)
    legacy = await _conversation(services, tenant, LEGACY_EXTERNAL_ID)
    assert published["agent_id"] == agent_id
    assert published["history"] == []
    assert published["customer_id"] is None
    assert legacy["agent_id"] is None
    assert legacy["history"] == []
    assert legacy["customer_id"] is None
    conversation_ids = (published["id"], legacy["id"])

    operator_draft = dict(agent["draft"])
    operator_draft["system_prompt"] = "Operator draft preserved by reseeding."
    async with services.runtime.engine.begin() as connection:
        for table in ("gateway_connections", "gateway_models", "gateway_profiles"):
            await execute(
                connection,
                f"UPDATE {table} SET name=:name WHERE tenant_id=:tenant",
                name=f"Operator {table}",
                tenant=tenant,
            )
        await execute(
            connection,
            "UPDATE gateway_profiles SET archived=true,enabled=false WHERE tenant_id=:tenant",
            tenant=tenant,
        )
        await execute(
            connection,
            """UPDATE agents SET name=:name,draft=CAST(:draft AS jsonb),archived=true
            WHERE tenant_id=:tenant AND id=:id""",
            name="Operator Agent",
            draft=json.dumps(operator_draft),
            tenant=tenant,
            id=agent_id,
        )
        await execute(
            connection,
            """UPDATE open_applications SET name=:name,enabled=false,agent_ids=:agent_ids
            WHERE tenant_id=:tenant AND id=:id""",
            name="Operator Disabled Application",
            agent_ids=[],
            tenant=tenant,
            id=application_id,
        )
        await execute(
            connection,
            "UPDATE runtime_conversations SET agent_id=NULL WHERE tenant_id=:tenant AND external_id=:external",
            tenant=tenant,
            external=PUBLISHED_EXTERNAL_ID,
        )
        await execute(
            connection,
            "UPDATE runtime_conversations SET agent_id=:agent_id WHERE tenant_id=:tenant AND external_id=:external",
            agent_id=agent_id,
            tenant=tenant,
            external=LEGACY_EXTERNAL_ID,
        )

    second = await seed(services, tenant)

    assert second["created"] == ZERO
    assert second["preserved"] == PRESERVED
    assert second["agent_id"] == first["agent_id"]
    assert second["agent_version"] == first["agent_version"]
    assert second["open_application_id"] == first["open_application_id"]
    assert (await _conversation(services, tenant, PUBLISHED_EXTERNAL_ID))["id"] == conversation_ids[
        0
    ]
    assert (await _conversation(services, tenant, LEGACY_EXTERNAL_ID))["id"] == conversation_ids[1]
    assert (await _conversation(services, tenant, PUBLISHED_EXTERNAL_ID))["agent_id"] is None
    assert (await _conversation(services, tenant, LEGACY_EXTERNAL_ID))["agent_id"] == agent_id
    async with services.runtime.engine.connect() as connection:
        preserved_agent = await one(connection, "SELECT * FROM agents WHERE id=:id", id=agent_id)
        preserved_application = await one(
            connection, "SELECT * FROM open_applications WHERE id=:id", id=application_id
        )
        assert await one(
            connection,
            "SELECT count(*) AS count FROM agent_versions WHERE agent_id=:id",
            id=agent_id,
        ) == {"count": 1}
        assert await one(
            connection,
            "SELECT count(*) AS count FROM gateway_profile_versions WHERE profile_id=:id",
            id=profile_id,
        ) == {"count": 1}
        names = await many(
            connection,
            """SELECT name FROM gateway_profiles WHERE tenant_id=:tenant
            UNION ALL SELECT name FROM gateway_models WHERE tenant_id=:tenant
            UNION ALL SELECT name FROM gateway_connections WHERE tenant_id=:tenant""",
            tenant=tenant,
        )
    assert preserved_agent["name"] == "Operator Agent"
    assert preserved_agent["draft"] == operator_draft
    assert preserved_agent["archived"] is True
    assert preserved_application["name"] == "Operator Disabled Application"
    assert preserved_application["enabled"] is False
    assert preserved_application["agent_ids"] == []
    assert {row["name"] for row in names} == {
        "Operator gateway_connections",
        "Operator gateway_models",
        "Operator gateway_profiles",
    }


async def test_seed_isolated_by_tenant_and_stable_business_keys(platform):
    _client, runtime, settings = platform
    services = runtime.groups
    other_tenant = f"{settings.tenant_id}-other"
    try:
        first = await seed(services, settings.tenant_id)
        other = await seed(services, other_tenant)
        assert other["created"] == CREATED
        assert other["agent_id"] != first["agent_id"]
        assert other["open_application_id"] != first["open_application_id"]
        assert await _conversation(services, other_tenant, PUBLISHED_EXTERNAL_ID) is not None
        assert await _conversation(services, other_tenant, LEGACY_EXTERNAL_ID) is not None

        repeated = await seed(services, other_tenant)
        assert repeated["created"] == ZERO
        assert repeated["preserved"] == PRESERVED
        assert repeated["agent_id"] == other["agent_id"]
        assert repeated["open_application_id"] == other["open_application_id"]
        async with services.runtime.engine.connect() as connection:
            counts = await many(
                connection,
                """SELECT tenant_id,count(*) AS count FROM runtime_conversations
                WHERE tenant_id IN (:first,:second) GROUP BY tenant_id ORDER BY tenant_id""",
                first=settings.tenant_id,
                second=other_tenant,
            )
        assert counts == [
            {"tenant_id": settings.tenant_id, "count": 2},
            {"tenant_id": other_tenant, "count": 2},
        ] or counts == [
            {"tenant_id": other_tenant, "count": 2},
            {"tenant_id": settings.tenant_id, "count": 2},
        ]
    finally:
        await _cleanup_additional_tenant(services, other_tenant)


async def test_main_prints_only_low_sensitivity_counts_and_references(
    platform, monkeypatch, capsys
):
    _client, runtime, settings = platform

    @asynccontextmanager
    async def fake_runtime_services(_settings):
        yield runtime

    monkeypatch.setattr(seed_module, "Settings", lambda: settings)
    monkeypatch.setattr(seed_module, "runtime_services", fake_runtime_services)

    await seed_module.main()

    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    payload = json.loads(captured.out)
    assert set(payload) == OUTPUT_KEYS
    assert payload["created"] == CREATED
    assert payload["preserved"] == ZERO
    assert UUID(payload["agent_id"]) == resource_id(settings.tenant_id, "agent", "published-agent")
    assert payload["agent_version"] == 1
    assert payload["published_external_id"] == PUBLISHED_EXTERNAL_ID
    assert payload["legacy_external_id"] == LEGACY_EXTERNAL_ID
    assert UUID(payload["open_application_id"]) == resource_id(
        settings.tenant_id, "open_application", "open-application"
    )
    assert settings.tenant_id not in captured.out
    assert settings.database_url.get_secret_value() not in captured.out
    for forbidden in ("api_key", "token", "secret", "password", "history", "database_url"):
        assert forbidden not in captured.out.lower()
    assert BATCH not in captured.out


LIVE_TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled"}
LIVE_OPEN_FORBIDDEN_KEYS = {
    "arguments",
    "chunks",
    "config",
    "context",
    "documents",
    "duration_ms",
    "first_token_ms",
    "gateway_call_id",
    "history",
    "input",
    "outcome",
    "reasoning",
    "tool_input",
    "tool_result",
    "usage",
}


async def _live_read_sse(
    response: httpx.Response,
) -> tuple[list[dict[str, Any]], str]:
    response.raise_for_status()
    events = []
    raw_lines = []
    current: dict[str, Any] = {"id": None, "event": "message", "data": []}

    def flush() -> None:
        nonlocal current
        if not current["data"] and current["id"] is None and current["event"] == "message":
            return
        raw_data = "\n".join(current["data"])
        try:
            data = json.loads(raw_data) if raw_data else None
        except json.JSONDecodeError:
            data = raw_data
        events.append({"id": current["id"], "event": current["event"], "data": data})
        current = {"id": None, "event": "message", "data": []}

    async with asyncio.timeout(60):
        async for line in response.aiter_lines():
            raw_lines.append(line)
            if line == "":
                flush()
                if events and events[-1]["event"] in LIVE_TERMINAL_EVENTS:
                    break
            elif line.startswith(":"):
                continue
            elif line.startswith("id:"):
                current["id"] = line[3:].strip()
            elif line.startswith("event:"):
                current["event"] = line[6:].strip()
            elif line.startswith("data:"):
                current["data"].append(line[5:].lstrip())
    flush()
    return events, "\n".join(raw_lines)


def _live_persistent(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [event for event in events if event["id"] is not None]


def _live_assert_terminal(events: list[dict[str, Any]]) -> None:
    assert events
    terminal = events[-1]
    assert terminal["event"] == "run.completed"
    assert terminal["data"]["output"]
    assert terminal["data"]["error_code"] is None
    persisted = _live_persistent(events)
    sequences = [int(event["id"]) for event in persisted]
    assert sequences == sorted(set(sequences))
    assert persisted[-1]["event"] == "run.completed"


def _live_assert_replay(
    initial: list[dict[str, Any]],
    replayed: list[dict[str, Any]],
    allowed_unpersisted: frozenset[str] = frozenset(),
) -> None:
    assert _live_persistent(replayed) == _live_persistent(initial)
    _live_assert_terminal(replayed)
    assert all(
        event["id"] is not None or event["event"] in allowed_unpersisted for event in replayed
    )


async def _live_empty_replay(
    client: httpx.AsyncClient,
    path: str,
    auth_headers: dict[str, str],
    after: int,
    last_event_id: int,
) -> None:
    async with client.stream(
        "GET",
        path,
        params={"after": after},
        headers={**auth_headers, "Last-Event-ID": str(last_event_id)},
    ) as response:
        events, _ = await _live_read_sse(response)
    assert _live_persistent(events) == []


async def _live_wait_run(
    client: httpx.AsyncClient, path: str, headers: dict[str, str]
) -> dict[str, Any]:
    for _ in range(150):
        response = await client.get(path, headers=headers)
        response.raise_for_status()
        run = response.json()
        if run["status"] in {"completed", "failed", "cancelled"}:
            assert run["status"] == "completed"
            assert run["error_code"] is None
            assert run["output"]
            return run
        await asyncio.sleep(0.2)
    raise TimeoutError(f"Live Run did not reach a terminal state: {path}")


def _live_data_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_live_data_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_live_data_keys(item) for item in value)) if value else set()
    return set()


@pytest.mark.skipif(
    os.environ.get("NEXUSDESK_LIVE_QUICKSTART") != "1"
    or not os.environ.get("NEXUSDESK_LIVE_QUICKSTART_URL")
    or not os.environ.get("NEXUSDESK_LIVE_QUICKSTART_TOKEN"),
    reason="opt-in seeded quickstart URL and admin token are required",
)
async def test_live_quickstart_internal_and_open_sse_replay() -> None:
    """Drive a seeded quickstart over real HTTP; never controls Docker in default CI."""

    base_url = os.environ["NEXUSDESK_LIVE_QUICKSTART_URL"]
    token = os.environ["NEXUSDESK_LIVE_QUICKSTART_TOKEN"]
    tenant = os.environ.get("NEXUSDESK_LIVE_QUICKSTART_TENANT", "local")
    agent_id = resource_id(tenant, "agent", "published-agent")
    application_id = resource_id(tenant, "open_application", "open-application")
    admin_headers = {"Authorization": f"Bearer {token}"}
    app_key = None
    key_id = None
    async with httpx.AsyncClient(
        base_url=base_url, verify=False, trust_env=False, timeout=20
    ) as client:
        try:
            for kind, external_id in (
                ("published", PUBLISHED_EXTERNAL_ID),
                ("no-snapshot", LEGACY_EXTERNAL_ID),
            ):
                response = await client.post(
                    "/api/v1/runs",
                    headers=admin_headers,
                    json={
                        "conversation_id": external_id,
                        "message": f"T11 opt-in live {kind} {uuid4()}",
                    },
                )
                response.raise_for_status()
                run_id = response.json()["id"]
                if kind == "published":
                    async with client.stream(
                        "GET",
                        f"/api/v1/runs/{run_id}/events",
                        params={"after": 0},
                        headers=admin_headers,
                    ) as stream_response:
                        initial, _ = await _live_read_sse(stream_response)
                    _live_assert_terminal(initial)
                    async with client.stream(
                        "GET",
                        f"/api/v1/runs/{run_id}/events",
                        params={"after": 0},
                        headers=admin_headers,
                    ) as replay_response:
                        replay, _ = await _live_read_sse(replay_response)
                    _live_assert_replay(initial, replay)
                    terminal_seq = int(_live_persistent(replay)[-1]["id"])
                    path = f"/api/v1/runs/{run_id}/events"
                    await _live_empty_replay(
                        client, path, admin_headers, after=terminal_seq, last_event_id=0
                    )
                    await _live_empty_replay(
                        client, path, admin_headers, after=0, last_event_id=terminal_seq
                    )
                    await _live_empty_replay(
                        client,
                        path,
                        admin_headers,
                        after=terminal_seq - 1,
                        last_event_id=terminal_seq,
                    )
                    await _live_empty_replay(
                        client,
                        path,
                        admin_headers,
                        after=terminal_seq,
                        last_event_id=terminal_seq - 1,
                    )
                await _live_wait_run(client, f"/api/v1/runs/{run_id}", admin_headers)

            response = await client.post(
                f"/api/v1/open-platform/applications/{application_id}/keys",
                headers=admin_headers,
                json={"expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat()},
            )
            response.raise_for_status()
            issued = response.json()
            key_id = issued["id"]
            app_key = issued["key"]
            open_headers = {
                "Authorization": f"Bearer {app_key}",
                "X-External-User-ID": f"t11-pytest-{uuid4()}",
            }
            response = await client.post(
                "/openapi/v1/conversations",
                headers=open_headers,
                json={"agent_id": str(agent_id), "external_session_id": f"t11-{uuid4()}"},
            )
            response.raise_for_status()
            conversation_id = response.json()["conversation_id"]
            message = f"T11 opt-in live Open {uuid4()}"
            async with client.stream(
                "POST",
                f"/openapi/v1/conversations/{conversation_id}/messages",
                headers={**open_headers, "Idempotency-Key": f"t11-{uuid4()}"},
                json={"message": message, "stream": True, "wait_seconds": 0},
            ) as open_stream_response:
                open_initial, open_raw = await _live_read_sse(open_stream_response)
            accepted = next(event for event in open_initial if event["event"] == "accepted")
            assert set(accepted["data"]) == {"run_id", "request_id"}
            open_run_id = accepted["data"]["run_id"]
            _live_assert_terminal(open_initial)
            assert open_initial[-1]["data"]["id"] == open_run_id
            assert open_initial[-1]["data"]["status"] == "completed"
            assert message not in open_raw
            for event in open_initial:
                assert not (_live_data_keys(event["data"]) & LIVE_OPEN_FORBIDDEN_KEYS)

            open_path = f"/openapi/v1/runs/{open_run_id}/events"
            async with client.stream(
                "GET", open_path, params={"after": 0}, headers=open_headers
            ) as open_replay_response:
                open_replay, open_replay_raw = await _live_read_sse(open_replay_response)
            _live_assert_replay(
                open_initial, open_replay, allowed_unpersisted=frozenset({"accepted"})
            )
            assert message not in open_replay_raw
            for event in open_replay:
                assert not (_live_data_keys(event["data"]) & LIVE_OPEN_FORBIDDEN_KEYS)
            terminal_seq = int(_live_persistent(open_replay)[-1]["id"])
            await _live_empty_replay(
                client, open_path, open_headers, after=terminal_seq, last_event_id=0
            )
            await _live_empty_replay(
                client, open_path, open_headers, after=0, last_event_id=terminal_seq
            )
            await _live_empty_replay(
                client,
                open_path,
                open_headers,
                after=terminal_seq - 1,
                last_event_id=terminal_seq,
            )
            await _live_empty_replay(
                client,
                open_path,
                open_headers,
                after=terminal_seq,
                last_event_id=terminal_seq - 1,
            )
            await _live_wait_run(client, f"/openapi/v1/runs/{open_run_id}", open_headers)
        finally:
            if key_id is not None:
                response = await client.post(
                    f"/api/v1/open-platform/applications/{application_id}/keys/{key_id}/revoke",
                    headers=admin_headers,
                )
                response.raise_for_status()
                assert response.json()["revoked"] is True
            if app_key is not None:
                app_key = None
                open_headers["Authorization"] = ""
                issued.pop("key", None)
            del token
