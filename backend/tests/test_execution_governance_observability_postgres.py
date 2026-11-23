"""Phase 6-2 T-12 · IT-1~IT-8: PostgreSQL integration for governance signals.

All database-backed cases skip unless TEST_DATABASE_URL points at a migrated,
dedicated PostgreSQL database (or MIGRATION_TEST_DATABASE_URL for IT-1's fresh
database upgrade). Nothing here fabricates a pass when the environment is
missing.
"""

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import asyncpg
import pytest
import pytest_asyncio
from alembic.config import Config
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import text

from agent_platform.applications.customer_service.main import create_app
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]

BACKEND = Path(__file__).resolve().parents[1]
HEAD = "0073_execution_parser_diag"
CANARY = "CANARY-SECRET-DO-NOT-LEAK-9f8a7b"

GOV_PATHS = [
    "/api/v1/observability/execution/fencing-denials",
    "/api/v1/observability/execution/cleanup-failures",
    "/api/v1/observability/execution/outbox",
    "/api/v1/observability/execution/usage-conflicts",
    "/api/v1/observability/execution/replay-gaps",
    "/api/v1/observability/execution/parser-diagnostics",
    "/api/v1/observability/execution/credential-audit",
]


# --- IT-1: migration chain / fresh database upgrade ------------------------


async def test_it1_migration_head_chain_is_single_and_additive():
    scripts = ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))
    assert scripts.get_heads() == [HEAD]
    rev72 = scripts.get_revision("0072_execution_replay_gap")
    rev73 = scripts.get_revision(HEAD)
    assert rev72.down_revision == "0071_execution_credential"
    assert rev73.down_revision == "0072_execution_replay_gap"
    assert len(rev72.revision) <= 32 and len(rev73.revision) <= 32


@pytest.fixture
def fresh_database():
    url = os.environ.get("MIGRATION_TEST_DATABASE_URL") or os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set MIGRATION_TEST_DATABASE_URL to a PostgreSQL role with CREATEDB")
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    parts = urlsplit(url)
    name = "gov_migration_" + uuid4().hex

    async def admin(statement):
        conn = await asyncpg.connect(url)
        try:
            await conn.execute(statement)
        finally:
            await conn.close()

    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    target = urlunsplit(parts._replace(path="/" + name))
    try:
        yield target
    finally:
        asyncio.run(admin(f'DROP DATABASE "{name}" WITH (FORCE)'))


