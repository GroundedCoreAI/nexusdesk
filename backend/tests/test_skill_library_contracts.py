import pytest
from pydantic import ValidationError

from agent_platform.business_capabilities.skill_library.models import (
    SkillDefinition,
    canonical_definition,
    definition_digest,
    next_semver,
    validate_parameter_input,
)
from agent_platform.business_capabilities.skill_library.templates import TEMPLATES
from agent_platform.core_platform.platform_services.identity.permissions import (
    ROLE_PERMISSIONS,
)
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings


def definition(**updates):
    payload = {
        "schema_version": "v1",
        "creation_mode": "professional",
        "type": "instruction",
        "trigger": "agent_auto",
        "instructions": "",
        "parameters": [],
        "output": {"format": "text", "schema": None},
        "dependencies": {
            "model_profile_id": None,
            "model_profile_version": None,
            "knowledge_base_ids": [],
            "tool_names": [],
            "handoff_queue": None,
        },
        "runtime": {
            "timeout_seconds": 30,
            "retry_policy": "none",
            "confirmation_required": False,
            "idempotency": "none",
            "error_behavior": "fail",
            "max_amount": None,
        },
        "permission_scope": "workspace",
    }
    payload.update(updates)
    return payload


def test_empty_professional_definition_round_trips_frozen_shape():
    value = SkillDefinition.model_validate(definition())
    encoded = value.model_dump(mode="json", by_alias=True)
    assert encoded == definition()


def test_parameter_defaults_and_schema_are_validated():
    with pytest.raises(ValidationError, match="does not match integer"):
        SkillDefinition.model_validate(
            definition(
                parameters=[
                    {
                        "name": "count",
                        "type": "integer",
                        "required": False,
                        "default": 1.5,
                        "description": "",
                    }
                ]
            )
        )
    with pytest.raises(ValidationError, match="json output requires a schema"):
        SkillDefinition.model_validate(definition(output={"format": "json", "schema": None}))


def test_release_gate_does_not_block_partial_draft_storage_contract():
    value = SkillDefinition.model_validate(definition())
    assert value.creation_mode == "professional"
    with pytest.raises(ValueError, match="require instructions"):
        value.validate_for_release()


def test_parameter_input_schema_requires_declared_fields_and_forbids_extra():
    value = SkillDefinition.model_validate(
        definition(
            instructions="extract",
            dependencies={
                "model_profile_id": "00000000-0000-0000-0000-000000000001",
                "model_profile_version": 1,
            },
            parameters=[
                {
                    "name": "text",
                    "type": "string",
                    "required": True,
                    "default": None,
                    "description": "",
                }
            ],
        )
    )
    with pytest.raises(ValueError, match="text"):
        validate_parameter_input(value, {})
    with pytest.raises(ValueError, match="Additional properties"):
        validate_parameter_input(value, {"text": "ok", "extra": True})


def test_semver_and_digest_are_deterministic():
    value = SkillDefinition.model_validate(definition())
    first = definition_digest(value)
    second = definition_digest(value.model_dump(mode="json", by_alias=True))
    assert first == second
    assert first.startswith("sha256:")
    assert len(first) == 71
    assert canonical_definition(value) == canonical_definition(value)
    assert next_semver(None, "patch") == "1.0.0"
    assert next_semver("1.2.3", "major") == "2.0.0"
    assert next_semver("1.2.3", "minor") == "1.3.0"
    assert next_semver("1.2.3", "patch") == "1.2.4"


def test_templates_are_complete_code_owned_definitions():
    assert len(TEMPLATES) >= 4
    assert len({template.key for template in TEMPLATES}) == len(TEMPLATES)
    for template in TEMPLATES:
        assert template.definition is not None
        assert template.definition.creation_mode == "template"
        encoded = template.definition.model_dump(mode="json", by_alias=True)
        assert encoded["schema_version"] == "v1"
        assert "schema" in encoded["output"]


def test_permission_mapping_and_safe_settings_defaults():
    assert {"skill.read", "skill.manage", "skill.test", "skill.publish"} <= set(
        ROLE_PERMISSIONS["admin"]
    )
    assert {"skill.read", "skill.test"} <= ROLE_PERMISSIONS["operator"]
    assert "skill.read" in ROLE_PERMISSIONS["viewer"]
    assert "skill.manage" not in ROLE_PERMISSIONS["operator"]
    assert "skill.publish" not in ROLE_PERMISSIONS["viewer"]
    settings = Settings(_env_file=None)
    assert settings.skill_ai_generation_enabled is False
    assert settings.skill_live_tool_tests_enabled is False
    assert settings.skill_test_timeout_seconds == 30
