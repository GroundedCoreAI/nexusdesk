"""Phase 7 Task 2 memory alerting — PostgreSQL integration tests.

Seeds real rows, runs a real AlertScanner/MemoryWorker alert pass, and
asserts the memory.alert.* audit rows (shape + cooldown), the R5/R6
exemptions, the standalone heartbeat record (R8) and the best-effort
webhook contract. Runs only with TEST_DATABASE_URL; skipped locally.
"""

import json
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_platform_postgres import platform as _platform

from agent_platform.modules.memory.alerting import AlertScanner
from agent_platform.modules.memory.worker import MemoryWorker

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def db_rows(engine, sql, **params):
    async with engine.connect() as c:
        rows = (await c.execute(text(sql), params)).mappings().all()
        return [dict(row) for row in rows]


async def db_exec(engine, sql, **params):
    async with engine.begin() as c:
        await c.execute(text(sql), params)


async def alert_audits(engine, tenant, name=None):
    sql = "SELECT * FROM audit_records WHERE tenant_id=:t AND action LIKE 'memory.alert.%'"
    params = {"t": tenant}
    if name:
        sql += " AND action=:a"
        params["a"] = f"memory.alert.{name}"
    return await db_rows(engine, sql + " ORDER BY id", **params)


def make_worker(services, settings, *, embedded=True, webhook=None):
    engine = services.repository.engine
    worker = MemoryWorker(engine, None, settings, embedded=embedded)
    if webhook is not None:
        worker.alert_scanner.webhook = webhook
    return worker


async def make_task(engine, tenant, *, status, age_sql="now()", kind="memory_extract"):
    task_id = uuid4()
    await db_exec(
        engine,
        f"""INSERT INTO memory_tasks(id,tenant_id,kind,status,payload,created_at,updated_at)
        VALUES(:id,:t,:k,:s,'{{}}',{age_sql},{age_sql})""",
        id=task_id,
        t=tenant,
        k=kind,
        s=status,
    )
    return task_id


async def make_pending_item(engine, tenant, *, embedding_failed=False):
    item_id = uuid4()
    await db_exec(
        engine,
        """INSERT INTO memory_items(id,tenant_id,type,key,content,status,source_type,
        embedding_failed) VALUES(:id,:t,'profile',:k,'敏感内容样本',:s,'extract',:e)""",
        id=item_id,
        t=tenant,
        k=f"profile:{uuid4().hex[:8]}",
        s="pending",
        e=embedding_failed,
    )
    return item_id


async def make_search_events(engine, tenant, *, total, fallback):
    cid = uuid4()
    await db_exec(
        engine,
        "INSERT INTO runtime_conversations(id,tenant_id,external_id) VALUES(:id,:t,:e)",
        id=cid,
        t=tenant,
        e=f"conv-{uuid4().hex[:8]}",
    )
    run_id = uuid4()
    await db_exec(
        engine,
        "INSERT INTO runtime_runs(id,conversation_id,tenant_id,input,config,status)"
        " VALUES(:id,:c,:t,'历史消息','{}','completed')",
        id=run_id,
        c=cid,
        t=tenant,
    )
    async with engine.begin() as c:
        for seq in range(total):
            mode = "keyword_fallback" if seq < fallback else "vector"
            await c.execute(
                text(
                    "INSERT INTO runtime_events(run_id,seq,type,data)"
                    " VALUES(:r,:s,'memory_search.completed',CAST(:d AS jsonb))"
                ),
                {"r": run_id, "s": seq, "d": json.dumps({"mode": mode, "hits": 1, "returned": 1})},
            )


