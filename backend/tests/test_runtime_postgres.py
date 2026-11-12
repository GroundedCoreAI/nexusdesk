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


class P2ScriptedRuntime:
    def __init__(self, events=(), *, output="orchestrated", completion_gate=None):
        self.events = events
        self.output = output
        self.completion_gate = completion_gate
        self.entered = asyncio.Event()

    async def run(self, message, history, emit, **kwargs):
        self.entered.set()
        for kind, data in self.events:
            await emit(kind, data)
        if self.completion_gate is not None:
            await self.completion_gate.wait()
        history = [
            {"role": "user", "content": message},
            {"role": "assistant", "content": self.output},
        ]
        return self.output, history, []


class P2ScriptedFactory:
    def __init__(self, runtime):
        self.runtime = runtime

    async def for_run(self, row, emit):
        return self.runtime


def p2_orchestrator(factory, adapters=None, *, queue_capacity=1, configure=None):
    from test_execution_orchestrator import _registry

    from agent_platform.core_platform.agent_execution.adapters.react import ReactAdapter
    from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
        capture_execution_context,
    )
    from agent_platform.core_platform.agent_execution.orchestration.orchestrator import (
        ExecutionOrchestrator,
    )

    def make_adapter():
        adapter = ReactAdapter(capture_execution_context(), factory, queue_capacity=queue_capacity)
        if adapters is not None:
            adapters.append(adapter)
        if configure is not None:
            configure(adapter)
        return adapter

    return ExecutionOrchestrator(_registry(make_adapter))


def p2_context(row):
    from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
        build_execution_context,
    )

    return build_execution_context(row, history=row["history"], timeout_seconds=30)


async def p2_expire_lease(repo, run_id):
    async with repo.engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_runs SET lease_until=now()-interval '1 second' WHERE id=:id"),
            {"id": run_id},
        )


def p2_terminal_events(events):
    return [
        event
        for event in events
        if event["type"] in {"run.completed", "run.failed", "run.cancelled"}
    ]


def p2_configure_worker(services, enabled):
    """Select the real off/on composition path without changing claimed rows."""
    from agent_platform.applications.platform_runtime.runtime_composition import (
        _build_execution_orchestrator,
    )

    settings = services.worker.settings.model_copy(
        update={"execution_orchestrator_enabled": enabled}
    )
    services.worker.settings = settings
    services.worker.orchestrator = (
        _build_execution_orchestrator(services.worker.runtime) if enabled else None
    )
    return settings


