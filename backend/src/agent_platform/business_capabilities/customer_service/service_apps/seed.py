"""Immutable service-application examples installed at startup.

The examples are application-v2 templates. They carry no credentials; their
``query``/``action`` skills point at the bundled mock-business demo API (base
URL overridable via ``AGENT_EXAMPLE_MOCK_BASE_URL``), so a fresh install demos
skill orchestration out of the box while copied applications still configure
their own real connections before publishing.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

EXAMPLE_KEY_PREFIX = "example-"
EXAMPLE_TEMPLATE_VERSION = "2026-11-15.1"

#: Base URL of the bundled mock-business demo API. Examples ship wired to it so
#: a fresh install demos skill orchestration out of the box; deployments reach
#: it at ``127.0.0.1:8010`` from the host or ``http://mock-business:8010`` from
#: a containerised backend.
MOCK_BASE_URL_ENV = "AGENT_EXAMPLE_MOCK_BASE_URL"
MOCK_BASE_URL_DEFAULT = "http://127.0.0.1:8010"


def mock_base_url() -> str:
    return os.environ.get(MOCK_BASE_URL_ENV, "").strip() or MOCK_BASE_URL_DEFAULT


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _connection(
    key: str,
    name: str,
    *,
    executor_kind: str = "http",
    endpoint: str | None = None,
    method: str = "GET",
    auth_kind: str = "none",
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "executor_kind": executor_kind,
        "endpoint": endpoint,
        "method": method,
        "public_headers": {},
        "auth_kind": auth_kind,
        "timeout_seconds": timeout_seconds,
        "max_response_bytes": 16000,
        "config": {"template": True},
        "revision": 1,
    }


def _skill(
    key: str,
    name: str,
    skill_type: str,
    *,
    connection_key: str | None,
    description: str,
    parameters: dict[str, Any] | None = None,
    requires_confirmation: bool = False,
    write_operation: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "type": skill_type,
        "description": description,
        "enabled": True,
        "connection_key": connection_key,
        "config": {
            "write_operation": write_operation,
            "parameters": parameters
            or {
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
            "argument_mapping": {},
            "result_mapping": {},
            "result_schema": {
                "type": "object",
                "additionalProperties": True,
            },
            "safety": {
                "requires_confirmation": requires_confirmation,
                "max_amount": None,
                "allowed_roles": [],
                "idempotency": "required" if write_operation else "none",
                "timeout_seconds": 10,
                "on_error": "handoff" if write_operation else "fail",
            },
        },
    }


def _entry(
    key: str,
    label: str,
    kind: str,
    binding: str,
    description: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "binding": binding,
        "description": description,
    }


def _category(
    key: str,
    label: str,
    icon: str,
    tone: str,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "icon": icon,
        "tone": tone,
        "entries": entries,
    }


def _experience(
    *,
    welcome_text: str,
    service_hours: str,
    suggestion_sets: list[list[str]],
    categories: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": "v1",
        "welcome_text": welcome_text,
        "service_hours": service_hours,
        "suggestion_sets": suggestion_sets,
        "categories": categories,
        "components": {
            "quick_menu": True,
            "suggestions": True,
            "order_card": True,
            "form": True,
            "confirmation": True,
            "receipt": True,
            "handoff": True,
        },
    }


def _template(
    *,
    key: str,
    name: str,
    description: str,
    agent: dict[str, Any],
    connections: list[dict[str, Any]],
    skills: list[dict[str, Any]],
    handoff_queue: str,
    experience: dict[str, Any],
) -> dict[str, Any]:
    config = {
        "schema_version": "v2",
        "name": name,
        "description": description,
        "agent": {
            "id": agent["id"],
            "version": agent["version"],
            "name": agent.get("name"),
        },
        "rules": {
            "fallback": "handoff",
            "handoff_queue": handoff_queue,
        },
        "channels": [],
        "experience": experience,
    }
    return {
        "key": key,
        "template_key": key.removeprefix(EXAMPLE_KEY_PREFIX),
        "template_version": EXAMPLE_TEMPLATE_VERSION,
        "digest": _digest({"config": config, "connections": connections, "skills": skills}),
        "config": config,
        "connections": connections,
        "skills": skills,
    }


def example_applications(agent: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the code-owned application examples for a published Agent."""

    base = mock_base_url()
    knowledge_connection = _connection(
        "knowledge",
        "知识库检索",
        executor_kind="internal",
        method="POST",
    )
    # One connection per (URL, method) pair: a tool's URL is the connection
    # endpoint verbatim, so GET lookups and POST submissions cannot share one.
    shopping_order_connection = _connection(
        "orders", "订单查询接口", endpoint=f"{base}/orders", method="GET"
    )
    shopping_refund_connection = _connection(
        "after-sales", "售后受理接口", endpoint=f"{base}/after-sales", method="POST"
    )
    game_role_connection = _connection(
        "accounts", "游戏角色接口", endpoint=f"{base}/game/roles", method="GET"
    )
    game_appeal_connection = _connection(
        "tickets", "处罚申诉接口", endpoint=f"{base}/game/sanctions/appeal", method="POST"
    )
    creator_work_connection = _connection(
        "content", "作品审核接口", endpoint=f"{base}/creator/works", method="GET"
    )
    creator_appeal_connection = _connection(
        "tickets", "版权投诉接口", endpoint=f"{base}/creator/copyright/complaints", method="POST"
    )
    mobility_trip_connection = _connection(
        "trips", "行程查询接口", endpoint=f"{base}/mobility/trips", method="GET"
    )
    mobility_safety_connection = _connection(
        "tickets", "安全事件接口", endpoint=f"{base}/mobility/safety-reports", method="POST"
    )

    game_experience = _experience(
        welcome_text=(
            "您好，我是游戏玩家客服助手。可以帮你查询账号、充值记录、道具问题，或发起封禁申诉。"
        ),
        service_hours="09:00-23:00",
        suggestion_sets=[
            [
                "账号被误封怎么办？",
                "充值未到账如何处理？",
                "道具丢失可以找回吗？",
            ],
            [
                "如何查询账号状态？",
                "封禁申诉多久有结果？",
                "充值记录在哪里查看？",
            ],
            [
                "游戏道具为什么不能交易？",
                "如何修改绑定手机？",
                "怎么联系人工客服？",
            ],
        ],
        categories=[
            _category(
                "game-account",
                "账号服务",
                "account",
                "green",
                [
                    _entry(
                        "game-account-view",
                        "账号状态",
                        "query",
                        "player_lookup",
                        "查询账号等级、登录状态与安全信息",
                    ),
                    _entry(
                        "game-account-recovery",
                        "账号找回",
                        "knowledge",
                        "knowledge_search",
                        "了解账号找回所需材料与流程",
                    ),
                    _entry(
                        "game-account-security",
                        "安全设置",
                        "knowledge",
                        "knowledge_search",
                        "密码、设备和二次验证说明",
                    ),
                    _entry(
                        "game-account-handoff",
                        "账号专员",
                        "handoff",
                        "handoff_queue",
                        "转交账号专员核验处理",
                    ),
                ],
            ),
            _category(
                "game-payment",
                "充值与订单",
                "order",
                "blue",
                [
                    _entry(
                        "game-payment-status",
                        "充值到账",
                        "knowledge",
                        "knowledge_search",
                        "查询充值到账规则和补单条件",
                    ),
                    _entry(
                        "game-payment-history",
                        "充值记录",
                        "knowledge",
                        "knowledge_search",
                        "查看历史充值与订单凭证",
                    ),
                    _entry(
                        "game-payment-refund",
                        "充值退款",
                        "knowledge",
                        "knowledge_search",
                        "了解充值退款适用范围",
                    ),
                ],
            ),
            _category(
                "game-items",
                "道具与活动",
                "member",
                "violet",
                [
                    _entry(
                        "game-item-recover",
                        "道具找回",
                        "knowledge",
                        "knowledge_search",
                        "了解道具异常丢失的找回条件",
                    ),
                    _entry(
                        "game-item-policy",
                        "交易规则",
                        "knowledge",
                        "knowledge_search",
                        "查看道具交易与赠送限制",
                    ),
                    _entry(
                        "game-event-reward",
                        "活动奖励",
                        "knowledge",
                        "knowledge_search",
                        "查询活动奖励发放规则",
                    ),
                ],
            ),
            _category(
                "game-appeal",
                "封禁申诉",
                "support",
                "amber",
                [
                    _entry(
                        "game-ban-appeal",
                        "提交封禁申诉",
                        "action",
                        "appeal_create",
                        "填写申诉材料并提交人工复核",
                    ),
                    _entry(
                        "game-appeal-progress",
                        "申诉进度",
                        "knowledge",
                        "knowledge_search",
                        "了解申诉处理时长与查询方式",
                    ),
                    _entry(
                        "game-appeal-human",
                        "转人工复核",
                        "handoff",
                        "handoff_queue",
                        "进入游戏客服人工队列",
                    ),
                ],
            ),
        ],
    )

    shopping_experience = _experience(
        welcome_text=(
            "您好，我是购物消费客服助手。可以帮你查询订单和物流，办理退款、发票或转接人工客服。"
        ),
        service_hours="09:00-21:00",
        suggestion_sets=[
            [
                "如何查询我的订单？",
                "退款申请多久可以到账？",
                "订单显示签收但没收到怎么办？",
            ],
            [
                "如何修改会员绑定手机号？",
                "如何申请开具电子发票？",
                "优惠券为什么不能使用？",
            ],
            [
                "物流一直没有更新怎么办？",
                "如何取消连续订阅？",
                "怎么联系人工客服？",
            ],
        ],
        categories=[
            _category(
                "membership",
                "会员服务",
                "member",
                "violet",
                [
                    _entry(
                        "membership-order",
                        "会员订单",
                        "query",
                        "order_lookup",
                        "查看会员开通、续费和到期信息",
                    ),
                    _entry(
                        "membership-coupon",
                        "会员优惠券",
                        "knowledge",
                        "knowledge_search",
                        "查询优惠券使用条件与有效期",
                    ),
                    _entry(
                        "membership-renewal",
                        "连续订阅",
                        "knowledge",
                        "knowledge_search",
                        "关闭或恢复连续订阅",
                    ),
                    _entry(
                        "membership-cooperation",
                        "内容合作",
                        "handoff",
                        "handoff_queue",
                        "转交商务合作团队",
                    ),
                ],
            ),
            _category(
                "order",
                "订单服务",
                "order",
                "blue",
                [
                    _entry(
                        "order-query",
                        "查询订单",
                        "query",
                        "order_lookup",
                        "按订单号查询状态和物流进度",
                    ),
                    _entry(
                        "order-refund",
                        "申请退款",
                        "action",
                        "refund_create",
                        "选择订单并提交退款申请",
                    ),
                    _entry(
                        "order-logistics",
                        "物流进度",
                        "query",
                        "order_lookup",
                        "查看订单最新物流节点",
                    ),
                    _entry(
                        "order-invoice",
                        "开具发票",
                        "knowledge",
                        "knowledge_search",
                        "了解电子发票申请条件和流程",
                    ),
                ],
            ),
            _category(
                "account",
                "账号与安全",
                "account",
                "green",
                [
                    _entry(
                        "account-recover",
                        "找回账号",
                        "knowledge",
                        "knowledge_search",
                        "了解账号找回所需材料",
                    ),
                    _entry(
                        "account-security",
                        "安全设置",
                        "knowledge",
                        "knowledge_search",
                        "密码、设备和二次验证说明",
                    ),
                    _entry(
                        "account-delete",
                        "注销账号",
                        "handoff",
                        "handoff_queue",
                        "转交账号专员处理",
                    ),
                ],
            ),
            _category(
                "support",
                "投诉与建议",
                "support",
                "amber",
                [
                    _entry(
                        "support-complaint",
                        "投诉反馈",
                        "knowledge",
                        "knowledge_search",
                        "了解投诉受理范围与材料",
                    ),
                    _entry(
                        "support-rules",
                        "服务规范",
                        "knowledge",
                        "knowledge_search",
                        "查看平台服务与售后规范",
                    ),
                    _entry(
                        "support-human",
                        "联系人工客服",
                        "handoff",
                        "handoff_queue",
                        "进入人工客服队列",
                    ),
                ],
            ),
        ],
    )

    creator_experience = _experience(
        welcome_text=(
            "您好，我是创作者服务助手。可以帮你查询内容审核、版权申诉、创作权益和账号问题。"
        ),
        service_hours="09:00-22:00",
        suggestion_sets=[
            [
                "内容审核为什么没有通过？",
                "版权申诉需要哪些材料？",
                "创作激励什么时候结算？",
            ],
            [
                "如何查询内容审核状态？",
                "作品被误判侵权怎么办？",
                "如何修改创作者认证信息？",
            ],
            [
                "收益结算异常如何处理？",
                "版权投诉如何撤销？",
                "怎么联系创作者运营？",
            ],
        ],
        categories=[
            _category(
                "creator-content",
                "内容发布",
                "order",
                "blue",
                [
                    _entry(
                        "creator-content-status",
                        "审核状态",
                        "query",
                        "content_status",
                        "查询内容审核状态与原因",
                    ),
                    _entry(
                        "creator-content-rules",
                        "内容规范",
                        "knowledge",
                        "knowledge_search",
                        "查看内容发布与社区规范",
                    ),
                    _entry(
                        "creator-content-edit",
                        "修改内容",
                        "knowledge",
                        "knowledge_search",
                        "了解审核中内容的修改限制",
                    ),
                ],
            ),
            _category(
                "creator-copyright",
                "版权申诉",
                "support",
                "amber",
                [
                    _entry(
                        "creator-copyright-appeal",
                        "提交版权申诉",
                        "action",
                        "copyright_appeal",
                        "提交材料并进入人工复核",
                    ),
                    _entry(
                        "creator-copyright-policy",
                        "版权规则",
                        "knowledge",
                        "knowledge_search",
                        "查看版权保护与申诉规则",
                    ),
                    _entry(
                        "creator-copyright-human",
                        "版权专员",
                        "handoff",
                        "handoff_queue",
                        "转交版权团队处理",
                    ),
                ],
            ),
            _category(
                "creator-benefits",
                "创作权益",
                "member",
                "violet",
                [
                    _entry(
                        "creator-benefit-policy",
                        "激励规则",
                        "knowledge",
                        "knowledge_search",
                        "查询创作激励和收益规则",
                    ),
                    _entry(
                        "creator-settlement",
                        "收益结算",
                        "knowledge",
                        "knowledge_search",
                        "了解结算周期和异常处理",
                    ),
                    _entry(
                        "creator-task",
                        "创作任务",
                        "knowledge",
                        "knowledge_search",
                        "查看活动任务与奖励条件",
                    ),
                ],
            ),
            _category(
                "creator-account",
                "创作者账号",
                "account",
                "green",
                [
                    _entry(
                        "creator-account-verify",
                        "创作者认证",
                        "knowledge",
                        "knowledge_search",
                        "了解认证条件与材料",
                    ),
                    _entry(
                        "creator-account-security",
                        "账号安全",
                        "knowledge",
                        "knowledge_search",
                        "查看账号与设备安全设置",
                    ),
                    _entry(
                        "creator-account-human",
                        "创作者运营",
                        "handoff",
                        "handoff_queue",
                        "转交创作者运营团队",
                    ),
                ],
            ),
        ],
    )

    mobility_experience = _experience(
        welcome_text=("您好，我是出行服务助手。可以帮你查询行程和费用，处理取消、发票或安全问题。"),
        service_hours="07:00-24:00",
        suggestion_sets=[
            [
                "如何查询历史行程？",
                "车费与预估价不一致怎么办？",
                "行程中遇到安全问题如何处理？",
            ],
            [
                "如何申请行程发票？",
                "司机取消订单怎么办？",
                "物品遗失在车上如何找回？",
            ],
            [
                "如何投诉司机服务？",
                "行程费用有争议怎么办？",
                "怎么联系出行人工客服？",
            ],
        ],
        categories=[
            _category(
                "mobility-trip",
                "行程服务",
                "order",
                "blue",
                [
                    _entry(
                        "mobility-trip-query",
                        "查询行程",
                        "query",
                        "trip_lookup",
                        "查看行程、司机和路线信息",
                    ),
                    _entry(
                        "mobility-trip-cancel",
                        "取消规则",
                        "knowledge",
                        "knowledge_search",
                        "了解取消订单与取消费规则",
                    ),
                    _entry(
                        "mobility-trip-lost",
                        "物品遗失",
                        "handoff",
                        "handoff_queue",
                        "转交人工协助联系司机",
                    ),
                ],
            ),
            _category(
                "mobility-fare",
                "费用与发票",
                "member",
                "violet",
                [
                    _entry(
                        "mobility-fare-detail",
                        "费用明细",
                        "query",
                        "trip_lookup",
                        "查看车费构成与优惠抵扣",
                    ),
                    _entry(
                        "mobility-fare-invoice",
                        "申请发票",
                        "knowledge",
                        "knowledge_search",
                        "了解出行发票申请流程",
                    ),
                    _entry(
                        "mobility-fare-dispute",
                        "费用申诉",
                        "handoff",
                        "handoff_queue",
                        "转交费用专员核查",
                    ),
                ],
            ),
            _category(
                "mobility-safety",
                "安全中心",
                "account",
                "green",
                [
                    _entry(
                        "mobility-safety-report",
                        "安全事件上报",
                        "action",
                        "safety_report",
                        "登记安全事件并立即转人工",
                    ),
                    _entry(
                        "mobility-safety-emergency",
                        "紧急协助",
                        "handoff",
                        "handoff_queue",
                        "立即进入安全应急队列",
                    ),
                    _entry(
                        "mobility-safety-rules",
                        "安全规则",
                        "knowledge",
                        "knowledge_search",
                        "查看行程安全与应急说明",
                    ),
                ],
            ),
            _category(
                "mobility-service",
                "投诉与建议",
                "support",
                "amber",
                [
                    _entry(
                        "mobility-service-feedback",
                        "服务反馈",
                        "knowledge",
                        "knowledge_search",
                        "了解服务投诉受理范围",
                    ),
                    _entry(
                        "mobility-service-rules",
                        "服务规范",
                        "knowledge",
                        "knowledge_search",
                        "查看平台服务标准",
                    ),
                    _entry(
                        "mobility-service-human",
                        "人工客服",
                        "handoff",
                        "handoff_queue",
                        "进入出行客服人工队列",
                    ),
                ],
            ),
        ],
    )

    return [
        _template(
            key="example-game-player-support",
            name="游戏玩家客服助手",
            description="处理账号、充值、道具与封禁申诉的标准案例。",
            agent=agent,
            handoff_queue="game-support",
            connections=[knowledge_connection, game_role_connection, game_appeal_connection],
            experience=game_experience,
            skills=[
                _skill(
                    "knowledge_search",
                    "客服知识检索",
                    "knowledge",
                    connection_key="knowledge",
                    description="检索公告、活动规则与账号政策。",
                ),
                _skill(
                    "player_lookup",
                    "玩家资料查询",
                    "query",
                    connection_key="accounts",
                    description="按角色 ID 查询游戏账号状态。",
                    parameters={
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "role_id": {
                                "type": "string",
                                "description": "角色 ID，如 ROLE-1001",
                            }
                        },
                        "required": ["role_id"],
                    },
                ),
                _skill(
                    "appeal_create",
                    "创建封禁申诉",
                    "action",
                    connection_key="tickets",
                    description="提交处罚申诉（需要处罚记录号，如 SN20261110001）。",
                    parameters={
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "record_no": {
                                "type": "string",
                                "description": "处罚记录号，如 SN20261110001",
                            },
                            "note": {
                                "type": "string",
                                "description": "申诉说明",
                            },
                        },
                        "required": ["record_no"],
                    },
                    requires_confirmation=True,
                    write_operation=True,
                ),
            ],
        ),
        _template(
            key="example-shopping-support",
            name="购物消费客服助手",
            description="订单、物流、退款和发票问题的标准案例。",
            agent=agent,
            handoff_queue="order-support",
            connections=[knowledge_connection, shopping_order_connection, shopping_refund_connection],
            experience=shopping_experience,
            skills=[
                _skill(
                    "knowledge_search",
                    "客服知识检索",
                    "knowledge",
                    connection_key="knowledge",
                    description="检索退换货规则与配送政策。",
                ),
                _skill(
                    "order_lookup",
                    "订单查询",
                    "query",
                    connection_key="orders",
                    description="查询订单状态和物流节点。",
                    parameters={
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "order_no": {
                                "type": "string",
                                "description": "订单号，如 PO20261110001",
                            }
                        },
                        "required": ["order_no"],
                    },
                ),
                _skill(
                    "refund_create",
                    "发起退款申请",
                    "action",
                    connection_key="after-sales",
                    description="创建售后/退款申请，执行前必须由人工确认。",
                    parameters={
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "order_no": {
                                "type": "string",
                                "description": "订单号，如 PO20261110001",
                            },
                            "reason": {
                                "type": "string",
                                "description": "售后原因",
                            },
                        },
                        "required": ["order_no"],
                    },
                    requires_confirmation=True,
                    write_operation=True,
                ),
            ],
        ),
        _template(
            key="example-creator-support",
            name="创作者服务助手",
            description="处理内容发布、版权申诉和创作激励咨询的标准案例。",
            agent=agent,
            handoff_queue="creator-support",
            connections=[knowledge_connection, creator_work_connection, creator_appeal_connection],
            experience=creator_experience,
            skills=[
                _skill(
                    "knowledge_search",
                    "创作者规则检索",
                    "knowledge",
                    connection_key="knowledge",
                    description="检索内容规范、版权与激励规则。",
                ),
                _skill(
                    "content_status",
                    "内容审核状态",
                    "query",
                    connection_key="content",
                    description="查询作品审核状态与原因。",
                    parameters={
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "work_id": {
                                "type": "string",
                                "description": "作品 ID，如 WK20261110001",
                            }
                        },
                        "required": ["work_id"],
                    },
                ),
                _skill(
                    "copyright_appeal",
                    "版权申诉",
                    "action",
                    connection_key="tickets",
                    description="提交版权/审核投诉并进入人工复核。",
                    parameters={
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "work_id": {
                                "type": "string",
                                "description": "作品 ID，如 WK20261110001",
                            },
                            "evidence": {
                                "type": "string",
                                "description": "权属证明说明",
                            },
                        },
                        "required": ["work_id"],
                    },
                    requires_confirmation=True,
                    write_operation=True,
                ),
            ],
        ),
        _template(
            key="example-mobility-support",
            name="出行服务助手",
            description="行程、费用和司乘安全问题的标准案例。",
            agent=agent,
            handoff_queue="mobility-support",
            connections=[knowledge_connection, mobility_trip_connection, mobility_safety_connection],
            experience=mobility_experience,
            skills=[
                _skill(
                    "knowledge_search",
                    "出行规则检索",
                    "knowledge",
                    connection_key="knowledge",
                    description="检索计费、取消和安全规则。",
                ),
                _skill(
                    "trip_lookup",
                    "行程查询",
                    "query",
                    connection_key="trips",
                    description="查询行程与费用明细。",
                    parameters={
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "trip_no": {
                                "type": "string",
                                "description": "行程号，如 TR20261110001",
                            }
                        },
                        "required": ["trip_no"],
                    },
                ),
                _skill(
                    "safety_report",
                    "安全事件上报",
                    "action",
                    connection_key="tickets",
                    description="登记行程安全事件并立即转人工。",
                    parameters={
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "trip_no": {
                                "type": "string",
                                "description": "行程号，如 TR20261110001",
                            },
                            "description": {
                                "type": "string",
                                "description": "事件描述",
                            },
                        },
                        "required": ["trip_no", "description"],
                    },
                    requires_confirmation=True,
                    write_operation=True,
                ),
            ],
        ),
    ]


__all__ = [
    "EXAMPLE_KEY_PREFIX",
    "EXAMPLE_TEMPLATE_VERSION",
    "MOCK_BASE_URL_DEFAULT",
    "MOCK_BASE_URL_ENV",
    "example_applications",
    "mock_base_url",
]
