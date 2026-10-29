"""Registry for serializable UI contributions from business capabilities."""

from agent_platform.extension_contracts import UiExtensionManifest

from .compatibility import PLATFORM_VERSION, version_satisfies


class UiExtensionRegistryError(ValueError):
    """Raised when a UI contribution cannot be registered."""


class UiExtensionRegistry:
    """Validate and expose UI extension manifests in stable order."""

    def __init__(
        self,
        supported_api_versions: tuple[str, ...] = ("v1",),
        platform_version: str = PLATFORM_VERSION,
    ) -> None:
        if not supported_api_versions:
            raise ValueError("at least one supported API version is required")
        version_satisfies(platform_version, "*")
        self._supported_api_versions = frozenset(supported_api_versions)
        self._platform_version = platform_version
        self._manifests: dict[str, UiExtensionManifest] = {}

    def register(self, manifest: UiExtensionManifest) -> UiExtensionManifest:
        if manifest.api_version not in self._supported_api_versions:
            raise UiExtensionRegistryError(
                f"unsupported UI extension API version: {manifest.api_version}"
            )
        try:
            version_satisfies(manifest.version, "*")
            platform_compatible = version_satisfies(
                self._platform_version,
                manifest.requires_platform,
            )
        except ValueError as exc:
            raise UiExtensionRegistryError(
                f"invalid version metadata for UI extension: {manifest.extension_id}"
            ) from exc
        if not platform_compatible:
            raise UiExtensionRegistryError(
                f"UI extension requires unsupported platform version: {manifest.extension_id}"
            )
        if manifest.extension_id in self._manifests:
            raise UiExtensionRegistryError(
                f"UI extension already registered: {manifest.extension_id}"
            )
        navigation_ids = {
            item.id for registered in self._manifests.values() for item in registered.navigation
        }
        route_ids = {
            route.id for registered in self._manifests.values() for route in registered.routes
        }
        if len({item.id for item in manifest.navigation}) != len(manifest.navigation):
            raise UiExtensionRegistryError("duplicate UI navigation item")
        if len({route.id for route in manifest.routes}) != len(manifest.routes):
            raise UiExtensionRegistryError("duplicate UI route contribution")
        if len({item.path for item in manifest.navigation}) != len(manifest.navigation):
            raise UiExtensionRegistryError("duplicate UI navigation path")
        if len({route.path for route in manifest.routes}) != len(manifest.routes):
            raise UiExtensionRegistryError("duplicate UI route path")
        if navigation_ids.intersection(item.id for item in manifest.navigation):
            raise UiExtensionRegistryError("UI navigation item already registered")
        if route_ids.intersection(route.id for route in manifest.routes):
            raise UiExtensionRegistryError("UI route contribution already registered")
        registered_paths = {
            item.path for registered in self._manifests.values() for item in registered.navigation
        }
        registered_route_paths = {
            route.path for registered in self._manifests.values() for route in registered.routes
        }
        if registered_paths.intersection(item.path for item in manifest.navigation):
            raise UiExtensionRegistryError("UI navigation path already registered")
        if registered_route_paths.intersection(route.path for route in manifest.routes):
            raise UiExtensionRegistryError("UI route path already registered")
        if any(
            item.path not in {route.path for route in manifest.routes}
            for item in manifest.navigation
        ):
            raise UiExtensionRegistryError("UI navigation item must have a matching route")
        self._manifests[manifest.extension_id] = manifest
        return manifest

    def get(self, extension_id: str) -> UiExtensionManifest | None:
        return self._manifests.get(extension_id)

    def list(self) -> tuple[UiExtensionManifest, ...]:
        return tuple(self._manifests[key] for key in sorted(self._manifests))
