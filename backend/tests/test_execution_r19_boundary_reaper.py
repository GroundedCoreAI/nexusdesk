"""Phase 6 R-19: real network boundary, live-reaper confirmation, fence ordering.

(1) allowlist uses an enforced internal-network + managed-proxy boundary, not
    advisory env vars on an open bridge.
(2) the live Worker reaper uses confirmed recovery; unconfirmed != cancelled.
(3) recovery fences/takes over the claim (new epoch) before cleanup runs under
    the new ownership.
"""
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_execution.host.docker_sandbox_provider import (
    DockerSandboxProvider,
)
from agent_platform.core_platform.agent_execution.host.egress_proxy import (
    EgressProxyEndpoint,
)
from agent_platform.core_platform.agent_execution.host.host_models import (
    ProcessSpec,
    ResourcePolicy,
)
from agent_platform.core_platform.agent_execution.host.network_policy import (
    NetworkPolicy,
    NetworkRule,
)
from agent_platform.core_platform.agent_execution.host.sandbox_provider import (
    SandboxPolicyError,
)
from agent_platform.core_platform.agent_execution.reliability.recovery import (
    RecoveryCoordinator,
)
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.agent_runtime.worker import RuntimeWorker
from agent_platform.core_platform.platform_services.persistence.database import (
    create_engine,
)
from agent_platform.core_platform.platform_services.platform_settings.settings import (
    Settings,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


def _spec():
    return ProcessSpec(
        executable_id="codex-cli", argv=("/bin/true",),
        workdir_relative_path="t/run",
        resource_policy=ResourcePolicy(
            cpu_seconds=5, memory_bytes=128 * 1024 * 1024, max_processes=8,
            workdir_total_bytes=1024 * 1024, workdir_file_bytes=1024 * 1024,
            wall_seconds=10, output_max_bytes_per_stream=1024 * 1024,
        ),
    )


# ---------------------------------------------------------------------------
# (1) Real network boundary
# ---------------------------------------------------------------------------


async def test_allowlist_uses_internal_network_and_proxy_not_open_bridge(tmp_path):
    provider = DockerSandboxProvider(
        image="alpine:latest", docker_probe=lambda: True,
        network_policy=NetworkPolicy(rules=(NetworkRule(host="api.example.com", port=443),)),
        proxy_endpoint=EgressProxyEndpoint(host="egress-proxy", port=3128),
    )
    workdir = tmp_path / "w"
    workdir.mkdir()
    reservation = await provider.prepare(_spec(), run_id=uuid4())
    plan = provider.launch_plan(reservation, _spec(), working_dir=workdir)
    argv = " ".join(plan.argv)
    # Enforced boundary: internal (no external route) network, not open bridge.
    assert "--network" in plan.argv and "bridge" not in argv
    assert "internal" in argv or "nexus-egress" in argv
    # Proxy is the only egress route; it is a managed endpoint, not advisory.
    assert any("HTTP_PROXY" in k or "http_proxy" in k for k, _ in plan.environment)
    assert "egress-proxy:3128" in " ".join(v for _, v in plan.environment)


async def test_allowlist_without_managed_proxy_endpoint_fails_closed(tmp_path):
    provider = DockerSandboxProvider(
        image="alpine:latest", docker_probe=lambda: True,
        network_policy=NetworkPolicy(rules=(NetworkRule(host="api.example.com", port=443),)),
        proxy_endpoint=None,
    )
    workdir = tmp_path / "w"
    workdir.mkdir()
    with pytest.raises(SandboxPolicyError) as exc:
        reservation = await provider.prepare(_spec(), run_id=uuid4())
        provider.launch_plan(reservation, _spec(), working_dir=workdir)
    assert exc.value.code == "runtime_host_sandbox_unavailable"


async def test_default_deny_stays_network_none_without_allowlist(tmp_path):
    provider = DockerSandboxProvider(image="alpine:latest", docker_probe=lambda: True)
    workdir = tmp_path / "w"
    workdir.mkdir()
    reservation = await provider.prepare(_spec(), run_id=uuid4())
    plan = provider.launch_plan(reservation, _spec(), working_dir=workdir)
    assert "none" in plan.argv[plan.argv.index("--network") + 1]


# ---------------------------------------------------------------------------
# (2) Live-reaper confirmation + (3) fence-before-cleanup ordering
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def repo():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "r19-" + uuid4().hex
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    engine = create_engine(settings)
    repository = RunRepository(engine, BusinessRuntimePersistenceHooks())
    try:
        yield repository, tenant, engine
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM execution_fencing_denials WHERE run_id IN "
                     "(SELECT id FROM runtime_runs WHERE tenant_id=:t)"), {"t": tenant}
            )
            await conn.execute(text("DELETE FROM runtime_runs WHERE tenant_id=:t"), {"t": tenant})
            await conn.execute(
                text("DELETE FROM runtime_conversations WHERE tenant_id=:t"), {"t": tenant}
            )
        await engine.dispose()


