import asyncio
import json
import os
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from langchain_core.messages import AIMessage
from pydantic import SecretStr
from sqlalchemy import text

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_runtime.engine import RuntimeEngine
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import (
    BusyError,
    CapacityError,
    RunRequest,
    RuntimeFault,
)
from agent_platform.core_platform.agent_runtime.worker import RuntimeWorker
from agent_platform.core_platform.platform_services.model_gateway.service import DemoModel
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.core_platform.tool_gateway.replay import DurableToolReplayCache
from agent_platform.core_platform.tool_gateway.service import ToolGateway

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


@pytest_asyncio.fixture
async def database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "test-" + str(uuid4())
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    engine = create_engine(settings)
    repo = RunRepository(engine, BusinessRuntimePersistenceHooks())
    try:
        yield repo, settings
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM runtime_runs WHERE tenant_id=:tenant"), {"tenant": tenant}
            )
            await conn.execute(
                text("DELETE FROM runtime_conversations WHERE tenant_id=:tenant"),
                {"tenant": tenant},
            )
        await engine.dispose()


async def submit(repo, settings, conversation="one", **kwargs):
    return await repo.submit(
        settings.tenant_id,
        RunRequest(conversation_id=conversation, message="hello"),
        {"fingerprint": "test"},
        kwargs.get("capacity", 10000),
        kwargs.get("tenant_capacity", 100),
        120,
    )


@asynccontextmanager
async def internal_runtime_client(settings):
    from agent_platform.applications.customer_service.main import create_app

    configured = settings.model_copy(update={"api_token": SecretStr("test-token")})
    app = create_app(configured)
    async with app.router.lifespan_context(app):  # noqa: SIM117
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            client.headers["Authorization"] = "Bearer test-token"
            yield app, client


def sse_ids(body):
    return [int(line.removeprefix("id: ")) for line in body.splitlines() if line.startswith("id: ")]


class RecordingRuntimePersistenceHooks:
    def __init__(self):
        self.delegate = BusinessRuntimePersistenceHooks()
        self.completed = []

    async def add_message(self, conn, conversation_id, role, content, run_id=None):
        await self.delegate.add_message(conn, conversation_id, role, content, run_id)

    async def on_completed(self, conn, run, conversation_id, output, history, completion):
        self.completed.append((run["id"], output, history, completion))
        return await self.delegate.on_completed(
            conn, run, conversation_id, output, history, completion
        )


async def test_concurrent_submit_and_exclusive_claim(database):
    repo, settings = database
    results = await asyncio.gather(
        *(submit(repo, settings) for _ in range(5)), return_exceptions=True
    )
    assert sum(isinstance(item, dict) for item in results) == 1
    assert sum(isinstance(item, BusyError) for item in results) == 4
    owners = [uuid4() for _ in range(5)]
    claims = await asyncio.gather(*(repo.claim(owner, 30, settings.tenant_id) for owner in owners))
    assert sum(item is not None for item in claims) == 1


async def test_capacity_and_tenant_isolation(database):
    repo, settings = database
    row = await submit(repo, settings, tenant_capacity=1)
    with pytest.raises(CapacityError):
        await submit(repo, settings, "two", tenant_capacity=1)
    assert await repo.get(row["id"], "other-tenant") is None
    assert await repo.events(row["id"], "other-tenant") == []
    assert await repo.cancel(row["id"], "other-tenant") is None


