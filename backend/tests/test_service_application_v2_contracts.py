from uuid import uuid4

import pytest
from pydantic import ValidationError

from agent_platform.business_capabilities.customer_service.service_apps.models import (
    ApplicationRules,
    AuthKind,
    ErrorBehavior,
    PageRequest,
    ReleaseAgent,
    ReleaseConnection,
    ReleaseSnapshot,
    ServiceApplicationCreate,
    ServiceApplicationDraft,
    ServiceApplicationModel,
    ServiceExperienceConfig,
)
from agent_platform.business_capabilities.customer_service.service_apps.releases import (
    canonical_digest,
    canonical_json,
    snapshot_digest,
)
from agent_platform.business_capabilities.customer_service.service_apps.runtime import (
    ApplicationRuntimeContext,
    authorized_tool_names,
)
from agent_platform.business_capabilities.customer_service.service_apps.service import (
    ServiceApplicationService,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError


def _create_payload(**overrides):
    payload = {
        "key": "order-assistant",
        "name": "订单助手",
        "description": "",
        "agent_id": uuid4(),
        "agent_version": 1,
    }
    payload.update(overrides)
    return payload


def _release_snapshot(*, digest: str | None = None) -> ReleaseSnapshot:
    zero_digest = "sha256:" + "0" * 64
    return ReleaseSnapshot(
        agent=ReleaseAgent(id=uuid4(), version=1),
        connections=[
            ReleaseConnection(
                key="orders",
                name="订单接口",
                executor_kind="http",
                endpoint="https://orders.example.com/status",
                method="GET",
                auth_kind=AuthKind.BEARER,
                credential_ref=uuid4(),
                revision=1,
                digest=zero_digest,
            )
        ],
        rules=ApplicationRules(fallback="handoff", handoff_queue="order-support"),
        digest=digest or zero_digest,
    )


@pytest.mark.parametrize(
    "legacy_field",
    [
        "scenario",
        "scenario_key",
        "scenarios",
        "capability",
        "capabilities",
        "providers",
        "service_categories",
        "default_execution_order",
    ],
)
def test_v2_application_models_reject_removed_scenario_and_capability_fields(
    legacy_field,
):
    with pytest.raises(ValidationError) as create_error:
        ServiceApplicationCreate.model_validate(_create_payload(**{legacy_field: []}))
    assert create_error.value.errors()[0]["type"] == "extra_forbidden"
    assert create_error.value.errors()[0]["loc"] == (legacy_field,)

    with pytest.raises(ValidationError) as draft_error:
        ServiceApplicationDraft.model_validate({legacy_field: []})
    assert draft_error.value.errors()[0]["type"] == "extra_forbidden"
    assert draft_error.value.errors()[0]["loc"] == (legacy_field,)


@pytest.mark.parametrize(
    ("field", "expected_code"),
    [
        ("agent_id", "service_application_agent_required"),
        ("agent_version", "service_application_agent_version_required"),
    ],
)
def test_service_requires_an_agent_binding(field, expected_code):
    payload = _create_payload()
    payload.pop(field)
    with pytest.raises(DomainError) as caught:
        ServiceApplicationService._normalise_draft(payload)
    assert caught.value.code == expected_code
    assert caught.value.status == 422

    with pytest.raises(ValidationError):
        ServiceApplicationCreate.model_validate(payload)

    payload = _create_payload(agent_version=-1)
    with pytest.raises(ValidationError):
        ServiceApplicationCreate.model_validate(payload)
    with pytest.raises(DomainError) as caught:
        ServiceApplicationService._normalise_draft(payload)
    assert caught.value.code == "service_application_agent_version_invalid"


def test_workbench_page_defaults_to_ten_rows():
    default = PageRequest()
    assert default.page == 1
    assert default.page_size == 10
    assert default.offset == 0

    second = PageRequest(page=2)
    assert second.page_size == 10
    assert second.offset == 10

    with pytest.raises(ValidationError):
        PageRequest(page_size=0)


def test_application_rules_cover_draft_release_and_confirmation_controls():
    rules = ApplicationRules.model_validate(
        {
            "fallback": "handoff",
            "handoff_queue": "customer-service",
            "handoff_message": "正在为你转接人工客服。",
            "require_confirmation": False,
            "preview_write_enabled": True,
            "validate_results": False,
        }
    )
    assert rules.handoff_message == "正在为你转接人工客服。"
    assert rules.require_confirmation is False
    assert rules.preview_write_enabled is True
    assert rules.validate_results is False
    assert set(rules.model_dump(mode="json")) == {
        "fallback",
        "handoff_queue",
        "handoff_message",
        "require_confirmation",
        "preview_write_enabled",
        "validate_results",
    }


def test_application_rules_normalise_legacy_reply_value_and_default_new_fields():
    rules = ApplicationRules.model_validate(
        {
            "fallback": "reply",
            "handoff_queue": "",
        }
    )
    assert rules.fallback == ErrorBehavior.FALLBACK
    assert rules.handoff_message == ""
    assert rules.require_confirmation is True
    assert rules.preview_write_enabled is False
    assert rules.validate_results is True


def test_application_rules_stay_strict_after_contract_expansion():
    with pytest.raises(ValidationError) as caught:
        ApplicationRules.model_validate(
            {
                "fallback": "handoff",
                "handoff_queue": "customer-service",
                "unexpected_rule": True,
            }
        )
    assert caught.value.errors()[0]["type"] == "extra_forbidden"


def test_release_snapshot_accepts_full_legacy_and_current_rules_contract():
    snapshot = _release_snapshot()
    payload = snapshot.model_dump(mode="json")
    payload["rules"] = {
        "fallback": "reply",
        "handoff_queue": "customer-service",
        "handoff_message": "转接人工处理。",
        "require_confirmation": True,
        "preview_write_enabled": False,
        "validate_results": True,
    }
    validated = ReleaseSnapshot.model_validate(payload)
    assert validated.rules.fallback == ErrorBehavior.FALLBACK
    assert validated.rules.handoff_message == "转接人工处理。"


def test_application_experience_validates_catalog_and_defaults():
    experience = ServiceExperienceConfig.model_validate(
        {
            "welcome_text": "您好，这里是购物客服。",
            "service_hours": "09:00-21:00",
            "suggestion_sets": [["如何查询订单？", "退款多久到账？"]],
            "categories": [
                {
                    "key": "orders",
                    "label": "订单服务",
                    "icon": "order",
                    "tone": "blue",
                    "entries": [
                        {
                            "key": "order-query",
                            "label": "查询订单",
                            "kind": "query",
                            "description": "查看订单状态",
                            "binding": "order_lookup",
                        }
                    ],
                }
            ],
        }
    )
    payload = experience.model_dump(mode="json")
    assert payload["schema_version"] == "v1"
    assert payload["components"]["quick_menu"] is True
    assert payload["categories"][0]["entries"][0]["binding"] == "order_lookup"


def test_application_experience_rejects_duplicate_keys_and_blank_suggestions():
    with pytest.raises(ValidationError, match="category key"):
        ServiceExperienceConfig.model_validate(
            {
                "categories": [
                    {
                        "key": "orders",
                        "label": "订单",
                        "icon": "order",
                        "tone": "blue",
                        "entries": [],
                    },
                    {
                        "key": "orders",
                        "label": "重复订单",
                        "icon": "order",
                        "tone": "blue",
                        "entries": [],
                    },
                ],
            }
        )
    with pytest.raises(ValidationError, match="nonblank"):
        ServiceExperienceConfig.model_validate({"suggestion_sets": [[""]]})


def test_release_snapshot_digest_is_canonical_and_secret_free():
    snapshot = _release_snapshot()
    digest = snapshot_digest(snapshot)
    assert digest == snapshot_digest({**snapshot.model_dump(mode="json"), "digest": digest})
    assert digest != snapshot.digest

    payload = snapshot.model_dump(mode="json")
    assert payload["connections"][0]["credential_ref"]
    assert "secret" not in canonical_json(payload).lower()
    assert "token" not in canonical_json(payload).lower()
    assert canonical_digest({"a": 1, "b": 2}) == canonical_digest({"b": 2, "a": 1})


def test_runtime_trace_projects_only_application_provenance():
    agent_id = uuid4()
    context = ApplicationRuntimeContext(
        application_id=uuid4(),
        application_version=3,
        application_key="order-assistant",
        business_id="customer-service",
        workspace_id="default",
        agent_snapshot={
            "id": str(agent_id),
            "version": 4,
            "name": "订单 Agent",
            "config": {"system_prompt": "internal prompt", "tool_names": ["knowledge_search"]},
        },
        skills=(
            {
                "key": "order_lookup",
                "type": "query",
                "connection_key": "orders",
                "config": {"parameters": {"type": "object"}},
            },
        ),
        connections=(
            {
                "key": "orders",
                "executor_kind": "http",
                "endpoint": "https://orders.example.com/status",
                "config": {"header_name": "X-API-Key"},
                "credential_ref": str(uuid4()),
            },
        ),
        builtin_tools=("knowledge_search",),
    )
    trace = context.trace_payload()

    assert trace["application_key"] == "order-assistant"
    assert trace["application_version"] == 3
    assert trace["agent_id"] == str(agent_id)
    assert trace["agent_version"] == 4
    assert trace["connections"] == [{"key": "orders", "executor_kind": "http"}]
    serialized = canonical_json(trace)
    assert "internal prompt" not in serialized
    assert "X-API-Key" not in serialized
    assert "https://orders.example.com/status" not in serialized


def test_same_agent_application_snapshots_authorize_only_their_own_skills():
    agent = {"id": str(uuid4()), "version": 1}
    connection = {
        "key": "mock",
        "executor_kind": "http",
        "endpoint": "https://business.example.com/execute",
    }
    first = {
        "agent": agent,
        "connections": [connection],
        "skills": [
            {
                "key": "order_lookup",
                "type": "query",
                "connection_key": "mock",
            }
        ],
        "builtin_tools": [],
    }
    second = {
        "agent": agent,
        "connections": [connection],
        "skills": [
            {
                "key": "refund_create",
                "type": "action",
                "connection_key": "mock",
            }
        ],
        "builtin_tools": [],
    }

    assert authorized_tool_names(first) == ["order_lookup"]
    assert authorized_tool_names(second) == ["refund_create"]
    assert set(authorized_tool_names(first)).isdisjoint(authorized_tool_names(second))


def test_contract_base_is_strict():
    assert ServiceApplicationModel.model_config["extra"] == "forbid"
