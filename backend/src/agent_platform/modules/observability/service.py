from agent_platform.platform.persistence.store import many, one, required

# Phase 7 Task 3: expected cadence (hours) of the daily maintenance jobs, for
# the maintenance.overdue list. rule_scan's cadence is settings-derived (2x
# the scan interval) and the job is exempt when the scan is disabled.
MAINTENANCE_CADENCE_HOURS = {"ttl_purge": 24.0, "decay": 24.0, "embedding_retry": 24.0}
# Lookback for the per-job last-at scan: far enough back that every cadence
# violation is visible without an unbounded audit_records scan (the table has
# no TTL), matching the longest existing trend window.
MAINTENANCE_LOOKBACK_HOURS = 24 * 7


def _rate(part, whole):
    """part/whole as a float; None when the denominator is zero (no calls)."""
    return (part / whole) if whole else None


def _injection_from_detail(row):
    """Injection section from the Phase 6 memory_injection_log detail rows."""
    return {
        "source": "detail",
        "avg_items": _rate(row["logged"], row["runs"]),
        "by_section": {
            "flag": row["flag"],
            "profile": row["profile"],
            "preference": row["preference"],
            "event": row["event"],
        },
    }


def _injection_from_events(row):
    """Injection section degraded to the counts-only memory.injected events.

    The event payload lumps profile and preference into one ``items`` count,
    so those two sections are indistinguishable here and stay None.
    """
    total = row["items"] + row["flags"] + row["events"]
    return {
        "source": "events",
        "avg_items": _rate(total, row["runs"]),
        "by_section": {
            "flag": row["flags"],
            "profile": None,
            "preference": None,
            "event": row["events"],
        },
    }

# The answer round is the one that did not end in tool calls: the ReAct loop stops
# there, so its text is what the customer sees. Its model.started marks when the
# model call began, and the first_token_ms it records says how long that round ran
# before the first visible character.
ANSWER_ROUND = """SELECT
  (SELECT min(s.created_at) FROM runtime_events s
   WHERE s.run_id=c.run_id AND s.type='model.started'
     AND (s.data->>'round')=(c.data->>'round')) AS answer_started_at,
  CAST(c.data->>'first_token_ms' AS double precision) AS first_token_ms
  FROM runtime_events c
  WHERE c.run_id=r.id AND c.type='model.completed' AND (c.data->>'tool_calls')='0'
  ORDER BY c.seq LIMIT 1"""

# Time to the first character of the answer, in milliseconds, measured from when the
# run was queued. NULL when it was not measured: a run whose answer round never
# streamed (deltas disabled, or an older run predating first_token_ms) has no first
# character to time, and reporting that as zero would understate the metric.
TTFC_EXPRESSION = """CASE WHEN a.answer_started_at IS NULL OR a.first_token_ms IS NULL
  THEN NULL
  ELSE extract(epoch FROM (a.answer_started_at-r.created_at))*1000 + a.first_token_ms
  END"""

TTFC_ROWS = (
    "SELECT r.created_at," + TTFC_EXPRESSION + " AS ttfc_ms FROM runtime_runs r "
    "LEFT JOIN LATERAL (" + ANSWER_ROUND + ") a ON true WHERE r.tenant_id=:t"
)


