"""Trusted application-side bindings for external capability implementations."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from agent_platform.extension_contracts import CapabilityLifecycle

CapabilityLifecycleFactory = Callable[[], CapabilityLifecycle]
CapabilityContributionFactory = Callable[[object], object]
_CAPABILITY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


class CapabilityBindingError(ValueError):
    """Raised when a trusted capability implementation binding is invalid."""


@dataclass(frozen=True)
class _Binding:
    lifecycle_factory: CapabilityLifecycleFactory
    contribution_factory: CapabilityContributionFactory | None = None


class CapabilityImplementationRegistry:
    """Explicit registry of trusted lifecycle factories.

    Factories are supplied by the application composition root. This registry
    deliberately has no module path or import-string support, so a manifest
    cannot cause arbitrary Python code to be loaded.
    """

    def __init__(self) -> None:
        self._bindings: dict[str, _Binding] = {}

    def register(
        self,
        capability_id: str,
        factory: CapabilityLifecycleFactory,
        contribution_factory: CapabilityContributionFactory | None = None,
    ) -> None:
        """Bind one capability ID to trusted lifecycle and contribution factories."""

        if not _CAPABILITY_ID_PATTERN.fullmatch(capability_id):
            raise CapabilityBindingError(f"invalid capability id: {capability_id}")
        if not callable(factory):
            raise CapabilityBindingError("capability lifecycle factory must be callable")
        if contribution_factory is not None and not callable(contribution_factory):
            raise CapabilityBindingError("capability contribution factory must be callable")
        if capability_id in self._bindings:
            raise CapabilityBindingError(
                f"capability implementation already bound: {capability_id}"
            )
        self._bindings[capability_id] = _Binding(factory, contribution_factory)

    def unregister(self, capability_id: str) -> None:
        """Remove one binding from the application-side registry."""

        self._bindings.pop(capability_id, None)

    def factory(self, capability_id: str) -> CapabilityLifecycleFactory | None:
        """Return a trusted factory without constructing the implementation."""

        binding = self._bindings.get(capability_id)
        return binding.lifecycle_factory if binding else None

    def contribution_factory(self, capability_id: str) -> CapabilityContributionFactory | None:
        """Return the trusted contribution factory for one capability."""

        binding = self._bindings.get(capability_id)
        return binding.contribution_factory if binding else None

    def contains(self, capability_id: str) -> bool:
        """Return whether a trusted implementation is bound."""

        return capability_id in self._bindings

    def list(self) -> tuple[str, ...]:
        """Return bound capability IDs in stable order."""

        return tuple(sorted(self._bindings))


__all__ = [
    "CapabilityBindingError",
    "CapabilityContributionFactory",
    "CapabilityImplementationRegistry",
    "CapabilityLifecycleFactory",
]
