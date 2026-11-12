"""Seed the isolated Phase 2 orchestrator examples without runtime side effects."""

import asyncio
import json
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from agent_platform.applications.customer_service.runtime_composition import runtime_services
from agent_platform.business_capabilities.agent_config.service import AgentConfig, AgentDraft
from agent_platform.business_capabilities.open_platform.service import ApplicationInput
from agent_platform.core_platform.platform_services.model_gateway.contracts import (
    Connection,
    Model,
    Profile,
)
from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    execute,
    one,
)
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings
from agent_platform.core_platform.platform_services.tenant_isolation.service import (
    resource_scope_values,
)

BATCH = "execution-orchestrator-phase2-v1"
ACTOR = "seed-execution-orchestrator"
PUBLISHED_EXTERNAL_ID = "phase2-orchestrator-published"
LEGACY_EXTERNAL_ID = "phase2-orchestrator-legacy"
DISPLAY_PREFIX = "[Phase 2 Orchestrator]"
COUNT_KEYS = (
    "connections",
    "models",
    "profiles",
    "agents",
    "conversations",
    "open_applications",
)
RESOURCE_KEYS = {
    "connection": "demo-connection",
    "model": "demo-chat",
    "profile": "chat-profile",
    "agent": "published-agent",
    "open_application": "open-application",
}
GATEWAY_TABLES = {
    "connections": "gateway_connections",
    "models": "gateway_models",
    "profiles": "gateway_profiles",
}


def resource_id(tenant: str, kind: str, key: str) -> UUID:
    """Return the stable Phase 2 identity for a tenant-scoped resource."""

    return uuid5(NAMESPACE_URL, f"agent-platform:{tenant}:{BATCH}:{kind}:{key}")


def _new_counts() -> dict[str, int]:
    return {key: 0 for key in COUNT_KEYS}


async def _ensure_gateway_resource(
    platform: Any,
    tenant: str,
    kind: str,
    body: Connection | Model | Profile,
) -> tuple[dict[str, Any], bool]:
    """Insert a deterministic draft once; never rewrite an operator's resource."""

    table = GATEWAY_TABLES[kind]
    identifier = resource_id(tenant, kind.removesuffix("s"), RESOURCE_KEYS[kind.removesuffix("s")])
    async with platform.runtime.engine.begin() as connection:
        existing = await one(
            connection,
            f"SELECT * FROM {table} WHERE tenant_id=:tenant AND id=:id",
            tenant=tenant,
            id=identifier,
        )
        if existing:
            return existing, False
        row = await one(
            connection,
            f"""INSERT INTO {table}(id,tenant_id,name,spec)
            VALUES(:id,:tenant,:name,CAST(:spec AS jsonb)) RETURNING *""",
            id=identifier,
            tenant=tenant,
            name=body.name,
            spec=json.dumps(body.model_dump(mode="json")),
        )
        return row, True


async def _ensure_published_profile(
    platform: Any, tenant: str
) -> tuple[dict[str, Any], tuple[bool, bool, bool]]:
    connection, connection_created = await _ensure_gateway_resource(
        platform,
        tenant,
        "connections",
        Connection(name=f"{DISPLAY_PREFIX} Demo Connection", protocol="demo"),
    )
    model, model_created = await _ensure_gateway_resource(
        platform,
        tenant,
        "models",
        Model(
            name=f"{DISPLAY_PREFIX} Demo Chat",
            connection_id=connection["id"],
            model_name="demo",
            operations=["chat"],
            tool_calling=True,
        ),
    )
    profile, profile_created = await _ensure_gateway_resource(
        platform,
        tenant,
        "profiles",
        Profile(
            name=f"{DISPLAY_PREFIX} Chat Profile",
            operation="chat",
            model_id=model["id"],
        ),
    )
    if profile["published_version"] is None:
        if profile["archived"] or not profile["enabled"]:
            raise DomainError("seed_profile_unavailable", 409)
        published = await platform.runtime.gateway.catalog.publish(
            tenant,
            ACTOR,
            profile["id"],
            profile["revision"],
        )
        profile["published_version"] = published["version"]
    return profile, (connection_created, model_created, profile_created)


