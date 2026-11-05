"""Content-community industry pack V1.

The pack is a versioned asset, not a runtime tenant entity.  Every scenario
is expressed with the generic scenario, object, decision, handler and
simulation contracts; no runtime code branches on the pack key.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..scenarios.models import ObjectMode, SimulatedObject
from ..service_apps.models import ApplicationCapability, ApplicationChannel
from .models import (
    AcceptanceCase,
    ApplicationBlueprint,
    CatalogCategoryTemplate,
    IndustryPackManifest,
    IndustryPackMaturity,
    ObjectTemplate,
    PackSample,
    ScenarioKind,
    ScenarioTemplate,
)

TEMPLATE_VERSION = "1.0.0"


def _fact(
    key: str,
    label: str,
    source: str,
    *,
    order: int,
    masked: bool = False,
    audiences: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "source": source,
        "format": "text",
        "order": order,
        "masked": masked,
        "audiences": audiences or ["customer", "agent", "human"],
        "refresh": "on_open",
        "config": {},
    }


def _entry(key: str, label: str, description: str = "") -> dict[str, Any]:
    return {
        "key": key,
        "type": "natural_language",
        "label": label,
        "description": description,
        "enabled": True,
        "config": {},
    }


def _handler(
    key: str,
    handler_type: str,
    label: str,
    *,
    priority: int,
    tool: str | None = None,
    queue: str | None = None,
    when: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "type": handler_type,
        "label": label,
        "priority": priority,
        "enabled": True,
        "when": when or {},
        "tool": tool,
        "queue": queue,
        "reply": None,
        "agent_id": None,
        "agent_version": None,
        "agent_name": None,
        "config": config or {},
    }


def _decision(
    key: str,
    kind: str,
    label: str,
    *,
    required: bool = True,
    confirm: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "kind": kind,
        "label": label,
        "required": required,
        "options": [],
        "allow_free_text": False,
        "allow_skip": not required,
        "confirm": confirm,
        "correctable": True,
        "when": {},
    }


def _object_template(
    *,
    key: str,
    name: str,
    provider: str,
    facts: list[dict[str, Any]],
    sensitive_fields: list[str],
    mode: ObjectMode = ObjectMode.REQUIRED,
    filters: list[str] | None = None,
    sample_refs: list[str] | None = None,
) -> ObjectTemplate:
    return ObjectTemplate(
        object_template_key=key,
        object_type=key,
        name=name,
        provider_key=provider,
        default_mode=mode,
        permission_scope="customer_scope",
        fact_fields=facts,
        sensitive_fields=sensitive_fields,
        candidate_strategy={
            "sort": "recent_desc",
            "limit": 5,
            "filters": filters or [],
            "empty_state": "没有找到可处理的业务对象，请重新选择或转人工。",
            "unavailable_state": "业务对象暂时不可用，请稍后重试或转人工。",
        },
        sample_refs=sample_refs or [],
    )


def _scenario(
    *,
    key: str,
    name: str,
    description: str,
    scenario_kind: ScenarioKind,
    execution_template: str,
    maturity: IndustryPackMaturity,
    category_key: str,
    object_template_key: str | None,
    keywords: list[str],
    handlers: list[dict[str, Any]],
    decisions: list[dict[str, Any]] | None = None,
    recommendations: list[dict[str, Any]] | None = None,
    policy_profile: str,
) -> ScenarioTemplate:
    return ScenarioTemplate(
        template_key=key,
        template_version=TEMPLATE_VERSION,
        name=name,
        description=description,
        scenario_kind=scenario_kind,
        execution_template=execution_template,
        maturity=maturity,
        catalog_category_key=category_key,
        object_template_key=object_template_key,
        channels=["web", "app", "wechat", "h5"],
        sample_refs=[f"sample-{key}"],
        acceptance_case_refs=[f"case-{key}"],
        config={
            "domain": "内容社区",
            "entries": [_entry("natural-language", "自然语言")],
            "decisions": decisions or [],
            "recommendations": recommendations or [],
            "handlers": handlers,
            "fallback_order": [handler["key"] for handler in handlers],
            "matching": {
                "keywords": keywords,
                "intents": [],
                "negative_keywords": [],
            },
            "config": {"policy_profile": policy_profile},
        },
    )


_OBJECT_TEMPLATES = [
    _object_template(
        key="community_account",
        name="社区账号",
        provider="community_account_provider",
        mode=ObjectMode.REQUIRED,
        filters=["受限", "正常", "安全验证"],
        sensitive_fields=["registered_at", "realname_summary"],
        facts=[
            _fact("account_status", "账号状态", "status", order=10),
            _fact("security_state", "安全状态", "security_state", order=20),
            _fact("registered_at", "注册时间", "created_at", order=30, masked=True),
            _fact(
                "realname_summary",
                "实名状态摘要",
                "realname_summary",
                order=40,
                masked=True,
            ),
            _fact(
                "restriction_reason",
                "受限原因",
                "restriction_reason",
                order=50,
            ),
        ],
        sample_refs=["sample-account-status-query"],
    ),
    _object_template(
        key="community_content",
        name="内容作品",
        provider="community_content_provider",
        mode=ObjectMode.REQUIRED,
        filters=["发布中", "审核中", "不可见"],
        sensitive_fields=["content_summary"],
        facts=[
            _fact("content_title", "内容标题", "title", order=10),
            _fact("content_type", "内容类型", "content_type", order=20),
            _fact("publish_status", "发布状态", "publish_status", order=30),
            _fact("review_status", "审核状态", "review_status", order=40),
            _fact("visibility", "可见性", "visibility", order=50),
            _fact("published_at", "发布时间", "published_at", order=60),
            _fact(
                "content_summary",
                "内容摘要",
                "content_summary",
                order=70,
                masked=True,
            ),
        ],
        sample_refs=[
            "sample-content-status-query",
            "sample-content-violation-diagnosis",
            "sample-content-appeal",
            "sample-governance-report",
        ],
    ),
    _object_template(
        key="membership_entitlement",
        name="会员权益",
        provider="membership_entitlement_provider",
        mode=ObjectMode.REQUIRED,
        filters=["生效中", "已过期"],
        sensitive_fields=["account_identifier"],
        facts=[
            _fact("membership_level", "会员等级", "level", order=10),
            _fact("entitlement_status", "权益状态", "status", order=20),
            _fact("effective_at", "生效时间", "effective_at", order=30),
            _fact("expires_at", "到期时间", "expires_at", order=40),
            _fact("available_benefits", "可用权益", "benefits", order=50),
        ],
        sample_refs=["sample-membership-benefit-query"],
    ),
    _object_template(
        key="membership_order",
        name="会员订单",
        provider="membership_order_provider",
        mode=ObjectMode.REQUIRED,
        filters=["已支付", "开通处理中", "已生效"],
        sensitive_fields=["amount", "transaction_no"],
        facts=[
            _fact("product_name", "商品名称", "product_name", order=10),
            _fact("amount", "支付金额", "amount", order=20, masked=True),
            _fact("payment_status", "支付状态", "payment_status", order=30),
            _fact("paid_at", "支付时间", "paid_at", order=40),
            _fact(
                "entitlement_activation_status",
                "权益开通状态",
                "activation_status",
                order=50,
            ),
            _fact(
                "transaction_no",
                "交易号",
                "transaction_no",
                order=60,
                masked=True,
            ),
        ],
        sample_refs=["sample-membership-renewal-diagnosis"],
    ),
    _object_template(
        key="governance_case",
        name="治理案件",
        provider="governance_case_provider",
        mode=ObjectMode.REQUIRED,
        filters=["处理中", "已生效", "可申诉"],
        sensitive_fields=["evidence_excerpt", "reporter_info"],
        facts=[
            _fact("case_type", "案件类型", "case_type", order=10),
            _fact("target_reference", "对象引用", "target_reference", order=20),
            _fact("violation_type", "违规类型", "violation_type", order=30),
            _fact("handling_status", "处理状态", "status", order=40),
            _fact("penalty_summary", "处罚摘要", "penalty_summary", order=50),
            _fact("appeal_deadline", "申诉期限", "appeal_deadline", order=60),
            _fact(
                "evidence_excerpt",
                "证据摘要",
                "evidence_excerpt",
                order=70,
                masked=True,
            ),
        ],
        sample_refs=[
            "sample-account-penalty-query",
            "sample-account-penalty-appeal",
        ],
    ),
    _object_template(
        key="merchant_collaboration",
        name="商家合作项目",
        provider="merchant_collaboration_provider",
        mode=ObjectMode.REQUIRED,
        filters=["对接中", "执行中", "已结束"],
        sensitive_fields=["contract_summary", "settlement_info"],
        facts=[
            _fact("collaboration_project", "合作项目", "project_name", order=10),
            _fact(
                "collaboration_type",
                "合作类型",
                "collaboration_type",
                order=20,
            ),
            _fact("current_stage", "当前阶段", "stage", order=30),
            _fact("collaboration_status", "合作状态", "status", order=40),
            _fact("owner_queue", "负责队列", "owner_queue", order=50),
            _fact(
                "contract_summary",
                "合同摘要",
                "contract_summary",
                order=60,
                masked=True,
            ),
        ],
        sample_refs=["sample-merchant-collaboration-service"],
    ),
]


def _query_handlers(tool: str, label: str) -> list[dict[str, Any]]:
    return [
        _handler(
            "object-query",
            "query",
            label,
            priority=10,
            tool=tool,
            when={"requires_object": True},
        ),
        _handler(
            "policy-knowledge",
            "knowledge",
            "社区规则与政策",
            priority=20,
            config={"knowledge_base": "content-community-policy"},
        ),
        _handler(
            "human-support",
            "human",
            "内容社区人工队列",
            priority=30,
            queue="content-support",
            when={"message_terms": ["转人工", "人工客服"]},
        ),
    ]


def _action_handlers(tool: str, label: str, queue: str) -> list[dict[str, Any]]:
    return [
        _handler(
            "submit-action",
            "action",
            label,
            priority=10,
            tool=tool,
            when={"requires_object": True},
            config={"requires_confirmation": True},
        ),
        _handler(
            "human-support",
            "human",
            "内容社区人工队列",
            priority=20,
            queue=queue,
            when={"message_terms": ["转人工", "人工客服"]},
        ),
    ]


_SCENARIOS = [
    _scenario(
        key="account-status-query",
        name="账号状态查询",
        description="查询账号当前状态、安全状态和受限原因",
        scenario_kind=ScenarioKind.QUERY,
        execution_template="query",
        maturity=IndustryPackMaturity.GA,
        category_key="account-security",
        object_template_key="community_account",
        keywords=["账号状态", "账号受限", "为什么不能登录", "账号安全"],
        handlers=_query_handlers("community.account.status", "查询账号状态"),
        decisions=[_decision("select-account", "select_object", "选择账号")],
        recommendations=[
            {
                "key": "security-check",
                "label": "如何完成安全验证？",
                "message": "如何完成安全验证？",
                "when": {"object_statuses": ["受限"]},
            }
        ],
        policy_profile="read_only_account_query",
    ),
    _scenario(
        key="account-recovery-diagnosis",
        name="登录与账号找回诊断",
        description="诊断密码、验证码、设备和账号状态导致的登录问题",
        scenario_kind=ScenarioKind.DIAGNOSIS,
        execution_template="consult",
        maturity=IndustryPackMaturity.BETA,
        category_key="account-security",
        object_template_key=None,
        keywords=["登录不上", "账号找回", "密码错误", "验证码收不到"],
        handlers=[
            _handler(
                "recovery-knowledge",
                "knowledge",
                "登录与账号找回知识",
                priority=10,
                config={"knowledge_base": "content-community-account-recovery"},
            ),
            _handler(
                "human-support",
                "human",
                "账号安全人工队列",
                priority=20,
                queue="account-security",
                when={"message_terms": ["转人工", "人工客服"]},
            ),
        ],
        recommendations=[
            {
                "key": "password",
                "label": "忘记密码",
                "message": "我忘记密码了",
                "when": {},
            },
            {
                "key": "verification",
                "label": "收不到验证码",
                "message": "我收不到验证码",
                "when": {},
            },
        ],
        policy_profile="diagnosis_only",
    ),
    _scenario(
        key="account-penalty-query",
        name="账号处罚查询",
        description="查询账号处罚原因、处理状态和申诉期限",
        scenario_kind=ScenarioKind.QUERY,
        execution_template="query",
        maturity=IndustryPackMaturity.BETA,
        category_key="governance",
        object_template_key="governance_case",
        keywords=["账号处罚", "处罚原因", "违规处罚", "申诉期限"],
        handlers=_query_handlers("community.governance.case.status", "查询处罚案件"),
        decisions=[_decision("select-case", "select_object", "选择处罚案件")],
        recommendations=[
            {
                "key": "appeal",
                "label": "我要申诉",
                "message": "我要对处罚提出申诉",
                "when": {},
            }
        ],
        policy_profile="read_only_governance_query",
    ),
    _scenario(
        key="account-penalty-appeal",
        name="账号处罚申诉",
        description="选择处罚案件、填写理由并提交账号处罚申诉",
        scenario_kind=ScenarioKind.ACTION,
        execution_template="action",
        maturity=IndustryPackMaturity.ALPHA,
        category_key="governance",
        object_template_key="governance_case",
        keywords=["处罚申诉", "账号申诉", "申诉处罚"],
        handlers=_action_handlers(
            "community.governance.appeal",
            "提交账号处罚申诉",
            "governance-appeal",
        ),
        decisions=[
            _decision("select-case", "select_object", "选择处罚案件"),
            _decision(
                "confirm-appeal",
                "confirm_action",
                "确认提交账号处罚申诉",
                confirm=True,
            ),
        ],
        recommendations=[
            {
                "key": "penalty-detail",
                "label": "先查看处罚详情",
                "message": "我先查看处罚详情",
                "when": {},
            }
        ],
        policy_profile="high_risk_action",
    ),
    _scenario(
        key="content-status-query",
        name="内容状态查询",
        description="查询内容发布、审核、可见性和发布时间",
        scenario_kind=ScenarioKind.QUERY,
        execution_template="query",
        maturity=IndustryPackMaturity.GA,
        category_key="content-creation",
        object_template_key="community_content",
        keywords=["内容状态", "为什么不能发布", "内容不可见", "审核状态"],
        handlers=_query_handlers("community.content.status", "查询内容状态"),
        decisions=[_decision("select-content", "select_object", "选择内容")],
        recommendations=[
            {
                "key": "review-rule",
                "label": "查看审核规则",
                "message": "社区审核规则是什么？",
                "when": {},
            }
        ],
        policy_profile="read_only_content_query",
    ),
    _scenario(
        key="content-violation-diagnosis",
        name="内容违规诊断",
        description="结合内容状态和社区规则解释违规判定",
        scenario_kind=ScenarioKind.DIAGNOSIS,
        execution_template="consult",
        maturity=IndustryPackMaturity.BETA,
        category_key="content-creation",
        object_template_key="community_content",
        keywords=["内容违规", "为什么被判违规", "审核不通过", "内容被限流"],
        handlers=_query_handlers("community.content.status", "查询内容审核状态"),
        decisions=[_decision("select-content", "select_object", "选择内容")],
        recommendations=[
            {
                "key": "community-rule",
                "label": "查看社区规范",
                "message": "查看社区规范",
                "when": {},
            }
        ],
        policy_profile="diagnosis_read_only",
    ),
    _scenario(
        key="content-appeal",
        name="内容申诉办理",
        description="选择内容、补充申诉理由并提交内容审核申诉",
        scenario_kind=ScenarioKind.ACTION,
        execution_template="action",
        maturity=IndustryPackMaturity.ALPHA,
        category_key="content-creation",
        object_template_key="community_content",
        keywords=["内容申诉", "申诉审核结果", "内容被误判"],
        handlers=_action_handlers(
            "community.content.appeal",
            "提交内容审核申诉",
            "content-appeal",
        ),
        decisions=[
            _decision("select-content", "select_object", "选择内容"),
            _decision(
                "confirm-appeal",
                "confirm_action",
                "确认提交内容申诉",
                confirm=True,
            ),
        ],
        recommendations=[
            {
                "key": "violation-detail",
                "label": "先查看违规原因",
                "message": "先查看这条内容的违规原因",
                "when": {},
            }
        ],
        policy_profile="high_risk_action",
    ),
    _scenario(
        key="membership-benefit-query",
        name="会员权益查询",
        description="查询会员等级、权益状态、生效时间和到期时间",
        scenario_kind=ScenarioKind.QUERY,
        execution_template="query",
        maturity=IndustryPackMaturity.GA,
        category_key="membership",
        object_template_key="membership_entitlement",
        keywords=["会员权益", "会员到期", "会员等级", "权益状态"],
        handlers=_query_handlers("community.membership.entitlement", "查询会员权益"),
        decisions=[_decision("select-entitlement", "select_object", "选择会员权益")],
        recommendations=[
            {
                "key": "renewal",
                "label": "如何续费",
                "message": "会员如何续费？",
                "when": {},
            }
        ],
        policy_profile="read_only_membership_query",
    ),
    _scenario(
        key="membership-renewal-diagnosis",
        name="会员续费与权益未到账诊断",
        description="查询会员订单支付和权益开通状态，解释未到账原因",
        scenario_kind=ScenarioKind.DIAGNOSIS,
        execution_template="query",
        maturity=IndustryPackMaturity.BETA,
        category_key="membership",
        object_template_key="membership_order",
        keywords=["续费未到账", "会员没生效", "支付成功会员没到账", "会员订单"],
        handlers=_query_handlers(
            "community.membership.order.status",
            "查询会员订单",
        ),
        decisions=[_decision("select-order", "select_object", "选择会员订单")],
        recommendations=[
            {
                "key": "payment-check",
                "label": "查看支付状态",
                "message": "查看这笔会员订单的支付状态",
                "when": {},
            }
        ],
        policy_profile="diagnosis_read_only",
    ),
    _scenario(
        key="governance-report",
        name="举报与治理反馈",
        description="选择内容或账号、确认举报信息并进入社区治理队列",
        scenario_kind=ScenarioKind.ACTION,
        execution_template="action",
        maturity=IndustryPackMaturity.BETA,
        category_key="governance",
        object_template_key="community_content",
        keywords=["举报内容", "举报账号", "治理反馈", "投诉违规内容"],
        handlers=_action_handlers(
            "community.governance.report",
            "提交社区治理举报",
            "governance-review",
        ),
        decisions=[
            _decision("select-content", "select_object", "选择举报对象"),
            _decision(
                "confirm-report",
                "confirm_action",
                "确认提交举报",
                confirm=True,
            ),
        ],
        recommendations=[
            {
                "key": "report-rule",
                "label": "查看举报规则",
                "message": "举报规则是什么？",
                "when": {},
            }
        ],
        policy_profile="governance_action",
    ),
    _scenario(
        key="merchant-collaboration-service",
        name="商家合作进度与服务",
        description="查询商家合作项目阶段、状态和负责队列",
        scenario_kind=ScenarioKind.SERVICE,
        execution_template="query",
        maturity=IndustryPackMaturity.BETA,
        category_key="merchant",
        object_template_key="merchant_collaboration",
        keywords=["商家合作", "合作进度", "合作项目", "合作到哪一步"],
        handlers=_query_handlers(
            "community.merchant.collaboration.status",
            "查询商家合作项目",
        ),
        decisions=[_decision("select-project", "select_object", "选择合作项目")],
        recommendations=[
            {
                "key": "contact",
                "label": "联系合作经理",
                "message": "我想联系合作经理",
                "when": {},
            }
        ],
        policy_profile="partner_read_only_query",
    ),
]


_OBJECT_SAMPLES: dict[str, dict[str, Any]] = {
    "community_account": {
        "status": "受限",
        "facts": {
            "status": "受限",
            "security_state": "需要安全验证",
            "created_at": "2024-03-12",
            "realname_summary": "已实名",
            "restriction_reason": "检测到异常登录风险",
        },
    },
    "community_content": {
        "status": "审核中",
        "facts": {
            "title": "周末城市散步路线",
            "content_type": "图文",
            "publish_status": "待发布",
            "review_status": "审核中",
            "visibility": "仅自己可见",
            "published_at": "",
            "content_summary": "一篇记录城市散步路线的图文内容",
        },
    },
    "membership_entitlement": {
        "status": "生效中",
        "facts": {
            "level": "年度会员",
            "status": "生效中",
            "effective_at": "2026-01-01",
            "expires_at": "2026-12-31",
            "benefits": ["专属标识", "内容置顶", "会员客服"],
        },
    },
    "membership_order": {
        "status": "已支付",
        "facts": {
            "product_name": "年度会员续费",
            "amount": "168.00",
            "payment_status": "已支付",
            "paid_at": "2026-10-31 20:15",
            "activation_status": "开通处理中",
            "transaction_no": "PAY-20261031-001",
        },
    },
    "governance_case": {
        "status": "处理中",
        "facts": {
            "case_type": "账号处罚",
            "target_reference": "ACCOUNT-SIM-001",
            "violation_type": "异常营销内容",
            "status": "处理中",
            "penalty_summary": "限制发布 7 天",
            "appeal_deadline": "2026-11-09",
            "evidence_excerpt": "系统检测到重复营销内容",
        },
    },
    "merchant_collaboration": {
        "status": "执行中",
        "facts": {
            "project_name": "城市生活内容共创计划",
            "collaboration_type": "内容合作",
            "stage": "内容制作",
            "status": "执行中",
            "owner_queue": "merchant-success",
            "contract_summary": "年度内容合作框架",
        },
    },
}


_SAMPLE_SPECS = [
    ("account-status-query", "我的账号现在是什么状态？", "community_account"),
    ("account-recovery-diagnosis", "我登录不上，想找回账号。", None),
    ("account-penalty-query", "我收到了什么处罚？", "governance_case"),
    ("account-penalty-appeal", "我要对账号处罚提出申诉。", "governance_case"),
    ("content-status-query", "我的内容为什么不能发布？", "community_content"),
    ("content-violation-diagnosis", "这篇内容为什么被判定违规？", "community_content"),
    ("content-appeal", "我要对内容审核结果提出申诉。", "community_content"),
    ("membership-benefit-query", "我的会员有哪些权益？", "membership_entitlement"),
    ("membership-renewal-diagnosis", "我续费了，为什么会员还没生效？", "membership_order"),
    ("governance-report", "我要举报这篇内容。", "community_content"),
    ("merchant-collaboration-service", "我的合作项目现在到哪一步？", "merchant_collaboration"),
]


def _samples() -> list[PackSample]:
    samples: list[PackSample] = []
    for scenario_key, message, object_template_key in _SAMPLE_SPECS:
        simulated_object: SimulatedObject | None = None
        if object_template_key is not None:
            object_sample = deepcopy(_OBJECT_SAMPLES[object_template_key])
            simulated_object = SimulatedObject(
                id=f"SIM-{scenario_key.upper()}",
                type=object_template_key,
                status=object_sample["status"],
                facts=object_sample["facts"],
            )
        samples.append(
            PackSample(
                sample_id=f"sample-{scenario_key}",
                scenario_template_key=scenario_key,
                name=f"{scenario_key} 模拟样例",
                message=message,
                object=simulated_object,
                description="用于客户体验预览和确定性模拟的 Pack 样例。",
            )
        )
    return samples


_ACCEPTANCE_SPECS = [
    (
        "account-status-query",
        "succeeded",
        "query",
        ["account_status", "security_state"],
        ["registered_at", "realname_summary"],
    ),
    (
        "account-recovery-diagnosis",
        "succeeded",
        "knowledge",
        [],
        [],
    ),
    (
        "account-penalty-query",
        "succeeded",
        "query",
        ["violation_type", "penalty_summary"],
        ["evidence_excerpt"],
    ),
    (
        "account-penalty-appeal",
        "needs_input",
        "action",
        ["violation_type"],
        ["reporter_info"],
    ),
    (
        "content-status-query",
        "succeeded",
        "query",
        ["review_status", "visibility"],
        ["content_summary"],
    ),
    (
        "content-violation-diagnosis",
        "succeeded",
        "query",
        ["review_status"],
        ["content_summary"],
    ),
    (
        "content-appeal",
        "needs_input",
        "action",
        ["review_status"],
        ["content_summary"],
    ),
    (
        "membership-benefit-query",
        "succeeded",
        "query",
        ["membership_level", "expires_at"],
        ["account_identifier"],
    ),
    (
        "membership-renewal-diagnosis",
        "succeeded",
        "query",
        ["payment_status", "entitlement_activation_status"],
        ["transaction_no", "amount"],
    ),
    (
        "governance-report",
        "needs_input",
        "action",
        ["content_type"],
        ["reporter_info"],
    ),
    (
        "merchant-collaboration-service",
        "succeeded",
        "query",
        ["collaboration_status", "current_stage"],
        ["contract_summary", "settlement_info"],
    ),
]


def _acceptance_cases() -> list[AcceptanceCase]:
    return [
        AcceptanceCase(
            case_id=f"case-{scenario_key}",
            scenario_template_key=scenario_key,
            required=True,
            given="使用 Pack 内与该场景关联的模拟业务对象。",
            when="客户进入场景并执行自然语言模拟。",
            then={
                "result_status": result_status,
                "handler_type": handler_type,
                "must_include_facts": must_include,
                "must_not_include": must_not_include,
            },
        )
        for (
            scenario_key,
            result_status,
            handler_type,
            must_include,
            must_not_include,
        ) in _ACCEPTANCE_SPECS
    ]


def _application_blueprint() -> ApplicationBlueprint:
    return ApplicationBlueprint(
        application_key="content-community-service",
        name="内容社区服务",
        description="账号、内容、会员权益、社区治理与商家合作的统一服务应用",
        catalog_category_keys=[
            "account-security",
            "content-creation",
            "membership",
            "governance",
            "merchant",
            "general",
        ],
        scenario_template_keys=[
            "account-status-query",
            "content-status-query",
            "membership-benefit-query",
        ],
        scenario_template_versions={
            "account-status-query": TEMPLATE_VERSION,
            "content-status-query": TEMPLATE_VERSION,
            "membership-benefit-query": TEMPLATE_VERSION,
        },
        capabilities=[
            ApplicationCapability(
                key="direct",
                type="direct",
                label="Direct",
                priority=10,
                config={"description": "固定回执、服务时间和确定性回复。"},
            ),
            ApplicationCapability(
                key="knowledge",
                type="knowledge",
                label="知识检索",
                priority=20,
                config={"description": "社区规范、会员政策和账号安全知识。"},
            ),
            ApplicationCapability(
                key="business-query",
                type="query",
                label="业务查询",
                priority=30,
                config={
                    "description": "账号、内容、会员权益等只读业务对象查询。",
                    "tools": [
                        "community.account.status",
                        "community.content.status",
                        "community.membership.entitlement",
                    ],
                },
            ),
            ApplicationCapability(
                key="business-action",
                type="action",
                label="业务办理",
                priority=40,
                config={
                    "description": "申诉、举报等需要确认的业务动作。",
                    "tools": [
                        "community.governance.appeal",
                        "community.content.appeal",
                        "community.governance.report",
                    ],
                },
            ),
            ApplicationCapability(
                key="human-support",
                type="human",
                label="人工客服",
                priority=50,
                queue="content-support",
                config={"description": "携带场景、对象、事实和轨迹的人工兜底。"},
            ),
            ApplicationCapability(
                key="service-tracking",
                type="tracking",
                label="处理进度跟踪",
                priority=60,
                config={"description": "申诉、举报和治理处理进度查询。"},
            ),
        ],
        default_execution_order=["deterministic", "action", "agent", "human"],
        channels=[
            ApplicationChannel(
                key="web",
                name="官网帮助中心",
                type="web",
                status="active",
            ),
            ApplicationChannel(
                key="app",
                name="社区 App",
                type="app",
                status="active",
            ),
            ApplicationChannel(
                key="wechat",
                name="社区服务号",
                type="wechat",
                status="active",
            ),
            ApplicationChannel(
                key="h5",
                name="H5 服务页",
                type="h5",
                status="canary",
            ),
        ],
    )


def build_content_community_pack() -> IndustryPackManifest:
    """Build a fresh, validated content-community pack manifest."""

    return IndustryPackManifest(
        schema_version="v1",
        pack_key="content-community",
        name="内容社区",
        description="账号、内容、会员权益、社区治理与商家合作场景包",
        pack_version="1.0.0",
        maturity=IndustryPackMaturity.BETA,
        supported_channels=["web", "app", "wechat", "h5"],
        catalog_categories=[
            CatalogCategoryTemplate(key="account-security", name="账号与安全", order=10),
            CatalogCategoryTemplate(key="content-creation", name="内容与创作", order=20),
            CatalogCategoryTemplate(key="membership", name="会员与权益", order=30),
            CatalogCategoryTemplate(key="governance", name="社区治理", order=40),
            CatalogCategoryTemplate(key="merchant", name="商家合作", order=50),
            CatalogCategoryTemplate(key="general", name="通用服务", order=60),
        ],
        object_templates=deepcopy(_OBJECT_TEMPLATES),
        scenario_templates=deepcopy(_SCENARIOS),
        sample_data=_samples(),
        acceptance_cases=_acceptance_cases(),
        application_blueprint=_application_blueprint(),
    )


CONTENT_COMMUNITY_PACK = build_content_community_pack()


__all__ = [
    "CONTENT_COMMUNITY_PACK",
    "TEMPLATE_VERSION",
    "build_content_community_pack",
]
