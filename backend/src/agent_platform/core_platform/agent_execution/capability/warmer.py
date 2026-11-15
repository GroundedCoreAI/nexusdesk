"""Controlled background warmer for capability cache initial population.

The warmer owns one loop task per application composition. It only calls the
resolver's awaited ``warm`` refresh (trusted ports plus sanitized cache
writes); it never constructs adapters, starts runs, or touches authorization.
A raising round is logged and retried at the bounded retry interval: losing the
loop would silently freeze platform-wide cache freshness. Application close
must call :meth:`aclose`, which cancels the loop task.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from contextlib import suppress

from .resolver import CapabilityResolutionRequest, CapabilityResolver

Sleeper = Callable[[float], Awaitable[None]]

logger = logging.getLogger(__name__)


class CapabilityWarmer:
    """Round-based background refresher with bounded failure retry."""

    def __init__(
        self,
        *,
        resolver: CapabilityResolver,
        targets: Iterable[CapabilityResolutionRequest],
        refresh_interval_seconds: float,
        retry_interval_seconds: float,
        sleeper: Sleeper | None = None,
    ) -> None:
        if refresh_interval_seconds <= 0 or retry_interval_seconds <= 0:
            raise ValueError("Warmer intervals must be positive")
        self._resolver = resolver
        self._targets = tuple(targets)
        self._refresh_interval = refresh_interval_seconds
        self._retry_interval = retry_interval_seconds
        self._sleeper: Sleeper = sleeper or asyncio.sleep
        self._loop_task: asyncio.Task[None] | None = None
        self._next_delay = refresh_interval_seconds
        self._closed = False

    @property
    def next_refresh_delay(self) -> float:
        """Bounded delay until the next round: refresh or failure retry."""
        return self._next_delay

    def start(self) -> None:
        """Spawn the background loop; the first round populates cache entries."""
        if self._closed:
            raise RuntimeError("CapabilityWarmer is closed")
        if self._loop_task is None:
            self._loop_task = asyncio.create_task(self._run())

    async def run_once(self) -> bool:
        """One deterministic refresh round over all targets; True if all passed."""
        warmed = True
        for target in self._targets:
            if not await self._resolver.warm(target):
                warmed = False
        self._next_delay = self._refresh_interval if warmed else self._retry_interval
        return warmed

    async def _run(self) -> None:
        try:
            while not self._closed:
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - any round failure retries, never ends the loop.
                    # The exception text is never logged: port and registry
                    # failures may carry secrets or host paths. Only the type
                    # name and the target count are safe diagnostics.
                    logger.warning(
                        "capability warm round failed",
                        extra={"error_type": type(exc).__name__, "targets": len(self._targets)},
                    )
                    self._next_delay = self._retry_interval
                if self._closed:
                    break
                await self._sleeper(self._next_delay)
        except asyncio.CancelledError:
            if not self._closed:
                raise

    async def aclose(self) -> None:
        """Cancel and reap the background loop; leaves no pending warmer task."""
        self._closed = True
        task = self._loop_task
        self._loop_task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
