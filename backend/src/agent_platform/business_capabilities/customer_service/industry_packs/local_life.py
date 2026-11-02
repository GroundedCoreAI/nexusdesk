"""Local-life industry pack V1.

This pack is a second, independent content asset compiled by the same
industry-pack compiler as the content-community pack.  It adds no runtime
industry entities and no code branches on the pack key.
"""

from __future__ import annotations

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
    filters: list[str],
    sample_refs: list[str],
    mode: ObjectMode = ObjectMode.REQUIRED,
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
            "filters": filters,
            "empty_state": "没有找到可处理的本地生活业务对象，请重新选择或转人工。",
            "unavailable_state": "本地生活业务对象暂时不可用，请稍后重试或转人工。",
        },
        sample_refs=sample_refs,
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
    object_template_key: str,
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
            "domain": "本地生活",
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
            "service-knowledge",
            "knowledge",
            "本地生活服务规则",
            priority=20,
            config={"knowledge_base": "local-life-policy"},
        ),
        _handler(
            "human-support",
            "human",
            "本地生活人工队列",
            priority=30,
            queue="local-life-support",
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
            "本地生活人工队列",
            priority=20,
            queue=queue,
            when={"message_terms": ["转人工", "人工客服"]},
        ),
    ]


_OBJECT_TEMPLATES = [
    _object_template(
        key="local_life_order",
        name="本地生活订单",
        provider="local_life_order_provider",
        filters=["待核销", "已完成", "可退款"],
        sensitive_fields=["total_amount", "contact_phone"],
        sample_refs=[
            "sample-order-status-query",
            "sample-fulfillment-exception-diagnosis",
            "sample-refund-after-sales",
        ],
        facts=[
            _fact("order_status", "订单状态", "status", order=10),
            _fact("merchant_name", "商家名称", "merchant_name", order=20),
            _fact("store_name", "门店名称", "store_name", order=30),
            _fact("total_amount", "订单金额", "total_amount", order=40, masked=True),
            _fact("scheduled_at", "预约/到店时间", "scheduled_at", order=50),
            _fact(
                "fulfillment_status",
                "履约状态",
                "fulfillment_status",
                order=60,
            ),
            _fact("pickup_code", "核销码", "pickup_code", order=70),
            _fact(
                "contact_phone",
                "联系手机号",
                "contact_phone",
                order=80,
                masked=True,
            ),
        ],
    ),
    _object_template(
        key="reservation_record",
        name="预约与核销记录",
        provider="reservation_record_provider",
        filters=["已预约", "待到店", "已核销"],
        sensitive_fields=["contact_phone"],
        sample_refs=["sample-reservation-progress-query"],
        facts=[
            _fact("reservation_status", "预约状态", "status", order=10),
            _fact("merchant_name", "商家名称", "merchant_name", order=20),
            _fact("store_name", "门店名称", "store_name", order=30),
            _fact("reserved_at", "预约时间", "reserved_at", order=40),
            _fact("arrival_status", "到店状态", "arrival_status", order=50),
            _fact(
                "verification_status",
                "核销状态",
                "verification_status",
                order=60,
            ),
            _fact("queue_no", "排队号", "queue_no", order=70),
            _fact("party_size", "到店人数", "party_size", order=80),
            _fact(
                "contact_phone",
                "联系手机号",
                "contact_phone",
                order=90,
                masked=True,
            ),
        ],
    ),
    _object_template(
        key="refund_after_sales",
        name="退款与售后单",
        provider="refund_after_sales_provider",
        filters=["审核中", "退款中", "已退款"],
        sensitive_fields=["refund_amount", "payout_account"],
        sample_refs=["sample-refund-progress-query"],
        facts=[
            _fact("refund_status", "售后状态", "status", order=10),
            _fact("after_sales_type", "售后类型", "after_sales_type", order=20),
            _fact(
                "refund_amount",
                "退款金额",
                "refund_amount",
                order=30,
                masked=True,
            ),
            _fact("refund_reason", "退款原因", "reason", order=40),
            _fact("applied_at", "申请时间", "applied_at", order=50),
            _fact(
                "expected_completion_at",
                "预计完成时间",
                "expected_completion_at",
                order=60,
            ),
            _fact("order_ref", "关联订单", "order_ref", order=70),
            _fact(
                "handling_progress",
                "处理进度",
                "handling_progress",
                order=80,
            ),
            _fact(
                "payout_account",
                "退款账户",
                "payout_account",
                order=90,
                masked=True,
            ),
        ],
    ),
    _object_template(
        key="merchant_store",
        name="商家门店",
        provider="merchant_store_provider",
        filters=["营业中", "休息中", "合作中"],
        sensitive_fields=["contact_name", "contact_phone"],
        sample_refs=["sample-merchant-store-service"],
        facts=[
            _fact("merchant_name", "商家名称", "merchant_name", order=10),
            _fact("store_name", "门店名称", "store_name", order=20),
            _fact("business_status", "营业状态", "business_status", order=30),
            _fact("store_address", "门店地址", "store_address", order=40),
            _fact("opening_hours", "营业时间", "opening_hours", order=50),
            _fact(
                "service_phone",
                "门店电话",
                "service_phone",
                order=60,
                masked=True,
            ),
            _fact("queue_status", "排队状态", "queue_status", order=70),
            _fact(
                "cooperation_stage",
                "合作阶段",
                "cooperation_stage",
                order=80,
            ),
            _fact("contact_name", "联系人", "contact_name", order=90, masked=True),
            _fact(
                "contact_phone",
                "联系人电话",
                "contact_phone",
                order=100,
                masked=True,
            ),
        ],
    ),
]


