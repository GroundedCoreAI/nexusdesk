"""Phase 7 observability instrumentation — PostgreSQL integration tests.

Covers the Task-1 data points: memory_tasks.duration_ms recording (D1
adjusted), per-job maintenance completion/failure audits
(memory.maintenance.completed / .failed), and the extended
memory_search.completed event payload ({mode, hits, returned}).

Runs only with TEST_DATABASE_URL; skipped locally without one. The
keyword_fallback leg runs on any image; the vector leg skips itself on a
plain postgres:17 database (no embedding column), matching the Phase 3
dual-mode matrix convention.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text
from test_memory_events_postgres import (
    StubEmbedGateway,
    add_event_row,
    db_rows,
    has_embedding_column,
    make_customer,
    make_maintenance_worker,
    make_memory_agent,
    set_embedding,
    store_settings,
)
from test_memory_governance_postgres import make_ticket
from test_memory_postgres import audit_records
from test_platform_postgres import platform as _platform

from agent_platform.modules.memory.store import (
    EMBEDDING_DIMENSION,
    PgVectorStore,
    TsVectorStore,
)
from agent_platform.modules.memory.summary import SummaryError
from agent_platform.modules.memory.worker import MemoryWorker

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


class _DoneDispatcher:
    async def execute(self, task):
        return "done"


class _CrashDispatcher:
    async def execute(self, task):
        raise RuntimeError("boom")


class _RetryableDispatcher:
    async def execute(self, task):
        raise SummaryError("gateway_timeout", retryable=True)


async def enqueue_task(engine, tenant, *, attempts=0, max_attempts=2):
    async with engine.begin() as c:
        return (
            await c.execute(
                text(
                    """INSERT INTO memory_tasks(tenant_id,kind,payload,attempts,max_attempts)
                    VALUES(:t,'conversation_summary','{}',:a,:m) RETURNING id"""
                ),
                {"t": tenant, "a": attempts, "m": max_attempts},
            )
        ).scalar()


async def task_row(engine, task_id):
    rows = await db_rows(
        engine,
        "SELECT status,duration_ms FROM memory_tasks WHERE id=:id",
        id=task_id,
    )
    return rows[0]


async def test_p7_it_duration_ms_written_for_done_and_failed(platform):
    """D1 adjusted: every executed attempt records its wall time; done,
    permanently failed and retry-requeued rows alike carry duration_ms >= 0."""
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id

    done_id = await enqueue_task(engine, tenant)
    worker = MemoryWorker(engine, _DoneDispatcher(), settings)
    assert await worker.run_once()
    row = await task_row(engine, done_id)
    assert row["status"] == "done"
    assert row["duration_ms"] is not None and row["duration_ms"] >= 0

    # Retryable failure with attempts left: back to pending, still timed —
    # the duration belongs to the attempt, not the final state.
    retry_id = await enqueue_task(engine, tenant)
    worker = MemoryWorker(engine, _RetryableDispatcher(), settings)
    assert await worker.run_once()
    row = await task_row(engine, retry_id)
    assert row["status"] == "pending" and row["duration_ms"] is not None

    # Last-attempt crash: the generic boundary finalizes straight to failed.
    failed_id = await enqueue_task(engine, tenant, attempts=1, max_attempts=2)
    worker = MemoryWorker(engine, _CrashDispatcher(), settings)
    assert await worker.run_once()
    row = await task_row(engine, failed_id)
    assert row["status"] == "failed"
    assert row["duration_ms"] is not None and row["duration_ms"] >= 0


async def test_p7_it_maintenance_audits_ttl_and_injection_purge(platform):
    """Each affected maintenance job writes one tenant-scoped
    memory.maintenance.completed row carrying {job, result, stats}."""
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    customer_id = await make_customer(engine, tenant)
    stale = await add_event_row(
        engine, tenant, customer_id, "ticket:TK-900:resolved", "超龄事件"
    )
    async with engine.begin() as c:
        await c.execute(
            text("UPDATE memory_items SET expires_at=now()-interval '1 day' WHERE id=:id"),
            {"id": stale},
        )
        await c.execute(
            text(
                """INSERT INTO memory_injection_log(tenant_id,run_id,customer_id,item_id,
                section,injected_at)
                VALUES(:t,:r,:c,:i,'event',now()-interval '120 days')"""
            ),
            {"t": tenant, "r": uuid4(), "c": customer_id, "i": uuid4()},
        )

    worker = make_maintenance_worker(services, settings)
    await worker.maintenance()

    records = await audit_records(engine, tenant, "memory.maintenance.completed")
    by_job = {r["details"]["job"]: r for r in records}
    assert by_job["ttl_purge"]["details"]["result"] == "ok"
    assert by_job["ttl_purge"]["details"]["stats"] == {"expired": 1}
    assert by_job["injection_log_purge"]["details"]["stats"] == {"purged": 1}
    assert all(r["actor"] == "memory" for r in records)
    assert await audit_records(engine, tenant, "memory.maintenance.failed") == []


async def test_p7_it_maintenance_quiet_pass_writes_zero_stat_audits(platform):
    """Spec compliance (03-technical-design: every pass writes an audit): a
    quiet pass — zero rows affected in any job — still writes one
    memory.maintenance.completed row per job with zeroed stats, because R5
    (maintenance_silent) and the maintenance.overdue card read a missing
    audit as "maintenance not running". Runs on plain PG: with store=None
    the embedding_retry pass scans nothing and records zeros."""
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    await make_customer(engine, tenant)  # nothing expires, nothing purges

    worker = make_maintenance_worker(services, settings)
    await worker.maintenance()
    await worker.rule_scan()

    records = await audit_records(engine, tenant, "memory.maintenance.completed")
    by_job = {}
    for r in records:
        by_job.setdefault(r["details"]["job"], []).append(r["details"]["stats"])
    assert by_job["ttl_purge"] == [{"expired": 0}]
    assert by_job["injection_log_purge"] == [{"purged": 0}]
    assert by_job["embedding_retry"] == [{"scanned": 0, "succeeded": 0, "failed": 0}]
    assert by_job["decay"] == [{"profile_pending": 0, "preference_expired": 0, "evicted": 0}]
    assert by_job["rule_scan"] == [{"scanned": 0, "marked": 0, "flags_removed": 0}]
    assert all(r["actor"] == "memory" for r in records)
    assert await audit_records(engine, tenant, "memory.maintenance.failed") == []


async def test_p7_it_embedding_retry_audit_counts_outcomes(platform):
    """The retry batch audit counts actual per-item outcomes
    ({scanned, succeeded, failed}) via embed_and_save's return value."""
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    if not await has_embedding_column(engine):
        pytest.skip("embedding retry needs the pgvector-migrated database")
    customer_id = await make_customer(engine, tenant)
    ok_item = await add_event_row(
        engine, tenant, customer_id, "ticket:TK-901:resolved", "重试成功：更换了主板"
    )
    bad_item = await add_event_row(
        engine, tenant, customer_id, "ticket:TK-902:resolved", "重试失败：型号不明"
    )
    async with engine.begin() as c:
        await c.execute(
            text("UPDATE memory_items SET embedding_failed=true WHERE id IN (:a,:b)"),
            {"a": ok_item, "b": bad_item},
        )

    class FlakyGateway:
        async def invoke(self, tenant, profile_id, version, request, **kwargs):
            item = request.inputs[0]
            if "失败" in item.text:
                raise RuntimeError("model down")
            vector = [1.0] + [0.0] * (EMBEDDING_DIMENSION - 1)
            return {"payload": {"vectors": [{"id": item.id, "vector": vector}]}}

    store = PgVectorStore(engine, FlakyGateway(), store_settings(settings))
    worker = make_maintenance_worker(services, settings, store=store)
    await worker.maintenance()

    records = await audit_records(engine, tenant, "memory.maintenance.completed")
    retry = [r for r in records if r["details"]["job"] == "embedding_retry"]
    assert len(retry) == 1
    assert retry[0]["details"]["stats"] == {"scanned": 2, "succeeded": 1, "failed": 1}


