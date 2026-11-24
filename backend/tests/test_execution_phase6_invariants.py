"""Phase 6 T-11: cross-cutting code-only invariants and Secret scan."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import ValidationError
from sqlalchemy import text

from agent_platform.applications.customer_service.execution_credential_routes import (
    router as credential_router,
)
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
P6 = REPO / "docs/requirement/agent-execution-platform-v2/phase-6-security-reliability-events"


def test_single_migration_head_and_revision_lengths():
    heads = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini"))).get_heads()
    # 0072/0073 append to the 0071 baseline; 0074 appends the Codex wire-api
    # backfill and 0075 appends the UI-managed egress-host table.
    assert heads == ["0075_gateway_allowed_hosts"]
    assert all(len(head) <= 32 for head in heads)


def test_defaults_never_enable_untrusted_or_history_deletion():
    settings = Settings(_env_file=None)
    assert settings.execution_untrusted_tenants_enabled is False
    assert settings.execution_sandbox_required is True
    assert settings.execution_network_default_deny is True
    assert settings.execution_event_cleanup_enabled is False
    assert settings.execution_outbox_enabled is False
    assert settings.execution_parser_raw_sample_enabled is False
    # Exposure cannot be enabled without Docker + a pinned image + sandbox.
    with pytest.raises(ValidationError):
        Settings(_env_file=None, execution_untrusted_tenants_enabled=True)
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            execution_untrusted_tenants_enabled=True,
            execution_sandbox_provider="docker",
            execution_sandbox_docker_image="",
        )
    enabled = Settings(
        _env_file=None,
        execution_untrusted_tenants_enabled=True,
        execution_sandbox_provider="docker",
        execution_sandbox_docker_image="alpine:latest",
    )
    assert enabled.execution_untrusted_tenants_enabled is True


def test_no_public_secret_read_route_exists():
    paths = {route.path for route in credential_router.routes}
    assert not any("secret" in path for path in paths)
    methods = {
        (route.path, method) for route in credential_router.routes for method in route.methods
    }
    assert ("/execution-credentials", "POST") in methods
    assert ("/execution-credentials/{credential_ref}/rotate", "POST") in methods
    assert ("/execution-credentials/{credential_ref}/revoke", "POST") in methods


def test_deployment_and_migration_artifacts_are_secret_free():
    candidates = [
        BACKEND / ".env.example",
        REPO / "deploy/production/.env.example",
        REPO / "deploy/production/compose.yaml",
        REPO / "deploy/quickstart/compose.yaml",
        BACKEND / "migrations/versions/0071_execution_credential.py",
        P6 / "03-technical-design.en.md",
    ]
    markers = (
        "-----BEGIN PRIVATE KEY-----",
        "-----BEGIN RSA PRIVATE KEY-----",
        "fernet:",
        "sk-abcdefghijklmnop",
        "AKIAIOSFODNN7EXAMPLE",
    )
    for path in candidates:
        text = path.read_text()
        for marker in markers:
            assert marker not in text, f"{marker} found in {path}"


@pytest_asyncio.fixture
async def engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    settings = Settings(database_url=url, tenant_id="invariant", embedded_worker=False)
    value = create_engine(settings)
    try:
        yield value
    finally:
        await value.dispose()


@pytest.mark.asyncio
async def test_outbox_trigger_is_independent_of_the_publisher_switch(engine):
    # execution_outbox_enabled only controls the dispatcher; identity and the
    # same-transaction trigger stay on (02 FR-16, P6-UT-22).
    assert Settings(_env_file=None).execution_outbox_enabled is False
    tenant = "invariant-" + uuid4().hex
    async with engine.begin() as conn:
        conversation = uuid4()
        run_id = uuid4()
        await conn.execute(
            text(
                "INSERT INTO runtime_conversations(id,tenant_id,external_id)"
                " VALUES (:id,:tenant,:external)"
            ),
            {"id": conversation, "tenant": tenant, "external": "inv"},
        )
        await conn.execute(
            text(
                "INSERT INTO runtime_runs(id,conversation_id,tenant_id,input,config,"
                "status,queue_expires_at) VALUES (:id,:cid,:tenant,'x','{}'::jsonb,"
                "'queued',now()+interval '1 hour')"
            ),
            {"id": run_id, "cid": conversation, "tenant": tenant},
        )
        # Old-shaped direct writer, exactly what a pre-0068 binary sends.
        await conn.execute(
            text(
                "INSERT INTO runtime_events(run_id,seq,type,data)"
                " VALUES (:id,1,'run.queued','{}'::jsonb)"
            ),
            {"id": run_id},
        )
    async with engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT e.event_id,o.status FROM runtime_events e"
                        " JOIN runtime_event_outbox o ON o.run_id=e.run_id AND o.seq=e.seq"
                        " WHERE e.run_id=:id"
                    ),
                    {"id": run_id},
                )
            )
            .mappings()
            .first()
        )
    assert row is not None and row["status"] == "pending" and row["event_id"] is not None
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM runtime_runs WHERE id=:id"), {"id": run_id})
        await conn.execute(
            text("DELETE FROM runtime_conversations WHERE id=:id"), {"id": conversation}
        )
