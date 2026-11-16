"""Phase 6 T-07: Execution Vault/Broker, grants, redaction, admin routes."""

import os
from pathlib import Path
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
    CredentialBindingMismatch,
    ExecutionCredentialKeyError,
    ExecutionCredentialVault,
)
from agent_platform.core_platform.agent_execution.security.redaction import SecretRedactor
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import RunRequest
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


def _key_file(tmp_path: Path, *, create: bool = True) -> Path:
    path = tmp_path / "execution.key"
    if create:
        path.write_bytes(Fernet.generate_key())
    return path


async def test_missing_runtime_key_fails_closed_without_auto_creation(tmp_path):
    path = _key_file(tmp_path, create=False)
    vault = ExecutionCredentialVault(path)
    with pytest.raises(ExecutionCredentialKeyError):
        vault.encrypt("secret", credential_id=uuid4(), tenant_id="t", version=1)
    assert not path.exists()


async def test_ciphertext_is_bound_to_credential_tenant_and_version(tmp_path):
    vault = ExecutionCredentialVault(_key_file(tmp_path))
    credential_id, tenant, version = uuid4(), "tenant-a", 1
    ciphertext, key_version = vault.encrypt(
        "top-secret", credential_id=credential_id, tenant_id=tenant, version=version
    )
    assert "top-secret" not in ciphertext
    assert key_version.startswith("k")
    assert (
        vault.decrypt(ciphertext, credential_id=credential_id, tenant_id=tenant, version=version)
        == "top-secret"
    )
    for kwargs in (
        {"credential_id": uuid4(), "tenant_id": tenant, "version": version},
        {"credential_id": credential_id, "tenant_id": "tenant-b", "version": version},
        {"credential_id": credential_id, "tenant_id": tenant, "version": 2},
    ):
        with pytest.raises(CredentialBindingMismatch):
            vault.decrypt(ciphertext, **kwargs)


async def test_common_redaction_covers_registered_values_patterns_and_structure():
    redactor = SecretRedactor(["canary-value"])
    text_value = (
        "token canary-value Authorization: Bearer abc123.def api_key=sk-abcdefghijklmnop1234"
    )
    redacted = redactor.redact_text(text_value)
    assert "canary-value" not in redacted
    assert "abc123.def" not in redacted
    assert "sk-abcdefghijklmnop1234" not in redacted
    assert "[REDACTED]" in redacted
    structured = redactor.redact_structure(
        {"password": "p", "nested": {"token": "t", "note": "canary-value"}, "ok": 1}
    )
    assert structured["password"] == "[REDACTED]"
    assert structured["nested"]["token"] == "[REDACTED]"
    assert "canary-value" not in structured["nested"]["note"]
    assert structured["ok"] == 1
    assert len(redactor.redact_text("x" * 10_000, max_chars=64)) == 64


@pytest_asyncio.fixture
async def credential_env(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    tenant = "cred-" + uuid4().hex
    settings = Settings(database_url=url, tenant_id=tenant, embedded_worker=False)
    engine = create_engine(settings)
    vault = ExecutionCredentialVault(_key_file(tmp_path))
    repository = ExecutionCredentialRepository(engine, vault)
    broker = ExecutionCredentialBroker(engine, vault, repository=repository, grant_ttl_seconds=300)
    run_repo = RunRepository(engine, BusinessRuntimePersistenceHooks())
    try:
        yield {
            "engine": engine,
            "tenant": tenant,
            "vault": vault,
            "repository": repository,
            "broker": broker,
            "run_repo": run_repo,
        }
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM execution_credential_audit WHERE tenant_id=:t"), {"t": tenant}
            )
            await conn.execute(text("DELETE FROM runtime_runs WHERE tenant_id=:t"), {"t": tenant})
            await conn.execute(
                text("DELETE FROM runtime_conversations WHERE tenant_id=:t"), {"t": tenant}
            )
            for table in ("execution_credential_grants", "execution_credentials"):
                await conn.execute(text(f"DELETE FROM {table} WHERE tenant_id=:t"), {"t": tenant})
        await engine.dispose()


async def _new_run(run_repo, tenant):
    run = await run_repo.submit(
        tenant,
        RunRequest(conversation_id="cred-" + uuid4().hex[:8], message="credential"),
        {"fingerprint": "cred"},
        1000,
        100,
        120,
    )
    owner = uuid4()
    claimed = await run_repo.claim(owner, 120, tenant)
    return run["id"], claimed, owner


