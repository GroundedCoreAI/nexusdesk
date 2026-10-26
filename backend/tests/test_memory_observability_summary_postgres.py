"""Phase 7 Task 3 observability aggregation — PostgreSQL integration tests.

Seeds known data (memory_tasks with durations, memory_search.completed
events per mode, Task 1 maintenance audits with backdated timestamps,
memory_injection_log detail rows, confirm/reject governance audits, runs
with agent snapshots) and reconciles every new memory_summary() health
section against the seeds (test-plan P7-IT metric reconciliation), plus the
window_hours=168 variant, the empty-tenant case and the HTTP surface
(window validation, /observability/memory/alerts, auth).

Runs only with TEST_DATABASE_URL; skipped locally without one.
"""

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_memory_alerting_postgres import db_exec
from test_memory_events_postgres import make_customer
from test_platform_postgres import platform as _platform

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


# ---------------------------------------------------------------------------
# Seeders
# ---------------------------------------------------------------------------


async def make_task(
    engine,
    tenant,
    *,
    kind="memory_extract",
    status,
    duration_ms=None,
    created="now()",
    updated="now()",
):
    await db_exec(
        engine,
        f"""INSERT INTO memory_tasks(id,tenant_id,kind,status,payload,duration_ms,
        created_at,updated_at)
        VALUES(:id,:t,:k,:s,'{{}}',:d,{created},{updated})""",
        id=uuid4(),
        t=tenant,
        k=kind,
        s=status,
        d=duration_ms,
    )


async def make_run(
    engine,
    tenant,
    *,
    agent_id=None,
    customer_id=None,
    injected=False,
    search_events=(),
    created="now()",
):
    """One conversation + one completed run, optionally customer-bound, with a
    config snapshot carrying the agent id and the given run events."""
    cid = uuid4()
    await db_exec(
        engine,
        "INSERT INTO runtime_conversations(id,tenant_id,external_id,customer_id)"
        " VALUES(:id,:t,:e,:cu)",
        id=cid,
        t=tenant,
        e=f"conv-{uuid4().hex[:8]}",
        cu=customer_id,
    )
    config = {"agent": {"id": agent_id}} if agent_id else {}
    run_id = uuid4()
    await db_exec(
        engine,
        f"""INSERT INTO runtime_runs(id,conversation_id,tenant_id,input,config,status,created_at)
        VALUES(:id,:c,:t,'历史消息',CAST(:cfg AS jsonb),'completed',{created})""",
        id=run_id,
        c=cid,
        t=tenant,
        cfg=json.dumps(config),
    )
    events = list(search_events)
    if injected:
        events.append(("memory.injected", {"items": 2, "flags": 1, "events": 1}))
    async with engine.begin() as c:
        for seq, (event_type, data) in enumerate(events, start=1):
            await c.execute(
                text(
                    "INSERT INTO runtime_events(run_id,seq,type,data)"
                    " VALUES(:r,:s,:ty,CAST(:d AS jsonb))"
                ),
                {"r": run_id, "s": seq, "ty": event_type, "d": json.dumps(data)},
            )
    return run_id


async def make_maintenance_audit(engine, tenant, job, *, stats=None, at="now()"):
    await db_exec(
        engine,
        f"""INSERT INTO audit_records(tenant_id,actor,action,resource,details,created_at)
        VALUES(:t,'memory','memory.maintenance.completed',:job,
        CAST(:d AS jsonb),{at})""",
        t=tenant,
        job=job,
        d=json.dumps({"job": job, "result": "ok", "stats": stats or {}}),
    )


async def make_alert_audit(engine, tenant, rule, details, *, at="now()"):
    await db_exec(
        engine,
        f"""INSERT INTO audit_records(tenant_id,actor,action,resource,details,created_at)
        VALUES(:t,'memory',:action,:rule,CAST(:d AS jsonb),{at})""",
        t=tenant,
        action=f"memory.alert.{rule}",
        rule=rule,
        d=json.dumps(details),
    )


async def make_governance_audit(engine, tenant, action, *, at="now()"):
    await db_exec(
        engine,
        f"""INSERT INTO audit_records(tenant_id,actor,action,resource,details,created_at)
        VALUES(:t,'operator',:action,:r,'{{}}',{at})""",
        t=tenant,
        action=action,
        r=str(uuid4()),
    )


