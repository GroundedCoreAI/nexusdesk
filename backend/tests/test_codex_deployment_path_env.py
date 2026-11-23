"""Issue #168: the deployment ``codex_path_env`` is the single effective PATH.

Historically ``settings.codex_path_env`` (``AGENT_CODEX_PATH_ENV``) was declared
and exported in compose but no runtime source read it: the child process PATH came
from the published per-Agent ``codex.path_env``, which the customer form exposed
as a free-text field. This pins the new precedence so a deployment change takes
effect without editing or re-publishing any Agent.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from agent_platform.core_platform.agent_execution.adapters.codex.adapter import CodexCliAdapter
from agent_platform.core_platform.agent_execution.adapters.codex.config import (
    CodexConfig,
    CodexStageGate,
)
from agent_platform.core_platform.agent_execution.adapters.codex.home_config import (
    CodexEngineHomeConfig,
)
from agent_platform.core_platform.agent_execution.contracts import ExecutionRequest
from agent_platform.core_platform.agent_execution.host.host_models import ResourcePolicy

_TENANT = "tenant-q5"
_AGENT = uuid4()
_DEPLOYMENT_PATH = "/opt/nexusdesk/codex/bin:/opt/nexusdesk/codex/node:/usr/bin:/bin"
_PUBLISHED_PATH = "/usr/local/bin:/usr/bin:/bin"

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
_HOME_CONFIG = CodexEngineHomeConfig(
    model="deepseek-flash",
    model_provider="deepseek",
    base_url="https://api.deepseek.com/v1",
    env_key="OPENAI_API_KEY",
)


class _RecordingHost:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def start(self, spec, **kwargs):
        self.calls.append({"spec": spec, **kwargs})
        return SimpleNamespace(managed_id=uuid4())


def _request() -> ExecutionRequest:
    return ExecutionRequest(
        execution_id=uuid4(),
        engine_id="codex",
        protocol_id="cli_exec",
        adapter_version="v1",
        tenant_id=_TENANT,
        agent_id=_AGENT,
        input="path precedence probe",
        workspace_id="workspace-q5",
        execution_workdir=f"aa11/{uuid4()}",
        config={
            "engine": {"engine_id": "codex", "protocol_id": "cli_exec", "adapter_version": "v1"},
            "codex": {"version": "0.169.0", "path_env": _PUBLISHED_PATH},
        },
    )


def _adapter(host: _RecordingHost, tmp_path: Path, *, deployment_path: str | None):
    return CodexCliAdapter(
        host,
        config=CodexConfig(version="0.169.0", path_env=_PUBLISHED_PATH),
        gate=_GATE,
        workdir_root=tmp_path,
        resource_policy=_POLICY,
        engine_home_config=_HOME_CONFIG,
        path_env=deployment_path,
    )


def _run(host: _RecordingHost, tmp_path: Path, *, deployment_path: str | None) -> str:
    request = _request()
    (tmp_path / request.execution_workdir).mkdir(parents=True, mode=0o700)
    adapter = _adapter(host, tmp_path, deployment_path=deployment_path)
    asyncio.run(adapter.start(request))
    assert host.calls, "the adapter must reach the Host to observe the launch environment"
    return host.calls[0]["spec"].environment["PATH"]


def test_deployment_path_wins_over_the_published_snapshot(tmp_path: Path) -> None:
    host = _RecordingHost()
    assert _run(host, tmp_path, deployment_path=_DEPLOYMENT_PATH) == _DEPLOYMENT_PATH


def test_legacy_callers_without_the_setting_keep_the_published_path(tmp_path: Path) -> None:
    host = _RecordingHost()
    assert _run(host, tmp_path, deployment_path=None) == _PUBLISHED_PATH