async def test_cancellation_wins_finish_race_and_event_replay(database):
    """P0-IT-02: running cancellation beats a late successful finish."""
    repo, settings = database
    row = await submit(repo, settings)
    owner = uuid4()
    await repo.claim(owner, 30, settings.tenant_id)
    requested = await repo.cancel(row["id"], settings.tenant_id)
    assert requested["status"] == "running"
    assert requested["cancel_requested"] is True
    await repo.finish(row["id"], owner, "completed", output="must not publish", history=[])
    final = await repo.get(row["id"], settings.tenant_id)
    assert final["status"] == "cancelled"
    assert final["output"] is None
    assert final["error_code"] is None
    assert final["lease_until"] is None
    assert final["finished_at"] is not None
    events = await repo.events(row["id"], settings.tenant_id)
    assert [event["seq"] for event in events] == list(range(1, len(events) + 1))
    assert [event["type"] for event in events] == [
        "run.queued",
        "run.started",
        "run.cancel_requested",
        "run.cancelled",
    ]
    assert events[-1]["data"] == {"output": None, "error_code": None}
    replay = await repo.events(row["id"], settings.tenant_id, events[-2]["seq"])
    assert [event["type"] for event in replay] == ["run.cancelled"]
    await submit(repo, settings)  # active conversation slot was released


async def test_persisted_history_survives_repository_recreation(database):
    repo, settings = database
    row = await submit(repo, settings)
    owner = uuid4()
    await repo.claim(owner, 30, settings.tenant_id)
    history = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    await repo.finish(row["id"], owner, "completed", output="hi", history=history)
    await submit(repo, settings)
    recreated = RunRepository(repo.engine, BusinessRuntimePersistenceHooks())
    next_run = await recreated.claim(uuid4(), 30, settings.tenant_id)
    assert next_run["history"] == history


async def test_lost_worker_is_failed_and_cannot_publish_late_result(database):
    """P0-IT-04: an expired lease cannot heartbeat or publish, even after reaping."""
    repo, settings = database
    row = await submit(repo, settings)
    owner = uuid4()
    await repo.claim(owner, 30, settings.tenant_id)
    async with repo.engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE runtime_runs SET lease_until=now()-:seconds * interval '1 second' "
                "WHERE id=:id"
            ),
            {"id": row["id"], "seconds": 1},
        )
    assert await repo.heartbeat(row["id"], owner, 30) == "lost"
    await repo.finish(row["id"], owner, "completed", output="expired", history=[])
    assert (await repo.get(row["id"], settings.tenant_id))["output"] is None
    await repo.reap(settings.tenant_id)
    await repo.finish(row["id"], owner, "completed", output="late", history=[])
    final = await repo.get(row["id"], settings.tenant_id)
    assert final["status"] == "failed"
    assert final["error_code"] == "worker_lost"
    assert final["output"] is None
    assert final["lease_until"] is None
    events = await repo.events(row["id"], settings.tenant_id)
    assert [event["type"] for event in events] == ["run.queued", "run.started", "run.failed"]
    assert events[-1]["data"] == {"error_code": "worker_lost"}
    assert final["event_seq"] == len(events) == 3


async def test_queue_expiration_and_cancel_without_worker(database):
    repo, settings = database
    row = await submit(repo, settings)
    final = await repo.cancel(row["id"], settings.tenant_id)
    assert final["status"] == "cancelled"
    next_run = await submit(repo, settings)
    async with repo.engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_runs SET queue_expires_at=now()-interval '1 second' WHERE id=:id"),
            {"id": next_run["id"]},
        )
    await repo.reap(settings.tenant_id)
    assert (await repo.get(next_run["id"], settings.tenant_id))["error_code"] == "queue_timeout"


async def test_worker_runs_real_graph_and_persists_events(database):
    repo, settings = database
    row = await submit(repo, settings)
    async with httpx.AsyncClient() as client:
        worker = RuntimeWorker(
            repo, RuntimeEngine(DemoModel(), ToolGateway(client, []), settings), settings, "test"
        )
        task = asyncio.create_task(worker.serve())
        try:
            async with asyncio.timeout(5):
                while (final := await repo.get(row["id"], settings.tenant_id))["status"] not in {
                    "completed",
                    "failed",
                }:
                    await asyncio.sleep(0.05)
            assert final["status"] == "completed"
            assert "演示模式" in final["output"]
            events = await repo.events(row["id"], settings.tenant_id)
            assert events[-1]["type"] == "run.completed"
        finally:
            worker.stop()
            await task


