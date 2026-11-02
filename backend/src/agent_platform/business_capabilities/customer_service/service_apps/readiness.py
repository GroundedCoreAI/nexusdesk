"""Publish-readiness evaluation for service applications.

The evaluator only uses business configuration.  Check text is deliberately
kept free of provider names, tool identifiers, agent ids and queue keys so the
same result can be shown to operators and used as a server-side release gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import Field

from ..scenarios.models import (
    HandlerDefinition,
    HandlerType,
    ObjectMode,
    ScenarioConfig,
    ScenarioModel,
    ScenarioStatus,
    ScenarioTemplate,
    UserDecisionKind,
)
from .models import (
    ApplicationCapability,
    ApplicationScenarioReference,
    CapabilityType,
    ChannelStatus,
    ServiceApplicationConfig,
)


class ReadinessState(StrEnum):
    READY = "ready"
    SIMULATE_ONLY = "simulate_only"
    BLOCKED = "blocked"


class ReadinessCheckStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    BLOCKED = "blocked"


class ReadinessCheckSeverity(StrEnum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


_STATE_LABELS = {
    ReadinessState.READY: "可发布",
    ReadinessState.SIMULATE_ONLY: "仅可模拟",
    ReadinessState.BLOCKED: "配置不完整",
}

_STATE_DESCRIPTIONS = {
    ReadinessState.READY: "核心配置和客户触点已就绪，可以发布新版本。",
    ReadinessState.SIMULATE_ONLY: "核心链路可以模拟体验，但仍有发布前需要处理的配置。",
    ReadinessState.BLOCKED: "存在阻断发布的配置缺失，请先完成必需项。",
}

_OBJECT_NAMES = {
    "order": "订单",
    "invoice": "发票",
    "logistics": "物流",
    "refund": "退款",
    "after_sales": "售后单",
    "aftersales": "售后单",
    "member": "会员",
    "account": "账户",
    "ticket": "工单",
    "complaint": "投诉",
    "address": "收货地址",
    "transaction": "交易",
    "payment": "支付记录",
    "service_record": "服务记录",
}


class ReadinessCheck(ScenarioModel):
    key: str
    title: str
    detail: str
    status: ReadinessCheckStatus
    severity: ReadinessCheckSeverity


class ReadinessCounts(ScenarioModel):
    passed: int = Field(serialization_alias="pass")
    warning: int
    blocked: int


class ScenarioReadinessResult(ScenarioModel):
    key: str
    name: str
    version: int | None = None
    scenario_status: str
    status: ReadinessState
    label: str
    description: str
    checks: list[ReadinessCheck]
    counts: ReadinessCounts
    can_publish: bool
    can_simulate: bool


class ApplicationReadinessResult(ScenarioModel):
    key: str
    name: str
    revision: int
    application_status: str
    status: ReadinessState
    label: str
    description: str
    checks: list[ReadinessCheck]
    counts: ReadinessCounts
    can_publish: bool
    can_simulate: bool
    scenarios: list[ScenarioReadinessResult]


@dataclass(frozen=True)
class ScenarioReadinessSnapshot:
    """A scenario reference plus the snapshots needed to assess a release."""

    reference: ApplicationScenarioReference
    name: str | None = None
    scenario_status: str = ""
    published_version: int | None = None
    effective_version: int | None = None
    version_available: bool = False
    effective_config: ScenarioConfig | None = None
    has_unpublished_changes: bool = False
    found: bool = True


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _check(
    key: str,
    title: str,
    detail: str,
    status: ReadinessCheckStatus,
    severity: ReadinessCheckSeverity,
) -> ReadinessCheck:
    return ReadinessCheck(
        key=key,
        title=title,
        detail=detail,
        status=status,
        severity=severity,
    )


def _passed(
    key: str,
    title: str,
    detail: str,
    severity: ReadinessCheckSeverity = ReadinessCheckSeverity.BLOCKING,
) -> ReadinessCheck:
    return _check(key, title, detail, ReadinessCheckStatus.PASS, severity)


def _blocked(key: str, title: str, detail: str) -> ReadinessCheck:
    return _check(
        key,
        title,
        detail,
        ReadinessCheckStatus.BLOCKED,
        ReadinessCheckSeverity.BLOCKING,
    )


def _warning(
    key: str,
    title: str,
    detail: str,
    severity: ReadinessCheckSeverity = ReadinessCheckSeverity.WARNING,
) -> ReadinessCheck:
    return _check(key, title, detail, ReadinessCheckStatus.WARNING, severity)


def _object_name(object_type: str | None) -> str:
    normalized = _text(object_type).casefold().replace("-", "_")
    return _OBJECT_NAMES.get(normalized, "业务对象")


def _queue_of(source: HandlerDefinition | ApplicationCapability) -> str:
    if _text(source.queue):
        return _text(source.queue)
    for key in ("queue", "handoff_queue", "handoff_target", "assignee_group"):
        value = _text(source.config.get(key))
        if value:
            return value
    return ""


def _requires_business_object(
    config: ScenarioConfig,
    object_required: bool,
    object_mode: ObjectMode | None,
) -> bool:
    if config.template in {ScenarioTemplate.QUERY, ScenarioTemplate.ACTION}:
        return True
    return bool(object_required or object_mode in {ObjectMode.REQUIRED, ObjectMode.MULTIPLE})


def _counts(checks: list[ReadinessCheck]) -> ReadinessCounts:
    return ReadinessCounts(
        passed=sum(item.status == ReadinessCheckStatus.PASS for item in checks),
        warning=sum(item.status == ReadinessCheckStatus.WARNING for item in checks),
        blocked=sum(item.status == ReadinessCheckStatus.BLOCKED for item in checks),
    )


def _state(checks: list[ReadinessCheck]) -> ReadinessState:
    has_blocking = any(
        item.status != ReadinessCheckStatus.PASS
        and item.severity == ReadinessCheckSeverity.BLOCKING
        for item in checks
    )
    if has_blocking:
        return ReadinessState.BLOCKED
    has_warning = any(
        item.status != ReadinessCheckStatus.PASS and item.severity == ReadinessCheckSeverity.WARNING
        for item in checks
    )
    return ReadinessState.SIMULATE_ONLY if has_warning else ReadinessState.READY


def _application_link_check(
    application: ServiceApplicationConfig,
    snapshot: ScenarioReadinessSnapshot,
) -> ReadinessCheck:
    if not snapshot.found:
        return _blocked(
            "application-link",
            "应用关联与启用",
            "场景尚未加入当前服务应用，客户无法从该应用进入服务。",
        )
    if not snapshot.reference.enabled:
        return _blocked(
            "application-link",
            "应用关联与启用",
            "场景在应用内处于停用状态，客户不会看到该服务。",
        )
    return _passed(
        "application-link",
        "应用关联与启用",
        f"已加入「{application.name}」并在应用内启用。",
    )


def _business_object_check(config: ScenarioConfig | None) -> ReadinessCheck:
    if config is None:
        return _blocked(
            "business-object",
            "必填业务对象",
            "场景配置不可用，无法确认客户要选择或提供哪类业务对象。",
        )

    business_object = config.object
    required = _requires_business_object(
        config,
        business_object.required if business_object else False,
        business_object.mode if business_object else None,
    )
    no_object_configured = business_object is None or (
        business_object.mode == ObjectMode.NONE and not required
    )
    if no_object_configured:
        if required:
            return _blocked(
                "business-object",
                "必填业务对象",
                "该场景需要业务对象，但尚未明确客户要选择或提供哪类业务对象。",
            )
        return _passed(
            "business-object",
            "必填业务对象",
            "咨询型场景无需业务对象，可直接通过知识或固定应答处理。",
        )
    if not _text(business_object.type):
        return _blocked(
            "business-object",
            "必填业务对象",
            "业务对象尚未选择，客户无法进入对应的查询或办理流程。",
        )
    if not _text(business_object.provider):
        return _blocked(
            "business-object",
            "必填业务对象",
            f"已选择{_object_name(business_object.type)}对象，但尚未明确业务数据来源。",
        )
    return _passed(
        "business-object",
        "必填业务对象",
        f"已配置{_object_name(business_object.type)}对象，并明确业务数据来源。",
    )


def _business_facts_check(config: ScenarioConfig | None) -> ReadinessCheck:
    if config is None:
        return _blocked(
            "business-facts",
            "业务事实字段",
            "场景配置不可用，无法确认客户看到的业务事实。",
        )
    if not config.facts:
        if config.template in {ScenarioTemplate.QUERY, ScenarioTemplate.ACTION}:
            return _blocked(
                "business-facts",
                "业务事实字段",
                "查询或办理场景尚未配置业务事实，客户无法看到判断所需的关键信息。",
            )
        return _passed(
            "business-facts",
            "业务事实字段",
            "咨询型场景无需展示业务事实。",
            ReadinessCheckSeverity.INFO,
        )
    invalid = sum(
        not _text(item.key) or not _text(item.label) or not _text(item.source)
        for item in config.facts
    )
    if invalid:
        return _blocked(
            "business-facts",
            "业务事实字段",
            f"有 {invalid} 项业务事实缺少业务名称或数据来源，请补全后再发布。",
        )
    return _passed(
        "business-facts",
        "业务事实字段",
        f"已配置 {len(config.facts)} 项业务事实，客户可看到判断所需的信息。",
    )


def _handlers_check(config: ScenarioConfig | None) -> ReadinessCheck:
    if config is None:
        return _blocked(
            "handlers",
            "处理能力",
            "场景配置不可用，无法确认客户问题如何被承接。",
        )
    enabled = [item for item in config.handlers if item.enabled]
    if not enabled:
        return _blocked(
            "handlers",
            "处理能力",
            "场景尚未启用任何处理能力，客户进入后无法得到处理结果。",
        )
    return _passed(
        "handlers",
        "处理能力",
        f"已启用 {len(enabled)} 项处理能力，可承接客户问题。",
    )


def _action_confirmation_check(config: ScenarioConfig | None) -> ReadinessCheck:
    if config is None:
        return _blocked(
            "action-confirmation",
            "办理确认",
            "场景配置不可用，无法确认办理动作是否经过客户确认。",
        )
    if config.template != ScenarioTemplate.ACTION:
        return _passed(
            "action-confirmation",
            "办理确认",
            "当前场景不涉及业务办理，无需提交操作确认。",
            ReadinessCheckSeverity.INFO,
        )
    confirmation = next(
        (item for item in config.decisions if item.kind == UserDecisionKind.CONFIRM_ACTION),
        None,
    )
    if confirmation is None:
        return _blocked(
            "action-confirmation",
            "办理确认",
            "办理型场景尚未配置操作确认，客户可能在未确认影响的情况下提交业务。",
        )
    safe = confirmation.required and confirmation.confirm and not confirmation.allow_skip
    if not safe:
        return _warning(
            "action-confirmation",
            "办理确认",
            "操作确认尚未设置为必填且不可跳过，请确认客户能够明确知晓办理影响。",
        )
    return _passed(
        "action-confirmation",
        "办理确认",
        "办理前会要求客户确认影响和操作内容。",
    )


def _fallback_check(config: ScenarioConfig | None) -> ReadinessCheck:
    if config is None:
        return _blocked(
            "fallback-order",
            "异常兜底顺序",
            "场景配置不可用，无法确定处理能力不可用时的承接方式。",
        )
    enabled_keys = {item.key for item in config.handlers if item.enabled}
    fallback = list(dict.fromkeys(item for item in map(_text, config.fallback_order) if item))
    if not fallback:
        return _blocked(
            "fallback-order",
            "异常兜底顺序",
            "兜底顺序为空，处理能力不可用时无法确定下一承接方式。",
        )
    valid = [key for key in fallback if key in enabled_keys]
    invalid = [key for key in fallback if key not in enabled_keys]
    if not valid:
        return _blocked(
            "fallback-order",
            "异常兜底顺序",
            "兜底顺序中的承接方式均不可用，请重新编排异常处理路径。",
        )
    if invalid:
        return _warning(
            "fallback-order",
            "异常兜底顺序",
            f"兜底顺序中有 {len(invalid)} 项承接方式已失效，发布前请重新编排。",
        )
    return _passed(
        "fallback-order",
        "异常兜底顺序",
        f"已配置 {len(valid)} 级兜底顺序，异常时可继续升级处理。",
    )


def _human_handoff_check(
    application: ServiceApplicationConfig,
    config: ScenarioConfig | None,
) -> ReadinessCheck:
    if config is None:
        return _blocked(
            "human-handoff",
            "人工承接",
            "场景配置不可用，无法确认转人工后的承接方式。",
        )
    handlers = [item for item in config.handlers if item.enabled]
    human_handlers = [item for item in handlers if item.type == HandlerType.HUMAN]
    human_capabilities = [
        item
        for item in application.capabilities
        if item.enabled and item.type == CapabilityType.HUMAN
    ]
    explicit_handoff = any(item.kind == UserDecisionKind.HANDOFF for item in config.decisions)
    human_in_fallback = any(item.key in config.fallback_order for item in human_handlers)
    sources: list[HandlerDefinition | ApplicationCapability] = [
        *human_handlers,
        *human_capabilities,
    ]
    if not sources:
        if explicit_handoff:
            return _blocked(
                "human-handoff",
                "人工承接",
                "已设置转人工决策，但尚未配置可接管的人工队列或承接方式。",
            )
        return _warning(
            "human-handoff",
            "人工承接",
            "尚未配置人工承接，复杂问题暂时无法升级给人工坐席。",
        )
    if any(_queue_of(item) for item in sources):
        return _passed(
            "human-handoff",
            "人工承接",
            "已配置明确的人工承接方式，复杂问题可以转交人工处理。",
        )
    if explicit_handoff or human_in_fallback:
        return _blocked(
            "human-handoff",
            "人工承接",
            "服务路径包含转人工，但尚未指定人工队列或承接方式。",
        )
    return _warning(
        "human-handoff",
        "人工承接",
        "已添加人工能力，但尚未指定人工队列或承接方式。",
    )


def _customer_channels_check(
    application: ServiceApplicationConfig,
) -> ReadinessCheck:
    channels = [item for item in application.channels if item.status != ChannelStatus.DISABLED]
    if not channels:
        return _warning(
            "customer-channels",
            "客户渠道",
            "尚未接入可用客户渠道，可以先用模拟体验，但暂不能对外发布。",
        )
    return _passed(
        "customer-channels",
        "客户渠道",
        f"已接入 {len(channels)} 个客户渠道。",
    )


def _publication_check(snapshot: ScenarioReadinessSnapshot) -> ReadinessCheck:
    if not snapshot.found:
        return _blocked(
            "publication",
            "发布状态",
            "场景尚未加入当前服务应用，无法确认可发布版本。",
        )
    if not snapshot.version_available:
        return _blocked(
            "publication",
            "发布状态",
            "场景尚未发布正式版本，不能随服务应用发布。",
        )
    if snapshot.reference.version is None and snapshot.scenario_status != ScenarioStatus.PUBLISHED:
        return _blocked(
            "publication",
            "发布状态",
            "场景当前不在已发布状态，请先发布场景版本再发布应用。",
        )
    if snapshot.scenario_status == ScenarioStatus.OFFLINE:
        return _warning(
            "publication",
            "发布状态",
            "场景当前已下线，重新发布后才会对客户生效。",
            ReadinessCheckSeverity.INFO,
        )
    if snapshot.has_unpublished_changes:
        published = snapshot.published_version
        return _warning(
            "publication",
            "发布状态",
            (
                f"已发布 v{published}，但当前配置存在未发布修改；客户仍在使用已发布版本。"
                if published
                else "当前配置尚未发布；完成检查后会生成首个客户可用版本。"
            ),
            ReadinessCheckSeverity.INFO,
        )
    if snapshot.effective_version:
        return _passed(
            "publication",
            "发布状态",
            f"当前配置已发布为 v{snapshot.effective_version}，与客户使用版本一致。",
            ReadinessCheckSeverity.INFO,
        )
    return _passed(
        "publication",
        "发布状态",
        "当前场景尚未发布；检查通过后可以发布首个客户可用版本。",
        ReadinessCheckSeverity.INFO,
    )


def _application_scenarios_check(
    application: ServiceApplicationConfig,
) -> ReadinessCheck:
    if not application.scenarios:
        return _blocked(
            "application-scenarios",
            "服务场景",
            "服务应用尚未关联任何场景，客户无法从应用进入服务。",
        )
    if not any(item.enabled for item in application.scenarios):
        return _blocked(
            "application-scenarios",
            "服务场景",
            "服务应用中的场景均已停用，客户无法从应用进入服务。",
        )
    return _passed(
        "application-scenarios",
        "服务场景",
        f"已关联 {len(application.scenarios)} 个服务场景。",
    )


def _scenario_result(
    application: ServiceApplicationConfig,
    snapshot: ScenarioReadinessSnapshot,
) -> ScenarioReadinessResult:
    if not snapshot.found:
        checks = [_application_link_check(application, snapshot)]
    else:
        checks = [
            _application_link_check(application, snapshot),
            _business_object_check(snapshot.effective_config),
            _business_facts_check(snapshot.effective_config),
            _handlers_check(snapshot.effective_config),
            _fallback_check(snapshot.effective_config),
            _action_confirmation_check(snapshot.effective_config),
            _human_handoff_check(application, snapshot.effective_config),
            _customer_channels_check(application),
            _publication_check(snapshot),
        ]
    state = _state(checks)
    return ScenarioReadinessResult(
        key=snapshot.reference.key,
        name=snapshot.name or snapshot.reference.key,
        version=(
            snapshot.effective_version
            if snapshot.effective_version is not None
            else snapshot.published_version
        ),
        scenario_status=snapshot.scenario_status or "missing",
        status=state,
        label=_STATE_LABELS[state],
        description=_STATE_DESCRIPTIONS[state],
        checks=checks,
        counts=_counts(checks),
        can_publish=state == ReadinessState.READY,
        can_simulate=state != ReadinessState.BLOCKED,
    )


def evaluate_application_readiness(
    *,
    application_key: str,
    application_name: str,
    revision: int,
    application_status: str,
    application: ServiceApplicationConfig,
    scenarios: list[ScenarioReadinessSnapshot],
) -> ApplicationReadinessResult:
    """Evaluate an application release from already-loaded snapshots."""

    application_checks = [
        _application_scenarios_check(application),
        _customer_channels_check(application),
    ]
    scenario_results = [_scenario_result(application, snapshot) for snapshot in scenarios]
    checks = [*application_checks]
    state = _state(checks)
    if any(item.status == ReadinessState.BLOCKED for item in scenario_results):
        state = ReadinessState.BLOCKED
    elif state != ReadinessState.BLOCKED and any(
        item.status == ReadinessState.SIMULATE_ONLY for item in scenario_results
    ):
        state = ReadinessState.SIMULATE_ONLY
    if not scenario_results:
        state = ReadinessState.BLOCKED

    return ApplicationReadinessResult(
        key=application_key,
        name=application_name,
        revision=revision,
        application_status=application_status,
        status=state,
        label=_STATE_LABELS[state],
        description=_STATE_DESCRIPTIONS[state],
        checks=application_checks,
        counts=_counts(checks),
        can_publish=state == ReadinessState.READY,
        can_simulate=state != ReadinessState.BLOCKED,
        scenarios=scenario_results,
    )


__all__ = [
    "ApplicationReadinessResult",
    "ReadinessCheck",
    "ReadinessCheckSeverity",
    "ReadinessCheckStatus",
    "ReadinessCounts",
    "ReadinessState",
    "ScenarioReadinessResult",
    "ScenarioReadinessSnapshot",
    "evaluate_application_readiness",
]
