"""Business capability and extension lifecycle contracts."""

import re
from datetime import datetime
from typing import Literal, Protocol

from pydantic import Field, model_validator

from .base import ContractModel

ExtensionKind = Literal["tools", "policies", "events", "routes", "ui"]
CapabilityStatus = Literal["registered", "starting", "ready", "degraded", "stopped"]


class CapabilityManifest(ContractModel):
    """Validated metadata used by the future extension registry."""

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    api_version: str = Field(default="v1", pattern=r"^v\d+$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1_000)
    dependencies: tuple[str, ...] = ()
    dependency_constraints: dict[str, str] = Field(default_factory=dict)
    requires_platform: str | None = Field(default=None, min_length=1, max_length=100)
    configuration_schema_version: str | None = Field(default=None, min_length=1, max_length=100)
    permissions: frozenset[str] = Field(default_factory=frozenset)
    contributions: frozenset[ExtensionKind] = frozenset()
    enabled_by_default: bool = True

    @model_validator(mode="after")
    def validate_dependencies(self) -> "CapabilityManifest":
        if self.id in self.dependencies:
            raise ValueError("capability cannot depend on itself")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise ValueError("capability dependencies must be unique")
        invalid_dependencies = sorted(
            dependency
            for dependency in self.dependencies
            if not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", dependency)
        )
        if invalid_dependencies:
            raise ValueError(
                "capability dependencies must use lowercase identifiers: "
                + ",".join(invalid_dependencies)
            )
        unknown_constraints = set(self.dependency_constraints) - set(self.dependencies)
        if unknown_constraints:
            raise ValueError(
                "dependency constraints require matching dependencies: "
                + ",".join(sorted(unknown_constraints))
            )
        invalid_permissions = sorted(
            permission
            for permission in self.permissions
            if not re.fullmatch(r"[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+", permission)
        )
        if invalid_permissions:
            raise ValueError(
                "capability permissions must use dotted lowercase identifiers: "
                + ",".join(invalid_permissions)
            )
        return self


class CapabilityLifecycle(Protocol):
    """Lifecycle hooks called by the Extension Platform."""

    async def start(self) -> None:
        """Initialize capability-owned adapters."""

    async def stop(self) -> None:
        """Release capability-owned resources."""


class CapabilityConfigurable(Protocol):
    """Optional hook for applying the active configuration at runtime."""

    async def configure(self, config: dict[str, object]) -> None:
        """Apply one validated, JSON-serializable configuration snapshot."""


class CapabilityStatusView(ContractModel):
    """Operational status returned by the registry."""

    capability_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    enabled: bool = True
    config_version: int | None = Field(default=None, ge=1)
    status: CapabilityStatus
    reason: str | None = Field(default=None, max_length=200)
    last_started_at: datetime | None = None
    last_stopped_at: datetime | None = None
    last_failure_at: datetime | None = None
    failure_count: int = Field(default=0, ge=0)


class CapabilityConfigVersion(ContractModel):
    """One validated configuration snapshot for a capability."""

    capability_id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    version: int = Field(ge=1)
    schema_version: str = Field(min_length=1, max_length=100)
    config: dict[str, object] = Field(default_factory=dict)
    created_by: str = Field(min_length=1, max_length=200)
    created_at: datetime
    rollback_of: int | None = Field(default=None, ge=1)
