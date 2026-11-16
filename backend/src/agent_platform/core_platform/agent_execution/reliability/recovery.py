"""Takeover recovery: confirmed cleanup before one terminal state (T-09).

Unconfirmed cancellation/cleanup never reports ``cancelled``. The coordinator
first fences the expired lease (new epoch), asks the Host/Workspace cleanup
port for a real confirmation, and only then commits one terminal state.
"""

from collections.abc import Awaitable, Callable, Mapping


def terminal_decision(cancel_requested: bool, cleanup_confirmed: bool) -> tuple[str, str]:
    """Return (Run status, cleanup_status) from real confirmation evidence."""
    if cleanup_confirmed:
        return ("cancelled" if cancel_requested else "failed", "completed")
    return ("failed", "failed")


CleanupConfirmation = Callable[[Mapping[str, object]], Awaitable[bool]]


class RecoveryCoordinator:
    def __init__(self, repository, cleanup: CleanupConfirmation) -> None:
        self._repository = repository
        self._cleanup = cleanup

    async def recover_expired(self, tenant: str, *, new_owner=None, batch_size: int = 100) -> int:
        rows = await self._repository.expired_running(tenant, batch=batch_size)
        if not rows:
            return 0
        confirmed: list[dict[str, object]] = []
        for row in rows:
            try:
                cleanup_ok = await self._cleanup(row)
            except Exception:  # noqa: BLE001 - unconfirmed cleanup is a failure.
                cleanup_ok = False
            confirmed.append({"id": row["id"], "cleanup_confirmed": cleanup_ok})
        return await self._repository.apply_recovery(confirmed, new_owner=new_owner)
