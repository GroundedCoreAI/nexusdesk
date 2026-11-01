"""Default V1 service scenarios.

These definitions are platform templates, not runtime fixtures: an operator
can edit every field through the scenario API after seeding.  Keeping the
defaults in one module makes the first two scenes examples of the same
configuration contract rather than special-cased code paths.
"""

from copy import deepcopy
from typing import Any
from uuid import UUID

from .models import ScenarioConfig


def _entry(key: str, kind: str, label: str, description: str = "") -> dict[str, Any]:
    return {
        "key": key,
        "type": kind,
        "label": label,
        "description": description,
        "enabled": True,
        "config": {},
    }


def _handler(
    key: str,
    kind: str,
    label: str,
    *,
    priority: int = 20,
    when: dict[str, Any] | None = None,
    reply: str | None = None,
    queue: str | None = None,
    tool: str | None = None,
    agent_id: UUID | None = None,
    agent_version: int | None = None,
    agent_name: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "type": kind,
        "label": label,
        "priority": priority,
        "enabled": True,
        "when": when or {},
        "reply": reply,
        "queue": queue,
        "tool": tool,
        "agent_id": agent_id,
        "agent_version": agent_version,
        "agent_name": agent_name,
        "config": config or {},
    }


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


def _decision(
    key: str,
    kind: str,
    label: str,
    *,
    options: list[dict[str, Any]] | None = None,
    required: bool = True,
    confirm: bool = False,
    correctable: bool = True,
    allow_free_text: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "kind": kind,
        "label": label,
        "required": required,
        "options": options or [],
        "allow_free_text": allow_free_text,
        "allow_skip": not required,
        "confirm": confirm,
        "correctable": correctable,
        "when": {},
    }


def _order_object() -> dict[str, Any]:
    return {
        "type": "order",
        "provider": "order_provider",
        "required": True,
        "mode": "required",
        "candidate_strategy": {
            "sort": "recent_desc",
            "limit": 5,
            "filters": ["待收货", "已完成", "退款/售后"],
            "empty_state": "没有找到可咨询的订单，可以切换其他业务或转人工。",
            "unavailable_state": "订单暂时不可用，请稍后重试或转人工。",
        },
        "permission_policy": "customer_scope",
        "config": {},
    }


def _no_object() -> dict[str, Any]:
    return {
        "type": "none",
        "provider": "",
        "required": False,
        "mode": "none",
        "candidate_strategy": {
            "sort": "recent_desc",
            "limit": 5,
            "filters": [],
            "empty_state": "",
            "unavailable_state": "",
        },
        "permission_policy": "customer_scope",
        "config": {},
    }


def _base(
    *,
    key: str,
    name: str,
    description: str,
    category: str = "订单服务",
    template: str,
    matching_keywords: list[str],
    entries: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    object_config: dict[str, Any],
    decisions: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    handlers: list[dict[str, Any]],
    fallback_order: list[str],
) -> dict[str, Any]:
    return {
        "key": key,
        "status": "draft",
        "published_version": None,
        "config": ScenarioConfig.model_validate(
            {
                "schema_version": "v1",
                "name": name,
                "description": description,
                "domain": "购物消费",
                "category": category,
                "template": template,
                "channels": ["web", "app", "wechat"],
                "entries": entries,
                "facts": facts,
                "object": object_config,
                "decisions": decisions,
                "recommendations": recommendations,
                "handlers": handlers,
                "fallback_order": fallback_order,
                "matching": {
                    "keywords": matching_keywords,
                    "intents": [],
                    "negative_keywords": [],
                },
                "config": {},
            }
        ),
    }


