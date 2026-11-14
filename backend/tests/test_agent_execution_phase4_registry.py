"""Phase 4 registry tests: decision table, locking, durable recovery (08 T9).

The orphan decision is a pure substitute-testable function (P4-UT-07/08/09);
the postgres cases run against the dedicated pgvector container
(P4-IT-08/11 plus the substitute half of P4-IT-10, whose deterministic real
OS PID-reuse corroboration stays pending_env per 08 R-3).
"""

import asyncio
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import asyncpg
import pytest
from test_ticket_migrations import migrate

from agent_platform.core_platform.agent_execution.host import process_identity
from agent_platform.core_platform.agent_execution.host.host_models import (
    compute_command_digest,
)
from agent_platform.core_platform.agent_execution.host.process_registry import (
    ProcessRegistry,
    RegistryUnavailableError,
    orphan_decision,
)

TENANT = "phase4-registry"

# ---------------------------------------------------------------------------
# P4-UT-08: identity decision table (pure, substitutes)
# ---------------------------------------------------------------------------


def test_decision_table_match_terminates():
    decision = orphan_decision(
        stored_token="linux:42:abcd", probed_token="linux:42:abcd", alive=True
    )
    assert decision.decision == "terminate"
    assert decision.reason_code is None


def test_decision_table_pid_reuse_gets_zero_signals():
    decision = orphan_decision(
        stored_token="linux:42:abcd", probed_token="linux:99:ffff", alive=True
    )
    assert decision.decision == "no_signal"
    assert decision.reason_code == "runtime_host_identity_mismatch"


def test_decision_table_unavailable_identity_is_mismatch():
    for probed in (None, ""):
        decision = orphan_decision(stored_token="linux:42:abcd", probed_token=probed, alive=True)
        assert decision.decision == "no_signal"
    decision = orphan_decision(stored_token=None, probed_token="linux:1:aa", alive=True)
    assert decision.decision == "no_signal"


def test_decision_table_gone_group_is_absent():
    decision = orphan_decision(stored_token="linux:42:abcd", probed_token=None, alive=False)
    assert decision.decision == "absent"


# ---------------------------------------------------------------------------
# P4-UT-07/09: host scoping with a fake engine
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


def test_every_write_reasserts_host_id():
    engine = _FakeEngine()
    registry = ProcessRegistry(engine, host_id="worker-a", host_instance_id="boot-1")
    managed_id = uuid.uuid4()
    managed = _managed_for(registry, managed_id)
    asyncio.run(
        registry.register_starting(
            managed_id=managed_id,
            run_id=uuid.uuid4(),
            tenant_id=TENANT,
            command_digest=managed.command_digest,
        )
    )
    asyncio.run(registry.attach_spawn(managed=managed))
    asyncio.run(
        registry.mark_state(
            managed_id=managed_id, from_states=("running",), to_status="terminating"
        )
    )
    asyncio.run(registry.observe(managed_id))
    for statement, params in engine.calls:
        assert params["host_id"] == "worker-a"
    # attach_spawn requires the 'starting' guard, never a blind update.
    attach = engine.calls[1][0]
    assert "AND status='starting'" in attach


def _managed_for(registry, managed_id):
    from agent_platform.core_platform.agent_execution.host.host_models import ManagedProcess

    return ManagedProcess(
        managed_id=managed_id,
        run_id=uuid.uuid4(),
        host_id=registry.host_id,
        host_instance_id=registry.host_instance_id,
        sandbox_provider="local/v1",
        state="running",
        os_pid=4_000_002,
        process_group_id=4_000_002,
        start_token="linux:1:2",
        command_digest=compute_command_digest("trusted-test-target", ("exit", "0")),
    )