async def test_credential_create_rotate_revoke_is_versioned(credential_env):
    repository = credential_env["repository"]
    tenant = credential_env["tenant"]
    created = await repository.create(
        tenant_id=tenant,
        name="engine",
        credential_type="api_key",
        secret="secret-v1",
        allowed_engines=("react", "codex"),
        allowed_workspaces=("default",),
    )
    assert created.version == 1 and created.status == "active"
    public = created.public_metadata()
    assert "encrypted_secret" not in public and "secret-v1" not in repr(public)
    assert await repository.get(credential_ref=created.credential_ref, tenant_id=tenant) == created
    assert await repository.get(credential_ref=created.credential_ref, tenant_id="other") is None

    rotated = await repository.rotate(
        credential_ref=created.credential_ref, tenant_id=tenant, secret="secret-v2"
    )
    assert rotated.version == 2 and rotated.status == "active"
    old = await repository.get(credential_ref=created.credential_ref, tenant_id=tenant, version=1)
    assert old.status == "superseded"

    revoked = await repository.revoke(credential_ref=created.credential_ref, tenant_id=tenant)
    assert revoked is not None
    assert revoked.status == "revoked"
    assert [item.status for item in await repository.list(tenant_id=tenant)] == [
        "revoked",
        "revoked",
    ]


async def test_grants_bind_run_engine_workspace_scope_and_ttl(credential_env):
    repository = credential_env["repository"]
    broker = credential_env["broker"]
    run_repo = credential_env["run_repo"]
    tenant = credential_env["tenant"]
    credential = await repository.create(
        tenant_id=tenant,
        name="engine",
        credential_type="api_key",
        secret="secret-grant",
        allowed_engines=("react",),
        allowed_workspaces=("default",),
    )
    run_id, claimed, _owner = await _new_run(run_repo, tenant)
    issued = await broker.issue(
        credential_ref=credential.credential_ref,
        tenant_id=tenant,
        run_id=run_id,
        engine_id="react",
        protocol_id="native",
        workspace_id="default",
        scopes=("execution.read",),
        lease_epoch=claimed["lease_epoch"],
    )
    assert issued.token not in repr(issued.grant)
    assert issued.grant.credential_version == 1
    consumed = await broker.consume(
        token=issued.token,
        run_id=run_id,
        tenant_id=tenant,
        engine_id="react",
        protocol_id="native",
        workspace_id="default",
        required_scopes=("execution.read",),
    )
    assert consumed.secret == "secret-grant"
    assert consumed.credential_version == 1

    # One-time/replayed use, cross-Run, scope expansion, wrong tenant/engine.
    with pytest.raises(CredentialGrantDenied) as replay:
        await broker.consume(
            token=issued.token,
            run_id=run_id,
            tenant_id=tenant,
            engine_id="react",
            protocol_id="native",
            workspace_id="default",
            required_scopes=("execution.read",),
        )
    assert replay.value.code == "grant_replayed"
    other_run, _c, _o = await _new_run(run_repo, tenant)
    with pytest.raises(CredentialGrantDenied) as cross:
        await broker.consume(
            token=issued.token,
            run_id=other_run,
            tenant_id=tenant,
            engine_id="react",
            protocol_id="native",
            workspace_id="default",
            required_scopes=("execution.read",),
        )
    assert cross.value.code == "grant_binding_mismatch"


async def test_grant_denials_cover_expiry_revocation_scope_and_tenant(credential_env):
    repository = credential_env["repository"]
    broker = credential_env["broker"]
    run_repo = credential_env["run_repo"]
    engine = credential_env["engine"]
    tenant = credential_env["tenant"]
    credential = await repository.create(
        tenant_id=tenant,
        name="engine",
        credential_type="token",
        secret="s",
        allowed_engines=("react",),
        allowed_workspaces=("default",),
    )
    run_id, claimed, _ = await _new_run(run_repo, tenant)
    issued = await broker.issue(
        credential_ref=credential.credential_ref,
        tenant_id=tenant,
        run_id=run_id,
        engine_id="react",
        protocol_id="native",
        workspace_id="default",
        scopes=("execution.read",),
        lease_epoch=claimed["lease_epoch"],
    )
    with pytest.raises(CredentialGrantDenied) as scope:
        await broker.consume(
            token=issued.token,
            run_id=run_id,
            tenant_id=tenant,
            engine_id="react",
            protocol_id="native",
            workspace_id="default",
            required_scopes=("execution.write",),
        )
    assert scope.value.code == "grant_scope_denied"

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE execution_credential_grants"
                " SET issued_at=now()-interval '10 minutes',"
                " expires_at=now()-interval '1 second'"
                " WHERE tenant_id=:tenant"
            ),
            {"tenant": tenant},
        )
    with pytest.raises(CredentialGrantDenied) as expired:
        await broker.consume(
            token=issued.token,
            run_id=run_id,
            tenant_id=tenant,
            engine_id="react",
            protocol_id="native",
            workspace_id="default",
            required_scopes=(),
        )
    assert expired.value.code == "grant_expired"

    await repository.revoke(credential_ref=credential.credential_ref, tenant_id=tenant)
    issued2 = None
    with pytest.raises(CredentialGrantDenied) as revoked_issue:
        await broker.issue(
            credential_ref=credential.credential_ref,
            tenant_id=tenant,
            run_id=run_id,
            engine_id="react",
            protocol_id="native",
            workspace_id="default",
            scopes=("execution.read",),
            lease_epoch=claimed["lease_epoch"],
        )
    assert revoked_issue.value.code == "credential_revoked"
    assert issued2 is None