class ObservabilityService:
    def __init__(self, engine, settings=None):
        # settings is optional: only the Phase 7 maintenance section reads it
        # (rule-scan cadence), defaulting to the settings.py default of 15m.
        self.engine, self.settings = engine, settings

    async def summary(self, tenant):
        async with self.engine.connect() as c:
            result = await one(
                c,
                """SELECT count(*) AS total,
                count(*) FILTER(WHERE status='completed') AS completed,
                count(*) FILTER(WHERE status='failed') AS failed,
                count(*) FILTER(WHERE status='cancelled') AS cancelled,
                count(*) FILTER(WHERE status='running') AS running,
                count(*) FILTER(WHERE status='queued') AS queued,
                avg(extract(epoch FROM finished_at-started_at)) FILTER(WHERE finished_at IS NOT NULL) AS average_seconds,
                percentile_cont(0.95) WITHIN GROUP(ORDER BY extract(epoch FROM finished_at-started_at)) FILTER(WHERE finished_at IS NOT NULL) AS p95_seconds
                FROM runtime_runs WHERE tenant_id=:t AND created_at>now()-interval '24 hours'""",
                t=tenant,
            )
            result["tool_failures"] = (
                await one(
                    c,
                    """SELECT count(*) AS n FROM runtime_events e JOIN runtime_runs r ON r.id=e.run_id
                WHERE r.tenant_id=:t AND e.created_at>now()-interval '24 hours' AND e.type='tool.completed'
                AND e.data->>'ok'='false'""",
                    t=tenant,
                )
            )["n"]
            result["tokens"] = (
                await one(
                    c,
                    """SELECT COALESCE(sum(CAST(e.data->'usage'->>'total_tokens' AS bigint)),0) AS n
                FROM runtime_events e JOIN runtime_runs r ON r.id=e.run_id WHERE r.tenant_id=:t
                AND e.created_at>now()-interval '24 hours' AND e.type='model.completed'""",
                    t=tenant,
                )
            )["n"]
            # Time to the first character of the answer. Derived from the persisted
            # round boundaries plus the first_token_ms each round records, so it needs
            # no extra writes and no stored token text.
            result["ttfc"] = await one(
                c,
                """SELECT percentile_cont(0.5) WITHIN GROUP(ORDER BY ttfc_ms) AS p50_ms,
                percentile_cont(0.95) WITHIN GROUP(ORDER BY ttfc_ms) AS p95_ms,
                count(*) AS samples
                FROM (""" + TTFC_ROWS + """ AND r.created_at>now()-interval '24 hours') t
                WHERE ttfc_ms IS NOT NULL""",
                t=tenant,
            )
            return result

    async def runs(self, tenant, page=1, page_size=10):
        async with self.engine.connect() as c:
            total = await one(
                c, "SELECT count(*) AS total FROM runtime_runs WHERE tenant_id=:t", t=tenant
            )
            items = await many(
                c,
                """SELECT r.id,r.conversation_id,r.status,r.error_code,r.created_at,r.started_at,
                r.finished_at,""" + TTFC_EXPRESSION + """ AS ttfc_ms
                FROM runtime_runs r LEFT JOIN LATERAL (""" + ANSWER_ROUND + """) a ON true
                WHERE r.tenant_id=:t ORDER BY r.created_at DESC LIMIT :lim OFFSET :off""",
                t=tenant,
                lim=page_size,
                off=(page - 1) * page_size,
            )
            return {"items": items, "total": total["total"], "page": page, "page_size": page_size}

    async def audit(self, tenant, page=1, page_size=10, action_type=None):
        async with self.engine.connect() as c:
            where = "tenant_id=:t"
            params = {"t": tenant}
            if action_type:
                where += " AND action=:action_type"
                params["action_type"] = action_type
            total = await one(
                c, f"SELECT count(*) AS total FROM audit_records WHERE {where}", **params
            )
            items = await many(
                c,
                f"""SELECT * FROM audit_records WHERE {where}
                ORDER BY id DESC LIMIT :lim OFFSET :off""",
                **params,
                lim=page_size,
                off=(page - 1) * page_size,
            )
            action_types = await many(
                c,
                """SELECT action, count(*)::int AS count FROM audit_records
                WHERE tenant_id=:t GROUP BY action ORDER BY action""",
                t=tenant,
            )
            return {
                "items": items,
                "total": total["total"],
                "page": page,
                "page_size": page_size,
                "action_types": action_types,
            }

    async def gateways(self, tenant):
        async with self.engine.connect() as c:
            models = await many(
                c,
                "SELECT operation,status,count(*) calls,avg(duration_ms) average_ms,percentile_cont(0.95) WITHIN GROUP(ORDER BY duration_ms) p95_ms FROM gateway_calls WHERE tenant_id=:t AND created_at>now()-interval '24 hours' GROUP BY operation,status ORDER BY operation,status",
                t=tenant,
            )
            tools = await many(
                c,
                "SELECT adapter_type,effect,status,count(*) calls,avg(duration_ms) average_ms FROM tool_calls WHERE tenant_id=:t AND created_at>now()-interval '24 hours' GROUP BY adapter_type,effect,status ORDER BY adapter_type,effect,status",
                t=tenant,
            )
            usage = await many(
                c,
                "SELECT g.operation,u.key unit,sum((u.value#>>'{}')::numeric) amount FROM gateway_attempts a JOIN gateway_calls g ON g.id=a.call_id CROSS JOIN LATERAL jsonb_each(CASE WHEN jsonb_typeof(a.usage)='object' THEN a.usage ELSE '{}'::jsonb END) u WHERE g.tenant_id=:t AND g.created_at>now()-interval '24 hours' GROUP BY g.operation,u.key",
                t=tenant,
            )
            return {"models": models, "tools": tools, "known_usage": usage, "window_hours": 24}

    async def memory_summary(self, tenant, window_hours: int = 24):
        """Phase 4 memory observability (FR-7, R20) + Phase 7 Task 3 health sections.

        Extraction volume aggregates the ``memory.extract.applied`` audit
        details (same-key upserts rewrite item rows, so the row table cannot
        reconstruct the added/updated/pending/dropped split); the hit rate
        divides customer-bound runs with a ``memory.injected`` event by all
        customer-bound runs; governance/decay counts group the R17 audit
        actions; reinforcement reads the ``reinforce`` task queue. Windows
        follow the existing observability style: 24h for rates and counters,
        7d for the daily extraction and recovery trends.

        Phase 7 Task 3 (pure additive — every Phase 4 key keeps its hardcoded
        window and semantics): the new ``tasks``/``search_modes``/
        ``search_quality``/``agents``/``injection`` sections follow the
        ``window_hours`` parameter (1-168, enforced at the API boundary);
        ``embedding``/``maintenance``/``pending_quality`` keep fixed
        cadence-aligned windows (7d retry/confirm trends, per-job cadences).
        See ``_memory_health_sections`` for the per-section semantics and the
        documented degradations (per-agent write/failure attribution and the
        events-mode injection split).
        """
        async with self.engine.connect() as c:
            extraction_daily = await many(
                c,
                """SELECT date_trunc('day', created_at)::text AS day,
                count(*)::int AS runs,
                COALESCE(sum(CAST(details->>'added' AS int)),0)::int AS added,
                COALESCE(sum(CAST(details->>'updated' AS int)),0)::int AS updated,
                COALESCE(sum(CAST(details->>'pending' AS int)),0)::int AS pending,
                COALESCE(sum(CAST(details->>'dropped' AS int)),0)::int AS dropped,
                COALESCE(sum(CAST(details->>'pii_masked' AS int)),0)::int AS pii_masked
                FROM audit_records
                WHERE tenant_id=:t AND action='memory.extract.applied'
                AND created_at>now()-interval '7 days'
                GROUP BY 1 ORDER BY 1""",
                t=tenant,
            )
            hit_rate = await one(
                c,
                """SELECT count(*)::int AS customer_runs,
                count(*) FILTER (WHERE EXISTS (
                    SELECT 1 FROM runtime_events e
                    WHERE e.run_id=r.id AND e.type='memory.injected'))::int AS injected_runs
                FROM runtime_runs r
                JOIN runtime_conversations cv ON cv.id=r.conversation_id
                WHERE r.tenant_id=:t AND cv.customer_id IS NOT NULL
                AND r.created_at>now()-interval '24 hours'""",
                t=tenant,
            )
            backlog = await one(
                c,
                """SELECT count(*)::int AS pending,
                EXTRACT(EPOCH FROM max(now()-updated_at))::bigint AS oldest_age_seconds
                FROM memory_items WHERE tenant_id=:t AND status='pending'""",
                t=tenant,
            )
            governance = await many(
                c,
                """SELECT action, count(*)::int AS n FROM audit_records
                WHERE tenant_id=:t AND action LIKE 'memory.%'
                AND created_at>now()-interval '24 hours'
                GROUP BY action ORDER BY action""",
                t=tenant,
            )
            pii = await one(
                c,
                """SELECT COALESCE(sum(CAST(details->>'pii_masked' AS int)),0)::int AS n
                FROM audit_records
                WHERE tenant_id=:t AND action LIKE 'memory.%'
                AND created_at>now()-interval '24 hours'""",
                t=tenant,
            )
            reinforce = await one(
                c,
                """SELECT count(*) FILTER (WHERE status='done')::int AS tasks_done,
                count(*) FILTER (WHERE status='failed')::int AS tasks_failed,
                COALESCE(sum((SELECT count(*) FROM jsonb_object_keys(payload->'hits')))
                    FILTER (WHERE status='done'),0)::int AS ids_refreshed
                FROM memory_tasks
                WHERE tenant_id=:t AND kind='reinforce'
                AND created_at>now()-interval '24 hours'""",
                t=tenant,
            )
            decay = await one(
                c,
                """SELECT count(*) FILTER (WHERE action='memory.decay_pending')::int AS decay_pending,
                count(*) FILTER (WHERE action='memory.decay_expired')::int AS decay_expired,
                count(*) FILTER (WHERE action='memory.evicted')::int AS evicted,
                count(*) FILTER (WHERE action='memory.item.restored'
                    AND details->>'old_status'='expired')::int AS expired_restored
                FROM audit_records
                WHERE tenant_id=:t AND created_at>now()-interval '7 days'""",
                t=tenant,
            )
            search = await one(
                c,
                """SELECT count(*)::int AS calls,
                count(*) FILTER (WHERE CAST(e.data->>'hits' AS int)=0)::int AS empty
                FROM runtime_events e JOIN runtime_runs r ON r.id=e.run_id
                WHERE r.tenant_id=:t AND e.type='memory_search.completed'
                AND e.created_at>now()-interval '24 hours'""",
                t=tenant,
            )
            return {
                "window_hours": 24,
                "extraction_daily": extraction_daily,
                "hit_rate": hit_rate,
                "backlog": backlog,
                "governance": governance,
                "pii_masked": pii["n"],
                "reinforce": reinforce,
                "decay": decay,
                "search": search,
                **await self._memory_health_sections(c, tenant, window_hours),
            }

    async def _memory_health_sections(self, c, tenant, window_hours: int) -> dict:
        """Phase 7 Task 3 production-observability sections (all tenant-scoped).

        - ``tasks``: pending/running are current-state counts; ``failed_15m``
          matches alert rule R1's window; ``by_kind`` aggregates duration_ms
          over done/failed tasks created in the window (NULL durations — rows
          predating Task 1 — are excluded from avg/p95 but still counted).
        - ``embedding``: the current embedding_failed backlog plus the 7d
          retry outcome sums from the Task 1 maintenance audits.
        - ``search_modes``/``search_quality``: ``memory_search.completed``
          events in the window; rates are None with zero calls (no
          denominator beats a misleading zero).
        - ``maintenance``: per-job last completion from the Task 1 audits
          (heartbeat is liveness, not maintenance, and rides its own field).
          ``overdue`` lists jobs whose last completion is older than their
          cadence (daily jobs 24h; rule_scan 2x the configured interval,
          exempt when the scan is disabled). Matching R5's exemption spirit:
          a never-run job counts as overdue only when the tenant has
          memory-task activity (a row created in 24h or pending/running
          now); a fully idle tenant reports an empty list.
        - ``agents``: per-agent customer-run injection rates in the window,
          grouped by ``config->'agent'->>'id'`` (runs without an agent
          snapshot group under None). DEGRADED: ``items_written`` and
          ``tasks_failed`` stay None — neither the memory.extract.applied
          audit details nor the memory_tasks payload carry agent context, so
          per-agent attribution would need a conversation join the design
          defers; tenant-level write volume is already in extraction_daily.
        - ``injection``: D3 source switch — the Phase 6 detail table when
          present (``source="detail"``), the counts-only memory.injected
          events otherwise (``source="events"``; profile/preference
          indistinguishable there, see _injection_from_events).
        - ``pending_quality``: 7d confirm/reject governance outcomes.
        """
        tasks = await one(
            c,
            """SELECT count(*) FILTER (WHERE status='pending')::int AS pending,
            count(*) FILTER (WHERE status='running')::int AS running,
            count(*) FILTER (WHERE status='failed'
                AND updated_at>now()-interval '15 minutes')::int AS failed_15m,
            EXTRACT(EPOCH FROM max(now()-created_at)
                FILTER (WHERE status='pending'))/60 AS oldest_pending_age_minutes
            FROM memory_tasks WHERE tenant_id=:t""",
            t=tenant,
        )
        tasks["by_kind"] = await many(
            c,
            """SELECT kind,
            count(*) FILTER (WHERE status='done')::int AS done,
            count(*) FILTER (WHERE status='failed')::int AS failed,
            (avg(duration_ms) FILTER (WHERE duration_ms IS NOT NULL))::double precision
                AS avg_ms,
            percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
                FILTER (WHERE duration_ms IS NOT NULL) AS p95_ms
            FROM memory_tasks
            WHERE tenant_id=:t AND status IN ('done','failed')
            AND created_at>now()-:wh*interval '1 hour'
            GROUP BY kind ORDER BY kind""",
            t=tenant,
            wh=window_hours,
        )
        embedding = await one(
            c,
            """SELECT count(*) FILTER (WHERE embedding_failed)::int AS failed_backlog
            FROM memory_items WHERE tenant_id=:t""",
            t=tenant,
        )
        embedding.update(
            await one(
                c,
                """SELECT COALESCE(sum(CAST(details->'stats'->>'scanned' AS int)),0)::int
                    AS retry_scanned_7d,
                COALESCE(sum(CAST(details->'stats'->>'succeeded' AS int)),0)::int
                    AS retry_succeeded_7d
                FROM audit_records
                WHERE tenant_id=:t AND action='memory.maintenance.completed'
                AND resource='embedding_retry' AND created_at>now()-interval '7 days'""",
                t=tenant,
            )
        )
        # One scan feeds both search sections: the WHERE clause is identical,
        # and this endpoint is polled on a few-second cadence.
        search = await one(
            c,
            """SELECT count(*) FILTER (WHERE e.data->>'mode'='vector')::int AS vector,
            count(*) FILTER (WHERE e.data->>'mode'='text')::int AS text,
            count(*) FILTER (WHERE e.data->>'mode'='keyword_fallback')::int
                AS keyword_fallback,
            count(*)::int AS calls,
            count(*) FILTER (WHERE CAST(e.data->>'hits' AS int)=0)::int AS empty,
            avg(CAST(e.data->>'returned' AS double precision)) AS avg_returned
            FROM runtime_events e JOIN runtime_runs r ON r.id=e.run_id
            WHERE r.tenant_id=:t AND e.type='memory_search.completed'
            AND e.created_at>now()-:wh*interval '1 hour'""",
            t=tenant,
            wh=window_hours,
        )
        modes = {
            "vector": search["vector"],
            "text": search["text"],
            "keyword_fallback": search["keyword_fallback"],
        }
        modes["fallback_rate"] = _rate(
            modes["keyword_fallback"],
            modes["vector"] + modes["text"] + modes["keyword_fallback"],
        )
        quality = {
            "calls": search["calls"],
            "empty": search["empty"],
            "empty_rate": _rate(search["empty"], search["calls"]),
            "avg_returned": search["avg_returned"],
        }
        maintenance = await self._maintenance_section(c, tenant, window_hours)
        agents = await many(
            c,
            """SELECT r.config->'agent'->>'id' AS agent_id,
            count(*) FILTER (WHERE cv.customer_id IS NOT NULL)::int AS customer_runs,
            count(*) FILTER (WHERE cv.customer_id IS NOT NULL AND EXISTS (
                SELECT 1 FROM runtime_events e
                WHERE e.run_id=r.id AND e.type='memory.injected'))::int AS injected_runs
            FROM runtime_runs r
            JOIN runtime_conversations cv ON cv.id=r.conversation_id
            WHERE r.tenant_id=:t AND r.created_at>now()-:wh*interval '1 hour'
            GROUP BY 1 ORDER BY 1""",
            t=tenant,
            wh=window_hours,
        )
        for row in agents:
            row["inject_rate"] = _rate(row["injected_runs"], row["customer_runs"])
            row["items_written"] = None  # degraded: no agent context in the audit
            row["tasks_failed"] = None  # degraded: no agent link in task payloads
        reg = await one(c, "SELECT to_regclass('memory_injection_log') AS reg")
        has_log = reg["reg"] is not None
        if has_log:
            injection = _injection_from_detail(
                await one(
                    c,
                    """SELECT count(*)::int AS logged,
                    count(DISTINCT run_id)::int AS runs,
                    count(*) FILTER (WHERE section='flag')::int AS flag,
                    count(*) FILTER (WHERE section='profile')::int AS profile,
                    count(*) FILTER (WHERE section='preference')::int AS preference,
                    count(*) FILTER (WHERE section='event')::int AS event
                    FROM memory_injection_log
                    WHERE tenant_id=:t AND injected_at>now()-:wh*interval '1 hour'""",
                    t=tenant,
                    wh=window_hours,
                )
            )
        else:
            injection = _injection_from_events(
                await one(
                    c,
                    """SELECT count(*)::int AS runs,
                    COALESCE(sum(CAST(e.data->>'items' AS int)),0)::int AS items,
                    COALESCE(sum(CAST(e.data->>'flags' AS int)),0)::int AS flags,
                    COALESCE(sum(CAST(e.data->>'events' AS int)),0)::int AS events
                    FROM runtime_events e JOIN runtime_runs r ON r.id=e.run_id
                    WHERE r.tenant_id=:t AND e.type='memory.injected'
                    AND e.created_at>now()-:wh*interval '1 hour'""",
                    t=tenant,
                    wh=window_hours,
                )
            )
        pending_quality = await one(
            c,
            """SELECT count(*) FILTER (WHERE action='memory.item.confirmed')::int
                AS confirmed_7d,
            count(*) FILTER (WHERE action='memory.item.rejected')::int AS rejected_7d
            FROM audit_records
            WHERE tenant_id=:t AND action IN ('memory.item.confirmed','memory.item.rejected')
            AND created_at>now()-interval '7 days'""",
            t=tenant,
        )
        pending_quality["confirm_rate"] = _rate(
            pending_quality["confirmed_7d"],
            pending_quality["confirmed_7d"] + pending_quality["rejected_7d"],
        )
        return {
            "tasks": tasks,
            "embedding": embedding,
            "search_modes": modes,
            "search_quality": quality,
            "maintenance": maintenance,
            "agents": agents,
            "injection": injection,
            "pending_quality": pending_quality,
        }

    async def _maintenance_section(self, c, tenant, window_hours: int) -> dict:
        """Per-job last completion + overdue list; see _memory_health_sections."""
        lookback = max(window_hours, MAINTENANCE_LOOKBACK_HOURS)
        rows = await many(
            c,
            # max(now()) piggybacks the server clock on the same query, so the
            # overdue arithmetic below compares timestamps from one source.
            """SELECT resource AS job, max(created_at) AS last_at, max(now()) AS now
            FROM audit_records
            WHERE tenant_id=:t AND action='memory.maintenance.completed'
            AND created_at>now()-:lookback*interval '1 hour'
            GROUP BY resource""",
            t=tenant,
            lookback=lookback,
        )
        now = rows[0]["now"] if rows else (await one(c, "SELECT now() AS now"))["now"]
        last_by_job = {row["job"]: row["last_at"] for row in rows}
        heartbeat_last_at = last_by_job.pop("heartbeat", None)
        activity = (
            await one(
                c,
                # Two EXISTS clauses, not one EXISTS over an OR: each arm is
                # then index-served (tenant+created_at / tenant+status), while
                # the OR form defeats both indexes and seq-scans at scale.
                """SELECT EXISTS(SELECT 1 FROM memory_tasks WHERE tenant_id=:t
                AND created_at>now()-interval '24 hours')
                OR EXISTS(SELECT 1 FROM memory_tasks WHERE tenant_id=:t
                AND status IN ('pending','running')) AS active""",
                t=tenant,
            )
        )["active"]
        cadences = dict(MAINTENANCE_CADENCE_HOURS)
        rule_interval = (
            getattr(self.settings, "memory_rule_scan_interval_minutes", 15)
            if self.settings is not None
            else 15
        )
        if rule_interval > 0:
            cadences["rule_scan"] = 2 * rule_interval / 60
        overdue = []
        for job, cadence_hours in cadences.items():
            last_at = last_by_job.get(job)
            if last_at is None:
                if activity:  # never ran despite work to do (R5 spirit)
                    overdue.append(job)
            elif (now - last_at).total_seconds() > cadence_hours * 3600:
                overdue.append(job)
        return {
            "ttl_last_at": last_by_job.get("ttl_purge"),
            "decay_last_at": last_by_job.get("decay"),
            "rule_scan_last_at": last_by_job.get("rule_scan"),
            "embedding_retry_last_at": last_by_job.get("embedding_retry"),
            "heartbeat_last_at": heartbeat_last_at,
            "overdue": overdue,
        }

    async def memory_alerts(self, tenant, window_hours: int = 24, limit: int = 200) -> list:
        """Phase 7 Task 3: the tenant's recent memory.alert.* firings, newest first.

        Rows mirror the Task 2 audit shape: rule from the audit resource,
        value/threshold/window from the details (value is null for R8's
        never-seen-heartbeat firing). Bounded to the latest ``limit`` rows.
        """
        async with self.engine.connect() as c:
            return await many(
                c,
                """SELECT resource AS rule, created_at AS at,
                CAST(details->>'value' AS double precision) AS value,
                CAST(details->>'threshold' AS double precision) AS threshold,
                details->>'window' AS window
                FROM audit_records
                WHERE tenant_id=:t AND action LIKE 'memory.alert.%'
                AND created_at>now()-:wh*interval '1 hour'
                ORDER BY created_at DESC, id DESC LIMIT :lim""",
                t=tenant,
                wh=window_hours,
                lim=limit,
            )

    async def trace(self, tenant, rid):
        async with self.engine.connect() as c:
            row = required(
                await one(
                    c,
                    "SELECT id,conversation_id,status,error_code,config FROM runtime_runs WHERE id=:id AND tenant_id=:t",
                    id=rid,
                    t=tenant,
                )
            )
            row["model_calls"] = await many(
                c,
                "SELECT id,operation,profile_id,profile_version,status,error_code,duration_ms FROM gateway_calls WHERE run_id=:id AND tenant_id=:t ORDER BY created_at",
                id=rid,
                t=tenant,
            )
            row["tool_calls"] = await many(
                c,
                "SELECT * FROM tool_calls WHERE run_id=:id AND tenant_id=:t ORDER BY created_at",
                id=rid,
                t=tenant,
            )
            return row
