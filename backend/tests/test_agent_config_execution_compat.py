import ast
import copy
import json
import re
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import text
from test_execution_orchestrator import (
    AGENT_ID,
    ExecutionOrchestrator,
    ParityMemory,
    ParityRepository,
    _registry,
    assert_real_worker_parity,
    parity_worker_row,
    run_real_worker_pair,
)
from test_model_gateway import setup
from test_platform_postgres import conversation
from test_platform_postgres import platform as _platform
from test_runtime_engine import SequenceModel, call, spec

from agent_platform.applications.platform_runtime.runtime_factory import RuntimeFactory
from agent_platform.business_capabilities.agent_config.service import AgentConfig
from agent_platform.core_platform.agent_execution.adapters.react import ReactAdapter
from agent_platform.core_platform.agent_execution.orchestration.execution_context import (
    capture_execution_context,
)
from agent_platform.core_platform.agent_runtime.engine import RuntimeEngine
from agent_platform.core_platform.agent_runtime.worker import RuntimeWorker
from agent_platform.core_platform.platform_services.integrations.business_tools.platform_tools import (
    PlatformTools,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.extension_contracts import RuntimeBindings

platform = _platform

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "agent_execution_baseline"
LEGACY_FIXTURES = ("legacy-core-shape.v1.json", "legacy-memory-shape.v1.json")
PRODUCTION_IDENTITY = ("react", "native", "v1")
LOCAL_TEST_IDENTITY = ("local-test", "scripted", "v1")


def _legacy_config(fixture_name: str, profile_id: str) -> tuple[Path, bytes, dict]:
    path = FIXTURE_ROOT / fixture_name
    source = path.read_bytes()
    config = copy.deepcopy(json.loads(source))
    config.update(
        model_profile_id=profile_id,
        model_profile_version=1,
        tool_names=[],
        knowledge_base_ids=[],
    )
    return path, source, config


async def _create_legacy_agent(client, runtime, settings, fixture_name: str):
    _, _, profile = await setup(client, "chat")
    created = await client.post(
        "/api/v1/agents",
        json={
            "name": f"legacy-{fixture_name}",
            "config": {
                "system_prompt": "Current config before legacy draft simulation",
                "model_profile_id": profile["id"],
                "model_profile_version": 1,
                "tool_names": [],
                "knowledge_base_ids": [],
            },
        },
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    path, source, legacy = _legacy_config(fixture_name, profile["id"])
    async with runtime.repository.engine.begin() as connection:
        result = await connection.execute(
            text(
                "UPDATE agents SET draft=CAST(:draft AS jsonb) "
                "WHERE id=:id AND tenant_id=:tenant AND draft_revision=:revision"
            ),
            {
                "id": UUID(agent["id"]),
                "tenant": settings.tenant_id,
                "draft": json.dumps(legacy),
                "revision": agent["draft_revision"],
            },
        )
        assert result.rowcount == 1
    return agent, path, source, legacy


async def _stored_version(runtime, agent_id: str, version: int) -> dict:
    async with runtime.repository.engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    text(
                        "SELECT version,config FROM agent_versions "
                        "WHERE agent_id=:id AND version=:version"
                    ),
                    {"id": UUID(agent_id), "version": version},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def _snapshot(runtime, tenant: str, agent_id: str, version: int | None = None) -> dict:
    async with runtime.repository.engine.connect() as connection:
        return await runtime.groups.business.agents.snapshot(
            tenant, UUID(agent_id), connection, version=version
        )


async def _update_and_publish(client, agent: dict, config: dict, revision: int) -> None:
    updated = await client.put(
        f"/api/v1/agents/{agent['id']}",
        json={"name": agent["name"], "revision": revision, "config": config},
    )
    assert updated.status_code == 200, updated.text
    published = await client.post(
        f"/api/v1/agents/{agent['id']}/publish", json={"revision": revision + 1}
    )
    assert published.status_code == 200, published.text


@pytest.mark.asyncio
@pytest.mark.postgres
@pytest.mark.parametrize("fixture_name", LEGACY_FIXTURES)
async def test_p0_it_08_legacy_raw_draft_publishes_normalized_v1(platform, fixture_name):
    client, runtime, settings = platform
    agent, fixture_path, fixture_source, legacy = await _create_legacy_agent(
        client, runtime, settings, fixture_name
    )

    raw = await client.get(f"/api/v1/agents/{agent['id']}")
    assert raw.status_code == 200, raw.text
    assert raw.json()["draft"] == legacy
    assert raw.json()["draft_revision"] == agent["draft_revision"]

    expected = AgentConfig.model_validate(legacy).model_dump(mode="json")
    published = await client.post(
        f"/api/v1/agents/{agent['id']}/publish",
        json={"revision": agent["draft_revision"]},
    )
    assert published.status_code == 200, published.text
    assert published.json()["version"] == 1

    raw_after_publish = await client.get(f"/api/v1/agents/{agent['id']}")
    assert raw_after_publish.json()["draft"] == legacy
    stored_v1 = await _stored_version(runtime, agent["id"], 1)
    assert stored_v1["config"] == expected
    assert set(stored_v1["config"]) == set(AgentConfig.model_fields)

    snapshot_v1 = await _snapshot(runtime, settings.tenant_id, agent["id"], version=1)
    assert snapshot_v1["version"] == 1
    assert snapshot_v1["config"] == stored_v1["config"]
    assert fixture_path.read_bytes() == fixture_source


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_later_draft_and_v2_do_not_rewrite_v1_or_cross_tenant_boundary(platform):
    client, runtime, settings = platform
    agent, _, _, legacy = await _create_legacy_agent(
        client, runtime, settings, "legacy-core-shape.v1.json"
    )
    published = await client.post(f"/api/v1/agents/{agent['id']}/publish", json={"revision": 1})
    assert published.status_code == 200, published.text
    expected_v1 = AgentConfig.model_validate(legacy).model_dump(mode="json")
    assert (await _stored_version(runtime, agent["id"], 1))["config"] == expected_v1

    v2_config = copy.deepcopy(legacy)
    v2_config["system_prompt"] = "Version two prompt"
    await _update_and_publish(client, agent, v2_config, revision=1)

    assert (await _stored_version(runtime, agent["id"], 1))["config"] == expected_v1
    snapshot_v1 = await _snapshot(runtime, settings.tenant_id, agent["id"], version=1)
    assert snapshot_v1["version"] == 1
    assert snapshot_v1["config"] == expected_v1
    latest = await _snapshot(runtime, settings.tenant_id, agent["id"])
    assert latest["version"] == 2
    assert latest["config"]["system_prompt"] == "Version two prompt"

    other_tenant = settings.tenant_id + "-other"
    with pytest.raises(DomainError) as versions_error:
        await runtime.groups.business.agents.versions(other_tenant, UUID(agent["id"]))
    assert (versions_error.value.code, versions_error.value.status) == ("not_found", 404)
    with pytest.raises(DomainError) as snapshot_error:
        await _snapshot(runtime, other_tenant, agent["id"], version=1)
    assert (snapshot_error.value.code, snapshot_error.value.status) == ("agent_not_found", 404)


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_queued_run_keeps_v1_snapshot_after_v2_is_published(platform):
    client, runtime, settings = platform
    agent, _, _, legacy = await _create_legacy_agent(
        client, runtime, settings, "legacy-core-shape.v1.json"
    )
    published = await client.post(f"/api/v1/agents/{agent['id']}/publish", json={"revision": 1})
    assert published.status_code == 200, published.text
    conv = await conversation(client, agent["id"])
    submitted = await client.post(
        f"/api/v1/conversations/{conv['id']}/messages", json={"content": "Capture v1"}
    )
    assert submitted.status_code == 202, submitted.text
    run_id = UUID(submitted.json()["run"]["id"])
    queued = await runtime.repository.get(run_id, settings.tenant_id)
    assert queued["status"] == "queued"
    captured_v1 = copy.deepcopy(queued["config"]["agent"])
    assert captured_v1["version"] == 1
    assert captured_v1["config"]["system_prompt"] == legacy["system_prompt"]

    v2_config = copy.deepcopy(legacy)
    v2_config["system_prompt"] = "Published after run submission"
    await _update_and_publish(client, agent, v2_config, revision=1)

    still_queued = await runtime.repository.get(run_id, settings.tenant_id)
    assert still_queued["status"] == "queued"
    assert still_queued["config"]["agent"] == captured_v1
    assert still_queued["config"]["agent"]["version"] == 1
    assert still_queued["config"]["agent"]["config"]["system_prompt"] == legacy["system_prompt"]


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_sparse_raw_version_exposes_direct_snapshot_tool_names_limitation(platform):
    client, runtime, settings = platform
    sparse = json.loads((FIXTURE_ROOT / "minimal-defaults.v1.json").read_text(encoding="utf-8"))
    AgentConfig.model_validate(sparse)
    created = await client.post(
        "/api/v1/agents", json={"name": "sparse raw version", "config": sparse}
    )
    assert created.status_code == 201, created.text
    agent_id = UUID(created.json()["id"])
    async with runtime.repository.engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO agent_versions(agent_id,version,config,tool_snapshot) "
                "VALUES(:id,1,CAST(:config AS jsonb),'[]'::jsonb)"
            ),
            {"id": agent_id, "config": json.dumps(sparse)},
        )
        await connection.execute(
            text("UPDATE agents SET published_version=1 WHERE id=:id AND tenant_id=:tenant"),
            {"id": agent_id, "tenant": settings.tenant_id},
        )

    with pytest.raises(KeyError) as caught:
        await _snapshot(runtime, settings.tenant_id, str(agent_id), version=1)
    assert caught.value.args == ("tool_names",)


