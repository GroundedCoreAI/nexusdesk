"""Business application registration for the unified platform entrypoint.

The registry is deliberately small: it owns business metadata, route mounting,
and application-owned trusted extension bindings. Runtime construction stays in
``applications.platform_runtime`` so every business shares the same core
runtime in one process.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from fastapi import FastAPI

from agent_platform.core_platform.extension_platform import CapabilityImplementationRegistry

BusinessRouteRegistrar = Callable[[FastAPI, str, str], None]
TrustedExtensionBinder = Callable[[CapabilityImplementationRegistry, object], None]


def _normalize_prefix(value: str) -> str:
    if not value or value == "/":
        return ""
    return "/" + value.strip("/")


@dataclass(frozen=True)
class BusinessApplication:
    """A business slice mounted into one platform process."""

    business_id: str
    name: str
    route_prefix: str
    register_routes: BusinessRouteRegistrar
    trusted_extension_binder: TrustedExtensionBinder | None = None

    def __post_init__(self) -> None:
        if not self.business_id.strip():
            raise ValueError("business_id must not be empty")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        object.__setattr__(self, "route_prefix", _normalize_prefix(self.route_prefix))


class BusinessRegistry:
    """Ordered registry of business applications mounted by one entrypoint."""

    def __init__(self, applications: Iterable[BusinessApplication] = ()) -> None:
        self._applications: dict[str, BusinessApplication] = {}
        for application in applications:
            self.register(application)

    def register(self, application: BusinessApplication) -> None:
        if application.business_id in self._applications:
            raise ValueError(f"business already registered: {application.business_id}")
        self._applications[application.business_id] = application

    def get(self, business_id: str) -> BusinessApplication:
        try:
            return self._applications[business_id]
        except KeyError as exc:
            raise KeyError(f"business not registered: {business_id}") from exc

    def all(self) -> tuple[BusinessApplication, ...]:
        return tuple(self._applications.values())

    def resolve_business_id(self, path: str) -> str | None:
        """Resolve the business owning an API path using the longest prefix."""

        matches = []
        for application in self._applications.values():
            prefix = f"/api/v1{application.route_prefix}"
            if path == prefix or path.startswith(prefix + "/"):
                matches.append((len(prefix), application.business_id))
        return max(matches)[1] if matches else None

    def catalog(self) -> list[dict[str, str]]:
        return [
            {
                "id": application.business_id,
                "name": application.name,
                "route_prefix": application.route_prefix or "/",
            }
            for application in self._applications.values()
        ]

    def bind_extensions(
        self,
        registry: CapabilityImplementationRegistry,
        platform: object,
    ) -> None:
        """Apply reviewed bindings from each registered business."""

        for application in self._applications.values():
            if application.trusted_extension_binder is not None:
                application.trusted_extension_binder(registry, platform)

    def register_routes(self, app: FastAPI) -> None:
        for application in self._applications.values():
            application.register_routes(
                app,
                f"/api/v1{application.route_prefix}",
                f"/openapi/v1{application.route_prefix}",
            )


__all__ = [
    "BusinessApplication",
    "BusinessRegistry",
    "BusinessRouteRegistrar",
    "TrustedExtensionBinder",
]