async def _ensure_published_agent(
    platform: Any,
    tenant: str,
    profile: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    identifier = resource_id(tenant, "agent", RESOURCE_KEYS["agent"])
    async with platform.runtime.engine.begin() as connection:
        agent = await one(
            connection,
            "SELECT * FROM agents WHERE tenant_id=:tenant AND id=:id",
            tenant=tenant,
            id=identifier,
        )
        created = False
        if agent is None:
            body = AgentDraft(
                name=f"{DISPLAY_PREFIX} Published Agent",
                description=f"Phase 2 orchestrator example; batch {BATCH}; no customer data.",
                is_example=True,
                config=AgentConfig(
                    system_prompt=(
                        "Answer briefly and accurately with the configured demo model. "
                        "Do not request credentials or claim to perform real transactions."
                    ),
                    model_profile_id=profile["id"],
                    model_profile_version=profile["published_version"],
                ),
            )
            agent = await one(
                connection,
                """INSERT INTO agents(
                    id,tenant_id,business_id,workspace_id,name,description,draft,industry,tags,
                    is_example,created_by
                ) VALUES(
                    :id,:tenant,:business_id,:workspace_id,:name,:description,
                    CAST(:draft AS jsonb),:industry,:tags,true,:creator
                ) RETURNING *""",
                id=identifier,
                tenant=tenant,
                **resource_scope_values(),
                name=body.name,
                description=body.description,
                draft=body.config.model_dump_json(),
                industry=body.industry,
                tags=body.tags,
                creator=ACTOR,
            )
            created = True
    if agent["published_version"] is None:
        if agent["archived"]:
            raise DomainError("seed_agent_unavailable", 409)
        published = await platform.business.agents.publish(
            tenant,
            ACTOR,
            agent["id"],
            agent["draft_revision"],
        )
        agent["published_version"] = published["version"]
    return agent, created


async def _ensure_conversation(
    platform: Any,
    tenant: str,
    external_id: str,
    agent_id: UUID | None,
) -> bool:
    """Create a conversation once and return whether it was created."""

    async with platform.runtime.engine.connect() as connection:
        existing = await one(
            connection,
            """SELECT id FROM runtime_conversations
            WHERE tenant_id=:tenant AND external_id=:external_id""",
            tenant=tenant,
            external_id=external_id,
        )
    if existing:
        return False
    await platform.business.conversations.create(tenant, ACTOR, external_id, agent_id)
    return True


async def _ensure_open_application(
    platform: Any,
    tenant: str,
    agent_id: UUID,
) -> tuple[dict[str, Any], bool]:
    identifier = resource_id(tenant, "open_application", RESOURCE_KEYS["open_application"])
    async with platform.runtime.engine.begin() as connection:
        application = await one(
            connection,
            "SELECT * FROM open_applications WHERE tenant_id=:tenant AND id=:id",
            tenant=tenant,
            id=identifier,
        )
        if application:
            return application, False
        body = ApplicationInput(
            name=f"{DISPLAY_PREFIX} Open Application",
            description=f"Phase 2 Open SSE example; batch {BATCH}; no App Key is seeded.",
            enabled=True,
            agent_ids=[agent_id],
        )
        application = await one(
            connection,
            """INSERT INTO open_applications(
                id,tenant_id,name,description,enabled,agent_ids,rpm,max_concurrency,
                agent_versions,knowledge_base_ids
            ) VALUES(
                :id,:tenant,:name,:description,true,:agent_ids,:rpm,:max_concurrency,
                CAST(:agent_versions AS jsonb),:knowledge_base_ids
            ) RETURNING *""",
            id=identifier,
            tenant=tenant,
            name=body.name,
            description=body.description,
            agent_ids=body.agent_ids,
            rpm=body.rpm,
            max_concurrency=body.max_concurrency,
            agent_versions=json.dumps({}),
            knowledge_base_ids=body.knowledge_base_ids,
        )
        return application, True


async def seed(platform: Any, tenant: str) -> dict[str, Any]:
    """Create or preserve the Phase 2 examples and return non-sensitive references."""

    created = _new_counts()
    preserved = _new_counts()
    async with platform.runtime.engine.connect() as lock:
        await execute(
            lock,
            "SELECT pg_advisory_lock(hashtextextended(:key,71432024))",
            key=f"{tenant}:{BATCH}",
        )
        try:
            profile, gateway_created = await _ensure_published_profile(platform, tenant)
            for key, was_created in zip(
                ("connections", "models", "profiles"), gateway_created, strict=True
            ):
                created[key] = int(was_created)
                preserved[key] = int(not was_created)
            agent, agent_created = await _ensure_published_agent(platform, tenant, profile)
            created["agents"] = int(agent_created)
            preserved["agents"] = int(not agent_created)
            for external_id, agent_id in (
                (PUBLISHED_EXTERNAL_ID, agent["id"]),
                (LEGACY_EXTERNAL_ID, None),
            ):
                conversation_created = await _ensure_conversation(
                    platform, tenant, external_id, agent_id
                )
                created["conversations"] += int(conversation_created)
                preserved["conversations"] += int(not conversation_created)
            application, application_created = await _ensure_open_application(
                platform, tenant, agent["id"]
            )
            created["open_applications"] = int(application_created)
            preserved["open_applications"] = int(not application_created)
        finally:
            await execute(
                lock,
                "SELECT pg_advisory_unlock(hashtextextended(:key,71432024))",
                key=f"{tenant}:{BATCH}",
            )
    return {
        "created": created,
        "preserved": preserved,
        "agent_id": str(agent["id"]),
        "agent_version": agent["published_version"],
        "published_external_id": PUBLISHED_EXTERNAL_ID,
        "legacy_external_id": LEGACY_EXTERNAL_ID,
        "open_application_id": str(application["id"]),
    }


async def main() -> None:
    """Run the seed with the standard application settings."""

    settings = Settings()
    async with runtime_services(settings) as runtime:
        report = await seed(runtime.groups, settings.tenant_id)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