def test_react_descriptor_metadata_matches_between_standalone_and_production_registries():
    """Minor-3 lock, rewritten per R-45: value-equivalent without losing strictness.

    Exactly one descriptor field is deployment-derived: ``policy_version``, which
    production reads from ``execution_capability_policy_version`` while the
    standalone mirror keeps its own literal (R-31 forbids forcing it). Every other
    field must stay field-identical, so the parity is not weakened; each side's
    derivation source is pinned separately, because "both default to v1" would
    hide a deployment that overrides the settings value.
    """
    from agent_platform.applications.platform_runtime import runtime_composition
    from agent_platform.business_capabilities.agent_config import service as agent_service

    settings = Settings(_env_file=None)
    production_registry = runtime_composition._execution_adapter_registry()
    runtime_composition._build_execution_orchestrator(None, production_registry, settings=settings)
    production = production_registry.metadata("react", "native", "v1")
    standalone = agent_service._standalone_execution_registry().metadata("react", "native", "v1")

    assert standalone.model_dump(exclude={"policy_version"}) == production.model_dump(
        exclude={"policy_version"}
    )
    assert production.policy_version == settings.execution_capability_policy_version
    assert (
        standalone.policy_version
        == Settings.model_fields["execution_capability_policy_version"].default
    )


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_p3_corrupt_stored_draft_update_degrades_audit_instead_of_500(platform):
    """A historical corrupt draft must not turn the audit diff into a 500.

    Chosen semantics: degrade. The submitted config already passed the strict
    parse/execution gates, so the save succeeds; the unreadable baseline only
    degrades the audit ``changes`` field to an empty diff. Blocking with a 409
    would make such an agent permanently unrepairable through the API.
    """
    client, runtime, settings = platform
    agent, _, _, legacy = await _create_legacy_agent(
        client, runtime, settings, "legacy-core-shape.v1.json"
    )
    async with runtime.repository.engine.begin() as connection:
        result = await connection.execute(
            text("UPDATE agents SET draft=CAST(:draft AS jsonb) WHERE id=:id"),
            {"id": UUID(agent["id"]), "draft": "{}"},
        )
        assert result.rowcount == 1

    repaired = copy.deepcopy(legacy)
    repaired["system_prompt"] = "Repaired after a corrupt stored draft"
    response = await client.put(
        f"/api/v1/agents/{agent['id']}",
        json={"name": agent["name"], "revision": agent["draft_revision"], "config": repaired},
    )
    assert response.status_code == 200, response.text

    stored = await client.get(f"/api/v1/agents/{agent['id']}")
    # ``update`` stores the canonical serialization of the submitted config.
    assert stored.json()["draft"] == AgentConfig.model_validate(repaired).model_dump(mode="json")

    async with runtime.repository.engine.connect() as connection:
        audit_row = (
            (
                await connection.execute(
                    text(
                        "SELECT details FROM audit_records "
                        "WHERE tenant_id=:tenant AND resource=:resource "
                        "AND action='agent.updated' ORDER BY id DESC LIMIT 1"
                    ),
                    {"tenant": settings.tenant_id, "resource": agent["id"]},
                )
            )
            .mappings()
            .one()
        )
    assert audit_row["details"]["changes"] == {}


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_p3_corrupt_stored_draft_update_still_records_name_change_despite_degraded_diff(
    platform,
):
    """Degradation is scoped to the config diff only; name/description audit survives."""
    client, runtime, settings = platform
    agent, _, _, legacy = await _create_legacy_agent(
        client, runtime, settings, "legacy-core-shape.v1.json"
    )
    async with runtime.repository.engine.begin() as connection:
        result = await connection.execute(
            text("UPDATE agents SET draft=CAST(:draft AS jsonb) WHERE id=:id"),
            {"id": UUID(agent["id"]), "draft": "{}"},
        )
        assert result.rowcount == 1

    renamed = copy.deepcopy(legacy)
    response = await client.put(
        f"/api/v1/agents/{agent['id']}",
        json={
            "name": f"{agent['name']}-renamed",
            "revision": agent["draft_revision"],
            "config": renamed,
        },
    )
    assert response.status_code == 200, response.text

    async with runtime.repository.engine.connect() as connection:
        audit_row = (
            (
                await connection.execute(
                    text(
                        "SELECT details FROM audit_records "
                        "WHERE tenant_id=:tenant AND resource=:resource "
                        "AND action='agent.updated' ORDER BY id DESC LIMIT 1"
                    ),
                    {"tenant": settings.tenant_id, "resource": agent["id"]},
                )
            )
            .mappings()
            .one()
        )
    assert audit_row["details"]["changes"] == {
        "name": {"from": agent["name"], "to": f"{agent['name']}-renamed"}
    }