def test_registry_wraps_dbapi_errors_as_unavailable():
    from sqlalchemy.exc import DBAPIError

    class _RaisingConn:
        async def execute(self, *args, **kwargs):
            raise DBAPIError("stmt", {}, Exception("connection reset"))

    class _RaisingBegin:
        async def __aenter__(self):
            return _RaisingConn()

        async def __aexit__(self, *args):
            return False

    class _RaisingEngine:
        def begin(self):
            return _RaisingBegin()

    broken = ProcessRegistry(_RaisingEngine(), host_id="worker-a", host_instance_id="boot-1")
    with pytest.raises(RegistryUnavailableError):
        asyncio.run(
            broken.register_starting(
                managed_id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                tenant_id=TENANT,
                command_digest="sha256:" + "0" * 64,
            )
        )


# ---------------------------------------------------------------------------
# Postgres integration (P4-IT-08/10-substitute/11)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def registry_database():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a PostgreSQL role with CREATEDB")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    name = "phase4_registry_" + uuid.uuid4().hex

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


async def _make_run(engine, tenant: str):
    from agent_platform.applications.platform_runtime.runtime_hooks import (
        BusinessRuntimePersistenceHooks,
    )
    from agent_platform.core_platform.agent_runtime.repository import RunRepository
    from agent_platform.core_platform.agent_runtime.schemas import RunRequest

    repo = RunRepository(engine, BusinessRuntimePersistenceHooks())
    row = await repo.submit(
        tenant,
        RunRequest(conversation_id=f"conv-{uuid.uuid4()}", message="registry test"),
        {"fingerprint": "phase4-registry"},
        100,
        100,
        120,
    )
    return uuid.UUID(str(row["id"]))


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
            await flow(engine, url)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def _registry(engine, host_id="worker-a", boot="boot-1"):
    return ProcessRegistry(engine, host_id=host_id, host_instance_id=boot)


@pytest.mark.postgres
def test_registry_persists_records_and_scans_by_host(registry_database):
    async def flow(engine, url):
        run_id = await _make_run(engine, TENANT)
        registry = _registry(engine)
        managed_id = uuid.uuid4()
        digest = compute_command_digest("trusted-test-target", ("exit", "0"))
        await registry.register_starting(
            managed_id=managed_id,
            run_id=run_id,
            tenant_id=TENANT,
            command_digest=digest,
        )
        managed = _managed_for(registry, managed_id)
        assert await registry.attach_spawn(managed=managed)
        # A second attach must fail: the starting guard was consumed.
        assert not await registry.attach_spawn(managed=managed)

        row = await registry.fetch_one(managed_id)
        assert row is not None
        assert row.managed.state == "running"
        assert row.managed.os_pid == 4_000_002
        assert row.managed.start_token == "linux:1:2"

        # host scoping: another host_id cannot see or move the row.
        other = _registry(engine, host_id="worker-b")
        assert await other.fetch_one(managed_id) is None
        assert not await other.mark_state(
            managed_id=managed_id, from_states=("running",), to_status="terminating"
        )

        # illegal from-state guard and honest transitions.
        assert not await registry.mark_state(
            managed_id=managed_id, from_states=("starting",), to_status="terminating"
        )
        assert await registry.mark_state(
            managed_id=managed_id, from_states=("running",), to_status="terminating"
        )
        assert await registry.mark_state(
            managed_id=managed_id,
            from_states=("terminating",),
            to_status="exited",
            exit_code=-15,
            metadata_merge={"reason": "cancelled"},
        )
        done = await registry.fetch_one(managed_id)
        assert done is not None and done.managed.state == "exited"
        assert done.metadata.get("reason") == "cancelled"

        # pending scan never returns terminal rows.
        pending = await registry.fetch_pending(statuses=("running", "terminating"))
        assert managed_id not in {row.managed_id for row in pending}

    _drive(registry_database, flow)


