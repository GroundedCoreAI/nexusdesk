"""Safe loading and validation of external capability manifests."""

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError

from agent_platform.extension_contracts import CapabilityManifest
from agent_platform.extension_contracts.base import ContractModel

from .compatibility import PLATFORM_VERSION, validate_constraint, version_satisfies

MANIFEST_MAX_BYTES = 256 * 1024


class ManifestValidationError(ValueError):
    """Raised when an external plugin manifest is invalid or unsafe."""


class ExternalCapabilityManifest(ContractModel):
    """Versioned document envelope used by external capability packages."""

    manifest_version: Literal["1"]
    capability: CapabilityManifest


def _validate_compatibility(
    manifest: CapabilityManifest,
    supported_api_versions: tuple[str, ...],
    platform_version: str,
) -> None:
    if manifest.api_version not in supported_api_versions:
        raise ManifestValidationError(
            f"unsupported capability API version: {manifest.api_version}"
        )
    try:
        version_satisfies(manifest.version, "*")
        validate_constraint(manifest.requires_platform)
        for requirement in manifest.dependency_constraints.values():
            validate_constraint(requirement)
        if not version_satisfies(platform_version, manifest.requires_platform):
            raise ManifestValidationError(
                f"capability requires unsupported platform version: {manifest.id}"
            )
    except ValueError as exc:
        if isinstance(exc, ManifestValidationError):
            raise
        raise ManifestValidationError(f"invalid version metadata: {manifest.id}") from exc


def parse_capability_manifest(
    document: object,
    *,
    supported_api_versions: tuple[str, ...] = ("v1",),
    platform_version: str = PLATFORM_VERSION,
) -> CapabilityManifest:
    """Validate one parsed manifest document without executing plugin code."""

    if not isinstance(document, Mapping):
        raise ManifestValidationError("manifest root must be an object")
    if document.get("manifest_version") != "1":
        raise ManifestValidationError("unsupported manifest version")
    try:
        envelope = ExternalCapabilityManifest.model_validate(document)
    except ValidationError as exc:
        raise ManifestValidationError("invalid capability manifest") from exc
    manifest = envelope.capability
    _validate_compatibility(manifest, supported_api_versions, platform_version)
    return manifest


def load_capability_manifest(
    path: str | Path,
    *,
    supported_api_versions: tuple[str, ...] = ("v1",),
    platform_version: str = PLATFORM_VERSION,
) -> CapabilityManifest:
    """Load and validate YAML or JSON without allowing arbitrary constructors."""

    manifest_path = Path(path)
    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise ManifestValidationError("manifest could not be read") from exc
    if len(raw) > MANIFEST_MAX_BYTES:
        raise ManifestValidationError("manifest is too large")
    try:
        document = yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ManifestValidationError("manifest is not valid UTF-8 YAML/JSON") from exc
    return parse_capability_manifest(
        document,
        supported_api_versions=supported_api_versions,
        platform_version=platform_version,
    )


def dump_capability_manifest(manifest: CapabilityManifest) -> str:
    """Serialize a validated manifest in the canonical external format."""

    return yaml.safe_dump(
        {
            "manifest_version": "1",
            "capability": manifest.model_dump(mode="json"),
        },
        sort_keys=False,
        allow_unicode=True,
    )
