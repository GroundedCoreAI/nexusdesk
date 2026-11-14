"""Five strict Phase 3 startup snapshots, recursive secret scan, canonical bytes.

Every snapshot is a strict, frozen DTO that carries the startup identity
(``execution_id``, R-9: the identity lives inside the DTOs, never as a sixth
column). ``serialize_snapshot`` performs, in order: type check, recursive
denylist scan of the dumped payload, canonical JSON serialization (fixed key
order, no NaN/Infinity, timezone-required datetimes), a strict re-validation of
those exact bytes (``model_copy(update=...)`` bypasses pydantic validators, and
the completion invariants are what later replay treats as authorization, so the
canonical text is re-validated before it is returned), and a per-class UTF-8
size check. Denylist violations report only the field path and a stable code;
the rejected value is never echoed into the message, its traceback chain, or
any log. Any failure raises :class:`ExecutionSnapshotError` so the caller
fails closed before ``Adapter.start``.

Two deliberate narrowing decisions are part of this contract, not accidents:

* **Value-shaped host paths.** ``_value_is_denied`` rejects *every* string value
  that starts with a path separator (``/``, ``./``, ``../``, ``~/``,
  ``<drive>:\\``) regardless of the key that carries it, because a snapshot must
  never record a host filesystem location. Inbound values therefore have to be
  opaque identifiers, never paths. Consequence for callers: if a legitimate
  snapshot field ever needs a leading-separator value, this rule must be
  revisited explicitly instead of being widened ad hoc.
* **Semantic, not byte-level, replay.** See ``deserialize_execution_snapshots``.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, ValidationError, field_validator, model_validator

from .base import ExecutionContractModel
from .capabilities import (
    CAPABILITY_ORDER,
    AvailableCapabilities,
    CapabilityDecision,
    CapabilityPolicy,
    DeclaredCapabilities,
    DigestString,
    EffectiveCapabilities,
    EffectiveCapabilityDecision,
    EngineCapabilities,
    PolicyDecisionSet,
    PolicyLayerVersion,
)
from .common import AdapterVersion, Slug
from .config import CapabilityName, EngineIdentity, ExecutionConfig

# Per-class UTF-8 budget (FR-9 ``execution_snapshot_max_bytes`` default). The
# limit applies to each of the five classes independently, never as a shared
# five-class aggregate. Composition passes the live settings value; this
# constant only pins the documented default so settings and contracts cannot
# drift apart silently.
SNAPSHOT_MAX_BYTES_DEFAULT = 65536

SNAPSHOT_COLUMNS: tuple[str, ...] = (
    "execution_config_snapshot",
    "declared_capabilities_snapshot",
    "available_capabilities_snapshot",
    "effective_capabilities_snapshot",
    "execution_policy_snapshot",
)


class ExecutionSnapshotError(Exception):
    """Fail-closed snapshot rejection carrying only a stable code and path.

    The message never contains scanned content: denylist rejections name the
    field path and category only, so the exception can surface in errors and
    logs without echoing a secret.
    """

    def __init__(self, code: str, path: tuple[str, ...] = ()) -> None:
        self.code = code
        self.path = tuple(path)
        super().__init__(f"{code}: {'.'.join(self.path)}" if self.path else code)


# --------------------------------------------------------------------------- #
# Recursive denylist (03 §5.2)                                                  #
# --------------------------------------------------------------------------- #

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")

# Single-word segments: a key whose normalized form *equals* or *contains as a
# word segment* one of these is denied, so ``id_token``, ``accessToken`` and
# ``X-API-KEY`` all land in the same net as the plain names.
_DENY_KEY_WORDS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "stderr",
    }
)
# Multi-word phrases are matched against the whole normalized key (and inside
# longer names) so ``access_token_backup`` is denied while ordinary schema
# names such as ``provider_version`` are not.
_DENY_KEY_PHRASES = frozenset(
    {
        "access_token",
        "refresh_token",
        "api_key",
        "private_key",
        "connection_string",
        "customer_memory",
        "summary_message",
        "raw_memory",
        "host_path",
        "workdir_path",
    }
)

_CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Prefixed credential material (sk-..., ghp_..., xox..., bearer-style
    # provider tokens) with a body long enough to be usable.
    re.compile(
        r"(?:^|[^0-9A-Za-z])(?:sk|ghp|gso|gtf|xox[a-z]?|glpat|ya29|AIza)[-_/][0-9A-Za-z_.\-]{6,}"
    ),
    re.compile(r"(?i)\bbearer\s+[0-9A-Za-z._\-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    # URL/connection strings that embed a password in the authority.
    re.compile(r"[0-9A-Za-z+.\-]+://[^/\s:]+:[^/\s@]+@"),
)
_HOST_PATH_PATTERN = re.compile(r"^(?:/|\./|\.\./|~/|[A-Za-z]:[\\/])")


def _normalized_key(key: str) -> tuple[str, frozenset[str]]:
    # Split camelCase before lowering, otherwise ``accessToken`` would fold
    # into ``accesstoken`` and slip past the ``access_token`` phrase deny.
    normalized = _NON_ALNUM.sub("_", _CAMEL_BOUNDARY.sub("_", key).lower()).strip("_")
    return normalized, frozenset(normalized.split("_"))


def _key_is_denied(key: str) -> bool:
    normalized, segments = _normalized_key(key)
    if not normalized:
        return False
    if bool(segments & _DENY_KEY_WORDS):
        return True
    return any(phrase in normalized for phrase in _DENY_KEY_PHRASES)


def _value_is_denied(value: str) -> str | None:
    for pattern in _CREDENTIAL_PATTERNS:
        if pattern.search(value):
            return "snapshot_denied_credential_value"
    if _HOST_PATH_PATTERN.match(value):
        return "snapshot_denied_host_path"
    return None


def assert_snapshot_payload_clean(payload: object, path: tuple[str, ...] = ()) -> None:
    """Recursively reject denied keys and value shapes at any depth.

    Typed values produced by the strict DTOs (``UUID``, ``datetime``) pass
    through; anything outside the JSON container/scalar vocabulary is a
    serialization failure, so a smuggled object can never reach the database.
    """

    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key)
            child = (*path, key_text)
            if _key_is_denied(key_text):
                raise ExecutionSnapshotError("snapshot_denied_field_name", child) from None
            assert_snapshot_payload_clean(value, child)
        return
    if isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            assert_snapshot_payload_clean(item, (*path, str(index)))
        return
    if isinstance(payload, (UUID, datetime)):
        return
    if isinstance(payload, str):
        code = _value_is_denied(payload)
        if code is not None:
            raise ExecutionSnapshotError(code, path) from None
        return
    if payload is None or isinstance(payload, (bool, int, float)):
        return
    raise ExecutionSnapshotError("snapshot_not_serializable", path) from None


# --------------------------------------------------------------------------- #
# Shared DTO pieces                                                             #
# --------------------------------------------------------------------------- #


def _require_order(names: tuple[str, ...], expected: tuple[str, ...], label: str) -> None:
    if names != expected:
        raise ValueError(f"{label} must cover every entry exactly once in canonical order")


def _require_aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


class _SnapshotModel(ExecutionContractModel):
    """Common startup identity for every snapshot class (R-9)."""

    schema_version: Literal["v1"] = "v1"
    execution_id: UUID


class ExecutionConfigSnapshot(_SnapshotModel):
    """Canonical configuration, Agent version, Engine triple, and provider identity."""

    agent_id: UUID | None = None
    agent_version: int | None = Field(default=None, ge=1)
    engine: EngineIdentity
    config: ExecutionConfig
    provider_id: Slug
    provider_version: AdapterVersion


class DeclaredCapabilitiesSnapshot(_SnapshotModel):
    """Registry-declared capabilities exactly as registered; never client input."""

    engine: EngineIdentity
    declaration_schema_version: AdapterVersion
    declaration_digest: DigestString
    capabilities: EngineCapabilities


class AvailableCapabilitiesSnapshot(_SnapshotModel):
    """Sanitized deployment observation including workspace narrowing."""

    engine: EngineIdentity
    probe_id: Slug
    probe_version: AdapterVersion
    observed_at: datetime
    declaration_digest: DigestString
    deployment_digest: DigestString
    items: tuple[CapabilityDecision, ...]

    @field_validator("observed_at")
    @classmethod
    def observed_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "observed_at")

    @model_validator(mode="after")
    def items_are_complete(self) -> Self:
        _require_order(
            tuple(item.name for item in self.items), CAPABILITY_ORDER, "Snapshot availability items"
        )
        return self


class ExecutionPolicySnapshot(_SnapshotModel):
    """Trusted policy decisions with provenance and narrowing digests (03 §5.1)."""

    engine: EngineIdentity
    policy_provider_id: Slug
    policy_version: AdapterVersion
    policy_revision: int = Field(ge=0)
    resolved_at: datetime
    layer_versions: tuple[PolicyLayerVersion, ...]
    decisions: tuple[CapabilityPolicy, ...]
    disabled_capabilities_digest: DigestString
    execution_restriction_digest: DigestString

    @field_validator("resolved_at")
    @classmethod
    def resolved_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "resolved_at")

    @model_validator(mode="after")
    def coverage_is_complete(self) -> Self:
        _require_order(
            tuple(entry.layer for entry in self.layer_versions),
            ("platform", "tenant", "agent", "execution"),
            "Snapshot policy layers",
        )
        _require_order(
            tuple(decision.name for decision in self.decisions),
            CAPABILITY_ORDER,
            "Snapshot policy decisions",
        )
        return self


class EffectiveCapabilitiesSnapshot(_SnapshotModel):
    """Final narrowed capabilities with resolved version summaries."""

    engine: EngineIdentity
    tenant_id: str = Field(min_length=1, max_length=200)
    declaration_digest: DigestString
    probe_id: Slug
    probe_version: AdapterVersion
    policy_provider_id: Slug
    policy_version: AdapterVersion
    policy_revision: int = Field(ge=0)
    items: tuple[EffectiveCapabilityDecision, ...]
    required_capabilities_missing: tuple[CapabilityName, ...] = ()

    @model_validator(mode="after")
    def items_are_complete(self) -> Self:
        _require_order(
            tuple(item.name for item in self.items), CAPABILITY_ORDER, "Snapshot effective items"
        )
        false_names = {item.name for item in self.items if not item.effective}
        if len(set(self.required_capabilities_missing)) != len(self.required_capabilities_missing):
            raise ValueError("Snapshot required capability names must be unique")
        if not set(self.required_capabilities_missing) <= false_names:
            raise ValueError("Snapshot required capability entries must be ineffective")
        return self


SnapshotModel = (
    ExecutionConfigSnapshot
    | DeclaredCapabilitiesSnapshot
    | AvailableCapabilitiesSnapshot
    | ExecutionPolicySnapshot
    | EffectiveCapabilitiesSnapshot
)

_COLUMN_TYPES: dict[str, type[ExecutionContractModel]] = {
    "execution_config_snapshot": ExecutionConfigSnapshot,
    "declared_capabilities_snapshot": DeclaredCapabilitiesSnapshot,
    "available_capabilities_snapshot": AvailableCapabilitiesSnapshot,
    "effective_capabilities_snapshot": EffectiveCapabilitiesSnapshot,
    "execution_policy_snapshot": ExecutionPolicySnapshot,
}
_TYPE_NAMES = tuple(_COLUMN_TYPES.values())


# --------------------------------------------------------------------------- #
# Builders from typed sources                                                   #
# --------------------------------------------------------------------------- #


def _snapshot(dto_type: type, **values: object) -> object:
    try:
        return dto_type(**values)
    except ValidationError:
        raise ExecutionSnapshotError("snapshot_field_invalid", (dto_type.__name__,)) from None


def build_execution_config_snapshot(
    *,
    execution_id: UUID,
    config: ExecutionConfig,
    agent_id: UUID | None,
    agent_version: int | None,
    provider_id: str,
    provider_version: str,
) -> ExecutionConfigSnapshot:
    """Pin the canonical execution config with the startup identity."""

    if not isinstance(config, ExecutionConfig):
        raise ExecutionSnapshotError("snapshot_field_invalid", ("config",)) from None
    if not isinstance(execution_id, UUID):
        raise ExecutionSnapshotError("snapshot_field_invalid", ("execution_id",)) from None
    snapshot = _snapshot(
        ExecutionConfigSnapshot,
        execution_id=execution_id,
        agent_id=agent_id,
        agent_version=agent_version,
        engine=config.engine,
        config=config,
        provider_id=provider_id,
        provider_version=provider_version,
    )
    assert isinstance(snapshot, ExecutionConfigSnapshot)
    return snapshot


def _declared_snapshot_from(
    execution_id: UUID, declared: DeclaredCapabilities
) -> DeclaredCapabilitiesSnapshot:
    """Convert one registry-declared layer (already identity-checked upstream)."""

    if not isinstance(declared, DeclaredCapabilities):
        raise ExecutionSnapshotError("snapshot_field_invalid", ("declared",)) from None
    snapshot = _snapshot(
        DeclaredCapabilitiesSnapshot,
        execution_id=execution_id,
        engine=EngineIdentity(
            engine_id=declared.engine_id,
            protocol_id=declared.protocol_id,
            adapter_version=declared.adapter_version,
        ),
        declaration_schema_version=declared.declaration_schema_version,
        declaration_digest=declared.declaration_digest,
        capabilities=declared.capabilities,
    )
    assert isinstance(snapshot, DeclaredCapabilitiesSnapshot)
    return snapshot


def _available_snapshot_from(
    execution_id: UUID, available: AvailableCapabilities
) -> AvailableCapabilitiesSnapshot:
    if not isinstance(available, AvailableCapabilities):
        raise ExecutionSnapshotError("snapshot_field_invalid", ("available",)) from None
    snapshot = _snapshot(
        AvailableCapabilitiesSnapshot,
        execution_id=execution_id,
        engine=EngineIdentity(
            engine_id=available.engine_id,
            protocol_id=available.protocol_id,
            adapter_version=available.adapter_version,
        ),
        probe_id=available.probe_id,
        probe_version=available.probe_version,
        observed_at=available.observed_at,
        declaration_digest=available.declaration_digest,
        deployment_digest=available.deployment_digest,
        items=available.items,
    )
    assert isinstance(snapshot, AvailableCapabilitiesSnapshot)
    return snapshot


def _policy_snapshot_from(
    execution_id: UUID,
    engine: EngineIdentity,
    policy: PolicyDecisionSet,
    *,
    disabled_capabilities_digest: str,
    execution_restriction_digest: str,
) -> ExecutionPolicySnapshot:
    if not isinstance(policy, PolicyDecisionSet):
        raise ExecutionSnapshotError("snapshot_field_invalid", ("policy",)) from None
    snapshot = _snapshot(
        ExecutionPolicySnapshot,
        execution_id=execution_id,
        engine=engine,
        policy_provider_id=policy.policy_provider_id,
        policy_version=policy.policy_version,
        policy_revision=policy.policy_revision,
        resolved_at=policy.resolved_at,
        layer_versions=policy.layer_versions,
        decisions=policy.decisions,
        disabled_capabilities_digest=disabled_capabilities_digest,
        execution_restriction_digest=execution_restriction_digest,
    )
    assert isinstance(snapshot, ExecutionPolicySnapshot)
    return snapshot


def _effective_snapshot_from(
    execution_id: UUID, effective: EffectiveCapabilities
) -> EffectiveCapabilitiesSnapshot:
    if not isinstance(effective, EffectiveCapabilities):
        raise ExecutionSnapshotError("snapshot_field_invalid", ("effective",)) from None
    snapshot = _snapshot(
        EffectiveCapabilitiesSnapshot,
        execution_id=execution_id,
        engine=EngineIdentity(
            engine_id=effective.engine_id,
            protocol_id=effective.protocol_id,
            adapter_version=effective.adapter_version,
        ),
        tenant_id=effective.tenant_id,
        declaration_digest=effective.declaration_digest,
        probe_id=effective.probe_id,
        probe_version=effective.probe_version,
        policy_provider_id=effective.policy_provider_id,
        policy_version=effective.policy_version,
        policy_revision=effective.policy_revision,
        items=effective.items,
        required_capabilities_missing=effective.required_capabilities_missing,
    )
    assert isinstance(snapshot, EffectiveCapabilitiesSnapshot)
    return snapshot


# --------------------------------------------------------------------------- #
# Canonical serialization, size budget, and read-only replay                    #
# --------------------------------------------------------------------------- #


def _json_default(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise TypeError("datetime values must be timezone-aware")
        return value.isoformat()
    raise TypeError("snapshot value is not JSON-compatible")


def _canonical_text(value: object) -> str:
    """The one canonical JSON encoding used by both write and replay sides.

    Sharing a single implementation is what makes ``serialize_snapshot`` and
    ``deserialize_execution_snapshots`` agree byte for byte; the encoding is
    pure (``sort_keys``, fixed separators, no NaN), so identical semantics
    always produce identical text.
    """

    return json.dumps(
        value,
        default=_json_default,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def serialize_snapshot(
    snapshot: SnapshotModel, *, max_bytes: int = SNAPSHOT_MAX_BYTES_DEFAULT
) -> str:
    """Return the canonical JSON bytes for one snapshot or fail closed.

    Key order is fixed by ``sort_keys``, numbers never include NaN/Infinity,
    and datetimes must be timezone-aware, so repeated serialization of equal
    DTOs is byte-identical (P3-UT-15). The size budget is enforced per class.

    The canonical text is re-validated through the strict DTO before it is
    returned (D-5): frozen DTOs can still be edited with
    ``model_copy(update=...)``, which skips every pydantic validator, and a
    snapshot that violates its own completeness invariant would otherwise reach
    the database and later replay as authorization. Re-validation reads the
    exact bytes that were just produced, so it cannot change them — the
    byte-for-byte stability asserted by P3-UT-15 is preserved (the validated DTO
    equals the input DTO whenever the input was already consistent).
    """

    if not isinstance(snapshot, _TYPE_NAMES):
        raise ExecutionSnapshotError("snapshot_field_invalid", ("snapshot",)) from None
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 1:
        raise ExecutionSnapshotError("snapshot_invalid_limit") from None
    try:
        payload = snapshot.model_dump(mode="python", warnings=False)
    except (TypeError, ValueError):
        raise ExecutionSnapshotError(
            "snapshot_not_serializable", (type(snapshot).__name__,)
        ) from None
    assert_snapshot_payload_clean(payload)
    try:
        canonical = _canonical_text(payload)
    except (TypeError, ValueError):
        raise ExecutionSnapshotError(
            "snapshot_not_serializable", (type(snapshot).__name__,)
        ) from None
    try:
        type(snapshot).model_validate_json(canonical)
    except ValidationError:
        raise ExecutionSnapshotError("snapshot_field_invalid", (type(snapshot).__name__,)) from None
    except (TypeError, ValueError):
        raise ExecutionSnapshotError(
            "snapshot_not_serializable", (type(snapshot).__name__,)
        ) from None
    if len(canonical.encode("utf-8")) > max_bytes:
        raise ExecutionSnapshotError("snapshot_size_exceeded", (type(snapshot).__name__,))
    return canonical


@dataclass(frozen=True, slots=True)
class SerializedExecutionSnapshots:
    """The five canonical payloads keyed by their ``runtime_runs`` columns."""

    execution_id: UUID
    payloads: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class DeserializedExecutionSnapshots:
    """Rehydrated snapshot DTOs for read-only decision replay."""

    config: ExecutionConfigSnapshot
    declared: DeclaredCapabilitiesSnapshot
    available: AvailableCapabilitiesSnapshot
    effective: EffectiveCapabilitiesSnapshot
    policy: ExecutionPolicySnapshot

    @property
    def execution_id(self) -> UUID:
        return self.config.execution_id


def serialize_execution_snapshots(
    *,
    config: ExecutionConfigSnapshot,
    declared: DeclaredCapabilitiesSnapshot,
    available: AvailableCapabilitiesSnapshot,
    policy: ExecutionPolicySnapshot,
    effective: EffectiveCapabilitiesSnapshot,
    max_bytes: int = SNAPSHOT_MAX_BYTES_DEFAULT,
) -> SerializedExecutionSnapshots:
    """Serialize all five snapshots under one startup identity or fail closed."""

    snapshots = {
        "execution_config_snapshot": config,
        "declared_capabilities_snapshot": declared,
        "available_capabilities_snapshot": available,
        "effective_capabilities_snapshot": effective,
        "execution_policy_snapshot": policy,
    }
    for column, snapshot in snapshots.items():
        if not isinstance(snapshot, _COLUMN_TYPES[column]):
            raise ExecutionSnapshotError("snapshot_field_invalid", (column,)) from None
    identities = {snapshot.execution_id for snapshot in snapshots.values()}
    if len(identities) != 1:
        raise ExecutionSnapshotError("snapshot_identity_mismatch") from None
    payloads = {
        column: serialize_snapshot(snapshot, max_bytes=max_bytes)
        for column, snapshot in snapshots.items()
    }
    return SerializedExecutionSnapshots(
        execution_id=config.execution_id, payloads=MappingProxyType(payloads)
    )


SnapshotPayload = str | Mapping[str, object]
"""One stored snapshot column: canonical JSON text, or a decoded JSON object.

