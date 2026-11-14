"""Capability-level checks registered by the application composition root.

``core_platform`` must not import business capabilities, so the backlog probes
that read memory / knowledge / channel / open-platform tables live here and are
registered onto the monitoring service at construction time.
"""

from agent_platform.core_platform.platform_services.monitoring.registry import (
    Action,
    Cadence,
    Check,
    CheckKind,
    CollectorContext,
    Judgment,
    Registration,
    Severity,
)
from agent_platform.core_platform.platform_services.persistence.store import one
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

OBSERVABILITY = Action("打开可观测性", "/observability")
KNOWLEDGE = Action("查看知识库", "/knowledge")
HANDOFF = Action("查看人工接管", "/handoff")


def _check(
    check_id: str,
    group: str,
    kind: CheckKind,
    severity: Severity,
    cadence: Cadence,
    title: str,
    action: Action,
) -> Check:
    return Check(
        id=check_id,
        group=group,
        kind=kind,
        severity=severity,
        cadence=cadence,
        action=action,
        scoped=True,
        title=title,
    )


async def queue_memory(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            """SELECT count(*)::int AS pending,
            EXTRACT(EPOCH FROM now() - min(created_at)) AS oldest_seconds,
            count(*) FILTER (WHERE status = 'failed'
                AND updated_at > now() - interval '24 hours')::int AS failed
            FROM memory_tasks
            WHERE tenant_id = :t AND status IN ('pending', 'running')""",
            t=ctx.tenant,
        )
    return _queue_sample(row, row["failed"])


async def queue_knowledge(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            """SELECT count(*)::int AS pending,
            EXTRACT(EPOCH FROM now() - min(created_at)) AS oldest_seconds,
            count(*) FILTER (WHERE status = 'failed'
                AND updated_at > now() - interval '24 hours')::int AS failed
            FROM knowledge_tasks
            WHERE tenant_id = :t AND status IN ('queued', 'running')""",
            t=ctx.tenant,
        )
        beat = await one(
            conn,
            """SELECT EXTRACT(EPOCH FROM now() - beat_at) AS age_seconds
            FROM worker_heartbeats WHERE worker_id = 'knowledge'""",
        )
    sample = _queue_sample(row, row["failed"])
    # -1 means the role never beat at all, so a backlog has no consumer. The
    # queue age alone cannot tell "worker down" from "worker falling behind".
    sample["worker_age_seconds"] = (
        -1.0 if beat is None else float(beat["age_seconds"] or 0)
    )
    return sample


