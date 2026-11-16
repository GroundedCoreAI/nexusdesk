"""Small JSON-RPC correlation state machine for the App-Server adapter.

Provider-private by construction: request ids, method names and raw frames never
leave this package, and neither this module nor :mod:`.app_server` touches a
transport. Stage B (connection ownership, Session/Turn persistence) is not
implemented in this phase; only the pure state machine and codecs exist so the
protocol semantics can be unit tested without a socket.
"""

from dataclasses import dataclass, field

# Bounded pending set: an unbounded correlation map is a memory-exhaustion
# primitive for a peer that never answers. The ceiling matches the "bounded
# concurrency" requirement of FR-7.
DEFAULT_MAX_PENDING = 256


class JsonRpcStateError(ValueError):
    """Raised for duplicate ids or an exhausted bounded pending set."""


@dataclass
class JsonRpcState:
    """Pending-request correlation with a hard bound and late-response tolerance.

    Semantics preserved for Stage A/B compatibility:
    * registering an empty or already-pending id raises;
    * resolving an unknown or already-resolved id returns ``False`` (late and
      duplicate responses are ignored, never replayed);
    * a resolved id frees one slot of the bound.
    """

    max_pending: int = DEFAULT_MAX_PENDING
    _pending: dict[str, None] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if type(self.max_pending) is not int or self.max_pending < 1:
            raise JsonRpcStateError("max_pending must be a positive integer")

    def register(self, request_id: str) -> None:
        if not request_id or not isinstance(request_id, str):
            raise JsonRpcStateError("duplicate or empty JSON-RPC request id")
        if request_id in self._pending:
            raise JsonRpcStateError("duplicate or empty JSON-RPC request id")
        if len(self._pending) >= self.max_pending:
            raise JsonRpcStateError("JSON-RPC pending set is full")
        self._pending[request_id] = None

    def resolve(self, request_id: str) -> bool:
        if request_id not in self._pending:
            return False
        del self._pending[request_id]
        return True

    def pending(self) -> tuple[str, ...]:
        return tuple(self._pending)

    def clear(self) -> None:
        """Drop every waiter on disconnect; no response is synthesized."""
        self._pending.clear()
