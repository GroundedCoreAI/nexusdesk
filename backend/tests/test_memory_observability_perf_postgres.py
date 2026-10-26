"""Phase 7 P7-IT-13: observability interface performance under 万级 data.

Seeds one tenant with >=10k memory_tasks and >=10k runtime_events rows —
plus a larger decoy tenant so the tenant filter is genuinely selective —
then:

(a) hammers ``memory_summary`` (24h and 168h windows) and ``memory_alerts``
    20 times each and asserts the plan's P95-style bound: every call must
    stay <= 2s (median/max are reported in the assertion message);
(b) EXPLAINs the key aggregate queries copied verbatim from
    ``observability.service`` and asserts no Seq Scan on the large tables
    (memory_tasks / runtime_events / runtime_runs / audit_records) — the
    design doc promises "既有索引 + 时间窗过滤, explain 验证无全表扫描".

Runs only with TEST_DATABASE_URL; skipped locally without one. Seeded rows
are removed at teardown so repeated runs do not bloat the shared test DB.
"""

import statistics
import time
from uuid import uuid4

import pytest
from sqlalchemy import text
from test_memory_alerting_postgres import db_exec
from test_platform_postgres import platform as _platform

platform = _platform
pytestmark = [pytest.mark.asyncio, pytest.mark.postgres]

# 万级 seeding volumes: the target tenant clears the 10k bar on both tasks
# and events; the decoy is bigger still so tenant-scoped indexes, where they
# exist, win over sequential scans on planner cost rather than on table size.
TARGET_TASKS = 12_000
DECOY_TASKS = 30_000
TARGET_RUNS = 500
DECOY_RUNS = 1_500
EVENTS_PER_RUN = 24  # => 12k target / 36k decoy runtime_events rows
TARGET_ALERT_AUDITS = 50
DECOY_AUDITS = 20_000

CALL_BOUND_SECONDS = 2.0
CALL_REPETITIONS = 20

BIG_TABLES = ("memory_tasks", "runtime_events", "runtime_runs", "audit_records")


