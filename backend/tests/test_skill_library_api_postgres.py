import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import ClassVar
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from test_platform_postgres import platform as _platform_fixture

from agent_platform.core_platform.platform_services.persistence.store import DomainError

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]
skill_platform_base = _platform_fixture


@pytest_asyncio.fixture
async def skill_platform(skill_platform_base):
    client, services, settings = skill_platform_base
    try:
        yield client, services, settings
    finally:
        async with services.repository.engine.begin() as connection:
            for table in ("skill_packages", "skill_versions", "skill_test_runs", "skills"):
                await connection.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id=:tenant"),
                    {"tenant": settings.tenant_id},
                )


def empty_definition(mode="professional"):
    return {
        "schema_version": "v1",
        "creation_mode": mode,
        "type": "instruction",
        "trigger": "agent_auto",
        "instructions": "",
        "parameters": [],
        "output": {"format": "text", "schema": None},
        "dependencies": {
            "model_profile_id": None,
            "model_profile_version": None,
            "knowledge_base_ids": [],
            "tool_names": [],
            "handoff_queue": None,
        },
        "runtime": {
            "timeout_seconds": 30,
            "retry_policy": "none",
            "confirmation_required": False,
            "idempotency": "none",
            "error_behavior": "fail",
            "max_amount": None,
        },
        "permission_scope": "workspace",
    }