async def make_injection_rows(engine, tenant, run_id, customer_id, sections):
    async with engine.begin() as c:
        for section in sections:
            await c.execute(
                text(
                    """INSERT INTO memory_injection_log(tenant_id,run_id,customer_id,item_id,
                    section) VALUES(:t,:r,:c,:i,:s)"""
                ),
                {"t": tenant, "r": run_id, "c": customer_id, "i": uuid4(), "s": section},
            )


# ---------------------------------------------------------------------------
# Full reconciliation against a known dataset
# ---------------------------------------------------------------------------


async def seed_health_dataset(engine, tenant):
    """Returns the ids the assertions reconcile against."""
    customer_id = await make_customer(engine, tenant)
    # Tasks: extract done 100ms/300ms, failed 50ms (updated now -> R1 window);
    # reinforce done 1000ms; one pending aged ~30min; one running; one stale
    # done (10d) outside the default 24h window but inside 168h.
    await make_task(engine, tenant, status="done", duration_ms=100)
    await make_task(engine, tenant, status="done", duration_ms=300)
    await make_task(engine, tenant, status="failed", duration_ms=50)
    await make_task(engine, tenant, kind="reinforce", status="done", duration_ms=1000)
    await make_task(
        engine,
        tenant,
        kind="conversation_summary",
        status="pending",
        created="now()-interval '30 minutes'",
        updated="now()-interval '30 minutes'",
    )
    # A second, younger pending task: oldest_pending_age_minutes must report
    # the OLDEST age (~30m) — a min/max slip here once reported the newest.
    await make_task(
        engine,
        tenant,
        kind="conversation_summary",
        status="pending",
        created="now()-interval '5 minutes'",
        updated="now()-interval '5 minutes'",
    )
    await make_task(engine, tenant, kind="conversation_summary", status="running")
    await make_task(
        engine,
        tenant,
        status="done",
        duration_ms=9999,
        created="now()-interval '10 days'",
        updated="now()-interval '10 days'",
    )
    # Embedding backlog.
    for _ in range(2):
        await db_exec(
            engine,
            """INSERT INTO memory_items(id,tenant_id,customer_id,type,key,content,status,
            source_type,embedding_failed)
            VALUES(:id,:t,:c,'profile',:k,'样本','active','extract',true)""",
            id=uuid4(),
            t=tenant,
            c=customer_id,
            k=f"profile:{uuid4().hex[:8]}",
        )
    # Maintenance evidence: ttl_purge fresh; decay 2d ago (overdue, cadence
    # 24h); embedding_retry fresh + a 3d-ago row (7d sums); heartbeat fresh;
    # rule_scan never ran (overdue — the seeded tasks are tenant activity).
    await make_maintenance_audit(engine, tenant, "ttl_purge", stats={"expired": 1})
    await make_maintenance_audit(engine, tenant, "decay", at="now()-interval '2 days'")
    await make_maintenance_audit(
        engine, tenant, "embedding_retry", stats={"scanned": 5, "succeeded": 4, "failed": 1}
    )
    await make_maintenance_audit(
        engine,
        tenant,
        "embedding_retry",
        stats={"scanned": 2, "succeeded": 2, "failed": 0},
        at="now()-interval '3 days'",
    )
    await make_maintenance_audit(engine, tenant, "heartbeat")
    # Search events across both runs: vector x2, text x1 (empty),
    # keyword_fallback x1.
    search_run = await make_run(
        engine,
        tenant,
        agent_id="agent-search",
        customer_id=customer_id,
        search_events=[
            ("memory_search.completed", {"mode": "vector", "hits": 3, "returned": 3}),
            ("memory_search.completed", {"mode": "text", "hits": 0, "returned": 0}),
        ],
    )
    run2 = await make_run(
        engine,
        tenant,
        agent_id="agent-search",
        customer_id=customer_id,
        injected=True,
        search_events=[
            ("memory_search.completed", {"mode": "keyword_fallback", "hits": 1, "returned": 1}),
            ("memory_search.completed", {"mode": "vector", "hits": 2, "returned": 2}),
        ],
    )
    # Injection detail rows: run1 profile+flag, run2 preference+event+profile.
    await make_injection_rows(engine, tenant, search_run, customer_id, ["profile", "flag"])
    await make_injection_rows(
        engine, tenant, run2, customer_id, ["preference", "event", "profile"]
    )
    # Governance outcomes over 7d: 3 confirmed (one 3d ago), 1 rejected.
    await make_governance_audit(engine, tenant, "memory.item.confirmed")
    await make_governance_audit(engine, tenant, "memory.item.confirmed")
    await make_governance_audit(
        engine, tenant, "memory.item.confirmed", at="now()-interval '3 days'"
    )
    await make_governance_audit(engine, tenant, "memory.item.rejected")
    # Agents: agent-a customer-bound injected + not-injected; agent-b
    # customer-bound injected; a customer-bound run without an agent snapshot
    # (null group); an agent-a run without a customer (not customer-bound).
    await make_run(engine, tenant, agent_id="agent-a", customer_id=customer_id, injected=True)
    await make_run(engine, tenant, agent_id="agent-a", customer_id=customer_id)
    await make_run(engine, tenant, agent_id="agent-b", customer_id=customer_id, injected=True)
    await make_run(engine, tenant, customer_id=customer_id, injected=True)
    await make_run(engine, tenant, agent_id="agent-a")
    return customer_id


