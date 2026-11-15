"""Regression lane for the D-1 fresh-volume quickstart seed crash (2026-11-14).

``seed_memory_common.ensure_agent`` used to assign the legacy model fields on
an already-constructed ``AgentConfig``; the canonical ``react`` alias stayed
at its ``None`` defaults, and the moment the draft round-tripped through the
JSONB column, the publish re-validation (``AgentService.parse_config``) saw a
set legacy alias contradicting the explicit null react alias and rejected it
as ``execution_configuration_invalid`` - crashing the quickstart bootstrap on
an empty volume (latent since the Phase 3 alias normalizer landed; unobserved
because the drill itself was deferred).

These pins run the same parse/validate sequence the create→publish service
performs, driven through the real ``ensure_agent``, and additionally document
the normalizer contract the fix must not weaken: post-mutation drafts stay
rejected, equal aliases stay accepted.
"""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from agent_platform.applications.seed_memory_common import ensure_agent
from agent_platform.business_capabilities.agent_config.service import (
    AgentConfig,
    AgentService,
    _standalone_execution_registry,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError

PROFILE_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "d1-regression-profile"))
PROFILE_VERSION = 3


class _FakeCatalog:
    """Scripted model-gateway catalog: profile rows carry fixed ids/versions."""

    def __init__(self) -> None:
        self.saved: dict[str, object] = {}

    async def list(self, tenant, kind):
        return []

    async def save(self, tenant, actor, kind, body):
        row = {
            "id": PROFILE_ID if kind == "profiles" else str(uuid.uuid5(uuid.NAMESPACE_DNS, kind)),
            "name": body.name,
            "revision": 1,
            "published_version": None,
        }
        self.saved[kind] = row
        return row

    async def publish(self, tenant, actor, kind_or_id, revision):
        return {"version": PROFILE_VERSION}


class _FakeAgents:
    """Mirrors the AgentService create/publish JSONB boundary exactly."""

    def __init__(self) -> None:
        self.draft_json: str | None = None
        self.published_config: AgentConfig | None = None

    async def list(self, tenant):
        return []

    async def create(self, tenant, actor, draft):
        # AgentService.create persists `draft.config.model_dump_json()` as the
        # draft column; the in-process instance never re-validates.
        self.draft_json = draft.config.model_dump_json()
        return {"id": str(uuid.uuid4()), "draft_revision": 1}

    async def publish(self, tenant, actor, aid, revision):
        # AgentService.publish re-parses the stored draft and validates the
        # execution config through the adapter registry - the D-1 crash point.
        config = AgentService.parse_config(json.loads(self.draft_json))
        _standalone_execution_registry().validate_config(config.execution_config())
        assert config.model_profile_id is not None, "profile binding was lost"
        assert config.react is not None
        assert str(config.react.model_profile_id) == PROFILE_ID
        assert config.react.model_profile_version == PROFILE_VERSION
        self.published_config = config
        return {"published": True}


def _p(agents: _FakeAgents, catalog: _FakeCatalog):
    return SimpleNamespace(
        business=SimpleNamespace(agents=agents),
        runtime=SimpleNamespace(gateway=SimpleNamespace(catalog=catalog)),
    )


def test_ensure_agent_binding_survives_publish_reparse():
    agents = _FakeAgents()
    catalog = _FakeCatalog()
    config = AgentConfig(
        system_prompt="Regression prompt",
        tool_names=[],
        knowledge_base_ids=[],
    )
    agent = asyncio.run(
        ensure_agent(
            _p(agents, catalog),
            "tenant-d1",
            "seed",
            "D1 Regression Assistant",
            "fresh-volume quickstart seed regression",
            config,
        )
    )
    assert agent["draft_revision"] == 1
    published = agents.published_config
    assert published is not None
    # Both representations carry the identical binding (normalizer contract),
    # and the caller-visible legacy attribute is a real UUID after binding.
    assert str(published.model_profile_id) == PROFILE_ID
    assert published.model_profile_version == PROFILE_VERSION
    assert str(published.react.model_profile_id) == PROFILE_ID
    assert published.react.model_profile_version == PROFILE_VERSION


def test_post_mutation_draft_shape_stays_rejected():
    # Documents the Phase 3 normalizer contract the D-1 fix relies on rather
    # than weakens: mutating legacy fields after construction still produces
    # a draft that re-parses as execution_configuration_invalid.
    config = AgentConfig(system_prompt="Regression prompt")
    config.model_profile_id = PROFILE_ID
    config.model_profile_version = PROFILE_VERSION
    stored = json.loads(config.model_dump_json())
    with pytest.raises(DomainError) as excinfo:
        AgentService.parse_config(stored)
    assert excinfo.value.code == "execution_configuration_invalid"


def test_equal_aliases_round_trip_cleanly():
    # The positive half of the same contract: an alias-consistent draft
    # re-parses with identical values on both sides.
    config = AgentConfig(
        system_prompt="Regression prompt",
        model_profile_id=PROFILE_ID,
        model_profile_version=PROFILE_VERSION,
    )
    stored = json.loads(config.model_dump_json())
    parsed = AgentService.parse_config(stored)
    assert str(parsed.model_profile_id) == PROFILE_ID
    assert str(parsed.react.model_profile_id) == PROFILE_ID
