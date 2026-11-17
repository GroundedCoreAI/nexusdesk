"""Phase 6 round 2 (R2-A/R2-B): reservation release and launch-plan secret."""

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import text

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_execution.credentials.broker import (
    CredentialGrantDenied,
    ExecutionCredentialBroker,
)
from agent_platform.core_platform.agent_execution.credentials.repository import (
    ExecutionCredentialRepository,
)
from agent_platform.core_platform.agent_execution.credentials.vault import (
    ExecutionCredentialVault,
)
from agent_platform.core_platform.agent_execution.host.docker_sandbox_provider import (
    DockerSandboxProvider,
)
from agent_platform.core_platform.agent_execution.host.host_models import (
    ProcessSpec,
    ResourcePolicy,
)
from agent_platform.core_platform.agent_execution.host.local_sandbox_provider import (
    LocalSandboxProvider,
)
from agent_platform.core_platform.agent_execution.host.process_registry import ProcessRegistry
from agent_platform.core_platform.agent_execution.host.process_runner import (
    ProcessRunner,
    TrustedTargetDescriptor,
    TrustedTargetRegistry,
)
from agent_platform.core_platform.agent_execution.host.process_supervisor import (
    ProcessSupervisor,
)
from agent_platform.core_platform.agent_execution.host.resource_manager import ResourceManager
from agent_platform.core_platform.agent_execution.host.runtime_host import (
    HostStartError,
    RuntimeHost,
)
from agent_platform.core_platform.agent_execution.reliability.ownership import (
    ExecutionOwnership,
)
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.database import (
    create_engine,
)
from agent_platform.core_platform.platform_services.platform_settings.settings import (
    Settings,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


@pytest_asyncio.fixture
async def env(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "r2-" + uuid4().hex
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    engine = create_engine(settings)
    vault = ExecutionCredentialVault(tmp_path / "k.key")
    (tmp_path / "k.key").write_bytes(Fernet.generate_key())
    repository = ExecutionCredentialRepository(engine, vault)
    broker = ExecutionCredentialBroker(engine, vault, repository=repository)
    run_repo = RunRepository(engine, BusinessRuntimePersistenceHooks())
    try:
        yield {
            "engine": engine,
            "tenant": tenant,
            "vault": vault,
            "repository": repository,
            "broker": broker,
            "run_repo": run_repo,
            "tmp": tmp_path,
        }
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM execution_credential_audit WHERE tenant_id=:t"), {"t": tenant}
            )
            for table in ("execution_credential_grants", "execution_credentials"):
                await conn.execute(text(f"DELETE FROM {table} WHERE tenant_id=:t"), {"t": tenant})
            await conn.execute(text("DELETE FROM runtime_runs WHERE tenant_id=:t"), {"t": tenant})
            await conn.execute(
                text("DELETE FROM runtime_conversations WHERE tenant_id=:t"), {"t": tenant}
            )
            await conn.execute(
                text("DELETE FROM runtime_host_processes WHERE tenant_id=:t"), {"t": tenant}
            )
        await engine.dispose()


def _spec():
    return ProcessSpec(
        executable_id="codex-cli",
        argv=(),
        workdir_relative_path="t/run",
        resource_policy=ResourcePolicy(
            cpu_seconds=5,
            memory_bytes=128 * 1024 * 1024,
            max_processes=8,
            workdir_total_bytes=1024 * 1024,
            workdir_file_bytes=1024 * 1024,
            wall_seconds=10,
            output_max_bytes_per_stream=1024 * 1024,
        ),
    )


class _RecordingProvider(LocalSandboxProvider):
    """Local provider that records release calls to prove reservation cleanup."""

    def __init__(self):
        super().__init__(enforcement_required=False)
        self.released = []

    async def release(self, reservation):
        self.released.append(reservation.reservation_id)
        await super().release(reservation)


def _host(env, provider):
    resources = ResourceManager(provider, sample_interval_seconds=1.0)
    registry = ProcessRegistry(env["engine"], host_id="r2-host", host_instance_id="boot-1")
    runner = ProcessRunner(
        TrustedTargetRegistry(
            (
                TrustedTargetDescriptor(
                    executable_id="codex-cli", executable_path="/usr/bin/true", fixed_prefix=()
                ),
            )
        )
    )
    supervisor = ProcessSupervisor(cancel_grace_seconds=1.0, kill_timeout_seconds=1.0)
    return RuntimeHost(
        enabled=True,
        host_id="r2-host",
        runner=runner,
        supervisor=supervisor,
        registry=registry,
        wall_timeout_seconds=10,
        resource_manager=resources,
        credential_broker=env["broker"],
    )


async def _credential(repository, tenant, secret="launch-secret-canary"):
    return await repository.create(
        tenant_id=tenant,
        name="engine",
        credential_type="api_key",
        secret=secret,
        allowed_engines=("codex-cli",),
        allowed_workspaces=("default",),
    )


async def _claim(run_repo, tenant, owner):
    run = await run_repo.submit(
        tenant,
        RunRequest(conversation_id="r2-" + uuid4().hex[:6], message="x"),
        {"fingerprint": "r2"},
        1000,
        100,
        120,
    )
    return run["id"], await run_repo.claim(owner, 120, tenant)


async def test_revoked_grant_releases_reservation_and_zero_spawn(env):
    provider = _RecordingProvider()
    host = _host(env, provider)
    credential = await _credential(env["repository"], env["tenant"])
    await env["repository"].revoke(
        credential_ref=credential.credential_ref, tenant_id=env["tenant"]
    )
    run_id, claimed = await _claim(env["run_repo"], env["tenant"], uuid4())
    ownership = ExecutionOwnership(run_id, claimed["owner"], claimed["lease_epoch"])
    workdir = env["tmp"] / "wd"
    workdir.mkdir()
    with pytest.raises((HostStartError, CredentialGrantDenied)):
        await host.start(
            _spec(),
            run_id=run_id,
            tenant_id=env["tenant"],
            working_dir=workdir,
            ownership=ownership,
            credential_ref=credential.credential_ref,
            broker_audience={
                "engine_id": "codex-cli",
                "protocol_id": "cli_exec",
                "workspace_id": "default",
            },
        )
    # R2-A: the acquired reservation MUST be released on the Broker failure.
    assert len(provider.released) == 1, "reservation not released on broker denial"
    async with env["engine"].connect() as conn:
        procs = await conn.scalar(
            text("SELECT count(*) FROM runtime_host_processes WHERE run_id=:id"), {"id": run_id}
        )
    assert procs == 0  # zero spawn/record


async def test_docker_plan_carries_consumed_secret_in_child_env(env):
    provider = DockerSandboxProvider(image="alpine:latest", docker_probe=lambda: True)
    host = _host(env, provider)
    credential = await _credential(env["repository"], env["tenant"])
    run_id, claimed = await _claim(env["run_repo"], env["tenant"], uuid4())
    ownership = ExecutionOwnership(run_id, claimed["owner"], claimed["lease_epoch"])
    workdir = env["tmp"] / "wd"
    workdir.mkdir()

    captured = {}

    async def capture_start(spec, **kwargs):
        # Capture the launch plan BEFORE spawn; assert the plan carries the
        # consumed Secret in its controlled child environment.
        plan = kwargs.get("launch_plan")
        captured["plan"] = plan
        captured["spec_env"] = spec.environment
        raise HostStartError("probe_stop_before_spawn")

    host._runner.start = capture_start
    with pytest.raises(HostStartError):
        await host.start(
            _spec(),
            run_id=run_id,
            tenant_id=env["tenant"],
            working_dir=workdir,
            ownership=ownership,
            credential_ref=credential.credential_ref,
            broker_audience={
                "engine_id": "codex-cli",
                "protocol_id": "cli_exec",
                "workspace_id": "default",
            },
        )
    plan = captured["plan"]
    assert plan is not None, "launch plan was not rebuilt after consumption"
    plan_env = dict(plan.environment)
    assert "EXECUTION_CREDENTIAL" in plan_env
    assert plan_env["EXECUTION_CREDENTIAL"] == "launch-secret-canary"
    # The Secret is only in the controlled channel, not in argv/logs.
    assert "launch-secret-canary" not in " ".join(plan.argv)
    await host.close()
