"""Status judgements for platform checks.

Pure functions only: no I/O, no clock except what the collector already put in
the sample, and every threshold comes from ``Settings``. That keeps the truth
tables cheap to test and makes the numbers tunable without a code change.
"""

from ..platform_settings.settings import Settings
from .registry import Judgment


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def judge_pg_connection(sample: dict, settings: Settings) -> Judgment:
    latency = int(_float(sample.get("latency_ms")))
    limit = settings.monitor_pg_latency_warn_ms
    if latency > limit:
        return Judgment("warn", "数据库查询变慢", {"latency_ms": latency, "threshold": limit})
    return Judgment("pass", "数据库连接正常", {"latency_ms": latency})


def judge_pg_migration(sample: dict, settings: Settings) -> Judgment:
    evidence = {
        "revision": sample.get("revision", ""),
        "heads": ",".join(sample.get("heads") or []),
    }
    if sample.get("multi_head"):
        return Judgment("fail", "迁移存在多个 head", evidence)
    if sample.get("behind"):
        return Judgment("fail", "数据库迁移版本落后于代码", evidence)
    return Judgment("pass", "数据库迁移版本一致", evidence)


def judge_pgvector(sample: dict, settings: Settings) -> Judgment:
    version = sample.get("version", "")
    if not sample.get("installed"):
        return Judgment("warn", "pgvector 扩展未安装，向量检索降级为关键词检索", {})
    return Judgment("pass", "pgvector 扩展可用", {"version": version})


def judge_db_pool(sample: dict, settings: Settings) -> Judgment:
    ratio = _ratio(_float(sample.get("checked_out")), _float(sample.get("capacity")))
    evidence = {"checked_out": sample.get("checked_out"), "capacity": sample.get("capacity")}
    if ratio >= settings.monitor_pool_fail_ratio:
        return Judgment("fail", "数据库连接池已耗尽", {**evidence, "ratio": round(ratio, 3)})
    if ratio >= settings.monitor_pool_warn_ratio:
        return Judgment("warn", "数据库连接池使用率偏高", {**evidence, "ratio": round(ratio, 3)})
    return Judgment("pass", "数据库连接池正常", evidence)


def _judge_capacity(sample: dict, label: str, warn_ratio: float, fail_ratio: float) -> Judgment:
    """Shared host-capacity judgement: warn and fail are both upper bounds."""

    percent = _float(sample.get("percent"))
    evidence = {
        "percent": round(percent, 1),
        "warn_threshold": round(warn_ratio * 100),
        "fail_threshold": round(fail_ratio * 100),
        "source": sample.get("source", ""),
    }
    if percent >= fail_ratio * 100:
        return Judgment("fail", f"{label}过高", evidence)
    if percent >= warn_ratio * 100:
        return Judgment("warn", f"{label}偏高", evidence)
    return Judgment("pass", f"{label}正常", evidence)


def judge_cpu_usage(sample: dict, settings: Settings) -> Judgment:
    return _judge_capacity(
        sample,
        "CPU 使用率",
        settings.monitor_cpu_warn_ratio,
        settings.monitor_cpu_fail_ratio,
    )


def judge_memory_usage(sample: dict, settings: Settings) -> Judgment:
    return _judge_capacity(
        sample,
        "内存使用率",
        settings.monitor_memory_warn_ratio,
        settings.monitor_memory_fail_ratio,
    )


def judge_required_config(sample: dict, settings: Settings) -> Judgment:
    missing = sample.get("missing", "")
    if sample.get("missing_count"):
        return Judgment("fail", "必填配置缺失", {"missing": missing})
    return Judgment("pass", "必填配置完整", {})


def judge_credential_resolve(sample: dict, settings: Settings) -> Judgment:
    # A credential store we cannot read is an outage, not a neutral state: the
    # platform cannot decrypt a single stored secret in that case.
    if not sample.get("readable"):
        return Judgment("fail", "模型凭据不可读", {"exists": sample.get("exists", False)})
    return Judgment("pass", "模型凭据可读", {})


def judge_milvus(sample: dict, settings: Settings) -> Judgment:
    if not sample.get("configured"):
        return Judgment("not_configured", "Milvus 未接入", {})
    status_code = int(_float(sample.get("http_status")))
    raw_code = sample.get("code")
    code = -1 if raw_code is None else int(_float(raw_code))
    evidence = {
        "http_status": status_code,
        "code": code,
        "latency_ms": sample.get("latency_ms"),
    }
    if status_code >= 500:
        return Judgment("warn", "Milvus 健康检查返回异常", evidence)
    if status_code != 200 or code != 0:
        return Judgment("warn", "Milvus 拒绝请求", evidence)
    return Judgment("pass", "Milvus 可用", evidence)


