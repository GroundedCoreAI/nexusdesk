"""P3-UT-01..05/21: strict execution configuration and canonical compatibility."""

import copy
import importlib
from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from agent_platform.business_capabilities.agent_config import service as agent_service

PROFILE_ID = UUID("50000000-0000-4000-8000-000000000005")
REACT_ENGINE = {
    "engine_id": "react",
    "protocol_id": "native",
    "adapter_version": "v1",
}


def _config_module():
    return importlib.import_module("agent_platform.core_platform.agent_execution.contracts.config")


def _normalize(value):
    return _config_module().normalize_execution_config(value)


def _legacy_config():
    return {
        "model_profile_id": PROFILE_ID,
        "model_profile_version": 3,
        "max_model_rounds": 6,
    }


def test_p3_ut_01_missing_engine_defaults_react_without_mutating_input():
    legacy = _legacy_config()
    original = copy.deepcopy(legacy)

    normalized = _normalize(legacy)

    assert normalized.engine.model_dump() == REACT_ENGINE
    assert normalized.react.model_profile_id == PROFILE_ID
    assert normalized.react.model_profile_version == 3
    assert normalized.react.max_model_rounds == 6
    assert normalized.disabled_capabilities == ()
    assert legacy == original
    assert "engine" not in legacy
    assert "react" not in legacy


def test_p3_ut_01_missing_react_fields_use_react_defaults():
    normalized = _normalize({})

    assert normalized.engine.model_dump() == REACT_ENGINE
    assert normalized.react.model_profile_id is None
    assert normalized.react.model_profile_version is None
    assert normalized.react.max_model_rounds == 6


def test_p3_ut_01_model_input_returns_an_equal_but_distinct_canonical_object():
    original = _normalize(_legacy_config())

    normalized = _normalize(original)

    assert normalized == original
    assert normalized is not original
    assert normalized.engine is not original.engine
    assert normalized.react is not original.react


def test_p3_ut_02_equal_legacy_and_react_aliases_produce_one_canonical_value():
    value = {
        "engine": REACT_ENGINE,
        **_legacy_config(),
        "react": {
            "model_profile_id": PROFILE_ID,
            "model_profile_version": 3,
            "max_model_rounds": 6,
        },
    }
    original = copy.deepcopy(value)

    normalized = _normalize(value)

    assert normalized.react.model_dump() == value["react"]
    assert normalized.model_fields_set == {"engine", "react"}
    assert value == original


@pytest.mark.parametrize(
    "field,legacy_value,react_value",
    [
        ("model_profile_id", PROFILE_ID, None),
        ("model_profile_version", 3, 4),
        ("max_model_rounds", 6, 7),
    ],
)
def test_p3_ut_03_conflicting_aliases_name_the_stable_field_path(field, legacy_value, react_value):
    value = {
        **_legacy_config(),
        field: legacy_value,
        "react": {**_legacy_config(), field: react_value},
    }

    with pytest.raises(ValidationError) as caught:
        _normalize(value)

    assert f"react.{field}" in str(caught.value)
    assert field in str(caught.value)


@pytest.mark.parametrize(
    "unserializable", [{1, 2}, b"raw-bytes", datetime(2026, 11, 12, tzinfo=UTC)]
)
@pytest.mark.parametrize("side", ["react", "legacy"])
def test_p3_ut_03_unserializable_alias_pair_fails_closed_as_validation_error(unserializable, side):
    """Process-local callers must not escape the alias comparison with a bare TypeError."""
    if side == "react":
        value = {
            **_legacy_config(),
            "max_model_rounds": 7,
            "react": {**_legacy_config(), "max_model_rounds": unserializable},
        }
    else:
        value = {
            **_legacy_config(),
            "max_model_rounds": unserializable,
            "react": {**_legacy_config(), "max_model_rounds": 7},
        }

    with pytest.raises(ValidationError) as caught:
        _normalize(value)

    assert "max_model_rounds" in str(caught.value)


def test_p3_ut_03_circular_reference_alias_pair_fails_closed_as_validation_error():
    """A self-referencing value raises ValueError (not TypeError) from json.dumps."""
    circular: dict[str, object] = {}
    circular["self"] = circular
    value = {
        **_legacy_config(),
        "max_model_rounds": 7,
        "react": {**_legacy_config(), "max_model_rounds": circular},
    }

    with pytest.raises(ValidationError) as caught:
        _normalize(value)

    assert "max_model_rounds" in str(caught.value)


