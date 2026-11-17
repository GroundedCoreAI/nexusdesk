"""Phase 6 T-12: controlled Resume-equivalent Broker reauthorization."""

import pytest
from test_execution_credentials import _new_run, credential_env  # noqa: F401

from agent_platform.core_platform.agent_execution.credentials.broker import CredentialGrantDenied

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


async def test_resume_equivalent_new_run_requires_and_receives_new_grant(credential_env):  # noqa: F811
    broker = credential_env["broker"]
    repository = credential_env["repository"]
    run_repo = credential_env["run_repo"]
    tenant = credential_env["tenant"]
    credential = await repository.create(
        tenant_id=tenant,
        name="engine",
        credential_type="api_key",
        secret="resume-canary",
        allowed_engines=("react",),
        allowed_workspaces=("default",),
    )
    old_run, old_claim, _ = await _new_run(run_repo, tenant)
    old = await broker.issue(
        credential_ref=credential.credential_ref,
        tenant_id=tenant,
        run_id=old_run,
        engine_id="react",
        protocol_id="native",
        workspace_id="default",
        scopes=("execution.launch",),
        lease_epoch=old_claim["lease_epoch"],
    )
    new_run, new_claim, _ = await _new_run(run_repo, tenant)
    with pytest.raises(CredentialGrantDenied):
        await broker.consume(
            token=old.token,
            run_id=new_run,
            tenant_id=tenant,
            engine_id="react",
            protocol_id="native",
            workspace_id="default",
            required_scopes=("execution.launch",),
        )
    new = await broker.issue(
        credential_ref=credential.credential_ref,
        tenant_id=tenant,
        run_id=new_run,
        engine_id="react",
        protocol_id="native",
        workspace_id="default",
        scopes=("execution.launch",),
        lease_epoch=new_claim["lease_epoch"],
    )
    consumed = await broker.consume(
        token=new.token,
        run_id=new_run,
        tenant_id=tenant,
        engine_id="react",
        protocol_id="native",
        workspace_id="default",
        required_scopes=("execution.launch",),
    )
    assert consumed.secret == "resume-canary"
    assert new.grant.grant_id != old.grant.grant_id
    await repository.revoke(credential_ref=credential.credential_ref, tenant_id=tenant)
    with pytest.raises(CredentialGrantDenied, match="credential_revoked"):
        await broker.issue(
            credential_ref=credential.credential_ref,
            tenant_id=tenant,
            run_id=new_run,
            engine_id="react",
            protocol_id="native",
            workspace_id="default",
            scopes=("execution.launch",),
            lease_epoch=new_claim["lease_epoch"],
        )