async def make_overdue_ticket(engine, tenant):
    customer_id = uuid4()
    type_id = uuid4()
    await db_exec(
        engine,
        "INSERT INTO ticket_types(id,tenant_id,code,name,enabled,draft_definition,revision,"
        "created_at,updated_at) VALUES(:id,:t,:code,'告警类型',true,'{}',1,now(),now())",
        id=type_id,
        t=tenant,
        code=f"t{uuid4().hex[:8]}",
    )
    await db_exec(
        engine,
        "INSERT INTO ticket_type_versions(tenant_id,type_id,version,name,definition,created_by)"
        " VALUES(:t,:ty,1,'告警类型','{}','qa')",
        t=tenant,
        ty=type_id,
    )
    cid = uuid4()
    await db_exec(
        engine,
        "INSERT INTO runtime_conversations(id,tenant_id,external_id) VALUES(:id,:t,:e)",
        id=cid,
        t=tenant,
        e=f"conv-{uuid4().hex[:8]}",
    )
    ticket_id = uuid4()
    await db_exec(
        engine,
        "INSERT INTO tickets(id,tenant_id,conversation_id,title,status,ticket_no,type_id,"
        "type_version,customer_id,due_at) VALUES(:id,:t,:c,'告警工单','open',:no,:ty,1,:cu,"
        "now()-interval '1 day')",
        id=ticket_id,
        t=tenant,
        c=cid,
        no=f"TK-{uuid4().hex[:6]}",
        ty=type_id,
        cu=str(customer_id),
    )
    return ticket_id


# ---------------------------------------------------------------------------
# R1 + cooldown + alert details shape
# ---------------------------------------------------------------------------


async def test_alert_task_failed_writes_audit_and_cooldown_suppresses(platform):
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    await make_task(engine, tenant, status="failed")
    worker = make_worker(services, settings)

    fired = await worker.alert_scan()
    assert "task_failed" in fired
    rows = await alert_audits(engine, tenant, "task_failed")
    assert len(rows) == 1
    details = rows[0]["details"]
    # Details carry only numbers and rule parameters — no payload/content/PII.
    assert set(details) == {"value", "threshold", "window"}
    assert details == {"value": 1, "threshold": 0, "window": "15m"}
    assert rows[0]["actor"] == "memory" and rows[0]["resource"] == "task_failed"

    # Second scan inside the cooldown window writes nothing new.
    count = len(await alert_audits(engine, tenant))
    assert await worker.alert_scan() == []
    assert len(await alert_audits(engine, tenant)) == count


async def test_alert_details_never_carry_content(platform):
    """The seeded item content must not leak into any alert detail payload."""
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    await make_pending_item(engine, tenant)
    await make_task(engine, tenant, status="pending", age_sql="now()-interval '2 hours'")
    worker = make_worker(
        services,
        settings.model_copy(update={"memory_alert_pending_backlog_threshold": 0}),
    )
    fired = await worker.alert_scan()
    assert "pending_backlog" in fired and "pending_task_age" in fired
    for row in await alert_audits(engine, tenant):
        blob = json.dumps(row["details"], ensure_ascii=False)
        assert "敏感内容样本" not in blob
        assert set(row["details"]) == {"value", "threshold", "window"}


# ---------------------------------------------------------------------------
# R5 maintenance_silent: activity with no evidence fires; idle exempt
# ---------------------------------------------------------------------------


async def test_r5_maintenance_silent_fires_with_activity_and_is_exempt_when_idle(
    platform,
):
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    # Cooldown zeroed so the second half re-evaluates on evidence, not on the
    # cooldown window left by the first firing.
    settings = settings.model_copy(update={"memory_alert_cooldown_minutes": 0})
    # Fresh tenant, zero memory activity: exempt despite no maintenance audit.
    assert await make_worker(services, settings).alert_scan() == []

    await make_task(engine, tenant, status="done")
    fired = await make_worker(services, settings).alert_scan()
    assert "maintenance_silent" in fired
    rows = await alert_audits(engine, tenant, "maintenance_silent")
    assert rows[0]["details"] == {"value": 0, "threshold": 0, "window": "24h"}

    # Maintenance evidence in 24h silences the rule (new tenant state reused:
    # write one heartbeat-shaped maintenance audit for this tenant).
    async with engine.begin() as c:
        from agent_platform.platform.persistence.store import audit

        await audit(
            c,
            tenant,
            "memory",
            "memory.maintenance.completed",
            "ttl_purge",
            job="ttl_purge",
            result="ok",
            stats={"expired": 1},
        )
    fired = await make_worker(services, settings).alert_scan()
    assert "maintenance_silent" not in fired


