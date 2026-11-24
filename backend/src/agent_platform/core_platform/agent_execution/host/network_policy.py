"""Pure default-deny egress policy with private/metadata/DNS checks (T-08)."""

import ipaddress
from collections.abc import Callable
from dataclasses import dataclass, field

_METADATA_ADDRESS = ipaddress.ip_address("169.254.169.254")


@dataclass(frozen=True, slots=True)
class NetworkRule:
    host: str
    port: int

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip() or not 1 <= self.port <= 65535:
            raise ValueError("network rule requires a host and a valid TCP port")


@dataclass(frozen=True, slots=True)
class NetworkPolicy:
    rules: tuple[NetworkRule, ...] = ()
    default_deny: bool = True

    def __post_init__(self) -> None:
        if type(self.default_deny) is not bool:
            raise TypeError("default_deny must be boolean")

    def allows(self, host: str, port: int) -> bool:
        normalized = host.strip().lower().rstrip(".")
        return any(
            rule.host.strip().lower().rstrip(".") == normalized and rule.port == port
            for rule in self.rules
        )


@dataclass(frozen=True, slots=True)
class DestinationDecision:
    allowed: bool
    reason_code: str
    pinned_ips: tuple[str, ...] = field(default_factory=tuple)


def _deny(reason: str) -> DestinationDecision:
    return DestinationDecision(False, reason)


def classify_address(value: str) -> str | None:
    """Classify one resolved address as metadata/private/unparsable or public."""

    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return "unparsable"
    if address == _METADATA_ADDRESS:
        return "metadata"
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        return "private"
    return None


def decide_destination(
    policy: NetworkPolicy,
    *,
    host: str,
    port: int,
    resolved_ips: tuple[str, ...],
) -> DestinationDecision:
    """Allow only an exact rule whose every resolved IP is public."""
    if not policy.allows(host, port) and policy.default_deny:
        return _deny("egress_not_allowed")
    if not resolved_ips:
        return _deny("dns_unresolved")
    reason: str | None = None
    for value in resolved_ips:
        classification = classify_address(value)
        if classification == "metadata":
            return _deny("egress_metadata_address")
        if classification is not None:
            reason = reason or (
                "egress_private_address" if classification == "private" else "dns_unresolved"
            )
    if reason is not None:
        return _deny(reason)
    return DestinationDecision(True, "allowed", tuple(resolved_ips))


def validate_connect_target(
    policy: NetworkPolicy,
    *,
    host: str,
    port: int,
    resolver: Callable[[str], tuple[str, ...]],
) -> DestinationDecision:
    """Resolve once and pin the actual connected IPs for this hop."""
    try:
        resolved = tuple(resolver(host))
    except OSError:
        return _deny("dns_unresolved")
    return decide_destination(policy, host=host, port=port, resolved_ips=resolved)
