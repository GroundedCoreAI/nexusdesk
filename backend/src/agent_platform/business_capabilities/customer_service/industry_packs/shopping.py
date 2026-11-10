"""Shopping industry demo pack.

Business shape: a single-transaction lifecycle (place -> ship -> receive ->
after-sales).  Every catalog category owns at least one scenario, every scenario
is GA, and the app can be published straight after installation.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .demo_kit import (
    _fact,
    acceptance_cases,
    action_scenario,
    consult_scenario,
    demo_blueprint,
    demo_manifest,
    object_template,
    query_scenario,
    sample_specs_to_samples,
)
from .models import IndustryPackManifest, ScenarioTemplate

DOMAIN = "购物消费"
QUEUE = "shopping-support"
KNOWLEDGE_BASE = "shopping-policy"

_OBJECT_TEMPLATES = [
    object_template(
        key="purchase_order",
        name="购买订单",
        filters=["待发货", "运输中", "已完成", "售后中"],
        sensitive_fields=["recipient"],
        sample_refs=["sample-order-status-query", "sample-after-sale-apply"],
        facts=[
            _fact("order_no", "订单号", "order_no", order=10),
            _fact("order_status", "订单状态", "status", order=20),
            _fact("paid_amount", "实付金额", "paid_amount", order=30),
            _fact("placed_at", "下单时间", "placed_at", order=40),
            _fact("recipient", "收货人", "recipient", order=50, masked=True),
        ],
    ),
    object_template(
        key="shipment",
        name="物流运单",
        filters=["已揽收", "运输中", "派送中", "已签收"],
        sensitive_fields=["tracking_no"],
        sample_refs=["sample-shipment-tracking"],
        facts=[
            _fact("tracking_no", "运单号", "tracking_no", order=10, masked=True),
            _fact("carrier", "承运商", "carrier", order=20),
            _fact("shipment_status", "物流状态", "status", order=30),
            _fact("current_node", "当前节点", "current_node", order=40),
            _fact("eta", "预计到达", "eta", order=50),
        ],
    ),
    object_template(
        key="after_sale_ticket",
        name="售后工单",
        filters=["处理中", "待补充", "已完成"],
        sample_refs=["sample-after-sale-progress-query"],
        facts=[
            _fact("ticket_no", "工单号", "ticket_no", order=10),
            _fact("after_sale_status", "处理状态", "status", order=20),
            _fact("reason", "申请原因", "reason", order=30),
            _fact("submitted_at", "提交时间", "submitted_at", order=40),
            _fact("resolution", "处理结果", "resolution", order=50),
        ],
    ),
]

_SCENARIO_TEMPLATES: list[ScenarioTemplate] = [
    query_scenario(
        domain=DOMAIN,
        key="order-status-query",
        name="订单状态查询",
        description="查询订单当前状态、实付金额和下单时间",
        category_key="status",
        object_key="purchase_order",
        tool="shopping.order.status",
        queue=QUEUE,
        human_label="购物人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["订单状态", "订单到哪了", "我的订单", "为什么还没发货"],
        recommendations=[
            {
                "key": "shipping",
                "label": "为什么还没发货？",
                "message": "我的订单为什么还没发货？",
                "when": {"object_statuses": ["待发货"]},
            }
        ],
    ),
    query_scenario(
        domain=DOMAIN,
        key="shipment-tracking",
        name="物流进度跟踪",
        description="查询运单当前节点和预计到达时间",
        category_key="status",
        object_key="shipment",
        tool="shopping.shipment.track",
        queue=QUEUE,
        human_label="购物人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["物流", "运单", "快递到哪", "什么时候送达"],
        recommendations=[
            {
                "key": "delay",
                "label": "物流为什么不动了？",
                "message": "我的物流好几天没有更新了。",
                "when": {},
            }
        ],
    ),
    query_scenario(
        domain=DOMAIN,
        key="after-sale-progress-query",
        name="售后进度查询",
        description="查询售后工单的处理状态、申请原因和当前结果",
        category_key="status",
        object_key="after_sale_ticket",
        tool="shopping.after_sale.status",
        queue=QUEUE,
        human_label="购物人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["售后进度", "退货处理到哪了", "售后工单", "退款什么时候到账"],
        recommendations=[
            {
                "key": "refund-time",
                "label": "退款多久到账？",
                "message": "退款一般多久能到账？",
                "when": {},
            }
        ],
    ),
    action_scenario(
        domain=DOMAIN,
        key="after-sale-apply",
        name="退换货申请",
        description="选择订单、确认后提交退换货申请",
        category_key="transaction",
        object_key="purchase_order",
        tool="shopping.after_sale.create",
        queue=QUEUE,
        human_label="购物人工客服",
        confirm_label="确认提交退换货申请",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["退货", "换货", "退款申请", "售后"],
        recommendations=[
            {
                "key": "policy",
                "label": "先看退换货规则",
                "message": "退换货规则是什么？",
                "when": {},
            }
        ],
    ),
    action_scenario(
        domain=DOMAIN,
        key="invoice-apply",
        name="发票开具申请",
        description="为指定订单申请电子发票并提交开票信息",
        category_key="transaction",
        object_key="purchase_order",
        tool="shopping.invoice.create",
        queue=QUEUE,
        human_label="购物人工客服",
        confirm_label="确认提交开票申请",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["发票", "开票", "电子发票", "发票抬头"],
    ),
    consult_scenario(
        domain=DOMAIN,
        key="return-policy-guide",
        name="退换货规则说明",
        description="解释退换货时限、运费承担和例外商品",
        category_key="policy",
        queue=QUEUE,
        human_label="购物人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["退换货规则", "七天无理由", "运费谁出", "不能退的商品"],
        recommendations=[
            {
                "key": "seven-days",
                "label": "七天无理由怎么算？",
                "message": "七天无理由退换是怎么计算的？",
                "when": {},
            }
        ],
    ),
    consult_scenario(
        domain=DOMAIN,
        key="order-exception-help",
        name="订单异常求助",
        description="处理地址错误、重复下单、支付异常等无法自助解决的订单问题",
        category_key="exception",
        queue=QUEUE,
        human_label="购物人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["订单异常", "地址填错", "重复下单", "支付失败"],
    ),
]

_OBJECT_SAMPLES: dict[str, dict[str, Any]] = {
    "purchase_order": {
        "status": "运输中",
        "facts": {
            "order_no": "SO-20261105-8842",
            "status": "运输中",
            "paid_amount": "299.00",
            "placed_at": "2026-11-05 14:20",
            "recipient": "张**",
        },
    },
    "shipment": {
        "status": "运输中",
        "facts": {
            "tracking_no": "SF1234567890",
            "carrier": "顺丰速运",
            "status": "运输中",
            "current_node": "杭州转运中心",
            "eta": "2026-11-11 前送达",
        },
    },
    "after_sale_ticket": {
        "status": "处理中",
        "facts": {
            "ticket_no": "AS-20261108-0311",
            "status": "处理中",
            "reason": "商品与描述不符",
            "submitted_at": "2026-11-08 09:40",
            "resolution": "等待仓库核验",
        },
    },
}

_SAMPLE_SPECS = [
    ("order-status-query", "我的订单现在到哪一步了？", "purchase_order"),
    ("shipment-tracking", "这个运单什么时候能送到？", "shipment"),
    ("after-sale-progress-query", "我提交的退货申请处理到哪一步了？", "after_sale_ticket"),
    ("after-sale-apply", "我收到的商品和描述不一样，想退货。", "purchase_order"),
    ("invoice-apply", "我需要给这单开一张电子发票。", "purchase_order"),
    ("return-policy-guide", "七天无理由退换是怎么算的？", None),
    ("order-exception-help", "我的收货地址填错了，怎么办？", None),
]

_ACCEPTANCE_SPECS = [
    ("order-status-query", "query", ["order_no", "order_status"], ["recipient"]),
    ("shipment-tracking", "query", ["tracking_no", "current_node"], []),
    ("after-sale-progress-query", "query", ["ticket_no", "after_sale_status"], []),
    ("after-sale-apply", "action", ["order_no"], []),
    ("invoice-apply", "action", ["order_no"], []),
    ("return-policy-guide", "knowledge", [], []),
    ("order-exception-help", "knowledge", [], []),
]


def _blueprint():
    return demo_blueprint(
        application_key="shopping-service",
        name="购物消费服务",
        description="订单、物流、售后与发票的统一服务应用",
        domain_label=DOMAIN,
        catalog_category_keys=["status", "transaction", "policy", "exception"],
        scenario_template_keys=[template.template_key for template in _SCENARIO_TEMPLATES],
        query_tools=["shopping.order.status", "shopping.shipment.track"],
        action_tools=["shopping.after_sale.create", "shopping.invoice.create"],
        queue=QUEUE,
        app_name="购物 App",
        wechat_name="购物服务号",
    )


def build_shopping_pack() -> IndustryPackManifest:
    """Build a fresh, validated shopping demo pack manifest."""

    return demo_manifest(
        pack_key="shopping",
        name="购物消费",
        description="订单状态、物流跟踪、退换货、发票与规则说明的完整演示包",
        extra_categories=[],
        object_templates=deepcopy(_OBJECT_TEMPLATES),
        scenario_templates=deepcopy(_SCENARIO_TEMPLATES),
        sample_data=sample_specs_to_samples(
            _SAMPLE_SPECS,
            _OBJECT_SAMPLES,
            confirmed={"after-sale-apply", "invoice-apply"},
        ),
        cases=acceptance_cases(_ACCEPTANCE_SPECS),
        blueprint=_blueprint(),
    )


SHOPPING_PACK = build_shopping_pack()


__all__ = ["SHOPPING_PACK", "build_shopping_pack"]