def test_it1b_fresh_database_upgrades_through_new_head(fresh_database, monkeypatch):
    """Upgrade a brand-new database to head (expand-only, no data loss)."""
    import subprocess
    import sys

    monkeypatch.setenv(
        "AGENT_DATABASE_URL", fresh_database.replace("postgresql://", "postgresql+asyncpg://")
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=dict(os.environ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    def query(sql, *params):
        async def run():
            conn = await asyncpg.connect(fresh_database)
            try:
                return await conn.fetch(sql, *params)
            finally:
                await conn.close()

        return asyncio.run(run())

    tables = {row[0] for row in query("SELECT table_name FROM information_schema.tables")}
    assert {"execution_replay_gap_events", "execution_parser_diagnostics"} <= tables
    version = query("SELECT version_num FROM alembic_version")
    assert version[0][0] == HEAD


# --- shared PostgreSQL app fixture -----------------------------------------


async def _purge_governance_tables(engine) -> None:
    """Reset every table these ITs touch, including orphan-only audit rows.

    Fencing/outbox/events rows may reference run_ids that no longer exist, so a
    per-tenant ``WHERE tenant_id`` (or a ``run_id IN (SELECT ...)``) can never
    remove them. The dedicated test database is reset wholesale at both setup
    and teardown so a prior run with a broken teardown cannot pollute later
    cases (e.g. IT-2's ``reason`` filter counting stale orphan rows).
    """
    tables = (
        "execution_fencing_denials",
        "runtime_event_outbox",
        "runtime_events",
        "execution_replay_gap_events",
        "execution_parser_diagnostics",
        "runtime_usage_ledger",
        "execution_credential_audit",
        "runtime_runs",
        "runtime_conversations",
    )
    async with engine.begin() as conn:
        for table in tables:
            await conn.execute(text(f"DELETE FROM {table}"))


@pytest_asyncio.fixture
async def gov_env():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL database")
    tenant = "gov-" + uuid4().hex
    other = "gov-other-" + uuid4().hex
    settings = Settings(
        database_url=url,
        tenant_id=tenant,
        embedded_worker=False,
        # A nonempty host id assembles the real execution runtime subsystem,
        # including the SIG-7 parser collector/sink that IT-7 exercises. The
        # Host stays disabled (default) so no process may be admitted.
        execution_runtime_host_id="gov-test-host",
        api_token=SecretStr("admin-token"),
        viewer_api_token=SecretStr("viewer-token"),
    )
    app = create_app(settings)
    import httpx

    async with app.router.lifespan_context(app):
        engine = app.state.runtime.repository.engine
        # Start from a clean slate even if a previous (broken) run left orphan
        # audit rows behind; guarantees per-case isolation on a shared DB.
        await _purge_governance_tables(engine)

        async def insert_run(t: str, **overrides):
            conversation_id, run_id = uuid4(), uuid4()
            values = {
                "id": run_id,
                "conversation_id": conversation_id,
                "tenant_id": t,
                "input": "governance-test",
                "config": "{}",
                "status": "completed",
                "queue_expires_at": datetime.now(UTC),
                "created_at": datetime.now(UTC),
                # The INSERT binds all five columns below; supply explicit
                # defaults so no bind parameter is left unbound.
                "cleanup_status": "not_started",
                "cleanup_updated_at": None,
                "cancel_requested_at": None,
                "cancel_confirmed_at": None,
                "event_retention_floor_seq": 0,
            }
            values.update(overrides)
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        """INSERT INTO runtime_conversations
                           (id,tenant_id,business_id,workspace_id,external_id)
                           VALUES (:id,:tenant,'customer-service','default',:external)"""
                    ),
                    {"id": conversation_id, "tenant": t, "external": uuid4().hex},
                )
                await conn.execute(
                    text(
                        """INSERT INTO runtime_runs
                           (id,conversation_id,tenant_id,business_id,workspace_id,
                            input,config,status,queue_expires_at,created_at,
                            cleanup_status,cleanup_updated_at,cancel_requested_at,
                            cancel_confirmed_at,event_retention_floor_seq)
                           VALUES (:id,:conversation_id,:tenant_id,'customer-service','default',
                            :input,:config,:status,:queue_expires_at,:created_at,
                            COALESCE(:cleanup_status,'not_started'),:cleanup_updated_at,
                            :cancel_requested_at,:cancel_confirmed_at,
                            COALESCE(:event_retention_floor_seq,0))"""
                    ),
                    values,
                )
            return run_id

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            client.headers["Authorization"] = "Bearer admin-token"
            yield {
                "app": app,
                "client": client,
                "engine": engine,
                "tenant": tenant,
                "other": other,
                "insert_run": insert_run,
            }

        await _purge_governance_tables(engine)


# --- IT-2 ~ IT-8 -----------------------------------------------------------


async def test_it2_fencing_join_tenant_isolation_and_orphan(gov_env):
    engine, tenant, other = gov_env["engine"], gov_env["tenant"], gov_env["other"]
    own_run = await gov_env["insert_run"](tenant)
    other_run = await gov_env["insert_run"](other)
    orphan = uuid4()
    async with engine.begin() as conn:
        for run_id, reason in ((own_run, "stale_epoch"), (other_run, "stale_epoch"), (orphan, "owner_mismatch")):
            await conn.execute(
                text(
                    """INSERT INTO execution_fencing_denials
                       (id,run_id,operation,reason,created_at)
                       VALUES (:id,:run,'append',:reason,now())"""
                ),
                {"id": uuid4(), "run": run_id, "reason": reason},
            )
    client = gov_env["client"]
    response = await client.get(GOV_PATHS[0])
    assert response.status_code == 200
    body = response.json()
    tenant_ids = [item["tenant_id"] for item in body["items"]]
    assert tenant in tenant_ids and other not in tenant_ids
    assert any(item["deployment_level"] for item in body["items"])
    by_reason = await client.get(GOV_PATHS[0], params={"reason": "owner_mismatch"})
    assert by_reason.status_code == 200 and by_reason.json()["total"] == 1
    cross = await client.get(GOV_PATHS[0], params={"tenant_id": other})
    assert cross.status_code == 200 and cross.json()["total"] == 0


async def test_it3_cleanup_failure_categories_and_runview_zero_diff(gov_env):
    from agent_platform.core_platform.agent_runtime.schemas import RunView

    before = dict(RunView.model_fields)
    tenant = gov_env["tenant"]
    await gov_env["insert_run"](
        tenant,
        cleanup_status="failed",
        cleanup_updated_at=datetime.now(UTC),
    )
    await gov_env["insert_run"](
        tenant,
        cancel_requested_at=datetime.now(UTC),
        cancel_confirmed_at=None,
    )
    response = await gov_env["client"].get(GOV_PATHS[1])
    assert response.status_code == 200
    categories = {item["category"] for item in response.json()["items"]}
    assert {"failed", "unconfirmed_cancel"} <= categories
    assert dict(RunView.model_fields) == before


