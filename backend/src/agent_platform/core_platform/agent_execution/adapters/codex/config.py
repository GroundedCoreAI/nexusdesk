"""Fail-closed stage gates for Codex adapters.

The publishable ``CodexConfig`` and ``CodexProtocol`` types live in ``contracts``
so the registry and snapshots validate the exact same strict model without a
contracts-to-adapters dependency. They are re-exported here for adapter callers.
This module deliberately keeps Stage B hard-disabled at the gate level.
"""

from pydantic import BaseModel, ConfigDict

from agent_platform.core_platform.agent_execution.contracts.config import (
    CodexConfig,
    CodexProtocol,
)

# Stable gate denials, consumed by the adapter to pick an existing
# ``ExecutionErrorCode``. They are not public error codes: the adapter maps them
# onto the frozen catalog so the Run vocabulary does not grow (Phase 5 C2).
GATE_DENIED_DISABLED = "stage_gate_disabled"
GATE_DENIED_VERSION = "version_not_allowed"
GATE_DENIED_TENANT = "tenant_not_trusted"
GATE_DENIED_PROTOCOL = "protocol_disabled"


def _protocol(value: CodexProtocol | str) -> CodexProtocol:
    try:
        return value if isinstance(value, CodexProtocol) else CodexProtocol(value)
    except (TypeError, ValueError):
        raise ValueError("unknown Codex protocol") from None


class CodexStageGate(BaseModel):
    """Deployment gate shared by CLI and app-server protocols.

    ``permits`` answers one execution; ``deployment_enabled`` answers whether the
    registration may be constructed at all. Both default to refusal: an
    unconfigured deployment trusts no version and no tenant, so there is no code
    path that reads "empty allowlist" as "allow everything".
    """

    model_config = ConfigDict(frozen=True)

    cli_enabled: bool = False
    app_server_enabled: bool = False
    allowed_versions: tuple[str, ...] = ()
    trusted_tenants: tuple[str, ...] = ()
    stage_a_verified: bool = False

    def denial(
        self,
        protocol: CodexProtocol | str,
        *,
        version: str,
        tenant_id: str,
    ) -> str | None:
        """Return the stable denial reason, or ``None`` when the run may start."""
        protocol = _protocol(protocol)
        if not self.stage_a_verified or not self.cli_enabled:
            return GATE_DENIED_DISABLED
        if not version or version not in self.allowed_versions:
            return GATE_DENIED_VERSION
        if not tenant_id or tenant_id not in self.trusted_tenants:
            return GATE_DENIED_TENANT
        if protocol is not CodexProtocol.CLI_EXEC and not self.app_server_enabled:
            return GATE_DENIED_PROTOCOL
        return None

    def permits(self, protocol: CodexProtocol | str, *, version: str, tenant_id: str) -> bool:
        return self.denial(protocol, version=version, tenant_id=tenant_id) is None

    def deployment_enabled(self, protocol: CodexProtocol | str) -> bool:
        """Whether the registration for ``protocol`` may be marked enabled.

        Version and tenant allowlists must both be non-empty because a
        registration that can never permit an execution is not a deployment.
        """
        protocol = _protocol(protocol)
        if not self.cli_enabled or not self.stage_a_verified:
            return False
        if not self.allowed_versions or not self.trusted_tenants:
            return False
        return protocol is CodexProtocol.CLI_EXEC or self.app_server_enabled


__all__ = [
    "GATE_DENIED_DISABLED",
    "GATE_DENIED_PROTOCOL",
    "GATE_DENIED_TENANT",
    "GATE_DENIED_VERSION",
    "CodexConfig",
    "CodexProtocol",
    "CodexStageGate",
]