async def _seed(engine, tenant, decoy):
    """Bulk-seed via generate_series: six statements, no per-row round trips."""
    await db_exec(
        engine,
        """INSERT INTO memory_tasks(id,tenant_id,kind,status,payload,attempts,max_attempts,
           created_at,updated_at,duration_ms)
        SELECT gen_random_uuid(), :t,
            (ARRAY['memory_extract','conversation_summary','reinforce'])[1 + g % 3],
            CASE WHEN g % 20 = 0 THEN 'failed' WHEN g % 25 = 0 THEN 'pending' ELSE 'done' END,
            '{}', 1, 2,
            now() - (g % 48) * interval '1 hour',
            now() - (g % 48) * interval '1 hour',
            CASE WHEN g % 25 = 0 THEN NULL ELSE 50 + g % 400 END
        FROM generate_series(1, :n) g""",
        t=tenant,
        n=TARGET_TASKS,
    )
    await db_exec(
        engine,
        """INSERT INTO memory_tasks(id,tenant_id,kind,status,payload,attempts,max_attempts,
           created_at,updated_at,duration_ms)
        SELECT gen_random_uuid(), :t, 'memory_extract', 'done', '{}', 1, 2,
            now() - interval '3 days' - (g % 10) * interval '1 day',
            now() - interval '3 days' - (g % 10) * interval '1 day',
            50 + g % 400
        FROM generate_series(1, :n) g""",
        t=decoy,
        n=DECOY_TASKS,
    )
    for t, runs in ((tenant, TARGET_RUNS), (decoy, DECOY_RUNS)):
        conversation_id = uuid4()
        await db_exec(
            engine,
            "INSERT INTO runtime_conversations(id,tenant_id,external_id) VALUES(:id,:t,:e)",
            id=conversation_id,
            t=t,
            e=f"perf-{uuid4().hex[:8]}",
        )
        await db_exec(
            engine,
            """INSERT INTO runtime_runs(id,conversation_id,tenant_id,input,config,status,
               queue_expires_at,created_at,finished_at)
            SELECT gen_random_uuid(), :c, :t, '历史消息', '{}', 'completed',
                now() + interval '1 hour',
                now() - (g % 48) * interval '1 hour',
                now() - (g % 48) * interval '1 hour'
            FROM generate_series(1, :n) g""",
            c=conversation_id,
            t=t,
            n=runs,
        )
        await db_exec(
            engine,
            """INSERT INTO runtime_events(run_id,seq,type,data,created_at)
            SELECT r.id, s.seq, 'memory_search.completed',
                jsonb_build_object(
                    'mode', (ARRAY['vector','text','keyword_fallback'])[1 + s.seq % 3],
                    'hits', s.seq % 3,
                    'returned', s.seq % 5),
                r.created_at
            FROM runtime_runs r CROSS JOIN generate_series(1, :per) s(seq)
            WHERE r.tenant_id=:t""",
            t=t,
            per=EVENTS_PER_RUN,
        )
    await db_exec(
        engine,
        """INSERT INTO audit_records(tenant_id,actor,action,resource,details,created_at)
        SELECT :t, 'memory', 'memory.alert.task_failed', 'task_failed',
            CAST(:d AS jsonb),
            now() - (g % 48) * interval '1 hour'
        FROM generate_series(1, :n) g""",
        t=tenant,
        d='{"value":1,"threshold":0,"window":"15m"}',
        n=TARGET_ALERT_AUDITS,
    )
    await db_exec(
        engine,
        """INSERT INTO audit_records(tenant_id,actor,action,resource,details,created_at)
        SELECT :t, 'memory', 'memory.maintenance.completed', 'ttl_purge',
            CAST(:d AS jsonb),
            now() - (g % 48) * interval '1 hour'
        FROM generate_series(1, :n) g""",
        t=decoy,
        d='{"job":"ttl_purge","result":"ok","stats":{"expired":1}}',
        n=DECOY_AUDITS,
    )
    # Fresh planner statistics: without ANALYZE the just-inserted rows are
    # invisible to the cost model and the EXPLAIN assertions below would
    # measure stale-statistics plans, not production-shaped ones.
    async with engine.begin() as c:
        for table in ("memory_tasks", "runtime_runs", "runtime_events", "audit_records"):
            await c.execute(text(f"ANALYZE {table}"))


async def _cleanup(engine, tenant, decoy):
    async with engine.begin() as c:
        for table in ("memory_tasks", "runtime_runs", "runtime_conversations", "audit_records"):
            await c.execute(text(f"DELETE FROM {table} WHERE tenant_id=:t"), {"t": tenant})
            await c.execute(text(f"DELETE FROM {table} WHERE tenant_id=:t"), {"t": decoy})


async def _explain(engine, sql) -> str:
    async with engine.connect() as c:
        rows = (await c.execute(text("EXPLAIN " + sql))).all()
    return "\n".join(row[0] for row in rows)