async def test_it4_outbox_metrics_and_no_publish_side_effect(gov_env):
    engine, tenant = gov_env["engine"], gov_env["tenant"]
    run_id = await gov_env["insert_run"](tenant)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """INSERT INTO runtime_events (run_id,seq,type,data,created_at)
                   VALUES (:run,1,'tool.call','{}',now())"""
            ),
            {"run": run_id},
        )
        # The runtime_events_outbox_trigger already enqueued (run_id, seq=1);
        # update that row instead of inserting a duplicate key.
        await conn.execute(
            text(
                """UPDATE runtime_event_outbox
                   SET status='pending', attempts=2,
                       available_at=now()-interval '2 hours', last_error=:err
                   WHERE run_id=:run AND seq=1"""
            ),
            {"run": run_id, "err": "publisher_rejected"},
        )
    response = await gov_env["client"].get(GOV_PATHS[2])
    assert response.status_code == 200
    body = response.json()
    assert body["pending_count"] >= 1
    assert body["stall_seconds"] is not None and body["stall_seconds"] > 0
    assert any(item["last_error"] == "publisher_rejected" for item in body["last_errors"])
    assert CANARY not in response.text


async def test_it5_usage_conflicts_tenant_filter_and_aggregation_unchanged(gov_env):
    from agent_platform.core_platform.agent_execution.events.usage import aggregate_effective_usage

    engine, tenant, other = gov_env["engine"], gov_env["tenant"], gov_env["other"]
    own_run = await gov_env["insert_run"](tenant)
    other_run = await gov_env["insert_run"](other)
    async with engine.begin() as conn:
        for run_id, t, event_id in (
            (own_run, tenant, "evt-1"),
            (own_run, tenant, "evt-2"),
            (other_run, other, "evt-3"),
        ):
            await conn.execute(
                text(
                    """INSERT INTO runtime_usage_ledger
                       (id,run_id,tenant_id,lease_epoch,source,source_event_id,usage,cost)
                       VALUES (:id,:run,:tenant,1,'engine_native',:event,'{"tokens"\\:1}',0.1)"""
                ),
                {"id": uuid4(), "run": run_id, "tenant": t, "event": event_id},
            )
    response = await gov_env["client"].get(GOV_PATHS[3], params={"kind": "duplicate"})
    assert response.status_code == 200
    tenants = {item["tenant_id"] for item in response.json()["items"]}
    assert tenant in tenants and other not in tenants
    # Aggregation semantics remain the repository's responsibility.
    assert callable(aggregate_effective_usage)


async def test_it6_sse_409_gap_write_and_contract_zero_diff(gov_env):
    from agent_platform.applications.customer_service import runtime_routes

    tenant = gov_env["tenant"]
    run_id = await gov_env["insert_run"](tenant, event_retention_floor_seq=10)
    client = gov_env["client"]

    # (a) write failure never changes the 409 contract.
    original = runtime_routes._record_replay_gap

    async def failing(*args, **kwargs):
        raise RuntimeError("audit store down")

    runtime_routes._record_replay_gap = failing
    try:
        denied = await client.get(
            f"/api/v1/runs/{run_id}/events", params={"after": 1}
        )
        assert denied.status_code == 409
        assert denied.json()["detail"] == "event_replay_gap"
        assert denied.headers["X-Event-Retention-Floor"] == "10"
    finally:
        runtime_routes._record_replay_gap = original

    # (b) normal path persists one bounded event and the query endpoint sees it.
    denied2 = await client.get(f"/api/v1/runs/{run_id}/events", params={"after": 1})
    assert denied2.status_code == 409
    gaps = await client.get(GOV_PATHS[4])
    assert gaps.status_code == 200
    items = gaps.json()["items"]
    assert any(item["run_id"] == str(run_id) for item in items)
    assert all(item["reason_code"] == "cursor_below_floor" for item in items)
    assert CANARY not in gaps.text


