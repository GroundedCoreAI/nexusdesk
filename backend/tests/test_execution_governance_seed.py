"""Tests for the opt-in synthetic execution governance demo seed."""

import json

import pytest
from sqlalchemy import text
from test_platform_postgres import platform as _platform

from agent_platform.applications import seed_execution_governance as gov
from agent_platform.applications import seed_execution_platform as platform_seed
from agent_platform.core_platform.agent_execution.credentials.repository import (
    ExecutionCredentialRepository,
)
from agent_platform.core_platform.agent_execution.credentials.vault import ExecutionCredentialVault
from agent_platform.core_platform.platform_services.persistence.store import one
from agent_platform.core_platform.platform_services.secrets.vault import CredentialVault

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]

GOV_BASE = "/api/v1/observability/execution"
LIST_ENDPOINTS = (
    "fencing-denials",
    "cleanup-failures",
    "usage-conflicts",
    "replay-gaps",
    "parser-diagnostics",
)


def _credential_repository(runtime, key_file):
    """A repository whose vault key exists, so a synthetic credential can be seeded."""

    CredentialVault(key_file).cipher(create=True)
    return ExecutionCredentialRepository(
        runtime.repository.engine, ExecutionCredentialVault(key_file)
    )


async def _governance_counts(engine, tenant):
    async with engine.connect() as conn:
        return dict(
            (
                await conn.execute(
                    text(
                        """SELECT
                        (SELECT count(*) FROM execution_fencing_denials d
                          JOIN runtime_runs r ON r.id=d.run_id
                          WHERE r.tenant_id=:t AND r.input LIKE '[execution-governance-demo]%') AS fencing,
                        (SELECT count(*) FROM execution_replay_gap_events g
                          JOIN runtime_runs r ON r.id=g.run_id
                          WHERE r.tenant_id=:t AND r.input LIKE '[execution-governance-demo]%') AS replay,
                        (SELECT count(*) FROM runtime_usage_ledger u
                          JOIN runtime_runs r ON r.id=u.run_id
                          WHERE r.tenant_id=:t AND r.input LIKE '[execution-governance-demo]%') AS usage,
                        (SELECT count(*) FROM execution_parser_diagnostics d
                          JOIN runtime_runs r ON r.id=d.run_id
                          WHERE r.tenant_id=:t AND r.input LIKE '[execution-governance-demo]%') AS parser,
                        (SELECT count(*) FROM runtime_event_outbox o
                          JOIN runtime_runs r ON r.id=o.run_id
                          WHERE r.tenant_id=:t AND r.input LIKE '[execution-governance-demo]%'
                            AND o.status='pending' AND o.last_error IS NOT NULL) AS outbox_errors,
                        (SELECT count(*) FROM runtime_runs
                          WHERE tenant_id=:t AND input LIKE '[execution-governance-demo]%'
                            AND cancel_requested_at IS NOT NULL AND cancel_confirmed_at IS NULL) AS cancels"""
                    ),
                    {"t": tenant},
                )
            ).mappings().one()
        )


async def _cleanup(engine, tenant):
    """Remove tenant governance rows the shared platform fixture does not cascade.

    ``runtime_events``/``runtime_event_outbox`` carry no tenant_id and are
    removed by the ON DELETE CASCADE from ``runtime_runs``.
    """

    async with engine.begin() as conn:
        await conn.execute(
            text(
                """DELETE FROM execution_fencing_denials
                   WHERE run_id IN (SELECT id FROM runtime_runs WHERE tenant_id=:t)"""
            ),
            {"t": tenant},
        )
        for table in (
            "execution_replay_gap_events",
            "runtime_usage_ledger",
            "execution_parser_diagnostics",
            "execution_credential_audit",
            "runtime_runs",
            "runtime_conversations",
            "execution_credentials",
        ):
            await conn.execute(text(f"DELETE FROM {table} WHERE tenant_id=:t"), {"t": tenant})


async def test_governance_seed_is_idempotent_and_synthetic(platform, tmp_path):
    _client, runtime, settings = platform
    tenant = settings.tenant_id
    engine = runtime.repository.engine
    repository = _credential_repository(runtime, tmp_path / "execution.key")
    await _cleanup(engine, tenant)
    try:
        first = await gov.seed(runtime.groups, tenant, repository, settings=settings)
        assert sum(first["created"].values()) > 0
        counts = await _governance_counts(engine, tenant)
        assert counts == {
            "fencing": 2,
            "replay": 2,
            "usage": 3,
            "parser": 2,
            "outbox_errors": 1,
            "cancels": 1,
        }

        second = await gov.seed(runtime.groups, tenant, repository, settings=settings)
        assert not any(second["created"].values())
        assert await _governance_counts(engine, tenant) == counts

        # No real secret in the JSON report or any free-form text column.
        report = json.dumps(first, ensure_ascii=False)
        assert gov.CANARY_SECRET not in report
        async with engine.connect() as conn:
            leaked = await conn.scalar(
                text(
                    """SELECT
                    (SELECT count(*) FROM runtime_usage_ledger WHERE position(:s in source)>0)
                    + (SELECT count(*) FROM execution_parser_diagnostics
                       WHERE position(:s in reason_code)>0)
                    + (SELECT count(*) FROM runtime_event_outbox
                       WHERE position(:s in last_error)>0)
                    + (SELECT count(*) FROM execution_credential_audit
                       WHERE position(:s in reason_code)>0
                          OR position(:s in actor)>0)
                    + (SELECT count(*) FROM runtime_runs
                       WHERE position(:s in input)>0)"""
                ),
                {"s": gov.CANARY_SECRET},
            )
            assert leaked == 0
        assert "Synthetic" in first["note"]
    finally:
        await _cleanup(engine, tenant)


