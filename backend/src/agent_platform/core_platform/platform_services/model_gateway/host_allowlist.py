"""Tenant-scoped egress hosts managed from the console (public HTTPS only).

The deployment environment list stays authoritative; this store only adds
hostnames when ``AGENT_MODEL_GATEWAY_UI_ALLOWED_HOSTS`` is enabled. Every write
is audited, and a process-local TTL cache keeps the hot model-call path free of
an extra database round-trip. Removal is fail-closed: a host that disappears
from the effective set can no longer be saved, probed or invoked.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import time
from collections.abc import Callable
from urllib.parse import urlsplit
from uuid import uuid4

from agent_platform.core_platform.agent_execution.host.network_policy import (
    classify_address,
)
from agent_platform.core_platform.platform_services.persistence.store import (
    DomainError,
    audit,
    execute,
    many,
    one,
)

__all__ = [
    "HostAllowlistStore",
    "normalize_public_host",
    "resolve_public",
]

_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_METADATA_NAMES = frozenset({"localhost", "metadata", "metadata.google.internal", "instance-data"})
_CACHE_TTL_SECONDS = 15.0
_RESOLVE_TIMEOUT_SECONDS = 5.0


def _invalid() -> DomainError:
    return DomainError("model_host_invalid")


def _not_public() -> DomainError:
    return DomainError("model_host_not_public")


def normalize_public_host(value: str) -> str:
    """Return a canonical public DNS hostname or raise a stable domain error.

    Accepts a bare hostname or an ``https://host[/path]`` URL. Rejects literal
    IP addresses, wildcards, single-label names, embedded credentials, queries,
    fragments, plain http and metadata/localhost names.
    """

    if not isinstance(value, str):
        raise _invalid()
    raw = value.strip()
    if not raw:
        raise _invalid()
    if "://" in raw:
        try:
            url = urlsplit(raw)
            _ = url.port
        except ValueError:
            raise _invalid() from None
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
        ):
            raise _invalid()
        host = url.hostname
    else:
        host = raw
    host = host.strip().lower().rstrip(".")
    if (
        not host
        or not host.isascii()
        or len(host) > 253
        or "*" in host
        or "/" in host
        or ":" in host
    ):
        raise _invalid()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise _not_public()
    if host in _METADATA_NAMES or host.endswith(".localhost"):
        raise _not_public()
    labels = host.split(".")
    if len(labels) < 2 or any(not _LABEL.fullmatch(label) for label in labels):
        raise _invalid()
    return host


def _resolve(host: str) -> tuple[str, ...]:
    infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return tuple(sorted({info[4][0] for info in infos}))


async def resolve_public(
    host: str,
    *,
    resolver: Callable[[str], tuple[str, ...]] = _resolve,
    timeout: float = _RESOLVE_TIMEOUT_SECONDS,
) -> tuple[str, ...]:
    """Resolve in a worker thread and require every address to be public."""

    try:
        async with asyncio.timeout(timeout):
            addresses = tuple(await asyncio.to_thread(resolver, host))
    except (OSError, TimeoutError):
        raise DomainError("model_host_unresolved") from None
    if not addresses:
        raise DomainError("model_host_unresolved")
    if any(classify_address(address) is not None for address in addresses):
        raise _not_public()
    return addresses


class HostAllowlistStore:
    """Additive, audited host list with a short process-local cache."""

    def __init__(
        self,
        engine,
        settings,
        *,
        ttl: float = _CACHE_TTL_SECONDS,
        resolver: Callable[[str], tuple[str, ...]] = _resolve,
    ) -> None:
        self._engine = engine
        self._settings = settings
        self._ttl = ttl
        self._resolver = resolver
        self._cache: dict[str, tuple[float, frozenset[str]]] = {}

    def enabled(self) -> bool:
        return bool(self._settings.model_gateway_ui_allowed_hosts)

    def invalidate(self, tenant: str) -> None:
        self._cache.pop(tenant, None)

    async def effective(self, tenant: str) -> frozenset[str]:
        if not self.enabled():
            return frozenset()
        now = time.monotonic()
        cached = self._cache.get(tenant)
        if cached is not None and cached[0] > now:
            return cached[1]
        async with self._engine.connect() as connection:
            rows = await many(
                connection,
                "SELECT host FROM gateway_allowed_hosts WHERE tenant_id=:t",
                t=tenant,
            )
        hosts = frozenset(str(row["host"]) for row in rows)
        self._cache[tenant] = (now + self._ttl, hosts)
        return hosts

    async def list(self, tenant: str) -> list[dict]:
        async with self._engine.connect() as connection:
            return await many(
                connection,
                """SELECT host,created_by,created_at FROM gateway_allowed_hosts
                WHERE tenant_id=:t ORDER BY host""",
                t=tenant,
            )

    async def ensure_resolution(self, host: str) -> tuple[str, ...]:
        return await resolve_public(host, resolver=self._resolver)

    async def add(self, tenant: str, actor: str, value: str) -> dict:
        if not self.enabled():
            raise DomainError("model_host_management_disabled", 409)
        host = normalize_public_host(value)
        await self.ensure_resolution(host)
        async with self._engine.begin() as connection:
            # Serialize concurrent additions of the same host so ON CONFLICT
            # DO NOTHING can report a deterministic conflict.
            await execute(
                connection,
                "SELECT pg_advisory_xact_lock(hashtextextended(:s,9130))",
                s=f"{tenant}:allowed-hosts",
            )
            row = await one(
                connection,
                """INSERT INTO gateway_allowed_hosts(id,tenant_id,host,created_by)
                VALUES(:id,:t,:h,:a) ON CONFLICT(tenant_id,host) DO NOTHING
                RETURNING host,created_by,created_at""",
                id=uuid4(),
                t=tenant,
                h=host,
                a=actor,
            )
            if row is None:
                raise DomainError("model_host_exists", 409)
            await audit(
                connection,
                tenant,
                actor,
                "model_gateway.allowed_host.added",
                f"gateway_allowed_host:{host}",
            )
        self.invalidate(tenant)
        return row

    async def remove(self, tenant: str, actor: str, value: str) -> None:
        if not self.enabled():
            raise DomainError("model_host_management_disabled", 409)
        host = normalize_public_host(value)
        async with self._engine.begin() as connection:
            row = await one(
                connection,
                """DELETE FROM gateway_allowed_hosts
                WHERE tenant_id=:t AND host=:h RETURNING host""",
                t=tenant,
                h=host,
            )
            if row is None:
                raise DomainError("model_host_not_found", 404)
            await audit(
                connection,
                tenant,
                actor,
                "model_gateway.allowed_host.removed",
                f"gateway_allowed_host:{host}",
            )
        self.invalidate(tenant)
