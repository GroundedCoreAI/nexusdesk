"""Phase 7 production alerting for the memory subsystem (Task 2).

Eight rules (R1-R8) evaluate a DB-collected snapshot and write
``memory.alert.<name>`` audit rows (details ``{value, threshold, window}`` —
numbers and rule parameters only, never payloads, content or PII) with a
per-rule cooldown and an optional best-effort webhook (FR-3).

The module is split so rules stay unit-testable without a database:
``AlertContext`` is the snapshot every rule reads, ``collect`` fills it with
window-limited count queries (the whole scan stays well under ~5s), the
``rule_*`` functions are pure, and ``AlertScanner.scan`` orchestrates
cooldown + audit + webhook on one transaction.

Honest limitations, by design:
- R3 embedding_growing keeps its last two backlog samples in this process;
  a worker restart resamples from scratch, so a rise straddling a restart is
  missed rather than risk a false fire (宁漏不误).
- R5/R6 are exempt by construction when there is nothing to act on (no
  memory-task activity / no overdue tickets / rule scan disabled), matching
  Task 1's quiet-pass-silent audit design.
- R8 worker_heartbeat only exists in the standalone topology and is written
  by the worker's own claim loop, so a fully dead worker also stops this
  scanner: R8 catches wedged or partially-alive states (claim loop alive,
  heartbeat path broken), not a hard-killed process — an external watchdog
  remains the answer for the latter.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from sqlalchemy import text

from agent_platform.platform.persistence.store import audit, one

logger = logging.getLogger(__name__)

# R8: the standalone worker's claim loop rewrites its liveness record at most
# this often; the rule fires once no record is seen within HEARTBEAT_WINDOW.
HEARTBEAT_INTERVAL_SECONDS = 300
HEARTBEAT_WINDOW_MINUTES = 30
HEARTBEAT_JOB = "heartbeat"
# R4: the fallback-rate gate needs this much traffic before a share means
# anything; below it the rule stays silent regardless of the share.
SEARCH_MIN_CALLS_24H = 20

# One webhook sender signature; injectable so tests never touch the network.
WebhookSender = Callable[[str, dict, float], Awaitable[None]]


@dataclass
class AlertContext:
    """Everything the rules need, collected with window-limited queries."""

    now: datetime
    embedded: bool
    # R1: failed memory_tasks in the last 15 minutes.
    failed_tasks_15m: int = 0
    # R2: age of the oldest pending memory_tasks row, seconds; None = no
    # pending rows at all.
    oldest_pending_task_age_seconds: float | None = None
    # R3: current embedding_failed backlog.
    embedding_backlog: int = 0
    # R4: memory_search.completed calls in 24h and how many fell back to
    # keyword mode.
    search_calls_24h: int = 0
    search_keyword_fallback_24h: int = 0
    # R5: memory-task activity in 24h (rows created in the window or
    # pending/running right now) and maintenance evidence in 24h.
    memory_task_activity: bool = False
    maintenance_audits_24h: int = 0
    # R6: overdue-flaggable tickets right now (the scan_overdue_tickets
    # predicate) and rule-scan evidence within the evidence window.
    overdue_flaggable_tickets: int = 0
    rule_scan_evidence: bool = False
    # R7: pending-confirmation memory items (same predicate the
    # observability memory_summary backlog count uses).
    pending_items: int = 0
    # R8: minutes since the standalone worker's last heartbeat record;
    # None = never seen.
    heartbeat_age_minutes: float | None = None
    # Timestamps of the most recent memory.alert.<name> audit per rule,
    # for the cooldown check.
    last_alerts: dict[str, datetime] = field(default_factory=dict)


@dataclass
class Alert:
    name: str
    value: int | float | None
    threshold: int | float
    window: str

    @property
    def action(self) -> str:
        return f"memory.alert.{self.name}"


# ---------------------------------------------------------------------------
# Pure rules: snapshot + settings in, Alert or None out.
# ---------------------------------------------------------------------------


def rule_task_failed(ctx: AlertContext, settings) -> Alert | None:
    """R1: any memory task failed in the last 15 minutes."""
    if ctx.failed_tasks_15m > 0:
        return Alert("task_failed", ctx.failed_tasks_15m, 0, "15m")
    return None


def rule_pending_task_age(ctx: AlertContext, settings) -> Alert | None:
    """R2: the oldest pending memory task waited past the configured age."""
    limit = settings.memory_alert_pending_task_max_age_minutes * 60
    if ctx.oldest_pending_task_age_seconds is not None and (
        ctx.oldest_pending_task_age_seconds > limit
    ):
        return Alert("pending_task_age", int(ctx.oldest_pending_task_age_seconds), limit, "now")
    return None


def rule_embedding_growing(ctx: AlertContext, settings, samples: list[int]) -> Alert | None:
    """R3: the embedding_failed backlog rose across 2 consecutive scans.

    ``samples`` holds the two most recent prior backlog readings (process
    memory; a restart resamples from scratch — 宁漏不误, a rise straddling a
    restart is missed rather than false-fired). The caller owns the list;
    this rule shifts the current reading in after deciding.
    """
    alert = None
    if (
        len(samples) == 2
        and ctx.embedding_backlog > 0
        and ctx.embedding_backlog > samples[-1] > samples[0]
    ):
        alert = Alert("embedding_growing", ctx.embedding_backlog, samples[-1], "2 scans")
    samples[:] = (samples + [ctx.embedding_backlog])[-2:]
    return alert


def rule_vector_fallback(ctx: AlertContext, settings) -> Alert | None:
    """R4: too many searches degrade to keyword_fallback in 24h."""
    rate = settings.memory_alert_vector_fallback_rate
    if ctx.search_calls_24h < SEARCH_MIN_CALLS_24H:
        return None
    share = ctx.search_keyword_fallback_24h / ctx.search_calls_24h
    if share > rate:
        return Alert("vector_fallback", round(share, 4), rate, "24h")
    return None


def rule_maintenance_silent(ctx: AlertContext, settings) -> Alert | None:
    """R5: maintenance has work to do but left no evidence in 24h.

    Controller's adjustment of the raw design: the rule fires only when the
    tenant had memory-task activity in the last 24h (any memory_tasks row
    created in the window, or pending/running right now — i.e. maintenance
    has work to do) AND no memory.maintenance.completed/failed audit exists
    in the same window. The worker's heartbeat liveness records are excluded
    from that evidence: the standalone worker writes one every 5 minutes, so
    counting them would silence R5 exactly where it matters. Tenants with
    zero memory activity are EXEMPT, which avoids false positives from
    Task 1's quiet-pass-silent design (a pass that affected no rows writes
    nothing). The value is the maintenance audit count in the window; the
    threshold is the zero it must stay above.
    """
    if ctx.memory_task_activity and ctx.maintenance_audits_24h == 0:
        return Alert("maintenance_silent", 0, 0, "24h")
    return None


def rule_rule_scan_missed(ctx: AlertContext, settings) -> Alert | None:
    """R6: the built-in rule scan is enabled, has overdue work, no evidence.

    Evidence = a memory.maintenance.completed audit with job=rule_scan or a
    memory.flag.removed audit within the last 2x scan interval. No overdue
    tickets -> exempt (a quiet pass legitimately writes nothing); a disabled
    scan -> exempt.
    """
    interval = getattr(settings, "memory_rule_scan_interval_minutes", 15)
    if interval <= 0:
        return None
    if ctx.overdue_flaggable_tickets > 0 and not ctx.rule_scan_evidence:
        return Alert(
            "rule_scan_missed",
            ctx.overdue_flaggable_tickets,
            0,
            f"{2 * interval}m",
        )
    return None


def rule_pending_backlog(ctx: AlertContext, settings) -> Alert | None:
    """R7: pending-confirmation memory items above the configured backlog."""
    limit = settings.memory_alert_pending_backlog_threshold
    if ctx.pending_items > limit:
        return Alert("pending_backlog", ctx.pending_items, limit, "now")
    return None


def rule_worker_heartbeat(ctx: AlertContext, settings) -> Alert | None:
    """R8: the standalone worker's heartbeat record went stale.

    Embedded mode is exempt by construction (API alive => worker alive), and
    a fully dead worker also stops this scanner — see the module docstring.
    """
    if ctx.embedded:
        return None
    if ctx.heartbeat_age_minutes is None or (ctx.heartbeat_age_minutes > HEARTBEAT_WINDOW_MINUTES):
        return Alert(
            "worker_heartbeat",
            ctx.heartbeat_age_minutes,
            HEARTBEAT_WINDOW_MINUTES,
            f"{HEARTBEAT_WINDOW_MINUTES}m",
        )
    return None


def evaluate(ctx: AlertContext, settings, backlog_samples: list[int]) -> list[Alert]:
    """Run all eight rules; R3 consumes/updates the caller's sample state."""
    alerts = []
    for fn in (rule_task_failed, rule_pending_task_age):
        alert = fn(ctx, settings)
        if alert:
            alerts.append(alert)
    alert = rule_embedding_growing(ctx, settings, backlog_samples)
    if alert:
        alerts.append(alert)
    for fn in (
        rule_vector_fallback,
        rule_maintenance_silent,
        rule_rule_scan_missed,
        rule_pending_backlog,
        rule_worker_heartbeat,
    ):
        alert = fn(ctx, settings)
        if alert:
            alerts.append(alert)
    return alerts