async def p2_execute_next(services, settings):
    row = await services.repository.claim(services.worker.owner, 30, settings.tenant_id)
    assert row is not None
    await services.worker._execute(row)
    final = await services.repository.get(row["id"], settings.tenant_id)
    assert final is not None
    return final


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

        live_marker = "synthetic-live-transient-delta-marker"
        live_row = await submit(repo, configured, conversation="live-transient-delta")
        live_owner = uuid4()
        live_claimed = await repo.claim(live_owner, 30, configured.tenant_id)
        assert live_claimed is not None and live_claimed["id"] == live_row["id"]
        subscribed = asyncio.Event()
        delta_consumed = asyncio.Event()
        original_subscribe = app.state.runtime.listener.subscribe

        async def tracked_subscribe(tracked_run_id):
            queue = await original_subscribe(tracked_run_id)
            original_get = queue.get

            async def tracked_get():
                payload = await original_get()
                if json.loads(payload).get("k") == "delta":
                    delta_consumed.set()
                return payload

            queue.get = tracked_get
            subscribed.set()
            return queue

        live_url = f"/api/v1/runs/{live_row['id']}/events"
        app.state.runtime.listener.subscribe = tracked_subscribe
        live_task = asyncio.create_task(client.get(live_url))
        try:
            await asyncio.wait_for(subscribed.wait(), 5)
            await app.state.runtime.notifier.send(
                live_row["id"],
                {"k": "delta", "round": 1, "text": live_marker, "reasoning": "live-reasoning"},
            )
            await asyncio.wait_for(delta_consumed.wait(), 5)
            await repo.append(live_row["id"], live_owner, "extension.after_delta", {"stable": True})
            await repo.finish(
                live_row["id"], live_owner, "completed", output="live done", history=[]
            )
            live = await asyncio.wait_for(live_task, 10)
        finally:
            app.state.runtime.listener.subscribe = original_subscribe
            if not live_task.done():
                live_task.cancel()
            await asyncio.gather(live_task, return_exceptions=True)

        assert live.status_code == 200
        delta_frames = [frame for frame in live.text.split("\n\n") if "event: model.delta" in frame]
        assert len(delta_frames) == 1
        assert "id:" not in delta_frames[0]
        assert live_marker in delta_frames[0]
        assert sse_ids(live.text) == [1, 2, 3, 4]
        assert live.text.index("event: run.started") < live.text.index("event: model.delta")
        assert live.text.index("event: model.delta") < live.text.index(
            "event: extension.after_delta"
        )
        assert live.text.rindex("event: run.completed") > live.text.index(
            "event: extension.after_delta"
        )
        live_stored = await repo.events(live_row["id"], configured.tenant_id)
        assert [event["type"] for event in live_stored] == [
            "run.queued",
            "run.started",
            "extension.after_delta",
            "run.completed",
        ]
        assert all(event["type"] != "model.delta" for event in live_stored)
        for replay in (
            await client.get(live_url, params={"after": 0}),
            await client.get(live_url, headers={"Last-Event-ID": "2"}),
        ):
            assert replay.status_code == 200
            assert live_marker not in replay.text
            assert "event: model.delta" not in replay.text
            assert replay.text.rindex("event: run.completed") > replay.text.index(
                "event: extension.after_delta"
            )


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


@pytest.mark.parametrize("terminal", ["finish", "reap"])
@pytest.mark.parametrize("terminal_first", [True, False])
async def test_p2_it09_running_first_commit_wins_for_cancel_finish_and_reaper(
    database, terminal, terminal_first
):
    """P2-IT09: persistent first-commit-wins, with exactly one terminal frame."""
    repo, settings = database
    row = await submit(repo, settings)
    owner = uuid4()
    await repo.claim(owner, 30, settings.tenant_id)
    if terminal == "reap":
        await p2_expire_lease(repo, row["id"])

    async def terminate():
        if terminal == "finish":
            await repo.finish(row["id"], owner, "completed", output="late", history=[])
        else:
            await repo.reap(settings.tenant_id)

    if terminal_first:
        await terminate()
        cancelled = await repo.cancel(row["id"], settings.tenant_id)
        assert cancelled["status"] in {"completed", "failed"}
    else:
        requested = await repo.cancel(row["id"], settings.tenant_id)
        assert requested["cancel_requested"] is True
        await terminate()

    final = await repo.get(row["id"], settings.tenant_id)
    expected_status = (
        ("completed" if terminal == "finish" else "failed") if terminal_first else "cancelled"
    )
    expected_error = "worker_lost" if terminal == "reap" else None
    assert final["status"] == expected_status
    assert final["error_code"] == expected_error
    assert final["output"] == ("late" if expected_status == "completed" else None)
    events = await repo.events(row["id"], settings.tenant_id)
    terminal_events = p2_terminal_events(events)
    assert len(terminal_events) == 1
    assert terminal_events[0]["type"] == f"run.{expected_status}"
    assert events[-1] == terminal_events[0]
    before = (final, events)
    await terminate()
    await repo.cancel(row["id"], settings.tenant_id)
    assert (
        await repo.get(row["id"], settings.tenant_id),
        await repo.events(row["id"], settings.tenant_id),
    ) == before


