"""Fail-closed configuration and stage gates for Codex adapters.

This module is deployment-level configuration plus the one stage gate every
Codex protocol consults. It deliberately does not widen ``ExecutionConfig``: the
canonical execution configuration stays engine/protocol/version plus the React
block, and a Codex block there would be a second, publishable policy surface
(Phase 5 C4).
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Stable gate denials, consumed by the adapter to pick an existing
# ``ExecutionErrorCode``. They are not public error codes: the adapter maps them
# onto the frozen catalog so the Run vocabulary does not grow (Phase 5 C2).
GATE_DENIED_DISABLED = "stage_gate_disabled"
GATE_DENIED_VERSION = "version_not_allowed"
GATE_DENIED_TENANT = "tenant_not_trusted"
GATE_DENIED_PROTOCOL = "protocol_disabled"


class CodexProtocol(StrEnum):
    CLI_EXEC = "cli_exec"
    APP_SERVER = "app_server"


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


class CodexConfig(BaseModel):
    """Typed, bounded Codex execution options.

    ``strict``/``frozen``/``extra="forbid"`` are mandatory for a registry
    ``config_schema``: ``AdapterRegistry.register`` refuses anything weaker.
    Credentials are represented only by a reference; values must be injected by
    the execution host and are deliberately excluded from this model.

    Stage A accepts exactly one approval mode and one sandbox mode. Accepting a
    wider value here would advertise a capability the stage gate has not
    verified, so the model rejects it at validation time instead.
    """

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    protocol: CodexProtocol = CodexProtocol.CLI_EXEC
    version: str = Field(min_length=1, max_length=64)
    executable: str = Field(default="codex", min_length=1, max_length=256)
    # C6: bounded by the Run deadline ceiling (settings.run_timeout_seconds is
    # le=600), so a deployment cannot configure a Codex timeout that outlives
    # every Run it belongs to. The effective timeout is the minimum of this
    # value, the Run deadline and the Host wall ceiling.
    timeout_seconds: int = Field(default=600, gt=0, le=600)
    approval_mode: Literal["never"] = "never"
    sandbox_mode: Literal["read-only"] = "read-only"
    credential_ref: str | None = Field(default=None, min_length=1, max_length=256)
    # The one environment value this lane may contribute (08 R17): the installed
    # CLI is a ``#!/usr/bin/env node`` launcher, so an empty environment makes
    # the kernel fail the exec with ENOENT (measured: ``env -i codex --version``
    # exits 127 with "node: No such file or directory"). A typed ``PATH`` is
    # deliberately narrower than a free-form map: credentials, proxy settings and
    # host secrets have no field to travel in, so nothing here can become an
    # injection surface (C1/C2).
    path_env: str = Field(default="/usr/local/bin:/usr/bin:/bin", min_length=1, max_length=4096)

    @field_validator("path_env")
    @classmethod
    def path_env_must_be_absolute_dirs(cls, value: str) -> str:
        # Only absolute directories, no ``..`` segments, no empty entries (an
        # empty entry means "current directory" to most loaders).
        if "\x00" in value or ".." in value.split(":"):
            raise ValueError("path_env must not contain NUL or parent segments")
        entries = value.split(":")
        if not entries or any(not entry.startswith("/") for entry in entries):
            raise ValueError("path_env entries must be absolute directories")
        return value

    @field_validator("protocol", mode="before")
    @classmethod
    def accept_protocol_value(cls, value: object) -> object:
        # ``strict=True`` is mandatory for a registry config schema, but a
        # deployment file supplies the bare string; normalizing the enum value
        # here keeps both callers valid without weakening any other field.
        if isinstance(value, CodexProtocol):
            return value
        if type(value) is str:
            return _protocol(value)
        return value

    @field_validator("executable")
    @classmethod
    def executable_must_be_name(cls, value: str) -> str:
        if "\x00" in value or "/" in value or "\\" in value:
            raise ValueError("executable must be a command name, not a path")
        return value

    @field_validator("approval_mode", mode="before")
    @classmethod
    def stage_a_approval_mode_only(cls, value: object) -> object:
        if value != "never":
            raise ValueError("Stage A only supports approval_mode='never'")
        return value

    @field_validator("sandbox_mode", mode="before")
    @classmethod
    def stage_a_sandbox_mode_only(cls, value: object) -> object:
        if value != "read-only":
            raise ValueError("Stage A only supports sandbox_mode='read-only'")
        return value
