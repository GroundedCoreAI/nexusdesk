"""Phase 4 RuntimeHost contract tests: AC-1 reuse, gates, drain, pin tests.

Pins for 08 T10: admission honoring ``execution_runtime_host_enabled``,
target rejection before any side effect (P4-UT-02), the no-PID handle rule
(P4-UT-21 / 08 R-4b serialization pins), close() drain semantics, and the
AC-1 proof: two different engine triples drive one unchanged Host through
the shared contract, with zero direct spawn/signal code in the adapters
(AST-checked). PG-backed cases run on the dedicated pgvector container.
"""

import ast
import asyncio
import json
import os
import uuid
from pathlib import Path

import asyncpg
import pytest
from agent_execution.process_test_adapters import (
    KeyValueProcessAdapter,
    LineJsonProcessAdapter,
    build_trusted_registry,
    make_request,
    make_spec,
)
from test_ticket_migrations import migrate

from agent_platform.core_platform.agent_execution.host import (
    process_identity,
)
from agent_platform.core_platform.agent_execution.host import (
    runtime_host as host_module,
)
from agent_platform.core_platform.agent_execution.host.host_models import (
    REASON_ADMISSION_CLOSED,
    REASON_UNTRUSTED_TARGET,
)
from agent_platform.core_platform.agent_execution.host.process_registry import ProcessRegistry
from agent_platform.core_platform.agent_execution.host.process_runner import ProcessRunner
from agent_platform.core_platform.agent_execution.host.process_supervisor import ProcessSupervisor
from agent_platform.core_platform.agent_execution.host.runtime_host import (
    HostAdmissionError,
    HostStartError,
    RuntimeHost,
)

TENANT = "phase4-rhost"


def _host(engine, *, enabled=True, host_id="worker-host", boot="boot-1", grace=0.3, kill=0.3):
    return RuntimeHost(
        enabled=enabled,
        host_id=host_id,
        runner=ProcessRunner(build_trusted_registry()),
        supervisor=ProcessSupervisor(cancel_grace_seconds=grace, kill_timeout_seconds=kill),
        registry=ProcessRegistry(engine, host_id=host_id, host_instance_id=boot),
        wall_timeout_seconds=60,
    )


# ---------------------------------------------------------------------------
# PG fixture (module-scoped, same pattern as workdir/registry files)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def host_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a PostgreSQL role with CREATEDB")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    name = "phase4_rhost_" + uuid.uuid4().hex

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


async def _make_run(engine, tenant: str, run_id: uuid.UUID | None = None):
    from agent_platform.applications.platform_runtime.runtime_hooks import (
        BusinessRuntimePersistenceHooks,
    )
    from agent_platform.core_platform.agent_runtime.repository import RunRepository
    from agent_platform.core_platform.agent_runtime.schemas import RunRequest

    repo = RunRepository(engine, BusinessRuntimePersistenceHooks())
    row = await repo.submit(
        tenant,
        RunRequest(conversation_id=f"conv-{uuid.uuid4()}", message="runtime host test"),
        {"fingerprint": "phase4-rhost"},
        100,
        100,
        120,
    )
    return uuid.UUID(str(row["id"]))


# ---------------------------------------------------------------------------
# Admission gate (no DB needed: the gate precedes every side effect)
# ---------------------------------------------------------------------------


def test_disabled_host_admits_nothing_and_touches_no_record():
    host = _host(engine=None, enabled=False)
    with pytest.raises(HostAdmissionError) as excinfo:
        asyncio.run(
            host.start(
                make_spec("exit", "0"),
                run_id=uuid.uuid4(),
                tenant_id=TENANT,
                working_dir=Path("/tmp"),
            )
        )
    assert excinfo.value.code == REASON_ADMISSION_CLOSED


def test_enabled_host_requires_stable_host_id():
    with pytest.raises(ValueError):
        _host(engine=None, enabled=True, host_id="  ")


def test_untrusted_target_rejected_before_record_and_spawn():
    host = _host(engine=None)
    bad = make_spec("exit", "0").model_copy(update={"argv": ("/bin/sh", "-c", "true")})
    with pytest.raises(HostStartError) as excinfo:
        asyncio.run(
            host.start(
                bad,
                run_id=uuid.uuid4(),
                tenant_id=TENANT,
                working_dir=Path("/tmp"),  # never used: rejection precedes it
            )
        )
    assert excinfo.value.code == REASON_UNTRUSTED_TARGET


