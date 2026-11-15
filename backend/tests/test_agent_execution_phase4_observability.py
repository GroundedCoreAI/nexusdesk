"""Phase 4 observability and secret-hygiene tests (08 T15, 02 FR-9).

Pins the structured alert surface: record-model hygiene (scalar facts and
vocabulary codes only), the AlertSink seam threaded through the Supervisor,
Registry, RuntimeHost and the workspace sweeper, host counters aggregated
into ``HostHealth`` (start failures, exit reasons, recovery batches), the
stalled-reconcile alert in the composition loops, and the completed P4-UT-21
full-surface secret scan (logs, alerts, DB metadata) over a real-process run
(P4-IT-25, AC-11). The low-cardinality audit and the no-leak assertions are
the core-rule half of 08 §6 (secrets/OS ids never on observable surfaces).
"""

import asyncio
import logging
import os
import re
import uuid
from pathlib import Path

import pytest
from agent_execution.process_test_adapters import (
    TRUSTED_TARGET_PATH,
    build_trusted_registry,
    make_spec,
)

from agent_platform.core_platform.agent_execution.host import runtime_host as host_module
from agent_platform.core_platform.agent_execution.host.host_models import (
    HOST_REASON_CODES,
    HostHealth,
    ManagedProcess,
    ProcessSpec,
    ResourcePolicy,
    compute_command_digest,
)
from agent_platform.core_platform.agent_execution.host.observability import (
    EVENT_CLEANUP_FAILED,
    EVENT_MANUAL_REMEDIATION,
    EVENT_PROCESS_EXITED,
    EVENT_RECONCILE_STALLED,
    EVENT_RECOVERY_BATCH,
    EVENT_START_FAILED,
    EVENT_START_REFUSED,
    EVENT_SWEEP_BATCH,
    EVENT_WORKDIR_CLEANUP_FAILED,
    EVENT_WORKDIR_OVER_QUOTA,
    OBSERVABILITY_EVENTS,
    LoggingAlertSink,
    ObservabilityRecord,
    RecordingAlertSink,
)
from agent_platform.core_platform.agent_execution.host.process_registry import ProcessRegistry
from agent_platform.core_platform.agent_execution.host.process_runner import ProcessRunner
from agent_platform.core_platform.agent_execution.host.process_supervisor import ProcessSupervisor
from agent_platform.core_platform.agent_execution.host.runtime_host import (
    HostStartError,
    RuntimeHost,
)
from agent_platform.core_platform.agent_execution.workspace.workspace_manager import (
    ExecutionWorkspaceManager,
    WorkspaceStateError,
)

TENANT = "phase4-observability"


_POLICY = ResourcePolicy(
    cpu_seconds=60,
    memory_bytes=67_108_864,
    max_processes=16,
    workdir_total_bytes=67_108_864,
    workdir_file_bytes=16_777_216,
    wall_seconds=60,
    output_max_bytes_per_stream=65_536,
)


def _managed(**overrides) -> ManagedProcess:
    values = {
        "managed_id": uuid.uuid4(),
        "run_id": uuid.uuid4(),
        "host_id": "worker-observability",
        "host_instance_id": "boot-1",
        "sandbox_provider": "local/v1",
        "command_digest": compute_command_digest("trusted-test-target", ("x",)),
        "os_pid": 4_000_001,
        "process_group_id": 4_000_001,
        "state": "running",
        "started_at_posix": 0.0,
    }
    values.update(overrides)
    return ManagedProcess(**values)


# ---------------------------------------------------------------------------
# Record-model hygiene (P4-UT-21/22 vocabulary and cardinality guards)
# ---------------------------------------------------------------------------


def test_record_accepts_only_vocabulary_codes_and_scalar_facts():
    run_id = uuid.uuid4()
    record = ObservabilityRecord(
        event="host.start.failed",
        severity="error",
        code="runtime_host_spawn_failed",
        host_id="worker-a",
        run_id=run_id,
        fields={"exit_code": -9, "note": "slug-ok", "ratio": 1.5},
    )
    assert record.run_id == run_id
    assert set(record.model_fields_set) <= {
        "event",
        "severity",
        "code",
        "host_id",
        "run_id",
        "managed_id",
        "workdir_id",
        "fields",
    }