async def queue_channel(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        inbound = await one(
            conn,
            """SELECT count(*)::int AS pending,
            EXTRACT(EPOCH FROM now() - min(created_at)) AS oldest_seconds
            FROM channel_inbound_events
            WHERE tenant_id = :t AND status = 'pending'""",
            t=ctx.tenant,
        )
        delivery = await one(
            conn,
            """SELECT count(*)::int AS pending,
            EXTRACT(EPOCH FROM now() - min(d.created_at)) AS oldest_seconds,
            count(*) FILTER (WHERE d.status = 'failed'
                AND d.updated_at > now() - interval '24 hours')::int AS failed
            FROM channel_deliveries d JOIN channels c ON c.id = d.channel_id
            WHERE c.tenant_id = :t AND d.status IN ('pending', 'running')""",
            t=ctx.tenant,
        )
    pending = int(inbound["pending"]) + int(delivery["pending"])
    ages = [
        float(value)
        for value in (inbound["oldest_seconds"], delivery["oldest_seconds"])
        if value is not None
    ]
    return {
        "pending": pending,
        "oldest_seconds": max(ages) if ages else 0.0,
        "failed": delivery["failed"],
    }


async def queue_open_platform(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            """SELECT count(*)::int AS pending,
            EXTRACT(EPOCH FROM now() - min(d.created_at)) AS oldest_seconds,
            count(*) FILTER (WHERE d.status = 'failed'
                AND d.updated_at > now() - interval '24 hours')::int AS failed
            FROM open_deliveries d JOIN open_applications a ON a.id = d.app_id
            WHERE a.tenant_id = :t AND d.status IN ('pending', 'running')""",
            t=ctx.tenant,
        )
    return _queue_sample(row, row["failed"])


def _queue_sample(row: dict, failed: int) -> dict:
    oldest = row["oldest_seconds"]
    return {
        "pending": int(row["pending"]),
        "oldest_seconds": float(oldest) if oldest is not None else 0.0,
        "failed": int(failed or 0),
    }


async def business_run_failure_rate(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            """SELECT count(*)::int AS samples,
            count(*) FILTER (WHERE status = 'failed')::int AS failed
            FROM runtime_runs
            WHERE tenant_id = :t AND created_at > now() - interval '24 hours'""",
            t=ctx.tenant,
        )
    return dict(row)


async def business_tool_failure_rate(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            """SELECT count(*)::int AS samples,
            count(*) FILTER (WHERE e.data->>'ok' = 'false')::int AS failed
            FROM runtime_events e JOIN runtime_runs r ON r.id = e.run_id
            WHERE r.tenant_id = :t AND e.type = 'tool.completed'
              AND e.created_at > now() - interval '24 hours'""",
            t=ctx.tenant,
        )
    return dict(row)


async def business_human_takeover(ctx: CollectorContext) -> dict:
    async with ctx.engine.connect() as conn:
        row = await one(
            conn,
            """SELECT count(*)::int AS waiting,
            EXTRACT(EPOCH FROM now() - min(created_at)) AS oldest_seconds
            FROM handoffs
            WHERE tenant_id = :t AND status IN ('waiting', 'active')""",
            t=ctx.tenant,
        )
    oldest = row["oldest_seconds"]
    return {
        "waiting": int(row["waiting"]),
        "oldest_seconds": float(oldest) if oldest is not None else 0.0,
    }


def _judge_queue(sample: dict, settings: Settings, label: str) -> Judgment:
    pending = int(sample.get("pending") or 0)
    oldest = float(sample.get("oldest_seconds") or 0)
    evidence = {
        "pending": pending,
        "oldest_seconds": round(oldest),
        "failed": sample.get("failed", 0),
    }
    if not pending:
        return Judgment("pass", f"{label}队列空闲", {"pending": 0})
    if oldest > settings.monitor_queue_fail_age_seconds:
        return Judgment("fail", f"{label}队列积压过久", evidence)
    if oldest > settings.monitor_queue_warn_age_seconds:
        return Judgment("warn", f"{label}队列存在积压", evidence)
    return Judgment("pass", f"{label}队列正常", evidence)


def judge_queue_memory(sample: dict, settings: Settings) -> Judgment:
    return _judge_queue(sample, settings, "记忆任务")


def judge_queue_knowledge(sample: dict, settings: Settings) -> Judgment:
    judgment = _judge_queue(sample, settings, "知识任务")
    if judgment.status != "fail":
        return judgment
    age = float(sample.get("worker_age_seconds", -1))
    evidence = {**judgment.evidence, "worker_age_seconds": round(age, 1)}
    if age < 0:
        return Judgment("fail", "知识任务积压：消费进程未启动", evidence)
    if age > settings.monitor_worker_heartbeat_timeout_seconds:
        return Judgment("fail", "知识任务积压：消费进程心跳超时", evidence)
    return Judgment("fail", judgment.summary, evidence)


def judge_queue_channel(sample: dict, settings: Settings) -> Judgment:
    return _judge_queue(sample, settings, "渠道消息")


def judge_queue_open_platform(sample: dict, settings: Settings) -> Judgment:
    return _judge_queue(sample, settings, "Webhook 投递")


def _judge_rate(
    sample: dict, settings: Settings, label: str, warn: float, fail: float, minimum: int
) -> Judgment:
    samples = int(sample.get("samples") or 0)
    failed = int(sample.get("failed") or 0)
    if samples < minimum:
        return Judgment("unknown", f"{label}样本不足", {"samples": samples})
    rate = failed / samples if samples else 0.0
    evidence = {"samples": samples, "failed": failed, "rate": round(rate, 4)}
    if rate > fail:
        return Judgment("fail", f"{label}失败率过高", evidence)
    if rate > warn:
        return Judgment("warn", f"{label}失败率上升", evidence)
    return Judgment("pass", f"{label}正常", evidence)


def judge_run_failure_rate(sample: dict, settings: Settings) -> Judgment:
    return _judge_rate(
        sample,
        settings,
        "24 小时运行",
        settings.monitor_run_failure_warn_ratio,
        settings.monitor_run_failure_fail_ratio,
        20,
    )


def judge_tool_failure_rate(sample: dict, settings: Settings) -> Judgment:
    return _judge_rate(
        sample,
        settings,
        "工具调用",
        settings.monitor_tool_failure_warn_ratio,
        settings.monitor_tool_failure_fail_ratio,
        20,
    )


def judge_human_takeover(sample: dict, settings: Settings) -> Judgment:
    waiting = int(sample.get("waiting") or 0)
    oldest = float(sample.get("oldest_seconds") or 0)
    evidence = {"waiting": waiting, "oldest_seconds": round(oldest)}
    if not waiting:
        return Judgment("pass", "没有等待接管", {"waiting": 0})
    if oldest > settings.monitor_handoff_fail_age_seconds:
        return Judgment("fail", "人工接管长时间无人处理", evidence)
    if oldest > settings.monitor_handoff_warn_age_seconds:
        return Judgment("warn", "人工接管等待偏久", evidence)
    return Judgment("pass", "人工接管队列正常", evidence)


BUSINESS_REGISTRATIONS: tuple[Registration, ...] = (
    Registration(
        _check(
            "queue.memory", "queues", "conditional", "P1", "fast", "记忆任务队列", OBSERVABILITY
        ),
        queue_memory,
        judge_queue_memory,
    ),
    Registration(
        _check("queue.knowledge", "queues", "conditional", "P1", "fast", "知识任务队列", KNOWLEDGE),
        queue_knowledge,
        judge_queue_knowledge,
    ),
    Registration(
        _check(
            "queue.channel", "queues", "conditional", "P1", "fast", "渠道消息队列", OBSERVABILITY
        ),
        queue_channel,
        judge_queue_channel,
    ),
    Registration(
        _check(
            "queue.open_platform",
            "queues",
            "conditional",
            "P1",
            "fast",
            "Webhook 投递队列",
            OBSERVABILITY,
        ),
        queue_open_platform,
        judge_queue_open_platform,
    ),
    Registration(
        _check(
            "business.run.failure_rate",
            "business",
            "required",
            "P1",
            "business",
            "24 小时运行失败率",
            OBSERVABILITY,
        ),
        business_run_failure_rate,
        judge_run_failure_rate,
    ),
    Registration(
        _check(
            "business.tool.failure_rate",
            "business",
            "required",
            "P2",
            "business",
            "工具调用失败率",
            OBSERVABILITY,
        ),
        business_tool_failure_rate,
        judge_tool_failure_rate,
    ),
    Registration(
        _check(
            "business.human_takeover",
            "business",
            "conditional",
            "P1",
            "fast",
            "人工接管积压",
            HANDOFF,
        ),
        business_human_takeover,
        judge_human_takeover,
    ),
)
