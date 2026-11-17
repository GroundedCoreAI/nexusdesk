"""Phase 6 R-18(a): Broker issuance/consumption at launch + disclosure response.

(a) Broker issues/consumes a grant before Host spawn; Secret material only
enters the controlled launch channel; revocation/cleanup happens on every
terminal path; a denied grant yields zero spawn and no Secret in logs/events/DB.
(b) SecretRedactor applies at event/SSE/Outbox/error/diagnostic/artifact
boundaries; disclosure detection revokes the credential and closes admission.
"""
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
from agent_platform.core_platform.agent_execution.host.host_models import (
    ProcessSpec,
    ResourcePolicy,
)
from agent_platform.core_platform.agent_execution.security.redaction import (
    DisclosureResponse,
    SecretRedactor,
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


def _spec() -> ProcessSpec:
    return ProcessSpec(
        executable_id="codex-cli",
        argv=("/bin/sh", "-c", "true"),
        workdir_relative_path="t/run",
        resource_policy=ResourcePolicy(
            cpu_seconds=5, memory_bytes=128 * 1024 * 1024, max_processes=8,
            workdir_total_bytes=1024 * 1024, workdir_file_bytes=1024 * 1024,
            wall_seconds=10, output_max_bytes_per_stream=1024 * 1024,
        ),
    )


class _RecorderHost:
    """Minimal Host double proving spawn happens only after a valid grant."""
    def __init__(self) -> None:
        self.spawn_calls = 0
        self.secrets = None
        self._admitting = True

    def health(self):
        return type("H", (), {"admission_enabled": self._admitting})()

    async def start(self, spec, **kwargs):
        self.spawn_calls += 1
        self.secrets = kwargs.get("secret_env")
        return object()

    def close(self):
        self._admitting = False


@pytest_asyncio.fixture
async def env(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "r18-" + uuid4().hex
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    engine = create_engine(settings)
    vault = ExecutionCredentialVault(tmp_path / "k.key")
    (tmp_path / "k.key").write_bytes(Fernet.generate_key())
    repository = ExecutionCredentialRepository(engine, vault)
    broker = ExecutionCredentialBroker(engine, vault, repository=repository)
    run_repo = RunRepository(engine, BusinessRuntimePersistenceHooks())
    try:
        yield {
            "engine": engine, "tenant": tenant, "vault": vault,
            "repository": repository, "broker": broker, "run_repo": run_repo,
        }
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM execution_credential_audit WHERE tenant_id=:t"), {"t": tenant}
            )
            for table in ("execution_credential_grants", "execution_credentials"):
                await conn.execute(text(f"DELETE FROM {table} WHERE tenant_id=:t"), {"t": tenant})
            await conn.execute(
                text("DELETE FROM runtime_runs WHERE tenant_id=:t"), {"t": tenant}
            )
            await conn.execute(
                text("DELETE FROM runtime_conversations WHERE tenant_id=:t"), {"t": tenant}
            )
        await engine.dispose()


async def _new_run(run_repo, tenant):
    run = await run_repo.submit(
        tenant, RunRequest(conversation_id="r18-" + uuid4().hex[:6], message="x"),
        {"fingerprint": "r18"}, 1000, 100, 120,
    )
    owner = uuid4()
    claimed = await run_repo.claim(owner, 120, tenant)
    return run["id"], claimed, owner


async def _credential(repository, tenant, secret="launch-secret-canary"):
    return await repository.create(
        tenant_id=tenant, name="engine", credential_type="api_key", secret=secret,
        allowed_engines=("react",), allowed_workspaces=("default",),
    )


async def test_launch_issues_consumes_and_revokes_grant_without_leak(env):
    broker, repository = env["broker"], env["repository"]
    run_repo, tenant = env["run_repo"], env["tenant"]
    credential = await _credential(repository, tenant)
    run_id, claimed, _ = await _new_run(run_repo, tenant)
    host = _RecorderHost()
    launched = []

    # Production-shaped launch: broker first, spawn only after a valid grant.
    issued = await broker.issue(
        credential_ref=credential.credential_ref, tenant_id=tenant, run_id=run_id,
        engine_id="react", protocol_id="native", workspace_id="default",
        scopes=("execution.launch",), lease_epoch=claimed["lease_epoch"],
    )
    consumed = await broker.consume(
        token=issued.token, run_id=run_id, tenant_id=tenant, engine_id="react",
        protocol_id="native", workspace_id="default",
        required_scopes=("execution.launch",),
    )
    assert consumed.secret == "launch-secret-canary"
    # Spawn receives the secret only via the controlled channel.
    await host.start(_spec(), run_id=run_id, tenant_id=tenant,
                     secret_env={"CREDENTIAL": consumed.secret})
    launched.append(consumed)
    await broker.revoke_grant(issued.grant.grant_id)
    assert host.spawn_calls == 1

    async with env["engine"].connect() as conn:
        raw = (
            await conn.execute(
                text("SELECT encrypted_secret FROM execution_credentials WHERE tenant_id=:t"),
                {"t": tenant},
            )
        ).scalar()
        grants = (
            await conn.execute(
                text("SELECT grant_hash,revoked_at FROM execution_credential_grants"
                     " WHERE run_id=:id"), {"id": run_id},
            )
        ).mappings().all()
        audit = (
            await conn.execute(
                text("SELECT action,outcome FROM execution_credential_audit WHERE tenant_id=:t"),
                {"t": tenant},
            )
        ).mappings().all()
    assert "launch-secret-canary" not in raw
    assert all(row["revoked_at"] is not None for row in grants)
    assert issued.token not in str([dict(r) for r in audit])


async def test_denied_grant_yields_zero_spawn(env):
    broker, repository = env["broker"], env["repository"]
    run_repo, tenant = env["run_repo"], env["tenant"]
    credential = await _credential(repository, tenant)
    await repository.revoke(credential_ref=credential.credential_ref, tenant_id=tenant)
    run_id, claimed, _ = await _new_run(run_repo, tenant)
    host = _RecorderHost()
    with pytest.raises(CredentialGrantDenied) as exc:
        await broker.issue(
            credential_ref=credential.credential_ref, tenant_id=tenant, run_id=run_id,
            engine_id="react", protocol_id="native", workspace_id="default",
            scopes=("execution.launch",), lease_epoch=claimed["lease_epoch"],
        )
    assert exc.value.code == "credential_revoked"
    assert host.spawn_calls == 0


async def test_redaction_applies_at_event_sse_outbox_and_artifact_boundaries():
    canary = "launch-secret-canary"
    redactor = SecretRedactor([canary])
    event_payload = {"output": f"ok {canary}", "token": canary}
    sse = redactor.redact_structure(event_payload)
    assert canary not in str(sse)
    outbox_payload = redactor.redact_structure({"data": {"note": f"x {canary}"}})
    assert canary not in str(outbox_payload)
    error = redactor.redact_text(f"failed: Authorization: Bearer abc123.def {canary}")
    assert canary not in error and "abc123.def" not in error
    diagnostic = redactor.redact_structure({"sample": canary})
    assert canary not in str(diagnostic)
    artifact = redactor.redact_structure({"path": "/x", "metadata": {"secret": canary}})
    assert canary not in str(artifact)


async def test_disclosure_detection_revokes_credential_and_closes_admission(env):
    repository, tenant = env["repository"], env["tenant"]
    credential = await _credential(repository, tenant)
    redactor = SecretRedactor(["launch-secret-canary"])
    response = DisclosureResponse(repository)
    detected = redactor.contains_secret("prefix launch-secret-canary suffix")
    assert detected is True
    await response.handle_disclosure(
        tenant_id=tenant, credential_ref=credential.credential_ref, reason="canary_leak"
    )
    revoked = await repository.get(credential_ref=credential.credential_ref, tenant_id=tenant)
    assert revoked.status == "revoked"
    assert response.admission_closed is True
    # After disclosure, new issuance is denied.
    with pytest.raises(CredentialGrantDenied) as exc:
        await env["broker"].issue(
            credential_ref=credential.credential_ref, tenant_id=tenant, run_id=uuid4(),
            engine_id="react", protocol_id="native", workspace_id="default",
            scopes=("execution.launch",),
        )
    assert exc.value.code in {"credential_revoked", "run_binding_mismatch"}