async def test_r5_heartbeat_rows_are_not_maintenance_evidence(platform):
    """Regression: the standalone worker writes a heartbeat audit every 5
    minutes; if those counted as maintenance evidence R5 could never fire in
    exactly the topology it guards (production compose sets embedded=false)."""
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    standalone = make_worker(services, settings, embedded=False)
    await standalone.write_heartbeat_audit()
    await make_task(engine, tenant, status="done")  # memory-task activity
    # Fresh heartbeat silences R8; only R5 may fire.
    fired = await make_worker(services, settings, embedded=False).alert_scan()
    assert fired == ["maintenance_silent"]
    rows = await alert_audits(engine, tenant, "maintenance_silent")
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# R6 rule_scan_missed: exemption without overdue tickets, fires with them
# ---------------------------------------------------------------------------


async def test_r6_exempt_without_overdue_tickets(platform):
    _client, services, settings = platform
    assert "rule_scan_missed" not in await make_worker(services, settings).alert_scan()


async def test_r6_fires_with_overdue_tickets_and_no_evidence(platform):
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    # Cooldown zeroed so the evidence half re-evaluates instead of being
    # suppressed by the first firing's cooldown window.
    settings = settings.model_copy(update={"memory_alert_cooldown_minutes": 0})
    await make_overdue_ticket(engine, tenant)
    fired = await make_worker(services, settings).alert_scan()
    assert "rule_scan_missed" in fired
    rows = await alert_audits(engine, tenant, "rule_scan_missed")
    assert rows[0]["details"]["value"] == 1
    assert rows[0]["details"]["window"] == "30m"  # 2x the 15m default interval

    # Rule-scan evidence (a rule_scan completion audit) silences the rule.
    async with engine.begin() as c:
        from agent_platform.platform.persistence.store import audit

        await audit(
            c,
            tenant,
            "memory",
            "memory.maintenance.completed",
            "rule_scan",
            job="rule_scan",
            result="ok",
            stats={"marked": 1},
        )
    assert "rule_scan_missed" not in await make_worker(services, settings).alert_scan()


# ---------------------------------------------------------------------------
# R4 vector_fallback over real runtime_events rows
# ---------------------------------------------------------------------------


async def test_r4_vector_fallback_fires_above_rate_with_min_calls(platform):
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    await make_search_events(engine, tenant, total=20, fallback=5)  # 25% > 20%
    fired = await make_worker(services, settings).alert_scan()
    assert "vector_fallback" in fired
    rows = await alert_audits(engine, tenant, "vector_fallback")
    assert rows[0]["details"]["value"] == pytest.approx(0.25)
    assert rows[0]["details"]["threshold"] == pytest.approx(0.2)
    assert rows[0]["details"]["window"] == "24h"


# ---------------------------------------------------------------------------
# R3 embedding_growing across real scan cycles
# ---------------------------------------------------------------------------


async def test_r3_rising_backlog_across_three_scans_fires(platform):
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    scanner = AlertScanner(engine, settings, embedded=True)
    await make_pending_item(engine, tenant, embedding_failed=True)
    assert await scanner.scan() == []  # first sample
    await make_pending_item(engine, tenant, embedding_failed=True)
    assert await scanner.scan() == []  # one rise is not enough
    await make_pending_item(engine, tenant, embedding_failed=True)
    fired = await scanner.scan()
    assert "embedding_growing" in fired
    rows = await alert_audits(engine, tenant, "embedding_growing")
    assert rows[0]["details"]["value"] == 3
    assert rows[0]["details"]["threshold"] == 2