async def test_p7_it_maintenance_failure_writes_failed_audit_and_reraises(platform):
    """A job that raises writes exactly one memory.maintenance.failed row
    ({job, error} with the error truncated to 500 chars) and the original
    exception still propagates out of maintenance() to the dispatcher
    boundary. Runs on plain PG: the poisoned store only needs the
    unconditional embedding_failed column."""
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    customer_id = await make_customer(engine, tenant)
    item_id = await add_event_row(
        engine, tenant, customer_id, "ticket:TK-903:resolved", "重试永不成功"
    )
    async with engine.begin() as c:
        await c.execute(
            text("UPDATE memory_items SET embedding_failed=true WHERE id=:id"),
            {"id": item_id},
        )

    boom = "gateway boom " + "x" * 600

    class RaisingStore:
        def available(self):
            return "vector"

        async def embed_and_save(self, item_id, text):
            raise RuntimeError(boom)

    worker = make_maintenance_worker(services, settings, store=RaisingStore())
    with pytest.raises(RuntimeError, match="gateway boom"):
        await worker.maintenance()

    failed = await audit_records(engine, tenant, "memory.maintenance.failed")
    assert len(failed) == 1
    details = failed[0]["details"]
    assert failed[0]["actor"] == "memory"
    assert details["job"] == "embedding_retry"
    assert details["error"] == boom[:500]
    # The sweep transaction committed before the embedding loop failed, so
    # the two quiet jobs it covered left their zero-stat completion rows;
    # the failed embedding_retry job itself has no completion row.
    completed = await audit_records(engine, tenant, "memory.maintenance.completed")
    assert sorted(r["details"]["job"] for r in completed) == [
        "injection_log_purge",
        "ttl_purge",
    ]


