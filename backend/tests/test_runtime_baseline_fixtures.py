import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_platform.business_capabilities.agent_config.service import AgentConfig

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "agent_execution_baseline"
MANIFEST = json.loads((FIXTURE_ROOT / "manifest.v1.json").read_text(encoding="utf-8"))


def fixture_cases(entry):
    payload = json.loads((FIXTURE_ROOT / entry["file"]).read_text(encoding="utf-8"))
    if entry["payload_kind"] == "agent_config":
        return [(entry["file"], payload, entry["expected_result"])]
    return [(case["id"], case["config"], case) for case in payload["cases"]]


def normalized_locations(errors):
    return sorted(
        (list(error["loc"]) for error in errors),
        key=lambda location: json.dumps(location),
    )


def test_fixture_manifest_covers_exact_files_and_all_valid_configs():
    documented = {entry["file"] for entry in MANIFEST["files"]} | {"manifest.v1.json"}
    actual = {path.name for path in FIXTURE_ROOT.iterdir() if path.is_file()}
    assert actual == documented

    valid_count = 0
    for entry in MANIFEST["files"]:
        if entry["expected_result"]["status"] != "valid":
            continue
        for _, payload, _ in fixture_cases(entry):
            config = AgentConfig.model_validate(payload)
            valid_count += 1
            if "required_publish_keys" in entry:
                assert set(entry["required_publish_keys"]) <= payload.keys()
                assert "tool_names" in payload
            if entry["file"] == "minimal-defaults.v1.json":
                dumped = config.model_dump(mode="json")
                for key, value in entry["expected_result"]["defaults"].items():
                    assert dumped[key] == value

    assert valid_count == 5


def test_invalid_fixtures_declare_exact_pydantic_error_locations():
    invalid_count = 0
    for entry in MANIFEST["files"]:
        if not entry["expected_result"]["status"].startswith("invalid"):
            continue
        for case_id, payload, metadata in fixture_cases(entry):
            declared = metadata.get("expected_error_locations")
            assert declared is not None, f"{case_id} must declare exact error locations"
            assert "expected_error_fields" not in metadata
            with pytest.raises(ValidationError) as caught:
                AgentConfig.model_validate(payload)
            actual = normalized_locations(caught.value.errors())
            expected = normalized_locations({"loc": location} for location in declared)
            assert actual == expected, case_id
            if case_id == "model-profile-binding-is-incomplete":
                assert declared == [[]]
                assert set(metadata["related_fields"]) == {
                    "model_profile_id",
                    "model_profile_version",
                }
            invalid_count += 1

    assert invalid_count == 16