@pytest.mark.parametrize("terminal_first", [True, False])
async def test_p2_it09_queued_reaper_cancel_orders_and_cancelled_queue_timeout(
    database, terminal_first
):
    repo, settings = database
    row = await submit(repo, settings)
    async with repo.engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE runtime_runs SET queue_expires_at=now()-interval '1 second', "
                "cancel_requested=:cancel_requested WHERE id=:id"
            ),
            {"id": row["id"], "cancel_requested": not terminal_first},
        )
    if terminal_first:
        await repo.reap(settings.tenant_id)
        await repo.cancel(row["id"], settings.tenant_id)
    else:
        await repo.reap(settings.tenant_id)
    final = await repo.get(row["id"], settings.tenant_id)
    assert final["status"] == ("failed" if terminal_first else "cancelled")
    assert final["error_code"] == "queue_timeout"
    events = await repo.events(row["id"], settings.tenant_id)
    assert len(p2_terminal_events(events)) == 1
    assert events[-1]["data"] == {"error_code": "queue_timeout"}


@pytest.mark.parametrize("stale_state", ["expired", "reaped", "cancelled"])
async def test_p2_it11_stale_react_append_rethrows_cleans_and_preserves_terminal(
    database, stale_state
):
    """P2-IT11: real Adapter/Orchestrator/Repository append control flow and cleanup."""
    repo, settings = database
    row = await submit(repo, settings)
    owner = uuid4()
    claimed = await repo.claim(owner, 30, settings.tenant_id)
    if stale_state in {"expired", "reaped"}:
        await p2_expire_lease(repo, row["id"])
        assert await repo.heartbeat(row["id"], owner, 30) == "lost"
        if stale_state == "reaped":
            await repo.reap(settings.tenant_id)
    else:
        await repo.cancel(row["id"], settings.tenant_id)
        await repo.finish(row["id"], owner, "cancelled", error=None)
    before = await repo.get(row["id"], settings.tenant_id)
    before_events = await repo.events(row["id"], settings.tenant_id)
    adapters = []
    runtime = P2ScriptedRuntime((("extension.stale", {"secret": "not-persisted"}),))
    orchestrator = p2_orchestrator(P2ScriptedFactory(runtime), adapters)

    async def worker_emit(kind, data):
        await repo.append(row["id"], owner, kind, data)

    with pytest.raises(asyncio.CancelledError):
        await orchestrator.execute(p2_context(claimed), worker_emit)

    execution = adapters[0]._execution
    assert execution.stream_state == "closed"
    assert execution.task.done()
    assert execution.terminal.result().status == "cancelled"
    assert execution.in_flight is None and execution.undelivered == 0
    assert all(task.done() for task in adapters[0]._owned_tasks)
    await repo.finish(row["id"], owner, "completed", output="forbidden", history=[])
    after = await repo.get(row["id"], settings.tenant_id)
    after_events = await repo.events(row["id"], settings.tenant_id)
    assert after == before
    assert after_events == before_events
    assert all(event["type"] != "extension.stale" for event in after_events)
    assert after["error_code"] != "execution_error"
    if stale_state == "expired":
        assert after["status"] == "running" and after["lease_valid"] is False
        await repo.reap(settings.tenant_id)
        after = await repo.get(row["id"], settings.tenant_id)
        assert after["status"] == "failed" and after["error_code"] == "worker_lost"
    elif stale_state == "reaped":
        assert after["status"] == "failed" and after["error_code"] == "worker_lost"
    else:
        assert after["status"] == "cancelled" and after["error_code"] is None
    if stale_state != "expired":
        assert len(p2_terminal_events(after_events)) == 1


