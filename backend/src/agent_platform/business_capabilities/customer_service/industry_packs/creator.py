"""Creator industry demo pack.

Business shape: content from creation to distribution and payout.  The lifecycle
is longer than shopping: a work is created, reviewed, published, possibly
challenged, and eventually paid.  Review records therefore carry an appeal
deadline, which the appeal scenario is expected to surface.
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

DOMAIN = "创作者服务"
QUEUE = "creator-support"
KNOWLEDGE_BASE = "creator-policy"

_OBJECT_TEMPLATES = [
    object_template(
        key="creator_account",
        name="创作者账号",
        filters=["正常", "受限", "认证中"],
        sensitive_fields=["creator_id"],
        sample_refs=["sample-creator-account-status"],
        facts=[
            _fact("creator_name", "创作者名称", "creator_name", order=10),
            _fact("creator_level", "创作者等级", "level", order=20),
            _fact("account_status", "账号状态", "status", order=30),
            _fact("verification", "认证状态", "verification", order=40),
            _fact("creator_id", "创作者标识", "creator_id", order=50, masked=True),
        ],
    ),
    object_template(
        key="content_work",
        name="作品",
        filters=["草稿", "审核中", "已发布", "仅自己可见"],
        sample_refs=["sample-work-review-status", "sample-copyright-complaint"],
        facts=[
            _fact("work_title", "作品标题", "title", order=10),
            _fact("work_type", "作品类型", "work_type", order=20),
            _fact("review_status", "审核状态", "status", order=30),
            _fact("publish_status", "发布状态", "publish_status", order=40),
            _fact("published_at", "发布时间", "published_at", order=50),
        ],
    ),
    object_template(
        key="review_record",
        name="审核记录",
        filters=["审核中", "已驳回", "已恢复"],
        sample_refs=["sample-work-appeal"],
        facts=[
            _fact("record_no", "审核编号", "record_no", order=10),
            _fact("reject_reason", "驳回原因", "reject_reason", order=20),
            _fact("review_status", "审核状态", "status", order=30),
            _fact("reviewed_at", "审核时间", "reviewed_at", order=40),
            _fact("appeal_deadline", "申诉截止", "appeal_deadline", order=50),
        ],
    ),
    object_template(
        key="revenue_statement",
        name="收益结算单",
        filters=["待结算", "结算中", "已结算"],
        sample_refs=["sample-revenue-statement-query"],
        facts=[
            _fact("period", "结算周期", "period", order=10),
            _fact("settle_amount", "结算金额", "amount", order=20),
            _fact("settle_status", "结算状态", "status", order=30),
            _fact("settled_at", "结算时间", "settled_at", order=40),
        ],
    ),
]

_SCENARIO_TEMPLATES: list[ScenarioTemplate] = [
    query_scenario(
        domain=DOMAIN,
        key="creator-account-status",
        name="创作者账号状态",
        description="查询创作者等级、账号状态和认证进度",
        category_key="status",
        object_key="creator_account",
        tool="creator.account.status",
        queue=QUEUE,
        human_label="创作者人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["创作者账号", "认证进度", "创作者等级", "账号受限"],
    ),
    query_scenario(
        domain=DOMAIN,
        key="work-review-status",
        name="作品审核状态",
        description="查询作品的审核进度、驳回原因和发布时间",
        category_key="status",
        object_key="content_work",
        tool="creator.work.status",
        queue=QUEUE,
        human_label="创作者人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["审核状态", "作品审核", "为什么还在审核", "作品不可见"],
        recommendations=[
            {
                "key": "rule",
                "label": "审核标准是什么？",
                "message": "作品审核标准是什么？",
                "when": {},
            }
        ],
    ),
    query_scenario(
        domain=DOMAIN,
        key="revenue-statement-query",
        name="收益结算查询",
        description="按结算周期查询收益金额与结算状态",
        category_key="status",
        object_key="revenue_statement",
        tool="creator.revenue.status",
        queue=QUEUE,
        human_label="创作者人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["收益", "结算", "什么时候打款", "收益明细"],
    ),
    action_scenario(
        domain=DOMAIN,
        key="work-appeal",
        name="作品申诉",
        description="选择审核记录、填写理由并确认提交申诉",
        category_key="transaction",
        object_key="review_record",
        tool="creator.review.appeal",
        queue=QUEUE,
        human_label="创作者人工客服",
        confirm_label="确认提交作品申诉",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["作品申诉", "审核不通过", "误判", "恢复作品"],
        recommendations=[
            {
                "key": "deadline",
                "label": "申诉截止时间",
                "message": "这次申诉的截止时间是什么时候？",
                "when": {},
            }
        ],
    ),
    action_scenario(
        domain=DOMAIN,
        key="copyright-complaint",
        name="侵权投诉",
        description="对侵权作品提交投诉，由人工完成证据核验",
        category_key="transaction",
        object_key="content_work",
        tool="creator.copyright.complaint",
        queue=QUEUE,
        human_label="创作者人工客服",
        confirm_label="确认提交侵权投诉",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["侵权", "抄袭", "版权投诉", "搬运"],
    ),
    consult_scenario(
        domain=DOMAIN,
        key="creator-policy-guide",
        name="创作规范与权益",
        description="解释审核标准、收益分成规则和原创保护政策",
        category_key="policy",
        queue=QUEUE,
        human_label="创作者人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["创作规范", "审核标准", "收益分成", "原创保护"],
    ),
    consult_scenario(
        domain=DOMAIN,
        key="review-exception-help",
        name="审核异常求助",
        description="处理审核结果与作品状态不一致等无法自助判定的问题",
        category_key="exception",
        queue=QUEUE,
        human_label="创作者人工客服",
        knowledge_base=KNOWLEDGE_BASE,
        keywords=["审核异常", "状态不一致", "作品消失", "数据异常"],
    ),
]

_OBJECT_SAMPLES: dict[str, dict[str, Any]] = {
    "creator_account": {
        "status": "正常",
        "facts": {
            "creator_name": "林间观察",
            "level": "Lv.5 资深创作者",
            "status": "正常",
            "verification": "已实名认证",
            "creator_id": "CR-**4417",
        },
    },
    "content_work": {
        "status": "审核中",
        "facts": {
            "title": "城市骑行路线记录",
            "work_type": "图文",
            "status": "审核中",
            "publish_status": "待发布",
            "published_at": "",
        },
    },
    "review_record": {
        "status": "已驳回",
        "facts": {
            "record_no": "RV-20261106-0233",
            "reject_reason": "疑似包含未授权商业推广",
            "status": "已驳回",
            "reviewed_at": "2026-11-06 11:20",
            "appeal_deadline": "2026-11-13",
        },
    },
    "revenue_statement": {
        "status": "结算中",
        "facts": {
            "period": "2026 年 10 月",
            "amount": "1280.50",
            "status": "结算中",
            "settled_at": "预计 2026-11-15",
        },
    },
}

_SAMPLE_SPECS = [
    ("creator-account-status", "我的创作者账号现在是什么状态？", "creator_account"),
    ("work-review-status", "我这条作品为什么还在审核？", "content_work"),
    ("revenue-statement-query", "我 10 月的收益结算了吗？", "revenue_statement"),
    ("work-appeal", "这条作品被误判了，我要申诉。", "review_record"),
    ("copyright-complaint", "有人搬运我的作品，我要投诉。", "content_work"),
    ("creator-policy-guide", "审核标准到底是怎样的？", None),
    ("review-exception-help", "我的作品状态显示不一致。", None),
]

_ACCEPTANCE_SPECS = [
    ("creator-account-status", "query", ["creator_name", "account_status"], ["creator_id"]),
    ("work-review-status", "query", ["work_title", "review_status"], []),
    ("revenue-statement-query", "query", ["period", "settle_amount"], []),
    ("work-appeal", "action", ["record_no"], []),
    ("copyright-complaint", "action", ["work_title"], []),
    ("creator-policy-guide", "knowledge", [], []),
    ("review-exception-help", "knowledge", [], []),
]


def _blueprint():
    return demo_blueprint(
        application_key="creator-service",
        name="创作者服务",
        description="作品审核、收益结算、申诉与版权保护的统一服务应用",
        domain_label=DOMAIN,
        catalog_category_keys=["status", "transaction", "policy", "exception"],
        scenario_template_keys=[template.template_key for template in _SCENARIO_TEMPLATES],
        query_tools=[
            "creator.account.status",
            "creator.work.status",
            "creator.revenue.status",
        ],
        action_tools=["creator.review.appeal", "creator.copyright.complaint"],
        queue=QUEUE,
        app_name="创作 App",
        wechat_name="创作者服务号",
    )


def build_creator_pack() -> IndustryPackManifest:
    """Build a fresh, validated creator demo pack manifest."""

    return demo_manifest(
        pack_key="creator",
        name="创作者服务",
        description="账号状态、作品审核、收益结算、申诉与侵权投诉的完整演示包",
        extra_categories=[],
        object_templates=deepcopy(_OBJECT_TEMPLATES),
        scenario_templates=deepcopy(_SCENARIO_TEMPLATES),
        sample_data=sample_specs_to_samples(
            _SAMPLE_SPECS,
            _OBJECT_SAMPLES,
            confirmed={"work-appeal", "copyright-complaint"},
        ),
        cases=acceptance_cases(_ACCEPTANCE_SPECS),
        blueprint=_blueprint(),
    )


CREATOR_PACK = build_creator_pack()


__all__ = ["CREATOR_PACK", "build_creator_pack"]
