# ruff: noqa: F811
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from test_platform_postgres import create_agent, execute_next, platform  # noqa: F401

from agent_platform.business_capabilities.open_platform import routes as open_routes

pytestmark = pytest.mark.asyncio
ROOT = "/api/v1/open-platform/applications"
PUBLIC = "/openapi/v1"


@pytest.mark.postgres
async def test_application_status_filter_preserves_total_and_search(platform):
    client, _, _settings = platform
    for name, enabled in [("Filter A", True), ("Filter B", False), ("Other", True)]:
        response = await client.post(ROOT, json={"name": name, "enabled": enabled})
        assert response.status_code == 201
    for enabled, expected in [("true", "Filter A"), ("false", "Filter B")]:
        response = await client.get(ROOT, params={"q": "Filter", "enabled": enabled})
        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert response.json()["items"][0]["name"] == expected
    assert (await client.get(ROOT)).json()["total"] == 3


async def application(client, aid, **options):
    r = await client.post(ROOT, json={"name": "Enterprise", "agent_ids": [aid], **options})
    assert r.status_code == 201, r.text
    app = r.json()
    r = await client.post(f"{ROOT}/{app['id']}/keys", json={})
    assert r.status_code == 201, r.text
    return app, r.json()


def headers(key, user="employee-1", idem="message-1"):
    return {"Authorization": "Bearer " + key, "X-External-User-ID": user, "Idempotency-Key": idem}


async def session(client, key, aid, user="employee-1", external="session-1"):
    r = await client.post(
        PUBLIC + "/conversations",
        headers=headers(key, user),
        json={"agent_id": aid, "external_session_id": external},
    )
    assert r.status_code == 201, r.text
    return r.json()["conversation_id"]


@pytest.mark.postgres
async def test_identity_keys_scope_rotation_and_disable(platform):
    client, services, _settings = platform
    agent, _ = await create_agent(client)
    app, key = await application(client, agent["id"])
    path = f"{ROOT}/{app['id']}"
    async with services.repository.engine.connect() as c:
        digest = await c.scalar(
            text("SELECT token_hash FROM open_api_keys WHERE id=:id"), {"id": key["id"]}
        )
    assert digest == hashlib.sha256(key["key"].encode()).hexdigest()
    listing = await client.get(path + "/keys")
    assert key["key"] not in listing.text and "token_hash" not in listing.text
    assert (await client.get("/api/v1/agents", headers=headers(key["key"]))).status_code == 401
    assert (await client.get(PUBLIC + "/agents")).status_code == 401
    assert (await client.get(PUBLIC + "/agents", headers=headers(key["key"]))).json()[0][
        "id"
    ] == agent["id"]
    assert (
        await client.post(
            ROOT, headers={"Authorization": "Bearer platform-viewer"}, json={"name": "forbidden"}
        )
    ).status_code == 403
    assert (
        await client.post(
            path + "/keys", json={"expires_at": (datetime.now(UTC) - timedelta(days=1)).isoformat()}
        )
    ).status_code == 422
    rotated = await client.post(path + "/keys", json={"replace_id": key["id"], "grace_minutes": 60})
    assert rotated.status_code == 201, rotated.text
    assert (await client.get(PUBLIC + "/agents", headers=headers(key["key"]))).status_code == 200
    await client.post(path + f"/keys/{key['id']}/revoke")
    assert (await client.get(PUBLIC + "/agents", headers=headers(key["key"]))).status_code == 401
    newkey = rotated.json()
    immediate = await client.post(
        path + "/keys", json={"replace_id": newkey["id"], "grace_minutes": 0}
    )
    assert immediate.status_code == 201
    assert (await client.get(PUBLIC + "/agents", headers=headers(newkey["key"]))).status_code == 401
    body = {
        k: app[k]
        for k in (
            "name",
            "description",
            "enabled",
            "agent_ids",
            "rpm",
            "max_concurrency",
            "revision",
        )
    }
    body["enabled"] = False
    assert (await client.put(path, json=body)).status_code == 200
    assert (
        await client.get(PUBLIC + "/agents", headers=headers(immediate.json()["key"]))
    ).status_code == 403
    assert (await client.put(path, json=body)).status_code == 409


