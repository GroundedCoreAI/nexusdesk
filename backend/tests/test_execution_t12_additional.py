"""Phase 6 T-12: continuous diagnostics/disclosure and independent quota release."""

from uuid import uuid4

import pytest
from sqlalchemy import text
from test_execution_t12_matrix import _claim, repo  # noqa: F401

from agent_platform.core_platform.agent_execution.events.diagnostics import (
    ParserDiagnosticCollector,
)
from agent_platform.core_platform.agent_execution.host.local_sandbox_provider import (
    LocalSandboxProvider,
)
from agent_platform.core_platform.agent_execution.host.resource_manager import ResourceManager
from agent_platform.core_platform.agent_execution.reliability.ownership import ExecutionOwnership
from agent_platform.core_platform.agent_execution.security.redaction import SecretRedactor
from agent_platform.core_platform.agent_runtime.schemas import CapacityError, RunRequest

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


async def test_continuous_diagnostics_are_bounded_redacted_and_trigger_disclosure(repo):  # noqa: F811
    from cryptography.fernet import Fernet
    from test_execution_r18_launch_redaction import _credential

    from agent_platform.core_platform.agent_execution.credentials.repository import (
        ExecutionCredentialRepository,
    )
    from agent_platform.core_platform.agent_execution.credentials.vault import (
        ExecutionCredentialVault,
    )
    from agent_platform.core_platform.agent_execution.security.redaction import DisclosureResponse

    _repository, tenant, engine, _ = repo
    key = __import__("pathlib").Path(__import__("tempfile").mkdtemp()) / "key"
    key.write_bytes(Fernet.generate_key())
    credentials = ExecutionCredentialRepository(engine, ExecutionCredentialVault(key))
    credential = await _credential(credentials, tenant, secret="continuous-secret-canary")
    redactor = SecretRedactor(["continuous-secret-canary"])
    diagnostics = []
    collector = ParserDiagnosticCollector(
        sink=diagnostics.append,
        redact=redactor.redact_text,
        raw_samples_enabled=True,
        max_sample_bytes=64,
        max_per_minute=3,
    )
    diagnostic_run_id = uuid4()
    for _ in range(20):
        collector.report(
            "malformed",
            engine_id="codex",
            protocol_id="cli_exec",
            run_id=diagnostic_run_id,
            sample="continuous-secret-canary",
        )
    assert len(diagnostics) <= 3
    assert collector.counters()["suppressed"] >= 17
    assert all("continuous-secret-canary" not in str(item) for item in diagnostics)
    response = DisclosureResponse(credentials)
    await response.handle_disclosure(
        tenant_id=tenant, credential_ref=credential.credential_ref, reason="continuous_parse_leak"
    )
    assert response.admission_closed is True
    assert (
        await credentials.get(credential_ref=credential.credential_ref, tenant_id=tenant)
    ).status == "revoked"
    async with engine.connect() as conn:
        audit = (
            (
                await conn.execute(
                    text("SELECT reason_code FROM execution_credential_audit WHERE tenant_id=:t"),
                    {"t": tenant},
                )
            )
            .scalars()
            .all()
        )
    assert "continuous-secret-canary" not in str(audit)


async def test_run_capacity_and_host_reservation_release_independently(repo):  # noqa: F811
    repository, tenant, engine, _ = repo
    owner = uuid4()
    claimed = await _claim(repository, tenant, owner)
    run_id = claimed["id"]
    async with engine.connect() as conn:
        active = await conn.scalar(
            text("SELECT count(*) FROM runtime_runs WHERE status IN ('queued','running')")
        )
    capacity = max(1, active)
    with pytest.raises(CapacityError):
        await repository.submit(
            tenant,
            RunRequest(conversation_id="full-" + uuid4().hex[:6], message="x"),
            {"fingerprint": "t12"},
            capacity,
            capacity,
            120,
        )

    provider = LocalSandboxProvider(enforcement_required=False)
    resources = ResourceManager(provider, sample_interval_seconds=1.0)
    from test_execution_sandbox import _spec

    reservation = await provider.prepare(_spec("/bin/true"), run_id=run_id)
    await repository.finish(
        run_id,
        owner,
        "completed",
        output="done",
        history=[],
        lease_epoch=1,
        cleanup_confirmed=True,
    )
    # Run terminal admission capacity and Host reservation are separate resources.
    retried = await repository.submit(
        tenant,
        RunRequest(conversation_id="after-" + uuid4().hex[:6], message="x"),
        {"fingerprint": "t12"},
        capacity,
        capacity,
        120,
    )
    assert retried["status"] == "queued"
    ownership = ExecutionOwnership(run_id, owner, 1)

    async def authorize(_ownership, _operation):
        return True

    assert await resources.release(reservation, ownership=ownership, authorize=authorize) is True
    assert await resources.release(reservation, ownership=ownership, authorize=authorize) is True
    assert reservation.released is True
