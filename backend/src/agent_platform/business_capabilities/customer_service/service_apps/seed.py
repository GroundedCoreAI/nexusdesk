"""Default service-application composition for the consumer-service demo."""

from __future__ import annotations

from typing import Any

SERVICE_CATEGORY_ORDER = [
    "订单服务",
    "售后服务",
    "发票服务",
    "规则与知识",
    "投诉反馈",
    "通用服务",
]


def _service_categories(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names: list[str] = []
    for row in scenarios:
        name = str(row.get("category") or "").strip()
        if name and name not in names:
            names.append(name)
    rank = {name: index for index, name in enumerate(SERVICE_CATEGORY_ORDER)}
    position = {name: index for index, name in enumerate(names)}
    names.sort(key=lambda name: (rank.get(name, len(rank)), position[name]))
    return [{"name": name, "order": (index + 1) * 10} for index, name in enumerate(names)]


def default_application(
    *,
    scenarios: list[dict[str, Any]],
    agent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    capabilities: list[dict[str, Any]] = [
        {
            "key": "direct",
            "type": "direct",
            "label": "Direct",
            "priority": 10,
            "config": {
                "description": "固定回执、服务时间与不需要外部资源的确定性回复。"
            },
        },
        {
            "key": "knowledge",
            "type": "knowledge",
            "label": "知识检索",
            "priority": 20,
            "config": {"description": "企业知识库、FAQ、规则与政策文档。"},
        },
        {
            "key": "business-query",
            "type": "query",
            "label": "业务查询",
            "priority": 30,
            "config": {
                "description": "订单、物流、发票等只读业务接口。",
                "tools": ["order_status", "logistics_status", "invoice_status"],
            },
        },
        {
            "key": "business-action",
            "type": "action",
            "label": "业务办理",
            "priority": 40,
            "config": {
                "description": "售后申请、投诉、工单等需要确认的业务动作。",
                "tools": ["create_after_sales", "propose_ticket"],
            },
        },
    ]
    if agent is not None:
        capabilities.append(
            {
                "key": "shopping-agent",
                "type": "agent",
                "label": "购物消费助手",
                "priority": 50,
                "agent_id": agent["id"],
                "agent_version": agent.get("version"),
                "agent_name": agent.get("name"),
                "config": {
                    "description": "复杂解释、多步推理和确定性能力失败后的升级处理。"
                },
            }
        )
    capabilities.extend(
        [
            {
                "key": "human-support",
                "type": "human",
                "label": "人工客服",
                "priority": 60,
                "queue": "order-support",
                "config": {"description": "带完整业务上下文的最终人工兜底。"},
            },
            {
                "key": "service-tracking",
                "type": "tracking",
                "label": "处理进度跟踪",
                "priority": 70,
                "config": {"description": "售后、投诉与工单的处理进度查询。"},
            },
        ]
    )
    return {
        "schema_version": "v1",
        "name": "购物消费服务应用",
        "description": "订单、物流、售后与发票服务的统一业务应用",
        "service_categories": _service_categories(scenarios),
        "scenarios": [
            {
                "key": row["scenario_key"],
                "version": row.get("published_version"),
                "enabled": True,
            }
            for row in scenarios
        ],
        "capabilities": capabilities,
        "default_execution_order": [
            "deterministic",
            "action",
            "agent",
            "human",
        ],
        "channels": [
            {
                "key": "web",
                "name": "官网帮助中心",
                "type": "web",
                "status": "active",
            },
            {
                "key": "wecom",
                "name": "企业微信客服",
                "type": "wecom",
                "status": "active",
            },
            {
                "key": "open-api",
                "name": "开放平台 API",
                "type": "api",
                "status": "active",
            },
            {
                "key": "h5",
                "name": "H5 服务页",
                "type": "h5",
                "status": "canary",
            },
        ],
    }


__all__ = ["default_application"]