# ---------------------------------------------------------------------------
# R8 worker_heartbeat: standalone fires, heartbeat record silences
# ---------------------------------------------------------------------------


async def test_r8_standalone_fires_then_heartbeat_record_silences(platform):
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    standalone = make_worker(services, settings, embedded=False)
    assert standalone.heartbeat_audit_due() is True
    fired = await standalone.alert_scan()
    assert "worker_heartbeat" in fired
    rows = await alert_audits(engine, tenant, "worker_heartbeat")
    assert rows[0]["details"]["threshold"] == 30

    # The claim loop's liveness record silences the rule on a fresh scanner
    # (the firing scanner is inside its own cooldown).
    await standalone.write_heartbeat_audit()
    heartbeat_rows = await db_rows(
        engine,
        "SELECT * FROM audit_records WHERE tenant_id=:t"
        " AND action='memory.maintenance.completed' AND resource='heartbeat'",
        t=tenant,
    )
    assert len(heartbeat_rows) == 1
    assert heartbeat_rows[0]["details"]["job"] == "heartbeat"
    assert heartbeat_rows[0]["details"]["stats"] == {}
    assert (
        "worker_heartbeat" not in await make_worker(services, settings, embedded=False).alert_scan()
    )


async def test_r8_embedded_worker_never_fires(platform):
    _client, services, settings = platform
    embedded = make_worker(services, settings, embedded=True)
    assert embedded.heartbeat_audit_due() is False
    assert "worker_heartbeat" not in await embedded.alert_scan()


# ---------------------------------------------------------------------------
# Webhook (FR-3): payload shape; failure only logs
# ---------------------------------------------------------------------------


async def test_webhook_payload_shape_and_failure_isolated(platform):
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    # Maintenance evidence up front keeps R5 quiet so exactly one rule fires.
    async with engine.begin() as c:
        from agent_platform.platform.persistence.store import audit

        await audit(
            c,
            tenant,
            "memory",
            "memory.maintenance.completed",
            "ttl_purge",
            job="ttl_purge",
            result="ok",
            stats={"expired": 1},
        )
    await make_task(engine, tenant, status="failed")

    calls = []

    async def recording_sender(url, payload, timeout):
        calls.append((url, payload, timeout))

    hooked = settings.model_copy(update={"memory_alert_webhook_url": "https://hooks.example/alert"})
    worker = make_worker(services, hooked, webhook=recording_sender)
    fired = await worker.alert_scan()
    assert "task_failed" in fired
    assert len(calls) == 1
    url, payload, timeout = calls[0]
    assert url == "https://hooks.example/alert" and timeout == 5
    assert set(payload) == {"rule", "tenant", "value", "threshold", "window", "at"}
    assert payload["rule"] == "task_failed" and payload["tenant"] == tenant
    assert payload["value"] == 1 and payload["threshold"] == 0

    # A failing sender must not fail the scan; the alert audit still lands.
    async def failing_sender(url, payload, timeout):
        raise TimeoutError("webhook down")

    await make_task(engine, tenant, status="pending", age_sql="now()-interval '3 hours'")
    worker = make_worker(services, hooked, webhook=failing_sender)
    fired = await worker.alert_scan()
    assert "pending_task_age" in fired
    assert len(await alert_audits(engine, tenant, "pending_task_age")) == 1


# ---------------------------------------------------------------------------
# Master switch: no scan, no heartbeat, no audits
# ---------------------------------------------------------------------------


async def test_master_switch_off_writes_nothing(platform):
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    await make_task(engine, tenant, status="failed")
    off = settings.model_copy(update={"memory_alert_enabled": False})
    worker = make_worker(services, off, embedded=False)
    assert worker.alert_scan_due() is False
    assert worker.heartbeat_audit_due() is False
    assert await worker.alert_scan() == []
    assert await alert_audits(engine, tenant) == []