def judge_object_storage(sample: dict, settings: Settings) -> Judgment:
    # No "not configured" escape hatch: if the endpoint cannot be probed, the
    # capability is broken for every upload that needs archiving. Report it as a
    # fault so it is either wired up or taken out of the checklist.
    if not sample.get("configured"):
        return Judgment("fail", "对象存储未接入", {"integrated": False})
    return Judgment(
        "pass",
        "对象存储可用",
        {"bucket": sample.get("bucket", ""), "latency_ms": sample.get("latency_ms")},
    )


def judge_knowledge_parser(sample: dict, settings: Settings) -> Judgment:
    # Optional capability, not an outage: txt/md/csv/pdf/docx/pptx/xlsx are parsed
    # in-process, so only legacy Office files, scanned PDFs and OFD/CAJ need the
    # external service. The check is registered as optional, so this never rings.
    if not sample.get("configured"):
        return Judgment(
            "fail",
            "外部格式解析未接入（doc/xls/扫描件会跳过）",
            {"integrated": False, "local_formats_only": True},
        )
    status_code = int(_float(sample.get("http_status")))
    evidence = {"http_status": status_code, "latency_ms": sample.get("latency_ms")}
    if status_code >= 500:
        return Judgment("fail", "知识解析服务不可用", evidence)
    if status_code == 404:
        return Judgment("pass", "知识解析服务可达（无健康检查路由）", evidence)
    return Judgment("pass", "知识解析服务可用", evidence)


def judge_model_chat_available(sample: dict, settings: Settings) -> Judgment:
    usable = int(_float(sample.get("usable")))
    evidence = {"usable": usable, "published": sample.get("published", 0)}
    if usable <= 0:
        return Judgment("fail", "没有可用的真实 Chat 渠道", evidence)
    return Judgment("pass", "模型渠道可用", evidence)


def judge_model_profile_capability(sample: dict, settings: Settings) -> Judgment:
    missing = int(_float(sample.get("missing_tools")))
    if missing:
        return Judgment(
            "fail", "已发布 Profile 要求的工具调用能力不被模型支持", {"missing_tools": missing}
        )
    return Judgment("pass", "Profile 能力匹配", {})


def judge_model_profile_consistency(sample: dict, settings: Settings) -> Judgment:
    broken = int(_float(sample.get("broken")))
    evidence = {
        "broken": broken,
        "disabled_profile": sample.get("disabled_profile", 0),
        "disabled_model": sample.get("disabled_model", 0),
        "disabled_connection": sample.get("disabled_connection", 0),
    }
    if broken:
        return Judgment("fail", "已发布 Profile 引用了禁用的模型或连接", evidence)
    return Judgment("pass", "已发布 Profile 引用一致", evidence)


def judge_model_success_rate(sample: dict, settings: Settings) -> Judgment:
    samples = int(_float(sample.get("samples")))
    completed = int(_float(sample.get("completed")))
    if samples < 10:
        return Judgment("unknown", "24 小时调用样本不足", {"samples": samples})
    rate = _ratio(completed, samples)
    evidence = {"samples": samples, "rate": round(rate, 3)}
    if rate < settings.monitor_model_success_fail_ratio:
        return Judgment("fail", "模型调用成功率过低", evidence)
    if rate < settings.monitor_model_success_warn_ratio:
        return Judgment("warn", "模型调用成功率下降", evidence)
    return Judgment("pass", "模型调用成功率正常", evidence)


def judge_model_error_class(sample: dict, settings: Settings) -> Judgment:
    samples = int(_float(sample.get("samples")))
    bad = int(_float(sample.get("bad")))
    if samples < 10:
        return Judgment("unknown", "24 小时调用样本不足", {"samples": samples})
    rate = _ratio(bad, samples)
    evidence = {"samples": samples, "bad": bad, "rate": round(rate, 3)}
    if rate > settings.monitor_model_error_warn_ratio:
        return Judgment("warn", "超时与传输类错误占比偏高", evidence)
    return Judgment("pass", "错误类型分布正常", evidence)


def judge_model_latency(sample: dict, settings: Settings) -> Judgment:
    samples = int(_float(sample.get("samples")))
    p95 = sample.get("p95_ms")
    baseline = sample.get("baseline_p95_ms")
    if samples < 10 or p95 is None:
        return Judgment("unknown", "模型调用样本不足", {"samples": samples})
    if baseline is None or _float(baseline) <= 0:
        return Judgment(
            "unknown", "缺少延迟基线", {"samples": samples, "p95_ms": round(_float(p95))}
        )
    ratio = _float(p95) / _float(baseline)
    evidence = {"p95_ms": round(_float(p95)), "baseline_ms": round(_float(baseline))}
    if ratio > 1 + settings.monitor_model_latency_fail_ratio:
        return Judgment("fail", "模型调用延迟显著恶化", {**evidence, "ratio": round(ratio, 3)})
    if ratio > 1 + settings.monitor_model_latency_warn_ratio:
        return Judgment("warn", "模型调用延迟上升", {**evidence, "ratio": round(ratio, 3)})
    return Judgment("pass", "模型调用延迟正常", {**evidence, "ratio": round(ratio, 3)})