async def test_http_api_authorization_conflicts_cancel_and_sse(database):
    from agent_platform.applications.customer_service.main import create_app

    _repo, settings = database
    settings = settings.model_copy(update={"api_token": SecretStr("test-token")})
    app = create_app(settings)
    async with app.router.lifespan_context(app):  # noqa: SIM117
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            assert (await client.get("/api/v1/ready")).status_code == 401
            client.headers["Authorization"] = "Bearer test-token"
            assert (await client.get("/api/v1/ready")).status_code == 200
            payload = {"conversation_id": "http-test", "message": "hello"}
            response = await client.post("/api/v1/runs", json=payload)
            assert response.status_code == 202
            run_id = response.json()["id"]
            assert (await client.post("/api/v1/runs", json=payload)).status_code == 409
            cancelled = await client.post(f"/api/v1/runs/{run_id}/cancel")
            assert cancelled.json()["status"] == "cancelled"
            stream = await client.get(f"/api/v1/runs/{run_id}/events")
            assert stream.status_code == 200
            assert "event: run.queued" in stream.text and "event: run.cancelled" in stream.text
            replay = await client.get(
                f"/api/v1/runs/{run_id}/events", headers={"Last-Event-ID": "1"}
            )
            assert "run.queued" not in replay.text and "run.cancelled" in replay.text
            invalid = await client.get(
                f"/api/v1/runs/{run_id}/events", headers={"Last-Event-ID": "-1"}
            )
            assert invalid.status_code == 400
            assert (await client.get(f"/api/v1/runs/{uuid4()}")).status_code == 404


