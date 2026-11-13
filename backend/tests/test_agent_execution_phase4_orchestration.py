"""Phase 4 orchestration wiring tests (08 T13/T14).

Covers the barrier contract with stubs (single prepare call, R-11 post-
condition, reverse-order cleanup on every pre-start refusal, retention
decision mapping, cancellation precedence, and the React byte-parity gate),
a PG-backed end-to-end run of both process triples through the real
Orchestrator/Host/Workspace stack with a real trusted target (P4-IT-02),
the real-process cancellation race, and the composition recovery-before-
admission boot (T14, P4-IT-09 local half).
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest
from test_ticket_migrations import migrate

from agent_platform.core_platform.agent_execution.contracts import (
    AgentEvent,
    EngineCapabilities,
    ExecutionHandle,
    ExecutionRequest,
    ExecutionResult,
)
from agent_platform.core_platform.agent_execution.host.host_models import HostHealth
from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
    build_execution_context,
)
from agent_platform.core_platform.agent_execution.orchestration.orchestrator import (
    ExecutionOrchestrator,
)
from agent_platform.core_platform.agent_execution.registry import (
    AdapterDescriptor,
    AdapterRegistry,
    EngineDescriptor,
    EngineRegistry,
    ProtocolDescriptor,
    ProtocolRegistry,
)
from agent_platform.core_platform.agent_execution.workspace.workspace_manager import (
    WorkspaceStateError,
)
from agent_platform.core_platform.agent_execution.workspace.workspace_provider import (
    WorkdirRecord,
)
from agent_platform.extension_contracts import BusinessScope

TENANT = "phase4-orch"


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


def _record(status="ready", *, run_id=None, tenant_id=TENANT):
    return WorkdirRecord(
        workdir_id=uuid.uuid4(),
        run_id=run_id or uuid.uuid4(),
        tenant_id=tenant_id,
        business_id="b",
        workspace_id="w",
        relative_path="aa11/bb22",
        status=status,
        quota_bytes=1024,
        size_bytes=0,
        file_count=0,
        created_at_posix=0.0,
    )


class StubWorkspace:
    def __init__(
        self,
        *,
        prepare_status="ready",
        prepare_raises=False,
        activate_raises=False,
    ) -> None:
        self.calls: list[str] = []
        self.retained: list[str] = []
        self.prepare_status = prepare_status
        self.prepare_raises = prepare_raises
        self.activate_raises = activate_raises
        self._record = _record(status="preparing")

    async def prepare(self, *, run_id, tenant_id, business_id, workspace_id):
        self.calls.append("prepare")
        if self.prepare_raises:
            raise WorkspaceStateError("workdir_root_invalid")
        self._record = _record(status=self.prepare_status, run_id=run_id)
        return self._record

    async def activate(self, *, workdir_id, run_id, tenant_id):
        self.calls.append("activate")
        if self.activate_raises:
            raise WorkspaceStateError("workdir_state_invalid")
        self._record = self._record.model_copy(update={"status": "active"})
        return self._record

    async def retain(self, *, workdir_id, run_id, tenant_id, outcome):
        self.calls.append("retain")
        self.retained.append(outcome)

    async def cleanup(self, *, workdir_id, run_id, tenant_id):
        self.calls.append("cleanup")

    async def get(self, *, run_id, tenant_id):
        return self._record


class StubHost:
    def __init__(self, *, admission=True) -> None:
        self.admission = admission
        self.health_calls = 0

    def health(self):
        self.health_calls += 1
        return HostHealth(
            host_id="worker-stub",
            host_instance_id="boot-1",
            sandbox_provider="local/v1",
            admission_enabled=self.admission,
            resource_enforcement_required=True,
            running_count=0,
        )


class StubProcessAdapter:
    engine = "proc-stub"
    protocol = "line-json"

    def __init__(self, *, result=None, stream_blocks=False, start_raises=False) -> None:
        self.result = result or ExecutionResult(
            execution_id=uuid.uuid4(),
            engine_id=self.engine,
            protocol_id=self.protocol,
            adapter_version="v1",
            status="completed",
            output="hello",
        )
        self.calls: list[str] = []
        self.started_request: ExecutionRequest | None = None
        self.stream_blocks = stream_blocks
        self.start_raises = start_raises

    @property
    def engine_id(self):
        return self.engine

    @property
    def protocol_id(self):
        return self.protocol

    @property
    def adapter_version(self):
        return "v1"

    async def get_capabilities(self):
        return EngineCapabilities(workspace_required=True, native_events=True, cancellation=True)

    async def start(self, request):
        self.calls.append("start")
        self.started_request = request
        if self.start_raises:
            raise RuntimeError("host refused")
        return ExecutionHandle(
            execution_id=request.execution_id,
            engine_id=self.engine,
            protocol_id=self.protocol,
            adapter_version="v1",
            provider_session_id="sess-1",
        )

    def stream_events(self, handle):
        async def gen():
            self.calls.append("stream")
            if self.stream_blocks:
                await asyncio.sleep(30)
            yield AgentEvent(
                execution_id=handle.execution_id,
                engine_id=self.engine,
                protocol_id=self.protocol,
                adapter_version="v1",
                event_id=uuid.uuid4(),
                sequence=1,
                event_type="engine.run.completed",
                source="engine_native",
                timestamp=datetime.now(UTC),
                payload={"answer": "hello"},
            )

        return gen()

    async def cancel(self, handle):
        self.calls.append("cancel")

    async def collect_result(self, handle):
        self.calls.append("collect")
        return self.result


def _registry_for(adapter: StubProcessAdapter) -> AdapterRegistry:
    engines = EngineRegistry()
    engines.register(EngineDescriptor(engine_id=adapter.engine))
    protocols = ProtocolRegistry()
    protocols.register(ProtocolDescriptor(protocol_id=adapter.protocol))
    registry = AdapterRegistry(engines, protocols)
    registry.register(
        AdapterDescriptor(
            engine_id=adapter.engine,
            protocol_id=adapter.protocol,
            adapter_version="v1",
            declared=EngineCapabilities(workspace_required=True),
        ),
        lambda: adapter,
    )
    return registry


def _context(run_id: uuid.UUID, *, scope=True):
    row = {
        "id": run_id,
        "tenant_id": TENANT,
        "conversation_id": uuid.uuid4(),
        "input": "phase4 barrier",
        "config": {},
        "workspace_id": None,
    }
    return build_execution_context(
        row,
        history=[{"role": "user", "content": "phase4 barrier"}],
        scope=BusinessScope(tenant_id=TENANT, business_id="b", workspace_id="w") if scope else None,
    )


async def _emit_sink():
    events: list[tuple[str, dict]] = []

    async def emit(event_type, payload):
        events.append((event_type, payload))

    return events, emit


def _orchestrator(workspace, host_stub, adapter, **kwargs):
    return ExecutionOrchestrator(
        _registry_for(adapter),
        selector=(adapter.engine, adapter.protocol, "v1"),
        workdir_provider=workspace,
        runtime_host=host_stub,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Barrier semantics (unit, no DB, no process)
# ---------------------------------------------------------------------------


def test_completed_run_prepares_once_activates_retains_success_window():
    workspace = StubWorkspace()
    adapter = StubProcessAdapter()
    events, emit = asyncio.run(_emit_sink())

    async def flow():
        run_id = uuid.uuid4()
        orchestrator = _orchestrator(workspace, StubHost(), adapter)
        return await orchestrator.execute(_context(run_id), emit), run_id

    outcome, _run_id = asyncio.run(flow())
    assert outcome.status == "completed"
    assert workspace.calls == ["prepare", "activate", "retain"]
    assert workspace.retained == ["success"]
    assert adapter.started_request is not None
    assert adapter.started_request.execution_workdir == "aa11/bb22"
    assert events and events[0][0] == "engine.run.completed"


def test_failed_run_retains_failed_window_without_cleanup():
    from agent_platform.core_platform.agent_execution.contracts import (
        ExecutionError,
        ExecutionErrorCategory,
        ExecutionErrorCode,
    )

    adapter = StubProcessAdapter(
        result=ExecutionResult(
            execution_id=uuid.uuid4(),
            engine_id="proc-stub",
            protocol_id="line-json",
            adapter_version="v1",
            status="failed",
            error=ExecutionError(
                category=ExecutionErrorCategory.ENGINE_UNAVAILABLE,
                code=ExecutionErrorCode.ENGINE_UNAVAILABLE,
            ),
        )
    )
    workspace = StubWorkspace()

    async def flow():
        orchestrator = _orchestrator(workspace, StubHost(), adapter)
        _events, emit = await _emit_sink()
        return await orchestrator.execute(_context(uuid.uuid4()), emit)

    outcome = asyncio.run(flow())
    assert outcome.status == "failed"
    assert workspace.retained == ["failed"]
    assert "cleanup" not in workspace.calls


def test_prepare_refusal_prevents_start_without_recorded_directory():
    workspace = StubWorkspace(prepare_raises=True)
    adapter = StubProcessAdapter()

    async def flow():
        orchestrator = _orchestrator(workspace, StubHost(), adapter)
        _events, emit = await _emit_sink()
        return await orchestrator.execute(_context(uuid.uuid4()), emit)

    outcome = asyncio.run(flow())
    assert outcome.status == "failed"
    assert outcome.legacy_error_code == "execution_engine_unavailable"
    assert "activate" not in workspace.calls
    assert adapter.calls == []


def test_r11_violation_shape_is_refused_with_reverse_cleanup():
    workspace = StubWorkspace(prepare_status="retained")
    adapter = StubProcessAdapter()

    async def flow():
        orchestrator = _orchestrator(workspace, StubHost(), adapter)
        _events, emit = await _emit_sink()
        return await orchestrator.execute(_context(uuid.uuid4()), emit)

    outcome = asyncio.run(flow())
    assert outcome.legacy_error_code == "execution_engine_unavailable"
    assert workspace.calls == ["prepare", "cleanup"]
    assert adapter.calls == []


def test_closed_admission_cleans_prepared_workdir_and_blocks_start():
    workspace = StubWorkspace()
    adapter = StubProcessAdapter()

    async def flow():
        orchestrator = _orchestrator(workspace, StubHost(admission=False), adapter)
        _events, emit = await _emit_sink()
        return await orchestrator.execute(_context(uuid.uuid4()), emit)

    outcome = asyncio.run(flow())
    assert outcome.legacy_error_code == "execution_engine_unavailable"
    assert workspace.calls == ["prepare", "cleanup"]
    assert adapter.calls == []


def test_activate_failure_cleans_and_blocks_start():
    workspace = StubWorkspace(activate_raises=True)
    adapter = StubProcessAdapter()

    async def flow():
        orchestrator = _orchestrator(workspace, StubHost(), adapter)
        _events, emit = await _emit_sink()
        return await orchestrator.execute(_context(uuid.uuid4()), emit)

    outcome = asyncio.run(flow())
    assert outcome.legacy_error_code == "execution_engine_unavailable"
    assert workspace.calls == ["prepare", "activate", "cleanup"]
    assert adapter.calls == []


def test_start_failure_cleans_workdir_in_reverse():
    workspace = StubWorkspace()
    adapter = StubProcessAdapter(start_raises=True)

    async def flow():
        orchestrator = _orchestrator(workspace, StubHost(), adapter)
        _events, emit = await _emit_sink()
        return await orchestrator.execute(_context(uuid.uuid4()), emit)

    outcome = asyncio.run(flow())
    assert outcome.status == "failed"
    assert workspace.calls == ["prepare", "activate", "cleanup"]


def test_missing_trusted_scope_fails_closed_before_any_side_effect():
    workspace = StubWorkspace()
    adapter = StubProcessAdapter()

    async def flow():
        orchestrator = _orchestrator(workspace, StubHost(), adapter)
        _events, emit = await _emit_sink()
        return await orchestrator.execute(_context(uuid.uuid4(), scope=False), emit)

    outcome = asyncio.run(flow())
    assert outcome.legacy_error_code == "execution_configuration_invalid"
    assert workspace.calls == []
    assert adapter.calls == []


def test_cancellation_wins_and_retains_cancellation_window():
    workspace = StubWorkspace()
    adapter = StubProcessAdapter(stream_blocks=True)

    async def flow():
        orchestrator = _orchestrator(workspace, StubHost(), adapter)
        _events, emit = await _emit_sink()
        task = asyncio.create_task(orchestrator.execute(_context(uuid.uuid4()), emit))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # the shielded cancel+retain completions settle after the cancel
        await asyncio.sleep(0.05)
        return task

    asyncio.run(flow())
    assert "cancel" in adapter.calls
    assert workspace.calls == ["prepare", "activate", "retain"]
    assert workspace.retained == ["success"]  # cancelled uses the default window


def test_seams_inert_for_react_selection_byte_parity():
    # The declared capability gates the barrier: with the seams wired, the
    # production React registration (workspace_required=False) keeps the
    # exact Phase 3 path and touches neither port.
    from agent_platform.applications.platform_runtime import runtime_composition
    from agent_platform.core_platform.platform_services.platform_settings.settings import (
        Settings,
    )

    settings = Settings(_env_file=None)
    registry = runtime_composition._execution_adapter_registry()
    descriptor = runtime_composition._react_adapter_descriptor(settings)
    orchestrator = ExecutionOrchestrator(
        registry,
        selector=(descriptor.engine_id, descriptor.protocol_id, descriptor.adapter_version),
        workdir_provider=StubWorkspace(),
        runtime_host=StubHost(),
    )
    assert orchestrator.execution_paths_enabled
    assert orchestrator._process_capable_selection() is False


# ---------------------------------------------------------------------------
# Composition builder pins (T14)
# ---------------------------------------------------------------------------


def test_composition_builds_runtime_only_with_stable_host_id():
    from agent_platform.applications.platform_runtime import runtime_composition
    from agent_platform.core_platform.platform_services.platform_settings.settings import (
        Settings,
    )

    base = {
        "_env_file": None,
        "database_url": "postgresql+asyncpg://agent:agent@127.0.0.1/none",
        "tenant_id": TENANT,
    }
    default = Settings(**base)
    assert runtime_composition._build_execution_runtime_subsystem(default, engine=None) is None

    staged = Settings(
        **base,
        execution_runtime_host_id="worker-composition",
        execution_runtime_host_enabled=False,
        execution_workdir_root="/tmp/phase4-composition-root",
    )
    subsystem = runtime_composition._build_execution_runtime_subsystem(
        staged, engine=None, boot_id="boot-test", clock=lambda: 0.0
    )
    assert subsystem is not None
    # enabled=false still assembles the recovery/cleanup lane (03 §5.1, R-8),
    # but admission inside the Host refuses starts.
    assert subsystem.host.health().admission_enabled is False
    assert subsystem.registry.host_instance_id == "boot-test"

    orchestrator = ExecutionOrchestrator(
        runtime_composition._execution_adapter_registry(),
        workdir_provider=subsystem.workspace,
        runtime_host=subsystem.host,
    )
    assert orchestrator.execution_paths_enabled
    assert orchestrator._process_capable_selection() is False


# ---------------------------------------------------------------------------
# PG-backed end-to-end (P4-IT-02) and recovery-before-admission (T14)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def orch_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a PostgreSQL role with CREATEDB")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    name = "phase4_orch_" + uuid.uuid4().hex

    async def admin(statement):
        conn = await asyncpg.connect(url)
        try:
            await conn.execute(statement)
        finally:
            await conn.close()

    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    target = urlunsplit(parts._replace(path="/" + name))
    migrate(target, "head")
    try:
        yield target
    finally:
        asyncio.run(admin(f'DROP DATABASE "{name}" WITH (FORCE)'))


def _drive(url, flow):
    async def main():
        from agent_platform.core_platform.platform_services.persistence.database import (
            create_engine,
        )
        from agent_platform.core_platform.platform_services.platform_settings.settings import (
            Settings,
        )

        settings = Settings(
            _env_file=None,
            database_url=url.replace("postgresql://", "postgresql+asyncpg://"),
            tenant_id=TENANT,
            embedded_worker=False,
        )
        engine = create_engine(settings)
        try:
            await flow(engine)
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def _make_run(engine):
    from agent_platform.applications.platform_runtime.runtime_hooks import (
        BusinessRuntimePersistenceHooks,
    )
    from agent_platform.core_platform.agent_runtime.repository import RunRepository
    from agent_platform.core_platform.agent_runtime.schemas import RunRequest

    repo = RunRepository(engine, BusinessRuntimePersistenceHooks())
    row = await repo.submit(
        TENANT,
        RunRequest(conversation_id=f"conv-{uuid.uuid4()}", message="orchestration test"),
        {"fingerprint": "phase4-orchestration"},
        100,
        100,
        120,
    )
    return uuid.UUID(str(row["id"]))


def _full_stack(engine, root: Path, *, host_id="worker-orch", boot="boot-1", enabled=True):
    from agent_execution.process_test_adapters import build_trusted_registry

    from agent_platform.core_platform.agent_execution.host.local_sandbox_provider import (
        LocalSandboxProvider,
    )
    from agent_platform.core_platform.agent_execution.host.process_registry import (
        ProcessRegistry,
    )
    from agent_platform.core_platform.agent_execution.host.process_runner import (
        ProcessRunner,
    )
    from agent_platform.core_platform.agent_execution.host.process_supervisor import (
        ProcessSupervisor,
    )
    from agent_platform.core_platform.agent_execution.host.resource_manager import (
        ResourceManager,
    )
    from agent_platform.core_platform.agent_execution.host.runtime_host import RuntimeHost
    from agent_platform.core_platform.agent_execution.workspace.workspace_manager import (
        ExecutionWorkspaceManager,
    )

    provider = LocalSandboxProvider(enforcement_required=False)
    resources = ResourceManager(provider, sample_interval_seconds=0.2)
    host = RuntimeHost(
        enabled=enabled,
        host_id=host_id,
        runner=ProcessRunner(build_trusted_registry()),
        supervisor=ProcessSupervisor(cancel_grace_seconds=0.5, kill_timeout_seconds=0.5),
        registry=ProcessRegistry(
            engine, host_id=host_id, host_instance_id=boot, sandbox_provider="local/v1"
        ),
        wall_timeout_seconds=30,
        resource_manager=resources,
    )
    workspace = ExecutionWorkspaceManager(
        engine,
        root=root,
        quota_bytes=1_073_741_824,
        retention_seconds=3600,
        failed_retention_seconds=7200,
    )
    return host, workspace


def _process_registry_for(host, root):
    from agent_execution.process_test_adapters import (
        KeyValueProcessAdapter,
        LineJsonProcessAdapter,
    )

    engines = EngineRegistry()
    engines.register(EngineDescriptor(engine_id="proc-json"))
    engines.register(EngineDescriptor(engine_id="proc-kv"))
    engines.register(EngineDescriptor(engine_id="proc-sleep"))
    protocols = ProtocolRegistry()
    protocols.register(ProtocolDescriptor(protocol_id="line-json"))
    protocols.register(ProtocolDescriptor(protocol_id="key-value"))
    registry = AdapterRegistry(engines, protocols)

    def triple(engine_id, protocol_id, factory, case=None):
        registry.register(
            AdapterDescriptor(
                engine_id=engine_id,
                protocol_id=protocol_id,
                adapter_version="v1",
                declared=EngineCapabilities(
                    workspace_required=True, native_events=True, cancellation=True
                ),
            ),
            factory,
        )

    triple(
        "proc-json",
        "line-json",
        lambda: LineJsonProcessAdapter(host, root=root),
    )
    triple(
        "proc-kv",
        "key-value",
        lambda: KeyValueProcessAdapter(host, root=root),
    )

    class SleeperAdapter(LineJsonProcessAdapter):
        # A process-capable triple that keeps the group alive: the
        # cancellation race test cancels the orchestrator task inside this
        # adapter's stream wait, exactly where a long engine session blocks.
        _CASE = "sleep"
        _ENGINE_ID = "proc-sleep"
        _PROTOCOL_ID = "line-json"

        async def start(self, request):
            from agent_execution.process_test_adapters import make_spec

            relative = str(request.execution_workdir or f"adhoc/{request.execution_id}")
            working_dir = self._root / relative
            working_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            spec = make_spec("sleep", "30", workdir_relative=relative)
            managed = await self._host.start(
                spec,
                run_id=request.execution_id,
                tenant_id=request.tenant_id,
                working_dir=working_dir,
            )
            self._managed_by_execution[request.execution_id] = managed.managed_id
            return ExecutionHandle(
                execution_id=request.execution_id,
                engine_id=self.engine_id,
                protocol_id=self.protocol_id,
                adapter_version="v1",
                provider_session_id=str(managed.managed_id),
            )

        async def stream_events(self, handle):
            await asyncio.sleep(30)
            if False:  # pragma: no cover - keeps this an async generator
                yield

    triple("proc-sleep", "line-json", lambda: SleeperAdapter(host, root=root))
    return registry


@pytest.mark.postgres
def test_orchestrator_end_to_end_with_real_processes(orch_database, tmp_path):
    # P4-IT-02: both process triples drive the real Orchestrator -> Workspace
    # prepare/activate -> Host -> trusted target -> events -> wait -> retain
    # chain with zero Host or Repository changes.
    root = tmp_path / "exec-root"
    root.mkdir(mode=0o700)

    async def flow(engine):
        host, workspace = _full_stack(engine, root)
        registry = _process_registry_for(host, root)
        events_seen: list[str] = []

        async def emit(event_type, payload):
            events_seen.append(event_type)

        for engine_id, protocol_id in (("proc-json", "line-json"), ("proc-kv", "key-value")):
            orchestrator = ExecutionOrchestrator(
                registry,
                selector=(engine_id, protocol_id, "v1"),
                workdir_provider=workspace,
                runtime_host=host,
            )
            run_id = await _make_run(engine)
            outcome = await orchestrator.execute(_context(run_id), emit)
            assert outcome.status == "completed", engine_id
            assert outcome.output == "hello", engine_id
            assert "engine.run.completed" in events_seen

        rows = await workspace.sweep_expired()
        assert rows == []  # fresh retains sit inside the window; nothing expired
        # Durable facts: both Host records closed honestly as exited.
        counts = await host.registry.count_by_state()
        assert counts.get("exited", 0) == 2

    _drive(orch_database, flow)


@pytest.mark.postgres
def test_orchestrator_cancellation_race_with_real_process(orch_database, tmp_path):
    root = tmp_path / "exec-root"
    root.mkdir(mode=0o700)

    async def flow(engine):
        host, workspace = _full_stack(engine, root, host_id="worker-orch-cancel")
        registry = _process_registry_for(host, root)

        async def emit(event_type, payload):
            return None

        orchestrator = ExecutionOrchestrator(
            registry,
            selector=("proc-sleep", "line-json", "v1"),
            workdir_provider=workspace,
            runtime_host=host,
        )
        run_id = await _make_run(engine)
        task = asyncio.create_task(orchestrator.execute(_context(run_id), emit))
        await asyncio.sleep(0.5)  # the trusted sleeper is running
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.2)  # let the shielded cleanup land

        # The bounded machine finished: nothing pending remains (the cancel
        # path reaps before marking, so an empty scan proves the kill).
        rows = await host.registry.fetch_pending(batch_size=10)
        assert rows == []  # nothing left running or orphaned
        current = await workspace.get(run_id=run_id, tenant_id=TENANT)
        assert current is not None
        assert current.status == "retained"
        assert current.expires_at_posix is not None

    _drive(orch_database, flow)


@pytest.mark.postgres
def test_composition_recovery_before_admission(orch_database, tmp_path):
    # T14 startup order (R-8): an orphan row from a previous boot instance is
    # recovered by a composition-built, admission-closed subsystem before any
    # new admission could open; the loops start and stop cleanly.
    from agent_platform.applications.platform_runtime import runtime_composition
    from agent_platform.core_platform.agent_execution.host.process_identity import (
        process_alive,
    )
    from agent_platform.core_platform.platform_services.platform_settings.settings import (
        Settings,
    )

    root = tmp_path / "exec-root"
    root.mkdir(mode=0o700)
    host_id = "worker-composition-boot"

    async def flow(engine):
        spawner_host, _workspace = _full_stack(
            engine, root, host_id=host_id, boot="boot-old", enabled=True
        )
        run_id = await _make_run(engine)
        from agent_execution.process_test_adapters import make_spec

        managed = await spawner_host.start(
            make_spec("sleep", "30"),
            run_id=run_id,
            tenant_id=TENANT,
            working_dir=root,
        )
        assert process_alive(managed.os_pid)

        settings = Settings(
            _env_file=None,
            database_url=str(engine.url).replace("asyncpg://", "asyncpg://"),
            tenant_id=TENANT,
            execution_runtime_host_id=host_id,
            execution_runtime_host_enabled=False,
            execution_workdir_root=root,
            execution_process_reconcile_interval_seconds=0.05,
            execution_workdir_cleanup_interval_seconds=0.05,
        )
        subsystem = runtime_composition._build_execution_runtime_subsystem(
            settings, engine, boot_id="boot-new", clock=lambda: 0.0
        )
        assert subsystem is not None
        assert subsystem.host.health().admission_enabled is False
        await subsystem.recover_on_startup()
        assert not process_alive(managed.os_pid)
        row = await subsystem.registry.fetch_one(managed.managed_id)
        assert row is not None
        assert row.managed.state == "exited"
        assert row.metadata.get("recovery") == "terminated"

        subsystem.start()
        await asyncio.sleep(0.1)
        await subsystem.aclose()
        assert subsystem._tasks == []

    _drive(orch_database, flow)
