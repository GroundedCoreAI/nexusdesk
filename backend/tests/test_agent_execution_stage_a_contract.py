"""P1 Stage A CLI engine enablement: publishable Codex execution contract."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_platform.business_capabilities.agent_config.service import AgentConfig
from agent_platform.core_platform.agent_execution.contracts import (
    CodexConfig,
    EngineIdentity,
    ExecutionConfig,
    normalize_execution_config,
)
from agent_platform.core_platform.agent_execution.contracts.errors import ConfigurationError
from agent_platform.core_platform.agent_execution.contracts.snapshots import (
    ExecutionSnapshotError,
    build_execution_config_snapshot,
    serialize_snapshot,
)
from agent_platform.core_platform.agent_execution.registry import (
    AdapterDescriptor,
    AdapterRegistry,
    EngineDescriptor,
    EngineRegistry,
    ProtocolDescriptor,
    ProtocolRegistry,
)

CODEX_ENGINE = {"engine_id": "codex", "protocol_id": "cli_exec", "adapter_version": "v1"}


def _codex_registry() -> AdapterRegistry:
    engines = EngineRegistry()
    protocols = ProtocolRegistry()
    engines.register(EngineDescriptor(engine_id="codex"))
    protocols.register(ProtocolDescriptor(protocol_id="cli_exec"))
    adapters = AdapterRegistry(engines, protocols)

    def factory():  # pragma: no cover - publish validation never resolves an adapter
        raise AssertionError("publish validation must not instantiate an adapter")

    adapters.register(
        AdapterDescriptor(
            engine_id="codex",
            protocol_id="cli_exec",
            adapter_version="v1",
            enabled=True,
            config_schema=CodexConfig,
        ),
        factory,
    )
    return adapters


def test_codex_block_is_canonical_and_engine_specific():
    config = normalize_execution_config({"engine": CODEX_ENGINE, "codex": {"version": "0.169.0"}})
    assert config.react is None
    assert config.codex is not None
    assert config.codex.version == "0.169.0"
    assert config.codex.protocol == "cli_exec"
    assert set(config.model_dump()) == {"engine", "react", "codex", "disabled_capabilities"}


def test_codex_and_react_blocks_remain_mutually_exclusive():
    with pytest.raises(ValidationError, match="react"):
        normalize_execution_config(
            {"engine": CODEX_ENGINE, "react": {"max_model_rounds": 6}, "codex": {"version": "0.169.0"}}
        )
    with pytest.raises(ValidationError, match="codex"):
        normalize_execution_config(
            {
                "engine": {"engine_id": "react", "protocol_id": "native", "adapter_version": "v1"},
                "react": {"max_model_rounds": 6},
                "codex": {"version": "0.169.0"},
            }
        )


def test_registry_validates_the_codex_block_not_the_react_block():
    registry = _codex_registry()
    valid = normalize_execution_config({"engine": CODEX_ENGINE, "codex": {"version": "0.169.0"}})
    assert registry.validate_config(valid) == valid

    with pytest.raises(ConfigurationError):
        registry.validate_config(normalize_execution_config({"engine": CODEX_ENGINE}))

    with pytest.raises(ValidationError):
        normalize_execution_config(
            {"engine": CODEX_ENGINE, "codex": {"version": "0.169.0", "approval_mode": "always"}}
        )


def test_agent_config_round_trips_the_codex_block():
    codex = CodexConfig(version="0.169.0", credential_ref=str(uuid4()))
    agent = AgentConfig(
        system_prompt="demo",
        tool_names=[],
        knowledge_base_ids=[],
        engine=EngineIdentity(**CODEX_ENGINE),
        codex=codex,
    )
    assert agent.codex == codex
    assert agent.execution_config().codex == codex


def _snapshot(config: ExecutionConfig):
    return build_execution_config_snapshot(
        execution_id=uuid4(),
        config=config,
        agent_id=None,
        agent_version=None,
        provider_id="codex",
        provider_version="v1",
    )


def test_codex_reference_and_path_env_snapshot_only_at_the_typed_path():
    config = normalize_execution_config(
        {
            "engine": CODEX_ENGINE,
            "codex": {
                "version": "0.169.0",
                "credential_ref": str(uuid4()),
                "path_env": "/opt/node/bin:/usr/bin",
            },
        }
    )
    payload = serialize_snapshot(_snapshot(config))
    assert '"credential_ref"' in payload
    assert '"path_env"' in payload

    bad = config.model_copy(
        update={
            "codex": config.codex.model_copy(update={"credential_ref": "sk-not-a-reference"})
        }
    )
    with pytest.raises(ExecutionSnapshotError):
        serialize_snapshot(_snapshot(bad))