async def test_end_to_end_demo_uses_real_http_and_persistent_events(database, tmp_path):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from agent_platform.applications.customer_service.main import create_app

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.path)
            body = json.dumps({"demo": True, "status": "shipped"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _repo, settings = database
    tool_file = tmp_path / "tools.json"
    tool_file.write_text(
        json.dumps(
            [
                {
                    "name": "demo_order_lookup",
                    "description": "Demo query",
                    "url": f"http://127.0.0.1:{server.server_port}/orders",
                    "parameters": {
                        "type": "object",
                        "properties": {"order_id": {"type": "string"}},
                        "required": ["order_id"],
                        "additionalProperties": False,
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    app = create_app(settings.model_copy(update={"tools_file": tool_file, "embedded_worker": True}))
    try:
        async with app.router.lifespan_context(app):  # noqa: SIM117
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/v1/runs", json={"conversation_id": "live-http", "message": "查询演示"}
                )
                assert response.status_code == 202
                run_id = response.json()["id"]
                async with asyncio.timeout(10):
                    while True:
                        result = (await client.get(f"/api/v1/runs/{run_id}")).json()
                        if result["status"] in {"completed", "failed"}:
                            break
                        await asyncio.sleep(0.05)
                assert result["status"] == "completed", result
                assert "shipped" in result["output"]
                assert received == ["/orders?order_id=DEMO-001"]
                events = (await client.get(f"/api/v1/runs/{run_id}/events")).text
                assert "tool.started" in events and "tool.completed" in events
                assert "run.completed" in events
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)


async def test_cancellation_interrupts_inflight_model(database):
    repo, settings = database
    row = await submit(repo, settings)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class SlowModel:
        async def ainvoke(self, messages):
            started.set()
            try:
                await asyncio.sleep(100)
            finally:
                cancelled.set()

    async with httpx.AsyncClient() as client:
        worker = RuntimeWorker(
            repo, RuntimeEngine(SlowModel(), ToolGateway(client, []), settings), settings, "test"
        )
        task = asyncio.create_task(worker.serve())
        try:
            await asyncio.wait_for(started.wait(), 5)
            await repo.cancel(row["id"], settings.tenant_id)
            await asyncio.wait_for(cancelled.wait(), 5)
            async with asyncio.timeout(5):
                while (await repo.get(row["id"], settings.tenant_id))["status"] != "cancelled":
                    await asyncio.sleep(0.05)
        finally:
            worker.stop()
            await task


async def test_p0_it_01_queued_claim_completed_lifecycle_persists_exact_state(database):
    repo, settings = database
    queued = await submit(repo, settings)
    assert queued["status"] == "queued"
    assert queued["owner"] is None
    assert queued["lease_until"] is None
    assert queued["started_at"] is None
    assert queued["finished_at"] is None

    owner = uuid4()
    claimed = await repo.claim(owner, 30, settings.tenant_id)
    assert claimed["id"] == queued["id"]
    assert claimed["status"] == "running"
    assert claimed["owner"] == owner
    assert claimed["started_at"] is not None
    assert claimed["lease_until"] is not None
    running = await repo.get(queued["id"], settings.tenant_id)
    assert running["lease_valid"] is True
    assert running["started_at"] >= running["created_at"]
    assert running["finished_at"] is None

    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "exact successful output"},
    ]
    await repo.finish(
        queued["id"], owner, "completed", output="exact successful output", history=history
    )
    final = await repo.get(queued["id"], settings.tenant_id)
    assert final["status"] == "completed"
    assert final["owner"] == owner
    assert final["output"] == "exact successful output"
    assert final["error_code"] is None
    assert final["lease_until"] is None
    assert final["lease_valid"] is None
    assert final["started_at"] == running["started_at"]
    assert final["finished_at"] >= final["started_at"]
    async with repo.engine.connect() as conn:
        stored_history = await conn.scalar(
            text("SELECT history FROM runtime_conversations WHERE id=:id"),
            {"id": final["conversation_id"]},
        )
    assert stored_history == history
    events = await repo.events(queued["id"], settings.tenant_id)
    assert [(event["seq"], event["type"], event["data"]) for event in events] == [
        (1, "run.queued", {}),
        (2, "run.started", {}),
        (
            3,
            "run.completed",
            {"output": "exact successful output", "error_code": None},
        ),
    ]
    assert final["event_seq"] == 3

    await repo.finish(queued["id"], owner, "completed", output="forbidden", history=[])
    assert await repo.get(queued["id"], settings.tenant_id) == final
    assert await repo.events(queued["id"], settings.tenant_id) == events


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("fault", "controlled_runtime_fault"),
        ("run_timeout", "run_timeout"),
        ("exception", "execution_error"),
    ],
)
async def test_p0_it_03_real_worker_persists_sanitized_failure_terminal(
    database, mode, expected_code, caplog
):
    repo, base_settings = database
    provider_marker = "synthetic provider failure detail P0-IT-03"

    class ControlledModel:
        async def ainvoke(self, messages):
            if mode == "fault":
                raise RuntimeFault("controlled_runtime_fault")
            if mode == "run_timeout":
                await asyncio.Event().wait()
            raise RuntimeError(provider_marker)

    settings = base_settings.model_copy(
        update={"run_timeout_seconds": 1, "model_timeout_seconds": 5}
    )
    row = await submit(repo, settings)
    async with httpx.AsyncClient() as client:
        worker = RuntimeWorker(
            repo,
            RuntimeEngine(ControlledModel(), ToolGateway(client, []), settings),
            settings,
            "test",
        )
        claimed = await repo.claim(worker.owner, settings.lease_seconds, settings.tenant_id)
        async with asyncio.timeout(5):
            await worker._execute(claimed)

    final = await repo.get(row["id"], settings.tenant_id)
    assert final["status"] == "failed"
    assert final["error_code"] == expected_code
    assert final["output"] is None
    assert final["lease_until"] is None
    assert final["finished_at"] is not None
    events = await repo.events(row["id"], settings.tenant_id)
    assert [event["type"] for event in events] == [
        "run.queued",
        "run.started",
        "model.started",
        "run.failed",
    ]
    assert events[-1]["data"] == {"output": None, "error_code": expected_code}
    assert final["event_seq"] == len(events) == 4
    assert provider_marker not in json.dumps([event["data"] for event in events])
    assert provider_marker not in str(final["output"])
    assert provider_marker not in str(final["error_code"])
    assert provider_marker not in caplog.text


async def test_p0_it_04_reaper_cancelled_expired_running_lease_keeps_worker_lost(database):
    repo, settings = database
    row = await submit(repo, settings)
    owner = uuid4()
    await repo.claim(owner, 30, settings.tenant_id)
    await repo.cancel(row["id"], settings.tenant_id)
    # Manual time travel only: the running/cancel_requested state came from public APIs.
    async with repo.engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE runtime_runs SET lease_until=now()-:seconds * interval '1 second' "
                "WHERE id=:id"
            ),
            {"id": row["id"], "seconds": 1},
        )
    await repo.reap(settings.tenant_id)
    final = await repo.get(row["id"], settings.tenant_id)
    assert final["status"] == "cancelled"
    assert final["cancel_requested"] is True
    assert final["error_code"] == "worker_lost"
    assert final["output"] is None
    assert final["lease_until"] is None
    events = await repo.events(row["id"], settings.tenant_id)
    assert [event["type"] for event in events] == [
        "run.queued",
        "run.started",
        "run.cancel_requested",
        "run.cancelled",
    ]
    assert events[-1]["data"] == {"error_code": "worker_lost"}
    await repo.finish(row["id"], owner, "completed", output="late", history=[])
    with pytest.raises(asyncio.CancelledError):
        await repo.append(row["id"], owner, "forbidden.late", {})
    assert await repo.get(row["id"], settings.tenant_id) == final
    assert await repo.events(row["id"], settings.tenant_id) == events


