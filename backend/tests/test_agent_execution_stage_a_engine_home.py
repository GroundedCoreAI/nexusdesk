"""P5/G6 tests: key-free CODEX_HOME config, closed env-key allowlist, narrow mounts."""

import asyncio
import os
import stat
from pathlib import Path
from uuid import uuid4

import pytest

from agent_platform.core_platform.agent_execution.adapters.codex.adapter import CodexCliAdapter
from agent_platform.core_platform.agent_execution.adapters.codex.config import (
    CodexConfig,
    CodexStageGate,
)
from agent_platform.core_platform.agent_execution.adapters.codex.home_config import (
    CodexEngineHomeConfig,
    write_private_engine_config,
)
from agent_platform.core_platform.agent_execution.contracts import ExecutionRequest
from agent_platform.core_platform.agent_execution.host.host_models import ResourcePolicy
from agent_platform.core_platform.agent_execution.workspace.execution_workdir import (
    PRIVATE_ENGINE_HOME_NAME,
    WorkdirOperationError,
)

_TENANT = "tenant-p5"
_AGENT = uuid4()
_POLICY = ResourcePolicy(
    cpu_seconds=60,
    memory_bytes=67_108_864,
    max_processes=16,
    workdir_total_bytes=67_108_864,
    workdir_file_bytes=16_777_216,
    wall_seconds=60,
    output_max_bytes_per_stream=65_536,
)
_GATE = CodexStageGate(
    cli_enabled=True,
    stage_a_verified=True,
    allowed_versions=("0.169.0",),
    trusted_tenants=(_TENANT,),
)
_HOME_CONFIG = CodexEngineHomeConfig(
    model="deepseek-flash",
    model_provider="deepseek",
    base_url="https://api.deepseek.com/v1",
    env_key="OPENAI_API_KEY",
)


class _RecordingHost:
    def __init__(self) -> None:
        self.specs: list = []

    async def start(self, spec, *, run_id, tenant_id, working_dir, **_):
        self.specs.append(spec)
        return type("Managed", (), {"managed_id": uuid4()})()


def test_rendered_config_is_key_free_and_uses_responses():
    rendered = _HOME_CONFIG.to_toml()
    assert 'model = "deepseek-flash"' in rendered
    assert 'base_url = "https://api.deepseek.com/v1"' in rendered
    assert 'env_key = "OPENAI_API_KEY"' in rendered
    assert 'wire_api = "responses"' in rendered
    assert "CANARY_VALUE" not in rendered


def test_chat_wire_api_is_rejected_before_a_run_starts():
    """Codex 0.169+ aborts at config parse when ``wire_api = "chat"``."""

    with pytest.raises(ValueError, match="no longer supports"):
        CodexEngineHomeConfig(
            model="deepseek-flash",
            model_provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            env_key="OPENAI_API_KEY",
            wire_api="chat",
        )


def test_env_key_allowlist_is_closed():
    with pytest.raises(ValueError, match="closed allowlist"):
        CodexEngineHomeConfig(
            model="deepseek-flash",
            model_provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            env_key="ARBITRARY_CLIENT_KEY",
        )


def test_renderer_rejects_non_https_and_injection_shaped_values():
    with pytest.raises(ValueError, match="https"):
        CodexEngineHomeConfig(
            model="deepseek-flash",
            model_provider="deepseek",
            base_url="http://api.deepseek.com/v1",
            env_key="DEEPSEEK_API_KEY",
        )
    with pytest.raises(ValueError, match="identifier"):
        CodexEngineHomeConfig(
            model='deepseek"\nunsafe',
            model_provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            env_key="DEEPSEEK_API_KEY",
        )


def test_writer_denies_a_planted_symlink(tmp_path: Path):
    home = tmp_path / PRIVATE_ENGINE_HOME_NAME
    home.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.write_text("CANARY_VALUE")
    (home / "config.toml").symlink_to(outside)
    with pytest.raises(WorkdirOperationError):
        write_private_engine_config(home, _HOME_CONFIG)
    assert outside.read_text() == "CANARY_VALUE"


def test_adapter_writes_private_config_and_types_two_non_secret_slots(tmp_path: Path):
    host = _RecordingHost()
    adapter = CodexCliAdapter(
        host,
        config=CodexConfig(version="0.169.0"),
        gate=_GATE,
        workdir_root=tmp_path,
        resource_policy=_POLICY,
        engine_home_config=_HOME_CONFIG,
    )
    execution_id = uuid4()
    relative = f"aa11/{execution_id}"
    (tmp_path / relative).mkdir(parents=True, mode=0o700)
    request = ExecutionRequest(
        execution_id=execution_id,
        engine_id="codex",
        protocol_id="cli_exec",
        adapter_version="v1",
        tenant_id=_TENANT,
        agent_id=_AGENT,
        input="inspect the private engine home",
        execution_workdir=relative,
    )

    asyncio.run(adapter.start(request))

    home = tmp_path / relative / PRIVATE_ENGINE_HOME_NAME
    config_file = home / "config.toml"
    assert config_file.read_text() == _HOME_CONFIG.to_toml()
    assert stat.S_IMODE(os.stat(config_file).st_mode) == 0o600
    assert host.specs[0].environment == {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "CODEX_HOME": str(home),
    }
    assert "CANARY_VALUE" not in repr(host.specs[0])
