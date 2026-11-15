"""Monitoring service: scan, persist snapshots, emit notification transitions.

One loop owns every cadence (fast / business / integration / daily). Requests
never trigger probes: the checklist endpoint reads ``monitor_checks`` only, so a
slow object store cannot stall the console.
"""

import asyncio
import hashlib
import json
import logging
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import SQLAlchemyError

from agent_platform.core_platform.platform_services.persistence.store import (
    execute,
    many,
    one,
)

from .checks import PLATFORM_REGISTRATIONS
from .registry import (
    NON_PASS,
    NOTIFICATION_SEVERITIES,
    Check,
    CheckRegistry,
    CollectorContext,
    CollectorError,
    Registration,
    allowed_evidence,
)

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("active", "acknowledged", "suppressed")

# Console group order and labels. The backend owns the vocabulary so the client
# never hard-codes a check-to-group mapping.
GROUP_TITLES: dict[str, str] = {
    "middleware": "中间件与基础设施",
    "models": "模型渠道",
    "queues": "队列与后台任务",
    "integration": "外部集成",
    "business": "业务链路",
}
GROUP_ORDER = tuple(GROUP_TITLES)

UPSERT_CHECK = """
    INSERT INTO monitor_checks(
        check_id, tenant_id, scope, object_id, check_type, severity, status,
        summary, evidence, action_label, action_route, streak,
        first_seen_at, checked_at)
    VALUES(
        :check_id, :tenant_id, :scope, :object_id, :check_type, :severity, :status,
        :summary, CAST(:evidence AS jsonb), :action_label, :action_route, :streak,
        :first_seen_at, now())
    ON CONFLICT (check_id, scope, object_id, tenant_id) DO UPDATE SET
        check_type = EXCLUDED.check_type, severity = EXCLUDED.severity,
        status = EXCLUDED.status, summary = EXCLUDED.summary,
        evidence = EXCLUDED.evidence, action_label = EXCLUDED.action_label,
        action_route = EXCLUDED.action_route, streak = EXCLUDED.streak,
        first_seen_at = EXCLUDED.first_seen_at,
        changed_at = CASE
            WHEN monitor_checks.status IS DISTINCT FROM EXCLUDED.status
            THEN now() ELSE monitor_checks.changed_at END,
        checked_at = now()
"""


@dataclass(frozen=True)
class Outcome:
    check: Check
    tenant: str
    status: str
    summary: str
    evidence: dict
    streak: int
    first_seen_at: datetime

    @property
    def scope(self) -> str:
        return "tenant" if self.check.scoped else "global"

    @property
    def row_tenant(self) -> str:
        return self.tenant if self.check.scoped else ""

    @property
    def key(self) -> tuple[str, str, str, str]:
        return _row_key(self.check, self.tenant)

    @property
    def fingerprint(self) -> str:
        raw = f"{self.check.id}|{self.scope}||{self.row_tenant}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()