def test_unknown_managed_id_operations_are_refused():
    from agent_platform.core_platform.agent_execution.host.process_supervisor import (
        SupervisorStateError,
    )

    host = _host(engine=None)
    with pytest.raises(SupervisorStateError):
        asyncio.run(host.wait(uuid.uuid4()))
    with pytest.raises(SupervisorStateError):
        asyncio.run(host.cancel(uuid.uuid4()))


# ---------------------------------------------------------------------------
# AC-1: two engine triples, one unchanged Host (PG-backed)
# ---------------------------------------------------------------------------


@pytest.mark.postgres
def test_two_adapters_share_one_host_with_zero_engine_branching(host_database, tmp_path):
    root = tmp_path / "exec-root"
    root.mkdir()

    async def flow(engine):
        host = _host(engine, host_id="worker-ac1")

        # Production registries accept both triples; that is the entire
        # Host-side "support" for a new engine: none.
        from agent_platform.core_platform.agent_execution.registry import (
            AdapterDescriptor,
            AdapterRegistry,
            EngineDescriptor,
            EngineRegistry,
            ProtocolDescriptor,
            ProtocolRegistry,
        )

        engines = EngineRegistry()
        engines.register(EngineDescriptor(engine_id="proc-json"))
        engines.register(EngineDescriptor(engine_id="proc-kv"))
        protocols = ProtocolRegistry()
        protocols.register(ProtocolDescriptor(protocol_id="line-json"))
        protocols.register(ProtocolDescriptor(protocol_id="key-value"))
        adapters = AdapterRegistry(engines, protocols)
        adapters.register(
            AdapterDescriptor(engine_id="proc-json", protocol_id="line-json", adapter_version="v1"),
            lambda: LineJsonProcessAdapter(host, root=root),
        )
        adapters.register(
            AdapterDescriptor(engine_id="proc-kv", protocol_id="key-value", adapter_version="v1"),
            lambda: KeyValueProcessAdapter(host, root=root),
        )

        outcomes = []
        for adapter_cls, engine_id, protocol_id, case in (
            (LineJsonProcessAdapter, "proc-json", "line-json", "json-events"),
            (KeyValueProcessAdapter, "proc-kv", "key-value", "kv-events"),
        ):
            run_id = await _make_run(engine, TENANT)
            adapter = adapter_cls(host, root=root)
            request = make_request(engine_id, protocol_id, case=case).model_copy(
                update={"execution_id": run_id}
            )
            handle = await adapter.start(request)
            assert handle.process_id is None  # R-4b pin
            events = [event async for event in adapter.stream_events(handle)]
            result = await adapter.collect_result(handle)
            assert result.status == "completed"
            assert result.output == "hello"
            assert [event.event_type for event in events][:2] == [
                "engine.message.delta",
                "engine.run.completed",
            ]
            assert events[0].sequence == 1
            outcomes.append((engine_id, protocol_id))

        assert outcomes == [("proc-json", "line-json"), ("proc-kv", "key-value")]

        # AC-1 core claim: the Host carries no engine literals at all.
        source = Path(host_module.__file__).read_text()
        for literal in ("proc-json", "proc-kv", "line-json", "key-value", "react"):
            assert f'"{literal}"' not in source and f"'{literal}'" not in source
        assert "engine_id" not in source  # the Host never reads an engine identity

        await host.close()

    _drive(host_database, flow)


@pytest.mark.postgres
def test_public_serialization_never_leaks_os_identity(host_database, tmp_path):
    root = tmp_path / "exec-root"
    root.mkdir()

    async def flow(engine):
        host = _host(engine, host_id="worker-pin")
        run_id = await _make_run(engine, TENANT)
        adapter = LineJsonProcessAdapter(host, root=root)
        request = make_request("proc-json", "line-json", case="json-events").model_copy(
            update={"execution_id": run_id}
        )
        handle = await adapter.start(request)
        result = await adapter.collect_result(handle)

        # Serializing every public-surface DTO: no nonzero process id, no
        # start token, no absolute host path, no env value.
        dumps = {
            "handle": handle.model_dump_json(),
            "request": request.model_dump_json(),
            "result": result.model_dump_json(),
        }
        events = [event async for event in adapter.stream_events(handle)]
        dumps["events"] = json.dumps([json.loads(e.model_dump_json()) for e in events], default=str)
        managed_row = await host.registry.fetch_one(uuid.UUID(str(handle.provider_session_id)))
        assert managed_row is not None
        secretish = [
            str(managed_row.managed.os_pid),
            str(managed_row.managed.process_group_id),
        ]
        if managed_row.managed.start_token:
            secretish.append(managed_row.managed.start_token)
        for name, payload in dumps.items():
            parsed = json.loads(payload) if name != "events" else payload
            text = json.dumps(parsed, default=str)
            for token in secretish:
                assert token not in text, name
            assert "start_token" not in text
            assert "pgid" not in text
            assert str(root) not in text

        # The handle DTO itself keeps process_id unset.
        assert handle.process_id is None

        await host.close()

    _drive(host_database, flow)