async def test_p0_it_04_manual_queued_cancel_flag_reaps_cancelled_with_queue_timeout(database):
    repo, settings = database
    row = await submit(repo, settings)
    # Manually constructed intermediate state: public queued cancel would already be
    # terminal, so direct SQL is required to expose cancel_requested to the reaper.
    async with repo.engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE runtime_runs SET cancel_requested=true, "
                "queue_expires_at=now()-:seconds * interval '1 second' WHERE id=:id"
            ),
            {"id": row["id"], "seconds": 1},
        )
    await repo.reap(settings.tenant_id)
    final = await repo.get(row["id"], settings.tenant_id)
    assert final["status"] == "cancelled"
    assert final["cancel_requested"] is True
    assert final["error_code"] == "queue_timeout"
    assert final["output"] is None
    assert final["finished_at"] is not None
    events = await repo.events(row["id"], settings.tenant_id)
    assert [event["type"] for event in events] == ["run.queued", "run.cancelled"]
    assert events[-1]["data"] == {"error_code": "queue_timeout"}
    assert final["event_seq"] == 2


@pytest.mark.parametrize("cancel_first", [True, False])
async def test_p0_it_05_queued_cancel_and_reap_commit_orders(database, cancel_first):
    repo, settings = database
    row = await submit(repo, settings)
    async with repo.engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE runtime_runs SET queue_expires_at=now()-:seconds * interval '1 second' "
                "WHERE id=:id"
            ),
            {"id": row["id"], "seconds": 1},
        )
    if cancel_first:
        await repo.cancel(row["id"], settings.tenant_id)
        await repo.reap(settings.tenant_id)
        expected_status, expected_error, expected_payload = "cancelled", None, {}
    else:
        await repo.reap(settings.tenant_id)
        await repo.cancel(row["id"], settings.tenant_id)
        expected_status = "failed"
        expected_error = "queue_timeout"
        expected_payload = {"error_code": "queue_timeout"}
    final = await repo.get(row["id"], settings.tenant_id)
    assert final["status"] == expected_status
    assert final["error_code"] == expected_error
    assert final["cancel_requested"] is cancel_first
    events = await repo.events(row["id"], settings.tenant_id)
    assert [event["type"] for event in events] == ["run.queued", f"run.{expected_status}"]
    assert events[-1]["data"] == expected_payload
    assert final["event_seq"] == 2


