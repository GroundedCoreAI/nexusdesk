"""Managed allowlist egress proxy endpoint (R-19).

The allowlist path is only available when a managed proxy endpoint is supplied.
The proxy runs on an isolated internal container network; the sandbox joins that
network with no direct external route, so the proxy is the only egress path.
An unavailable/missing proxy fails closed rather than opening a bridge.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EgressProxyEndpoint:
    host: str
    port: int

    def __post_init__(self) -> None:
        if not isinstance(self.host, str) or not self.host.strip():
            raise ValueError("egress proxy host must be nonempty")
        if not 1 <= self.port <= 65535:
            raise ValueError("egress proxy port must be valid")

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class EgressNetwork:
    """The isolated internal network name shared by sandbox and proxy."""

    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("egress network name must be nonempty")
