"""Capability-owned contribution registration and attachment."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from agent_platform.extension_contracts import (
    CapabilityManifest,
    EventSubscriber,
    PolicyProvider,
    ToolContribution,
    ToolDefinition,
    UiExtensionManifest,
)

from .registry import CapabilityRegistry, ExtensionRegistryError
from .ui_registry import UiExtensionRegistry

_EVENT_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,149}$")


@dataclass(frozen=True)
class EventSubscription:
    """One event type routed to one capability-owned subscriber."""

    event_type: str
    subscriber: EventSubscriber

    def __post_init__(self) -> None:
        if not _EVENT_TYPE_PATTERN.fullmatch(self.event_type):
            raise ValueError(f"invalid extension event type: {self.event_type}")
        if not callable(getattr(self.subscriber, "handle", None)):
            raise TypeError("event subscriber must define handle")


@dataclass(frozen=True)
class CapabilityContributionBundle:
    """Explicit application-side contributions for one capability."""

    tools: tuple[ToolContribution, ...] = ()
    events: tuple[EventSubscription, ...] = ()
    policies: tuple[PolicyProvider, ...] = ()
    ui: tuple[UiExtensionManifest, ...] = ()


class CapabilityContributionError(ValueError):
    """Raised when a capability contribution violates its manifest contract."""


class CapabilityContributionRegistry:
    """Validate, retain, and attach explicit capability contributions."""

    def __init__(
        self,
        capabilities: CapabilityRegistry,
        ui_extensions: UiExtensionRegistry,
    ) -> None:
        self.capabilities = capabilities
        self.ui_extensions = ui_extensions
        self._tools: dict[str, list[ToolContribution]] = {}
        self._events: dict[str, list[EventSubscription]] = {}
        self._policies: dict[str, list[PolicyProvider]] = {}
        self._ui: dict[str, list[UiExtensionManifest]] = {}
        self._tool_permissions: dict[str, frozenset[str]] = {}
        self._event_bus = None
        self._attached_events: list[tuple[str, EventSubscription]] = []

    def register_bundle(
        self,
        capability_id: str,
        bundle: CapabilityContributionBundle,
    ) -> None:
        """Register all declared contribution types for one capability."""

        for contribution in bundle.tools:
            self.register_tool(capability_id, contribution)
        for subscription in bundle.events:
            self.register_event(capability_id, subscription)
        for provider in bundle.policies:
            self.register_policy(capability_id, provider)
        for manifest in bundle.ui:
            self.register_ui(capability_id, manifest)

    def register_tool(
        self,
        capability_id: str,
        contribution: ToolContribution,
    ) -> None:
        """Register one tool contribution after checking manifest ownership."""

        self._require_kind(capability_id, "tools")
        if not callable(getattr(contribution, "handlers", None)):
            raise CapabilityContributionError("tool contribution must define handlers")
        contributions = self._tools.setdefault(capability_id, [])
        if any(existing is contribution for existing in contributions):
            raise CapabilityContributionError(
                f"tool contribution already registered: {capability_id}"
            )
        contributions.append(contribution)

    def validate_tool_definitions(
        self,
        capability_id: str,
        definitions: Iterable[ToolDefinition],
    ) -> None:
        """Validate ownership and permissions for materialized tool definitions."""

        self._require_kind(capability_id, "tools")
        for definition in definitions:
            if definition.capability != capability_id:
                raise CapabilityContributionError(
                    "tool capability does not match contribution owner: "
                    f"{definition.capability}!={capability_id}"
                )
            try:
                self.capabilities.validate_contribution_permissions(
                    capability_id,
                    definition.required_permissions,
                )
            except ExtensionRegistryError as exc:
                raise CapabilityContributionError(str(exc)) from exc
            self._tool_permissions[capability_id] = (
                self._tool_permissions.get(capability_id, frozenset())
                | definition.required_permissions
            )

    def register_event(
        self,
        capability_id: str,
        subscription: EventSubscription,
    ) -> None:
        """Register one event subscription and attach it when a bus is active."""

        self._require_kind(capability_id, "events")
        existing = self._events.setdefault(capability_id, [])
        if any(
            item.event_type == subscription.event_type and item.subscriber is subscription.subscriber
            for item in existing
        ):
            raise CapabilityContributionError(
                f"event subscription already registered: {capability_id}/{subscription.event_type}"
            )
        existing.append(subscription)
        if self._event_bus is not None and self._is_active(capability_id):
            self._event_bus.subscribe(subscription.event_type, subscription.subscriber)
            self._attached_events.append((capability_id, subscription))

    def register_policy(
        self,
        capability_id: str,
        provider: PolicyProvider,
    ) -> None:
        """Register one policy provider owned by a capability."""

        self._require_kind(capability_id, "policies")
        if not callable(getattr(provider, "evaluate", None)):
            raise CapabilityContributionError("policy provider must define evaluate")
        providers = self._policies.setdefault(capability_id, [])
        if any(existing is provider for existing in providers):
            raise CapabilityContributionError(
                f"policy provider already registered: {capability_id}"
            )
        providers.append(provider)

    def register_ui(
        self,
        capability_id: str,
        manifest: UiExtensionManifest,
    ) -> None:
        """Register a UI manifest with capability and permission checks."""

        self._require_kind(capability_id, "ui")
        self._validate_ui_manifest(capability_id, manifest)
        try:
            self.ui_extensions.register(manifest)
        except (ExtensionRegistryError, ValueError) as exc:
            raise CapabilityContributionError(str(exc)) from exc
        self._ui.setdefault(capability_id, []).append(manifest)

    def validate(self) -> None:
        """Re-check all registered contributions against their capability contracts.

        Registration performs the same checks eagerly.  This explicit gate is
        useful at the composition boundary and for startup diagnostics: a
        capability cannot become active with a stale or malformed contribution
        bundle.
        """

        for capability_id, contributions in self._tools.items():
            self._require_kind(capability_id, "tools")
            for contribution in contributions:
                if not callable(getattr(contribution, "handlers", None)):
                    raise CapabilityContributionError(
                        f"tool contribution must define handlers: {capability_id}"
                    )
        for capability_id, subscriptions in self._events.items():
            self._require_kind(capability_id, "events")
            for subscription in subscriptions:
                if not callable(getattr(subscription.subscriber, "handle", None)):
                    raise CapabilityContributionError(
                        f"event subscriber must define handle: {capability_id}"
                    )
        for capability_id, providers in self._policies.items():
            self._require_kind(capability_id, "policies")
            for provider in providers:
                if not callable(getattr(provider, "evaluate", None)):
                    raise CapabilityContributionError(
                        f"policy provider must define evaluate: {capability_id}"
                    )
        for capability_id, manifests in self._ui.items():
            self._require_kind(capability_id, "ui")
            for manifest in manifests:
                self._validate_ui_manifest(capability_id, manifest)
                if self.ui_extensions.get(capability_id) is not manifest:
                    raise CapabilityContributionError(
                        f"UI extension registry is out of sync: {capability_id}"
                    )

    def validate_manifest_change(
        self,
        capability_id: str,
        manifest: CapabilityManifest,
    ) -> None:
        """Ensure an upgrade keeps all already-bound contributions contract-safe."""

        current = self.capabilities.get_manifest(capability_id)
        if current is None:
            raise CapabilityContributionError(f"capability is not registered: {capability_id}")
        if manifest.id != capability_id:
            raise CapabilityContributionError(
                f"capability manifest identity cannot change: {manifest.id}!={capability_id}"
            )
        for kind, mapping in (
            ("tools", self._tools),
            ("events", self._events),
            ("policies", self._policies),
            ("ui", self._ui),
        ):
            if mapping.get(capability_id) and kind not in manifest.contributions:
                raise CapabilityContributionError(
                    f"manifest upgrade removes active {kind} contribution: {capability_id}"
                )
        for ui_manifest in self._ui.get(capability_id, ()):
            required_permissions = frozenset(
                permission
                for item in ui_manifest.navigation
                for permission in item.required_permissions
            ) | frozenset(
                permission
                for route in ui_manifest.routes
                for permission in route.required_permissions
            )
            undeclared = required_permissions - manifest.permissions
            if undeclared:
                raise CapabilityContributionError(
                    "manifest upgrade removes UI permissions: "
                    + ",".join(sorted(undeclared))
                )
        undeclared_tool_permissions = self._tool_permissions.get(capability_id, frozenset()) - (
            manifest.permissions
        )
        if undeclared_tool_permissions:
            raise CapabilityContributionError(
                "manifest upgrade removes tool permissions: "
                + ",".join(sorted(undeclared_tool_permissions))
            )

    def _validate_ui_manifest(
        self,
        capability_id: str,
        manifest: UiExtensionManifest,
    ) -> None:
        if manifest.extension_id != capability_id:
            raise CapabilityContributionError(
                "UI extension identity must match capability: "
                f"{manifest.extension_id}!={capability_id}"
            )
        mismatched_capabilities = [
            item.required_capability
            for item in (*manifest.navigation, *manifest.routes)
            if item.required_capability not in (None, capability_id)
        ]
        if mismatched_capabilities:
            raise CapabilityContributionError(
                "UI contribution required_capability must match owner: "
                f"{mismatched_capabilities[0]}!={capability_id}"
            )
        required_permissions = frozenset(
            permission for item in manifest.navigation for permission in item.required_permissions
        ) | frozenset(
            permission for route in manifest.routes for permission in route.required_permissions
        )
        try:
            self.capabilities.validate_contribution_permissions(
                capability_id,
                required_permissions,
            )
        except ExtensionRegistryError as exc:
            raise CapabilityContributionError(str(exc)) from exc

    def tool_contributions(self, capability_id: str | None = None) -> tuple[ToolContribution, ...]:
        """Return registered tools in stable capability and insertion order."""

        return self._flatten(self._tools, capability_id)

    def event_subscriptions(
        self,
        capability_id: str | None = None,
        *,
        active_only: bool = False,
    ) -> tuple[EventSubscription, ...]:
        """Return registered event subscriptions in stable order."""

        owners = self._owners(self._events, capability_id)
        if active_only:
            owners = tuple(owner for owner in owners if self._is_active(owner))
        return tuple(
            subscription for owner in owners for subscription in self._events[owner]
        )

    def policy_providers(
        self,
        capability_id: str | None = None,
        *,
        active_only: bool = False,
    ) -> tuple[tuple[str, PolicyProvider], ...]:
        """Return policy providers together with their owning capability IDs."""

        items = []
        owners = self._owners(self._policies, capability_id)
        if active_only:
            owners = tuple(owner for owner in owners if self._is_active(owner))
        for owner in owners:
            items.extend((owner, provider) for provider in self._policies[owner])
        return tuple(items)

    def ui_manifests(
        self,
        capability_id: str | None = None,
    ) -> tuple[UiExtensionManifest, ...]:
        """Return registered UI manifests in stable order."""

        return self._flatten(self._ui, capability_id)

    def attach_events(self, event_bus) -> tuple[EventSubscription, ...]:
        """Attach only ready, enabled event contributions exactly once."""

        if self._event_bus is not None and self._event_bus is not event_bus:
            self.detach_events()
        self._event_bus = event_bus
        inactive = [
            (owner, subscription)
            for owner, subscription in self._attached_events
            if not self._is_active(owner)
        ]
        for owner, subscription in inactive:
            event_bus.unsubscribe(subscription.event_type, subscription.subscriber)
            self._attached_events.remove((owner, subscription))
        attached = [subscription for _, subscription in self._attached_events]
        for capability_id, subscription in (
            (owner, item)
            for owner in self._owners(self._events, None)
            for item in self._events[owner]
        ):
            if not self._is_active(capability_id):
                continue
            if subscription in attached:
                continue
            event_bus.subscribe(subscription.event_type, subscription.subscriber)
            self._attached_events.append((capability_id, subscription))
            attached.append(subscription)
        return tuple(subscription for _, subscription in self._attached_events)

    def detach_capability_events(self, capability_id: str) -> None:
        """Detach one capability's subscribers after it is disabled."""

        if self._event_bus is None:
            return
        retained: list[tuple[str, EventSubscription]] = []
        for owner, subscription in self._attached_events:
            if owner == capability_id:
                self._event_bus.unsubscribe(subscription.event_type, subscription.subscriber)
            else:
                retained.append((owner, subscription))
        self._attached_events = retained

    def detach_events(self) -> None:
        """Detach all event contributions without affecting other subscribers."""

        if self._event_bus is None:
            return
        for _, subscription in self._attached_events:
            self._event_bus.unsubscribe(subscription.event_type, subscription.subscriber)
        self._attached_events.clear()
        self._event_bus = None

    def observability(self) -> dict[str, int]:
        """Return contribution counts without exposing implementations."""

        return {
            "tools": sum(len(items) for items in self._tools.values()),
            "events": sum(len(items) for items in self._events.values()),
            "policies": sum(len(items) for items in self._policies.values()),
            "ui": sum(len(items) for items in self._ui.values()),
        }

    def is_registered_capability(self, capability_id: str) -> bool:
        """Return whether a definition belongs to a registered capability."""

        return self.capabilities.get_manifest(capability_id) is not None

    def _is_active(self, capability_id: str) -> bool:
        return self.capabilities.is_enabled(capability_id)

    def _require_kind(self, capability_id: str, kind: str) -> None:
        manifest = self.capabilities.get_manifest(capability_id)
        if manifest is None:
            raise CapabilityContributionError(f"capability is not registered: {capability_id}")
        if kind not in manifest.contributions:
            raise CapabilityContributionError(
                f"capability does not declare {kind} contribution: {capability_id}"
            )

    @staticmethod
    def _owners(mapping: dict[str, list], capability_id: str | None) -> tuple[str, ...]:
        if capability_id is not None:
            return (capability_id,) if capability_id in mapping else ()
        return tuple(sorted(mapping))

    @classmethod
    def _flatten(cls, mapping: dict[str, list], capability_id: str | None):
        return tuple(
            item for owner in cls._owners(mapping, capability_id) for item in mapping[owner]
        )


__all__ = [
    "CapabilityContributionBundle",
    "CapabilityContributionError",
    "CapabilityContributionRegistry",
    "EventSubscription",
]
