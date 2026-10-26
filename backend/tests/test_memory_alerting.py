"""Phase 7 Task 2 memory alerting — unit tests, no database.

Rule truth tables run against hand-built AlertContext snapshots; the
scanner's cooldown decision and gating are exercised on an engine-less
AlertScanner (scan() short-circuits before any DB access when disabled).
"""

from datetime import UTC, datetime, timedelta

import pytest

from agent_platform.modules.memory.alerting import (
    SEARCH_MIN_CALLS_24H,
    AlertContext,
    AlertScanner,
    cooldown_active,
    evaluate,
    rule_embedding_growing,
    rule_maintenance_silent,
    rule_pending_backlog,
    rule_pending_task_age,
    rule_rule_scan_missed,
    rule_task_failed,
    rule_vector_fallback,
    rule_worker_heartbeat,
)
from agent_platform.modules.memory.worker import MemoryWorker
from agent_platform.settings import Settings

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def make_settings(**overrides):
    return Settings(_env_file=None, **overrides)


def make_ctx(**overrides):
    base = {"now": NOW, "embedded": False}
    return AlertContext(**{**base, **overrides})


# ---------------------------------------------------------------------------
# Settings: eight new scalars, defaults + env override (P7-CM-01)
# ---------------------------------------------------------------------------


def test_alert_settings_defaults_and_env_override(monkeypatch):
    settings = make_settings()
    assert settings.memory_alert_enabled is True
    assert settings.memory_alert_scan_interval_minutes == 15
    assert settings.memory_alert_cooldown_minutes == 60
    assert settings.memory_alert_pending_task_max_age_minutes == 60
    assert settings.memory_alert_pending_backlog_threshold == 500
    assert settings.memory_alert_vector_fallback_rate == pytest.approx(0.2)
    assert settings.memory_alert_webhook_url == ""
    assert settings.memory_alert_webhook_timeout_seconds == 5

    monkeypatch.setenv("AGENT_MEMORY_ALERT_ENABLED", "false")
    monkeypatch.setenv("AGENT_MEMORY_ALERT_SCAN_INTERVAL_MINUTES", "0")
    monkeypatch.setenv("AGENT_MEMORY_ALERT_COOLDOWN_MINUTES", "30")
    monkeypatch.setenv("AGENT_MEMORY_ALERT_PENDING_TASK_MAX_AGE_MINUTES", "120")
    monkeypatch.setenv("AGENT_MEMORY_ALERT_PENDING_BACKLOG_THRESHOLD", "100")
    monkeypatch.setenv("AGENT_MEMORY_ALERT_VECTOR_FALLBACK_RATE", "0.5")
    monkeypatch.setenv("AGENT_MEMORY_ALERT_WEBHOOK_URL", "https://hooks.example/x")
    monkeypatch.setenv("AGENT_MEMORY_ALERT_WEBHOOK_TIMEOUT_SECONDS", "2")
    overridden = Settings(_env_file=None)
    assert overridden.memory_alert_enabled is False
    assert overridden.memory_alert_scan_interval_minutes == 0  # 0 disables scan
    assert overridden.memory_alert_cooldown_minutes == 30
    assert overridden.memory_alert_pending_task_max_age_minutes == 120
    assert overridden.memory_alert_pending_backlog_threshold == 100
    assert overridden.memory_alert_vector_fallback_rate == pytest.approx(0.5)
    assert overridden.memory_alert_webhook_url == "https://hooks.example/x"
    assert overridden.memory_alert_webhook_timeout_seconds == 2


# ---------------------------------------------------------------------------
# R1 task_failed / R2 pending_task_age
# ---------------------------------------------------------------------------


def test_r1_task_failed_truth_table():
    settings = make_settings()
    assert rule_task_failed(make_ctx(failed_tasks_15m=0), settings) is None
    alert = rule_task_failed(make_ctx(failed_tasks_15m=3), settings)
    assert alert is not None
    assert alert.name == "task_failed" and alert.action == "memory.alert.task_failed"
    assert alert.value == 3 and alert.threshold == 0 and alert.window == "15m"


def test_r2_pending_task_age_truth_table():
    settings = make_settings(memory_alert_pending_task_max_age_minutes=60)
    # No pending rows at all -> nothing to alert on.
    assert rule_pending_task_age(make_ctx(), settings) is None
    # Strictly above the threshold; exactly at it stays quiet.
    assert rule_pending_task_age(make_ctx(oldest_pending_task_age_seconds=3600), settings) is None
    alert = rule_pending_task_age(make_ctx(oldest_pending_task_age_seconds=3601.0), settings)
    assert alert is not None
    assert alert.name == "pending_task_age"
    assert alert.value == 3601 and alert.threshold == 3600