``RunRepository.get`` hands back asyncpg-decoded ``jsonb`` (a ``dict``), while
the serializer produces text, so the replay entry point accepts both shapes
rather than making every audit tool re-encode first.
"""


def _payload_body(column: str, payload: object) -> dict[str, object]:
    """Coerce one stored column into a JSON object body or fail with a precise code."""

    if payload is None:
        raise ExecutionSnapshotError("snapshot_payload_missing", (column,)) from None
    if isinstance(payload, str):
        try:
            body = json.loads(payload)
        except ValueError:
            raise ExecutionSnapshotError("snapshot_field_invalid", (column,)) from None
    elif isinstance(payload, Mapping):
        body = dict(payload)
    else:
        raise ExecutionSnapshotError("snapshot_payload_type_invalid", (column,)) from None
    if not isinstance(body, dict):
        raise ExecutionSnapshotError("snapshot_payload_type_invalid", (column,)) from None
    return body


def deserialize_execution_snapshots(
    payloads: Mapping[str, SnapshotPayload | None],
) -> DeserializedExecutionSnapshots:
    """Parse stored payloads back into snapshot DTOs without touching anything.

    Read-only decision replay (P3-UT-15): parsing re-runs the denylist and the
    strict schema, re-serializes canonically, and never mutates or re-observes
    any capability layer, adapter, or engine. Accepted values are canonical
    JSON text or the decoded ``dict`` a ``jsonb`` column comes back as, so a
    row read straight from the repository replays without re-encoding.

    What this guard promises, and what it does not (D-1):

    * every payload is strictly re-validated against the frozen DTO
      (``extra="forbid"``, version literal, complete capability coverage), so a
      missing field, an illegal enum, or an injected key fails closed with
      ``snapshot_field_invalid``;
    * the re-validated DTO must reproduce the same canonical text as the stored
      body, which catches any semantic edit (a truncated list, a flipped
      reason, a re-valued identity);
    * all five payloads must carry one and the same ``execution_id``.

    That is a *semantic* guarantee, not byte-level tamper evidence: PostgreSQL
    ``jsonb`` re-encodes stored text (key order, whitespace), so comparing the
    row against the serializer's bytes byte for byte would reject legitimate
    read-backs. A payload that is re-indented or key-reordered but semantically
    identical is therefore accepted **by design**, and rewriting a row while
    keeping it schema-valid is out of Phase 3 scope (P3-UT-15 only requires
    stable keys/versions/reasons, no snapshot mutation, no Engine call). Byte
    level audit integrity needs a checksum/chain column and is not claimed here.
    """

    if not isinstance(payloads, Mapping):
        raise ExecutionSnapshotError("snapshot_field_invalid", ("payloads",)) from None
    for column in payloads:
        if column not in _COLUMN_TYPES:
            raise ExecutionSnapshotError("snapshot_field_invalid", (str(column),)) from None
    parsed: dict[str, _SnapshotModel] = {}
    for column, dto_type in _COLUMN_TYPES.items():
        body = _payload_body(column, payloads.get(column))
        assert_snapshot_payload_clean(body, (column,))
        # One text form for both the strict parse and the semantic comparison.
        try:
            encoded = _canonical_text(body)
        except (TypeError, ValueError):
            raise ExecutionSnapshotError("snapshot_payload_type_invalid", (column,)) from None
        try:
            snapshot = dto_type.model_validate_json(encoded)
            canonical = _canonical_text(snapshot.model_dump(mode="python", warnings=False))
        except ValidationError:
            raise ExecutionSnapshotError("snapshot_field_invalid", (column,)) from None
        except (TypeError, ValueError):
            raise ExecutionSnapshotError("snapshot_not_serializable", (column,)) from None
        if canonical != encoded:
            # The stored semantics must already be what the strict DTO
            # re-produces; anything else is a tampered or truncated row and
            # never replays as authorization. The comparison is deliberately
            # on canonicalized forms, not on the raw stored bytes (D-1).
            raise ExecutionSnapshotError("snapshot_field_invalid", (column,)) from None
        parsed[column] = snapshot
    identities = {snapshot.execution_id for snapshot in parsed.values()}
    if len(identities) != 1:
        raise ExecutionSnapshotError("snapshot_identity_mismatch") from None
    return DeserializedExecutionSnapshots(
        config=parsed["execution_config_snapshot"],
        declared=parsed["declared_capabilities_snapshot"],
        available=parsed["available_capabilities_snapshot"],
        effective=parsed["effective_capabilities_snapshot"],
        policy=parsed["execution_policy_snapshot"],
    )