async def test_p7_it_memory_summary_health_sections_reconcile(platform):
    """Every new section's numbers reconcile against the seeded dataset."""
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    await seed_health_dataset(engine, tenant)

    summary = await services.platform.observability.memory_summary(tenant)

    # Phase 4 keys untouched.
    assert summary["window_hours"] == 24
    for key in (
        "extraction_daily",
        "hit_rate",
        "backlog",
        "governance",
        "pii_masked",
        "reinforce",
        "decay",
        "search",
    ):
        assert key in summary

    tasks = summary["tasks"]
    assert tasks["pending"] == 2 and tasks["running"] == 1 and tasks["failed_15m"] == 1
    assert 29 <= tasks["oldest_pending_age_minutes"] <= 31
    by_kind = {row["kind"]: row for row in tasks["by_kind"]}
    extract = by_kind["memory_extract"]  # the 10d-old row is out of the 24h window
    assert extract["done"] == 2 and extract["failed"] == 1
    assert extract["avg_ms"] == pytest.approx(150.0)
    assert extract["p95_ms"] == pytest.approx(280.0)  # percentile_cont over [50,100,300]
    reinforce = by_kind["reinforce"]
    assert reinforce["done"] == 1 and reinforce["failed"] == 0
    assert reinforce["avg_ms"] == pytest.approx(1000.0)

    embedding = summary["embedding"]
    assert embedding["failed_backlog"] == 2
    assert embedding["retry_scanned_7d"] == 7 and embedding["retry_succeeded_7d"] == 6

    modes = summary["search_modes"]
    assert modes["vector"] == 2 and modes["text"] == 1 and modes["keyword_fallback"] == 1
    assert modes["fallback_rate"] == pytest.approx(0.25)
    quality = summary["search_quality"]
    assert quality["calls"] == 4 and quality["empty"] == 1
    assert quality["empty_rate"] == pytest.approx(0.25)
    assert quality["avg_returned"] == pytest.approx(1.5)

    maintenance = summary["maintenance"]
    assert maintenance["ttl_last_at"] is not None
    assert maintenance["decay_last_at"] is not None
    assert maintenance["embedding_retry_last_at"] is not None
    assert maintenance["rule_scan_last_at"] is None
    assert maintenance["heartbeat_last_at"] is not None
    assert set(maintenance["overdue"]) == {"decay", "rule_scan"}

    agents = {row["agent_id"]: row for row in summary["agents"]}
    agent_a = agents["agent-a"]
    assert agent_a["customer_runs"] == 2 and agent_a["injected_runs"] == 1
    assert agent_a["inject_rate"] == pytest.approx(0.5)
    assert agent_a["items_written"] is None and agent_a["tasks_failed"] is None
    agent_b = agents["agent-b"]
    assert agent_b["customer_runs"] == 1 and agent_b["inject_rate"] == pytest.approx(1.0)
    no_agent = agents[None]  # runs without an agent snapshot group under null
    assert no_agent["customer_runs"] == 1 and no_agent["injected_runs"] == 1

    injection = summary["injection"]
    assert injection["source"] == "detail"
    assert injection["avg_items"] == pytest.approx(2.5)
    assert injection["by_section"] == {"flag": 1, "profile": 2, "preference": 1, "event": 1}

    pending_quality = summary["pending_quality"]
    assert pending_quality["confirmed_7d"] == 3 and pending_quality["rejected_7d"] == 1
    assert pending_quality["confirm_rate"] == pytest.approx(0.75)