# ---------------------------------------------------------------------------
# R3 embedding_growing: two-cycle rising sequence on caller-owned samples
# ---------------------------------------------------------------------------


def test_r3_rising_across_two_consecutive_scans_fires_on_third():
    settings = make_settings()
    samples = []  # restart state: resample from scratch
    assert rule_embedding_growing(make_ctx(embedding_backlog=5), settings, samples) is None
    assert samples == [5]
    # One rise is not enough (宁漏不误).
    assert rule_embedding_growing(make_ctx(embedding_backlog=6), settings, samples) is None
    assert samples == [5, 6]
    alert = rule_embedding_growing(make_ctx(embedding_backlog=7), settings, samples)
    assert alert is not None
    assert alert.name == "embedding_growing"
    assert alert.value == 7 and alert.threshold == 6
    assert samples == [6, 7]  # only the last two readings are kept


def test_r3_not_rising_or_zero_backlog_stays_quiet():
    settings = make_settings()
    # Flat then up: 6 > 5 but 5 > 5 is false -> no fire.
    samples = [5, 5]
    assert rule_embedding_growing(make_ctx(embedding_backlog=6), settings, samples) is None
    # Falling: no fire.
    samples = [9, 7]
    assert rule_embedding_growing(make_ctx(embedding_backlog=8), settings, samples) is None
    # Backlog cleared: never fires, and the samples keep tracking reality.
    samples = [1, 2]
    assert rule_embedding_growing(make_ctx(embedding_backlog=0), settings, samples) is None
    assert samples == [2, 0]


def test_r3_restart_resamples_from_scratch():
    settings = make_settings()
    samples = [5, 6]
    assert rule_embedding_growing(make_ctx(embedding_backlog=7), settings, samples)
    # Restart: state gone, the same rise must not fire for two cycles.
    samples = []
    assert rule_embedding_growing(make_ctx(embedding_backlog=7), settings, samples) is None
    assert rule_embedding_growing(make_ctx(embedding_backlog=8), settings, samples) is None
    assert rule_embedding_growing(make_ctx(embedding_backlog=9), settings, samples)


# ---------------------------------------------------------------------------
# R4 vector_fallback: minimum-call gate + share threshold
# ---------------------------------------------------------------------------


def test_r4_minimum_calls_gate():
    settings = make_settings()
    # 19 calls at 100% fallback: below the gate, stays silent.
    assert (
        rule_vector_fallback(
            make_ctx(search_calls_24h=SEARCH_MIN_CALLS_24H - 1, search_keyword_fallback_24h=19),
            settings,
        )
        is None
    )
    # 20 calls at 21% fallback (> 0.2): fires.
    alert = rule_vector_fallback(
        make_ctx(search_calls_24h=20, search_keyword_fallback_24h=5), settings
    )
    assert alert is not None
    assert alert.name == "vector_fallback"
    assert alert.value == pytest.approx(0.25) and alert.threshold == pytest.approx(0.2)
    # Exactly at the rate (4/20 = 0.2) is not above it: no fire.
    assert (
        rule_vector_fallback(make_ctx(search_calls_24h=20, search_keyword_fallback_24h=4), settings)
        is None
    )


# ---------------------------------------------------------------------------
# R5 maintenance_silent / R6 rule_scan_missed: exemption cases
# ---------------------------------------------------------------------------


def test_r5_exemptions_and_fire():
    settings = make_settings()
    # Zero memory activity -> exempt, even with no maintenance audit.
    assert rule_maintenance_silent(make_ctx(), settings) is None
    # Activity plus maintenance evidence -> quiet.
    assert (
        rule_maintenance_silent(
            make_ctx(memory_task_activity=True, maintenance_audits_24h=1), settings
        )
        is None
    )
    # Activity but no evidence in 24h -> fires.
    alert = rule_maintenance_silent(
        make_ctx(memory_task_activity=True, maintenance_audits_24h=0), settings
    )
    assert alert is not None and alert.name == "maintenance_silent"