def judge_model_quota(sample: dict, settings: Settings) -> Judgment:
    capacity = int(_float(sample.get("capacity"), 1))
    active = int(_float(sample.get("active_leases")))
    ratio = _ratio(active, capacity)
    evidence = {"active_leases": active, "capacity": capacity, "ratio": round(ratio, 3)}
    if ratio >= settings.monitor_quota_fail_ratio:
        return Judgment("fail", "模型并发额度耗尽", evidence)
    if ratio >= settings.monitor_quota_warn_ratio:
        return Judgment("warn", "模型并发额度紧张", evidence)
    return Judgment("pass", "模型并发额度充足", evidence)


def judge_model_probe_freshness(sample: dict, settings: Settings) -> Judgment:
    age = sample.get("age_seconds")
    if age is None:
        return Judgment("fail", "从未成功验证模型渠道", {"probe_samples": 0})
    age_minutes = _float(age) / 60
    evidence = {
        "age_minutes": round(age_minutes, 1),
        "probe_samples": sample.get("probe_samples", 0),
        "last_probe_status": sample.get("last_probe_status", ""),
    }
    if age_minutes > settings.monitor_probe_fail_age_minutes:
        # Stale verification is hygiene, not a fault: the channel's real health
        # is measured by model.chat.available and model.success_rate. Failing
        # here only punished an idle box that simply had no traffic.
        return Judgment("warn", "模型渠道验证信息陈旧", evidence)
    if age_minutes > settings.monitor_probe_warn_age_minutes:
        return Judgment("warn", "模型渠道验证信息偏旧", evidence)
    return Judgment("pass", "模型渠道近期验证成功", evidence)


def judge_worker_heartbeat(sample: dict, settings: Settings) -> Judgment:
    expected = str(sample.get("expected") or "")
    missing = str(sample.get("missing") or "")
    stale = str(sample.get("stale") or "")
    evidence = {
        "roles": expected,
        "missing": missing,
        "stale": stale,
        "alive": int(_float(sample.get("alive"))),
        "total": int(_float(sample.get("total"))),
        "age_seconds": round(_float(sample.get("age_seconds")), 1),
    }
    if missing and stale:
        return Judgment("fail", "Worker 未启动且心跳超时", evidence)
    if missing:
        return Judgment("fail", "Worker 未启动", evidence)
    if stale:
        return Judgment("fail", "Worker 心跳超时", evidence)
    return Judgment("pass", "Worker 心跳正常", evidence)


def judge_queue_runtime(sample: dict, settings: Settings) -> Judgment:
    queued = int(_float(sample.get("queued")))
    if not queued:
        return Judgment("pass", "运行队列空闲", {"queued": 0})
    oldest = _float(sample.get("oldest_seconds"))
    evidence = {"queued": queued, "oldest_seconds": round(oldest)}
    if oldest > settings.monitor_queue_fail_age_seconds:
        return Judgment("fail", "运行队列积压过久", evidence)
    if oldest > settings.monitor_queue_warn_age_seconds:
        return Judgment("warn", "运行队列存在积压", evidence)
    return Judgment("pass", "运行队列正常", evidence)


def judge_runtime_lease_expired(sample: dict, settings: Settings) -> Judgment:
    expired = int(_float(sample.get("expired")))
    if expired:
        return Judgment("warn", "存在过期的运行租约", {"expired": expired})
    return Judgment("pass", "运行租约正常", {"expired": 0})


def judge_monitor_scan(sample: dict, settings: Settings) -> Judgment:
    age = _float(sample.get("age_seconds"))
    limit = settings.monitor_fast_interval_seconds * 2
    evidence = {"age_seconds": round(age), "threshold": limit}
    if age > limit:
        return Judgment("fail", "巡检器已停止工作", evidence)
    return Judgment("pass", "巡检器运行中", evidence)


JUDGES = {
    "infra.pg.connection": judge_pg_connection,
    "infra.pg.migration": judge_pg_migration,
    "infra.pgvector": judge_pgvector,
    "infra.db.pool": judge_db_pool,
    "infra.cpu.usage": judge_cpu_usage,
    "infra.memory.usage": judge_memory_usage,
    "infra.config.required": judge_required_config,
    "infra.credential.resolve": judge_credential_resolve,
    "integration.milvus": judge_milvus,
    "integration.object_storage": judge_object_storage,
    "integration.knowledge_parser": judge_knowledge_parser,
    "model.chat.available": judge_model_chat_available,
    "model.profile.capability": judge_model_profile_capability,
    "model.profile.consistency": judge_model_profile_consistency,
    "model.success_rate": judge_model_success_rate,
    "model.error_class": judge_model_error_class,
    "model.latency": judge_model_latency,
    "model.quota": judge_model_quota,
    "model.probe.freshness": judge_model_probe_freshness,
    "worker.runtime.heartbeat": judge_worker_heartbeat,
    "queue.runtime": judge_queue_runtime,
    "runtime.lease_expired": judge_runtime_lease_expired,
    "monitor.scan": judge_monitor_scan,
}