async def test_p0_it_05_concurrent_queued_cancel_reap_has_one_terminal_transition(database):
    repo, settings = database
    row = await submit(repo, settings)
    async with repo.engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE runtime_runs SET queue_expires_at=now()-:seconds * interval '1 second' "
                "WHERE id=:id"
            ),
            {"id": row["id"], "seconds": 1},
        )
    await asyncio.gather(repo.cancel(row["id"], settings.tenant_id), repo.reap(settings.tenant_id))
    final = await repo.get(row["id"], settings.tenant_id)
    assert final["status"] in {"cancelled", "failed"}
    if final["status"] == "cancelled":
        assert final["error_code"] is None
        expected_payload = {}
    else:
        assert final["error_code"] == "queue_timeout"
        expected_payload = {"error_code": "queue_timeout"}
    events = await repo.events(row["id"], settings.tenant_id)
    terminal = [event for event in events if event["type"] in {"run.cancelled", "run.failed"}]
    assert len(terminal) == 1
    assert terminal[0]["type"] == f"run.{final['status']}"
    assert terminal[0]["data"] == expected_payload
    assert final["event_seq"] == len(events) == 2

    await asyncio.gather(repo.cancel(row["id"], settings.tenant_id), repo.reap(settings.tenant_id))
    assert await repo.get(row["id"], settings.tenant_id) == final
    assert await repo.events(row["id"], settings.tenant_id) == events


async def test_p0_it_06_terminal_rejects_late_append_and_repeat_finish(database):
    repo, settings = database
    row = await submit(repo, settings)
    owner = uuid4()
    await repo.claim(owner, 30, settings.tenant_id)
    await repo.finish(row["id"], owner, "completed", output="original", history=[])
    final = await repo.get(row["id"], settings.tenant_id)
    events = await repo.events(row["id"], settings.tenant_id)
    with pytest.raises(asyncio.CancelledError):
        await repo.append(row["id"], owner, "forbidden.terminal", {"marker": "late"})
    await repo.finish(row["id"], owner, "completed", output="forbidden", history=[])
    assert await repo.get(row["id"], settings.tenant_id) == final
    assert await repo.events(row["id"], settings.tenant_id) == events
    assert final["event_seq"] == 3


async def test_p0_it_06_wrong_owner_finish_and_append_do_not_write(database):
    repo, settings = database
    row = await submit(repo, settings)
    owner = uuid4()
    await repo.claim(owner, 30, settings.tenant_id)
    before = await repo.get(row["id"], settings.tenant_id)
    events = await repo.events(row["id"], settings.tenant_id)
    await repo.finish(row["id"], uuid4(), "completed", output="forbidden", history=[])
    with pytest.raises(asyncio.CancelledError):
        await repo.append(row["id"], uuid4(), "forbidden.owner", {})
    after = await repo.get(row["id"], settings.tenant_id)
    assert after == before
    assert after["status"] == "running"
    assert after["output"] is None
    assert await repo.events(row["id"], settings.tenant_id) == events
    assert after["event_seq"] == 2


async def test_p0_it_06_cancel_requested_rejects_append_and_forces_cancelled_finish(database):
    repo, settings = database
    row = await submit(repo, settings)
    owner = uuid4()
    await repo.claim(owner, 30, settings.tenant_id)
    await repo.cancel(row["id"], settings.tenant_id)
    with pytest.raises(asyncio.CancelledError):
        await repo.append(row["id"], owner, "forbidden.cancel", {})
    await repo.finish(row["id"], owner, "completed", output="forbidden", history=[])
    final = await repo.get(row["id"], settings.tenant_id)
    events = await repo.events(row["id"], settings.tenant_id)
    assert final["status"] == "cancelled"
    assert final["output"] is None
    assert final["error_code"] is None
    assert [event["type"] for event in events] == [
        "run.queued",
        "run.started",
        "run.cancel_requested",
        "run.cancelled",
    ]
    await repo.finish(row["id"], owner, "completed", output="late", history=[])
    assert await repo.get(row["id"], settings.tenant_id) == final
    assert await repo.events(row["id"], settings.tenant_id) == events


