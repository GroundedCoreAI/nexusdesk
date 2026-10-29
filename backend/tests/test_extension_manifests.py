from pathlib import Path

import pytest

from agent_platform.core_platform.extension_platform import (
    CapabilityRegistry,
    ManifestValidationError,
    capability_manifest_template,
    discover_manifest_directory,
    load_capability_manifest,
)
from agent_platform.core_platform.extension_platform.manifest import parse_capability_manifest
from agent_platform.extension_contracts import CapabilityManifest


def test_external_manifest_loader_validates_yaml_and_registry_compatibility(tmp_path: Path):
    path = tmp_path / "manifest.yaml"
    path.write_text(
        """
manifest_version: "1"
capability:
  id: order-approval
  version: 1.2.0
  api_version: v1
  name: Order Approval
  description: Approval workflow for purchase orders.
  dependencies: []
  dependency_constraints: {}
  requires_platform: ">=0.1.0,<1.0.0"
  permissions:
    - approval.read
  contributions:
    - tools
  enabled_by_default: false
""",
        encoding="utf-8",
    )

    manifest = load_capability_manifest(path)

    assert manifest.id == "order-approval"
    registry = CapabilityRegistry()
    status = registry.register_manifest_file(path)
    assert status.capability_id == "order-approval"
    assert status.enabled is False


def test_external_manifest_rejects_unknown_fields_and_invalid_constraints(tmp_path: Path):
    with pytest.raises(ManifestValidationError, match="invalid capability manifest"):
        parse_capability_manifest(
            {
                "manifest_version": "1",
                "capability": {
                    "id": "example-capability",
                    "version": "0.1.0",
                    "name": "Example",
                },
                "entrypoint": "do_not_execute",
            }
        )

    path = tmp_path / "invalid.yaml"
    path.write_text(
        """
manifest_version: "1"
capability:
  id: order-approval
  version: 1.0.0
  name: Order Approval
  dependencies:
    - knowledge
  dependency_constraints:
    knowledge: "not-a-version"
""",
        encoding="utf-8",
    )
    with pytest.raises(ManifestValidationError, match="invalid version metadata"):
        load_capability_manifest(path)


def test_external_manifest_uses_safe_yaml_and_template_is_loadable(tmp_path: Path):
    path = tmp_path / "unsafe.yaml"
    path.write_text(
        '!!python/object/apply:os.system ["echo unsafe"]',
        encoding="utf-8",
    )
    with pytest.raises(ManifestValidationError):
        load_capability_manifest(path)

    template = tmp_path / "template.yaml"
    template.write_text(capability_manifest_template("it-operations"), encoding="utf-8")
    manifest = load_capability_manifest(template)
    assert manifest == CapabilityManifest(
        id="it-operations",
        version="0.1.0",
        name="Example Capability",
        description="Replace this description with the capability boundary.",
        configuration_schema_version="v1",
        contributions=frozenset({"tools", "events"}),
        enabled_by_default=False,
    )


def _write_manifest(
    directory: Path,
    filename: str,
    capability_id: str,
    *,
    dependencies: list[str] | None = None,
    enabled_by_default: bool = True,
) -> Path:
    path = directory / filename
    path.write_text(
        f"""
manifest_version: "1"
capability:
  id: {capability_id}
  version: 1.0.0
  api_version: v1
  name: {capability_id}
  description: External capability.
  dependencies: {dependencies or []}
  dependency_constraints: {{}}
  requires_platform: ">=0.1.0,<1.0.0"
  enabled_by_default: {str(enabled_by_default).lower()}
""",
        encoding="utf-8",
    )
    return path


def test_external_manifest_directory_discovery_is_stable_and_isolates_invalid_files(
    tmp_path: Path,
):
    _write_manifest(tmp_path, "z-valid.yaml", "zeta")
    _write_manifest(tmp_path, "a-invalid.yaml", "Invalid_ID")
    _write_manifest(tmp_path, "b-valid.json", "alpha")
    (tmp_path / "ignored.txt").write_text("not a manifest", encoding="utf-8")

    results = discover_manifest_directory(tmp_path)

    assert [result.path.name for result in results] == [
        "a-invalid.yaml",
        "b-valid.json",
        "z-valid.yaml",
    ]
    assert [result.status for result in results] == [
        "rejected",
        "discovered",
        "discovered",
    ]
    assert results[0].capability_id is None
    assert "invalid capability manifest" in results[0].error


def test_external_manifest_directory_missing_and_empty_paths_are_non_fatal(tmp_path: Path):
    missing = discover_manifest_directory(tmp_path / "missing")
    (tmp_path / "empty").mkdir()
    empty = discover_manifest_directory(tmp_path / "empty")

    assert missing[0].status == "rejected"
    assert missing[0].error == "manifest directory does not exist"
    assert empty == ()
