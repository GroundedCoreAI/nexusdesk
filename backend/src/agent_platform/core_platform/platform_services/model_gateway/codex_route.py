"""Resolve one Codex CLI provider plan from a published ModelGateway profile (Q3).

ModelGateway is the single source of truth for model/provider selection, address
governance and credential binding. It is an *outbound* client only: there is no
inbound OpenAI-compatible endpoint, so the Codex CLI still calls the resolved
upstream directly. This resolver therefore only builds the per-run, key-free
``CODEX_HOME`` metadata and the credential *reference*; it never routes inference
traffic and never reads a secret value.

Every failure is a :class:`CodexRouteError` carrying a stable, secret-free
``code``. The adapter maps those (and any other resolver exception) to one
classified execution error instead of letting a raw exception degrade into the
sanitized ``execution_error`` legacy code.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

from agent_platform.core_platform.agent_execution.adapters.codex.home_config import (
    CodexEngineHomeConfig,
)
from agent_platform.core_platform.platform_services.persistence.store import DomainError

__all__ = ["CodexProviderPlan", "CodexProviderResolver", "CodexRouteError"]

# Neutral child env slot already present in CODEX_CREDENTIAL_ENV_KEYS. The value
# is the provider's real key held in execution_credentials, never stored here.
_CODEX_ENV_KEY = "OPENAI_API_KEY"
_PROVIDER_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_NON_PROVIDER_CHAR = re.compile(r"[^A-Za-z0-9_-]")
_WIRE_APIS = frozenset({"responses", "chat"})


class CodexRouteError(RuntimeError):
    """Fail-closed resolution error naming only a stable, non-sensitive code."""

    def __init__(self, code: str) -> None:
        self.code = code
        # The message is the code alone: no URL (which could carry credentials),
        # no connection name, no profile id and no exception text is echoed.
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class CodexProviderPlan:
    """The resolved per-run engine home plus the credential reference to bind."""

    home_config: CodexEngineHomeConfig
    credential_ref: UUID | None


def _require_bare_https(base_url: str) -> None:
    """Codex may only be pointed at a bare https endpoint."""

    try:
        parsed = urlsplit(base_url)
        _ = parsed.port  # a malformed port raises ValueError in urllib
    except (ValueError, TypeError):
        raise CodexRouteError("codex_host_not_allowed") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(ch.isspace() for ch in base_url)
    ):
        raise CodexRouteError("codex_host_not_allowed")


def _sanitize_provider(name: object) -> str:
    """Derive a safe TOML table key from a connection name when none is set."""

    provider = _NON_PROVIDER_CHAR.sub("-", str(name)).lower()
    if not provider or not provider[0].isalpha():
        provider = f"p{provider}"
    provider = provider[:64]
    if not _PROVIDER_ID.fullmatch(provider):
        raise CodexRouteError("codex_route_missing")
    return provider


class CodexProviderResolver:
    """Build one per-run Codex provider plan from a published chat profile."""

    def __init__(self, engine, settings, catalog) -> None:
        self._engine = engine
        self._settings = settings
        self._catalog = catalog

    async def resolve(
        self,
        tenant_id: str,
        profile_id: UUID,
        version: int | None,
        workspace_id: str = "default",
        *,
        connection: object | None = None,
    ) -> CodexProviderPlan:
        """Resolve ``profile_id``/``version`` for ``tenant_id``.

        ``workspace_id`` is the run's credential-scope hint; provider selection
        itself is tenant/profile scoped. It is accepted so the adapter and any
        future scoped-credential validation share one resolution signature.
        ``connection`` lets callers reuse an existing DB connection (publish
        validation and tests); otherwise one is opened from the resolver engine.
        """

        if connection is None:
            async with self._engine.connect() as c:
                return await self._resolve(c, tenant_id, profile_id, version)
        return await self._resolve(connection, tenant_id, profile_id, version)

    async def _resolve(
        self,
        c: object,
        tenant_id: str,
        profile_id: UUID,
        version: int | None,
    ) -> CodexProviderPlan:
        try:
            snapshot = await self._catalog.resolve(tenant_id, profile_id, version, c)
        except DomainError:
            raise CodexRouteError("codex_route_missing") from None
        try:
            spec: Mapping[str, object] = snapshot["spec"]
            routes: list[Mapping[str, object]] = snapshot["routes"]
        except (KeyError, TypeError):
            raise CodexRouteError("codex_route_missing") from None
        if spec.get("operation") != "chat":
            raise CodexRouteError("codex_profile_not_chat")
        if not routes:
            raise CodexRouteError("codex_route_missing")
        # Codex needs tool calling on every route, not just the primary one: a
        # fallback route without tools would turn a failover into a silent
        # capability loss.
        for route in routes:
            try:
                if not route["model"]["tool_calling"]:
                    raise CodexRouteError("codex_profile_tool_calling")
            except (KeyError, TypeError):
                raise CodexRouteError("codex_route_missing") from None
        try:
            primary = routes[0]
            model = str(primary["model"]["model_name"])
            conn: Mapping[str, object] = primary["connection"]
            # A connection may override the transport address/wire protocol for
            # providers whose OpenAI-compatible prefix differs from the
            # outbound Gateway client's base_url.
            base_url = str(conn.get("codex_base_url") or conn["base_url"])
            provider_raw = conn.get("codex_model_provider") or conn["name"]
            wire_api = conn.get("codex_wire_api") or "responses"
            credential_raw = conn.get("execution_credential_ref")
        except (KeyError, TypeError, AttributeError):
            raise CodexRouteError("codex_route_missing") from None

        _require_bare_https(base_url)
        self._assert_host_allowed(base_url)
        if wire_api not in _WIRE_APIS:
            raise CodexRouteError("codex_route_missing")
        credential_ref: UUID | None = None
        if credential_raw is not None:
            try:
                credential_ref = UUID(str(credential_raw))
            except (ValueError, TypeError, AttributeError):
                raise CodexRouteError("codex_route_missing") from None
        try:
            home_config = CodexEngineHomeConfig(
                model=model,
                model_provider=_sanitize_provider(provider_raw),
                base_url=base_url,
                env_key=_CODEX_ENV_KEY,
                wire_api=str(wire_api),
            )
        except ValueError:
            # An out-of-contract model/provider/base_url/wire_api must not reach
            # the private CODEX_HOME as a raw exception or a raw value.
            raise CodexRouteError("codex_route_missing") from None
        return CodexProviderPlan(home_config=home_config, credential_ref=credential_ref)

    def _assert_host_allowed(self, base_url: str) -> None:
        """Let ``model_gateway_allowed_hosts`` govern the Codex transport too."""

        # validate_address owns the scheme, embedded-credential, query and
        # fragment checks plus the allowlist. A non-demo protocol is forced so a
        # real Codex upstream address can never skip the allowlist via the
        # demo-protocol early return.
        try:
            self._catalog.validate_address({"protocol": "openai_compatible", "base_url": base_url})
        except DomainError:
            raise CodexRouteError("codex_host_not_allowed") from None
        # Defense in depth against a catalog double that skips validation: the
        # resolver's own settings carry the same deployment allowlist.
        allowed = getattr(self._settings, "model_gateway_allowed_hosts", None)
        if not allowed or "*" in allowed:
            return
        host = urlsplit(base_url).hostname or ""
        if host.lower() not in {str(item).lower() for item in allowed}:
            raise CodexRouteError("codex_host_not_allowed")