@pytest.mark.parametrize(
    "code",
    [
        "/Users/someone/secret",
        "SELECT * FROM users",
        "TOKEN=abc123",
        "RuntimeError: boom",
        "uppercase_code",
    ],
)
def test_record_rejects_free_text_codes(code: str):
    with pytest.raises(ValueError):
        ObservabilityRecord(event="host.start.failed", severity="error", code=code)


@pytest.mark.parametrize("value", [["a"], {"k": "v"}, b"bytes", object()])
def test_record_rejects_non_scalar_fact_values(value):
    with pytest.raises(ValueError):
        ObservabilityRecord(event="host.start.failed", severity="error", fields={"x": value})


def test_record_rejects_oversized_fact_strings():
    with pytest.raises(ValueError):
        ObservabilityRecord(event="host.start.failed", severity="error", fields={"x": "y" * 129})


def test_record_rejects_extra_fields_and_free_event_shapes():
    with pytest.raises(ValueError):
        ObservabilityRecord(event="host.start.failed", severity="error", argv=["secret"])
    with pytest.raises(ValueError):
        ObservabilityRecord(event="host start failed", severity="error")
    with pytest.raises(ValueError):
        ObservabilityRecord(event="Host.StartFailed", severity="error")


def test_observability_vocabulary_is_frozen_and_low_cardinality():
    # The event registry is a closed code constant set; the label space can
    # therefore never grow with runs, tenants or paths (P4-UT-22).
    assert OBSERVABILITY_EVENTS == frozenset(
        {
            "host.start.refused",
            "host.start.failed",
            "host.process.exited",
            "host.cleanup.failed",
            "host.recovery.manual_remediation",
            "host.recovery.batch",
            "host.reconcile.deferred",
            "host.reconcile.stalled",
            "host.resource.pressure",
            "workspace.workdir.over_quota",
            "workspace.workdir.cleanup_failed",
            "workspace.sweep.batch",
        }
    )


def test_observability_surface_stays_internal():
    # The host DTO pin (P4-UT-21) extends to observability: nothing from the
    # alert surface may reach the public contracts export surface.
    import agent_platform.core_platform.agent_execution.contracts as public
    from agent_platform.core_platform.agent_execution.host import observability

    leaked = [
        name
        for name in dir(public)
        if getattr(getattr(public, name), "__module__", "") == observability.__name__
    ]
    assert leaked == []


def test_logging_alert_sink_emits_structured_correlated_lines(caplog):
    sink = LoggingAlertSink()
    run_id = uuid.uuid4()
    with caplog.at_level(logging.DEBUG):
        sink.emit(
            ObservabilityRecord(
                event="host.process.exited",
                severity="info",
                code="runtime_host_cancelled",
                host_id="worker-a",
                run_id=run_id,
                fields={"final_state": "exited"},
            )
        )
        sink.emit(
            ObservabilityRecord(
                event="host.cleanup.failed", severity="error", managed_id=uuid.uuid4()
            )
        )
    lines = [r.getMessage() for r in caplog.records]
    assert any("event=host.process.exited" in line and f"run_id={run_id}" in line for line in lines)
    assert any(
        r.levelno == logging.ERROR and "event=host.cleanup.failed" in r.getMessage()
        for r in caplog.records
    )


# ---------------------------------------------------------------------------
# RuntimeHost counters and alerts (fake engine, real spawn)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rowcount=1) -> None:
        self.rowcount = rowcount


class _FakeConn:
    def __init__(self, recorder) -> None:
        self.recorder = recorder

    async def execute(self, statement, params=None):
        self.recorder.append((" ".join(str(statement).split()), params))
        return _FakeResult()