_SCENARIOS = [
    _scenario(
        key="order-status-query",
        name="本地生活订单状态查询",
        description="查询团购、到店或外卖订单状态、履约状态和预约时间",
        scenario_kind=ScenarioKind.QUERY,
        execution_template="query",
        maturity=IndustryPackMaturity.GA,
        category_key="order-fulfillment",
        object_template_key="local_life_order",
        keywords=["订单状态", "团购订单", "到店订单", "订单到哪一步", "履约状态"],
        handlers=_query_handlers("local_life.order.status", "查询本地生活订单"),
        decisions=[_decision("select-order", "select_object", "选择本地生活订单")],
        recommendations=[
            {
                "key": "store-route",
                "label": "查看门店信息",
                "message": "查看门店营业时间和地址",
                "when": {},
            }
        ],
        policy_profile="read_only_order_query",
    ),
    _scenario(
        key="reservation-progress-query",
        name="预约与到店进度查询",
        description="查询预约状态、到店状态、排队号和核销记录",
        scenario_kind=ScenarioKind.QUERY,
        execution_template="query",
        maturity=IndustryPackMaturity.GA,
        category_key="reservation",
        object_template_key="reservation_record",
        keywords=["预约进度", "到店排队", "核销记录", "预约时间", "排队号"],
        handlers=_query_handlers(
            "local_life.reservation.status",
            "查询预约与核销记录",
        ),
        decisions=[_decision("select-reservation", "select_object", "选择预约记录")],
        recommendations=[
            {
                "key": "arrival-guide",
                "label": "到店核销说明",
                "message": "到店后如何核销？",
                "when": {},
            }
        ],
        policy_profile="read_only_reservation_query",
    ),
    _scenario(
        key="fulfillment-exception-diagnosis",
        name="履约异常诊断",
        description="结合订单状态、门店信息和履约记录解释无法到店或核销失败",
        scenario_kind=ScenarioKind.DIAGNOSIS,
        execution_template="consult",
        maturity=IndustryPackMaturity.BETA,
        category_key="order-fulfillment",
        object_template_key="local_life_order",
        keywords=["履约异常", "商家没履约", "到店无法使用", "核销失败", "门店休息"],
        handlers=_query_handlers(
            "local_life.order.fulfillment",
            "查询订单履约记录",
        ),
        decisions=[_decision("select-order", "select_object", "选择异常订单")],
        recommendations=[
            {
                "key": "refund",
                "label": "申请退款或售后",
                "message": "我要申请退款或售后",
                "when": {},
            }
        ],
        policy_profile="diagnosis_read_only",
    ),
    _scenario(
        key="refund-after-sales",
        name="退款与售后办理",
        description="选择本地生活订单，确认后提交退款或售后申请",
        scenario_kind=ScenarioKind.ACTION,
        execution_template="action",
        maturity=IndustryPackMaturity.ALPHA,
        category_key="after-sales",
        object_template_key="local_life_order",
        keywords=["退款", "售后", "申请退款", "商家不履约退款", "售后退款"],
        handlers=_action_handlers(
            "local_life.refund.create",
            "提交退款或售后申请",
            "local-life-after-sales",
        ),
        decisions=[
            _decision("select-order", "select_object", "选择退款订单"),
            _decision(
                "confirm-refund",
                "confirm_action",
                "确认提交退款或售后申请",
                confirm=True,
            ),
        ],
        recommendations=[
            {
                "key": "refund-rule",
                "label": "查看退款规则",
                "message": "本地生活退款规则是什么？",
                "when": {},
            }
        ],
        policy_profile="high_risk_action",
    ),
    _scenario(
        key="refund-progress-query",
        name="退款与售后进度查询",
        description="查询退款审核、处理进度和预计完成时间",
        scenario_kind=ScenarioKind.QUERY,
        execution_template="query",
        maturity=IndustryPackMaturity.BETA,
        category_key="after-sales",
        object_template_key="refund_after_sales",
        keywords=["退款进度", "售后进度", "退款到账", "退款审核", "售后单"],
        handlers=_query_handlers(
            "local_life.refund.status",
            "查询退款与售后单",
        ),
        decisions=[_decision("select-refund", "select_object", "选择退款或售后单")],
        recommendations=[
            {
                "key": "refund-time",
                "label": "退款多久到账",
                "message": "退款多久到账？",
                "when": {},
            }
        ],
        policy_profile="read_only_after_sales_query",
    ),
    _scenario(
        key="merchant-store-service",
        name="商家门店服务",
        description="查询门店营业状态、排队情况、服务电话和合作阶段",
        scenario_kind=ScenarioKind.SERVICE,
        execution_template="query",
        maturity=IndustryPackMaturity.BETA,
        category_key="merchant-service",
        object_template_key="merchant_store",
        keywords=["门店营业", "商家合作", "门店状态", "排队情况", "门店电话"],
        handlers=_query_handlers("local_life.store.status", "查询商家门店"),
        decisions=[_decision("select-store", "select_object", "选择商家门店")],
        recommendations=[
            {
                "key": "cooperation",
                "label": "联系合作经理",
                "message": "我想联系合作经理",
                "when": {},
            }
        ],
        policy_profile="merchant_read_only_query",
    ),
]