async def test_p2_it11_worker_heartbeat_loss_is_worker_lost_not_user_cancellation(
    database, monkeypatch
):
    repo, base_settings = database
    settings = base_settings.model_copy(update={"execution_orchestrator_enabled": True})
    row = await submit(repo, settings)
    gate = asyncio.Event()
    runtime = P2ScriptedRuntime(completion_gate=gate)
    adapters = []
    orchestrator = p2_orchestrator(P2ScriptedFactory(runtime), adapters)
    worker = RuntimeWorker(
        repo, P2ScriptedFactory(runtime), settings, "test", orchestrator=orchestrator
    )
    claimed = await repo.claim(worker.owner, settings.lease_seconds, settings.tenant_id)
    monitor_started = asyncio.Event()
    release_monitor = asyncio.Event()

    async def gated_sleep(_seconds):
        monitor_started.set()
        await release_monitor.wait()

    monkeypatch.setattr(asyncio, "sleep", gated_sleep)
    task = asyncio.create_task(worker._execute(claimed))
    await asyncio.wait_for(runtime.entered.wait(), 1)
    await asyncio.wait_for(monitor_started.wait(), 1)
    await p2_expire_lease(repo, row["id"])
    release_monitor.set()
    await asyncio.wait_for(task, 1)

    interrupted = await repo.get(row["id"], settings.tenant_id)
    assert interrupted["status"] == "running" and interrupted["lease_valid"] is False
    assert interrupted["cancel_requested"] is False
    assert p2_terminal_events(await repo.events(row["id"], settings.tenant_id)) == []
    await repo.reap(settings.tenant_id)
    final = await repo.get(row["id"], settings.tenant_id)
    assert final["status"] == "failed" and final["error_code"] == "worker_lost"
    assert final["cancel_requested"] is False
    events = await repo.events(row["id"], settings.tenant_id)
    assert len(p2_terminal_events(events)) == 1
    assert events[-1]["type"] == "run.failed"
    assert all(task.done() for task in adapters[0]._owned_tasks)
    gate.set()


async def test_p2_it16_real_pg_capacity_one_ack_backpressure_and_terminal_order(database):
    """P2-IT16: slow durable worker_emit owns ack and releases capacity-one backpressure."""
    repo, settings = database
    row = await submit(repo, settings)
    owner = uuid4()
    claimed = await repo.claim(owner, 30, settings.tenant_id)
    worker_entered = asyncio.Event()
    release_worker = asyncio.Event()
    third_emit = asyncio.Event()
    order = []

    class Runtime:
        async def run(self, message, history, emit, **kwargs):
            for index in range(4):
                if index == 2:
                    third_emit.set()
                await emit("extension.backpressure", {"index": index})
            return "done", [], []

    adapters = []

    def capture_ack(adapter):
        original_stream = adapter.stream_events

        def stream_events(handle):
            stream = original_stream(handle)
            acknowledge = stream.acknowledge

            async def wrapped_ack(event):
                order.append(f"ack:{event.payload['index']}")
                await acknowledge(event)

            stream.acknowledge = wrapped_ack
            return stream

        adapter.stream_events = stream_events

    orchestrator = p2_orchestrator(P2ScriptedFactory(Runtime()), adapters, configure=capture_ack)

    async def worker_emit(kind, data):
        order.append(f"worker-start:{data['index']}")
        if data["index"] == 0:
            worker_entered.set()
            await release_worker.wait()
        await repo.append(row["id"], owner, kind, data)
        order.append(f"worker-end:{data['index']}")

    task = asyncio.create_task(orchestrator.execute(p2_context(claimed), worker_emit))
    await asyncio.wait_for(worker_entered.wait(), 1)
    await asyncio.wait_for(third_emit.wait(), 1)
    execution = adapters[0]._execution
    assert len(execution.queue) == 1
    assert execution.in_flight is not None and execution.undelivered == 2
    assert order == ["worker-start:0"]
    release_worker.set()
    outcome = await asyncio.wait_for(task, 1)

    assert outcome.status == "completed"
    assert order == [
        item
        for index in range(4)
        for item in (f"worker-start:{index}", f"worker-end:{index}", f"ack:{index}")
    ]
    events = await repo.events(row["id"], settings.tenant_id)
    assert [
        event["data"]["index"] for event in events if event["type"] == "extension.backpressure"
    ] == list(range(4))
    await repo.finish(row["id"], owner, "completed", output="done", history=[])
    events = await repo.events(row["id"], settings.tenant_id)
    assert events[-1]["type"] == "run.completed"
    assert len(p2_terminal_events(events)) == 1
    assert execution.task.done() and all(task.done() for task in adapters[0]._owned_tasks)