async def test_p7_it_rule_scan_audit(platform):
    """A rule pass that flags an overdue-ticket customer writes one
    completion audit (job=rule_scan) with the scan counters."""
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    customer_id = await make_customer(engine, tenant)
    await make_ticket(engine, tenant, customer_id)  # overdue, open

    worker = make_maintenance_worker(services, settings)
    await worker.rule_scan()

    records = await audit_records(engine, tenant, "memory.maintenance.completed")
    scan = [r for r in records if r["details"]["job"] == "rule_scan"]
    assert len(scan) == 1
    stats = scan[0]["details"]["stats"]
    assert stats == {"scanned": 1, "marked": 1, "flags_removed": 0}


# ---------------------------------------------------------------------------
# memory_search.completed event payload: {mode, hits, returned}
# ---------------------------------------------------------------------------


async def run_search_once(client, services, settings, engine, tenant, customer_id, store):
    """One full run whose demo model calls memory_search (message contains
    上次, per the P3-IT-06 convention) against the given store."""
    from test_platform_postgres import conversation, execute_next

    agent = await make_memory_agent(client)
    conv = await conversation(client, agent["id"])
    async with engine.begin() as c:
        await c.execute(
            text("UPDATE runtime_conversations SET customer_id=:c WHERE id=:id"),
            {"c": customer_id, "id": conv["id"]},
        )
    services.platform.memory_store = store
    response = await client.post(
        f"/api/v1/conversations/{conv['id']}/messages", json={"content": "上次的工单处理进展"}
    )
    assert response.status_code == 202, response.text
    final = await execute_next(services, settings)
    assert final["status"] == "completed", final


async def search_events(engine, tenant):
    rows = await db_rows(
        engine,
        """SELECT e.data FROM runtime_events e JOIN runtime_runs r ON r.id=e.run_id
        WHERE r.tenant_id=:t AND e.type='memory_search.completed'
        ORDER BY e.created_at,e.seq""",
        t=tenant,
    )
    return [row["data"] for row in rows]


async def test_p7_it_search_event_modes(platform):
    """The event payload records the per-call retrieval mode: text, the
    per-call keyword fallback, and (on the pgvector image) vector."""
    client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    customer_id = await make_customer(engine, tenant)
    # Text mode needs lexical overlap with the whole-message query (P3-IT-06).
    item_id = await add_event_row(
        engine,
        tenant,
        customer_id,
        "ticket:TK-100:resolved",
        "工单 TK-100 已解决：上次的工单处理进展为已更换主板",
    )

    await run_search_once(
        client, services, settings, engine, tenant, customer_id,
        TsVectorStore(engine, store_settings(settings)),
    )
    # Query embedding fails per call: the vector store degrades to the
    # keyword arm, stamped keyword_fallback for this call only.
    await run_search_once(
        client, services, settings, engine, tenant, customer_id,
        PgVectorStore(
            engine,
            StubEmbedGateway(None, error=RuntimeError("model down")),
            store_settings(settings),
        ),
    )
    events = await search_events(engine, tenant)
    assert [e["mode"] for e in events] == ["text", "keyword_fallback"]
    assert all(e["hits"] == 1 and e["returned"] == 1 for e in events)

    if not await has_embedding_column(engine):
        pytest.skip("vector leg needs the pgvector-migrated database")
    await set_embedding(engine, item_id, [1.0] + [0.0] * (EMBEDDING_DIMENSION - 1))
    await run_search_once(
        client, services, settings, engine, tenant, customer_id,
        PgVectorStore(
            engine,
            StubEmbedGateway([1.0] + [0.0] * (EMBEDDING_DIMENSION - 1)),
            store_settings(settings),
        ),
    )
    events = await search_events(engine, tenant)
    assert [e["mode"] for e in events] == ["text", "keyword_fallback", "vector"]