def _object(
    object_type: str,
    object_id: str,
    status: str,
    facts: dict[str, Any],
) -> SimulatedObject:
    return SimulatedObject(
        id=object_id,
        type=object_type,
        status=status,
        facts=facts,
    )


def _samples() -> list[PackSample]:
    return [
        PackSample(
            sample_id="sample-order-status-query",
            scenario_template_key="order-status-query",
            name="本地生活订单状态样例",
            message="我的团购订单现在是什么状态？",
            object=_object(
                "local_life_order",
                "SIM-LOCAL-ORDER-001",
                "待核销",
                {
                    "status": "待核销",
                    "merchant_name": "城市咖啡实验室",
                    "store_name": "滨江店",
                    "total_amount": "99.00",
                    "scheduled_at": "2026-11-03 18:30",
                    "fulfillment_status": "待到店核销",
                    "pickup_code": "A128",
                    "contact_phone": "13800001234",
                },
            ),
            description="用于订单状态查询、客户体验预览和确定性模拟。",
        ),
        PackSample(
            sample_id="sample-reservation-progress-query",
            scenario_template_key="reservation-progress-query",
            name="预约到店样例",
            message="我的预约到店排队到哪一步了？",
            object=_object(
                "reservation_record",
                "SIM-LOCAL-RESERVATION-001",
                "已预约",
                {
                    "status": "已预约",
                    "merchant_name": "江南小馆",
                    "store_name": "湖滨店",
                    "reserved_at": "2026-11-03 19:00",
                    "arrival_status": "未到店",
                    "verification_status": "未核销",
                    "queue_no": "A012",
                    "party_size": 2,
                    "contact_phone": "13800001234",
                },
            ),
            description="用于预约、排队和核销进度模拟。",
        ),
        PackSample(
            sample_id="sample-fulfillment-exception-diagnosis",
            scenario_template_key="fulfillment-exception-diagnosis",
            name="履约异常样例",
            message="我到店后商家说无法核销，帮我看看为什么。",
            object=_object(
                "local_life_order",
                "SIM-LOCAL-ORDER-EXC-001",
                "待核销",
                {
                    "status": "待核销",
                    "merchant_name": "城市咖啡实验室",
                    "store_name": "滨江店",
                    "total_amount": "128.00",
                    "scheduled_at": "2026-11-02 18:00",
                    "fulfillment_status": "门店临时休息",
                    "pickup_code": "B229",
                    "contact_phone": "13800001234",
                },
            ),
            description="用于履约异常和核销失败诊断。",
        ),
        PackSample(
            sample_id="sample-refund-after-sales",
            scenario_template_key="refund-after-sales",
            name="退款售后办理样例",
            message="商家无法履约，我要申请退款。",
            object=_object(
                "local_life_order",
                "SIM-LOCAL-ORDER-REFUND-001",
                "可退款",
                {
                    "status": "可退款",
                    "merchant_name": "城市咖啡实验室",
                    "store_name": "滨江店",
                    "total_amount": "88.00",
                    "scheduled_at": "2026-11-02 18:00",
                    "fulfillment_status": "商家未履约",
                    "pickup_code": "C331",
                    "contact_phone": "13800001234",
                },
            ),
            description="办理样例不预选确认决策，用于验证确认门禁。",
        ),
        PackSample(
            sample_id="sample-refund-progress-query",
            scenario_template_key="refund-progress-query",
            name="退款进度样例",
            message="我的退款审核到哪一步了？",
            object=_object(
                "refund_after_sales",
                "SIM-LOCAL-REFUND-001",
                "处理中",
                {
                    "status": "处理中",
                    "after_sales_type": "退款",
                    "refund_amount": "59.00",
                    "reason": "商家未履约",
                    "applied_at": "2026-11-01 20:15",
                    "expected_completion_at": "2026-11-04 23:59",
                    "order_ref": "SIM-LOCAL-ORDER-001",
                    "handling_progress": "商家审核中",
                    "payout_account": "wx***1234",
                },
            ),
            description="用于退款审核和处理进度查询。",
        ),
        PackSample(
            sample_id="sample-merchant-store-service",
            scenario_template_key="merchant-store-service",
            name="商家门店样例",
            message="这家门店现在营业吗？需要排队吗？",
            object=_object(
                "merchant_store",
                "SIM-LOCAL-STORE-001",
                "营业中",
                {
                    "merchant_name": "江南小馆",
                    "store_name": "湖滨店",
                    "business_status": "营业中",
                    "store_address": "杭州市湖滨路 88 号",
                    "opening_hours": "10:00-22:00",
                    "service_phone": "0571-88886666",
                    "queue_status": "前面还有 3 桌",
                    "cooperation_stage": "执行中",
                    "contact_name": "张经理",
                    "contact_phone": "13900001111",
                },
            ),
            description="用于门店营业状态和合作进度查询。",
        ),
    ]