async def test_audit_rows_are_secret_free(credential_env):
    repository = credential_env["repository"]
    broker = credential_env["broker"]
    run_repo = credential_env["run_repo"]
    engine = credential_env["engine"]
    tenant = credential_env["tenant"]
    credential = await repository.create(
        tenant_id=tenant,
        name="engine",
        credential_type="api_key",
        secret="DO-NOT-STORE",
        allowed_engines=("react",),
        allowed_workspaces=("default",),
    )
    run_id, claimed, _ = await _new_run(run_repo, tenant)
    await broker.issue(
        credential_ref=credential.credential_ref,
        tenant_id=tenant,
        run_id=run_id,
        engine_id="react",
        protocol_id="native",
        workspace_id="default",
        scopes=("execution.read",),
        lease_epoch=claimed["lease_epoch"],
    )
    with pytest.raises(CredentialGrantDenied):
        await broker.consume(
            token="not-a-real-token",
            run_id=run_id,
            tenant_id=tenant,
            engine_id="react",
            protocol_id="native",
            workspace_id="default",
            required_scopes=(),
        )
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    text(
                        "SELECT action,outcome,reason_code FROM execution_credential_audit"
                        " WHERE tenant_id=:t ORDER BY created_at"
                    ),
                    {"t": tenant},
                )
            )
            .mappings()
            .all()
        )
        raw = (
            await conn.execute(
                text("SELECT encrypted_secret FROM execution_credentials WHERE tenant_id=:t"),
                {"t": tenant},
            )
        ).scalar()
    assert any(row["action"] == "grant_denied" and row["outcome"] == "denied" for row in rows)
    assert "DO-NOT-STORE" not in str([dict(row) for row in rows])
    assert raw and "DO-NOT-STORE" not in raw


async def test_credential_admin_routes_are_tenant_role_and_secret_safe(credential_env, tmp_path):
    url = os.environ["TEST_DATABASE_URL"]
    tenant = credential_env["tenant"]
    settings = Settings(
        database_url=url,
        tenant_id=tenant,
        embedded_worker=False,
        api_token=__import__("pydantic").SecretStr("admin-token"),
        viewer_api_token=__import__("pydantic").SecretStr("viewer-token"),
    )
    import httpx

    from agent_platform.applications.customer_service.main import create_app

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        app.state.runtime.execution_credentials = credential_env["repository"]
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            client.headers["Authorization"] = "Bearer admin-token"
            created = await client.post(
                "/api/v1/execution-credentials",
                json={
                    "name": "engine",
                    "credential_type": "api_key",
                    "secret": "route-secret",
                    "allowed_engines": ["react"],
                    "allowed_workspaces": ["default"],
                },
            )
            assert created.status_code == 201
            body = created.json()
            assert "route-secret" not in created.text
            assert "encrypted_secret" not in body
            ref = body["credential_ref"]
            assert (await client.get(f"/api/v1/execution-credentials/{ref}")).status_code == 200
            assert len((await client.get("/api/v1/execution-credentials")).json()["items"]) == 1
            rotated = await client.post(
                f"/api/v1/execution-credentials/{ref}/rotate", json={"secret": "route-secret-2"}
            )
            assert rotated.status_code == 200 and rotated.json()["version"] == 2
            assert "route-secret-2" not in rotated.text
            revoked = await client.post(f"/api/v1/execution-credentials/{ref}/revoke")
            assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
            client.headers["Authorization"] = "Bearer viewer-token"
            assert (await client.get("/api/v1/execution-credentials")).status_code == 403
