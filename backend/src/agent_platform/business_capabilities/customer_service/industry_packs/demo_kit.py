"""Shared builders for the four demo industry packs.

The four demo packs (shopping / gaming / creator / mobility) deliberately share
one skeleton: three common catalog categories plus one business-specific
category, seven fixed capabilities, four channels and GA-only scenarios.  This
module owns that skeleton so each pack file only declares its own business data.

Nothing here branches on a pack key at runtime; every helper returns the same
generic scenario, object, decision and handler contracts the compiler already
understands.
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

CONFIRM_DECISION_KEY = "confirm-action"

CHANNEL_KEYS = ["web", "app", "wechat", "h5"]

EXECUTION_ORDER = ["deterministic", "action", "agent", "human"]

# The three common catalog categories every demo pack ships; the fourth one is
# pack specific and appended by ``demo_categories``.
COMMON_CATEGORIES = [
    CatalogCategoryTemplate(key="status", name="状态查询", order=10),
    CatalogCategoryTemplate(key="transaction", name="业务办理", order=30),
    CatalogCategoryTemplate(key="policy", name="规则与权益", order=60),
    CatalogCategoryTemplate(key="exception", name="异常与人工", order=70),
]


def _channels(*, app_name: str, wechat_name: str) -> list[ApplicationChannel]:
    return [
        ApplicationChannel(key="web", name="官网帮助中心", type="web", status="active"),
        ApplicationChannel(key="app", name=app_name, type="app", status="active"),
        ApplicationChannel(key="wechat", name=wechat_name, type="wechat", status="active"),
        ApplicationChannel(key="h5", name="H5 服务页", type="h5", status="canary"),
    ]


def _entry(key: str, label: str, description: str = "") -> dict[str, Any]:
    return {
        "key": key,
        "type": "natural_language",
        "label": label,
        "description": description,
        "enabled": True,
        "config": {},
    }


def _fact(
    key: str,
    label: str,
    source: str,
    *,
    order: int,
    masked: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "source": source,
        "format": "text",
        "order": order,
        "masked": masked,
        "audiences": ["customer", "agent", "human"],
        "refresh": "on_open",
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


def object_template(
    *,
    key: str,
    name: str,
    facts: list[dict[str, Any]],
    sensitive_fields: list[str] | None = None,
    filters: list[str] | None = None,
    sample_refs: list[str] | None = None,
    mode: ObjectMode = ObjectMode.REQUIRED,
) -> ObjectTemplate:
    """Build one object template; the provider key follows the object key."""

    return ObjectTemplate(
        object_template_key=key,
        object_type=key,
        name=name,
        provider_key=f"{key}_provider",
        default_mode=mode,
        permission_scope="customer_scope",
        fact_fields=facts,
        sensitive_fields=sensitive_fields or [],
        candidate_strategy={
            "sort": "recent_desc",
            "limit": 5,
            "filters": filters or [],
            "empty_state": "没有找到可处理的业务对象，请重新选择或转人工。",
            "unavailable_state": "业务对象暂时不可用，请稍后重试或转人工。",
        },
        sample_refs=sample_refs or [],
    )


def _human_handler(
    queue: str, label: str, *, priority: int, ai_only: bool = False
) -> dict[str, Any]:
    when = {} if ai_only else {"message_terms": ["转人工", "人工客服"]}
    return _handler(
        "human-support",
        "human",
        label,
        priority=priority,
        queue=queue,
        when=when,
    )


def _scenario(
    *,
    domain: str,
    key: str,
    name: str,
    description: str,
    scenario_kind: ScenarioKind,
    execution_template: str,
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
        maturity=IndustryPackMaturity.GA,
        catalog_category_key=category_key,
        object_template_key=object_template_key,
        channels=list(CHANNEL_KEYS),
        sample_refs=[f"sample-{key}"],
        acceptance_case_refs=[f"case-{key}"],
        config={
            "domain": domain,
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


def query_scenario(
    *,
    domain: str,
    key: str,
    name: str,
    description: str,
    category_key: str,
    object_key: str,
    keywords: list[str],
    tool: str,
    queue: str,
    knowledge_base: str,
    human_label: str,
    recommendations: list[dict[str, Any]] | None = None,
) -> ScenarioTemplate:
    """Read-only scenario: object query, then policy knowledge, then human."""

    return _scenario(
        domain=domain,
        key=key,
        name=name,
        description=description,
        scenario_kind=ScenarioKind.QUERY,
        execution_template="query",
        category_key=category_key,
        object_template_key=object_key,
        keywords=keywords,
        handlers=[
            _handler(
                "object-query",
                "query",
                f"查询{name}",
                priority=10,
                tool=tool,
                when={"requires_object": True},
            ),
            _handler(
                "policy-knowledge",
                "knowledge",
                "业务规则与政策",
                priority=20,
                config={"knowledge_base": knowledge_base},
            ),
            _human_handler(queue, human_label, priority=30),
        ],
        decisions=[_decision("select-object", "select_object", "选择需要查询的记录")],
        recommendations=recommendations,
        policy_profile="read_only_query",
    )


def action_scenario(
    *,
    domain: str,
    key: str,
    name: str,
    description: str,
    category_key: str,
    object_key: str,
    keywords: list[str],
    tool: str,
    queue: str,
    human_label: str,
    confirm_label: str,
    recommendations: list[dict[str, Any]] | None = None,
    knowledge_base: str | None = None,
) -> ScenarioTemplate:
    """Write scenario: submit after an explicit, non-skippable confirmation.

    The action handler comes first so the write path is attempted before any
    knowledge lookup; policy knowledge only fills the gaps while confirming.
    """

    handlers: list[dict[str, Any]] = [
        _handler(
            "submit-action",
            "action",
            "提交办理请求",
            priority=10,
            tool=tool,
            when={"requires_object": True},
            config={"requires_confirmation": True},
        )
    ]
    if knowledge_base is not None:
        handlers.append(
            _handler(
                "policy-knowledge",
                "knowledge",
                "业务规则与政策",
                priority=20,
                config={"knowledge_base": knowledge_base},
            )
        )
    handlers.append(_human_handler(queue, human_label, priority=30))
    return _scenario(
        domain=domain,
        key=key,
        name=name,
        description=description,
        scenario_kind=ScenarioKind.ACTION,
        execution_template="action",
        category_key=category_key,
        object_template_key=object_key,
        keywords=keywords,
        handlers=handlers,
        decisions=[
            _decision("select-object", "select_object", "选择需要办理的记录"),
            _decision("confirm-action", "confirm_action", confirm_label, confirm=True),
        ],
        recommendations=recommendations,
        policy_profile="high_risk_action",
    )


def consult_scenario(
    *,
    domain: str,
    key: str,
    name: str,
    description: str,
    category_key: str,
    keywords: list[str],
    queue: str,
    human_label: str,
    knowledge_base: str | None = None,
    recommendations: list[dict[str, Any]] | None = None,
    human_first: bool = False,
) -> ScenarioTemplate:
    """Advice scenario without a business object.

    ``human_first`` drops every deterministic step so the scenario goes straight
    to a person; the safety scenario of the mobility pack relies on it.
    """

    if human_first:
        handlers = [_human_handler(queue, human_label, priority=10, ai_only=True)]
        profile = "human_first"
    else:
        handlers = [
            _handler(
                "policy-knowledge",
                "knowledge",
                "业务规则与政策",
                priority=10,
                config={"knowledge_base": knowledge_base or f"{domain}-policy"},
            ),
            _human_handler(queue, human_label, priority=20),
        ]
        profile = "knowledge_first"
    return _scenario(
        domain=domain,
        key=key,
        name=name,
        description=description,
        scenario_kind=ScenarioKind.DIAGNOSIS,
        execution_template="consult",
        category_key=category_key,
        object_template_key=None,
        keywords=keywords,
        handlers=handlers,
        recommendations=recommendations,
        policy_profile=profile,
    )


def sample_specs_to_samples(
    specs: list[tuple[str, str, str | None]],
    object_samples: dict[str, dict[str, Any]],
    *,
    confirmed: set[str] | None = None,
) -> list[PackSample]:
    """Build samples; ``confirmed`` lists action scenarios that pre-confirm."""

    confirmed_keys = confirmed or set()
    samples: list[PackSample] = []
    for scenario_key, message, object_template_key in specs:
        simulated_object: SimulatedObject | None = None
        if object_template_key is not None:
            raw = deepcopy(object_samples[object_template_key])
            simulated_object = SimulatedObject(
                id=f"SIM-{scenario_key.upper()}",
                type=object_template_key,
                status=raw["status"],
                facts=raw["facts"],
            )
        samples.append(
            PackSample(
                sample_id=f"sample-{scenario_key}",
                scenario_template_key=scenario_key,
                name=f"{scenario_key} 模拟样例",
                message=message,
                object=simulated_object,
                selected_decision=CONFIRM_DECISION_KEY if scenario_key in confirmed_keys else None,
                description="用于客户体验预览和确定性模拟的演示样例。",
            )
        )
    return samples


def acceptance_cases(
    specs: list[tuple[str, str, list[str], list[str]]],
) -> list[AcceptanceCase]:
    """``specs`` entries are (scenario_key, handler_type, must_include, must_not_include).

    A handoff ends the run instead of succeeding, so the expected result status
    follows the handler type.
    """

    return [
        AcceptanceCase(
            case_id=f"case-{scenario_key}",
            scenario_template_key=scenario_key,
            required=True,
            given="使用演示包内与该场景关联的模拟业务对象。",
            when="客户进入场景并执行自然语言模拟。",
            then={
                "result_status": "handoff" if handler_type == "human" else "succeeded",
                "handler_type": handler_type,
                "must_include_facts": must_include,
                "must_not_include": must_not_include,
            },
        )
        for scenario_key, handler_type, must_include, must_not_include in specs
    ]


def demo_capabilities(
    *,
    domain_label: str,
    query_tools: list[str],
    action_tools: list[str],
    queue: str,
) -> list[ApplicationCapability]:
    return [
        ApplicationCapability(
            key="direct",
            type="direct",
            label="Direct",
            priority=10,
            config={"description": "固定回执、服务时间与确定性回复。"},
        ),
        ApplicationCapability(
            key="knowledge",
            type="knowledge",
            label="知识检索",
            priority=20,
            config={"description": f"{domain_label}规则、政策与常见问题。"},
        ),
        ApplicationCapability(
            key="business-query",
            type="query",
            label="业务查询",
            priority=30,
            config={"description": "只读业务对象查询。", "tools": query_tools},
        ),
        ApplicationCapability(
            key="business-action",
            type="action",
            label="业务办理",
            priority=40,
            config={"description": "需要二次确认的业务动作。", "tools": action_tools},
        ),
        ApplicationCapability(
            key="human-support",
            type="human",
            label="人工客服",
            priority=50,
            queue=queue,
            config={"description": "携带场景、对象、事实和轨迹的人工兜底。"},
        ),
        ApplicationCapability(
            key="service-tracking",
            type="tracking",
            label="处理进度跟踪",
            priority=60,
            config={"description": "办理类请求的处理进度查询。"},
        ),
    ]


def demo_blueprint(
    *,
    application_key: str,
    name: str,
    description: str,
    domain_label: str,
    catalog_category_keys: list[str],
    scenario_template_keys: list[str],
    query_tools: list[str],
    action_tools: list[str],
    queue: str,
    app_name: str,
    wechat_name: str,
) -> ApplicationBlueprint:
    return ApplicationBlueprint(
        application_key=application_key,
        name=name,
        description=description,
        catalog_category_keys=catalog_category_keys,
        scenario_template_keys=scenario_template_keys,
        scenario_template_versions={key: TEMPLATE_VERSION for key in scenario_template_keys},
        capabilities=demo_capabilities(
            domain_label=domain_label,
            query_tools=query_tools,
            action_tools=action_tools,
            queue=queue,
        ),
        default_execution_order=list(EXECUTION_ORDER),
        channels=_channels(app_name=app_name, wechat_name=wechat_name),
    )


def demo_manifest(
    *,
    pack_key: str,
    name: str,
    description: str,
    extra_categories: list[CatalogCategoryTemplate],
    object_templates: list[ObjectTemplate],
    scenario_templates: list[ScenarioTemplate],
    sample_data: list[PackSample],
    cases: list[AcceptanceCase],
    blueprint: ApplicationBlueprint,
) -> IndustryPackManifest:
    """Assemble a demo manifest; every category must own at least one scenario."""

    categories = deepcopy(COMMON_CATEGORIES)
    categories.extend(deepcopy(extra_categories))
    categories.sort(key=lambda item: item.order)

    used = {template.catalog_category_key for template in scenario_templates}
    empty = [category.key for category in categories if category.key not in used]
    if empty:
        raise ValueError(f"demo pack {pack_key} has empty categories: {', '.join(empty)}")

    return IndustryPackManifest(
        schema_version="v1",
        pack_key=pack_key,
        name=name,
        description=description,
        pack_version=TEMPLATE_VERSION,
        maturity=IndustryPackMaturity.GA,
        supported_channels=list(CHANNEL_KEYS),
        catalog_categories=categories,
        object_templates=deepcopy(object_templates),
        scenario_templates=deepcopy(scenario_templates),
        sample_data=sample_data,
        acceptance_cases=cases,
        application_blueprint=blueprint,
    )


__all__ = [
    "CHANNEL_KEYS",
    "COMMON_CATEGORIES",
    "EXECUTION_ORDER",
    "TEMPLATE_VERSION",
    "_decision",
    "_fact",
    "acceptance_cases",
    "action_scenario",
    "consult_scenario",
    "demo_blueprint",
    "demo_manifest",
    "object_template",
    "query_scenario",
    "sample_specs_to_samples",
]