async def test_p0_it_06_expired_lease_rejects_append_and_finish(database):
    repo, settings = database
    row = await submit(repo, settings)
    owner = uuid4()
    await repo.claim(owner, 30, settings.tenant_id)
    # Manual lease expiration leaves a running row until the worker/reaper observes it.
    async with repo.engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE runtime_runs SET lease_until=now()-:seconds * interval '1 second' "
                "WHERE id=:id"
            ),
            {"id": row["id"], "seconds": 1},
        )
    before = await repo.get(row["id"], settings.tenant_id)
    events = await repo.events(row["id"], settings.tenant_id)
    with pytest.raises(asyncio.CancelledError):
        await repo.append(row["id"], owner, "forbidden.expired", {})
    await repo.finish(row["id"], owner, "completed", output="forbidden", history=[])
    after = await repo.get(row["id"], settings.tenant_id)
    assert after == before
    assert after["status"] == "running"
    assert after["lease_valid"] is False
    assert after["output"] is None
    assert await repo.events(row["id"], settings.tenant_id) == events
    assert after["event_seq"] == 2


async def test_p0_it_07_internal_sse_after_and_last_event_id_use_strict_max(database):
    _repo, settings = database
    async with internal_runtime_client(settings) as (app, client):
        repo = app.state.runtime.repository
        row = await submit(repo, settings)
        await repo.cancel(row["id"], settings.tenant_id)
        url = f"/api/v1/runs/{row['id']}/events"
        after_wins = await client.get(url, params={"after": 2}, headers={"Last-Event-ID": "1"})
        header_wins = await client.get(url, params={"after": 1}, headers={"Last-Event-ID": "2"})
        boundary = await client.get(url, params={"after": 1}, headers={"Last-Event-ID": "1"})
        strict_terminal = await client.get(url, params={"after": 2}, headers={"Last-Event-ID": "2"})
        assert after_wins.status_code == header_wins.status_code == 200
        assert after_wins.text == header_wins.text == strict_terminal.text == ""
        assert sse_ids(boundary.text) == [2]
        assert "event: run.queued" not in boundary.text
        assert "event: run.cancelled" in boundary.text


async def test_p0_it_07_internal_sse_drains_more_than_200_events_before_terminal(database):
    _repo, settings = database
    async with internal_runtime_client(settings) as (app, client):
        repo = app.state.runtime.repository
        row = await submit(repo, settings)
        owner = uuid4()
        await repo.claim(owner, 30, settings.tenant_id)
        for index in range(201):
            await repo.append(
                row["id"],
                owner,
                "test.pagination",
                {"index": index, "marker": "synthetic-pagination-marker"},
            )
        await repo.finish(row["id"], owner, "completed", output="done", history=[])
        response = await client.get(f"/api/v1/runs/{row['id']}/events")
        assert response.status_code == 200
        assert sse_ids(response.text) == list(range(1, 205))
        assert response.text.count("event: test.pagination") == 201
        assert response.text.rstrip().endswith('data: {"output": "done", "error_code": null}')
        tail = await client.get(f"/api/v1/runs/{row['id']}/events", params={"after": 200})
        assert sse_ids(tail.text) == [201, 202, 203, 204]
        assert "event: run.completed" in tail.text


async def test_p0_it_07_internal_sse_does_not_replay_transient_model_delta(database):
    _repo, settings = database
    delta_marker = "synthetic-transient-delta-marker"

    class StreamingModel:
        async def ainvoke_stream(self, messages, on_delta):
            await on_delta({"content": delta_marker})
            return AIMessage(content="durable answer")

    async with internal_runtime_client(settings) as (app, client):
        repo = app.state.runtime.repository
        configured = app.state.settings
        row = await submit(repo, configured)
        async with httpx.AsyncClient() as model_client:
            worker = RuntimeWorker(
                repo,
                RuntimeEngine(StreamingModel(), ToolGateway(model_client, []), configured),
                configured,
                "test",
                notifier=app.state.runtime.notifier,
            )
            claimed = await repo.claim(worker.owner, configured.lease_seconds, configured.tenant_id)
            await worker._execute(claimed)
        events = await repo.events(row["id"], configured.tenant_id)
        assert [event["type"] for event in events] == [
            "run.queued",
            "run.started",
            "model.started",
            "model.completed",
            "run.completed",
        ]
        response = await client.get(f"/api/v1/runs/{row['id']}/events")
        assert response.status_code == 200
        assert "event: model.delta" not in response.text
        assert delta_marker not in response.text
        assert "durable answer" in response.text


