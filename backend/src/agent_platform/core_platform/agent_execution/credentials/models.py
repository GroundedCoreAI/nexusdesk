"""Internal Execution credential and grant DTOs (02 FR-1/FR-2, T-01).

These are administrative/internal value objects, not public API responses.
``ExecutionCredentialRecord.public_metadata`` is the only serializable view and
deliberately omits the encrypted secret. Grants carry an irreversible hash
identity, never a replayable plaintext token. Phase 6 T-07 adds the Vault and
Broker behavior over these shapes; T-01 only freezes them.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import UUID

CredentialStatus = Literal["active", "superseded", "revoked"]
CredentialType = Literal["token", "api_key", "oauth_client", "mtls_certificate"]
CREDENTIAL_STATUSES: frozenset[str] = frozenset({"active", "superseded", "revoked"})
CREDENTIAL_TYPES: frozenset[str] = frozenset(
    {"token", "api_key", "oauth_client", "mtls_certificate"}
)


def _is_uuid(value: object) -> bool:
    return isinstance(value, UUID) and (
        type(value) is UUID or any(base is UUID for base in type(value).__mro__)
    )


def _nonempty(value: object, name: str, limit: int = 200) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise ValueError(f"{name} must be a nonempty string of at most {limit} characters")
    return value


def _aware(value: object, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")
    return value


def _scopes(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise ValueError(f"{name} must be a nonempty tuple")
    for item in value:
        _nonempty(item, name, limit=200)
    return value


@dataclass(frozen=True, slots=True)
class ExecutionCredentialRecord:
    """One immutable credential version row (internal lifecycle snapshot)."""

    credential_id: UUID
    credential_ref: UUID
    tenant_id: str
    name: str
    credential_type: CredentialType
    encrypted_secret: str = field(repr=False)
    key_version: str
    version: int
    status: CredentialStatus
    allowed_engines: tuple[str, ...]
    allowed_workspaces: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    rotated_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if not _is_uuid(self.credential_id) or not _is_uuid(self.credential_ref):
            raise ValueError("credential identity requires UUIDs")
        object.__setattr__(self, "tenant_id", _nonempty(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "name", _nonempty(self.name, "name"))
        if self.credential_type not in CREDENTIAL_TYPES:
            raise ValueError("credential type is outside the closed vocabulary")
        object.__setattr__(
            self, "encrypted_secret", _nonempty(self.encrypted_secret, "encrypted_secret")
        )
        object.__setattr__(self, "key_version", _nonempty(self.key_version, "key_version"))
        if type(self.version) is not int or self.version < 1:
            raise ValueError("credential version must be a positive integer")
        if self.status not in CREDENTIAL_STATUSES:
            raise ValueError("credential status is outside the closed vocabulary")
        object.__setattr__(
            self, "allowed_engines", _scopes(self.allowed_engines, "allowed_engines")
        )
        object.__setattr__(
            self, "allowed_workspaces", _scopes(self.allowed_workspaces, "allowed_workspaces")
        )
        object.__setattr__(self, "created_at", _aware(self.created_at, "created_at"))
        object.__setattr__(self, "updated_at", _aware(self.updated_at, "updated_at"))
        if self.rotated_at is not None:
            object.__setattr__(self, "rotated_at", _aware(self.rotated_at, "rotated_at"))
        if self.revoked_at is not None:
            object.__setattr__(self, "revoked_at", _aware(self.revoked_at, "revoked_at"))

    def public_metadata(self) -> dict[str, object]:
        """Administrative view: identifiers/status/scope, never secret material."""
        return {
            "credential_ref": str(self.credential_ref),
            "tenant_id": self.tenant_id,
            "name": self.name,
            "credential_type": self.credential_type,
            "key_version": self.key_version,
            "version": self.version,
            "status": self.status,
            "allowed_engines": self.allowed_engines,
            "allowed_workspaces": self.allowed_workspaces,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "rotated_at": None if self.rotated_at is None else self.rotated_at.isoformat(),
            "revoked_at": None if self.revoked_at is None else self.revoked_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class ExecutionCredentialGrant:
    """One short-lived grant bound to exactly one Execution attempt."""

    grant_id: UUID
    grant_hash: str
    credential_id: UUID
    credential_version: int
    run_id: UUID
    tenant_id: str
    engine_id: str
    protocol_id: str
    workspace_id: str
    scopes: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, name in (
            (self.grant_id, "grant_id"),
            (self.credential_id, "credential_id"),
            (self.run_id, "run_id"),
        ):
            if not _is_uuid(value):
                raise ValueError(f"{name} must be a UUID")
        object.__setattr__(self, "grant_hash", _nonempty(self.grant_hash, "grant_hash"))
        if len(self.grant_hash) < 32:
            raise ValueError("grant hash must not be shorter than 32 characters")
        if type(self.credential_version) is not int or self.credential_version < 1:
            raise ValueError("credential version must be a positive integer")
        object.__setattr__(self, "tenant_id", _nonempty(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "engine_id", _nonempty(self.engine_id, "engine_id"))
        object.__setattr__(self, "protocol_id", _nonempty(self.protocol_id, "protocol_id"))
        object.__setattr__(self, "workspace_id", _nonempty(self.workspace_id, "workspace_id"))
        object.__setattr__(self, "scopes", _scopes(self.scopes, "scopes"))
        object.__setattr__(self, "issued_at", _aware(self.issued_at, "issued_at"))
        object.__setattr__(self, "expires_at", _aware(self.expires_at, "expires_at"))
        if self.expires_at <= self.issued_at:
            raise ValueError("grant expiry must be after its issuance")
        if self.revoked_at is not None:
            object.__setattr__(self, "revoked_at", _aware(self.revoked_at, "revoked_at"))
        if self.last_used_at is not None:
            object.__setattr__(self, "last_used_at", _aware(self.last_used_at, "last_used_at"))