def default_scenarios(
    *,
    agent: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return fresh, contract-valid default scene definitions.

    Agent handlers are omitted unless a published Agent is supplied by the
    seeder. This keeps templates valid in a fresh installation and avoids
    inventing an ``agent_id`` that cannot be opened in Agent management.
    """

    order_entries = [
        _entry("natural-language", "natural_language", "自然语言", "查我的订单"),
        _entry("catalog", "service_catalog", "服务目录", "购物消费 → 我的订单"),
        _entry("order-card", "object_card", "订单卡片", "最近订单 / 订单列表"),
        _entry("order-detail-cta", "external_link", "外部跳转", "订单详情页 CTA"),
    ]
    order_facts = [
        _fact("order_status", "订单状态", "status", order=10),
        _fact("ordered_at", "下单时间", "created_at", order=20),
        _fact("amount", "金额", "amount", order=30, masked=True),
        _fact("product_name", "商品名称", "items.0.title", order=40),
        _fact("logistics_status", "物流状态", "logistics.status", order=50),
    ]
    order_decisions = [
        _decision(
            "select_order",
            "select_object",
            "选择订单",
            options=[],
        ),
        _decision("confirm_object", "confirm_object", "确认当前订单"),
        _decision(
            "choose_intent",
            "select_intent",
            "选择问题",
            required=False,
            allow_free_text=True,
        ),
    ]
    order_recommendations = [
        {
            "key": "logistics_stale",
            "label": "物流为什么没更新？",
            "message": "物流为什么没更新？",
            "when": {"object_statuses": ["运输中", "已发货"], "message_terms": []},
        },
        {
            "key": "refund",
            "label": "如何申请退款？",
            "message": "如何申请退款？",
            "when": {},
        },
        {
            "key": "invoice",
            "label": "开发票",
            "message": "开发票",
            "when": {},
        },
    ]

    query_handlers = (
        [
            _handler(
                "agent-complex",
                "agent",
                "复杂问题与异常解释",
                priority=10,
                when={"message_terms": ["为什么", "异常", "复杂", "投诉", "没更新"]},
                agent_id=agent["id"] if agent else None,
                agent_version=agent["version"] if agent else None,
                agent_name=agent["name"] if agent else None,
                config={"instruction": "围绕当前订单解释异常，不重新猜测订单对象。"},
            )
        ]
        if agent
        else []
    )
    query_handlers.extend(
        [
            _handler(
                "order-status-query",
                "query",
                "查询订单状态",
                priority=20,
                when={"requires_object": True},
                tool="order_status",
            ),
            _handler(
                "human-order-queue",
                "human",
                "订单专属人工队列",
                priority=30,
                when={"message_terms": ["转人工", "人工客服"]},
                queue="order-support",
            ),
        ]
    )
    query_orders = _base(
        key="query-orders",
        name="查询我的订单",
        description="找到并确认一笔订单，查看状态并继续咨询",
        template="query",
        matching_keywords=["我的订单", "查订单", "订单状态", "这笔订单", "物流"],
        entries=order_entries,
        facts=order_facts,
        object_config=_order_object(),
        decisions=order_decisions,
        recommendations=order_recommendations,
        handlers=query_handlers,
        fallback_order=[handler["key"] for handler in query_handlers],
    )
    query_orders["status"] = "published"
    query_orders["published_version"] = 3

    order_rules = _base(
        key="order-rules",
        name="咨询订单规则",
        description="回答发票、取消、退款时效等通用规则问题",
        category="规则与知识",
        template="consult",
        matching_keywords=["规则", "退款时效", "取消订单", "能不能退", "多久到账"],
        entries=[
            _entry("natural-language", "natural_language", "自然语言", "订单规则咨询"),
            _entry("catalog", "service_catalog", "服务目录", "购物消费 → 订单规则"),
        ],
        facts=[],
        object_config=_no_object(),
        decisions=[
            _decision(
                "choose_rule",
                "select_intent",
                "选择规则问题",
                required=False,
                allow_free_text=True,
            )
        ],
        recommendations=[
            {
                "key": "cancel-rule",
                "label": "取消订单规则",
                "message": "取消订单规则",
                "when": {},
            },
            {
                "key": "refund-time",
                "label": "退款多久到账",
                "message": "退款多久到账",
                "when": {},
            },
        ],
        handlers=[
            _handler(
                "knowledge-order-rules",
                "knowledge",
                "订单规则知识库",
                priority=10,
                config={"knowledge_base": "shopping-rules"},
            ),
            _handler(
                "human-rule-queue",
                "human",
                "规则咨询人工队列",
                priority=20,
                when={"message_terms": ["转人工", "人工客服"]},
                queue="rule-support",
            ),
        ],
        fallback_order=["knowledge-order-rules", "human-rule-queue"],
    )
    order_rules["status"] = "published"
    order_rules["published_version"] = 2

    logistics = _base(
        key="track-logistics",
        name="查询物流",
        description="基于订单查询最新物流节点与异常状态",
        template="query",
        matching_keywords=["物流", "包裹", "快递", "运输", "没更新", "到哪了"],
        entries=[
            _entry("natural-language", "natural_language", "自然语言", "查物流"),
            _entry("order-card", "object_card", "订单卡片", "订单详情物流入口"),
        ],
        facts=order_facts,
        object_config=_order_object(),
        decisions=order_decisions,
        recommendations=[
            {
                "key": "latest-node",
                "label": "最新物流节点",
                "message": "我的包裹到哪了？",
                "when": {},
            },
            {
                "key": "exception",
                "label": "物流异常",
                "message": "物流为什么没更新？",
                "when": {},
            },
        ],
        handlers=[
            _handler(
                "logistics-query",
                "query",
                "物流查询工具",
                priority=10,
                when={"requires_object": True},
                tool="logistics_status",
            ),
            _handler(
                "human-logistics",
                "human",
                "物流人工队列",
                priority=20,
                when={"message_terms": ["转人工", "人工客服"]},
                queue="logistics-support",
            ),
        ],
        fallback_order=["logistics-query", "human-logistics"],
    )
    logistics["status"] = "published"
    logistics["published_version"] = 1

    after_sales = _base(
        key="after-sales",
        name="申请售后",
        description="选择订单、填写原因并提交售后申请",
        category="售后服务",
        template="action",
        matching_keywords=["售后", "退货", "换货", "退款申请", "质量问题"],
        entries=[
            _entry("natural-language", "natural_language", "自然语言", "申请售后"),
            _entry("order-card", "object_card", "订单卡片", "订单详情申请售后"),
        ],
        facts=order_facts,
        object_config=_order_object(),
        decisions=[
            _decision("select_order", "select_object", "选择订单"),
            _decision(
                "confirm_submit",
                "confirm_action",
                "确认提交售后申请",
                confirm=True,
            ),
        ],
        recommendations=[
            {
                "key": "return",
                "label": "我要退货",
                "message": "我要申请退货",
                "when": {},
            },
            {
                "key": "quality",
                "label": "商品有质量问题",
                "message": "商品有质量问题",
                "when": {},
            },
        ],
        handlers=[
            _handler(
                "submit-after-sales",
                "action",
                "提交售后申请",
                priority=10,
                when={"requires_object": True},
                tool="create_after_sales",
                config={"requires_confirmation": True},
            ),
            _handler(
                "human-after-sales",
                "human",
                "售后人工队列",
                priority=20,
                when={"message_terms": ["转人工", "人工客服"]},
                queue="after-sales",
            ),
        ],
        fallback_order=["submit-after-sales", "human-after-sales"],
    )

    invoice = _base(
        key="invoice",
        name="发票与报销",
        description="查询开票状态、下载发票或申请重开",
        category="发票服务",
        template="query",
        matching_keywords=["发票", "报销", "开票", "抬头", "税号"],
        entries=[
            _entry("natural-language", "natural_language", "自然语言", "开发票"),
            _entry("order-card", "object_card", "订单卡片", "订单详情发票入口"),
        ],
        facts=order_facts,
        object_config=_order_object(),
        decisions=order_decisions,
        recommendations=[
            {
                "key": "download",
                "label": "下载发票",
                "message": "我要下载发票",
                "when": {},
            },
            {
                "key": "reissue",
                "label": "申请重开",
                "message": "发票抬头填错了，能重开吗？",
                "when": {},
            },
        ],
        handlers=[
            _handler(
                "invoice-query",
                "query",
                "发票查询",
                priority=10,
                when={"requires_object": True},
                tool="invoice_status",
            ),
            _handler(
                "human-invoice",
                "human",
                "发票人工队列",
                priority=20,
                when={"message_terms": ["转人工", "人工客服"]},
                queue="invoice-support",
            ),
        ],
        fallback_order=["invoice-query", "human-invoice"],
    )
    invoice["status"] = "published"
    invoice["published_version"] = 4

    complaints = _base(
        key="complaints",
        name="投诉与反馈",
        description="收集问题、绑定订单并转入业务客服队列",
        category="投诉反馈",
        template="action",
        matching_keywords=["投诉", "反馈", "差评", "服务态度", "举报"],
        entries=[
            _entry("natural_language", "natural_language", "自然语言", "投诉与反馈"),
        ],
        facts=order_facts,
        object_config=_order_object(),
        decisions=[
            _decision("select_order", "select_object", "选择订单"),
            _decision(
                "confirm_submit",
                "confirm_action",
                "确认提交反馈",
                confirm=True,
            ),
        ],
        recommendations=[
            {
                "key": "service",
                "label": "服务态度问题",
                "message": "我要投诉服务态度",
                "when": {},
            }
        ],
        handlers=[
            _handler(
                "complaint-handoff",
                "human",
                "投诉人工队列",
                priority=10,
                queue="complaint-support",
            ),
            _handler(
                "complaint-tracking",
                "tracking",
                "投诉进度跟踪",
                priority=20,
                config={"tracking_type": "complaint"},
            ),
        ],
        fallback_order=["complaint-handoff", "complaint-tracking"],
    )
    complaints["status"] = "review"

    scenarios = [
        query_orders,
        order_rules,
        logistics,
        after_sales,
        invoice,
        complaints,
    ]
    return deepcopy(scenarios)


__all__ = ["default_scenarios"]