@pytest.mark.postgres
async def test_conversation_run_isolation_idempotency_and_sse(platform):
    client, services, settings = platform
    agent, _ = await create_agent(client)
    app, key = await application(client, agent["id"], max_concurrency=1)
    _, other = await application(client, agent["id"])
    k = key["key"]
    cid = await session(client, k, agent["id"])
    assert await session(client, k, agent["id"]) == cid
    assert await session(client, k, agent["id"], user="employee-2") != cid
    url = f"{PUBLIC}/conversations/{cid}/messages"
    assert (await client.get(url, headers=headers(k, "employee-2"))).status_code == 404
    assert (await client.get(url, headers=headers(other["key"]))).status_code == 404
    response = await client.post(
        url, headers=headers(k), json={"message": "Hello secret-body", "wait_seconds": 0}
    )
    assert response.status_code == 202, response.text
    rid = response.json()["id"]
    request_id = response.headers["x-request-id"]
    assert "config" not in response.json()
    duplicate = await client.post(
        url, headers=headers(k), json={"message": "Hello secret-body", "wait_seconds": 0}
    )
    assert duplicate.json()["id"] == rid
    assert (
        await client.post(url, headers=headers(k), json={"message": "different", "wait_seconds": 0})
    ).status_code == 409
    cid2 = await session(client, k, agent["id"], external="session-2")
    limited = await client.post(
        f"{PUBLIC}/conversations/{cid2}/messages",
        headers=headers(k, idem="other-message"),
        json={"message": "Hi", "wait_seconds": 0},
    )
    assert limited.status_code == 429, limited.text
    assert (
        await client.get(f"{PUBLIC}/runs/{rid}", headers=headers(other["key"]))
    ).status_code == 404
    assert (
        await client.post(f"{PUBLIC}/runs/{rid}/cancel", headers=headers(k, "employee-2"))
    ).status_code == 404
    final = await execute_next(services, settings)
    assert final["status"] == "completed", final["error_code"]
    events = await client.get(f"{PUBLIC}/runs/{rid}/events", headers=headers(k))
    assert events.status_code == 200, events.text
    assert "event: run.completed" in events.text and final["output"] in events.text
    assert "gateway_call_id" not in events.text and "tool_snapshot" not in events.text
    replay = await client.get(
        f"{PUBLIC}/runs/{rid}/events",
        headers={**headers(k), "Last-Event-ID": str(final["event_seq"])},
    )
    assert "event: run.completed" not in replay.text
    assert (await client.get(url, headers=headers(k))).json()["items"][-1]["role"] == "assistant"
    logs = await client.get(f"{ROOT}/{app['id']}/logs?request_id={request_id}")
    assert logs.status_code == 200, logs.text
    assert logs.json()["items"][0]["run_id"] == rid
    assert k not in logs.text and "secret-body" not in logs.text
    response = await client.post(
        url, headers=headers(k, idem="cancel-me"), json={"message": "cancel", "wait_seconds": 0}
    )
    rid = response.json()["id"]
    assert (await client.post(f"{PUBLIC}/runs/{rid}/cancel", headers=headers(k))).json()[
        "status"
    ] == "cancelled"


@pytest.mark.postgres
async def test_rate_limit_and_authorization_revocation(platform):
    client, services, _ = platform
    agent, _ = await create_agent(client)
    app, key = await application(client, agent["id"], rpm=2)
    h = headers(key["key"])
    assert (await client.get(PUBLIC + "/agents", headers=h)).status_code == 200
    assert (await client.get(PUBLIC + "/agents", headers=h)).status_code == 200
    for _ in range(2):
        r = await client.get(PUBLIC + "/agents", headers=h)
        assert r.status_code == 429 and r.headers["retry-after"] == "60"
    unpublished, _ = await create_agent(client, publish=False)
    assert (
        await client.post(ROOT, json={"name": "bad", "agent_ids": [unpublished["id"]]})
    ).status_code == 422
    app, key = await application(client, agent["id"])
    cid = await session(client, key["key"], agent["id"])
    body = {
        k: app[k]
        for k in (
            "name",
            "description",
            "enabled",
            "agent_ids",
            "rpm",
            "max_concurrency",
            "revision",
        )
    }
    body["agent_ids"] = []
    await client.put(f"{ROOT}/{app['id']}", json=body)
    assert (
        await client.get(f"{PUBLIC}/conversations/{cid}/messages", headers=headers(key["key"]))
    ).status_code == 403
    async with services.repository.engine.begin() as c:
        await c.execute(
            text("UPDATE open_applications SET tenant_id=:t WHERE id=:id"),
            {"t": "other-" + str(uuid4()), "id": app["id"]},
        )
    assert (await client.get(PUBLIC + "/agents", headers=headers(key["key"]))).status_code == 401
    async with services.repository.engine.begin() as c:
        await c.execute(
            text("UPDATE open_applications SET tenant_id=:t WHERE id=:id"),
            {"t": services.groups.runtime.settings.tenant_id, "id": app["id"]},
        )