@pytest.mark.postgres
def test_close_stops_admission_drains_and_leaves_zero_active(host_database, tmp_path):
    root = tmp_path / "exec-root"
    root.mkdir()

    async def flow(engine):
        host = _host(engine, host_id="worker-close")
        run_id = await _make_run(engine, TENANT)
        spec = make_spec("sleep", "30")
        working = root / "aa11" / "bb22"
        working.mkdir(parents=True)
        managed = await host.start(spec, run_id=run_id, tenant_id=TENANT, working_dir=working)
        health = host.health()
        assert health.running_count == 1
        assert health.admission_enabled

        remaining = await host.close()
        assert remaining == 0
        assert not process_identity.process_alive(managed.os_pid)

        # Post-close admission is closed; the record is honestly cancelled.
        with pytest.raises(HostAdmissionError):
            await host.start(spec, run_id=run_id, tenant_id=TENANT, working_dir=working)
        row = await host.registry.fetch_one(managed.managed_id)
        assert row is not None
        assert row.managed.state == "exited"
        assert row.metadata.get("recovery") in (None, "terminated")

        after = host.health()
        assert after.admission_enabled is False
        assert after.active_count == 0

    _drive(host_database, flow)


@pytest.mark.postgres
def test_wait_persists_honest_exit_status(host_database, tmp_path):
    root = tmp_path / "exec-root"
    root.mkdir()

    async def flow(engine):
        host = _host(engine, host_id="worker-wait")
        run_id = await _make_run(engine, TENANT)
        spec = make_spec("exit", "3")
        working = root / "aa11" / "bb22"
        working.mkdir(parents=True)
        managed = await host.start(spec, run_id=run_id, tenant_id=TENANT, working_dir=working)
        result = await host.wait(managed.managed_id)
        assert result.final_state == "exited"
        assert result.exit_code == 3
        row = await host.registry.fetch_one(managed.managed_id)
        assert row is not None
        assert row.managed.state == "exited"
        counts = await host.registry.count_by_state()
        assert counts.get("exited", 0) >= 1

    _drive(host_database, flow)


def test_adapters_contain_no_direct_spawn_or_signal_code():
    # AC-1 failure row: adapters must not duplicate signals/spawn. Parse the
    # helper's AST - no subprocess/signal imports and no os.kill*/spawn calls.
    adapter_path = Path(__file__).resolve().parent / "agent_execution" / "process_test_adapters.py"
    tree = ast.parse(adapter_path.read_text())
    banned_modules = {"subprocess", "signal"}
    imported: set[str] = set()
    killed_attrs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Attribute) and node.attr.startswith("kill"):
            killed_attrs.add(node.attr)
    assert not imported & banned_modules
    assert killed_attrs == set()
    source = adapter_path.read_text()
    for fragment in ("os.kill", "killpg", "create_subprocess", "Popen"):
        assert fragment not in source


@pytest.mark.postgres
def test_disabled_host_still_recovers_existing_records(host_database, tmp_path):
    # 03 §5.1 last bullet: execution_runtime_host_enabled=false gates new
    # admission only - recovery/cleanup keeps working so the drain-to-zero
    # precondition of rollback can always be met.
    root = tmp_path / "exec-root"
    root.mkdir()

    async def flow(engine):
        run_id = await _make_run(engine, TENANT)
        spec = make_spec("sleep", "30")
        working = root / "aa11" / "bb22"
        working.mkdir(parents=True)
        old = _host(engine, enabled=True, host_id="worker-disabled-recovery", boot="boot-old")
        managed = await old.start(spec, run_id=run_id, tenant_id=TENANT, working_dir=working)

        disabled = _host(engine, enabled=False, host_id="worker-disabled-recovery", boot="boot-new")
        summary = await disabled.reconcile()
        assert summary.terminated == 1
        assert not process_identity.process_alive(managed.os_pid)

        with pytest.raises(HostAdmissionError):
            await disabled.start(spec, run_id=run_id, tenant_id=TENANT, working_dir=working)

    _drive(host_database, flow)