@pytest.mark.parametrize("failure", ["ordinary", "repository_cancelled"])
async def test_p2_it16_emit_failure_and_cancelled_append_suppress_late_results(database, failure):
    repo, settings = database
    row = await submit(repo, settings)
    owner = uuid4()
    claimed = await repo.claim(owner, 30, settings.tenant_id)
    runtime = P2ScriptedRuntime(
        (
            ("extension.first", {"index": 1}),
            ("extension.failure", {"index": 2}),
            ("extension.late", {"index": 3}),
        )
    )
    adapters = []
    acknowledged = []

    def capture_ack(adapter):
        original_stream = adapter.stream_events

        def stream_events(handle):
            stream = original_stream(handle)
            acknowledge = stream.acknowledge

            async def wrapped_ack(event):
                acknowledged.append(event.payload["index"])
                await acknowledge(event)

            stream.acknowledge = wrapped_ack
            return stream

        adapter.stream_events = stream_events

    orchestrator = p2_orchestrator(P2ScriptedFactory(runtime), adapters, configure=capture_ack)

    async def worker_emit(kind, data):
        if kind == "extension.failure" and failure == "ordinary":
            raise RuntimeError("synthetic ordinary worker failure")
        await repo.append(row["id"], owner, kind, data)
        if kind == "extension.first" and failure == "repository_cancelled":
            await repo.cancel(row["id"], settings.tenant_id)

    if failure == "ordinary":
        outcome = await orchestrator.execute(p2_context(claimed), worker_emit)
        assert outcome.status == "failed" and outcome.legacy_error_code == "execution_error"
        await repo.finish(row["id"], owner, "failed", error="execution_error")
        final = await repo.get(row["id"], settings.tenant_id)
        assert final["status"] == "failed" and final["error_code"] == "execution_error"
    else:
        with pytest.raises(asyncio.CancelledError):
            await orchestrator.execute(p2_context(claimed), worker_emit)
        await repo.finish(row["id"], owner, "completed", output="late", history=[])
        final = await repo.get(row["id"], settings.tenant_id)
        assert final["status"] == "cancelled" and final["error_code"] is None

    assert acknowledged == [1]
    events = await repo.events(row["id"], settings.tenant_id)
    assert [event["type"] for event in events].count("extension.first") == 1
    assert all(event["type"] not in {"extension.failure", "extension.late"} for event in events)
    assert len(p2_terminal_events(events)) == 1
    execution = adapters[0]._execution
    assert execution.stream_state == "closed" and execution.task.done()
    assert all(task.done() for task in adapters[0]._owned_tasks)


