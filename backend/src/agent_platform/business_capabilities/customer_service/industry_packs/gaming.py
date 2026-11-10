"""Gaming industry demo pack.

Business shape: virtual assets plus account state.  Compared with the other
three demo packs this one carries two extra catalog categories, ``account`` and
``recharge``, because account state and payment arrival are the two questions
that dominate gaming support.
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
from .models import CatalogCategoryTemplate, IndustryPackManifest, ScenarioTemplate

DOMAIN = "游戏业务"
QUEUE = "gaming-support"
KNOWLEDGE_BASE = "gaming-policy"

_EXTRA_CATEGORIES = [
    CatalogCategoryTemplate(key="account", name="账号与角色", order=5),
    CatalogCategoryTemplate(key="recharge", name="充值与到账", order=20),
]

_OBJECT_TEMPLATES = [
    object_template(
        key="game_role",
        name="游戏角色",
        filters=["正常", "受限", "封禁中"],
        sensitive_fields=["account_id"],
        sample_refs=["sample-role-status-query"],
        facts=[
            _fact("role_name", "角色名", "role_name", order=10),
            _fact("server", "所在区服", "server", order=20),
            _fact("role_level", "角色等级", "role_level", order=30),
            _fact("role_status", "账号状态", "status", order=40),
            _fact("restriction", "限制说明", "restriction", order=50),
            _fact("account_id", "账号标识", "account_id", order=60, masked=True),
        ],
    ),
    object_template(
        key="recharge_order",
        name="充值订单",
        filters=["已到账", "处理中", "未到账"],
        sample_refs=["sample-recharge-arrival-check"],
        facts=[
            _fact("order_no", "充值单号", "order_no", order=10),
            _fact("recharge_amount", "充值金额", "amount", order=20),
            _fact("paid_at", "支付时间", "paid_at", order=30),
            _fact("arrival_status", "到账状态", "status", order=40),
            _fact("pay_channel", "支付渠道", "pay_channel", order=50),
        ],
    ),
    object_template(
        key="sanction_record",
        name="处罚记录",
        filters=["处理中", "已申诉", "已结束"],
        sample_refs=["sample-sanction-status-query", "sample-sanction-appeal"],
        facts=[
            _fact("record_no", "处罚编号", "record_no", order=10),
            _fact("violation", "违规类型", "violation", order=20),
            _fact("penalty", "处罚措施", "penalty", order=30),
            _fact("duration", "处罚时长", "duration", order=40),
            _fact("sanction_status", "处理状态", "status", order=50),
            _fact("appeal_deadline", "申诉截止", "appeal_deadline", order=60),
        ],
    ),
]

_SCENARIO_TEMPLATES: list[ScenarioTemplate] = [
    query_scenario(
        domain=DOMAIN,
        key="role-status-query",
        name="角色状态查询",
        description="查询角色所在区服、等级和账号当前状态",
        category_key="account",
        object_key="game_role",
        tool="gaming.role.status",
        queue=QUEUE,
        human_label="游戏人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["角色状态", "我的角色", "区服", "角色等级"],
    ),
    consult_scenario(
        domain=DOMAIN,
        key="account-security-help",
        name="账号安全求助",
        description="处理账号被盗、异地登录和二次验证异常",
        category_key="account",
        queue=QUEUE,
        human_label="游戏人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["账号被盗", "异地登录", "二次验证", "账号安全"],
    ),
    query_scenario(
        domain=DOMAIN,
        key="sanction-status-query",
        name="处罚记录查询",
        description="查询处罚原因、处罚时长和申诉截止时间",
        category_key="status",
        object_key="sanction_record",
        tool="gaming.sanction.status",
        queue=QUEUE,
        human_label="游戏人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["处罚记录", "为什么被封", "封禁原因", "处罚多久"],
        recommendations=[
            {
                "key": "appeal",
                "label": "我想申诉",
                "message": "我要对这个处罚提出申诉。",
                "when": {},
            }
        ],
    ),
    query_scenario(
        domain=DOMAIN,
        key="recharge-arrival-check",
        name="充值到账核查",
        description="核查充值单的到账状态，并解释渠道处理时长导致的延迟",
        category_key="recharge",
        object_key="recharge_order",
        tool="gaming.recharge.status",
        queue=QUEUE,
        human_label="游戏人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["充值没到账", "充值到账", "付款了没到", "充值延迟"],
        recommendations=[
            {
                "key": "delay",
                "label": "多久能到账？",
                "message": "充值一般多久能到账？",
                "when": {},
            }
        ],
    ),
    action_scenario(
        domain=DOMAIN,
        key="recharge-missing-report",
        name="充值未到账上报",
        description="选择充值单、确认后提报到账异常工单",
        category_key="recharge",
        object_key="recharge_order",
        tool="gaming.recharge.report",
        queue=QUEUE,
        human_label="游戏人工客服",
        confirm_label="确认提交充值异常工单",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["充值不到账上报", "补单", "充值异常工单", "我要投诉充值"],
    ),
    action_scenario(
        domain=DOMAIN,
        key="sanction-appeal",
        name="封禁申诉",
        description="选择处罚记录、填写申诉理由并确认提交",
        category_key="transaction",
        object_key="sanction_record",
        tool="gaming.sanction.appeal",
        queue=QUEUE,
        human_label="游戏人工客服",
        confirm_label="确认提交封禁申诉",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["封禁申诉", "解封", "误封", "申诉处罚"],
        recommendations=[
            {
                "key": "rule",
                "label": "先看处罚规则",
                "message": "游戏的处罚规则是怎样的？",
                "when": {},
            }
        ],
    ),
    consult_scenario(
        domain=DOMAIN,
        key="game-rule-guide",
        name="规则与处罚说明",
        description="解释违规判定标准、处罚梯度和申诉时限",
        category_key="policy",
        queue=QUEUE,
        human_label="游戏人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["游戏规则", "处罚规则", "违规判定", "申诉时限"],
    ),
    consult_scenario(
        domain=DOMAIN,
        key="game-exception-help",
        name="游戏异常求助",
        description="处理道具丢失、卡顿掉线和无法自助判定的异常",
        category_key="exception",
        queue=QUEUE,
        human_label="游戏人工客服",
        keywords=["道具丢失", "卡顿掉线", "游戏异常", "数据异常"],
        human_first=True,
    ),
]

_OBJECT_SAMPLES: dict[str, dict[str, Any]] = {
    "game_role": {
        "status": "受限",
        "facts": {
            "role_name": "夜行者",
            "server": "华东 1 区",
            "role_level": "62",
            "status": "受限",
            "restriction": "交易功能暂时关闭",
            "account_id": "U-**8821",
        },
    },
    "recharge_order": {
        "status": "处理中",
        "facts": {
            "order_no": "RC-20261109-4471",
            "amount": "98.00",
            "paid_at": "2026-11-09 21:12",
            "status": "处理中",
            "pay_channel": "应用商店内购",
        },
    },
    "sanction_record": {
        "status": "处理中",
        "facts": {
            "record_no": "SN-20261107-0092",
            "violation": "使用第三方辅助工具",
            "penalty": "封禁 7 天",
            "duration": "7 天",
            "status": "处理中",
            "appeal_deadline": "2026-11-14",
        },
    },
}

_SAMPLE_SPECS = [
    ("role-status-query", "我的角色现在是什么状态？", "game_role"),
    ("account-security-help", "我的账号好像被盗了，怎么处理？", None),
    ("sanction-status-query", "我的账号为什么被封了？", "sanction_record"),
    ("recharge-arrival-check", "我刚充值的点券还没到账。", "recharge_order"),
    ("recharge-missing-report", "这笔充值一直没到账，我要上报。", "recharge_order"),
    ("game-exception-help", "我的道具不见了。", None),
    ("sanction-appeal", "我觉得这次封禁是误判，要申诉。", "sanction_record"),
    ("game-rule-guide", "游戏的处罚规则是怎样的？", None),
]

_ACCEPTANCE_SPECS = [
    ("role-status-query", "query", ["role_name", "role_status"], ["account_id"]),
    ("account-security-help", "knowledge", [], []),
    ("sanction-status-query", "query", ["violation", "penalty"], []),
    ("recharge-arrival-check", "query", ["order_no", "arrival_status"], []),
    ("recharge-missing-report", "action", ["order_no"], []),
    ("game-exception-help", "human", [], []),
    ("sanction-appeal", "action", ["record_no"], []),
    ("game-rule-guide", "knowledge", [], []),
]


def _blueprint():
    return demo_blueprint(
        application_key="gaming-service",
        name="游戏业务服务",
        description="账号角色、处罚申诉、充值与到账的统一服务应用",
        domain_label=DOMAIN,
        catalog_category_keys=[
            "account",
            "status",
            "recharge",
            "transaction",
            "policy",
            "exception",
        ],
        scenario_template_keys=[template.template_key for template in _SCENARIO_TEMPLATES],
        query_tools=[
            "gaming.role.status",
            "gaming.sanction.status",
            "gaming.recharge.status",
        ],
        action_tools=["gaming.sanction.appeal", "gaming.recharge.report"],
        queue=QUEUE,
        app_name="游戏 App",
        wechat_name="游戏服务号",
    )


def build_gaming_pack() -> IndustryPackManifest:
    """Build a fresh, validated gaming demo pack manifest."""

    return demo_manifest(
        pack_key="gaming",
        name="游戏业务",
        description="账号与角色、充值与到账、处罚申诉和规则说明的完整演示包",
        extra_categories=deepcopy(_EXTRA_CATEGORIES),
        object_templates=deepcopy(_OBJECT_TEMPLATES),
        scenario_templates=deepcopy(_SCENARIO_TEMPLATES),
        sample_data=sample_specs_to_samples(
            _SAMPLE_SPECS,
            _OBJECT_SAMPLES,
            confirmed={"recharge-missing-report", "sanction-appeal"},
        ),
        cases=acceptance_cases(_ACCEPTANCE_SPECS),
        blueprint=_blueprint(),
    )


GAMING_PACK = build_gaming_pack()


__all__ = ["GAMING_PACK", "build_gaming_pack"]