async def test_p7_it_memory_summary_window_hours_168(platform):
    """window_hours=168 widens the new sections (the 10d-old task and an old
    search event enter by_kind/search_modes); Phase 4 sections keep their
    fixed windows."""
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    customer_id = await make_customer(engine, tenant)
    await make_task(
        engine,
        tenant,
        status="done",
        duration_ms=500,
        created="now()-interval '3 days'",
        updated="now()-interval '3 days'",
    )
    await make_task(engine, tenant, status="done", duration_ms=100)
    # An old (2d) search event joins the counts only in the wide window.
    cid = uuid4()
    await db_exec(
        engine,
        "INSERT INTO runtime_conversations(id,tenant_id,external_id,customer_id)"
        " VALUES(:id,:t,:e,:cu)",
        id=cid,
        t=tenant,
        e=f"conv-{uuid4().hex[:8]}",
        cu=customer_id,
    )
    run_id = uuid4()
    await db_exec(
        engine,
        "INSERT INTO runtime_runs(id,conversation_id,tenant_id,input,config,status,created_at)"
        " VALUES(:id,:c,:t,'历史消息','{}','completed',now()-interval '2 days')",
        id=run_id,
        c=cid,
        t=tenant,
    )
    await db_exec(
        engine,
        """INSERT INTO runtime_events(run_id,seq,type,data,created_at)
        VALUES(:r,1,'memory_search.completed',CAST(:d AS jsonb),now()-interval '2 days')""",
        r=run_id,
        d=json.dumps({"mode": "text", "hits": 1, "returned": 1}),
    )
    # An injection detail row 2d old: only the wide window may count it.
    await db_exec(
        engine,
        """INSERT INTO memory_injection_log(tenant_id,run_id,customer_id,item_id,section,
        injected_at) VALUES(:t,:r,:c,:i,'profile',now()-interval '2 days')""",
        t=tenant,
        r=run_id,
        c=customer_id,
        i=uuid4(),
    )

    observability = services.platform.observability
    narrow = await observability.memory_summary(tenant)
    wide = await observability.memory_summary(tenant, 168)

    narrow_kind = {row["kind"]: row for row in narrow["tasks"]["by_kind"]}["memory_extract"]
    wide_kind = {row["kind"]: row for row in wide["tasks"]["by_kind"]}["memory_extract"]
    assert narrow_kind["done"] == 1 and narrow_kind["avg_ms"] == pytest.approx(100.0)
    assert wide_kind["done"] == 2 and wide_kind["avg_ms"] == pytest.approx(300.0)
    assert narrow["search_modes"]["text"] == 0
    assert wide["search_modes"]["text"] == 1
    assert wide["search_quality"]["calls"] == 1
    # The window parameter also scopes the injection section.
    assert narrow["injection"]["by_section"]["profile"] == 0
    assert wide["injection"]["by_section"]["profile"] == 1
    assert wide["injection"]["avg_items"] == pytest.approx(1.0)
    # The null-agent run is only inside the wide agents window... it was
    # created 2d ago, so the narrow window sees no agents at all.
    assert narrow["agents"] == [] and len(wide["agents"]) == 1


