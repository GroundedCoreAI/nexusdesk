"""Mobility industry demo pack.

Business shape: a trip constrained by time and space.  The distinguishing
scenario is ``safety-help``: it drops every deterministic step and goes straight
to a person, which is the only place across the four demo packs where the
fallback chain is deliberately shortened.
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

DOMAIN = "出行服务"
QUEUE = "mobility-support"
KNOWLEDGE_BASE = "mobility-policy"

_OBJECT_TEMPLATES = [
    object_template(
        key="trip_order",
        name="行程单",
        filters=["进行中", "已完成", "已取消"],
        sensitive_fields=["plate_no"],
        sample_refs=["sample-trip-status-query", "sample-lost-item-report"],
        facts=[
            _fact("trip_no", "行程编号", "trip_no", order=10),
            _fact("origin", "上车点", "origin", order=20),
            _fact("destination", "目的地", "destination", order=30),
            _fact("trip_status", "行程状态", "status", order=40),
            _fact("started_at", "出发时间", "started_at", order=50),
            _fact("driver_name", "司机", "driver_name", order=60),
            _fact("plate_no", "车牌号", "plate_no", order=70, masked=True),
        ],
    ),
    object_template(
        key="fare_breakdown",
        name="计价明细",
        filters=["待支付", "已支付", "有争议"],
        sample_refs=["sample-fare-detail-query", "sample-fare-dispute"],
        facts=[
            _fact("fare_trip_no", "行程编号", "trip_no", order=10),
            _fact("base_fare", "起步价", "base_fare", order=20),
            _fact("distance_fare", "里程费", "distance_fare", order=30),
            _fact("extra_fare", "附加费", "extra_fare", order=40),
            _fact("total_amount", "实付金额", "total_amount", order=50),
            _fact("fare_status", "结算状态", "status", order=60),
        ],
    ),
]

_SCENARIO_TEMPLATES: list[ScenarioTemplate] = [
    query_scenario(
        domain=DOMAIN,
        key="trip-status-query",
        name="行程状态查询",
        description="查询行程状态、上下车点和司机信息",
        category_key="status",
        object_key="trip_order",
        tool="mobility.trip.status",
        queue=QUEUE,
        human_label="出行人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["行程状态", "司机到哪了", "我的行程", "车牌号"],
        recommendations=[
            {
                "key": "driver",
                "label": "怎么联系司机？",
                "message": "我要怎么联系司机？",
                "when": {"object_statuses": ["进行中"]},
            }
        ],
    ),
    query_scenario(
        domain=DOMAIN,
        key="fare-detail-query",
        name="费用明细查询",
        description="逐项拆解起步价、里程费、附加费和实付金额",
        category_key="status",
        object_key="fare_breakdown",
        tool="mobility.fare.detail",
        queue=QUEUE,
        human_label="出行人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["费用明细", "为什么这么贵", "计价明细", "账单"],
    ),
    action_scenario(
        domain=DOMAIN,
        key="fare-dispute",
        name="计费争议申诉",
        description="选择计价明细、说明争议并确认提交",
        category_key="transaction",
        object_key="fare_breakdown",
        tool="mobility.fare.dispute",
        queue=QUEUE,
        human_label="出行人工客服",
        confirm_label="确认提交计费争议",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["计费争议", "多收钱", "费用不对", "绕路"],
        recommendations=[
            {
                "key": "rule",
                "label": "先看计价规则",
                "message": "计价规则是怎么算的？",
                "when": {},
            }
        ],
    ),
    action_scenario(
        domain=DOMAIN,
        key="lost-item-report",
        name="物品遗失协查",
        description="提交遗失协查，由人工联系司机确认",
        category_key="transaction",
        object_key="trip_order",
        tool="mobility.lost_item.report",
        queue=QUEUE,
        human_label="出行人工客服",
        confirm_label="确认提交遗失协查",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["东西落车上", "物品遗失", "找回失物", "落东西"],
    ),
    consult_scenario(
        domain=DOMAIN,
        key="fare-rule-guide",
        name="计价规则说明",
        description="解释起步价、里程费、附加费和动态调价的构成",
        category_key="policy",
        queue=QUEUE,
        human_label="出行人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["计价规则", "起步价", "附加费", "动态调价"],
    ),
    consult_scenario(
        domain=DOMAIN,
        key="safety-help",
        name="安全求助",
        description="行程安全相关求助，跳过全部自动化环节直连人工",
        category_key="exception",
        queue=QUEUE,
        human_label="安全应急人工坐席",
        keywords=["安全求助", "行程异常", "司机绕路", "我觉得不安全"],
        human_first=True,
    ),
]

_OBJECT_SAMPLES: dict[str, dict[str, Any]] = {
    "trip_order": {
        "status": "已完成",
        "facts": {
            "trip_no": "TR-20261110-5521",
            "origin": "文三路地铁站 B 口",
            "destination": "西溪湿地北门",
            "status": "已完成",
            "started_at": "2026-11-10 09:12",
            "driver_name": "王师傅",
            "plate_no": "浙A·**821",
        },
    },
    "fare_breakdown": {
        "status": "已支付",
        "facts": {
            "trip_no": "TR-20261110-5521",
            "base_fare": "13.00",
            "distance_fare": "22.40",
            "extra_fare": "5.00",
            "total_amount": "40.40",
            "status": "已支付",
        },
    },
}

_SAMPLE_SPECS = [
    ("trip-status-query", "我这一单行程现在什么状态？", "trip_order"),
    ("fare-detail-query", "这一单的费用是怎么算出来的？", "fare_breakdown"),
    ("fare-dispute", "我觉得这单多收了钱，要申诉。", "fare_breakdown"),
    ("lost-item-report", "我把耳机落在车上了。", "trip_order"),
    ("fare-rule-guide", "计价规则具体是怎样的？", None),
    ("safety-help", "我感觉这趟行程不太安全。", None),
]

_ACCEPTANCE_SPECS = [
    ("trip-status-query", "query", ["trip_no", "trip_status"], ["plate_no"]),
    ("fare-detail-query", "query", ["base_fare", "total_amount"], []),
    ("fare-dispute", "action", ["fare_trip_no"], []),
    ("lost-item-report", "action", ["trip_no"], []),
    ("fare-rule-guide", "knowledge", [], []),
    ("safety-help", "human", [], []),
]


def _blueprint():
    return demo_blueprint(
        application_key="mobility-service",
        name="出行服务",
        description="行程查询、计费争议、物品协查与安全求助的统一服务应用",
        domain_label=DOMAIN,
        catalog_category_keys=["status", "transaction", "policy", "exception"],
        scenario_template_keys=[template.template_key for template in _SCENARIO_TEMPLATES],
        query_tools=["mobility.trip.status", "mobility.fare.detail"],
        action_tools=["mobility.fare.dispute", "mobility.lost_item.report"],
        queue=QUEUE,
        app_name="出行 App",
        wechat_name="出行服务号",
    )


def build_mobility_pack() -> IndustryPackManifest:
    """Build a fresh, validated mobility demo pack manifest."""

    return demo_manifest(
        pack_key="mobility",
        name="出行服务",
        description="行程状态、费用明细、计费争议、遗失协查与安全求助的完整演示包",
        extra_categories=[],
        object_templates=deepcopy(_OBJECT_TEMPLATES),
        scenario_templates=deepcopy(_SCENARIO_TEMPLATES),
        sample_data=sample_specs_to_samples(
            _SAMPLE_SPECS,
            _OBJECT_SAMPLES,
            confirmed={"fare-dispute", "lost-item-report"},
        ),
        cases=acceptance_cases(_ACCEPTANCE_SPECS),
        blueprint=_blueprint(),
    )


MOBILITY_PACK = build_mobility_pack()


__all__ = ["MOBILITY_PACK", "build_mobility_pack"]