import asyncio


@pytest.mark.postgres
async def test_stream_submission_and_terminal_failures(platform):
    client, services, settings = platform
    agent, _ = await create_agent(client)
    _app, key = await application(client, agent["id"])
    cid = await session(client, key["key"], agent["id"])
    task = asyncio.create_task(
        client.post(
            f"{PUBLIC}/conversations/{cid}/messages",
            headers=headers(key["key"]),
            json={"message": "stream hello", "stream": True},
        )
    )
    try:
        row = None
        for _ in range(100):
            row = await services.repository.claim(services.worker.owner, 30, settings.tenant_id)
            if row:
                break
            await asyncio.sleep(0.05)
        assert row is not None
        await services.worker._execute(row)
        r = await asyncio.wait_for(task, 10)
        assert (
            r.status_code == 200
            and "event: accepted" in r.text
            and "event: run.completed" in r.text
        )
        r = await client.post(
            f"{PUBLIC}/conversations/{cid}/messages",
            headers=headers(key["key"], idem="cancel-stream"),
            json={"message": "cancel", "wait_seconds": 0},
        )
        rid = r.json()["id"]
        await client.post(f"{PUBLIC}/runs/{rid}/cancel", headers=headers(key["key"]))
        events = await client.get(f"{PUBLIC}/runs/{rid}/events", headers=headers(key["key"]))
        assert "event: run.cancelled" in events.text and '"status": "cancelled"' in events.text
    finally:
        task.cancel()


@pytest.mark.postgres
async def test_concurrent_idempotent_submissions(platform):
    client, services, _ = platform
    agent, _ = await create_agent(client)
    _app, key = await application(client, agent["id"])
    cid = await session(client, key["key"], agent["id"])
    responses = await asyncio.gather(
        *[
            client.post(
                f"{PUBLIC}/conversations/{cid}/messages",
                headers=headers(key["key"]),
                json={"message": "concurrent", "wait_seconds": 0},
            )
            for _ in range(4)
        ]
    )
    assert all(r.status_code == 202 for r in responses)
    assert len({r.json()["id"] for r in responses}) == 1
    async with services.repository.engine.connect() as c:
        count = await c.scalar(
            text("SELECT count(*) FROM conversation_messages WHERE conversation_id=:id"),
            {"id": cid},
        )
        assert count == 1


class _OpenSSERepository:
    def __init__(self, events):
        self.all_events = events

    async def events(self, run_id, tenant, after):
        return [event for event in self.all_events if event["seq"] > after][:200]


class _OpenSSEListener:
    def __init__(self):
        self.unsubscribed = False

    async def subscribe(self, run_id):
        queue = asyncio.Queue()
        await queue.put('{"k":"delta","round":1,"text":"visible","reasoning":"hidden"}')
        await queue.put('{"k":"wake"}')
        return queue

    async def unsubscribe(self, run_id, queue):
        self.unsubscribed = True


class _OpenSSERequest:
    def __init__(self, repository, listener):
        runtime = SimpleNamespace(repository=repository, listener=listener)
        self.app = SimpleNamespace(state=SimpleNamespace(runtime=runtime))
        self.state = SimpleNamespace(open_request_id=uuid4(), open_run_id=None)

    async def is_disconnected(self):
        return False


def _open_sse_fixture():
    run_id = uuid4()
    now = datetime.now(UTC)
    final = {
        "id": run_id,
        "conversation_id": uuid4(),
        "status": "completed",
        "cancel_requested": False,
        "output": "public answer",
        "error_code": None,
        "created_at": now,
        "started_at": now,
        "finished_at": now,
        "event_seq": 3,
    }
    events = [
        {
            "seq": 1,
            "type": "model.completed",
            "data": {
                "round": 1,
                "tool_calls": 0,
                "usage": {"input_tokens": 4},
                "gateway_call_id": "private-gateway",
            },
        },
        {"seq": 2, "type": "tool.replay", "data": {"tool_snapshot": "private-tool"}},
        {"seq": 3, "type": "run.completed", "data": {"output": "private-duplicate"}},
    ]
    return run_id, final, events


