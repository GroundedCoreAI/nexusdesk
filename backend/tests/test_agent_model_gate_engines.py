"""The platform model gate is engine-scoped (P7 defect D-1).

A CLI engine selects its provider/model inside its own configuration, and
``AgentConfig.normalize_execution`` normalizes the legacy model aliases to
``None`` for it. Publishing such an Agent used to fail with
``agent_model_required`` because the gate was unconditional, which made every
Stage A Codex Agent impossible to publish, roll back or snapshot.
"""

import asyncio

import pytest

from agent_platform.business_capabilities.agent_config.service import (
    MODEL_PROFILE_ENGINES,
    AgentConfig,
    AgentService,
)
from agent_platform.core_platform.agent_execution.contracts.config import (
    CodexConfig,
    EngineIdentity,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError

CODEX_IDENTITY = {
    "engine_id": "codex",
    "protocol_id": "cli_exec",
    "adapter_version": "v1",
}


class _ExplodingCatalog:
    """Any Gateway lookup from a CLI-engine Agent is a defect."""

    async def resolve(self, *args, **kwargs):
        raise AssertionError("CLI engines must not resolve a Gateway model profile")


def _service() -> AgentService:
    service = object.__new__(AgentService)
    service.model_catalog = _ExplodingCatalog()
    return service


def _codex_agent_config() -> AgentConfig:
    return AgentConfig(
        system_prompt="stage-a probe",
        engine=EngineIdentity(**CODEX_IDENTITY),
        codex=CodexConfig(version="0.169.0"),
    )


def test_cli_engine_skips_the_platform_model_gate():
    config = _codex_agent_config()
    # The normalizer already drops the legacy aliases for a non-React engine.
    assert config.model_profile_id is None
    assert config.model_profile_version is None
    assert config.engine.engine_id not in MODEL_PROFILE_ENGINES

    asyncio.run(AgentService.validate_model(_service(), "local", config, None))


def test_react_engine_still_requires_a_profile():
    config = AgentConfig(system_prompt="no model bound")
    assert config.engine.engine_id in MODEL_PROFILE_ENGINES

    with pytest.raises(DomainError) as excinfo:
        asyncio.run(AgentService.validate_model(_service(), "local", config, None))
    assert excinfo.value.code == "agent_model_required"
    assert excinfo.value.status == 409


def test_react_engine_still_resolves_the_bound_profile():
    config = AgentConfig(
        system_prompt="bound model",
        model_profile_id="7f3c1f9e-2f7b-4f8a-9c19-2b7d8f2f4c11",
        model_profile_version=1,
    )
    with pytest.raises(AssertionError):
        asyncio.run(AgentService.validate_model(_service(), "local", config, None))