class MonitoringService:
    def __init__(self, engine, settings, registry: CheckRegistry | None = None) -> None:
        self.engine, self.settings = engine, settings
        self.registry = registry or CheckRegistry()
        if registry is None:
            self.registry.register_all(PLATFORM_REGISTRATIONS)
        self.stop_event = asyncio.Event()
        self._last_run: dict[str, float] = {}
        self._last_prune = 0.0

    # -- registration -----------------------------------------------------

    def register(self, registrations: tuple[Registration, ...]) -> None:
        self.registry.register_all(registrations)

    # -- loop -------------------------------------------------------------

    async def serve(self) -> None:
        """Idle-cycle scanner; mirrors the memory worker's cadence gating."""

        if not self.settings.monitor_enabled:
            return
        while not self.stop_event.is_set():
            try:
                await self._record_heartbeat()
                await self.scan()
                await self._prune_if_due()
            except (SQLAlchemyError, OSError, TimeoutError) as exc:
                logger.warning("Monitoring scan skipped (%s)", type(exc).__name__)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=5)
            except TimeoutError:
                continue

    def stop(self) -> None:
        self.stop_event.set()

    def _interval(self, cadence: str) -> int:
        settings = self.settings
        return {
            "fast": settings.monitor_fast_interval_seconds,
            "business": settings.monitor_business_interval_seconds,
            "integration": settings.monitor_integration_interval_seconds,
            "probe": settings.monitor_model_probe_interval_seconds,
            "daily": settings.monitor_daily_interval_seconds,
        }.get(cadence, settings.monitor_fast_interval_seconds)

    def _due(self, check: Check) -> bool:
        last = self._last_run.get(check.id)
        return last is None or time.monotonic() - last >= self._interval(check.cadence)

    # -- scan -------------------------------------------------------------

    async def scan(self, *, force: bool = False, tenant: str | None = None) -> dict:
        tenant = tenant or self.settings.tenant_id
        started = time.monotonic()
        scan_id = await self._open_scan(tenant)
        previous = await self._load_snapshot()
        outcomes: list[Outcome] = []
        for registration in self.registry.registrations:
            check = registration.check
            if not force and not self._due(check):
                continue
            status, summary, evidence = await self._evaluate(registration, tenant)
            self._last_run[check.id] = time.monotonic()
            prior = previous.get(_row_key(check, tenant))
            streak, first_seen = _streak(status, prior)
            outcomes.append(Outcome(check, tenant, status, summary, evidence, streak, first_seen))
        if outcomes:
            await self._persist(outcomes)
            await self._transitions(outcomes, tenant)
        await self._close_scan(scan_id, outcomes, started)
        return {
            "scan_id": scan_id,
            "checks": len(outcomes),
            "failed": sum(1 for item in outcomes if item.status in NON_PASS),
        }

    async def _evaluate(self, registration: Registration, tenant: str) -> tuple[str, str, dict]:
        context = CollectorContext(self.engine, self.settings, tenant)
        try:
            sample = await registration.collect(context)
            judgment = registration.judge(sample, self.settings)
        except CollectorError as exc:
            return "unknown", "采集失败", allowed_evidence({"error_code": exc.code, **exc.evidence})
        except (SQLAlchemyError, OSError, TimeoutError, ValueError) as exc:
            return "unknown", "采集失败", {"error_code": type(exc).__name__}
        return judgment.status, judgment.summary, allowed_evidence(judgment.evidence)

    async def _load_snapshot(self) -> dict[tuple[str, str, str, str], dict]:
        async with self.engine.connect() as conn:
            rows = await many(conn, "SELECT * FROM monitor_checks")
        return {(r["check_id"], r["scope"], r["object_id"], r["tenant_id"]): r for r in rows}

    async def _persist(self, outcomes: list[Outcome]) -> None:
        async with self.engine.begin() as conn:
            for item in outcomes:
                await execute(
                    conn,
                    UPSERT_CHECK,
                    check_id=item.check.id,
                    tenant_id=item.row_tenant,
                    scope=item.scope,
                    object_id="",
                    check_type=item.check.kind,
                    severity=item.check.severity,
                    status=item.status,
                    summary=item.summary,
                    evidence=json.dumps(item.evidence, default=str),
                    action_label=item.check.action.label,
                    action_route=item.check.action.route,
                    streak=item.streak,
                    first_seen_at=item.first_seen_at,
                )

    async def _close_scan(self, scan_id: int, outcomes: list[Outcome], started: float) -> None:
        async with self.engine.begin() as conn:
            await execute(
                conn,
                """UPDATE monitor_scans SET finished_at = now(), duration_ms = :ms,
                checks_total = :total, checks_failed = :failed WHERE id = :id""",
                id=scan_id,
                ms=int((time.monotonic() - started) * 1000),
                total=len(outcomes),
                failed=sum(1 for item in outcomes if item.status in NON_PASS),
            )

    async def _open_scan(self, tenant: str) -> int:
        async with self.engine.begin() as conn:
            row = await one(
                conn,
                """INSERT INTO monitor_scans(tenant_id, started_at)
                VALUES(:t, now()) RETURNING id""",
                t=tenant,
            )
        return int(row["id"])

    async def _record_heartbeat(self) -> None:
        async with self.engine.begin() as conn:
            await execute(
                conn,
                """INSERT INTO worker_heartbeats(worker_id, host, started_at, beat_at)
                VALUES('monitor', :host, now(), now())
                ON CONFLICT (worker_id) DO UPDATE SET beat_at = now(), host = EXCLUDED.host""",
                host=socket.gethostname(),
            )

    # -- retention --------------------------------------------------------

    async def _prune_if_due(self) -> None:
        """Drop closed history only; an active fault must never expire.

        Runs on the scanner's own cadence instead of a second scheduler, so a
        single process owns every monitoring write.
        """

        now = time.monotonic()
        if now - self._last_prune < self.settings.monitor_prune_interval_seconds:
            return
        self._last_prune = now
        async with self.engine.begin() as conn:
            await execute(
                conn,
                """DELETE FROM notifications
                WHERE status IN ('resolved', 'suppressed')
                  AND created_at < now() - make_interval(days => :days)""",
                days=self.settings.monitor_notification_retention_days,
            )
            await execute(
                conn,
                """DELETE FROM monitor_scans
                WHERE started_at < now() - make_interval(days => :days)""",
                days=self.settings.monitor_scan_retention_days,
            )

    # -- notification transitions -----------------------------------------

    def _confirm_rounds(self, severity: str) -> int:
        settings = self.settings
        return {
            "P0": settings.monitor_p0_confirm_rounds,
            "P1": settings.monitor_p1_confirm_rounds,
            "P2": settings.monitor_p2_confirm_rounds,
        }.get(severity, settings.monitor_p2_confirm_rounds)

    async def _transitions(self, outcomes: list[Outcome], tenant: str) -> None:
        async with self.engine.begin() as conn:
            for item in outcomes:
                if item.status in ("pass", "not_configured"):
                    # Recovery needs N consecutive healthy rounds; resolving an
                    # absent notification is a no-op, so this stays idempotent.
                    if (
                        item.status == "not_configured"
                        or item.streak >= self.settings.monitor_recover_rounds
                    ):
                        await self._resolve(conn, item)
                elif item.status == "unknown":
                    # A collector that could not measure proves nothing: keep
                    # the previous verdict and its notification untouched,
                    # otherwise a broken collector silently clears a real alert.
                    continue
                elif not self._notifies(item.check, item.status):
                    # A state the policy does not alert on must not keep a bell
                    # lit forever, including notifications an earlier policy
                    # already opened.
                    await self._resolve(conn, item, notify=False)
                elif item.streak >= self._confirm_rounds(item.check.severity):
                    await self._open(conn, item)
            await self._remind(conn, tenant)

    @staticmethod
    def _notifies(check, status: str) -> bool:
        """Whether this state deserves the operator's attention.

        ``kind`` is what keeps the bell honest: ``optional`` add-ons belong in
        the checklist only, ``conditional`` checks alert when they fail, and
        ``required`` checks also alert when degraded. Without this gate every
        idle-but-fine state — a stale manual probe, an uninstalled extension
        that has a working fallback — rings forever and the bell gets ignored.
        """

        if status not in NON_PASS or check.severity not in NOTIFICATION_SEVERITIES:
            return False
        if check.kind == "optional":
            return False
        if check.kind == "conditional":
            return status == "fail"
        return True

    async def _resolve(self, conn, item: Outcome, *, notify: bool = True) -> None:
        active = await many(
            conn,
            """SELECT id FROM notifications
            WHERE tenant_id = :t AND fingerprint = :f AND status = ANY(CAST(:statuses AS text[]))""",
            t=item.row_tenant,
            f=item.fingerprint,
            statuses=list(ACTIVE_STATUSES),
        )
        if not active:
            return
        await execute(
            conn,
            """UPDATE notifications SET status = 'resolved', resolved_at = now()
            WHERE tenant_id = :t AND fingerprint = :f AND status = ANY(CAST(:statuses AS text[]))""",
            t=item.row_tenant,
            f=item.fingerprint,
            statuses=list(ACTIVE_STATUSES),
        )
        if notify:
            await self._insert_notification(conn, item, kind="recovered", status="resolved")

    async def _open(self, conn, item: Outcome) -> None:
        existing = await one(
            conn,
            """SELECT id, severity FROM notifications
            WHERE tenant_id = :t AND fingerprint = :f AND status = ANY(CAST(:statuses AS text[]))
            ORDER BY created_at DESC LIMIT 1""",
            t=item.row_tenant,
            f=item.fingerprint,
            statuses=list(ACTIVE_STATUSES),
        )
        if existing is not None:
            if existing["severity"] == item.check.severity:
                return
            await execute(
                conn,
                """UPDATE notifications SET status = 'resolved', resolved_at = now()
                WHERE id = :id""",
                id=existing["id"],
            )
        await self._insert_notification(conn, item, kind="opened", status="active")

    async def _insert_notification(self, conn, item: Outcome, *, kind: str, status: str) -> None:
        now = datetime.now(UTC)
        await execute(
            conn,
            """INSERT INTO notifications(
                id, tenant_id, check_id, scope, object_id, fingerprint, kind, severity,
                status, title, impact, evidence, source, action_label, action_route,
                first_seen_at, last_seen_at, resolved_at)
            VALUES(
                :id, :tenant_id, :check_id, :scope, '', :fingerprint, :kind, :severity,
                :status, :title, :impact, CAST(:evidence AS jsonb), 'monitor',
                :action_label, :action_route, :first_seen, :first_seen, :resolved_at)""",
            id=uuid4(),
            tenant_id=item.row_tenant,
            check_id=item.check.id,
            scope=item.scope,
            fingerprint=item.fingerprint,
            kind=kind,
            severity=item.check.severity,
            status=status,
            title=item.check.title or item.check.id,
            impact=item.summary,
            evidence=json.dumps(item.evidence, default=str),
            action_label=item.check.action.label,
            action_route=item.check.action.route,
            first_seen=now if kind != "opened" else item.first_seen_at,
            resolved_at=now if kind == "recovered" else None,
        )

    async def _remind(self, conn, tenant: str) -> None:
        rows = await many(
            conn,
            """SELECT * FROM notifications
            WHERE tenant_id = :t AND status = 'active' AND severity IN ('P0', 'P1')
              AND COALESCE(reminder_sent_at, created_at)
                  < now() - make_interval(mins => :minutes)""",
            t=tenant,
            minutes=self.settings.monitor_reminder_minutes,
        )
        for row in rows:
            await execute(
                conn,
                """INSERT INTO notifications(
                    id, tenant_id, check_id, scope, object_id, fingerprint, kind, severity,
                    status, title, impact, evidence, source, action_label, action_route,
                    first_seen_at, last_seen_at)
                VALUES(
                    :id, :tenant_id, :check_id, :scope, :object_id, :fingerprint, 'reminder',
                    :severity, 'active', :title, :impact, CAST(:evidence AS jsonb), :source,
                    :action_label, :action_route, now(), now())""",
                id=uuid4(),
                tenant_id=row["tenant_id"],
                check_id=row["check_id"],
                scope=row["scope"],
                object_id=row["object_id"],
                fingerprint=row["fingerprint"],
                severity=row["severity"],
                title=row["title"],
                impact=row["impact"],
                evidence=json.dumps(row["evidence"], default=str),
                source=row["source"],
                action_label=row["action_label"],
                action_route=row["action_route"],
            )
            await execute(
                conn,
                "UPDATE notifications SET reminder_sent_at = now() WHERE id = :id",
                id=row["id"],
            )

    # -- read models -------------------------------------------------------

    async def checklist(self, tenant: str) -> dict:
        async with self.engine.connect() as conn:
            rows = await many(
                conn,
                """SELECT * FROM monitor_checks
                WHERE tenant_id IN (:t, '') ORDER BY check_id""",
                t=tenant,
            )
            last = await one(
                conn,
                """SELECT finished_at FROM monitor_scans
                WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1""",
            )
        groups: dict[str, dict] = {}
        counts = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        now = datetime.now(UTC)
        stale_after = self.settings.monitor_stale_after_seconds
        for row in rows:
            registration = self.registry.get(row["check_id"])
            group_id = registration.check.group if registration else "other"
            group = groups.setdefault(
                group_id,
                {
                    "id": group_id,
                    "title": GROUP_TITLES.get(group_id, group_id),
                    "status": "healthy",
                    "items": [],
                },
            )
            checked_at = row["checked_at"]
            age = (now - checked_at).total_seconds() if checked_at else stale_after + 1
            stale = age > max(
                stale_after,
                self._interval(registration.check.cadence if registration else "fast") + 30,
            )
            item = {
                "check_id": row["check_id"],
                "type": row["check_type"],
                "status": row["status"],
                "severity": row["severity"],
                "title": registration.check.title if registration else row["check_id"],
                "summary": row["summary"],
                "evidence": row["evidence"],
                "checked_at": checked_at,
                "first_seen_at": row["first_seen_at"],
                "changed_at": row["changed_at"],
                "stale": stale,
                "action": (
                    {"label": row["action_label"], "route": row["action_route"]}
                    if row["action_route"]
                    else None
                ),
            }
            group["items"].append(item)
            # Optional checks are capability gaps, not degradation: an unset external
            # parser must not turn the whole deployment yellow, so they are listed
            # (and counted in nothing) without touching group or overall status.
            # Same predicate as the bell badge, so the numbers always agree.
            if row["status"] in NON_PASS and _is_blocking(self.registry, row["check_id"]):
                group["status"] = "degraded"
                if row["severity"] in counts:
                    counts[row["severity"]] += 1
        return {
            "overall_status": _overall(rows, self.registry),
            "generated_at": now,
            "scan_age_seconds": (
                int((now - last["finished_at"]).total_seconds()) if last else None
            ),
            "counts": counts,
            "groups": sorted(
                groups.values(),
                key=lambda group: (
                    GROUP_ORDER.index(group["id"])
                    if group["id"] in GROUP_ORDER
                    else len(GROUP_ORDER)
                ),
            ),
        }

    async def unread_count(self, tenant: str) -> int:
        """Badge = how many checks need attention right now.

        Derived from ``monitor_checks``, the same snapshot the checklist counts,
        so the bell and the panel can never disagree. It used to read the
        ``notifications`` feed instead, which is a *transition* log: a
        conditional check that only warns never produces a row there, and
        marking a row read blanked the badge while the failure was still live.
        Read state now only affects the feed (unread tab, dimmed rows).
        """

        async with self.engine.connect() as conn:
            rows = await many(
                conn,
                # Platform-wide checks live under the empty tenant, exactly like
                # the checklist query, so the badge counts them too.
                """SELECT check_id, severity, status FROM monitor_checks
                WHERE tenant_id IN (:t, '')""",
                t=tenant,
            )
        return sum(
            1
            for row in rows
            if row["status"] in NON_PASS
            and row["severity"] != "P3"
            and _is_blocking(self.registry, row["check_id"])
        )

    @staticmethod
    def _notification_filter(unread: bool | None) -> str:
        """Shared WHERE for the feed and its total.

        ``unread`` is tri-state: NULL means "no filter", TRUE means "only rows
        nobody has opened yet". Cast keeps asyncpg from guessing the type of an
        untyped NULL parameter.
        """

        return """tenant_id IN (:t, '')
                  AND (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
                  AND (CAST(:severity AS text) IS NULL OR severity = CAST(:severity AS text))
                  AND (
                    CAST(:unread AS boolean) IS NULL
                    OR (CAST(:unread AS boolean) AND read_at IS NULL)
                  )"""

    async def notifications(
        self,
        tenant: str,
        *,
        status: str | None = None,
        severity: str | None = None,
        unread: bool | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> dict:
        where = self._notification_filter(unread)
        params = {"t": tenant, "status": status, "severity": severity, "unread": unread}
        async with self.engine.connect() as conn:
            items = await many(
                conn,
                f"""SELECT id, check_id, kind, severity, status, read_at, title, impact,
                evidence, source, action_label, action_route, first_seen_at, last_seen_at,
                resolved_at, created_at
                FROM notifications
                WHERE {where}
                ORDER BY created_at DESC LIMIT :limit OFFSET :offset""",
                **params,
                limit=limit,
                offset=offset,
            )
            total = await one(
                conn,
                f"SELECT count(*)::int AS n FROM notifications WHERE {where}",
                **params,
            )
        return {"items": items, "total": int(total["n"])}

    async def mark_read(self, tenant: str, notification_id: UUID) -> dict:
        # Idempotent: re-reading an already-read row keeps the first timestamp
        # instead of rewriting history on every click.
        async with self.engine.begin() as conn:
            row = await one(
                conn,
                """UPDATE notifications SET read_at = COALESCE(read_at, now())
                WHERE id = :id AND tenant_id IN (:t, '')
                RETURNING id, read_at""",
                id=notification_id,
                t=tenant,
            )
        if row is None:
            raise LookupError("notification_not_found")
        return {"id": str(row["id"]), "read_at": row["read_at"]}

    async def mark_all_read(self, tenant: str) -> dict:
        async with self.engine.begin() as conn:
            rows = await many(
                conn,
                """UPDATE notifications SET read_at = now()
                WHERE tenant_id IN (:t, '') AND read_at IS NULL
                RETURNING id""",
                t=tenant,
            )
        return {"updated": len(rows)}

    async def acknowledge(self, tenant: str, notification_id: UUID, actor: str) -> dict:
        async with self.engine.begin() as conn:
            row = await one(
                conn,
                """UPDATE notifications SET status = 'acknowledged',
                acknowledged_by = :actor, acknowledged_at = now()
                WHERE id = :id AND tenant_id IN (:t, '') AND status = 'active'
                RETURNING id, status""",
                id=notification_id,
                t=tenant,
                actor=actor,
            )
        if row is None:
            raise LookupError("notification_not_found")
        return {"id": str(row["id"]), "status": row["status"]}

    async def suppress(self, tenant: str, notification_id: UUID, minutes: int, actor: str) -> dict:
        async with self.engine.begin() as conn:
            row = await one(
                conn,
                """UPDATE notifications SET status = 'suppressed',
                suppressed_until = now() + make_interval(mins => :minutes),
                acknowledged_by = :actor, acknowledged_at = now()
                WHERE id = :id AND tenant_id IN (:t, '')
                  AND status IN ('active', 'acknowledged')
                RETURNING id, status""",
                id=notification_id,
                t=tenant,
                minutes=minutes,
                actor=actor,
            )
        if row is None:
            raise LookupError("notification_not_found")
        return {"id": str(row["id"]), "status": row["status"]}


def _row_key(check: Check, tenant: str) -> tuple[str, str, str, str]:
    """Storage key: deployment-wide checks share one row, the rest are per tenant."""

    if check.scoped:
        return (check.id, "tenant", "", tenant)
    return (check.id, "global", "", "")


def _streak(status: str, prior: dict | None) -> tuple[int, datetime]:
    now = datetime.now(UTC)
    if prior is None:
        return (0 if status == "pass" else 1, now)
    if prior["status"] == status:
        return (int(prior["streak"]) + 1, prior["first_seen_at"])
    return (1 if status != "pass" else 0, now)


def _is_blocking(registry: CheckRegistry, check_id: str) -> bool:
    """Whether a non-pass state on this check should count against the system.

    Optional capabilities (an unset external parser, a missing vector extension
    with a keyword fallback) are listed in the checklist but never drag the
    overall status or the badge down. Unknown registrations stay blocking: a
    check that vanished from the code is a real problem, not a choice.
    """

    registration = registry.get(check_id)
    return registration is None or registration.check.kind != "optional"


def _overall(rows: list[dict], registry: CheckRegistry) -> str:
    def blocking(row: dict) -> bool:
        return _is_blocking(registry, row["check_id"])

    if any(
        row["status"] == "fail" and row["severity"] == "P0" and blocking(row) for row in rows
    ):
        return "down"
    if any(row["status"] in NON_PASS and blocking(row) for row in rows):
        return "degraded"
    if any(row["status"] == "unknown" and blocking(row) for row in rows):
        return "unknown"
    return "healthy"


__all__ = ["MonitoringService", "Outcome"]
