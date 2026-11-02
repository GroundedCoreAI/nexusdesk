"""Outbound destination validation and address pinning for HTTP tools."""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpcore
import httpx

Resolver = Callable[[str, int], Awaitable[Iterable[str]]]


class ToolEgressError(Exception):
    """A sanitized error raised when a tool destination cannot be used."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PinnedDestination:
    hostname: str
    port: int
    addresses: tuple[str, ...]


_CURRENT_DESTINATION: ContextVar[PinnedDestination | None] = ContextVar(
    "tool_egress_destination", default=None
)
_LOCAL_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def normalize_hostname(hostname: str | bytes) -> str:
    if isinstance(hostname, bytes):
        hostname = hostname.decode("ascii")
    value = hostname.rstrip(".").lower()
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        return value


async def resolve_host(hostname: str, port: int) -> tuple[str, ...]:
    """Resolve a hostname without blocking the event loop."""

    try:
        records = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            port,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ToolEgressError("tool_connection_error") from exc

    addresses: set[str] = set()
    for family, _kind, _proto, _canonname, sockaddr in records:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        try:
            addresses.add(str(ipaddress.ip_address(sockaddr[0])))
        except (IndexError, ValueError, TypeError) as exc:
            raise ToolEgressError("tool_connection_error") from exc
    if not addresses:
        raise ToolEgressError("tool_connection_error")
    return tuple(sorted(addresses))


class ToolEgressPolicy:
    """Validate tool destinations and provide the address used for TCP connects."""

    def __init__(
        self,
        allowed_hosts: Iterable[str],
        *,
        allow_private_networks: bool = False,
        resolver: Resolver | None = None,
    ):
        self.allowed_hosts = frozenset(normalize_hostname(host) for host in allowed_hosts)
        self.allow_private_networks = allow_private_networks
        self.resolver = resolver or resolve_host

    @classmethod
    def from_settings(cls, settings: Any) -> "ToolEgressPolicy":
        return cls(
            settings.tool_allowed_hosts,
            allow_private_networks=settings.tool_allow_private_networks,
        )

    def allows_host(self, hostname: str) -> bool:
        normalized = normalize_hostname(hostname)
        return "*" in self.allowed_hosts or normalized in self.allowed_hosts

    def _allows_address(
        self, hostname: str, address: ipaddress.IPv4Address | ipaddress.IPv6Address
    ) -> bool:
        if address.is_loopback:
            return hostname in _LOCAL_HOSTNAMES and self.allows_host(hostname)
        if address.is_unspecified or address.is_multicast or address.is_reserved:
            return False
        if address.is_global:
            return True
        return self.allow_private_networks and self.allows_host(hostname)

    async def validate(
        self, url: str, previous: PinnedDestination | None = None
    ) -> PinnedDestination:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        if parsed.scheme not in {"http", "https"} or not hostname:
            raise ToolEgressError("tool_destination_not_allowed")
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            raise ToolEgressError("tool_destination_not_allowed") from exc

        normalized_hostname = normalize_hostname(hostname)
        if not self.allows_host(normalized_hostname):
            raise ToolEgressError("tool_destination_not_allowed")
        try:
            resolved = tuple(
                sorted(
                    {
                        str(ipaddress.ip_address(address))
                        for address in await self.resolver(hostname, port)
                    }
                )
            )
        except (TypeError, ValueError) as exc:
            raise ToolEgressError("tool_connection_error") from exc
        if not resolved:
            raise ToolEgressError("tool_connection_error")
        for raw_address in resolved:
            try:
                address = ipaddress.ip_address(raw_address)
            except ValueError as exc:
                raise ToolEgressError("tool_connection_error") from exc
            if not self._allows_address(normalized_hostname, address):
                raise ToolEgressError("tool_destination_not_allowed")
        destination = PinnedDestination(normalized_hostname, port, resolved)
        if previous is not None and destination != previous:
            raise ToolEgressError("tool_destination_changed")
        return destination

    @contextmanager
    def pin(self, destination: PinnedDestination) -> Iterator[None]:
        token = _CURRENT_DESTINATION.set(destination)
        try:
            yield
        finally:
            _CURRENT_DESTINATION.reset(token)


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Route each tool connection to the destination validated for its request."""

    def __init__(self, backend: httpcore.AsyncNetworkBackend):
        self.backend = backend

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ) -> httpcore.AsyncNetworkStream:
        destination = _CURRENT_DESTINATION.get()
        if (
            destination is None
            or normalize_hostname(host) != destination.hostname
            or port != destination.port
        ):
            raise httpcore.ConnectError("tool destination was not validated")

        last_error: Exception | None = None
        for address in destination.addresses:
            try:
                return await self.backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (OSError, httpcore.NetworkError) as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise httpcore.ConnectError("tool destination has no validated addresses")

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options=None
    ) -> httpcore.AsyncNetworkStream:
        return await self.backend.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options
        )

    async def sleep(self, seconds: float) -> None:
        await self.backend.sleep(seconds)


class ToolEgressTransport(httpx.AsyncHTTPTransport):
    """HTTPX transport whose direct TCP backend uses validated addresses."""

    def __init__(self, policy: ToolEgressPolicy, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pool._network_backend = PinnedNetworkBackend(self._pool._network_backend)
        self.policy = policy