async def test_p7_it13_observability_performance_at_10k_scale(platform):
    _client, services, settings = platform
    engine, tenant = services.repository.engine, settings.tenant_id
    observability = services.platform.observability
    decoy = f"perf-decoy-{uuid4()}"

    try:
        await _seed(engine, tenant, decoy)
        # (a) Response-time bound: 20 timed calls per surface after one
        # warm-up (the first call warms the connection pool and the plan
        # cache; it is not part of the measurement).
        timings: dict[str, list[float]] = {}
        for label, call in (
            ("summary_24h", lambda: observability.memory_summary(tenant)),
            ("summary_168h", lambda: observability.memory_summary(tenant, window_hours=168)),
            ("alerts_24h", lambda: observability.memory_alerts(tenant)),
        ):
            await call()  # warm-up
            samples = []
            for _ in range(CALL_REPETITIONS):
                start = time.perf_counter()
                await call()
                samples.append(time.perf_counter() - start)
            timings[label] = samples
        report = {
            label: (round(statistics.median(s), 4), round(max(s), 4))
            for label, s in timings.items()
        }
        print(f"\nP7-IT-13 timings (median, max) seconds over {CALL_REPETITIONS} calls: {report}")
        for label, samples in timings.items():
            assert max(samples) <= CALL_BOUND_SECONDS, (
                f"{label} exceeded the {CALL_BOUND_SECONDS}s bound: "
                f"median={statistics.median(samples):.4f}s max={max(samples):.4f}s"
            )

        # (b) Plan shape: the key aggregates, verbatim from
        # observability.service (literals inlined — the tenant id is a
        # self-generated UUID — because plain EXPLAIN takes no bind params).
        t = tenant
        queries = {
            "tasks_main": f"""SELECT count(*) FILTER (WHERE status='pending')::int AS pending,
                count(*) FILTER (WHERE status='running')::int AS running,
                count(*) FILTER (WHERE status='failed'
                    AND updated_at>now()-interval '15 minutes')::int AS failed_15m,
                EXTRACT(EPOCH FROM max(now()-created_at)
                    FILTER (WHERE status='pending'))/60 AS oldest_pending_age_minutes
                FROM memory_tasks WHERE tenant_id='{t}'""",
            "tasks_by_kind": f"""SELECT kind,
                count(*) FILTER (WHERE status='done')::int AS done,
                count(*) FILTER (WHERE status='failed')::int AS failed,
                (avg(duration_ms) FILTER (WHERE duration_ms IS NOT NULL))::double precision
                    AS avg_ms,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
                    FILTER (WHERE duration_ms IS NOT NULL) AS p95_ms
                FROM memory_tasks
                WHERE tenant_id='{t}' AND status IN ('done','failed')
                AND created_at>now()-24*interval '1 hour'
                GROUP BY kind ORDER BY kind""",
            "search_modes_quality": f"""SELECT count(*) FILTER (WHERE e.data->>'mode'='vector')::int
                    AS vector,
                count(*)::int AS calls,
                avg(CAST(e.data->>'returned' AS double precision)) AS avg_returned
                FROM runtime_events e JOIN runtime_runs r ON r.id=e.run_id
                WHERE r.tenant_id='{t}' AND e.type='memory_search.completed'
                AND e.created_at>now()-24*interval '1 hour'""",
            "maintenance_section": f"""SELECT resource AS job, max(created_at) AS last_at
                FROM audit_records
                WHERE tenant_id='{t}' AND action='memory.maintenance.completed'
                AND created_at>now()-24*interval '1 hour'
                GROUP BY resource""",
            "maintenance_activity": f"""SELECT EXISTS(SELECT 1 FROM memory_tasks
                WHERE tenant_id='{t}'
                AND (created_at>now()-interval '24 hours'
                    OR status IN ('pending','running'))) AS active""",
            "alerts_listing": f"""SELECT resource AS rule, created_at AS at,
                CAST(details->>'value' AS double precision) AS value
                FROM audit_records
                WHERE tenant_id='{t}' AND action LIKE 'memory.alert.%'
                AND created_at>now()-24*interval '1 hour'
                ORDER BY created_at DESC, id DESC LIMIT 200""",
        }
        plans = {name: await _explain(engine, sql) for name, sql in queries.items()}
        for name, plan in plans.items():
            print(f"\nP7-IT-13 plan [{name}]:\n{plan}")
        for name, plan in plans.items():
            for table in BIG_TABLES:
                assert f"Seq Scan on {table}" not in plan, (
                    f"query [{name}] sequential-scans {table} at 万级 scale:\n{plan}"
                )
    finally:
        await _cleanup(engine, tenant, decoy)