async def test_p2_it06_open_sse_redaction_hidden_replay_and_cursor(monkeypatch):
    """P2-IT06/CM07: public SSE keeps only stable public fields and advances hidden seq."""

    class Service:
        async def run(self, identity, user, run_id):
            return final

    run_id, final, events = _open_sse_fixture()
    monkeypatch.setattr(open_routes, "service", lambda request: Service())
    listener = _OpenSSEListener()
    request = _OpenSSERequest(_OpenSSERepository(events), listener)
    identity = SimpleNamespace(tenant="tenant-a")

    response = open_routes.stream_response(request, identity, "external-user", run_id)
    frames = "".join([chunk async for chunk in response.body_iterator])

    assert "event: accepted" in frames
    assert "event: model.delta" in frames
    assert "hidden" not in frames
    assert "private-gateway" not in frames
    assert "gateway_call_id" not in frames
    assert "usage" not in frames
    assert "tool_snapshot" not in frames
    assert "tool.replay" not in frames
    assert "id: 2\n" not in frames
    assert "id: 3\nevent: run.completed" in frames
    assert '"output": "public answer"' in frames
    assert "private-duplicate" not in frames
    assert "config" not in frames and "history" not in frames
    assert listener.unsubscribed

    replay = open_routes.stream_response(
        _OpenSSERequest(_OpenSSERepository(events), _OpenSSEListener()),
        identity,
        "external-user",
        run_id,
        after=2,
    )
    replay_frames = "".join([chunk async for chunk in replay.body_iterator])
    assert "id: 1\n" not in replay_frames
    assert "id: 3\nevent: run.completed" in replay_frames


async def test_p2_it06_open_sse_typed_invalid_cursor_and_last_event_id(monkeypatch):
    class Service:
        async def run(self, identity, user, run_id):
            return final

    run_id, final, events = _open_sse_fixture()
    monkeypatch.setattr(open_routes, "service", lambda request: Service())
    app = FastAPI()
    app.get("/events/{run_id}")(open_routes.events)

    @app.middleware("http")
    async def request_state(request, call_next):
        request.state.open_request_id = uuid4()
        return await call_next(request)

    identity = SimpleNamespace(tenant="tenant-a")
    app.dependency_overrides[open_routes.authenticate] = lambda: identity
    app.dependency_overrides[open_routes.external_user] = lambda: "external-user"
    request = _OpenSSERequest(_OpenSSERepository(events), _OpenSSEListener())
    app.state.runtime = request.app.state.runtime

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        valid = await client.get(
            f"/events/{run_id}", params={"after": 1}, headers={"Last-Event-ID": "2"}
        )
        invalid_header = await client.get(f"/events/{run_id}", headers={"Last-Event-ID": "bad"})
        negative_header = await client.get(f"/events/{run_id}", headers={"Last-Event-ID": "-1"})
        negative_after = await client.get(f"/events/{run_id}", params={"after": -1})

    assert valid.status_code == 200
    assert "id: 1\n" not in valid.text
    assert "id: 3\nevent: run.completed" in valid.text
    assert invalid_header.status_code == 422
    assert negative_header.status_code == 422
    assert negative_after.status_code == 422