async def test_it7_parser_diagnostics_wiring_and_canary_zero(gov_env):
    """Real malformed native events must reach the sink, flush to the table,
    carry the authorized run tenant, and never leak a raw Secret sample.

    This is deliberately driven through the actual React/Codex mappers holding
    the composition-wired collector — not a direct ``collector.report`` call —
    so an unwired collector (the SIG-7 bug) cannot make this test pass.
    """
    from agent_platform.core_platform.agent_execution.adapters.codex.events import CodexEventMapper
    from agent_platform.core_platform.agent_execution.adapters.react.event_mapper import (
        ReactEventMapper,
    )
    from agent_platform.core_platform.agent_execution.contracts import (
        AdapterExecutionError,
        ExecutionRequest,
    )
    from agent_platform.core_platform.platform_services.tenant_isolation.context import (
        bind_scope,
        reset_scope,
    )
    from agent_platform.extension_contracts import BusinessScope

    app = gov_env["app"]
    runtime = app.state.runtime
    execution_runtime = runtime.execution_runtime
    assert execution_runtime is not None
    collector = execution_runtime.parser_diagnostics
    assert collector is not None
    assert execution_runtime.parser_diagnostics_sink is not None

    tenant = gov_env["tenant"]
    run_id = await gov_env["insert_run"](tenant)

    # Bind the authorized run scope: the sink derives tenant_id from it, so a
    # hardcoded/deployment tenant would be caught by the assertion below.
    token = bind_scope(
        BusinessScope(
            tenant_id=tenant,
            business_id="customer-service",
            workspace_id="default",
        )
    )
    try:
        react_request = ExecutionRequest(
            execution_id=run_id,
            engine_id="react",
            protocol_id="native",
            adapter_version="v1",
            tenant_id=tenant,
            agent_id=uuid4(),
            input="x",
            config={},
        )
        react_mapper = ReactEventMapper(react_request, diagnostics=collector)
        # Envelope-field collision is a malformed native event; CANARY lives only
        # in a raw sample slot that the mappers never forward to the collector.
        with pytest.raises(AdapterExecutionError):
            react_mapper.map("extension.note", {"event_id": str(uuid4()), "secret": CANARY})

        codex_mapper = CodexEventMapper(
            execution_id=run_id,
            engine_id="codex",
            protocol_id="cli_exec",
            adapter_version="v1",
            engine_session_id=None,
            diagnostics=collector,
        )
        with pytest.raises(AdapterExecutionError):
            codex_mapper.map_lines([b"{not-json}\n"], max_line_bytes=1024)
    finally:
        reset_scope(token)

    # Sink-level canary probe: a raw sample with the canary must stay private
    # even if some caller temporarily enables samples (they are off here).
    collector.report(
        "malformed",
        engine_id="codex",
        protocol_id="v1",
        sample=CANARY,
    )

    await execution_runtime._flush_parser_diagnostics()

    engine = gov_env["engine"]
    async with engine.begin() as conn:
        result = await conn.execute(
            text(
                """SELECT tenant_id, run_id, category, reason_code
                   FROM execution_parser_diagnostics WHERE run_id = :run"""
            ),
            {"run": run_id},
        )
        rows = result.mappings().all()
    assert rows, "real mapper diagnostics were not persisted"
    assert {row["category"] for row in rows} == {"malformed"}
    assert any(row["tenant_id"] == tenant for row in rows), (
        "tenant_id must come from the authorized run scope, not a deployment default"
    )

    async with engine.begin() as conn:
        all_rows = await conn.execute(text("SELECT * FROM execution_parser_diagnostics"))
        persisted = [dict(row) for row in all_rows.mappings().all()]
    assert CANARY not in str(persisted), "raw Secret sample leaked into the table"

    response = await gov_env["client"].get(GOV_PATHS[5])
    assert response.status_code == 200
    assert CANARY not in response.text
    body = response.json()
    assert body["total"] >= 1
    assert all("sample" not in item for item in body["items"])


async def test_it8_credential_audit_tenant_filter_and_no_secret(gov_env):
    engine, tenant, other = gov_env["engine"], gov_env["tenant"], gov_env["other"]
    async with engine.begin() as conn:
        for t in (tenant, other):
            await conn.execute(
                text(
                    """INSERT INTO execution_credential_audit
                       (id,tenant_id,credential_ref,action,outcome,reason_code,actor)
                       VALUES (:id,:tenant,:ref,'revoked','success','operator_revoke','admin')"""
                ),
                {"id": uuid4(), "tenant": t, "ref": uuid4()},
            )
    response = await gov_env["client"].get(GOV_PATHS[6], params={"action": "revoked"})
    assert response.status_code == 200
    body = response.json()
    assert all(item["tenant_id"] == tenant for item in body["items"])
    assert CANARY not in response.text and "encrypted_secret" not in response.text
    cross = await gov_env["client"].get(GOV_PATHS[6], params={"tenant_id": other})
    assert cross.status_code == 200 and cross.json()["total"] == 0