def _identity_pattern(identity: tuple[str, str, str]) -> str:
    return r"\(\s*" + r"\s*,\s*".join(map(re.escape, identity)) + r"\s*\)"


def test_p0_ut_08_frozen_identities_terminology_and_worker_neutrality():
    assert PRODUCTION_IDENTITY != LOCAL_TEST_IDENTITY
    production_pattern = _identity_pattern(PRODUCTION_IDENTITY)
    local_test_pattern = _identity_pattern(LOCAL_TEST_IDENTITY)
    evidence = {}
    for suffix in (".md", ".en.md"):
        architecture = (
            REPO_ROOT / "docs" / "architecture" / f"agent-execution-platform-v2{suffix}"
        ).read_text(encoding="utf-8")
        phase_1 = (
            REPO_ROOT
            / "docs"
            / "requirement"
            / "agent-execution-platform-v2"
            / "phase-1-execution-contract-registries"
            / f"03-technical-design{suffix}"
        ).read_text(encoding="utf-8")
        checklist = (
            REPO_ROOT
            / "docs"
            / "requirement"
            / "agent-execution-platform-v2"
            / "phase-0-baseline-inventory"
            / "baseline"
            / f"refactoring-checklist{suffix}"
        ).read_text(encoding="utf-8")
        evidence[suffix] = (architecture, checklist)

        assert re.search(production_pattern, architecture), suffix
        assert "LocalTestAdapter" in architecture, suffix
        for document in (phase_1, checklist):
            assert re.search(production_pattern, document), suffix
            assert re.search(local_test_pattern, document), suffix

    architecture_zh, checklist_zh = evidence[".md"]
    architecture_en, checklist_en = evidence[".en.md"]
    assert "`Run = 一次 Execution 尝试`" in architecture_zh
    assert "暂不采用 Task / Execution 双表模型" in architecture_zh
    assert "`Run = one Execution attempt`" in architecture_en
    assert "No immediate Task / Execution double-table model" in architecture_en
    assert "不引入 Task/Execution 双表" in checklist_zh
    assert "No Task/Execution dual-table model" in checklist_en
    assert "无 Engine 分支" in checklist_zh
    assert "No Engine branches" in checklist_en

    production_sources = (
        "backend/src/agent_platform/business_capabilities/agent_config/service.py",
        "backend/src/agent_platform/applications/platform_runtime/runtime_factory.py",
        "backend/src/agent_platform/applications/platform_runtime/runtime_composition.py",
        "backend/src/agent_platform/core_platform/agent_runtime/worker.py",
    )
    for relative_path in production_sources:
        source = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert LOCAL_TEST_IDENTITY[0] not in source, relative_path

    worker_source = (REPO_ROOT / production_sources[-1]).read_text(encoding="utf-8")
    worker_tree = ast.parse(worker_source)
    worker_symbols = {
        *(node.id for node in ast.walk(worker_tree) if isinstance(node, ast.Name)),
        *(node.attr for node in ast.walk(worker_tree) if isinstance(node, ast.Attribute)),
        *(
            node.value
            for node in ast.walk(worker_tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ),
    }
    forbidden_selection_fields = {
        "engine_id",
        "protocol_id",
        "adapter_id",
        "adapter_name",
        "adapter_version",
        "provider_id",
        "provider_name",
    }
    assert worker_symbols.isdisjoint(forbidden_selection_fields)
    for node in ast.walk(worker_tree):
        if isinstance(node, ast.If):
            assert "provider" not in ast.unparse(node.test).lower()


@pytest.mark.asyncio
async def test_p2_it02_published_snapshot_language_and_multiround_tool_parity(monkeypatch):
    """P2-IT02/CM04: real UUID snapshot drives the same real Factory/PlatformTools chain."""
    config = AgentConfig(
        system_prompt="Answer from the controlled snapshot.",
        reply_language="zh-CN",
        model_profile_id="50000000-0000-4000-8000-000000000005",
        model_profile_version=3,
        tool_names=["lookup"],
        max_model_rounds=4,
    )
    snapshot = {
        "id": AGENT_ID,
        "version": 7,
        "config": config.model_dump(mode="json"),
        "tools": [{"spec": spec().model_dump(mode="json"), "version": "tool-v1"}],
    }
    original = copy.deepcopy(snapshot)
    model = SequenceModel(
        call("snapshot-A"),
        AIMessage(content="snapshot answer"),
        call("snapshot-A"),
        AIMessage(content="snapshot answer"),
    )

    class Policy:
        def check_rounds(self, rounds, settings):
            return rounds

        async def check(self, tenant_id, name, allowed):
            assert name in allowed

    class Tools:
        async def credential_headers(self, tenant_id, spec, connection=None):
            return {}

    class ControlledFactory(RuntimeFactory):
        def bound_model(self, snapshot, schemas, run_id=None):
            assert snapshot["id"] == AGENT_ID
            assert snapshot["config"]["model_profile_version"] == 3
            return model

    def build_factory(client, settings, base_runtime):
        bindings = RuntimeBindings(policy=Policy(), tools=Tools())
        return ControlledFactory(base_runtime, bindings, client, settings, base_runtime.tools.limit)

    async def http(request):
        return httpx.Response(200, json={"result": request.url.params["order_id"]})

    row = parity_worker_row(config={"fingerprint": "parity-fingerprint", "agent": snapshot})
    runtime_errors = []
    original_run = RuntimeEngine.run

    async def record_run(runtime, *args, **kwargs):
        try:
            return await original_run(runtime, *args, **kwargs)
        except Exception as exc:
            runtime_errors.append(exc)
            raise

    monkeypatch.setattr(RuntimeEngine, "run", record_run)
    monkeypatch.setattr(
        PlatformTools,
        "_operation_id",
        lambda self, name, args: UUID("60000000-0000-4000-8000-000000000006"),
    )
    off, on = await run_real_worker_pair(
        model=model,
        row=row,
        transport=httpx.MockTransport(http),
        factory_builder=build_factory,
    )

    assert not runtime_errors, [repr(error) for error in runtime_errors]
    assert off["status"] == "completed", (off["events"], off["model_calls"])
    assert_real_worker_parity(off, on)
    assert snapshot == original
    assert on["output"] == "snapshot answer"
    assert "Reply in Simplified Chinese." in on["model_calls"][0][0]["content"]
    assert "Answer from the controlled snapshot." in on["model_calls"][0][0]["content"]
    tool_completed = [event for event in on["events"] if event["type"] == "tool.completed"]
    assert len(tool_completed) == 1
    assert tool_completed[0]["data"]["tool_version"] == "tool-v1"


@pytest.mark.asyncio
async def test_p2_t9_a1_published_snapshot_serial_no_tool_off_on_parity():
    """T9 A1: a real published snapshot drives the identical serial no-tool script."""
    config = AgentConfig(
        system_prompt="Answer from the controlled serial snapshot.",
        reply_language="en",
        model_profile_id="50000000-0000-4000-8000-000000000005",
        model_profile_version=3,
        tool_names=[],
        max_model_rounds=2,
    )
    snapshot = {
        "id": AGENT_ID,
        "version": 7,
        "config": config.model_dump(mode="json"),
        "tools": [],
    }
    original = copy.deepcopy(snapshot)

    def reply(gateway_call_id):
        return AIMessage(
            content="serial snapshot answer",
            usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            response_metadata={"gateway_call_id": gateway_call_id},
        )

    model = SequenceModel(reply("serial-off"), reply("serial-on"))

    class Policy:
        def check_rounds(self, rounds, settings):
            return rounds

    class Tools:
        async def credential_headers(self, tenant_id, spec, connection=None):
            raise AssertionError("the no-tool scenario must not resolve credentials")

    class ControlledFactory(RuntimeFactory):
        def bound_model(self, snapshot, schemas, run_id=None):
            assert snapshot["id"] == AGENT_ID
            assert snapshot["config"]["tool_names"] == []
            assert snapshot["tools"] == []
            assert schemas == []
            return model

    def build_factory(client, settings, base_runtime):
        bindings = RuntimeBindings(policy=Policy(), tools=Tools())
        return ControlledFactory(base_runtime, bindings, client, settings, base_runtime.tools.limit)

    row = parity_worker_row(config={"fingerprint": "parity-fingerprint", "agent": snapshot})
    off, on = await run_real_worker_pair(
        model=model, row=row, memory=ParityMemory(), factory_builder=build_factory
    )

    assert_real_worker_parity(off, on)
    assert snapshot == original
    for capture in (off, on):
        assert capture["status"] == "completed"
        assert capture["output"] == "serial snapshot answer"
        assert capture["error_code"] is None
        assert capture["history"] == [
            {"role": "user", "content": "current question"},
            {"role": "assistant", "content": "serial snapshot answer"},
        ]
        assert capture["dropped"] == []
        assert capture["aggregate_usage"] == {}
        assert capture["usage"] == [{"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}]
        assert [event["type"] for event in capture["events"]] == [
            "model.started",
            "model.completed",
        ]
        assert not any(event["type"].startswith("tool.") for event in capture["events"])
        assert capture["terminal"]["type"] == "run.completed"
        assert capture["terminal"]["seq"] == len(capture["replay"])
        assert [event["seq"] for event in capture["replay"]] == list(
            range(1, len(capture["replay"]) + 1)
        )


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_p3_it_01_legacy_get_is_read_only_and_default_diff_is_empty(platform):
    client, runtime, settings = platform
    agent, _, _, legacy = await _create_legacy_agent(
        client, runtime, settings, "legacy-core-shape.v1.json"
    )
    agent_id = UUID(agent["id"])

    async def stored_draft():
        async with runtime.repository.engine.connect() as connection:
            return dict(
                (
                    await connection.execute(
                        text(
                            "SELECT draft,draft_revision,updated_at FROM agents "
                            "WHERE id=:id AND tenant_id=:tenant"
                        ),
                        {"id": agent_id, "tenant": settings.tenant_id},
                    )
                )
                .mappings()
                .one()
            )

    before = await stored_draft()
    first = await client.get(f"/api/v1/agents/{agent['id']}")
    second = await client.get(f"/api/v1/agents/{agent['id']}")
    assert first.status_code == second.status_code == 200
    assert first.json()["draft"] == second.json()["draft"] == legacy
    assert await stored_draft() == before

    published = await client.post(f"/api/v1/agents/{agent['id']}/publish", json={"revision": 1})
    assert published.status_code == 200, published.text
    diff = await client.get(f"/api/v1/agents/{agent['id']}/diff?version=1")
    assert diff.status_code == 200, diff.text
    assert diff.json()["changes"] == []

    updated = await client.put(
        f"/api/v1/agents/{agent['id']}",
        json={"name": agent["name"], "revision": 1, "config": legacy},
    )
    assert updated.status_code == 200, updated.text
    diff = await client.get(f"/api/v1/agents/{agent['id']}/diff?version=1")
    assert diff.json()["changes"] == []
    async with runtime.repository.engine.connect() as connection:
        audit_row = (
            (
                await connection.execute(
                    text(
                        "SELECT details FROM audit_records "
                        "WHERE tenant_id=:tenant AND resource=:resource "
                        "AND action='agent.updated' ORDER BY id DESC LIMIT 1"
                    ),
                    {"tenant": settings.tenant_id, "resource": agent["id"]},
                )
            )
            .mappings()
            .one()
        )
    assert audit_row["details"]["changes"] == {}


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_p3_it_02_new_react_publish_and_metadata_validation_never_create_adapter(
    platform, monkeypatch
):
    from agent_platform.applications.platform_runtime.react_adapter_factory import (
        ReactAdapterFactory,
    )

    client, runtime, settings = platform
    _, _, profile = await setup(client, "chat")
    factory_calls = 0

    def forbidden_factory(self):
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("AgentConfig metadata validation must not resolve an adapter")

    monkeypatch.setattr(ReactAdapterFactory, "__call__", forbidden_factory)
    config = {
        "system_prompt": "Canonical React config",
        "engine": {
            "engine_id": "react",
            "protocol_id": "native",
            "adapter_version": "v1",
        },
        "react": {
            "model_profile_id": profile["id"],
            "model_profile_version": 1,
            "max_model_rounds": 4,
        },
        "disabled_capabilities": ["streaming", "streaming"],
        "tool_names": [],
        "knowledge_base_ids": [],
    }
    created = await client.post(
        "/api/v1/agents", json={"name": "canonical-react", "config": config}
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["draft"]["engine"]["engine_id"] == "react"
    assert agent["draft"]["react"]["max_model_rounds"] == 4
    assert agent["draft"]["disabled_capabilities"] == ["streaming"]

    published = await client.post(f"/api/v1/agents/{agent['id']}/publish", json={"revision": 1})
    assert published.status_code == 200, published.text
    stored = await _stored_version(runtime, agent["id"], 1)
    assert stored["config"]["react"]["model_profile_id"] == profile["id"]
    assert stored["config"]["model_profile_id"] == profile["id"]
    assert stored["config"]["disabled_capabilities"] == ["streaming"]
    snapshot = await _snapshot(runtime, settings.tenant_id, agent["id"], version=1)
    assert snapshot["config"]["engine"]["adapter_version"] == "v1"
    assert snapshot["config"]["max_model_rounds"] == 4
    assert factory_calls == 0


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_p3_it_02_unknown_engine_is_rejected_before_publish_without_adapter(platform):
    client, runtime, settings = platform
    agent, _, _, legacy = await _create_legacy_agent(
        client, runtime, settings, "legacy-core-shape.v1.json"
    )
    unknown = copy.deepcopy(legacy)
    unknown.update(
        engine={
            "engine_id": "missing",
            "protocol_id": "native",
            "adapter_version": "v1",
        },
        react=None,
        model_profile_id=None,
        model_profile_version=None,
    )
    async with runtime.repository.engine.begin() as connection:
        await connection.execute(
            text("UPDATE agents SET draft=CAST(:draft AS jsonb) WHERE id=:id"),
            {"id": UUID(agent["id"]), "draft": json.dumps(unknown)},
        )

    response = await client.post(f"/api/v1/agents/{agent['id']}/publish", json={"revision": 1})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "execution_engine_unavailable"
    assert (await client.get(f"/api/v1/agents/{agent['id']}/versions")).json() == []


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_p3_it_02_invalid_stored_config_has_stable_publish_rejection(platform):
    client, runtime, settings = platform
    agent, _, _, legacy = await _create_legacy_agent(
        client, runtime, settings, "legacy-core-shape.v1.json"
    )
    invalid = copy.deepcopy(legacy)
    invalid["max_model_rounds"] = 0
    async with runtime.repository.engine.begin() as connection:
        await connection.execute(
            text("UPDATE agents SET draft=CAST(:draft AS jsonb) WHERE id=:id"),
            {"id": UUID(agent["id"]), "draft": json.dumps(invalid)},
        )

    response = await client.post(f"/api/v1/agents/{agent['id']}/publish", json={"revision": 1})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "execution_configuration_invalid"
    assert (await client.get(f"/api/v1/agents/{agent['id']}/versions")).json() == []


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_p3_it_02_alias_conflict_is_rejected_before_update(platform):
    client, runtime, settings = platform
    agent, _, _, legacy = await _create_legacy_agent(
        client, runtime, settings, "legacy-core-shape.v1.json"
    )
    conflict = copy.deepcopy(legacy)
    conflict["react"] = {
        "model_profile_id": legacy["model_profile_id"],
        "model_profile_version": legacy["model_profile_version"],
        "max_model_rounds": legacy["max_model_rounds"] + 1,
    }

    response = await client.put(
        f"/api/v1/agents/{agent['id']}",
        json={"name": agent["name"], "revision": 1, "config": conflict},
    )

    assert response.status_code == 422, response.text
    assert "react.max_model_rounds" in response.text
    assert (await client.get(f"/api/v1/agents/{agent['id']}")).json()["draft"] == legacy


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_p3_it_16_new_react_does_not_bypass_model_capability_validation(platform):
    client, _runtime, _settings = platform
    _, _, profile = await setup(client, "chat", model_extra={"tool_calling": False})
    config = {
        "system_prompt": "Model checks still apply",
        "react": {
            "model_profile_id": profile["id"],
            "model_profile_version": 1,
            "max_model_rounds": 6,
        },
        "tool_names": ["lookup"],
        "knowledge_base_ids": [],
    }
    created = await client.post(
        "/api/v1/agents", json={"name": "model-capability-boundary", "config": config}
    )
    assert created.status_code == 201, created.text

    response = await client.post(
        f"/api/v1/agents/{created.json()['id']}/publish", json={"revision": 1}
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == "agent_model_capability_mismatch"
    assert (await client.get(f"/api/v1/agents/{created.json()['id']}/versions")).json() == []


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_p3_it_16_new_react_preserves_tool_resolution_and_snapshot(platform):
    client, runtime, settings = platform
    _, _, profile = await setup(client, "chat")
    spec = {
        "name": "phase3_lookup",
        "description": "v1",
        "url": "http://localhost/orders",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
    }
    tool = await client.post("/api/v1/tools", json=spec)
    assert tool.status_code == 201, tool.text
    created = await client.post(
        "/api/v1/agents",
        json={
            "name": "canonical-react-tools",
            "config": {
                "system_prompt": "Use the released tool",
                "react": {
                    "model_profile_id": profile["id"],
                    "model_profile_version": 1,
                    "max_model_rounds": 6,
                },
                "tool_names": ["phase3_lookup"],
                "knowledge_base_ids": [],
            },
        },
    )
    assert created.status_code == 201, created.text
    agent = created.json()

    published = await client.post(f"/api/v1/agents/{agent['id']}/publish", json={"revision": 1})

    assert published.status_code == 200, published.text
    snapshot = await _snapshot(runtime, settings.tenant_id, agent["id"], version=1)
    assert snapshot["config"]["tool_names"] == ["phase3_lookup"]
    assert snapshot["config"]["react"]["model_profile_id"] == profile["id"]
    assert [tool["spec"]["name"] for tool in snapshot["tools"]] == ["phase3_lookup"]
    assert snapshot["tools"][0]["version"] == 1


@pytest.mark.asyncio
async def test_p2_it04_full_new_path_owns_one_private_stream_and_public_delivery(
    monkeypatch,
):
    """P2-IT04/CM08: Factory, PlatformTools and Engine share private emit, never Worker emit."""
    config = AgentConfig(
        system_prompt="controlled",
        model_profile_id="50000000-0000-4000-8000-000000000005",
        model_profile_version=1,
        tool_names=[],
    )
    snapshot = {
        "id": AGENT_ID,
        "version": 1,
        "config": config.model_dump(mode="json"),
        "tools": [],
    }
    model = SequenceModel(AIMessage(content="private stream answer"))
    private_emits = {"factory": [], "tools": [], "run": []}
    contexts = []
    acknowledgements = []
    private_collections = []
    repository = ParityRepository()

    class Policy:
        def check_rounds(self, rounds, settings):
            return rounds

    class ControlledFactory(RuntimeFactory):
        async def for_run(self, row, emit):
            private_emits["factory"].append(emit)
            runtime = await super().for_run(row, emit)
            private_emits["tools"].append(runtime.tools.emit)
            return runtime

        def bound_model(self, snapshot, schemas, run_id=None):
            return model

    original_run = RuntimeEngine.run

    async def run(runtime, message, history, emit, **kwargs):
        private_emits["run"].append(emit)
        return await original_run(runtime, message, history, emit, **kwargs)

    monkeypatch.setattr(RuntimeEngine, "run", run)

    settings = Settings(_env_file=None, execution_orchestrator_enabled=True)
    async with httpx.AsyncClient() as client:
        factory = ControlledFactory(None, RuntimeBindings(policy=Policy()), client, settings, None)

        def make_adapter():
            contexts.append(capture_execution_context())
            adapter = ReactAdapter(contexts[-1], factory)
            original_stream = adapter.stream_events
            original_collect = adapter.collect_outcome

            def stream_events(handle):
                stream = original_stream(handle)
                acknowledge = stream.acknowledge

                async def ack(event):
                    acknowledgements.append((event.event_id, repository.append_calls))
                    await acknowledge(event)

                stream.acknowledge = ack
                return stream

            async def collect_outcome(handle):
                private_collections.append(handle)
                return await original_collect(handle)

            async def public_collect(handle):
                raise AssertionError("React must use private Outcome collection exactly once")

            adapter.stream_events = stream_events
            adapter.collect_outcome = collect_outcome
            adapter.collect_result = public_collect
            return adapter

        worker = RuntimeWorker(
            repository,
            factory,
            settings,
            "parity-fingerprint",
            orchestrator=ExecutionOrchestrator(_registry(make_adapter)),
        )
        row = parity_worker_row(config={"fingerprint": "parity-fingerprint", "agent": snapshot})
        await worker._execute(row)

    assert repository.finishes[0]["status"] == "completed", repository.finishes
    assert len(contexts) == 1
    assert not any("emit" in field for field in vars(type(contexts[0])))
    assert private_emits["factory"][0] is private_emits["tools"][0]
    assert private_emits["factory"][0] is private_emits["run"][0]
    assert len(private_collections) == 1
    assert len(repository.finishes) == 1
    assert repository.finishes[0]["status"] == "completed"
    durable_count = len(repository.events) - 1
    assert [count for _, count in acknowledgements] == list(range(1, durable_count + 1))
    assert repository.events[-1]["type"] == "run.completed"
