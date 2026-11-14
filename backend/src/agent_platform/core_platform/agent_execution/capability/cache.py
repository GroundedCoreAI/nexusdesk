"""Bounded single-flight capability caches with injected clocks and keys.

The caches hold only sanitized DTOs. Values are served as ``fresh`` only
within TTL; expired or post-failure observations are ``stale`` and are never
treated as authorization, and a failed first attempt is ``error``.
"""

import asyncio
import hashlib
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import Field

from ..contracts.base import ExecutionContractModel
from ..contracts.capabilities import DigestString
from ..contracts.common import AdapterVersion, EngineId, OpaqueString, ProtocolId, Slug

CacheStatus = Literal["cold", "fresh", "stale", "error"]

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")

Loader = Callable[[], Awaitable[V]]

logger = logging.getLogger(__name__)


def _key_summary(key: object) -> dict[str, str]:
    """Non-reversible key identification for diagnostics; never key content.

    Cache keys carry tenant/agent scope and digests, so logs keep only the key
    type and a truncated hash that is stable within one process.
    """

    digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:16]
    return {"key_kind": type(key).__name__, "key_digest": digest}


class AvailabilityCacheKey(ExecutionContractModel):
    """Exact 03-4.3 identity key for one cached Available observation."""

    deployment_identity: OpaqueString
    engine_id: EngineId
    protocol_id: ProtocolId
    adapter_version: AdapterVersion
    config_schema_version: AdapterVersion
    probe_id: Slug
    probe_version: AdapterVersion
    declaration_digest: DigestString
    workspace_generation: int | None = Field(default=None, ge=0)


class PolicyCacheKey(ExecutionContractModel):
    """Exact 03-4.3 key for one cached Policy/Effective decision."""

    deployment_identity: OpaqueString
    engine_id: EngineId
    protocol_id: ProtocolId
    adapter_version: AdapterVersion
    config_schema_version: AdapterVersion
    probe_id: Slug
    probe_version: AdapterVersion
    declaration_digest: DigestString
    workspace_generation: int | None = Field(default=None, ge=0)
    tenant_id: str = Field(min_length=1, max_length=200)
    business_scope: OpaqueString | None = None
    workspace_id: OpaqueString | None = None
    agent_id: UUID | None = None
    agent_published_version: int | None = Field(default=None, ge=0)
    policy_provider_id: Slug
    policy_version: AdapterVersion
    policy_revision: int = Field(ge=0)
    disabled_capabilities_digest: DigestString
    execution_restriction_digest: DigestString


@dataclass(slots=True)
class _Entry(Generic[V]):
    value: V | None = None
    refreshed_at: float | None = None
    expires_at: float | None = None
    attempted_at: float | None = None
    failed: bool = False


@dataclass(frozen=True, slots=True)
class CacheLookup(Generic[V]):
    status: CacheStatus
    value: V | None


class CapabilityCache(Generic[K, V]):
    """TTL-bounded LRU cache with per-key singleflight and injected clock."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        capacity: int,
        clock: Callable[[], float],
        retry_interval_seconds: float,
    ) -> None:
        if ttl_seconds <= 0 or capacity < 1 or retry_interval_seconds < 0:
            raise ValueError("Cache bounds must be positive and retry interval non-negative")
        self._ttl = ttl_seconds
        self._capacity = capacity
        self._clock = clock
        self._retry_interval = retry_interval_seconds
        self._entries: OrderedDict[K, _Entry[V]] = OrderedDict()
        self._inflight: dict[K, asyncio.Task[tuple[bool, V | None]]] = {}

    @property
    def size(self) -> int:
        return len(self._entries)

    def status(self, key: K) -> CacheStatus:
        entry = self._entries.get(key)
        if entry is None or entry.value is None:
            if entry is not None and entry.attempted_at is not None:
                return "error"
            return "cold"
        if entry.failed:
            return "stale"
        if entry.expires_at is None or self._clock() >= entry.expires_at:
            return "stale"
        return "fresh"

    def lookup(self, key: K) -> CacheLookup[V]:
        entry = self._entries.get(key)
        value = entry.value if entry is not None else None
        return CacheLookup(self.status(key), value)

    async def refresh(self, key: K, loader: Loader) -> V | None:
        """Refresh once (sharing an in-flight round) and return the new value."""
        ok, value = await self._refresh_round(key, loader)
        return value if ok else None

    async def _refresh_round(self, key: K, loader: Loader) -> tuple[bool, V | None]:
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._load(key, loader))
            self._inflight[key] = task
            task.add_done_callback(lambda _completed, _key=key: self._inflight.pop(_key, None))
        return await asyncio.shield(task)

    def schedule(self, key: K, loader: Loader) -> bool:
        """Deduplicated background refresh; hot path never awaits it."""
        if key in self._inflight:
            return False
        entry = self._entries.get(key)
        now = self._clock()
        if (
            entry is not None
            and entry.attempted_at is not None
            and now - entry.attempted_at < self._retry_interval
        ):
            return False
        task = asyncio.create_task(self._load(key, loader))
        self._inflight[key] = task
        task.add_done_callback(lambda _completed, _key=key: self._inflight.pop(_key, None))
        return True

    async def _load(self, key: K, loader: Loader) -> tuple[bool, V | None]:
        entry = self._entries.get(key)
        if entry is None:
            entry = _Entry()
            self._entries[key] = entry
        entry.attempted_at = self._clock()
        try:
            value = await loader()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - any port failure is recorded as an error state.
            entry.failed = True
            # Only the exception type and a hashed key summary are logged: port
            # failure text may carry secrets or host paths and must never surface.
            logger.warning(
                "capability cache load failed",
                extra={"error_type": type(exc).__name__, **_key_summary(key)},
            )
            return False, None
        now = self._clock()
        entry.value = value
        entry.failed = False
        entry.refreshed_at = now
        entry.expires_at = now + self._ttl
        # A concurrent load of another key may have evicted this entry while the
        # loader was running; re-attach it so the finished observation is neither
        # lost by move_to_end nor reported to the caller as a failure.
        if self._entries.get(key) is not entry:
            self._entries[key] = entry
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
        return True, value

    async def wait_idle(self) -> None:
        while self._inflight:
            await asyncio.gather(*list(self._inflight.values()), return_exceptions=True)

    async def aclose(self) -> None:
        tasks = list(self._inflight.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
