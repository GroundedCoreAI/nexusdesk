"""Platform-level check registrations.

Capability-level checks (memory / knowledge / channel / open-platform queues and
business metrics) are registered by the application composition root, because
``core_platform`` must not depend on ``business_capabilities``.
"""

from . import collectors, resources
from .registry import Action, Cadence, Check, CheckKind, Registration, Severity
from .rules import JUDGES

OBSERVABILITY = Action("打开可观测性", "/observability")
MODEL_CONNECTIONS = Action("查看模型连接", "/models/connections")
MODEL_PROFILES = Action("查看模型 Profile", "/models/profiles")


def _check(
    check_id: str,
    group: str,
    kind: CheckKind,
    severity: Severity,
    cadence: Cadence,
    title: str,
    action: Action,
    *,
    scoped: bool = True,
) -> Check:
    return Check(
        id=check_id,
        group=group,
        kind=kind,
        severity=severity,
        cadence=cadence,
        action=action,
        scoped=scoped,
        title=title,
    )


PLATFORM_REGISTRATIONS: tuple[Registration, ...] = (
    Registration(
        _check(
            "infra.pg.connection",
            "middleware",
            "required",
            "P0",
            "fast",
            "PostgreSQL 连接",
            Action("查看系统状态", "/observability"),
            scoped=False,
        ),
        collectors.pg_connection,
        JUDGES["infra.pg.connection"],
    ),
    Registration(
        _check(
            "infra.pg.migration",
            "middleware",
            "required",
            "P0",
            "fast",
            "数据库迁移版本",
            OBSERVABILITY,
            scoped=False,
        ),
        collectors.pg_migration,
        JUDGES["infra.pg.migration"],
    ),
    Registration(
        _check(
            "infra.pgvector",
            "middleware",
            "optional",
            "P1",
            "fast",
            "pgvector 扩展",
            OBSERVABILITY,
            scoped=False,
        ),
        collectors.pgvector,
        JUDGES["infra.pgvector"],
    ),
    Registration(
        _check(
            "infra.db.pool",
            "middleware",
            "required",
            "P1",
            "fast",
            "数据库连接池",
            OBSERVABILITY,
            scoped=False,
        ),
        collectors.db_pool,
        JUDGES["infra.db.pool"],
    ),
    Registration(
        _check(
            "infra.cpu.usage",
            "middleware",
            "required",
            "P2",
            "fast",
            "CPU 使用率",
            OBSERVABILITY,
            scoped=False,
        ),
        resources.cpu_usage,
        JUDGES["infra.cpu.usage"],
    ),
    Registration(
        _check(
            "infra.memory.usage",
            "middleware",
            "required",
            "P2",
            "fast",
            "内存使用率",
            OBSERVABILITY,
            scoped=False,
        ),
        resources.memory_usage,
        JUDGES["infra.memory.usage"],
    ),
    Registration(
        _check(
            "infra.config.required",
            "middleware",
            "required",
            "P0",
            "fast",
            "必填配置",
            OBSERVABILITY,
            scoped=False,
        ),
        collectors.required_config,
        JUDGES["infra.config.required"],
    ),
    Registration(
        _check(
            "infra.credential.resolve",
            "middleware",
            "conditional",
            "P0",
            "fast",
            "模型凭据接入",
            MODEL_CONNECTIONS,
            scoped=False,
        ),
        collectors.credential_resolve,
        JUDGES["infra.credential.resolve"],
    ),
    Registration(
        _check(
            "integration.milvus",
            "middleware",
            "conditional",
            "P1",
            "integration",
            "Milvus 可用性",
            Action("查看知识库配置", "/knowledge"),
            scoped=False,
        ),
        collectors.milvus,
        JUDGES["integration.milvus"],
    ),
    Registration(
        _check(
            "integration.object_storage",
            "middleware",
            "conditional",
            "P1",
            "integration",
            "对象存储接入",
            Action("查看知识库配置", "/knowledge"),
            scoped=False,
        ),
        collectors.object_storage,
        JUDGES["integration.object_storage"],
    ),
    Registration(
        # Only legacy Office formats, scanned PDFs and OFD/CAJ archives need the
        # external parser; txt/md/csv/pdf/docx/pptx/xlsx are all parsed in-process,
        # so an unset parser URL is a capability choice, not an outage.
        _check(
            "integration.knowledge_parser",
            "middleware",
            "optional",
            "P2",
            "integration",
            "外部格式解析（可选）",
            Action("查看知识库配置", "/knowledge"),
            scoped=False,
        ),
        collectors.knowledge_parser,
        JUDGES["integration.knowledge_parser"],
    ),
    Registration(
        _check(
            "model.chat.available",
            "models",
            "required",
            "P0",
            "fast",
            "可用 Chat 渠道",
            MODEL_PROFILES,
        ),
        collectors.model_chat_available,
        JUDGES["model.chat.available"],
    ),
    Registration(
        _check(
            "model.profile.capability",
            "models",
            "required",
            "P0",
            "fast",
            "Profile 能力匹配",
            MODEL_PROFILES,
        ),
        collectors.model_profile_capability,
        JUDGES["model.profile.capability"],
    ),
    Registration(
        _check(
            "model.profile.consistency",
            "models",
            "required",
            "P0",
            "fast",
            "Profile 引用一致性",
            MODEL_PROFILES,
        ),
        collectors.model_profile_consistency,
        JUDGES["model.profile.consistency"],
    ),
    Registration(
        _check(
            "model.probe.freshness",
            "models",
            "conditional",
            "P1",
            "fast",
            "模型渠道验证",
            MODEL_CONNECTIONS,
        ),
        collectors.model_probe_freshness,
        JUDGES["model.probe.freshness"],
    ),
    Registration(
        _check(
            "model.success_rate",
            "models",
            "required",
            "P1",
            "business",
            "模型调用成功率",
            OBSERVABILITY,
        ),
        collectors.model_success_rate,
        JUDGES["model.success_rate"],
    ),
    Registration(
        _check(
            "model.error_class",
            "models",
            "required",
            "P1",
            "business",
            "模型错误类型",
            OBSERVABILITY,
        ),
        collectors.model_error_class,
        JUDGES["model.error_class"],
    ),
    Registration(
        _check(
            "model.latency",
            "models",
            "required",
            "P2",
            "business",
            "模型调用延迟",
            OBSERVABILITY,
        ),
        collectors.model_latency,
        JUDGES["model.latency"],
    ),
    Registration(
        _check(
            "model.quota",
            "models",
            "required",
            "P1",
            "fast",
            "模型并发额度",
            OBSERVABILITY,
        ),
        collectors.model_quota,
        JUDGES["model.quota"],
    ),
    Registration(
        _check(
            "worker.runtime.heartbeat",
            "queues",
            "required",
            "P1",
            "fast",
            "Worker 心跳",
            OBSERVABILITY,
        ),
        collectors.worker_heartbeat,
        JUDGES["worker.runtime.heartbeat"],
    ),
    Registration(
        _check(
            "queue.runtime",
            "queues",
            "required",
            "P1",
            "fast",
            "运行队列积压",
            OBSERVABILITY,
        ),
        collectors.queue_runtime,
        JUDGES["queue.runtime"],
    ),
    Registration(
        _check(
            "runtime.lease_expired",
            "queues",
            "required",
            "P1",
            "fast",
            "运行租约过期",
            OBSERVABILITY,
        ),
        collectors.runtime_lease_expired,
        JUDGES["runtime.lease_expired"],
    ),
    Registration(
        _check(
            "monitor.scan",
            "queues",
            "required",
            "P1",
            "fast",
            "巡检器心跳",
            OBSERVABILITY,
            scoped=False,
        ),
        collectors.monitor_scan,
        JUDGES["monitor.scan"],
    ),
)