async def test_governance_rest_endpoints_show_seeded_rows(platform, tmp_path):
    client, runtime, settings = platform
    tenant = settings.tenant_id
    engine = runtime.repository.engine
    repository = _credential_repository(runtime, tmp_path / "execution.key")
    await _cleanup(engine, tenant)
    try:
        await gov.seed(runtime.groups, tenant, repository, settings=settings)

        bodies = {}
        for name in LIST_ENDPOINTS:
            response = await client.get(f"{GOV_BASE}/{name}")
            assert response.status_code == 200, (name, response.text)
            body = response.json()
            assert body["total"] > 0, name
            assert body["items"], name
            bodies[name] = body

        concurrency = await client.get(f"{GOV_BASE}/credential-audit", params={"action": "revoked"})
        assert concurrency.status_code == 200
        assert concurrency.json()["total"] > 0
        assert all(
            row["action"] == "revoked" for row in concurrency.json()["items"]
        )

        outbox = await client.get(f"{GOV_BASE}/outbox")
        assert outbox.status_code == 200
        body = outbox.json()
        assert body["total"] > 0
        assert body["last_errors"]
        assert all(
            row["last_error"].startswith(gov.SYNTHETIC) for row in body["last_errors"]
        )

        signals_run = gov.resource_id(tenant, "run", gov.RUN_SIGNALS)
        cancel_run = gov.resource_id(tenant, "run", gov.RUN_CANCEL)
        assert {row["run_id"] for row in bodies["fencing-denials"]["items"]} == {signals_run}
        assert {row["run_id"] for row in bodies["replay-gaps"]["items"]} == {signals_run}
        assert {row["run_id"] for row in bodies["parser-diagnostics"]["items"]} == {signals_run}
        assert all(
            row["reason_code"].startswith(gov.SYNTHETIC)
            for row in bodies["parser-diagnostics"]["items"]
        )
        assert all(
            row["source"].startswith(gov.SYNTHETIC)
            for row in bodies["usage-conflicts"]["items"]
        )
        assert {row["kind"] for row in bodies["usage-conflicts"]["items"]} == {
            "chain",
            "duplicate",
        }
        assert any(
            row["category"] == "unconfirmed_cancel" and row["run_id"] == cancel_run
            for row in bodies["cleanup-failures"]["items"]
        )
        assert all(
            row["actor"].startswith(gov.SYNTHETIC)
            and (
                not row["reason_code"]
                or row["reason_code"].startswith(gov.SYNTHETIC)
            )
            for row in concurrency.json()["items"]
        )

        # The revoked synthetic credential is visible under the credentials API.
        credentials = await client.get("/api/v1/execution-credentials")
        assert credentials.status_code == 200
        assert any(
            row["status"] == "revoked" and row["name"] in gov.credential_names()
            for row in credentials.json()["items"]
        )
    finally:
        await _cleanup(engine, tenant)


async def test_platform_seeder_still_seeds_no_fencing_usage_or_grants(platform, tmp_path):
    """The formal platform seeder's side-effect contract is unchanged."""

    _client, runtime, settings = platform
    tenant = settings.tenant_id
    engine = runtime.repository.engine
    await _cleanup(engine, tenant)
    try:
        await platform_seed.seed(
            runtime.groups, tenant, runtime.execution_credentials, settings=settings
        )
        async with engine.connect() as conn:
            side_effects = await one(
                conn,
                """SELECT
                    (SELECT count(*) FROM execution_credential_grants g
                      JOIN execution_credentials c ON g.credential_id=c.id
                      WHERE c.tenant_id=:t) AS grants,
                    (SELECT count(*) FROM runtime_usage_ledger WHERE tenant_id=:t) AS usage,
                    (SELECT count(*) FROM execution_fencing_denials d
                      JOIN runtime_runs r ON d.run_id=r.id
                      WHERE r.tenant_id=:t) AS fences""",
                t=tenant,
            )
            assert dict(side_effects) == {"grants": 0, "usage": 0, "fences": 0}
    finally:
        await _cleanup(engine, tenant)