async def _claim(repo, tenant, owner):
    run = await repo.submit(
        tenant, RunRequest(conversation_id="r19-" + uuid4().hex[:6], message="x"),
        {"fingerprint": "r19"}, 1000, 100, 120,
    )
    claimed = await repo.claim(owner, 120, tenant)
    return run["id"], claimed


async def test_recovery_fences_epoch_before_cleanup_runs(repo):
    repository, tenant, engine = repo
    owner_a, owner_b = uuid4(), uuid4()
    run_id, _claimed = await _claim(repository, tenant, owner_a)
    await repository.cancel(run_id, tenant)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_runs SET lease_until=now()-interval '1 second' WHERE id=:id"),
            {"id": run_id},
        )
    order = []

    async def cleanup(row):
        # At cleanup time the claim must already carry the new epoch/owner.
        async with engine.connect() as conn:
            row_now = (
                (await conn.execute(
                    text("SELECT owner,lease_epoch FROM runtime_runs WHERE id=:id"),
                    {"id": row["id"]},
                )).mappings().one()
            )
        order.append(("cleanup", row_now["lease_epoch"], row_now["owner"]))
        return True

    coordinator = RecoveryCoordinator(repository, cleanup)
    await coordinator.recover_expired(tenant, new_owner=owner_b)
    assert order, "cleanup was not called"
    _, epoch_at_cleanup, owner_at_cleanup = order[0]
    assert epoch_at_cleanup >= 2  # fenced/taken over before cleanup
    assert owner_at_cleanup == owner_b
    async with engine.connect() as conn:
        status = await conn.scalar(
            text("SELECT status FROM runtime_runs WHERE id=:id"), {"id": run_id}
        )
    assert status == "cancelled"


async def test_live_worker_reaper_uses_confirmed_recovery(repo):
    repository, tenant, engine = repo
    owner = uuid4()
    run_id, _claimed = await _claim(repository, tenant, owner)
    await repository.cancel(run_id, tenant)
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE runtime_runs SET lease_until=now()-interval '1 second' WHERE id=:id"),
            {"id": run_id},
        )

    confirmed = {"value": False}

    async def cleanup(_row):
        return confirmed["value"]

    worker = RuntimeWorker(
        repository, object(), Settings(database_url="postgresql+asyncpg://x:y@h/d"),
        "fingerprint",
    )
    # The live reaper path is a first-class confirmed-recovery call.
    await worker._reap_expired(tenant, cleanup)
    async with engine.connect() as conn:
        row = (
            (await conn.execute(
                text("SELECT status,error_code FROM runtime_runs WHERE id=:id"),
                {"id": run_id},
            )).mappings().one()
        )
    assert row["status"] == "failed"
    assert row["error_code"] in {"cancellation_unconfirmed", "cleanup_failed"}
    assert row["status"] != "cancelled"