def _acceptance_cases() -> list[AcceptanceCase]:
    return [
        AcceptanceCase(
            case_id="case-order-status-query",
            scenario_template_key="order-status-query",
            required=True,
            given="客户持有待核销的本地生活订单。",
            when="客户查询订单状态。",
            then={
                "result_status": "succeeded",
                "handler_type": "query",
                "must_include_facts": ["order_status", "fulfillment_status"],
                "must_not_include": ["total_amount", "contact_phone"],
            },
        ),
        AcceptanceCase(
            case_id="case-reservation-progress-query",
            scenario_template_key="reservation-progress-query",
            required=True,
            given="客户持有已预约记录。",
            when="客户查询到店与核销进度。",
            then={
                "result_status": "succeeded",
                "handler_type": "query",
                "must_include_facts": ["reservation_status", "verification_status"],
                "must_not_include": ["contact_phone"],
            },
        ),
        AcceptanceCase(
            case_id="case-fulfillment-exception-diagnosis",
            scenario_template_key="fulfillment-exception-diagnosis",
            required=True,
            given="订单履约状态为门店临时休息。",
            when="客户反馈到店后无法核销。",
            then={
                "result_status": "succeeded",
                "handler_type": "query",
                "must_include_facts": ["order_status", "fulfillment_status"],
                "must_not_include": ["total_amount"],
            },
        ),
        AcceptanceCase(
            case_id="case-refund-after-sales",
            scenario_template_key="refund-after-sales",
            required=True,
            given="客户持有可退款订单。",
            when="客户提交退款申请但尚未确认动作。",
            then={
                "result_status": "needs_input",
                "handler_type": "action",
                "must_include_facts": ["order_status"],
                "must_not_include": ["total_amount", "contact_phone"],
            },
        ),
        AcceptanceCase(
            case_id="case-refund-progress-query",
            scenario_template_key="refund-progress-query",
            required=True,
            given="客户持有一笔处理中的退款单。",
            when="客户查询退款审核进度。",
            then={
                "result_status": "succeeded",
                "handler_type": "query",
                "must_include_facts": ["refund_status", "handling_progress"],
                "must_not_include": ["refund_amount", "payout_account"],
            },
        ),
        AcceptanceCase(
            case_id="case-merchant-store-service",
            scenario_template_key="merchant-store-service",
            required=True,
            given="客户持有一家合作门店。",
            when="客户查询门店营业和排队状态。",
            then={
                "result_status": "succeeded",
                "handler_type": "query",
                "must_include_facts": ["business_status", "queue_status"],
                "must_not_include": ["contact_name", "contact_phone"],
            },
        ),
    ]