async def test_p2_it18_real_pg_claimed_uuid_enters_execution_context(database):
    """The real React path preserves the claimed mapping through RuntimeFactory."""
    from uuid import UUID

    repo, settings = database
    await submit(repo, settings)
    owner = uuid4()
    claimed = await repo.claim(owner, 30, settings.tenant_id)
    assert claimed is not None
    original_row_id = claimed["id"]
    original_row_id_value = str(original_row_id)
    original_row_id_type = type(original_row_id)
    assert isinstance(original_row_id, UUID)
    assert original_row_id_type is not UUID
    assert original_row_id_type.__module__.startswith("asyncpg.")

    async with internal_runtime_client(settings) as (app, _client):
        factory = app.state.runtime.worker.runtime
        original_for_run = factory.for_run
        factory_calls = []

        async def spy_for_run(row, emit):
            factory_calls.append((row, row["id"], type(row["id"]), emit))
            return await original_for_run(row, emit)

        adapters = []
        factory.for_run = spy_for_run
        try:
            context = p2_context(claimed)
            orchestrator = p2_orchestrator(factory, adapters)

            async def worker_emit(kind, data):
                await repo.append(claimed["id"], owner, kind, data)

            outcome = await orchestrator.execute(context, worker_emit)
            await repo.finish(
                claimed["id"], owner, "completed", output=outcome.output, history=outcome.history
            )
        finally:
            factory.for_run = original_for_run

    assert outcome.status == "completed"
    assert len(factory_calls) == 1
    factory_row, factory_row_id, factory_row_id_type, factory_emit = factory_calls[0]
    assert factory_row is claimed
    assert factory_row_id is original_row_id
    assert factory_row_id_type is original_row_id_type
    assert str(factory_row_id) == original_row_id_value
    assert callable(factory_emit)

    assert context.row is claimed
    assert context.row["id"] is original_row_id
    assert type(context.row["id"]) is original_row_id_type
    assert type(context.execution_id) is UUID
    assert context.execution_id == original_row_id
    request = adapters[0]._execution.request
    assert type(request.execution_id) is UUID
    assert request.execution_id == original_row_id

    events = await repo.events(claimed["id"], settings.tenant_id)
    assert any(event["type"] == "model.completed" for event in events)
    assert events[-1]["type"] == "run.completed"


async def test_p2_it18_mixed_workers_exclusive_claim_parity_and_all_off_rollback(database):
    """P2-IT12/18: off API rows are claimed by on/off Workers without repair."""
    repo, base_settings = database
    off_settings = base_settings.model_copy(update={"execution_orchestrator_enabled": False})
    on_settings = base_settings.model_copy(update={"execution_orchestrator_enabled": True})
    assert off_settings.execution_orchestrator_enabled is False
    assert on_settings.execution_orchestrator_enabled is True
    rows = [await submit(repo, off_settings, conversation=f"mixed-{index}") for index in range(2)]
    off_runtime = P2ScriptedRuntime((("extension.mixed", {"stable": True}),), output="same")
    on_runtime = P2ScriptedRuntime((("extension.mixed", {"stable": True}),), output="same")
    off = RuntimeWorker(repo, P2ScriptedFactory(off_runtime), off_settings, "test")
    on = RuntimeWorker(
        repo,
        P2ScriptedFactory(on_runtime),
        on_settings,
        "test",
        orchestrator=p2_orchestrator(P2ScriptedFactory(on_runtime)),
    )
    off_row, on_row = await asyncio.gather(
        repo.claim(off.owner, 30, settings_tenant := off_settings.tenant_id),
        repo.claim(on.owner, 30, settings_tenant),
    )
    assert off_row is not None and on_row is not None
    assert {off_row["id"], on_row["id"]} == {row["id"] for row in rows}
    assert all(row["config"] == {"fingerprint": "test"} for row in (off_row, on_row))
    await asyncio.gather(off._execute(off_row), on._execute(on_row))
    finals = [await repo.get(row["id"], base_settings.tenant_id) for row in rows]
    assert [final["status"] for final in finals] == ["completed", "completed"]
    assert [final["output"] for final in finals] == ["same", "same"]
    assert all(final["error_code"] != "configuration_changed" for final in finals)
    event_payloads = []
    for row in rows:
        events = await repo.events(row["id"], base_settings.tenant_id)
        event_payloads.append([(event["type"], event["data"]) for event in events])
        assert events[-1]["type"] == "run.completed" and len(p2_terminal_events(events)) == 1
    assert event_payloads[0] == event_payloads[1]

    rollback_row = await submit(repo, on_settings, conversation="all-off-rollback")
    rollback = RuntimeWorker(
        repo, P2ScriptedFactory(P2ScriptedRuntime(output="rollback")), off_settings, "test"
    )
    claimed = await repo.claim(rollback.owner, 30, off_settings.tenant_id)
    assert claimed["id"] == rollback_row["id"]
    await rollback._execute(claimed)
    assert (await repo.get(rollback_row["id"], off_settings.tenant_id))["status"] == "completed"
    assert [await repo.get(row["id"], off_settings.tenant_id) for row in rows] == finals


