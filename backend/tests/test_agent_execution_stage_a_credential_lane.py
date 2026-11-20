"""P6/G5 tests: Broker reference lane, closed env-key binding, secret-free audit."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_platform.core_platform.agent_execution.adapters.codex.adapter import CodexCliAdapter
from agent_platform.core_platform.agent_execution.adapters.codex.config import (
    CodexConfig,
    CodexStageGate,
)
from agent_platform.core_platform.agent_execution.adapters.codex.home_config import (
    CodexEngineHomeConfig,
)
from agent_platform.core_platform.agent_execution.contracts import (
    AdapterExecutionError,
    ExecutionErrorCode,
    ExecutionRequest,
)
from agent_platform.core_platform.agent_execution.host.host_models import (
    ProcessSpec,
    ResourcePolicy,
)
from agent_platform.core_platform.agent_execution.host.runtime_host import (
    RuntimeHost,
    _with_credential_env,
)

_TENANT = "tenant-p6"
_AGENT = uuid4()
_CANARY = "CANARY_SECRET_VALUE"
_HOME_CONFIG = CodexEngineHomeConfig(
    model="deepseek-flash",
    model_provider="deepseek",
    base_url="https://api.deepseek.com/v1",
    env_key="DEEPSEEK_API_KEY",
)
_GATE = CodexStageGate(
    cli_enabled=True,
    stage_a_verified=True,
    allowed_versions=("0.169.0",),
    trusted_tenants=(_TENANT,),
)
_POLICY = ResourcePolicy(
    cpu_seconds=60,
    memory_bytes=67_108_864,
    max_processes=16,
    workdir_total_bytes=67_108_864,
    workdir_file_bytes=16_777_216,
    wall_seconds=60,
    output_max_bytes_per_stream=65_536,
)


class _RecordingHost:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def start(self, spec, **kwargs):
        self.calls.append({"spec": spec, **kwargs})
        return SimpleNamespace(managed_id=uuid4())


def _request(workspace_id: str | None, credential_ref: str | None):
    return ExecutionRequest(
        execution_id=uuid4(),
        engine_id="codex",
        protocol_id="cli_exec",
        adapter_version="v1",
        tenant_id=_TENANT,
        agent_id=_AGENT,
        input="run with a scoped credential",
        workspace_id=workspace_id,
        execution_workdir=f"aa11/{uuid4()}",
        config={
            "engine": {"engine_id": "codex", "protocol_id": "cli_exec", "adapter_version": "v1"},
            "codex": {
                "version": "0.169.0",
                "credential_ref": credential_ref,
            },
        },
    )


def _spec(credential_env_key: str | None) -> ProcessSpec:
    return ProcessSpec(
        executable_id="codex",
        argv=("exec", "--json"),
        environment={"PATH": "/usr/bin"},
        credential_env_key=credential_env_key,
        workdir_relative_path="aa11/run",
        resource_policy=_POLICY,
    )


def test_adapter_rejects_a_non_uuid_reference(tmp_path: Path):
    host = _RecordingHost()
    adapter = CodexCliAdapter(
        host,
        config=CodexConfig(version="0.169.0", credential_ref="not-a-reference"),
        gate=_GATE,
        workdir_root=tmp_path,
        resource_policy=_POLICY,
        engine_home_config=_HOME_CONFIG,
        credential_broker=object(),
    )
    request = _request("workspace-p6", "not-a-reference")
    (tmp_path / request.execution_workdir).mkdir(parents=True, mode=0o700)

    with pytest.raises(AdapterExecutionError) as exc:
        asyncio.run(adapter.start(request))
    assert exc.value.error.code == ExecutionErrorCode.ENGINE_UNAVAILABLE
    assert host.calls == []


def test_adapter_passes_reference_and_explicit_audience(tmp_path: Path):
    host = _RecordingHost()
    ref = str(uuid4())
    adapter = CodexCliAdapter(
        host,
        config=CodexConfig(version="0.169.0", credential_ref=ref),
        gate=_GATE,
        workdir_root=tmp_path,
        resource_policy=_POLICY,
        engine_home_config=_HOME_CONFIG,
        credential_broker=object(),
    )
    request = _request("workspace-p6", ref)
    (tmp_path / request.execution_workdir).mkdir(parents=True, mode=0o700)

    asyncio.run(adapter.start(request))

    call = host.calls[0]
    assert str(call["credential_ref"]) == ref
    assert call["broker_audience"] == {
        "engine_id": "codex",
        "protocol_id": "cli_exec",
        "workspace_id": "workspace-p6",
    }
    assert call["spec"].credential_env_key == "DEEPSEEK_API_KEY"
    assert _CANARY not in repr(call["spec"])


def test_adapter_fails_closed_without_broker_or_workspace(tmp_path: Path):
    ref = str(uuid4())
    for broker, workspace in ((None, "workspace-p6"), (object(), None)):
        host = _RecordingHost()
        adapter = CodexCliAdapter(
            host,
            config=CodexConfig(version="0.169.0", credential_ref=ref),
            gate=_GATE,
            workdir_root=tmp_path,
            resource_policy=_POLICY,
            engine_home_config=_HOME_CONFIG,
            credential_broker=broker,
        )
        request = _request(workspace, ref)
        (tmp_path / request.execution_workdir).mkdir(parents=True, mode=0o700)
        with pytest.raises(AdapterExecutionError) as exc:
            asyncio.run(adapter.start(request))
        assert exc.value.error.code == ExecutionErrorCode.ENGINE_UNAVAILABLE
    assert host.calls == []


def test_secret_maps_to_declared_key_and_never_serializes():
    bound = _with_credential_env(_spec("DEEPSEEK_API_KEY"), _CANARY)
    assert bound.environment["DEEPSEEK_API_KEY"] == _CANARY
    assert "EXECUTION_CREDENTIAL" not in bound.environment
    assert bound.credential_env_key is None
    assert _CANARY not in repr(bound)
    assert _CANARY not in str(bound.model_dump())
    assert _CANARY not in bound.command_digest


def test_legacy_callers_keep_the_original_credential_slot():
    bound = _with_credential_env(_spec(None), _CANARY)
    assert bound.environment["EXECUTION_CREDENTIAL"] == _CANARY
    assert _CANARY not in repr(bound)


def test_reconcile_revokes_a_foreign_boot_grant():
    revoked: list = []

    class _Broker:
        async def revoke_grant(self, grant_id):
            revoked.append(grant_id)

    class _Registry:
        host_instance_id = "boot-current"

        async def fetch_pending(self, *, batch_size):
            return [
                SimpleNamespace(
                    managed_id=managed_id,
                    host_instance_id="boot-foreign",
                )
            ]

    host = RuntimeHost(
        enabled=True,
        host_id="runtime-p6",
        runner=object(),
        supervisor=object(),
        registry=_Registry(),
        wall_timeout_seconds=30,
        credential_broker=_Broker(),
    )
    managed_id = uuid4()
    grant_id = uuid4()
    host._grants[managed_id] = SimpleNamespace(
        grant=SimpleNamespace(grant_id=grant_id),
        token="CANARY_TOKEN",
        secret=_CANARY,
    )

    async def _decide(row):
        return "terminate"

    async def _terminate_row(row):
        return None

    host._decide = _decide
    host._terminate_row = _terminate_row
    summary = asyncio.run(host.reconcile(batch_size=1))

    assert summary.terminated == 1
    assert revoked == [grant_id]
    assert managed_id not in host._grants