def cooldown_active(last_fired_at: datetime | None, now: datetime, cooldown_minutes: int) -> bool:
    """Pure cooldown decision: a prior alert within the window suppresses."""
    if last_fired_at is None:
        return False
    return (now - last_fired_at).total_seconds() < cooldown_minutes * 60


# ---------------------------------------------------------------------------
# Collector: window-limited counts only; the whole snapshot stays cheap.
# ---------------------------------------------------------------------------


async def collect(engine, settings, *, embedded: bool) -> AlertContext:
    tenant = settings.tenant_id
    rule_interval = max(getattr(settings, "memory_rule_scan_interval_minutes", 15), 1)
    ctx = AlertContext(now=datetime.now(UTC), embedded=embedded)
    async with engine.connect() as c:
        row = await one(
            c,
            """SELECT
            count(*) FILTER (WHERE status='failed'
                AND updated_at>now()-interval '15 minutes')::int AS failed_15m,
            min(created_at) FILTER (WHERE status='pending') AS oldest_pending_at,
            EXISTS(SELECT 1 FROM memory_tasks t2
                WHERE t2.tenant_id=:t
                AND (t2.created_at>now()-interval '24 hours'
                    OR t2.status IN ('pending','running'))) AS activity
            FROM memory_tasks WHERE tenant_id=:t""",
            t=tenant,
        )
        ctx.failed_tasks_15m = row["failed_15m"]
        oldest_pending_at = row["oldest_pending_at"]
        if oldest_pending_at is not None:
            if oldest_pending_at.tzinfo is None:
                oldest_pending_at = oldest_pending_at.replace(tzinfo=UTC)
            ctx.oldest_pending_task_age_seconds = (ctx.now - oldest_pending_at).total_seconds()
        ctx.memory_task_activity = row["activity"]
        row = await one(
            c,
            """SELECT
            count(*) FILTER (WHERE embedding_failed)::int AS embedding_backlog,
            count(*) FILTER (WHERE status='pending')::int AS pending_items
            FROM memory_items WHERE tenant_id=:t""",
            t=tenant,
        )
        ctx.embedding_backlog = row["embedding_backlog"]
        ctx.pending_items = row["pending_items"]
        row = await one(
            c,
            """SELECT count(*)::int AS calls,
            count(*) FILTER (WHERE e.data->>'mode'='keyword_fallback')::int AS fallback
            FROM runtime_events e JOIN runtime_runs r ON r.id=e.run_id
            WHERE r.tenant_id=:t AND e.type='memory_search.completed'
            AND e.created_at>now()-interval '24 hours'""",
            t=tenant,
        )
        ctx.search_calls_24h = row["calls"]
        ctx.search_keyword_fallback_24h = row["fallback"]
        row = await one(
            c,
            """SELECT
            count(*) FILTER (WHERE action IN
                ('memory.maintenance.completed','memory.maintenance.failed')
                AND resource<>:heartbeat
                AND created_at>now()-interval '24 hours')::int AS maintenance_24h,
            max(created_at) FILTER (WHERE action='memory.maintenance.completed'
                AND resource=:heartbeat
                AND created_at>now()-interval '24 hours') AS last_heartbeat,
            EXISTS(SELECT 1 FROM audit_records a2 WHERE a2.tenant_id=:t
                AND a2.created_at>now()-:evidence*interval '1 minute'
                AND ((a2.action='memory.maintenance.completed'
                    AND a2.resource='rule_scan')
                    OR a2.action='memory.flag.removed')) AS rule_evidence
            FROM audit_records WHERE tenant_id=:t""",
            t=tenant,
            heartbeat=HEARTBEAT_JOB,
            evidence=2 * rule_interval,
        )
        ctx.maintenance_audits_24h = row["maintenance_24h"]
        ctx.rule_scan_evidence = row["rule_evidence"]
        if row["last_heartbeat"] is not None:
            last = row["last_heartbeat"]
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            ctx.heartbeat_age_minutes = (ctx.now - last).total_seconds() / 60
        ctx.overdue_flaggable_tickets = (
            await one(
                c,
                """SELECT count(*)::int AS n FROM tickets
                WHERE tenant_id=:t AND due_at<now() AND status IN ('open','in_progress')
                AND customer_id IS NOT NULL""",
                t=tenant,
            )
        )["n"]
        for row in await _last_alerts(c, tenant, settings.memory_alert_cooldown_minutes):
            ctx.last_alerts[row["name"]] = row["last_fired_at"]
    return ctx