async def create_professional(client, name_instruction="incomplete draft"):
    body = {
        "mode": "professional",
        "prompt": None,
        "template_key": None,
        "definition": {**empty_definition(), "instructions": name_instruction},
    }
    response = await client.post("/api/v1/skills", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def create_handoff(client):
    response = await client.post(
        "/api/v1/skills",
        json={
            "mode": "template",
            "prompt": None,
            "template_key": "handoff-to-human",
            "definition": None,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def save_handoff_draft(client, skill, instructions):
    body = {
        "revision": skill["draft_revision"],
        "name": skill["name"],
        "description": skill["description"],
        "category": skill["category"],
        "tags": skill["tags"],
        "visibility": "workspace",
        "definition": {
            **skill["definition"],
            "instructions": instructions,
        },
    }
    response = await client.put(f"/api/v1/skills/{skill['key']}/draft", json=body)
    assert response.status_code == 200, response.text
    return response.json()


async def run_handoff_test(client, skill, request_id):
    response = await client.post(
        f"/api/v1/skills/{skill['key']}/test-runs",
        json={
            "draft_revision": skill["draft_revision"],
            "input": {"reason": "Customer requested a human"},
            "scenario": "handoff contract",
            "client_request_id": request_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def make_definition(
    *,
    definition_type="instruction",
    instructions="",
    dependencies=None,
    runtime=None,
    output=None,
):
    """Build a v1 definition without pretending release-only fields are valid."""

    payload = empty_definition()
    payload["type"] = definition_type
    payload["instructions"] = instructions
    if output is not None:
        payload["output"] = output
    if dependencies:
        payload["dependencies"].update(dependencies)
    if runtime:
        payload["runtime"].update(runtime)
    return payload


async def create_with_definition(client, definition, *, mode="professional"):
    response = await client.post(
        "/api/v1/skills",
        json={
            "mode": mode,
            "prompt": None,
            "template_key": None,
            "definition": definition,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def save_definition(client, skill, definition, *, revision=None):
    response = await client.put(
        f"/api/v1/skills/{skill['key']}/draft",
        json={
            "revision": revision if revision is not None else skill["draft_revision"],
            "name": skill["name"],
            "description": skill["description"],
            "category": skill["category"],
            "tags": skill["tags"],
            "visibility": "workspace",
            "definition": definition,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def run_skill_test(client, skill, payload, *, request_id=None, scenario=""):
    response = await client.post(
        f"/api/v1/skills/{skill['key']}/test-runs",
        json={
            "draft_revision": skill["draft_revision"],
            "input": payload,
            "scenario": scenario,
            "client_request_id": request_id or str(uuid4()),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def fetch_skill_state(services, tenant, skill_key):
    async with services.repository.engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    text(
                        "SELECT id,draft_revision,draft_definition,status,"
                        "published_version,published_revision "
                        "FROM skills WHERE tenant_id=:tenant AND skill_key=:key"
                    ),
                    {"tenant": tenant, "key": skill_key},
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


async def fetch_versions(services, tenant, skill_id):
    async with services.repository.engine.connect() as connection:
        rows = (
            (
                await connection.execute(
                    text(
                        "SELECT version,semver,release_kind,definition,"
                        "definition_digest,rollback_from "
                        "FROM skill_versions "
                        "WHERE tenant_id=:tenant AND skill_id=CAST(:skill AS uuid) "
                        "ORDER BY version"
                    ),
                    {"tenant": tenant, "skill": skill_id},
                )
            )
            .mappings()
            .all()
        )
    return [dict(row) for row in rows]


async def count_skill_test_runs(services, tenant, skill_id):
    async with services.repository.engine.connect() as connection:
        count = (
            await connection.execute(
                text(
                    "SELECT count(*) n FROM skill_test_runs "
                    "WHERE tenant_id=:tenant AND skill_id=CAST(:skill AS uuid)"
                ),
                {"tenant": tenant, "skill": skill_id},
            )
        ).scalar_one()
    return count


async def count_audit_actions(services, tenant, action):
    async with services.repository.engine.connect() as connection:
        count = (
            await connection.execute(
                text(
                    "SELECT count(*) n FROM audit_records "
                    "WHERE tenant_id=:tenant AND action=:action"
                ),
                {"tenant": tenant, "action": action},
            )
        ).scalar_one()
    return count


class ToolRegistryProbe:
    """Record dependency resolution/credential access for blocked test paths."""

    def __init__(self, inner):
        self.inner = inner
        self.resolve_calls = 0
        self.credential_calls = 0

    async def resolve(self, *args, **kwargs):
        self.resolve_calls += 1
        return await self.inner.resolve(*args, **kwargs)

    def credential_headers(self, *args, **kwargs):
        self.credential_calls += 1
        return self.inner.credential_headers(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.inner, name)


class OutboundClientProbe:
    """Fail if a blocked path ever tries to leave the process via a tool call."""

    def __init__(self):
        self.calls = []

    def _record(self, method, url):
        self.calls.append((method, str(url)))
        raise AssertionError(f"unexpected outbound tool call: {method} {url}")

    def stream(self, method, url, *args, **kwargs):
        self._record(method, url)

    async def request(self, method, url, *args, **kwargs):
        self._record(method, url)

    async def send(self, request, *args, **kwargs):
        self._record(request.method, request.url)

    async def get(self, url, *args, **kwargs):
        self._record("GET", url)

    async def post(self, url, *args, **kwargs):
        self._record("POST", url)

    async def put(self, url, *args, **kwargs):
        self._record("PUT", url)

    async def patch(self, url, *args, **kwargs):
        self._record("PATCH", url)

    async def delete(self, url, *args, **kwargs):
        self._record("DELETE", url)


def field_paths_from_validation_detail(detail):
    """Return loc/field paths from either FastAPI or domain-shaped 422 details."""

    if isinstance(detail, list):
        return [
            list(item.get("loc", ())) + ([item["field"]] if item.get("field") else [])
            for item in detail
            if isinstance(item, dict)
        ]
    if isinstance(detail, dict):
        for key in ("errors", "checks", "fields"):
            nested = detail.get(key)
            if isinstance(nested, list):
                return field_paths_from_validation_detail(nested)
        if detail.get("field"):
            return [[detail["field"]]]
        if detail.get("check"):
            return [[detail["check"]]]
    return []


async def test_catalog_create_incomplete_save_and_permissions(skill_platform):
    client, _, settings = skill_platform
    created = await create_professional(client)
    assert created["key"].startswith("incomplete-draft")
    assert created["draft_revision"] == 1
    assert created["definition"]["schema_version"] == "v1"

    catalog = (await client.get("/api/v1/skills")).json()
    assert catalog["total"] == 1
    assert catalog["page"] == 1
    assert catalog["status_facets"][0] == {"value": "draft", "count": 1}

    saved_body = {
        "revision": 1,
        "name": "Incomplete draft renamed",
        "description": "Still missing a model profile",
        "category": "service",
        "tags": ["draft"],
        "visibility": "workspace",
        "definition": created["definition"],
    }
    saved = await client.put(f"/api/v1/skills/{created['key']}/draft", json=saved_body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["draft_revision"] == 2
    assert saved.json()["definition"]["dependencies"]["model_profile_id"] is None
    conflict = await client.put(f"/api/v1/skills/{created['key']}/draft", json=saved_body)
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "skill_revision_conflict"

    viewer = {"Authorization": "Bearer platform-viewer"}
    operator = {"Authorization": "Bearer platform-operator"}
    assert (await client.get("/api/v1/skills", headers=viewer)).status_code == 200
    assert (
        await client.post(
            "/api/v1/skills",
            headers=viewer,
            json={"mode": "professional", "prompt": None, "template_key": None, "definition": None},
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/skills/{created['key']}/test-runs",
            headers=operator,
            json={
                "draft_revision": 2,
                "input": {"text": "hello"},
                "scenario": "",
                "client_request_id": str(uuid4()),
            },
        )
    ).status_code == 422

    with pytest.raises(DomainError):
        await skill_platform[1].groups.business.skill_library.get(
            "other-tenant",
            created["key"],
            scope=None,
        )
    assert settings.skill_live_tool_tests_enabled is False


async def test_test_idempotency_and_release_rollback_chain(skill_platform):
    client, services, settings = skill_platform
    skill = await create_handoff(client)
    request_id = str(uuid4())
    run = await run_handoff_test(client, skill, request_id)
    assert run["status"] == "passed"
    assert run["execution_kind"] == "contract"
    repeated = await run_handoff_test(client, skill, request_id)
    assert repeated["id"] == run["id"]
    history = (await client.get(f"/api/v1/skills/{skill['key']}/test-runs")).json()
    assert history["total"] == 1
    assert history["items"][0]["input_summary"].startswith('{"reason"')

    readiness = (await client.get(f"/api/v1/skills/{skill['key']}/readiness")).json()
    assert readiness["ready"] is True
    assert readiness["next_semver"] == "1.0.0"
    first = await client.post(
        f"/api/v1/skills/{skill['key']}/publish",
        json={"revision": 1, "bump": "minor", "release_notes": "Initial release"},
    )
    assert first.status_code == 200, first.text
    version_one = first.json()
    assert version_one["version"] == 1
    assert version_one["semver"] == "1.0.0"
    assert version_one["release_kind"] == "initial"
    assert version_one["test_run_id"] == run["id"]
    repeat = await client.post(
        f"/api/v1/skills/{skill['key']}/publish",
        json={"revision": 1, "bump": "minor", "release_notes": "Duplicate"},
    )
    assert repeat.status_code == 409

    updated = await save_handoff_draft(client, skill, "Escalate with a short reason.")
    run_two = await run_handoff_test(client, updated, str(uuid4()))
    assert run_two["draft_revision"] == 2
    second = await client.post(
        f"/api/v1/skills/{skill['key']}/publish",
        json={"revision": 2, "bump": "patch", "release_notes": "Clarify instructions"},
    )
    assert second.status_code == 200, second.text
    version_two = second.json()
    assert version_two["version"] == 2 and version_two["semver"] == "1.0.1"
    history_versions = (await client.get(f"/api/v1/skills/{skill['key']}/versions")).json()
    assert [item["version"] for item in history_versions["items"]] == [2, 1]

    rolled_back = await client.post(
        f"/api/v1/skills/{skill['key']}/rollback",
        json={"revision": 2, "target_version": 1, "release_notes": "Return to initial"},
    )
    assert rolled_back.status_code == 200, rolled_back.text
    version_three = rolled_back.json()
    assert version_three["version"] == 3
    assert version_three["semver"] == "1.0.2"
    assert version_three["release_kind"] == "rollback"
    assert version_three["rollback_from"] == 1
    assert version_three["definition"] == version_one["definition"]
    assert version_three["definition_digest"] == version_one["definition_digest"]
    assert version_three["test_run_id"] is None
    detail = (await client.get(f"/api/v1/skills/{skill['key']}")).json()
    assert detail["published_version"] == 3
    assert detail["has_unpublished_changes"] is True

    async with services.repository.engine.connect() as connection:
        audit_rows = (
            (
                await connection.execute(
                    text(
                        "SELECT action,details FROM audit_records "
                        "WHERE tenant_id=:tenant AND action LIKE 'skill.%'"
                    ),
                    {"tenant": settings.tenant_id},
                )
            )
            .mappings()
            .all()
        )
    assert any(row["action"] == "skill.published" for row in audit_rows)
    serialized = json.dumps([dict(row) for row in audit_rows])
    assert "Customer requested a human" not in serialized


async def test_instruction_failure_invalidates_readiness(skill_platform):
    client, _, _ = skill_platform
    from test_model_gateway import setup

    _, _, profile = await setup(client, "chat")
    body = {
        "mode": "professional",
        "prompt": None,
        "template_key": None,
        "definition": {
            **empty_definition(),
            "instructions": "Return the extracted object.",
            "parameters": [
                {
                    "name": "text",
                    "type": "string",
                    "required": True,
                    "default": None,
                    "description": "",
                }
            ],
            "output": {
                "format": "json",
                "schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
            "dependencies": {
                "model_profile_id": profile["id"],
                "model_profile_version": 1,
                "knowledge_base_ids": [],
                "tool_names": [],
                "handoff_queue": None,
            },
        },
    }
    response = await client.post("/api/v1/skills", json=body)
    assert response.status_code == 201, response.text
    skill = response.json()
    failed = await client.post(
        f"/api/v1/skills/{skill['key']}/test-runs",
        json={
            "draft_revision": 1,
            "input": {"text": "Name: Li Wei"},
            "scenario": "json contract",
            "client_request_id": str(uuid4()),
        },
    )
    assert failed.status_code == 201, failed.text
    assert failed.json()["status"] == "failed"
    readiness = (await client.get(f"/api/v1/skills/{skill['key']}/readiness")).json()
    assert readiness["ready"] is False
    check = next(item for item in readiness["checks"] if item["code"] == "latest_test_passed")
    assert check["status"] == "fail"


async def test_p2_ut_14_write_action_live_test_blocked_with_no_outbound_call(
    skill_platform,
    monkeypatch,
):
    """P2-UT-14: write actions stay blocked and never resolve/call a live tool."""

    client, services, settings = skill_platform
    definition = make_definition(
        definition_type="action",
        instructions="Create a customer ticket.",
        dependencies={"tool_names": ["write_ticket"]},
        runtime={"confirmation_required": True},
    )
    skill = await create_with_definition(client, definition)
    service = services.groups.business.skill_library

    tool_probe = ToolRegistryProbe(service.executor.tools)
    outbound_probe = OutboundClientProbe()
    with monkeypatch.context() as scoped:
        scoped.setattr(service, "tools", tool_probe)
        scoped.setattr(service.executor, "tools", tool_probe)
        scoped.setattr(service.executor.workspace, "client", outbound_probe)
        run = await run_skill_test(
            client,
            skill,
            {},
            request_id=str(uuid4()),
            scenario="write action",
        )

    assert run["status"] == "blocked"
    assert run["reason_code"] == "skill_write_test_unsafe"
    assert run["execution_kind"] == "live"
    assert run["diagnostics"] == {"policy": "write_action_tests_disabled"}
    assert tool_probe.resolve_calls == 0
    assert tool_probe.credential_calls == 0
    assert outbound_probe.calls == []

    async with services.repository.engine.connect() as connection:
        stored = (
            (
                await connection.execute(
                    text(
                        "SELECT status,execution_kind,reason_code,diagnostics "
                        "FROM skill_test_runs "
                        "WHERE tenant_id=:tenant AND skill_id=CAST(:skill AS uuid)"
                    ),
                    {"tenant": settings.tenant_id, "skill": skill["id"]},
                )
            )
            .mappings()
            .one()
        )
    assert stored["status"] == "blocked"
    assert stored["execution_kind"] == "live"
    assert stored["reason_code"] == "skill_write_test_unsafe"
    assert stored["diagnostics"] == {"policy": "write_action_tests_disabled"}

    blocked_publish = await client.post(
        f"/api/v1/skills/{skill['key']}/publish",
        json={
            "revision": 1,
            "bump": "minor",
            "release_notes": "Unsafe write test must not release.",
        },
    )
    assert blocked_publish.status_code == 409, blocked_publish.text
    assert blocked_publish.json()["detail"] == "skill_readiness_blocked"
    assert await fetch_versions(services, settings.tenant_id, skill["id"]) == []


async def test_p2_ut_19_readiness_missing_model_blocks_publish(skill_platform):
    """P2-UT-19: missing model names the failed check/destination and blocks publish."""

    client, services, settings = skill_platform
    definition = make_definition(
        instructions="Answer customer questions.",
        dependencies={
            "model_profile_id": str(uuid4()),
            "model_profile_version": 1,
        },
    )
    skill = await create_with_definition(client, definition)

    readiness = (await client.get(f"/api/v1/skills/{skill['key']}/readiness")).json()
    dependency_check = next(
        check for check in readiness["checks"] if check["code"] == "dependencies_available"
    )
    assert readiness["ready"] is False
    assert dependency_check == {
        "code": "dependencies_available",
        "status": "fail",
        "reason": "Dependency unavailable: model_resource_not_found",
        "destination": "dependencies",
    }

    publish = await client.post(
        f"/api/v1/skills/{skill['key']}/publish",
        json={
            "revision": 1,
            "bump": "minor",
            "release_notes": "Must stay blocked.",
        },
    )
    assert publish.status_code == 409, publish.text
    assert publish.json()["detail"] == "skill_readiness_blocked"
    assert await fetch_versions(services, settings.tenant_id, skill["id"]) == []


async def test_p2_ut_19_readiness_missing_knowledge_base_blocks_publish(
    skill_platform,
):
    """P2-UT-19: missing KB reports the exact dependency reason and blocks publish."""

    client, services, settings = skill_platform
    definition = make_definition(
        definition_type="knowledge",
        dependencies={"knowledge_base_ids": [str(uuid4())]},
    )
    skill = await create_with_definition(client, definition)

    readiness = (await client.get(f"/api/v1/skills/{skill['key']}/readiness")).json()
    dependency_check = next(
        check for check in readiness["checks"] if check["code"] == "dependencies_available"
    )
    assert readiness["ready"] is False
    assert dependency_check == {
        "code": "dependencies_available",
        "status": "fail",
        "reason": "Dependency unavailable: knowledge_base_unavailable",
        "destination": "dependencies",
    }

    publish = await client.post(
        f"/api/v1/skills/{skill['key']}/publish",
        json={
            "revision": 1,
            "bump": "minor",
            "release_notes": "Must stay blocked.",
        },
    )
    assert publish.status_code == 409, publish.text
    assert publish.json()["detail"] == "skill_readiness_blocked"
    assert await fetch_versions(services, settings.tenant_id, skill["id"]) == []


async def test_p2_ut_19_readiness_disabled_model_blocks_publish(skill_platform):
    """P2-UT-19: disabled model reports model_resource_disabled and blocks publish."""

    client, services, settings = skill_platform
    from test_model_gateway import setup

    _, _, profile = await setup(client, "chat")
    definition = make_definition(
        instructions="Answer customer questions.",
        dependencies={
            "model_profile_id": profile["id"],
            "model_profile_version": 1,
        },
    )
    skill = await create_with_definition(client, definition)
    disabled = await client.patch(
        f"/api/v1/model-gateway/profiles/{profile['id']}",
        json={"revision": 1, "enabled": False},
    )
    assert disabled.status_code == 200, disabled.text

    readiness = (await client.get(f"/api/v1/skills/{skill['key']}/readiness")).json()
    dependency_check = next(
        check for check in readiness["checks"] if check["code"] == "dependencies_available"
    )
    assert readiness["ready"] is False
    assert dependency_check == {
        "code": "dependencies_available",
        "status": "fail",
        "reason": "Dependency unavailable: model_resource_disabled",
        "destination": "dependencies",
    }

    publish = await client.post(
        f"/api/v1/skills/{skill['key']}/publish",
        json={
            "revision": 1,
            "bump": "minor",
            "release_notes": "Must stay blocked.",
        },
    )
    assert publish.status_code == 409, publish.text
    assert publish.json()["detail"] == "skill_readiness_blocked"
    assert await fetch_versions(services, settings.tenant_id, skill["id"]) == []


async def test_p2_ut_19_readiness_missing_tool_blocks_publish(skill_platform):
    """P2-UT-19: missing tool reports its exact name and blocks publish."""

    client, services, settings = skill_platform
    from test_model_gateway import setup

    _, _, profile = await setup(client, "chat")
    definition = make_definition(
        instructions="Answer customer questions.",
        dependencies={
            "model_profile_id": profile["id"],
            "model_profile_version": 1,
            "tool_names": ["missing_tool"],
        },
    )
    skill = await create_with_definition(client, definition)

    readiness = (await client.get(f"/api/v1/skills/{skill['key']}/readiness")).json()
    dependency_check = next(
        check for check in readiness["checks"] if check["code"] == "dependencies_available"
    )
    assert readiness["ready"] is False
    assert dependency_check == {
        "code": "dependencies_available",
        "status": "fail",
        "reason": "Dependency unavailable: tool_unavailable:missing_tool",
        "destination": "dependencies",
    }

    publish = await client.post(
        f"/api/v1/skills/{skill['key']}/publish",
        json={
            "revision": 1,
            "bump": "minor",
            "release_notes": "Must stay blocked.",
        },
    )
    assert publish.status_code == 409, publish.text
    assert publish.json()["detail"] == "skill_readiness_blocked"
    assert await fetch_versions(services, settings.tenant_id, skill["id"]) == []


async def test_p2_it_09_invalid_definition_save_is_atomic_and_reports_field(
    skill_platform,
):
    """P2-IT-09: invalid definition is 422 with field detail and writes nothing."""

    client, services, settings = skill_platform
    skill = await create_professional(client)
    before = await fetch_skill_state(services, settings.tenant_id, skill["key"])
    secret_marker = "SECRET_PROMPT_MARKER"
    invalid_definition = {
        **skill["definition"],
        "type": "bogus",
        "instructions": secret_marker,
    }

    response = await client.put(
        f"/api/v1/skills/{skill['key']}/draft",
        json={
            "revision": 1,
            "name": skill["name"],
            "description": skill["description"],
            "category": skill["category"],
            "tags": skill["tags"],
            "visibility": "workspace",
            "definition": invalid_definition,
        },
    )

    duplicate_parameter = {
        **skill["definition"],
        "parameters": [
            {"name": secret_marker, "type": "string"},
            {"name": secret_marker, "type": "string"},
        ],
    }
    check_response = await client.put(
        f"/api/v1/skills/{skill['key']}/draft",
        json={
            "revision": 1,
            "name": skill["name"],
            "description": skill["description"],
            "category": skill["category"],
            "tags": skill["tags"],
            "visibility": "workspace",
            "definition": duplicate_parameter,
        },
    )
    after = await fetch_skill_state(services, settings.tenant_id, skill["key"])

    assert response.status_code == 422, response.text
    assert check_response.status_code == 422, check_response.text
    assert after["draft_revision"] == before["draft_revision"] == 1
    assert after["draft_definition"] == before["draft_definition"]
    assert await count_audit_actions(services, settings.tenant_id, "skill.draft_saved") == 0

    detail = response.json().get("detail")
    assert isinstance(detail, dict)
    assert detail["code"] == "skill_definition_invalid"
    assert isinstance(detail["errors"], list) and detail["errors"]
    assert all(set(error) == {"loc", "type", "msg"} for error in detail["errors"])
    paths = field_paths_from_validation_detail(detail)
    assert any("type" in [str(part) for part in path] for path in paths), detail
    assert detail["errors"][0]["loc"] == ["definition", "type"]
    assert detail["errors"][0]["type"] == "literal_error"

    check_detail = check_response.json().get("detail")
    assert isinstance(check_detail, dict)
    assert check_detail["code"] == "skill_definition_invalid"
    check_paths = field_paths_from_validation_detail(check_detail)
    assert ["definition"] in check_paths, check_detail
    assert check_detail["errors"][0]["type"] == "value_error"
    assert "parameter names must be unique" in check_detail["errors"][0]["msg"]
    assert secret_marker not in response.text
    assert secret_marker not in check_response.text


async def test_p2_it_16_invalid_publish_metadata_creates_no_version(
    skill_platform,
):
    """P2-IT-16: invalid notes/bump never creates a version or moves the pointer."""

    client, services, settings = skill_platform
    skill = await create_handoff(client)
    run = await run_handoff_test(client, skill, str(uuid4()))
    assert run["status"] == "passed"

    released = await client.post(
        f"/api/v1/skills/{skill['key']}/publish",
        json={"revision": 1, "bump": "minor", "release_notes": "Initial release"},
    )
    assert released.status_code == 200, released.text
    assert released.json()["version"] == 1

    before = await fetch_skill_state(services, settings.tenant_id, skill["key"])
    versions_before = await fetch_versions(services, settings.tenant_id, skill["id"])
    assert before["published_version"] == 1
    assert before["published_revision"] == 1
    assert len(versions_before) == 1

    invalid_notes = await client.post(
        f"/api/v1/skills/{skill['key']}/publish",
        json={"revision": 1, "bump": "patch", "release_notes": ""},
    )
    invalid_bump = await client.post(
        f"/api/v1/skills/{skill['key']}/publish",
        json={
            "revision": 1,
            "bump": "banana",
            "release_notes": "Invalid bump must be rejected.",
        },
    )

    after = await fetch_skill_state(services, settings.tenant_id, skill["key"])
    versions_after = await fetch_versions(services, settings.tenant_id, skill["id"])
    assert invalid_notes.status_code == 422, invalid_notes.text
    assert invalid_bump.status_code == 422, invalid_bump.text
    assert after["published_version"] == before["published_version"] == 1
    assert after["published_revision"] == before["published_revision"] == 1
    assert versions_after == versions_before
    assert await count_audit_actions(services, settings.tenant_id, "skill.published") == 1

    for response, field in ((invalid_notes, "release_notes"), (invalid_bump, "bump")):
        paths = field_paths_from_validation_detail(response.json()["detail"])
        assert any(field in [str(part) for part in path] for path in paths), response.text


async def test_p2_it_20_rollback_dependency_failure_leaves_pointer_and_history(
    skill_platform,
):
    """P2-IT-20: unavailable rollback dependency adds no row and moves nothing."""

    client, services, settings = skill_platform
    from test_model_gateway import setup

    _, _, profile = await setup(client, "chat")
    definition = make_definition(
        instructions="Answer the customer politely.",
        dependencies={
            "model_profile_id": profile["id"],
            "model_profile_version": 1,
        },
    )
    skill = await create_with_definition(client, definition)
    first_run = await run_skill_test(client, skill, {})
    assert first_run["status"] == "passed"

    first = await client.post(
        f"/api/v1/skills/{skill['key']}/publish",
        json={"revision": 1, "bump": "minor", "release_notes": "Initial release"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1

    updated = await save_definition(
        client,
        skill,
        {
            **definition,
            "instructions": "Answer the customer in one sentence.",
        },
    )
    assert updated["draft_revision"] == 2
    second_run = await run_skill_test(client, updated, {})
    assert second_run["status"] == "passed"
    second = await client.post(
        f"/api/v1/skills/{skill['key']}/publish",
        json={
            "revision": 2,
            "bump": "patch",
            "release_notes": "Clarify the instruction.",
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["version"] == 2

    before = await fetch_skill_state(services, settings.tenant_id, skill["key"])
    versions_before = await fetch_versions(services, settings.tenant_id, skill["id"])
    assert [row["version"] for row in versions_before] == [1, 2]
    assert before["published_version"] == 2
    assert before["published_revision"] == 2

    disabled = await client.patch(
        f"/api/v1/model-gateway/profiles/{profile['id']}",
        json={"revision": 1, "enabled": False},
    )
    assert disabled.status_code == 200, disabled.text

    rollback = await client.post(
        f"/api/v1/skills/{skill['key']}/rollback",
        json={
            "revision": 2,
            "target_version": 1,
            "release_notes": "Return to the initial release.",
        },
    )
    assert rollback.status_code == 409, rollback.text
    assert rollback.json()["detail"] == "skill_dependency_unavailable"

    after = await fetch_skill_state(services, settings.tenant_id, skill["key"])
    versions_after = await fetch_versions(services, settings.tenant_id, skill["id"])
    assert versions_after == versions_before
    assert after["published_version"] == 2
    assert after["published_revision"] == 2
    assert await count_audit_actions(services, settings.tenant_id, "skill.rolled_back") == 0


async def test_p2_it_18_concurrent_publish_creates_single_version(skill_platform):
    """P2-IT-18: two concurrent publishes yield one success and one conflict."""

    client, services, settings = skill_platform
    skill = await create_handoff(client)
    run = await run_handoff_test(client, skill, str(uuid4()))
    assert run["status"] == "passed"

    payload = {
        "revision": 1,
        "bump": "minor",
        "release_notes": "Concurrent release.",
    }
    responses = await asyncio.gather(
        client.post(f"/api/v1/skills/{skill['key']}/publish", json=payload),
        client.post(f"/api/v1/skills/{skill['key']}/publish", json=payload),
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    success = next(response for response in responses if response.status_code == 200)
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["detail"] == "skill_publish_in_progress"
    assert success.json()["version"] == 1
    assert success.json()["semver"] == "1.0.0"

    versions = await fetch_versions(services, settings.tenant_id, skill["id"])
    assert len(versions) == 1
    state = await fetch_skill_state(services, settings.tenant_id, skill["key"])
    assert state["published_version"] == 1
    assert state["published_revision"] == 1
    assert await count_audit_actions(services, settings.tenant_id, "skill.published") == 1


async def test_p2_ut_13_model_transport_errors_classify_as_error(
    skill_platform,
    monkeypatch,
):
    """P2-UT-13: model transport failures persist as error with stable reasons."""

    client, services, settings = skill_platform
    definition = make_definition(
        instructions="Answer the customer.",
        dependencies={
            "model_profile_id": str(uuid4()),
            "model_profile_version": 1,
        },
    )
    skill = await create_with_definition(client, definition)
    service = services.groups.business.skill_library
    failures = [
        DomainError("model_credentials_unavailable", 502),
        DomainError("model_backend_unavailable", 502),
        TimeoutError(),
    ]

    async def failing_invoke(*args, **kwargs):
        raise failures.pop(0)

    with monkeypatch.context() as scoped:
        scoped.setattr(service.executor.gateway, "invoke", failing_invoke)
        credentials = await run_skill_test(client, skill, {})
        backend = await run_skill_test(client, skill, {})
        timeout = await run_skill_test(client, skill, {})

    assert credentials["status"] == "error"
    assert credentials["reason_code"] == "model_credentials_unavailable"
    assert backend["status"] == "error"
    assert backend["reason_code"] == "model_backend_unavailable"
    assert timeout["status"] == "error"
    assert timeout["reason_code"] == "skill_test_timeout"
    assert all(run["execution_kind"] == "live" for run in (credentials, backend, timeout))
    assert await count_skill_test_runs(services, settings.tenant_id, skill["id"]) == 3


async def test_p2_ut_25_ai_generated_unsafe_definition_fields_are_rejected(
    skill_platform,
    monkeypatch,
):
    """P2-UT-25: generated escalation/secret fields are rejected, not stored."""

    client, services, settings = skill_platform
    service = services.groups.business.skill_library
    generated_definition = {
        **make_definition(instructions="Handle the customer request."),
        "creation_mode": "ai",
        "permissions": ["admin"],
        "endpoint": "https://unsafe.example/v1",
        "credential": "sk-live-secret",
    }
    generated = {
        "name": "Unsafe generated skill",
        "description": "",
        "category": "general",
        "tags": [],
        "definition": generated_definition,
    }

    class FakeGateway:
        async def invoke(self, *args, **kwargs):
            return {"payload": {"content": json.dumps(generated)}}

    with monkeypatch.context() as scoped:
        scoped.setattr(settings, "skill_ai_generation_enabled", True)
        scoped.setattr(settings, "skill_ai_profile_id", uuid4())
        scoped.setattr(settings, "skill_ai_profile_version", 1)
        scoped.setattr(service, "gateway", FakeGateway())
        response = await client.post(
            "/api/v1/skills",
            json={
                "mode": "ai",
                "prompt": "Make a skill",
                "template_key": None,
                "definition": None,
            },
        )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "skill_definition_invalid"
    assert "sk-live-secret" not in response.text
    assert "unsafe.example" not in response.text
    async with services.repository.engine.connect() as connection:
        count = (
            await connection.execute(
                text("SELECT count(*) n FROM skills WHERE tenant_id=:tenant"),
                {"tenant": settings.tenant_id},
            )
        ).scalar_one()
    assert count == 0


async def test_classification_is_derived_and_relabellable(skill_platform):
    client, _, _ = skill_platform
    money = make_definition(
        definition_type="action",
        instructions="Issue a refund",
        dependencies={"tool_names": ["refund_order"]},
        runtime={"confirmation_required": True, "max_amount": 12_000},
    )
    created = await create_with_definition(client, money)
    assert created["weight_class"] == "declarative"
    assert created["risk_computed"] == "r3"
    assert created["risk_level"] == "r3"
    assert created["data_scope"] == ["tool", "money"]
    assert {
        "type_action",
        "tool_capability",
        "money_action",
        "large_amount",
    } <= {reason["code"] for reason in created["risk_reasons"]}

    # The label belongs to the author: lowering it is allowed and changes
    # nothing about execution. The computed baseline still travels with it.
    relabelled = await client.put(
        f"/api/v1/skills/{created['key']}/draft",
        json={
            "revision": created["draft_revision"],
            "name": created["name"],
            "description": created["description"],
            "category": created["category"],
            "tags": [],
            "visibility": "workspace",
            "risk_level": "r1",
            "definition": created["definition"],
        },
    )
    assert relabelled.status_code == 200, relabelled.text
    body = relabelled.json()
    assert body["risk_level"] == "r1"
    assert body["risk_computed"] == "r3"


async def test_catalog_filters_by_risk_and_weight(skill_platform):
    client, _, _ = skill_platform
    low = await create_with_definition(client, make_definition(instructions="Say hello"))
    high = await create_with_definition(
        client,
        make_definition(
            definition_type="action",
            instructions="Refund an order",
            dependencies={"tool_names": ["refund_order"]},
            runtime={"confirmation_required": True, "max_amount": 50},
        ),
    )
    assert (low["risk_level"], high["risk_level"]) == ("r0", "r2")

    by_risk = (await client.get("/api/v1/skills", params={"risk": "r2"})).json()
    assert [item["key"] for item in by_risk["items"]] == [high["key"]]
    assert by_risk["total"] == 1
    assert {row["value"] for row in by_risk["risk_facets"]} == {"r0", "r2"}
    assert by_risk["weight_facets"] == [{"value": "declarative", "count": 1}]

    by_weight = (await client.get("/api/v1/skills", params={"weight": "declarative"})).json()
    assert by_weight["total"] == 2
    assert (await client.get("/api/v1/skills", params={"weight": "executable"})).json()["total"] == 0


class FakeSkillArchive:
    """In-memory stand-in for S3. Keeps the package tests off the network."""

    objects: ClassVar[dict[str, bytes]] = {}

    def __init__(self, settings, profile="knowledge"):
        self.profile = profile

    def configured(self):
        return True

    async def put(self, key, content, content_type="application/octet-stream"):
        FakeSkillArchive.objects[key] = content
        return {"bucket": "fake", "key": key}

    async def get(self, key):
        return FakeSkillArchive.objects[key]

    async def delete(self, key):
        FakeSkillArchive.objects.pop(key, None)


@pytest.fixture
def package_storage(monkeypatch):
    from agent_platform.business_capabilities.skill_library import service as service_module

    FakeSkillArchive.objects.clear()
    monkeypatch.setattr(service_module, "S3Archive", FakeSkillArchive)
    return FakeSkillArchive


def build_package(entries: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


DECLARATIVE_PACKAGE = build_package(
    {
        "order-skill/SKILL.md": (
            b"---\nname: order-status\ndescription: Answer order status questions.\n---\n\n"
            b"Look the order up.\n"
        ),
        "order-skill/references/faq.md": b"# FAQ\n",
    }
)

EXECUTABLE_PACKAGE = build_package(
    {
        "SKILL.md": (
            b"---\nname: order-status\ndescription: Answer order status questions.\n"
            b"entrypoint: scripts/main.py\n---\n\nLook the order up.\n"
        ),
        "scripts/main.py": b"print('lookup')\n",
    }
)


async def upload_package(client, key, content, filename="skill.zip"):
    return await client.post(
        f"/api/v1/skills/{key}/package",
        params={"filename": filename},
        content=content,
        headers={"content-type": "application/zip"},
    )


async def test_package_upload_binds_and_classifies(skill_platform, package_storage):
    client, _, _ = skill_platform
    skill = await create_professional(client, "Look up an order")

    response = await upload_package(client, skill["key"], DECLARATIVE_PACKAGE)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["weight_class"] == "packaged"
    assert body["draft_revision"] == skill["draft_revision"] + 1
    assert body["package"]["file_count"] == 2
    assert body["package"]["has_scripts"] is False
    # The name the operator supplied is echoed back, so the card can show it.
    assert body["package"]["filename"] == "skill.zip"
    assert body["package"]["digest"].startswith("sha256:")
    assert len(package_storage.objects) == 1

    listing = (await client.get("/api/v1/skills", params={"weight": "packaged"})).json()
    assert [item["key"] for item in listing["items"]] == [skill["key"]]


async def test_package_filename_is_reduced_to_a_label(skill_platform, package_storage):
    client, _, _ = skill_platform
    skill = await create_professional(client, "Look up an order")

    # Some browsers send a full path. The label must not carry the directories,
    # and it must not fail after the bytes already reached object storage.
    body = (
        await upload_package(
            client,
            skill["key"],
            DECLARATIVE_PACKAGE,
            filename="C:\\Users\\ops\\lookup skill.zip",
        )
    ).json()

    assert body["package"]["filename"] == "lookup skill.zip"


async def test_executable_package_is_flagged_not_blocked(skill_platform, package_storage):
    client, _, _ = skill_platform
    skill = await create_professional(client, "Run the lookup script")

    body = (await upload_package(client, skill["key"], EXECUTABLE_PACKAGE)).json()

    assert body["weight_class"] == "executable"
    assert body["package"]["has_scripts"] is True
    assert body["package"]["entrypoint"] == "scripts/main.py"
    # Code is a data plane, so it shows up in the derived scope.
    assert "code" in body["data_scope"]


async def test_saving_a_draft_keeps_the_artefact_weight(skill_platform, package_storage):
    client, _, _ = skill_platform
    skill = await create_professional(client, "Run the lookup script")
    uploaded = (await upload_package(client, skill["key"], EXECUTABLE_PACKAGE)).json()
    assert uploaded["weight_class"] == "executable"

    saved = await save_handoff_draft(client, uploaded, "Run the lookup script, revised")
    # The form does not carry weight; the attached package still decides it.
    assert saved["weight_class"] == "executable"
    assert saved["package"]["has_scripts"] is True


async def test_replacing_a_package_leaves_one_row_and_one_object(
    skill_platform, package_storage
):
    client, services, settings = skill_platform
    skill = await create_professional(client, "Look up an order")
    await upload_package(client, skill["key"], DECLARATIVE_PACKAGE)
    second = (await upload_package(client, skill["key"], EXECUTABLE_PACKAGE)).json()

    assert second["weight_class"] == "executable"
    async with services.repository.engine.begin() as connection:
        rows = await connection.execute(
            text("SELECT count(*) FROM skill_packages WHERE tenant_id=:tenant"),
            {"tenant": settings.tenant_id},
        )
        assert rows.scalar() == 1
    assert len(package_storage.objects) == 1


async def test_package_manifest_endpoint_and_detach(skill_platform, package_storage):
    client, _, _ = skill_platform
    skill = await create_professional(client, "Look up an order")
    await upload_package(client, skill["key"], DECLARATIVE_PACKAGE)

    manifest = await client.get(f"/api/v1/skills/{skill['key']}/package")
    assert manifest.status_code == 200, manifest.text
    payload = manifest.json()
    assert [item["path"] for item in payload["manifest"]["files"]] == [
        "SKILL.md",
        "references/faq.md",
    ]
    assert payload["manifest"]["skill"]["name"] == "order-status"
    assert payload["filename"] == "skill.zip"

    detached = await client.delete(f"/api/v1/skills/{skill['key']}/package")
    assert detached.status_code == 200, detached.text
    assert detached.json()["package"] is None
    assert detached.json()["weight_class"] == "declarative"
    assert package_storage.objects == {}
    assert (await client.get(f"/api/v1/skills/{skill['key']}/package")).status_code == 404


async def test_rejected_packages_store_nothing(skill_platform, package_storage):
    client, _, _ = skill_platform
    skill = await create_professional(client, "Look up an order")

    traversing = build_package({"SKILL.md": b"---\nname: x\ndescription: y\n---\n", "../x.txt": b"1"})
    assert (await upload_package(client, skill["key"], traversing)).status_code == 422
    assert (await upload_package(client, skill["key"], b"not a zip")).status_code == 415
    assert (await upload_package(client, skill["key"], b"")).status_code == 422

    assert package_storage.objects == {}
    refreshed = (await client.get(f"/api/v1/skills/{skill['key']}")).json()
    assert refreshed["package"] is None
    assert refreshed["draft_revision"] == skill["draft_revision"]


async def import_package(client, content: bytes, filename="order-skill.zip"):
    return await client.post(
        "/api/v1/skills/import",
        params={"filename": filename},
        content=content,
        headers={"content-type": "application/zip"},
    )


async def test_import_creates_skill_from_the_archive(skill_platform, package_storage):
    client, _, _ = skill_platform

    response = await import_package(client, EXECUTABLE_PACKAGE)
    assert response.status_code == 201, response.text
    body = response.json()

    # Everything the caller did not type comes from SKILL.md.
    assert body["key"] == "order-status"
    assert body["name"] == "order-status"
    assert body["description"] == "Answer order status questions."
    assert body["definition"]["creation_mode"] == "package"
    assert body["definition"]["type"] == "instruction"
    assert body["definition"]["instructions"] == "Look the order up."
    # One creation event: the draft starts at revision 1, not 2.
    assert body["draft_revision"] == 1
    assert body["status"] == "draft"

    # The package is bound and re-tiers the Skill without any second call.
    assert body["weight_class"] == "executable"
    assert "code" in body["data_scope"]
    assert body["package"]["filename"] == "order-skill.zip"
    assert body["package"]["has_scripts"] is True
    assert body["package"]["entrypoint"] == "scripts/main.py"
    assert body["package"]["digest"].startswith("sha256:")
    assert len(package_storage.objects) == 1

    listed = (await client.get("/api/v1/skills")).json()
    assert listed["total"] == 1
    assert listed["items"][0]["key"] == "order-status"

    package = await client.get("/api/v1/skills/order-status/package")
    assert package.status_code == 200, package.text
    assert [item["path"] for item in package.json()["manifest"]["files"]] == [
        "SKILL.md",
        "scripts/main.py",
    ]


async def test_import_suffixes_a_taken_key_instead_of_failing(skill_platform, package_storage):
    client, _, _ = skill_platform

    first = await import_package(client, DECLARATIVE_PACKAGE)
    assert first.status_code == 201, first.text
    second = await import_package(client, DECLARATIVE_PACKAGE)
    assert second.status_code == 201, second.text

    assert first.json()["key"] == "order-status"
    assert second.json()["key"] == "order-status-2"
    assert (await client.get("/api/v1/skills")).json()["total"] == 2


async def test_import_rejection_creates_nothing(skill_platform, package_storage):
    client, _, _ = skill_platform

    missing = await import_package(client, build_package({"notes.md": b"# no manifest\n"}))
    assert missing.status_code == 422
    assert missing.json()["detail"] == "skill_package_missing_manifest"

    assert (await import_package(client, b"not a zip")).status_code == 415

    # A rejected archive must not leave a half-created Skill behind.
    assert (await client.get("/api/v1/skills")).json()["total"] == 0
    assert package_storage.objects == {}


async def test_import_refuses_to_truncate_long_instructions(skill_platform, package_storage):
    client, _, _ = skill_platform
    body = b"# " + b"x" * 25_000 + b"\n"

    response = await import_package(client, build_package({"SKILL.md": body}))
    assert response.status_code == 422
    assert response.json()["detail"] == "skill_package_instructions_too_long"
    assert package_storage.objects == {}


async def test_catalog_overview_reports_usage_and_rating(skill_platform):
    """Headline numbers must be derived from recorded behaviour, not stored."""

    client, services, _ = skill_platform
    created = await create_professional(client)

    async with services.repository.engine.begin() as connection:
        scope = (
            await connection.execute(
                text(
                    "SELECT tenant_id,business_id,workspace_id FROM skills WHERE id=:id"
                ),
                {"id": created["id"]},
            )
        ).mappings().one()
        scope_params = {
            "tenant": scope["tenant_id"],
            "business": scope["business_id"],
            "workspace": scope["workspace_id"],
        }
        for offset, runs in ((0, 100), (1, 50)):
            await connection.execute(
                text(
                    """
                    INSERT INTO skill_usage_daily(
                        tenant_id,business_id,workspace_id,skill_id,day,runs,succeeded
                    ) VALUES(
                        :tenant,:business,:workspace,:skill,:day,:runs,:ok
                    )
                    """
                ),
                {
                    **scope_params,
                    "skill": created["id"],
                    "day": datetime.now(tz=UTC).date() - timedelta(days=offset),
                    "runs": runs,
                    "ok": runs - 5,
                },
            )
        for rater, score in (("r1", 5), ("r2", 4)):
            await connection.execute(
                text(
                    """
                    INSERT INTO skill_ratings(
                        id,tenant_id,business_id,workspace_id,skill_id,rater,score
                    ) VALUES(
                        :id,:tenant,:business,:workspace,:skill,:rater,:score
                    )
                    """
                ),
                {
                    **scope_params,
                    "id": str(uuid4()),
                    "skill": created["id"],
                    "rater": rater,
                    "score": score,
                },
            )

    catalog = (await client.get("/api/v1/skills")).json()
    item = catalog["items"][0]
    assert item["usage_count"] == 150
    assert item["rating_count"] == 2
    assert item["rating_avg"] == 4.5
    assert item["success_rate"] == round(140 / 150, 4)

    overview = (await client.get("/api/v1/skills/overview")).json()
    assert overview["stats"]["total"]["value"] == 1
    assert overview["stats"]["in_use"]["value"] == 1
    assert overview["stats"]["rating"]["value"] == 4.5
    # No comparable prior window exists, so the trend must be absent rather
    # than reported as a flat zero.
    assert overview["stats"]["total"]["change"] is None
    assert len(overview["popular"]) == 1
    assert overview["popular"][0]["key"] == created["key"]
    assert overview["popular"][0]["runs"] == 150
    assert overview["popular"][0]["success_rate"] == round(140 / 150, 4)

    viewer = {"Authorization": "Bearer platform-viewer"}
    assert (await client.get("/api/v1/skills/overview", headers=viewer)).status_code == 200


async def test_catalog_pagination_and_server_side_sort(skill_platform):
    """The catalogue pages in SQL, so it must also order in SQL.

    Sorting only the rows of one page would reorder that page and leave the
    sequence across pages wrong, so pagination and ordering are asserted
    together. The three Skills are named and aged so that newest-first,
    alphabetical and most-used each put a *different* Skill first -- otherwise
    a single order could satisfy all three assertions by accident.
    """

    client, services, _ = skill_platform
    alpha = await create_professional(client, "Alpha skill")
    bravo = await create_professional(client, "Bravo skill")
    charlie = await create_professional(client, "Charlie skill")

    async with services.repository.engine.begin() as connection:
        # bravo is the most recent, alpha the oldest; charlie sits in between.
        for skill, age_days in ((alpha, 3), (charlie, 2), (bravo, 1)):
            await connection.execute(
                text(
                    "UPDATE skills SET updated_at=now()-make_interval(days=>:days) "
                    "WHERE id=:id"
                ),
                {"id": skill["id"], "days": age_days},
            )
        scope = (
            await connection.execute(
                text(
                    "SELECT tenant_id,business_id,workspace_id FROM skills WHERE id=:id"
                ),
                {"id": charlie["id"]},
            )
        ).mappings().one()
        # charlie is the most used even though it is neither newest nor first
        # alphabetically.
        await connection.execute(
            text(
                """
                INSERT INTO skill_usage_daily(
                    tenant_id,business_id,workspace_id,skill_id,day,runs,succeeded
                ) VALUES(:tenant,:business,:workspace,:skill,:day,:runs,:ok)
                """
            ),
            {
                "tenant": scope["tenant_id"],
                "business": scope["business_id"],
                "workspace": scope["workspace_id"],
                "skill": charlie["id"],
                "day": datetime.now(tz=UTC).date(),
                "runs": 900,
                "ok": 900,
            },
        )

    first = (await client.get("/api/v1/skills?page=1&page_size=2")).json()
    second = (await client.get("/api/v1/skills?page=2&page_size=2")).json()
    assert first["total"] == 3
    assert first["page"] == 1
    assert first["page_size"] == 2
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    # Pages partition the result: no row appears twice, none is dropped.
    keys = [item["key"] for item in first["items"] + second["items"]]
    assert sorted(keys) == sorted([alpha["key"], bravo["key"], charlie["key"]])
    assert len(set(keys)) == 3

    by_name = (await client.get("/api/v1/skills?sort=name&page_size=100")).json()
    assert [item["key"] for item in by_name["items"]] == [
        alpha["key"],
        bravo["key"],
        charlie["key"],
    ]

    by_latest = (await client.get("/api/v1/skills?sort=latest&page_size=100")).json()
    assert [item["key"] for item in by_latest["items"]] == [
        bravo["key"],
        charlie["key"],
        alpha["key"],
    ]

    by_usage = (await client.get("/api/v1/skills?sort=usage&page_size=100")).json()
    assert by_usage["items"][0]["key"] == charlie["key"]
    assert by_usage["items"][0]["usage_count"] == 900

    # An unknown key is a stale client, not a client error: fall back to the
    # default order instead of failing the whole list.
    fallback = await client.get("/api/v1/skills?sort=not_a_sort&page_size=100")
    assert fallback.status_code == 200
    assert [item["key"] for item in fallback.json()["items"]] == [
        bravo["key"],
        charlie["key"],
        alpha["key"],
    ]