async def test_p2_it20_real_pg_internal_run_scope_redaction_and_r15_errors(database):
    """P2-IT20/CM04: actual internal routes preserve tenant/workspace isolation."""
    from agent_platform.extension_contracts import BusinessScope

    repo, settings = database
    scope = BusinessScope(
        tenant_id=settings.tenant_id,
        business_id="customer-service",
        workspace_id="default",
    )
    async with internal_runtime_client(settings) as (app, client):
        row = await app.state.runtime.repository.submit(
            settings.tenant_id,
            RunRequest(conversation_id="scoped", message="private scoped input"),
            {"fingerprint": "test"},
            100,
            100,
            120,
            scope=scope,
        )
        await app.state.runtime.repository.cancel(row["id"], settings.tenant_id, scope)
        url = f"/api/v1/runs/{row['id']}"
        scoped_headers = {"X-Workspace-ID": "default"}
        response = await client.get(url, headers=scoped_headers)
        assert response.status_code == 200
        assert set(response.json()) == {
            "id",
            "conversation_id",
            "status",
            "output",
            "error_code",
            "cancel_requested",
            "created_at",
            "started_at",
            "finished_at",
        }
        assert "private scoped input" not in response.text
        assert all(
            field not in response.json()
            for field in ("config", "history", "outcome", "context", "dropped")
        )
        assert (await client.get(url)).status_code == 200
        assert (await client.get(url, headers={"X-Workspace-ID": "workspace-b"})).status_code == 403
        assert (await client.get(url + "/events")).status_code == 200
        assert (await client.get(url + "/events", headers=scoped_headers)).status_code == 200
        other_scope = BusinessScope(
            tenant_id=settings.tenant_id,
            business_id="other-business",
            workspace_id="default",
        )
        assert await repo.get(row["id"], settings.tenant_id, other_scope) is None
        wrong_workspace = BusinessScope(
            tenant_id=settings.tenant_id,
            business_id="customer-service",
            workspace_id="workspace-b",
        )
        assert await repo.get(row["id"], settings.tenant_id, wrong_workspace) is None
        assert await repo.events(row["id"], settings.tenant_id, scope=wrong_workspace) == []
        from agent_platform.core_platform.platform_services.persistence.store import DomainError

        with pytest.raises(DomainError, match="tenant_scope_mismatch"):
            await repo.events(row["id"], "other-" + settings.tenant_id, scope=scope)

        events_url = url + "/events"
        for invalid in ("bad", "-1", "2147483648", "1.5"):
            invalid_response = await client.get(
                events_url,
                params={"after": 1},
                headers={**scoped_headers, "Last-Event-ID": invalid},
            )
            assert invalid_response.status_code == 400
            assert invalid_response.json()["detail"] == "invalid_last_event_id"
        for after in (-1, 2147483648, "bad", "1.5"):
            assert (
                await client.get(events_url, params={"after": after}, headers=scoped_headers)
            ).status_code == 422
        assert (await client.get("/api/v1/runs/not-a-uuid/events")).status_code == 422
        assert (
            await client.get(f"/api/v1/runs/{uuid4()}/events", headers=scoped_headers)
        ).status_code == 404


async def test_p2_it19_real_pg_dynamic_alembic_head_matches_current(database):
    """P2-IT19/CM01: derive the expected revision from the migration scripts."""
    from pathlib import Path

    from alembic.script import ScriptDirectory

    repo, _settings = database
    scripts = ScriptDirectory(str(Path(__file__).parents[1] / "migrations"))
    heads = scripts.get_heads()
    async with repo.engine.connect() as conn:
        current = set(
            (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalars()
        )
    assert len(heads) == 1
    assert current == set(heads)