async def _last_alerts(conn, tenant, cooldown_minutes: int):
    """Most recent firing time per alert rule, for the cooldown check.

    Bounded to the cooldown window: rows older than that cannot change any
    cooldown decision, and audit_records has no TTL — an unbounded scan would
    degrade into a whole-table filter as the table grows.
    """
    rows = await conn.execute(
        text(
            """SELECT substring(action from 'memory.alert.(.*)') AS name,
            max(created_at) AS last_fired_at
            FROM audit_records
            WHERE tenant_id=:t AND action LIKE 'memory.alert.%'
            AND created_at>now()-:cooldown*interval '1 minute'
            GROUP BY 1"""
        ),
        {"t": tenant, "cooldown": cooldown_minutes},
    )
    return rows.mappings().all()


# ---------------------------------------------------------------------------
# Webhook (FR-3): best-effort, small JSON, any failure only logs.
# ---------------------------------------------------------------------------


async def post_webhook(url: str, payload: dict, timeout: float) -> None:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()


# ---------------------------------------------------------------------------
# Scanner: the worker owns one instance; it keeps R3 state and the timer.
# ---------------------------------------------------------------------------


class AlertScanner:
    """Periodic alert scan: collect -> evaluate -> cooldown -> audit/webhook."""

    def __init__(
        self,
        engine,
        settings,
        *,
        embedded: bool,
        webhook: WebhookSender = post_webhook,
    ):
        self.engine, self.settings = engine, settings
        self.embedded = embedded
        self.webhook = webhook
        # R3's last-two backlog samples; restart = resample from scratch.
        self.backlog_samples: list[int] = []
        self.last_scan: float | None = None

    def due(self) -> bool:
        """Idle-cycle gate, mirroring the worker's rule_scan_due pattern."""
        if not self.settings.memory_alert_enabled:
            return False
        interval = self.settings.memory_alert_scan_interval_minutes
        if interval <= 0:
            return False
        return self.last_scan is None or (time.monotonic() - self.last_scan >= interval * 60)

    async def scan(self) -> list[str]:
        """One alert pass; returns the fired rule names (after cooldown).

        Attempt-stamped up front like the maintenance pass: a failing scan
        retries at the next interval, not on every idle cycle. Alert audits
        commit on one transaction; webhook delivery happens after the commit
        and any delivery failure only logs.
        """
        self.last_scan = time.monotonic()
        if not self.settings.memory_alert_enabled:
            return []
        settings = self.settings
        tenant = settings.tenant_id
        ctx = await collect(self.engine, settings, embedded=self.embedded)
        alerts = evaluate(ctx, settings, self.backlog_samples)
        cooldown = settings.memory_alert_cooldown_minutes
        fired = [
            alert
            for alert in alerts
            if not cooldown_active(ctx.last_alerts.get(alert.name), ctx.now, cooldown)
        ]
        if not fired:
            return []
        async with self.engine.begin() as c:
            for alert in fired:
                await audit(
                    c,
                    tenant,
                    "memory",
                    alert.action,
                    alert.name,
                    value=alert.value,
                    threshold=alert.threshold,
                    window=alert.window,
                )
        url = settings.memory_alert_webhook_url
        if url:
            for alert in fired:
                payload = {
                    "rule": alert.name,
                    "tenant": tenant,
                    "value": alert.value,
                    "threshold": alert.threshold,
                    "window": alert.window,
                    "at": ctx.now.isoformat(),
                }
                try:
                    await self.webhook(url, payload, settings.memory_alert_webhook_timeout_seconds)
                except Exception:  # delivery must never fail the scan
                    logger.warning(
                        "Memory alert webhook delivery failed (rule=%s)",
                        alert.name,
                        exc_info=True,
                    )
        logger.warning("Memory alerts fired: %s", ",".join(alert.name for alert in fired))
        return [alert.name for alert in fired]
