"""Request-local business scope used by data-plane resource services."""

from contextvars import ContextVar, Token

from agent_platform.extension_contracts import BusinessScope

_current_scope: ContextVar[BusinessScope | None] = ContextVar(
    "agent_platform_business_scope",
    default=None,
)


def bind_scope(scope: BusinessScope) -> Token[BusinessScope | None]:
    """Bind one validated scope for the current request/task."""

    return _current_scope.set(scope)


def reset_scope(token: Token[BusinessScope | None]) -> None:
    """Restore the previous request scope."""

    _current_scope.reset(token)


def current_scope() -> BusinessScope | None:
    """Return the current trusted scope, if the code runs inside a request."""

    return _current_scope.get()