@pytest.mark.postgres
def test_pending_batches_are_bounded_and_skip_locked(registry_database):
    async def flow(engine, url):
        host = "worker-batch"
        run_ids = [await _make_run(engine, TENANT) for _ in range(4)]
        registry = _registry(engine, host_id=host, boot="boot-1")
        for index, run_id in enumerate(run_ids):
            await registry.register_starting(
                managed_id=uuid.uuid4(),
                run_id=run_id,
                tenant_id=TENANT,
                command_digest=compute_command_digest("trusted-test-target", (f"p{index}",)),
            )

        # Bounded batch: a scan with batch_size=2 pulls exactly two.
        batch = await registry.fetch_pending(batch_size=2)
        assert len(batch) == 2

        # Deterministic SKIP LOCKED proof: an open transaction locks the
        # host's rows; a concurrent registry scan must skip every one of
        # them (no double processing) rather than block or repeat.
        conn = await asyncpg.connect(url)
        try:
            await conn.execute("BEGIN")
            locked = await conn.fetch(
                "SELECT id FROM runtime_host_processes WHERE host_id=$1"
                " ORDER BY last_observed_at LIMIT 8 FOR UPDATE SKIP LOCKED",
                host,
            )
            assert len(locked) == 4
            during = await registry.fetch_pending(batch_size=8)
            assert during == []  # all rows are held elsewhere: zero overlap
        finally:
            await conn.execute("COMMIT")
            await conn.close()

        after = await registry.fetch_pending(batch_size=8)
        assert len(after) == 4

    _drive(registry_database, flow)


@pytest.mark.postgres
def test_db_outage_raises_unavailable_without_any_scan(registry_database):
    # P4-IT-11: a dead port surfaces as RegistryUnavailableError; the Host
    # (covered in the runtime-host file) turns it into a retry decision. No
    # process is enumerated or signalled anywhere in this path - pin: the
    # registry module has no psutil/subprocess/process-walking imports at all.
    import agent_platform.core_platform.agent_execution.host.process_registry as module

    source = Path(module.__file__).read_text()
    assert "psutil" not in source
    assert "subprocess" not in source

    async def flow(engine, url):
        from agent_platform.core_platform.platform_services.persistence.database import (
            create_engine,
        )
        from agent_platform.core_platform.platform_services.platform_settings.settings import (
            Settings,
        )

        dead_settings = Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://agent:invalid@127.0.0.1:59999/none",
            tenant_id=TENANT,
            embedded_worker=False,
        )
        dead = create_engine(dead_settings)
        try:
            registry = ProcessRegistry(dead, host_id="worker-x", host_instance_id="boot-1")
            with pytest.raises(RegistryUnavailableError):
                await registry.fetch_pending()
            with pytest.raises(RegistryUnavailableError):
                await registry.register_starting(
                    managed_id=uuid.uuid4(),
                    run_id=uuid.uuid4(),
                    tenant_id=TENANT,
                    command_digest="sha256:" + "0" * 64,
                )
        finally:
            await dead.dispose()

    _drive(registry_database, flow)


@pytest.mark.postgres
def test_restart_recovery_terminates_identity_matched_orphan(registry_database, tmp_path):
    # P4-IT-08 (local half): a process spawned by a previous boot instance
    # of the same host_id is recovered on the next boot: match -> orphaned ->
    # TERM/KILL through the group handle -> record exited, zero mistakes.
    # The container-restart corroboration half stays pending_env (08 R-3).
    from agent_execution.process_test_adapters import build_trusted_registry, make_spec

    from agent_platform.core_platform.agent_execution.host.process_runner import ProcessRunner
    from agent_platform.core_platform.agent_execution.host.process_supervisor import (
        ProcessSupervisor,
    )
    from agent_platform.core_platform.agent_execution.host.runtime_host import RuntimeHost

    working = tmp_path / "recovery"
    working.mkdir()

    async def flow(engine, url):
        run_id = await _make_run(engine, TENANT)
        host_id = "worker-recovery"

        def make_host(boot):
            return RuntimeHost(
                enabled=True,
                host_id=host_id,
                runner=ProcessRunner(build_trusted_registry()),
                supervisor=ProcessSupervisor(cancel_grace_seconds=0.5, kill_timeout_seconds=0.5),
                registry=ProcessRegistry(engine, host_id=host_id, host_instance_id=boot),
                wall_timeout_seconds=60,
            )

        old_boot = make_host("boot-old")
        spec = make_spec("sleep", "30")
        managed = await old_boot.start(spec, run_id=run_id, tenant_id=TENANT, working_dir=working)
        pid = managed.os_pid
        assert process_identity.process_alive(pid)

        new_boot = make_host("boot-new")
        summary = await new_boot.reconcile()
        assert summary.terminated == 1
        assert summary.manual_remediation == 0
        deadline = time.monotonic() + 5
        while process_identity.process_alive(pid) and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert not process_identity.process_alive(pid)

        row = await new_boot.registry.fetch_one(managed.managed_id)
        assert row is not None
        assert row.managed.state == "exited"
        assert row.metadata.get("recovery") == "terminated"

        # Re-running recovery is a no-op: terminal rows leave the scan, and
        # current-boot live records are skipped, never signalled twice.
        second = await new_boot.reconcile()
        assert second.terminated == 0 and second.manual_remediation == 0

    _drive(registry_database, flow)


