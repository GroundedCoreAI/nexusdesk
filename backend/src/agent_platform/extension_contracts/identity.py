"""Identity service bindings assembled by an application composition root."""

from dataclasses import dataclass


@dataclass(frozen=True)
class IdentityBindings:
    """Small dependency bundle exposed to the identity adapters."""

    engine: object
    enterprise: object
