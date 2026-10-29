"""Safe discovery of capability manifests from an external directory.

Manifest discovery is intentionally separate from plugin implementation loading.
An external document can describe a capability, but it can never name a Python
entry point that this module imports or executes. Applications must provide any
trusted lifecycle implementations explicitly to the registry.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from agent_platform.extension_contracts import CapabilityManifest

from .compatibility import PLATFORM_VERSION
from .manifest import ManifestValidationError, load_capability_manifest

ManifestDiscoveryStatus = Literal["discovered", "registered", "rejected", "conflict"]
MANIFEST_SUFFIXES = frozenset({".json", ".yaml", ".yml"})


@dataclass(frozen=True)
class PluginDiscoveryResult:
    """Outcome for one manifest path discovered from an external directory."""

    path: Path
    capability_id: str | None
    status: ManifestDiscoveryStatus
    error: str | None = None


@dataclass(frozen=True)
class ManifestCandidate:
    """Validated manifest retained for the registry's dependency ordering pass."""

    path: Path
    manifest: CapabilityManifest


def _manifest_paths(directory: str | Path) -> tuple[Path, ...]:
    root = Path(directory)
    if not root.exists() or not root.is_dir():
        return ()
    return tuple(
        sorted(
            (
                path
                for path in root.iterdir()
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and path.suffix.lower() in MANIFEST_SUFFIXES
                )
            ),
            key=lambda path: path.name.casefold(),
        )
    )


def _scan_manifest_directory(
    directory: str | Path,
    *,
    supported_api_versions: tuple[str, ...] = ("v1",),
    platform_version: str = PLATFORM_VERSION,
) -> tuple[tuple[ManifestCandidate, ...], tuple[PluginDiscoveryResult, ...]]:
    """Validate every manifest, retaining valid candidates and isolated errors."""

    root = Path(directory)
    try:
        root_exists = root.exists()
        root_is_directory = root.is_dir()
        paths = _manifest_paths(root)
    except OSError as exc:
        return (), (
            PluginDiscoveryResult(
                path=root,
                capability_id=None,
                status="rejected",
                error=f"manifest directory could not be scanned: {type(exc).__name__}",
            ),
        )
    if not root_exists:
        return (), (
            PluginDiscoveryResult(
                path=root,
                capability_id=None,
                status="rejected",
                error="manifest directory does not exist",
            ),
        )
    if not root_is_directory:
        return (), (
            PluginDiscoveryResult(
                path=root,
                capability_id=None,
                status="rejected",
                error="manifest directory is not a directory",
            ),
        )

    candidates: list[ManifestCandidate] = []
    results: list[PluginDiscoveryResult] = []
    for path in paths:
        try:
            manifest = load_capability_manifest(
                path,
                supported_api_versions=supported_api_versions,
                platform_version=platform_version,
            )
        except ManifestValidationError as exc:
            results.append(
                PluginDiscoveryResult(
                    path=path,
                    capability_id=None,
                    status="rejected",
                    error=str(exc),
                )
            )
            continue
        candidates.append(ManifestCandidate(path=path, manifest=manifest))
        results.append(
            PluginDiscoveryResult(
                path=path,
                capability_id=manifest.id,
                status="discovered",
            )
        )
    return tuple(candidates), tuple(results)


def discover_manifest_directory(
    directory: str | Path,
    *,
    supported_api_versions: tuple[str, ...] = ("v1",),
    platform_version: str = PLATFORM_VERSION,
) -> tuple[PluginDiscoveryResult, ...]:
    """Discover and validate YAML/JSON manifests in stable filename order.

    Missing directories and non-directory paths are returned as rejected
    results instead of raising, so an optional external plugin directory cannot
    prevent independent built-in capabilities from starting.
    """

    _, results = _scan_manifest_directory(
        directory,
        supported_api_versions=supported_api_versions,
        platform_version=platform_version,
    )
    return results


__all__ = [
    "MANIFEST_SUFFIXES",
    "ManifestCandidate",
    "ManifestDiscoveryStatus",
    "PluginDiscoveryResult",
    "discover_manifest_directory",
]
