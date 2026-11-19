"""Tests for the formal quickstart agent execution platform demo seed."""

import json

import pytest
from sqlalchemy import text
from test_platform_postgres import platform as _platform

from agent_platform.applications import seed_execution_platform as seed_module
from agent_platform.core_platform.platform_services.persistence.store import one

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


async def _counts(platform):
    _client, runtime, settings = platform
    async with runtime.groups.runtime.engine.connect() as connection:
        return dict(
            (
                await connection.execute(
                    text(
                        """SELECT
                            (SELECT count(*) FROM runtime_runs
                              WHERE tenant_id=:tenant AND input LIKE '[execution-demo]%') AS runs,
                            (SELECT count(*) FROM runtime_events e
                              JOIN runtime_runs r ON e.run_id=r.id
                              WHERE r.tenant_id=:tenant AND r.input LIKE '[execution-demo]%') AS events,
                            (SELECT count(*) FROM execution_workdirs w
                              JOIN runtime_runs r ON w.run_id=r.id
                              WHERE r.tenant_id=:tenant AND r.input LIKE '[execution-demo]%') AS workdirs"""
                    ),
                    {"tenant": settings.tenant_id},
                )
            ).mappings().one()
        )


async def _run(platform, run_key):
    _client, runtime, settings = platform
    identifier = seed_module.resource_id(
        platform[2].tenant_id, "run", run_key
    )
    async with runtime.groups.runtime.engine.connect() as connection:
        return await one(
            connection,
            """SELECT status, config, error_code, cancel_requested,
                      execution_config_snapshot, declared_capabilities_snapshot,
                      available_capabilities_snapshot, effective_capabilities_snapshot,
                      execution_policy_snapshot
               FROM runtime_runs WHERE tenant_id=:tenant AND id=:id""",
            tenant=settings.tenant_id,
            id=identifier,
        )


async def test_execution_platform_seed_is_idempotent_and_keeps_demo_invariants(platform):
    _client, runtime, settings = platform
    services, tenant = runtime.groups, settings.tenant_id

    first = await seed_module.seed(
        services, tenant, runtime.execution_credentials, settings=settings
    )
    before = await _counts(platform)
    assert before == {"runs": 3, "events": 9, "workdirs": 1}
    assert sum(first["created"].values()) > 0
    assert json.dumps(first, ensure_ascii=False).find(seed_module.CANARY_SECRET) == -1

    second = await seed_module.seed(
        services, tenant, runtime.execution_credentials, settings=settings
    )
    assert not any(second["created"].values())
    assert await _counts(platform) == before

    completed = await _run(platform, seed_module.COMPLETED_RUN)
    cancelled = await _run(platform, seed_module.CANCELLED_RUN)
    failed = await _run(platform, seed_module.FAILED_RUN)
    assert completed["status"] == "completed"
    assert cancelled["status"] == "cancelled" and cancelled["cancel_requested"] is True
    assert failed["status"] == "failed"
    assert failed["error_code"] == "execution_demo_failure"
    assert completed["config"]["execution_config_snapshot_marker"] == seed_module.SNAPSHOT_MARKER
    assert all(
        completed[key] for key in (
            "execution_config_snapshot",
            "declared_capabilities_snapshot",
            "available_capabilities_snapshot",
            "effective_capabilities_snapshot",
            "execution_policy_snapshot",
        )
    )
    assert cancelled["declared_capabilities_snapshot"] is None
    assert failed["execution_policy_snapshot"] is None

    async with services.runtime.engine.connect() as connection:
        terminal_types = await connection.execute(
            text(
                """SELECT e.type FROM runtime_events e
                   JOIN runtime_runs r ON e.run_id=r.id
                   WHERE r.tenant_id=:tenant AND r.input LIKE '[execution-demo]%'
                     AND e.seq=3 ORDER BY e.type"""
            ),
            {"tenant": tenant},
        )
        assert [row[0] for row in terminal_types] == [
            "run.cancelled",
            "run.completed",
            "run.failed",
        ]
        published = await connection.scalar(
            text(
                """SELECT count(*) FROM runtime_event_outbox o
                   JOIN runtime_runs r ON o.run_id=r.id
                   WHERE r.tenant_id=:tenant AND r.input LIKE '[execution-demo]%'
                     AND o.status='published'"""
            ),
            {"tenant": tenant},
        )
        assert published == 9
        workdir = await one(
            connection,
            """SELECT w.status, w.last_error_code, p.metadata
               FROM execution_workdirs w
               JOIN runtime_runs r ON w.run_id=r.id
               LEFT JOIN runtime_host_processes p ON p.workdir_id=w.id
               WHERE r.tenant_id=:tenant AND r.input LIKE '[execution-demo]%'
                 AND w.status='cleanup_failed'""",
            tenant=tenant,
        )
        assert workdir["last_error_code"] == "execution_demo_cleanup_failed_sample"
        assert workdir["metadata"]["real_process"] is False
        side_effects = await one(
            connection,
            """SELECT
                (SELECT count(*) FROM execution_credential_grants g
                  JOIN execution_credentials c ON g.credential_id=c.id
                  WHERE c.tenant_id=:tenant) AS grants,
                (SELECT count(*) FROM runtime_usage_ledger WHERE tenant_id=:tenant) AS usage,
                (SELECT count(*) FROM execution_fencing_denials d
                  JOIN runtime_runs r ON d.run_id=r.id
                  WHERE r.tenant_id=:tenant AND r.input LIKE '[execution-demo]%') AS fences""",
            tenant=tenant,
        )
        assert dict(side_effects) == {"grants": 0, "usage": 0, "fences": 0}