async def test_p7_it_memory_summary_empty_tenant(platform):
    """Zero rows everywhere: counts zero, rates/dates null, no crash, and the
    idle tenant reports no overdue maintenance jobs (R5 exemption spirit)."""
    _client, services, settings = platform
    tenant = settings.tenant_id
    summary = await services.platform.observability.memory_summary(tenant)

    assert summary["tasks"] == {
        "pending": 0,
        "running": 0,
        "failed_15m": 0,
        "oldest_pending_age_minutes": None,
        "by_kind": [],
    }
    assert summary["embedding"] == {
        "failed_backlog": 0,
        "retry_scanned_7d": 0,
        "retry_succeeded_7d": 0,
    }
    assert summary["search_modes"] == {
        "vector": 0,
        "text": 0,
        "keyword_fallback": 0,
        "fallback_rate": None,
    }
    assert summary["search_quality"] == {
        "calls": 0,
        "empty": 0,
        "empty_rate": None,
        "avg_returned": None,
    }
    maintenance = summary["maintenance"]
    assert maintenance == {
        "ttl_last_at": None,
        "decay_last_at": None,
        "rule_scan_last_at": None,
        "embedding_retry_last_at": None,
        "heartbeat_last_at": None,
        "overdue": [],
    }
    assert summary["agents"] == []
    assert summary["injection"] == {
        "source": "detail",
        "avg_items": None,
        "by_section": {"flag": 0, "profile": 0, "preference": 0, "event": 0},
    }
    assert summary["pending_quality"] == {
        "confirmed_7d": 0,
        "rejected_7d": 0,
        "confirm_rate": None,
    }


async def test_p7_it_rule_scan_not_overdue_when_scan_disabled(platform):
    """A settings object with the rule scan off exempts rule_scan from the
    overdue list even when the tenant has activity."""
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    await make_task(engine, tenant, status="done", duration_ms=10)

    from agent_platform.modules.observability.service import ObservabilityService

    disabled = ObservabilityService(
        engine, settings.model_copy(update={"memory_rule_scan_interval_minutes": 0})
    )
    summary = await disabled.memory_summary(tenant)
    assert "rule_scan" not in summary["maintenance"]["overdue"]
    # The daily jobs never ran and there IS activity: all three overdue.
    assert set(summary["maintenance"]["overdue"]) == {
        "ttl_purge",
        "decay",
        "embedding_retry",
    }


# ---------------------------------------------------------------------------
# HTTP surface: window validation, alerts listing, auth
# ---------------------------------------------------------------------------


async def test_p7_it_memory_endpoint_window_validation(platform):
    client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    await make_task(engine, tenant, status="done", duration_ms=10)
    headers = {"Authorization": "Bearer platform-viewer"}
    ok = await client.get("/api/v1/observability/memory?window_hours=168", headers=headers)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["tasks"]["by_kind"] and body["window_hours"] == 24
    for bad in ("0", "169", "-1", "abc"):
        response = await client.get(
            f"/api/v1/observability/memory?window_hours={bad}", headers=headers
        )
        assert response.status_code == 422, (bad, response.text)


async def test_p7_it_memory_alerts_endpoint(platform):
    """Seeded memory.alert.* rows come back newest-first with the Task 2
    detail shape (value nullable for R8); the window and auth are enforced."""
    client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    await make_alert_audit(
        engine, tenant, "task_failed", {"value": 1, "threshold": 0, "window": "15m"}
    )
    await make_alert_audit(
        engine,
        tenant,
        "worker_heartbeat",
        {"value": None, "threshold": 30, "window": "30m"},
        at="now()-interval '1 minute'",
    )
    await make_alert_audit(
        engine,
        tenant,
        "vector_fallback",
        {"value": 0.5, "threshold": 0.2, "window": "24h"},
        at="now()-interval '2 days'",
    )
    # Decoy: a non-alert memory audit must not leak into the listing.
    await make_maintenance_audit(engine, tenant, "ttl_purge", stats={"expired": 1})

    headers = {"Authorization": "Bearer platform-viewer"}
    response = await client.get("/api/v1/observability/memory/alerts", headers=headers)
    assert response.status_code == 200, response.text
    rows = response.json()
    assert [row["rule"] for row in rows] == ["task_failed", "worker_heartbeat"]
    assert rows[0]["value"] == 1 and rows[0]["threshold"] == 0
    assert rows[0]["window"] == "15m" and rows[0]["at"]
    assert rows[1]["value"] is None and rows[1]["threshold"] == 30

    wide = await client.get(
        "/api/v1/observability/memory/alerts?window_hours=72", headers=headers
    )
    assert [row["rule"] for row in wide.json()] == [
        "task_failed",
        "worker_heartbeat",
        "vector_fallback",
    ]
    assert (
        await client.get("/api/v1/observability/memory/alerts?window_hours=169", headers=headers)
    ).status_code == 422
    assert (
        await client.get(
            "/api/v1/observability/memory/alerts",
            headers={"Authorization": "Bearer no-such-token"},
        )
    ).status_code == 401