async def test_p0_it_07_internal_sse_hides_terminal_tool_replay_and_advances_cursor(database):
    _repo, settings = database
    replay_marker = "synthetic-replay-result-marker"
    async with internal_runtime_client(settings) as (app, client):
        repo = app.state.runtime.repository
        row = await submit(repo, settings)
        owner = uuid4()
        await repo.claim(owner, 30, settings.tenant_id)
        await repo.finish(row["id"], owner, "completed", output="done", history=[])
        terminal_seq = (await repo.get(row["id"], settings.tenant_id))["event_seq"]
        key = f"runtime:{row['id']}:" + "a" * 64
        await DurableToolReplayCache(repo.engine).put(key, {"marker": replay_marker})
        final = await repo.get(row["id"], settings.tenant_id)
        assert final["event_seq"] == terminal_seq + 1
        stored = await repo.events(row["id"], settings.tenant_id, terminal_seq)
        assert [(event["seq"], event["type"]) for event in stored] == [
            (terminal_seq + 1, "tool.replay")
        ]

        full = await client.get(f"/api/v1/runs/{row['id']}/events")
        assert full.status_code == 200
        assert sse_ids(full.text) == [1, 2, 3]
        assert "event: run.completed" in full.text
        assert "tool.replay" not in full.text
        assert replay_marker not in full.text
        # An empty response proves the hidden replay advanced the cursor to terminal
        # event_seq; otherwise the stream would remain open and emit heartbeats.
        hidden_tail = await client.get(
            f"/api/v1/runs/{row['id']}/events", params={"after": terminal_seq}
        )
        assert hidden_tail.status_code == 200
        assert hidden_tail.text == ""


async def test_p0_it_09_completion_hooks_run_only_for_completed_runs(database):
    repo, settings = database
    hooks = RecordingRuntimePersistenceHooks()
    recording_repo = RunRepository(repo.engine, hooks)
    runs = {}
    for status in ("completed", "failed", "cancelled"):
        row = await submit(recording_repo, settings, conversation=f"hook-{status}")
        owner = uuid4()
        await recording_repo.claim(owner, 30, settings.tenant_id)
        history = [{"role": "assistant", "content": f"{status} history"}]
        await recording_repo.finish(
            row["id"],
            owner,
            status,
            output=f"{status} output" if status == "completed" else None,
            error="controlled_failure" if status == "failed" else None,
            history=history,
            completion={"synthetic": "completion-context"},
        )
        runs[status] = (row, history)

    completed_id = runs["completed"][0]["id"]
    assert hooks.completed == [
        (
            completed_id,
            "completed output",
            runs["completed"][1],
            {"synthetic": "completion-context"},
        )
    ]
    for status, (row, history) in runs.items():
        final = await recording_repo.get(row["id"], settings.tenant_id)
        assert final["status"] == status
        async with repo.engine.connect() as conn:
            stored_history = await conn.scalar(
                text("SELECT history FROM runtime_conversations WHERE id=:id"),
                {"id": row["conversation_id"]},
            )
            messages = (
                (
                    await conn.execute(
                        text(
                            "SELECT role,content,run_id FROM conversation_messages "
                            "WHERE conversation_id=:id ORDER BY created_at,id"
                        ),
                        {"id": row["conversation_id"]},
                    )
                )
                .mappings()
                .all()
            )
        assert stored_history == (history if status == "completed" else [])
        assistant = [dict(message) for message in messages if message["role"] == "assistant"]
        if status == "completed":
            assert assistant == [
                {"role": "assistant", "content": "completed output", "run_id": completed_id}
            ]
        else:
            assert assistant == []
            assert final["output"] is None