@pytest.mark.postgres
def test_pid_reuse_substitute_forbids_signals(registry_database):
    # P4-IT-10 substitute half (the deterministic real OS PID-reuse
    # corroboration is pending_env): an existing pid whose identity token
    # mismatches the record receives zero signals and lands in
    # cleanup_failed with manual remediation.
    from agent_execution.process_test_adapters import build_trusted_registry

    from agent_platform.core_platform.agent_execution.host.process_runner import ProcessRunner
    from agent_platform.core_platform.agent_execution.host.process_supervisor import (
        ProcessSupervisor,
    )
    from agent_platform.core_platform.agent_execution.host.runtime_host import RuntimeHost

    host_id = "worker-pidreuse"
    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])

    async def flow(engine, url):
        run_id = await _make_run(engine, TENANT)
        if True:
            registry = ProcessRegistry(engine, host_id=host_id, host_instance_id="boot-old")
            managed_id = uuid.uuid4()
            await registry.register_starting(
                managed_id=managed_id,
                run_id=run_id,
                tenant_id=TENANT,
                command_digest=compute_command_digest("trusted-test-target", ("sleep", "30")),
            )
            from agent_platform.core_platform.agent_execution.host.host_models import (
                ManagedProcess,
            )

            hijacked = ManagedProcess(
                managed_id=managed_id,
                run_id=run_id,
                host_id=host_id,
                host_instance_id="boot-old",
                sandbox_provider="local/v1",
                state="running",
                os_pid=bystander.pid,
                process_group_id=os.getpgid(bystander.pid),
                start_token="linux:WRONG-TOKEN:0000",  # the reused-pid scenario
                command_digest=compute_command_digest("trusted-test-target", ("sleep", "30")),
                started_at_posix=time.time(),
            )
            assert await registry.attach_spawn(managed=hijacked)

            signals_sent = []
            real_killpg = os.killpg

            def spy_killpg(pgid, sig):
                if sig == 0:
                    return real_killpg(pgid, sig)  # liveness probe, not a signal
                signals_sent.append((pgid, sig))
                raise AssertionError("recovery must never signal a mismatch")

            os.killpg = spy_killpg  # type: ignore[assignment]
            try:
                host = RuntimeHost(
                    enabled=True,
                    host_id=host_id,
                    runner=ProcessRunner(build_trusted_registry()),
                    supervisor=ProcessSupervisor(
                        cancel_grace_seconds=0.2, kill_timeout_seconds=0.2
                    ),
                    registry=ProcessRegistry(engine, host_id=host_id, host_instance_id="boot-new"),
                    wall_timeout_seconds=60,
                )
                summary = await host.reconcile()
            finally:
                os.killpg = real_killpg  # type: ignore[assignment]

            assert summary.manual_remediation == 1
            assert summary.terminated == 0
            assert signals_sent == []
            assert process_identity.process_alive(bystander.pid)  # zero mistaken kills

            row = await host.registry.fetch_one(managed_id)
            assert row is not None
            assert row.managed.state == "cleanup_failed"
            # cleanup_failed rows stay alertable (retry candidate) but the
            # bystander remains untouched; a second pass re-decides, no signal.
            second = await host.reconcile()
            assert second.manual_remediation == 1
            assert signals_sent == []

    try:
        _drive(registry_database, flow)
    finally:
        bystander.terminate()
        bystander.wait(timeout=5)