@pytest.mark.parametrize(
    "value",
    [
        {"engine": "react"},
        {"engine": {**REACT_ENGINE, "adapter_version": "latest"}},
        {"engine": {**REACT_ENGINE, "extra": "denied"}},
        {"react": {"model_profile_id": PROFILE_ID, "free": {"anything": True}}},
        {"react": []},
        {"disabled_capabilities": {"terminal_execution": True}},
        {"effective_capabilities": ["terminal_execution"]},
        {"policy_version": "v1"},
    ],
)
def test_p3_ut_04_free_dict_latest_extra_and_client_policy_fields_fail_closed(value):
    with pytest.raises(ValidationError):
        _normalize(value)


@pytest.mark.parametrize(
    "react",
    [
        {"model_profile_id": PROFILE_ID},
        {"model_profile_version": 1},
        {"max_model_rounds": 0},
        {"max_model_rounds": 31},
        {"max_model_rounds": True},
        {"max_model_rounds": "6"},
    ],
)
def test_p3_ut_05_profile_pairing_and_round_bounds_remain_strict(react):
    with pytest.raises(ValidationError):
        _normalize({"react": react})


def test_p3_ut_05_disabled_capabilities_deduplicate_deterministically():
    normalized = _normalize(
        {
            "disabled_capabilities": [
                "terminal_execution",
                "streaming",
                "terminal_execution",
            ]
        }
    )

    assert normalized.disabled_capabilities == ("terminal_execution", "streaming")


@pytest.mark.parametrize(
    "disabled",
    [
        ["not_a_capability"],
        ["terminal_execution"] * 12,
        [True],
        "terminal_execution",
    ],
)
def test_p3_ut_05_disabled_capabilities_reject_unknown_unbounded_or_wrong_types(disabled):
    with pytest.raises(ValidationError):
        _normalize({"disabled_capabilities": disabled})


def test_p3_ut_04_explicit_non_react_cannot_carry_react_configuration():
    with pytest.raises(ValidationError) as caught:
        _normalize(
            {
                "engine": {
                    "engine_id": "other",
                    "protocol_id": "native",
                    "adapter_version": "v1",
                },
                "react": {"max_model_rounds": 6},
            }
        )

    assert "react" in str(caught.value)


def test_execution_contracts_are_strict_frozen_and_bounded():
    module = _config_module()
    normalized = _normalize(_legacy_config())

    for model in (module.EngineIdentity, module.ReactConfig, module.ExecutionConfig):
        assert model.model_config["strict"] is True
        assert model.model_config["frozen"] is True
        assert model.model_config["extra"] == "forbid"
    with pytest.raises(ValidationError):
        normalized.engine.engine_id = "other"
    with pytest.raises(ValidationError):
        normalized.react.max_model_rounds = 7


def test_agent_config_uses_the_same_normalizer_for_old_and_new_react():
    legacy = agent_service.AgentConfig.model_validate(
        {"system_prompt": "controlled", **_legacy_config()}
    )
    new = agent_service.AgentConfig.model_validate(
        {
            "system_prompt": "controlled",
            "engine": REACT_ENGINE,
            "react": _legacy_config(),
            "disabled_capabilities": ["streaming", "streaming"],
        }
    )

    assert legacy.engine == new.engine
    assert legacy.react.model_dump() == new.react.model_dump()
    assert new.model_profile_id == PROFILE_ID
    assert new.model_profile_version == 3
    assert new.max_model_rounds == 6
    assert new.disabled_capabilities == ("streaming",)


def test_p3_ut_21_canonical_diff_suppresses_only_default_equivalent_noise():
    legacy = {"system_prompt": "controlled", **_legacy_config()}
    canonical = agent_service.AgentConfig.model_validate(legacy).model_dump(mode="json")

    assert agent_service.canonical_config_diff(legacy, canonical) == []

    changed_model = copy.deepcopy(canonical)
    changed_model["react"]["max_model_rounds"] = 7
    changed_model["max_model_rounds"] = 7
    changes = agent_service.canonical_config_diff(legacy, changed_model)
    assert {change["field"] for change in changes} >= {"max_model_rounds"}

    changed_disabled = copy.deepcopy(canonical)
    changed_disabled["disabled_capabilities"] = ["terminal_execution"]
    changes = agent_service.canonical_config_diff(legacy, changed_disabled)
    assert {change["field"] for change in changes} == {"disabled_capabilities"}

    changed_engine = copy.deepcopy(canonical)
    changed_engine["engine"]["engine_id"] = "other"
    changed_engine["react"] = None
    changed_engine["model_profile_id"] = None
    changed_engine["model_profile_version"] = None
    changes = agent_service.canonical_config_diff(legacy, changed_engine)
    assert {change["field"] for change in changes} >= {"engine", "react"}