def _application_blueprint() -> ApplicationBlueprint:
    return ApplicationBlueprint(
        application_key="local-life-service",
        name="本地生活服务",
        description="订单履约、预约到店、退款售后和商家门店的统一服务应用",
        catalog_category_keys=[
            "order-fulfillment",
            "reservation",
            "after-sales",
            "merchant-service",
            "general",
        ],
        scenario_template_keys=[
            "order-status-query",
            "reservation-progress-query",
        ],
        scenario_template_versions={
            "order-status-query": TEMPLATE_VERSION,
            "reservation-progress-query": TEMPLATE_VERSION,
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
                config={"description": "退款规则、核销规则和门店服务政策。"},
            ),
            ApplicationCapability(
                key="business-query",
                type="query",
                label="业务查询",
                priority=30,
                config={
                    "description": "本地生活订单、预约、退款和门店状态查询。",
                    "tools": [
                        "local_life.order.status",
                        "local_life.reservation.status",
                        "local_life.refund.status",
                        "local_life.store.status",
                    ],
                },
            ),
            ApplicationCapability(
                key="business-action",
                type="action",
                label="业务办理",
                priority=40,
                config={
                    "description": "退款和售后等需要用户确认的业务动作。",
                    "tools": ["local_life.refund.create"],
                },
            ),
            ApplicationCapability(
                key="human-support",
                type="human",
                label="人工客服",
                priority=50,
                queue="local-life-support",
                config={"description": "携带订单、预约、售后与轨迹的人工兜底。"},
            ),
            ApplicationCapability(
                key="after-sales-human",
                type="human",
                label="退款售后人工",
                priority=55,
                queue="local-life-after-sales",
                config={"description": "退款申请、售后处理和争议升级的人工兜底。"},
            ),
            ApplicationCapability(
                key="service-tracking",
                type="tracking",
                label="处理进度跟踪",
                priority=60,
                config={"description": "退款、售后和商家履约处理进度。"},
            ),
        ],
        default_execution_order=["deterministic", "action", "agent", "human"],
        channels=[
            ApplicationChannel(
                key="web",
                name="本地生活帮助中心",
                type="web",
                status="active",
            ),
            ApplicationChannel(
                key="app",
                name="本地生活 App",
                type="app",
                status="active",
            ),
            ApplicationChannel(
                key="wechat",
                name="本地生活服务号",
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


def build_local_life_pack() -> IndustryPackManifest:
    """Build a fresh, validated local-life pack manifest."""

    return IndustryPackManifest(
        schema_version="v1",
        pack_key="local-life",
        name="本地生活",
        description="订单履约、预约到店、退款售后与商家门店场景包",
        pack_version="1.0.0",
        maturity=IndustryPackMaturity.BETA,
        supported_channels=["web", "app", "wechat", "h5"],
        catalog_categories=[
            CatalogCategoryTemplate(key="order-fulfillment", name="订单与履约", order=10),
            CatalogCategoryTemplate(key="reservation", name="预约与到店", order=20),
            CatalogCategoryTemplate(key="after-sales", name="退款与售后", order=30),
            CatalogCategoryTemplate(key="merchant-service", name="商家与门店", order=40),
            CatalogCategoryTemplate(key="general", name="通用服务", order=50),
        ],
        object_templates=_OBJECT_TEMPLATES,
        scenario_templates=_SCENARIOS,
        sample_data=_samples(),
        acceptance_cases=_acceptance_cases(),
        application_blueprint=_application_blueprint(),
    )


LOCAL_LIFE_PACK = build_local_life_pack()


__all__ = [
    "LOCAL_LIFE_PACK",
    "TEMPLATE_VERSION",
    "build_local_life_pack",
]