@pytest.mark.postgres
async def test_p2_it20_real_pg_open_sse_drain_cursor_delta_and_authorization(platform):
    """P2-IT06/20: real DB replay plus live NOTIFY delta through the public ASGI route."""
    from agent_platform.core_platform.tool_gateway.replay import DurableToolReplayCache

    client, services, settings = platform
    agent, _ = await create_agent(client)
    _app, key = await application(client, agent["id"])
    _, other_key = await application(client, agent["id"])
    auth = headers(key["key"])
    for forged in (str(uuid4()), "00000000-0000-0000-0000-000000000000"):
        denied = await client.post(
            PUBLIC + "/conversations",
            headers=auth,
            json={"agent_id": forged, "external_session_id": "forged-" + forged},
        )
        assert denied.status_code in {403, 404, 422}

    cid = await session(client, key["key"], agent["id"])
    submitted = await client.post(
        f"{PUBLIC}/conversations/{cid}/messages",
        headers=auth,
        json={"message": "private-open-input", "wait_seconds": 0},
    )
    assert submitted.status_code == 202
    run_id = submitted.json()["id"]
    owner = uuid4()
    claimed = await services.repository.claim(owner, 30, settings.tenant_id)
    assert claimed is not None and str(claimed["id"]) == run_id
    for index in range(201):
        await services.repository.append(
            claimed["id"], owner, "open.pagination", {"index": index, "private": "redact-me"}
        )
    await services.repository.finish(
        claimed["id"], owner, "completed", output="public-open-answer", history=[]
    )
    terminal = await services.repository.get(claimed["id"], settings.tenant_id)
    terminal_seq = terminal["event_seq"]
    replay_key = f"runtime:{run_id}:" + "b" * 64
    await DurableToolReplayCache(services.repository.engine).put(
        replay_key, {"private_replay": "never-public"}
    )
    final = await services.repository.get(claimed["id"], settings.tenant_id)
    assert final["event_seq"] == terminal_seq + 1

    events_url = f"{PUBLIC}/runs/{run_id}/events"
    response = await client.get(events_url, headers=auth)
    assert response.status_code == 200, response.text
    ids = [int(line[4:]) for line in response.text.splitlines() if line.startswith("id: ")]
    assert ids == list(range(1, terminal_seq + 1))
    assert response.text.count("event: open.pagination") == 201
    assert response.text.rstrip().endswith("}")
    assert response.text.rfind(f"id: {terminal_seq}\nevent: run.completed") > response.text.rfind(
        "event: open.pagination"
    )
    assert "public-open-answer" in response.text
    assert "tool.replay" not in response.text and "never-public" not in response.text
    assert "redact-me" not in response.text and "private-open-input" not in response.text
    assert all(
        field not in response.text
        for field in ("gateway_call_id", "tool_snapshot", "history", "outcome", "context")
    )
    assert (await client.get(events_url, headers=headers(other_key["key"]))).status_code == 404
    assert (
        await client.get(events_url, headers=headers(key["key"], user="employee-2"))
    ).status_code == 404
    public_run = await client.get(f"{PUBLIC}/runs/{run_id}", headers=auth)
    assert public_run.status_code == 200
    assert set(public_run.json()) == {
        "id",
        "conversation_id",
        "status",
        "cancel_requested",
        "output",
        "error_code",
        "created_at",
        "started_at",
        "finished_at",
    }

    after_wins = await client.get(
        events_url,
        params={"after": terminal_seq},
        headers={**auth, "Last-Event-ID": "1"},
    )
    header_wins = await client.get(
        events_url,
        params={"after": 1},
        headers={**auth, "Last-Event-ID": str(terminal_seq)},
    )
    assert after_wins.status_code == header_wins.status_code == 200
    assert "event: run.completed" not in after_wins.text
    assert "event: run.completed" not in header_wins.text
    assert "tool.replay" not in after_wins.text + header_wins.text
    for invalid in ("bad", "-1", "2147483648"):
        assert (
            await client.get(events_url, headers={**auth, "Last-Event-ID": invalid})
        ).status_code == 422
    for after in (-1, 2147483648, "bad", "1.5"):
        assert (
            await client.get(events_url, params={"after": after}, headers=auth)
        ).status_code == 422
    assert (await client.get(f"{PUBLIC}/runs/{uuid4()}/events", headers=auth)).status_code == 404

    subscribed = asyncio.Event()
    original_subscribe = services.listener.subscribe

    async def tracked_subscribe(tracked_run_id):
        queue = await original_subscribe(tracked_run_id)
        subscribed.set()
        return queue

    services.listener.subscribe = tracked_subscribe
    live_task = asyncio.create_task(
        client.get(
            events_url,
            params={"after": final["event_seq"]},
            headers=auth,
        )
    )
    try:
        await asyncio.wait_for(subscribed.wait(), 5)
        await services.notifier.send(
            claimed["id"],
            {"k": "delta", "round": 1, "text": "visible-delta", "reasoning": "private-reasoning"},
        )
        live = await asyncio.wait_for(live_task, 10)
    finally:
        services.listener.subscribe = original_subscribe
        if not live_task.done():
            live_task.cancel()
        await asyncio.gather(live_task, return_exceptions=True)
    assert live.status_code == 200
    delta_frames = [frame for frame in live.text.split("\n\n") if "event: model.delta" in frame]
    assert len(delta_frames) == 1
    assert "id:" not in delta_frames[0]
    assert "visible-delta" in delta_frames[0] and "private-reasoning" not in live.text
    stored = await services.repository.events(claimed["id"], settings.tenant_id)
    assert all(event["type"] != "model.delta" for event in stored)
    replay = await client.get(events_url, headers=auth)
    assert "visible-delta" not in replay.text and "event: model.delta" not in replay.text