def test_r6_exemptions_and_fire():
    settings = make_settings()
    # Disabled rule scan -> exempt.
    off = make_settings(memory_rule_scan_interval_minutes=0)
    assert rule_rule_scan_missed(make_ctx(overdue_flaggable_tickets=3), off) is None
    # No overdue tickets -> exempt even without evidence.
    assert rule_rule_scan_missed(make_ctx(), settings) is None
    # Overdue tickets but fresh evidence -> quiet.
    assert (
        rule_rule_scan_missed(
            make_ctx(overdue_flaggable_tickets=3, rule_scan_evidence=True), settings
        )
        is None
    )
    # Overdue tickets, no evidence in 2x interval -> fires.
    alert = rule_rule_scan_missed(
        make_ctx(overdue_flaggable_tickets=3, rule_scan_evidence=False), settings
    )
    assert alert is not None
    assert alert.name == "rule_scan_missed"
    assert alert.value == 3 and alert.window == "30m"  # 2x the 15m interval


# ---------------------------------------------------------------------------
# R7 pending_backlog / R8 worker_heartbeat
# ---------------------------------------------------------------------------


def test_r7_pending_backlog_threshold():
    settings = make_settings(memory_alert_pending_backlog_threshold=500)
    assert rule_pending_backlog(make_ctx(pending_items=500), settings) is None
    alert = rule_pending_backlog(make_ctx(pending_items=501), settings)
    assert alert is not None
    assert alert.value == 501 and alert.threshold == 500


def test_r8_standalone_only():
    settings = make_settings()
    # Embedded: API alive => worker alive, the rule never fires.
    assert (
        rule_worker_heartbeat(make_ctx(embedded=True, heartbeat_age_minutes=None), settings) is None
    )
    assert (
        rule_worker_heartbeat(make_ctx(embedded=True, heartbeat_age_minutes=9999), settings) is None
    )
    # Standalone: never-seen heartbeat fires; fresh heartbeat is quiet.
    assert rule_worker_heartbeat(make_ctx(heartbeat_age_minutes=None), settings) is not None
    assert rule_worker_heartbeat(make_ctx(heartbeat_age_minutes=29), settings) is None
    alert = rule_worker_heartbeat(make_ctx(heartbeat_age_minutes=31), settings)
    assert alert is not None and alert.threshold == 30


# ---------------------------------------------------------------------------
# Cooldown decision (pure part) and scanner gating
# ---------------------------------------------------------------------------


def test_cooldown_active_pure_logic():
    assert cooldown_active(None, NOW, 60) is False
    assert cooldown_active(NOW - timedelta(minutes=59), NOW, 60) is True
    assert cooldown_active(NOW - timedelta(minutes=61), NOW, 60) is False


@pytest.mark.asyncio
async def test_scanner_master_switch_off_never_touches_db():
    settings = make_settings(memory_alert_enabled=False)
    scanner = AlertScanner(None, settings, embedded=False)
    assert scanner.due() is False
    assert await scanner.scan() == []  # engine=None proves no DB access


@pytest.mark.asyncio
async def test_scanner_interval_zero_disables():
    settings = make_settings(memory_alert_scan_interval_minutes=0)
    scanner = AlertScanner(None, settings, embedded=False)
    assert scanner.due() is False


def test_scanner_due_first_pass_at_startup():
    scanner = AlertScanner(None, make_settings(), embedded=False)
    assert scanner.due() is True


def test_worker_wires_scanner_and_heartbeat_mode():
    # Embedded (default): heartbeat record skipped, R8 exempt downstream.
    embedded = MemoryWorker(None, None, make_settings())
    assert embedded.embedded is True
    assert embedded.heartbeat_audit_due() is False
    assert embedded.alert_scan_due() is True
    # Standalone: heartbeat due immediately (no record yet).
    standalone = MemoryWorker(None, None, make_settings(embedded_worker=False))
    assert standalone.embedded is False
    assert standalone.heartbeat_audit_due() is True
    # Master switch off: no scan, no heartbeat.
    disabled = MemoryWorker(None, None, make_settings(memory_alert_enabled=False))
    assert disabled.alert_scan_due() is False
    assert disabled.heartbeat_audit_due() is False
    # Explicit override wins over the settings flag.
    forced = MemoryWorker(None, None, make_settings(), embedded=False)
    assert forced.embedded is False


def test_evaluate_runs_all_rules_and_updates_r3_state():
    settings = make_settings()
    samples = [1, 2]
    ctx = make_ctx(
        failed_tasks_15m=1,
        embedding_backlog=3,
        heartbeat_age_minutes=10,
    )
    names = {alert.name for alert in evaluate(ctx, settings, samples)}
    assert {"task_failed", "embedding_growing"} <= names
    assert samples == [2, 3]