class _FakeBegin:
    def __init__(self, conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        return False


class _FakeEngine:
    def __init__(self) -> None:
        self.calls = []

    def begin(self):
        return _FakeBegin(_FakeConn(self.calls))


def _observability_host(tmp_path: Path, sink: RecordingAlertSink, **overrides):
    engine = _FakeEngine()
    registry = ProcessRegistry(
        engine, host_id="worker-observability", host_instance_id="boot-1", alert_sink=sink
    )
    supervisor = ProcessSupervisor(
        cancel_grace_seconds=0.05, kill_timeout_seconds=0.05, alert_sink=sink
    )
    params = {
        "enabled": True,
        "host_id": "worker-observability",
        "runner": ProcessRunner(build_trusted_registry()),
        "supervisor": supervisor,
        "registry": registry,
        "wall_timeout_seconds": 30,
        "alert_sink": sink,
    }
    params.update(overrides)
    return RuntimeHost(**params), engine


def test_normal_exit_records_reason_count_and_alert(tmp_path):
    sink = RecordingAlertSink()
    host, _engine = _observability_host(tmp_path, sink)
    run_id = uuid.uuid4()
    workdir = tmp_path / "wd"
    workdir.mkdir()

    async def flow():
        managed = await host.start(
            make_spec("exit", "0", workdir_relative="wd"),
            run_id=run_id,
            tenant_id=TENANT,
            working_dir=workdir,
        )
        return await host.wait(managed.managed_id)

    result = asyncio.run(flow())
    assert result.reason_code == "runtime_host_exited"
    exit_records = [r for r in sink.records if r.event == EVENT_PROCESS_EXITED]
    assert len(exit_records) == 1
    assert [r.severity for r in exit_records] == ["info"]
    assert exit_records[0].run_id == run_id
    assert exit_records[0].host_id == "worker-observability"
    health = host.health()
    assert health.exit_reason_counts == {"runtime_host_exited": 1}
    assert health.start_failure_count == 0


def test_cancel_records_cancelled_reason(tmp_path):
    sink = RecordingAlertSink()
    host, _engine = _observability_host(tmp_path, sink)
    run_id = uuid.uuid4()
    workdir = tmp_path / "wd"
    workdir.mkdir()

    async def flow():
        managed = await host.start(
            make_spec("sleep", "30", workdir_relative="wd"),
            run_id=run_id,
            tenant_id=TENANT,
            working_dir=workdir,
        )
        return await host.cancel(managed.managed_id)

    result = asyncio.run(flow())
    assert result.reason_code == "runtime_host_cancelled"
    assert host.health().exit_reason_counts == {"runtime_host_cancelled": 1}


def test_untrusted_target_counts_and_alerts_before_any_side_effect(tmp_path):
    sink = RecordingAlertSink()
    host, engine = _observability_host(tmp_path, sink)
    run_id = uuid.uuid4()
    spec = ProcessSpec(
        executable_id="not-in-the-allowlist",
        argv=("/bin/false",),
        environment={"PATH": "/usr/bin"},
        workdir_relative_path="aa11/bb22",
        resource_policy=_POLICY,
    )
    with pytest.raises(HostStartError):

        async def flow():
            return await host.start(spec, run_id=run_id, tenant_id=TENANT, working_dir=tmp_path)

        asyncio.run(flow())
    refused = [r for r in sink.records if r.event == EVENT_START_REFUSED]
    assert refused[0].code == "runtime_host_untrusted_target"
    assert refused[0].run_id == run_id
    assert host.health().start_failure_count == 1
    assert engine.calls == []  # zero durable writes for a refused start


def test_spawn_failure_counts_and_alerts(tmp_path, monkeypatch):
    sink = RecordingAlertSink()
    host, _engine = _observability_host(tmp_path, sink)
    workdir = tmp_path / "wd"
    workdir.mkdir()

    async def exploding_exec(*args, **kwargs):
        raise OSError(2, "no such file or directory")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", exploding_exec)
    run_id = uuid.uuid4()
    with pytest.raises(HostStartError):

        async def flow():
            return await host.start(
                make_spec("exit", "0", workdir_relative="wd"),
                run_id=run_id,
                tenant_id=TENANT,
                working_dir=workdir,
            )

        asyncio.run(flow())
    failed = [r for r in sink.records if r.event == EVENT_START_FAILED]
    assert failed[0].code == "runtime_host_spawn_failed"
    assert host.health().start_failure_count == 1


class _StubRegistry:
    """Reconcile-only registry stub: foreign-boot rows and state writes."""

    def __init__(self, rows, *, boot="boot-2") -> None:
        self._rows = rows
        self.host_instance_id = boot
        self.host_id = "worker-observability"
        self.marks = []

    async def fetch_pending(self, *, batch_size=16):
        return list(self._rows)

    async def mark_state(self, **kwargs):
        self.marks.append(kwargs)
        return True


def _foreign_row(**overrides) -> tuple:
    from agent_platform.core_platform.agent_execution.host.process_registry import (
        ProcessRecordRow,
    )

    managed = _managed(**overrides)
    return ProcessRecordRow(
        managed=managed,
        host_instance_id="boot-old",
        sandbox_provider_label="local/v1",
        workdir_id=None,
        metadata={},
    )


def test_reconcile_manual_remediation_alerts_and_counts(monkeypatch):
    sink = RecordingAlertSink()
    row = _foreign_row(start_token="token-stored")
    registry = _StubRegistry([row])
    monkeypatch.setattr(host_module, "group_alive", lambda pgid: True)
    host = RuntimeHost(
        enabled=False,
        host_id="worker-observability",
        runner=ProcessRunner(build_trusted_registry()),
        supervisor=ProcessSupervisor(cancel_grace_seconds=0.05, kill_timeout_seconds=0.05),
        registry=registry,
        wall_timeout_seconds=30,
        alert_sink=sink,
        identity_probe=lambda pid: asyncio.sleep(0, "token-probed"),
    )
    summary = asyncio.run(host.reconcile())
    assert summary.manual_remediation == 1
    health = host.health()
    assert health.recovery_manual_remediation_count == 1
    assert health.recovery_terminated_count == 0
    manual = [r for r in sink.records if r.event == EVENT_MANUAL_REMEDIATION]
    assert manual[0].code == "runtime_host_identity_mismatch"
    assert manual[0].run_id == row.managed.run_id
    batch = [r for r in sink.records if r.event == EVENT_RECOVERY_BATCH]
    assert batch[0].fields["manual_remediation"] == 1
    # Fail-closed: the mismatch row was marked, zero signals were sent.
    assert registry.marks[0]["to_status"] == "cleanup_failed"


def test_reconcile_identity_match_counts_terminated(monkeypatch, signal_recorder):
    sink = RecordingAlertSink()
    row = _foreign_row(start_token="same-token")
    registry = _StubRegistry([row])
    monkeypatch.setattr(host_module, "group_alive", lambda pgid: True)
    import agent_platform.core_platform.agent_execution.host.process_supervisor as sup_module

    monkeypatch.setattr(sup_module, "group_alive", lambda pgid: False)
    host = RuntimeHost(
        enabled=False,
        host_id="worker-observability",
        runner=ProcessRunner(build_trusted_registry()),
        supervisor=ProcessSupervisor(cancel_grace_seconds=0.05, kill_timeout_seconds=0.05),
        registry=registry,
        wall_timeout_seconds=30,
        alert_sink=sink,
        identity_probe=lambda pid: asyncio.sleep(0, "same-token"),
    )
    summary = asyncio.run(host.reconcile())
    assert summary.terminated == 1
    assert signal_recorder == [(4_000_001, 15)]  # TERM through the group machine
    assert host.health().recovery_terminated_count == 1
    batch = [r for r in sink.records if r.event == EVENT_RECOVERY_BATCH]
    assert batch[0].fields["terminated"] == 1


@pytest.fixture
def signal_recorder(monkeypatch):
    sent: list[tuple[int, int]] = []

    def fake_killpg(pgid, sig):
        sent.append((pgid, sig))

    monkeypatch.setattr(os, "killpg", fake_killpg)
    return sent


def test_reconcile_deferral_alerts_on_registry_outage():
    class _DeadRegistry(_StubRegistry):
        async def fetch_pending(self, *, batch_size=16):
            from agent_platform.core_platform.agent_execution.host.process_registry import (
                RegistryUnavailableError,
            )

            raise RegistryUnavailableError("db down")

    sink = RecordingAlertSink()
    host = RuntimeHost(
        enabled=True,
        host_id="worker-observability",
        runner=ProcessRunner(build_trusted_registry()),
        supervisor=ProcessSupervisor(cancel_grace_seconds=0.05, kill_timeout_seconds=0.05),
        registry=_DeadRegistry([]),
        wall_timeout_seconds=30,
        alert_sink=sink,
    )
    summary = asyncio.run(host.reconcile())
    assert summary.db_unavailable is True
    deferred = [r for r in sink.records if r.event == "host.reconcile.deferred"]
    assert deferred and deferred[0].severity == "warning"
    assert deferred[0].host_id == "worker-observability"


# ---------------------------------------------------------------------------
# Supervisor + Registry durable landing alerts (substitutes)
# ---------------------------------------------------------------------------


class _AliveTarget:
    def __init__(self, managed: ManagedProcess) -> None:
        self.managed = managed

    async def wait_exit(self, timeout: float):
        from agent_platform.core_platform.agent_execution.host.host_models import (
            ExitObservation,
        )

        return ExitObservation("alive", None)


def test_supervisor_cleanup_failed_alert_carries_run_correlation(monkeypatch, signal_recorder):
    import agent_platform.core_platform.agent_execution.host.process_supervisor as sup_module

    monkeypatch.setattr(sup_module, "group_alive", lambda pgid: True)
    sink = RecordingAlertSink()
    supervisor = ProcessSupervisor(
        cancel_grace_seconds=0.01, kill_timeout_seconds=0.01, alert_sink=sink
    )
    managed = _managed()
    result = asyncio.run(supervisor.cancel(_AliveTarget(managed)))
    assert result.final_state == "cleanup_failed"
    alerts = [r for r in sink.records if r.event == EVENT_CLEANUP_FAILED]
    assert len(alerts) == 1
    assert alerts[0].severity == "error"
    assert alerts[0].code == "runtime_host_cleanup_failed"
    assert alerts[0].run_id == managed.run_id
    assert alerts[0].managed_id == managed.managed_id
    assert alerts[0].host_id == managed.host_id
    # The OS group id is correlation-free on the alert surface.
    assert str(managed.process_group_id) not in alerts[0].model_dump_json()


def test_registry_durable_cleanup_failed_landing_alerts_once():
    sink = RecordingAlertSink()
    engine = _FakeEngine()
    registry = ProcessRegistry(
        engine,
        host_id="worker-a",
        host_instance_id="boot-1",
        alert_sink=sink,
    )
    managed = _managed()
    run_id = managed.run_id
    landed = asyncio.run(
        registry.mark_state(
            managed_id=managed.managed_id,
            from_states=("running",),
            to_status="cleanup_failed",
            last_error_code="runtime_host_identity_mismatch",
            run_id=run_id,
        )
    )
    assert landed
    alerts = [r for r in sink.records if r.event == EVENT_CLEANUP_FAILED]
    assert len(alerts) == 1
    assert alerts[0].code == "runtime_host_cleanup_failed"
    assert alerts[0].run_id == run_id
    assert alerts[0].host_id == "worker-a"
    # A lost conditional update (rowcount 0) must alert nothing.
    engine_inner = _FakeEngine()

    class _ZeroResult:
        rowcount = 0

    class _ZeroConn(_FakeConn):
        async def execute(self, statement, params=None):
            return _ZeroResult()

    engine_inner.begin = lambda: _FakeBegin(_ZeroConn(engine_inner.calls))
    registry2 = ProcessRegistry(
        engine_inner, host_id="worker-a", host_instance_id="boot-1", alert_sink=sink
    )
    asyncio.run(
        registry2.mark_state(
            managed_id=managed.managed_id,
            from_states=("running",),
            to_status="cleanup_failed",
            run_id=run_id,
        )
    )
    assert len([r for r in sink.records if r.event == EVENT_CLEANUP_FAILED]) == 1


def test_stable_code_folds_unknown_shapes_into_vocabulary():
    assert RuntimeHost._stable_code("runtime_host_wall_timeout") == "runtime_host_wall_timeout"
    assert RuntimeHost._stable_code("workdir_scope_mismatch") == "workdir_scope_mismatch"
    for junk in ("", None, 7, "ValueError: /home/u/x", "UPPER_CASE"):
        assert RuntimeHost._stable_code(junk) == "runtime_host_spawn_failed"
    # Vocabulary integrity: every host reason code survives unchanged.
    assert all(RuntimeHost._stable_code(code) == code for code in HOST_REASON_CODES)


def test_health_model_exposes_counters_with_zero_defaults():
    health = HostHealth(
        host_id="worker-a",
        host_instance_id="boot-1",
        sandbox_provider="local/v1",
        admission_enabled=True,
        resource_enforcement_required=True,
    )
    assert health.start_failure_count == 0
    assert health.exit_reason_counts == {}
    assert health.recovery_terminated_count == 0
    assert health.workdir_cleanup_failed_count == 0
    assert health.workdir_live_bytes == 0
    assert health.workdir_oldest_retention_age_seconds is None


# ---------------------------------------------------------------------------
# Composition loops: stalled reconcile and sweep batch (P4-UT-22)
# ---------------------------------------------------------------------------


def _subsystem(stub_host, stub_workspace, sink, interval=0.01):
    from agent_platform.applications.platform_runtime.runtime_composition import (
        ExecutionRuntimeSubsystem,
    )

    return ExecutionRuntimeSubsystem(
        host=stub_host,
        workspace=stub_workspace,
        registry=_StubRegistry([]),
        resources=object(),
        reconcile_interval_seconds=interval,
        cleanup_interval_seconds=interval,
        alert_sink=sink,
    )


def test_stalled_reconcile_alerts_once_per_episode():
    sink = RecordingAlertSink()

    class _AlwaysFailing:
        async def reconcile(self, *, batch_size=16):
            raise RuntimeError("db outage")

        async def close(self):
            return 0

    class _QuietWorkspace:
        async def sweep_expired(self, **kwargs):
            return []

    async def flow():
        subsystem = _subsystem(_AlwaysFailing(), _QuietWorkspace(), sink)
        subsystem.start()
        await asyncio.sleep(0.06)
        await subsystem.aclose()
        return [r for r in sink.records if r.event == EVENT_RECONCILE_STALLED]

    stalled = asyncio.run(flow())
    assert len(stalled) == 1  # one episode, not one per tick
    assert stalled[0].severity == "error"
    assert stalled[0].host_id == "worker-observability"


def test_sweep_batch_reports_candidate_count_and_survives_failures():
    sink = RecordingAlertSink()

    class _OkHost:
        async def close(self):
            return 0

    class _Candidate:
        def __init__(self):
            self.workdir_id = uuid.uuid4()
            self.run_id = uuid.uuid4()
            self.tenant_id = TENANT

    class _FailingWorkspace:
        def __init__(self):
            self.cleanup_calls = 0

        async def sweep_expired(self, **kwargs):
            return [_Candidate(), _Candidate()]

        async def cleanup(self, **kwargs):
            self.cleanup_calls += 1
            raise WorkspaceStateError("workdir_scope_mismatch")

    async def flow():
        workspace = _FailingWorkspace()
        subsystem = _subsystem(_OkHost(), workspace, sink)
        subsystem.start()
        await asyncio.sleep(0.05)
        await subsystem.aclose()
        return workspace

    workspace = asyncio.run(flow())
    assert workspace.cleanup_calls >= 2
    batches = [r for r in sink.records if r.event == EVENT_SWEEP_BATCH]
    assert batches and batches[0].fields["candidates"] == 2


# ---------------------------------------------------------------------------
# PG sections: workspace stats, alerts over the durable lanes, and the
# full-surface secret scan (P4-UT-21 completion, P4-IT-25)
# ---------------------------------------------------------------------------


def _pg_url_or_skip():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a PostgreSQL role with CREATEDB")
    return url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture(scope="module")
def observability_database():
    from urllib.parse import urlsplit, urlunsplit

    from test_ticket_migrations import migrate

    url = _pg_url_or_skip()
    parts = urlsplit(url)
    name = "phase4_observability_" + uuid.uuid4().hex

    async def admin(statement):
        import asyncpg

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


def _drive_observability(url, flow, root):
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
            await flow(engine, root)
        finally:
            await engine.dispose()

    return asyncio.run(main())


async def _make_run(engine, tenant: str) -> uuid.UUID:
    from agent_platform.applications.platform_runtime.runtime_hooks import (
        BusinessRuntimePersistenceHooks,
    )
    from agent_platform.core_platform.agent_runtime.repository import RunRepository
    from agent_platform.core_platform.agent_runtime.schemas import RunRequest

    repo = RunRepository(engine, BusinessRuntimePersistenceHooks())
    row = await repo.submit(
        tenant,
        RunRequest(conversation_id=f"conv-{uuid.uuid4()}", message="observability test"),
        {"fingerprint": "phase4-observability"},
        100,
        100,
        120,
    )
    return uuid.UUID(str(row["id"]))


def _workspace_manager(engine, root, sink, **overrides):
    params = {
        "quota_bytes": 1_073_741_824,
        "retention_seconds": 3600,
        "failed_retention_seconds": 7200,
    }
    params.update(overrides)
    return ExecutionWorkspaceManager(
        engine, root=root, clock=lambda: 1_700_000_000.0, alert_sink=sink, **params
    )


@pytest.mark.postgres
def test_workspace_stats_and_health_report_merge(observability_database, tmp_path):
    root = tmp_path / "exec-root"
    root.mkdir(mode=0o700)
    sink = RecordingAlertSink()

    async def flow(engine, root):
        workspace = _workspace_manager(engine, root, sink)
        host, _registry = _observability_host(tmp_path, sink)
        host.workspace_manager = workspace
        run_id = await _make_run(engine, TENANT)
        record = await workspace.prepare(
            run_id=run_id, tenant_id=TENANT, business_id="b", workspace_id="w"
        )
        await workspace.activate(workdir_id=record.workdir_id, run_id=run_id, tenant_id=TENANT)
        # Put a real file inside so the observation is nonzero.
        relative = Path(record.relative_path)
        (root / relative / "workdir" / "payload.txt").write_bytes(b"x" * 4096)
        await workspace.retain(
            workdir_id=record.workdir_id, run_id=run_id, tenant_id=TENANT, outcome="success"
        )

        stats = await workspace.stats()
        assert stats.retained_count == 1
        assert stats.live_bytes >= 4096
        assert stats.oldest_retention_age_seconds is not None

        report = await host.health_report()
        assert report.workdir_retained_count == 1
        assert report.workdir_live_bytes >= 4096
        assert report.workdir_cleanup_failed_count == 0
        # Sync health keeps its zero workdir defaults (documented split).
        assert host.health().workdir_live_bytes == 0

    _drive_observability(observability_database, flow, root)


@pytest.mark.postgres
def test_over_quota_and_cleanup_failed_landing_alerts_pg(observability_database, tmp_path):
    root = tmp_path / "exec-root"
    root.mkdir(mode=0o700)
    sink = RecordingAlertSink()

    async def flow(engine, root):
        workspace = _workspace_manager(engine, root, sink, quota_bytes=1)
        run_id = await _make_run(engine, TENANT)
        record = await workspace.prepare(
            run_id=run_id, tenant_id=TENANT, business_id="b", workspace_id="w"
        )
        await workspace.activate(workdir_id=record.workdir_id, run_id=run_id, tenant_id=TENANT)
        relative = Path(record.relative_path)
        (root / relative / "workdir" / "payload.txt").write_bytes(b"x" * 512)
        await workspace.retain(
            workdir_id=record.workdir_id, run_id=run_id, tenant_id=TENANT, outcome="failed"
        )
        over = [r for r in sink.records if r.event == EVENT_WORKDIR_OVER_QUOTA]
        assert over[0].code == "runtime_host_resource_exceeded"
        assert over[0].run_id == run_id
        assert over[0].fields["observed_bytes"] >= 512

        # Tamper the durable path so cleanup must refuse and land failed.
        import asyncpg

        conn = await asyncpg.connect(
            engine.url.render_as_string(hide_password=False).replace(
                "postgresql+asyncpg://", "postgresql://"
            )
        )
        try:
            await conn.execute(
                "UPDATE execution_workdirs SET relative_path='99zz/deadbeef' WHERE run_id=$1",
                str(run_id),
            )
        finally:
            await conn.close()
        with pytest.raises(WorkspaceStateError):
            await workspace.cleanup(workdir_id=record.workdir_id, run_id=run_id, tenant_id=TENANT)
        failed = [r for r in sink.records if r.event == EVENT_WORKDIR_CLEANUP_FAILED]
        assert failed[0].code == "workdir_scope_mismatch"
        assert failed[0].run_id == run_id
        assert str(root) not in failed[0].model_dump_json()

    _drive_observability(observability_database, flow, root)


def _iter_strings(value):
    """Recursively yield every string inside dumps/mappings for leak scans."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_strings(str(key))
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_strings(item)
    elif isinstance(value, bytes):
        yield value.decode("utf-8", "ignore")


@pytest.mark.postgres
def test_full_surface_secret_scan_real_run(observability_database, tmp_path, caplog):
    # P4-UT-21 completion / P4-IT-25 secret half: drive a real trusted
    # process through the whole stack with distinctive sentinels and assert
    # none of them appears in logs, alerts, or durable metadata.
    root = tmp_path / "exec-root"
    root.mkdir(mode=0o700)
    sink = RecordingAlertSink()
    env_sentinel = f"ENV-SENTINEL-{uuid.uuid4().hex}"
    token_sentinel = f"tok-{uuid.uuid4().hex}"

    async def flow(engine, root):
        workspace = _workspace_manager(engine, root, sink, host_id="worker-scan")
        registry = ProcessRegistry(
            engine, host_id="worker-scan", host_instance_id="boot-scan", alert_sink=sink
        )
        host = RuntimeHost(
            enabled=True,
            host_id="worker-scan",
            runner=ProcessRunner(build_trusted_registry()),
            supervisor=ProcessSupervisor(
                cancel_grace_seconds=0.05, kill_timeout_seconds=0.05, alert_sink=sink
            ),
            registry=registry,
            wall_timeout_seconds=30,
            workspace_manager=workspace,
            alert_sink=sink,
        )
        run_id = await _make_run(engine, TENANT)
        workdir_record = await workspace.prepare(
            run_id=run_id, tenant_id=TENANT, business_id="b", workspace_id="w"
        )
        await workspace.activate(
            workdir_id=workdir_record.workdir_id, run_id=run_id, tenant_id=TENANT
        )
        workdir = root / Path(workdir_record.relative_path) / "workdir"
        spec = ProcessSpec(
            executable_id="trusted-test-target",
            argv=(TRUSTED_TARGET_PATH, "env-silent"),
            environment={
                "PATH": "/usr/bin:/bin",
                "SECRET_DEMO_KEY": env_sentinel,
                "SESSION_TOKEN": token_sentinel,
            },
            workdir_relative_path=workdir_record.relative_path,
            resource_policy=_POLICY,
        )
        managed = await host.start(
            spec,
            run_id=run_id,
            tenant_id=TENANT,
            working_dir=workdir,
            workdir_id=workdir_record.workdir_id,
        )
        result = await host.wait(managed.managed_id)
        assert result.final_state == "exited"
        await workspace.retain(
            workdir_id=workdir_record.workdir_id,
            run_id=run_id,
            tenant_id=TENANT,
            outcome="success",
        )
        counts = await registry.count_by_state()
        assert counts.get("exited", 0) == 1
        return engine

    with caplog.at_level(logging.DEBUG, logger="agent_platform"):
        _drive_observability(observability_database, flow, root)

    # Surface 1: every log record (message + args formatting).
    log_text = "\n".join(r.getMessage() for r in caplog.records)
    # Surface 2: every emitted alert.
    alert_text = "\n".join(r.model_dump_json() for r in sink.records)
    # Surface 3: durable metadata columns and code columns.
    import asyncpg

    async def fetch_metadata():
        conn = await asyncpg.connect(
            observability_database.replace(
                "postgresql://",
                "postgresql://",
            )
        )
        try:
            process_rows = await conn.fetch(
                "SELECT metadata::text AS m, last_error_code, command_digest,"
                " process_start_token FROM runtime_host_processes"
            )
            workdir_rows = await conn.fetch(
                "SELECT relative_path, last_error_code FROM execution_workdirs"
            )
        finally:
            await conn.close()
        return process_rows, workdir_rows

    process_rows, workdir_rows = asyncio.run(fetch_metadata())
    db_text = "\n".join(
        [row["m"] for row in process_rows]
        + [row["last_error_code"] or "" for row in process_rows]
        + [row["relative_path"] for row in workdir_rows]
        + [row["last_error_code"] or "" for row in workdir_rows]
    )

    sentinels = {
        "environment value": env_sentinel,
        "token": token_sentinel,
        "argv absolute target path": TRUSTED_TARGET_PATH,
        "execution root absolute path": str(root),
    }
    for label, needle in sentinels.items():
        for surface_name, surface in (("logs", log_text), ("alerts", alert_text), ("db", db_text)):
            assert needle not in surface, f"{label} leaked into {surface_name}"

    # The durable rows exist and carry only digests/tokens-by-hash, argv
    # never in plain: the command_digest must be the sha256 form.
    assert all(re.fullmatch(r"sha256:[0-9a-f]{64}", row["command_digest"]) for row in process_rows)
    # Alert label audit (P4-UT-22): only registered events and field keys.
    allowed_field_keys = {
        "final_state",
        "exit_code",
        "term_signal",
        "trigger",
        "state",
        "executable_id",
        "terminated",
        "manual_remediation",
        "absent",
        "current_boot_skipped",
        "candidates",
        "observed_bytes",
        "quota_bytes",
        "survivors",
        "last_error_code",
        "stale_seconds",
        "interval_seconds",
        "dimension",
        "mechanism",
        "strength",
    }
    for record in sink.records:
        assert record.event in OBSERVABILITY_EVENTS
        assert set(record.fields) <= allowed_field_keys
        assert (
            record.code is None
            or record.code in HOST_REASON_CODES
            or record.code.startswith("workdir_")
        )
    # Zero surviving trusted processes after the run (08 T16 hygiene).
    survivors = [
        line
        for line in os.popen("ps -axo pid,command").read().splitlines()
        if "trusted_targets.py" in line
    ]
    assert survivors == []
