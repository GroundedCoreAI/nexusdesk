"""Phase 3 T5: five strict snapshots, recursive denylist, write-once persistence.

Covers P3-UT-13..15, the Repository-level parts of P3-IT-06/07/08/18, and the
P3-CM-06 audit. The five DTOs are strict/frozen with a per-class UTF-8 size
budget, are recursively secret-scanned without ever echoing the rejected
value, serialize byte-stably, and are written to ``runtime_runs`` in one
conditional statement per startup identity. Historical NULL rows are never
backfilled, terminal updates never rewrite the columns, and no public view
exposes them.

The rework section (D-1..D-15 of the T5 test report) adds the assertions that
were previously missing or vacuous: replay semantics versus byte-level
tampering, the completion re-validation inside ``serialize_snapshot``, the
row-shaped read-back that T7 will actually replay, the per-class size budget
proof, the post-execution transaction-failure injection (rollback before
commit, equivalent to a lost commit for the barrier's atomicity claim), and
the categorical :class:`SnapshotWriteResult` the barrier returns instead of a
boolean.
"""

import asyncio
import inspect
import json
import logging
import os
import re
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from pathlib import Path
from typing import get_args
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, text
from test_agent_execution_phase3_capabilities import (
    FIXED,
    build_env,
    make_descriptor,
    make_request,
)

from agent_platform.applications.platform_runtime.runtime_hooks import (
    BusinessRuntimePersistenceHooks,
)
from agent_platform.core_platform.agent_execution.capability import (
    CacheLookup,
    CapabilityResolution,
)
from agent_platform.core_platform.agent_execution.capability.snapshots import (
    CapabilitySnapshotSet,
    build_available_capabilities_snapshot,
    build_capability_snapshots,
    build_declared_capabilities_snapshot,
    build_effective_capabilities_snapshot,
    build_execution_policy_snapshot,
)
from agent_platform.core_platform.agent_execution.contracts import (
    CAPABILITY_ORDER,
    NO_EXECUTION_RESTRICTIONS,
    AvailableCapabilities,
    CapabilityDecision,
    CapabilityPolicy,
    DeclaredCapabilities,
    EffectiveCapabilities,
    EffectiveCapabilityDecision,
    EngineCapabilities,
    EngineIdentity,
    ExecutionConfig,
    ExecutionContractModel,
    PolicyDecisionSet,
    PolicyLayerDecision,
    PolicyLayerVersion,
    ReactConfig,
    canonical_digest,
    disabled_capabilities_digest,
)
from agent_platform.core_platform.agent_execution.contracts.snapshots import (
    SNAPSHOT_COLUMNS,
    SNAPSHOT_MAX_BYTES_DEFAULT,
    AvailableCapabilitiesSnapshot,
    DeclaredCapabilitiesSnapshot,
    EffectiveCapabilitiesSnapshot,
    ExecutionConfigSnapshot,
    ExecutionPolicySnapshot,
    ExecutionSnapshotError,
    assert_snapshot_payload_clean,
    build_execution_config_snapshot,
    deserialize_execution_snapshots,
    serialize_execution_snapshots,
    serialize_snapshot,
)
from agent_platform.core_platform.agent_runtime.repository import RunRepository
from agent_platform.core_platform.agent_runtime.schemas import (
    SNAPSHOT_WRITE_OUTCOMES,
    ExecutionSnapshotPayloads,
    RunRequest,
    RunView,
    SnapshotWriteResult,
)
from agent_platform.core_platform.platform_services.persistence.database import create_engine
from agent_platform.core_platform.platform_services.platform_settings.settings import Settings

# Obviously fake placeholder secrets; never real credential material.
FAKE_API_KEY = "sk-" + "synthetic-fake-0000000000"
FAKE_BEARER = "Bearer synthetic-fake-" + "a" * 24
FAKE_HOST_PATH = "/home/deploy/.ssh/id_rsa"
FAKE_CONNECTION = "postgresql://svc:SyntheticFake%401@db.internal:5432/prod"
# Benign but recognizable marker used as a smuggled payload value; asserting it
# never surfaces in an error message proves the no-echo rule without relying on
# the credential-shape deny.
SMUGGLED_MARKER = "smuggled-marker-value"
ZERO64 = "0" * 64
DEPLOYMENT_DIGEST = "d" * 64
AGENT_ID = UUID("7b8f0000-0000-0000-0000-000000000001")
REACT_DECLARED = EngineCapabilities(
    streaming=True,
    cancellation=True,
    tool_calling=True,
    native_events=True,
)
LAYER_ORDER = ("platform", "tenant", "agent", "execution")
SNAPSHOT_DTO_TYPES = (
    ExecutionConfigSnapshot,
    DeclaredCapabilitiesSnapshot,
    AvailableCapabilitiesSnapshot,
    EffectiveCapabilitiesSnapshot,
    ExecutionPolicySnapshot,
)


def _snapshot_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to a migrated, dedicated PostgreSQL test database")
    return url


def _settings(url: str, tenant: str) -> Settings:
    return Settings(_env_file=None, database_url=url, tenant_id=tenant, embedded_worker=False)


def _repository(url: str, tenant: str) -> tuple[object, RunRepository]:
    engine = create_engine(_settings(url, tenant))
    return engine, RunRepository(engine, BusinessRuntimePersistenceHooks())


async def _cleanup(engine, tenant: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "DELETE FROM runtime_events WHERE run_id IN "
                "(SELECT id FROM runtime_runs WHERE tenant_id=:tenant)"
            ),
            {"tenant": tenant},
        )
        await conn.execute(
            text("DELETE FROM runtime_runs WHERE tenant_id=:tenant"), {"tenant": tenant}
        )
        await conn.execute(
            text("DELETE FROM runtime_conversations WHERE tenant_id=:tenant"), {"tenant": tenant}
        )
    await engine.dispose()


async def _claimed_run(repo: RunRepository, tenant: str) -> dict:
    row = await repo.submit(
        tenant,
        RunRequest(conversation_id="snap-" + uuid4().hex[:8], message="snapshot barrier"),
        {"fingerprint": "phase3-t5"},
        10000,
        100,
        120,
    )
    owner = uuid4()
    claimed = await repo.claim(owner, 120, tenant)
    assert claimed is not None and claimed["id"] == row["id"]
    return {"row": row, "owner": owner}


# ---------------------------------------------------------------------------
# Deterministic resolution fixtures
# ---------------------------------------------------------------------------


def make_policy_set(revision: int = 7) -> PolicyDecisionSet:
    return PolicyDecisionSet(
        policy_provider_id="react-policy",
        policy_version="v1",
        policy_revision=revision,
        resolved_at=FIXED,
        layer_versions=tuple(
            PolicyLayerVersion(layer=layer, version="v1", revision=1) for layer in LAYER_ORDER
        ),
        decisions=tuple(
            CapabilityPolicy(
                name=name,
                layers=tuple(
                    PolicyLayerDecision(
                        layer=layer,
                        allowed=True,
                        source="trusted-source",
                        reason_code="allowed",
                    )
                    for layer in LAYER_ORDER
                ),
            )
            for name in CAPABILITY_ORDER
        ),
    )


def make_resolution(*, execution_tenant: str = "tenant-a") -> CapabilityResolution:
    """Hand-built resolution mirroring exactly what T4 emits (narrowed views)."""
    declared = DeclaredCapabilities(
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        declaration_schema_version="v1",
        declaration_digest=canonical_digest(REACT_DECLARED),
        capabilities=REACT_DECLARED,
    )
    available_items = []
    effective_items = []
    for name in CAPABILITY_ORDER:
        is_declared = bool(getattr(REACT_DECLARED, name))
        if not is_declared:
            available_items.append(
                CapabilityDecision(name=name, available=False, reason_code="not_declared")
            )
            effective_items.append(
                EffectiveCapabilityDecision(name=name, effective=False, reason_code="not_declared")
            )
        else:
            available_items.append(
                CapabilityDecision(name=name, available=True, reason_code="allowed")
            )
            effective_items.append(
                EffectiveCapabilityDecision(name=name, effective=True, reason_code="allowed")
            )
    available = AvailableCapabilities(
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        probe_id="react-probe",
        probe_version="v1",
        observed_at=FIXED,
        declaration_digest=canonical_digest(REACT_DECLARED),
        deployment_digest=DEPLOYMENT_DIGEST,
        items=tuple(available_items),
    )
    effective = EffectiveCapabilities(
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        tenant_id=execution_tenant,
        declaration_digest=canonical_digest(REACT_DECLARED),
        probe_id="react-probe",
        probe_version="v1",
        policy_provider_id="react-policy",
        policy_version="v1",
        policy_revision=7,
        items=tuple(effective_items),
    )
    resolution = CapabilityResolution(
        declared=declared,
        available=available,
        policy=make_policy_set(),
        effective=effective,
        availability_status="fresh",
        policy_status="fresh",
    )
    return resolution


def make_config_snapshot(execution_id: UUID | None = None) -> ExecutionConfigSnapshot:
    return build_execution_config_snapshot(
        execution_id=execution_id or uuid4(),
        agent_id=AGENT_ID,
        agent_version=3,
        config=ExecutionConfig(),
        provider_id="react-native",
        provider_version="v1",
    )


def make_snapshot_set(
    execution_id: UUID,
) -> tuple[ExecutionConfigSnapshot, CapabilitySnapshotSet]:
    resolution = make_resolution()
    config = make_config_snapshot(execution_id)
    capabilities = build_capability_snapshots(
        execution_id,
        resolution,
        disabled_capabilities_digest=disabled_capabilities_digest(()),
        execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
    )
    return config, capabilities


def make_payloads(execution_id: UUID) -> ExecutionSnapshotPayloads:
    config, caps = make_snapshot_set(execution_id)
    serialized = serialize_execution_snapshots(
        config=config,
        declared=caps.declared,
        available=caps.available,
        policy=caps.policy,
        effective=caps.effective,
    )
    return ExecutionSnapshotPayloads(
        execution_id=execution_id,
        **serialized.payloads,
    )


# ---------------------------------------------------------------------------
# DTO shape and startup identity (R-9: identity inside the DTO, no sixth column)
# ---------------------------------------------------------------------------


def test_five_snapshot_dtos_are_strict_frozen_and_carry_execution_id():
    assert set(SNAPSHOT_COLUMNS) == {
        "execution_config_snapshot",
        "declared_capabilities_snapshot",
        "available_capabilities_snapshot",
        "effective_capabilities_snapshot",
        "execution_policy_snapshot",
    }
    assert len(SNAPSHOT_COLUMNS) == 5
    for dto in SNAPSHOT_DTO_TYPES:
        fields = dto.model_fields
        assert "execution_id" in fields, dto
        assert "schema_version" in fields, dto
        assert get_args(fields["schema_version"].annotation) == ("v1",), dto
        assert dto.model_config["extra"] == "forbid", dto
        assert dto.model_config["frozen"] is True, dto
        assert issubclass(dto, ExecutionContractModel), dto

    execution_id = uuid4()
    snapshot = make_config_snapshot(execution_id)
    assert snapshot.execution_id == execution_id
    with pytest.raises(ValidationError):
        snapshot.execution_id = uuid4()  # type: ignore[misc]
    with pytest.raises(ValidationError):
        ExecutionConfigSnapshot.model_validate_json(
            json.dumps(
                {
                    **snapshot.model_dump(mode="json"),
                    "extra_field": "x",
                }
            )
        )


def test_execution_config_snapshot_pins_identity_engine_config_and_provider():
    execution_id = uuid4()
    config = ExecutionConfig.model_validate(
        {"engine": {"engine_id": "react", "protocol_id": "native", "adapter_version": "v1"}}
    )
    snapshot = build_execution_config_snapshot(
        execution_id=execution_id,
        agent_id=AGENT_ID,
        agent_version=3,
        config=config,
        provider_id="react-native",
        provider_version="v1",
    )
    assert snapshot.execution_id == execution_id
    assert snapshot.agent_id == AGENT_ID
    assert snapshot.agent_version == 3
    assert snapshot.engine == config.engine
    assert snapshot.config == config
    assert snapshot.provider_id == "react-native"
    assert snapshot.provider_version == "v1"


def test_builders_reject_naive_datetimes():
    resolution = make_resolution()
    naive = resolution.available.model_copy(update={"observed_at": datetime(2026, 11, 12)})  # noqa: DTZ001
    narrowed = CapabilityResolution(
        declared=resolution.declared,
        available=naive,
        policy=resolution.policy,
        effective=resolution.effective,
        availability_status="fresh",
        policy_status="fresh",
    )
    with pytest.raises(ExecutionSnapshotError) as exc:
        build_available_capabilities_snapshot(uuid4(), narrowed)
    assert exc.value.code == "snapshot_field_invalid"


# ---------------------------------------------------------------------------
# P3-UT-13  missing fields / non-serializable / per-class size limits
# ---------------------------------------------------------------------------


def test_snapshot_size_limit_default_matches_settings():
    assert SNAPSHOT_MAX_BYTES_DEFAULT == 65536
    defaults = _settings("postgresql+asyncpg://x:y@127.0.0.1:1/db", "t")
    assert defaults.execution_snapshot_max_bytes == SNAPSHOT_MAX_BYTES_DEFAULT


def test_p3_ut13_single_class_limit_is_per_snapshot_not_shared():
    """D-4: decisive shape for the per-class budget.

    The old version wrapped ``serialize_snapshot`` in try/except without an
    ``else`` branch, and only compared ``total > budget`` for an arbitrary
    mid-range budget — a shared five-class implementation passed that test
    unchanged (verified by temporarily replacing the per-class check with an
    aggregate one: the old assertions stayed green). Budgeting the *largest*
    single class is what separates the two readings: a per-class gate must
    accept the whole five-tuple at that size, while the sum of the five
    payloads is strictly larger, so a shared gate would have rejected it.
    """

    config, caps = make_snapshot_set(uuid4())
    serialized = serialize_execution_snapshots(
        config=config,
        declared=caps.declared,
        available=caps.available,
        policy=caps.policy,
        effective=caps.effective,
    )
    lengths = {name: len(payload.encode("utf-8")) for name, payload in serialized.payloads.items()}
    total = sum(lengths.values())
    budget = max(lengths.values())
    assert total > budget and len(lengths) == 5  # the two gates differ at all

    # The largest class alone fits, therefore every class fits.
    whole = serialize_execution_snapshots(
        config=config,
        declared=caps.declared,
        available=caps.available,
        policy=caps.policy,
        effective=caps.effective,
        max_bytes=budget,
    )
    assert {name: len(payload.encode("utf-8")) for name, payload in whole.payloads.items()} == (
        lengths
    )
    assert sum(len(payload.encode("utf-8")) for payload in whole.payloads.values()) > budget

    # One byte below the largest class: only that class may be rejected, and it
    # must be rejected (no silent pass, no try/except that swallows the case).
    tight = budget - 1
    dtos = {
        "execution_config_snapshot": config,
        "declared_capabilities_snapshot": caps.declared,
        "available_capabilities_snapshot": caps.available,
        "effective_capabilities_snapshot": caps.effective,
        "execution_policy_snapshot": caps.policy,
    }
    biggest_name = max(lengths, key=lambda name: lengths[name])
    assert lengths[biggest_name] == budget
    with pytest.raises(ExecutionSnapshotError) as exc:
        serialize_execution_snapshots(
            config=config,
            declared=caps.declared,
            available=caps.available,
            policy=caps.policy,
            effective=caps.effective,
            max_bytes=tight,
        )
    assert exc.value.code == "snapshot_size_exceeded"
    # The path names one over-budget class only: no payload content.
    over_budget = {type(dtos[name]).__name__ for name in dtos if lengths[name] > tight}
    assert exc.value.path[0] in over_budget
    assert len(over_budget) == 1 or max(lengths.values()) == min(
        lengths[name] for name in dtos if lengths[name] > tight
    )
    for name, dto in dtos.items():
        if lengths[name] == budget:
            with pytest.raises(ExecutionSnapshotError) as one:
                serialize_snapshot(dto, max_bytes=tight)
            assert one.value.code == "snapshot_size_exceeded"
        else:
            # A smaller class still passes the same tight budget: the gate is
            # per class, never an aggregate of the five.
            assert len(serialize_snapshot(dto, max_bytes=tight).encode("utf-8")) == lengths[name]
    assert set(serialized.payloads) == set(SNAPSHOT_COLUMNS)


def test_p3_ut13_serialization_failure_is_closed():
    snapshot = make_config_snapshot()
    corrupted = snapshot.model_copy(update={"agent_id": object()})
    with pytest.raises(ExecutionSnapshotError) as exc:
        serialize_snapshot(corrupted)
    assert exc.value.code == "snapshot_not_serializable"
    with pytest.raises(ExecutionSnapshotError):
        serialize_snapshot({"schema_version": "v1"})  # type: ignore[arg-type]
    with pytest.raises(ExecutionSnapshotError) as limit_exc:
        serialize_snapshot(snapshot, max_bytes=0)
    assert limit_exc.value.code == "snapshot_invalid_limit"


def test_p3_ut13_deserialize_rejects_missing_fields_and_versions():
    config, caps = make_snapshot_set(uuid4())
    serialized = serialize_execution_snapshots(
        config=config,
        declared=caps.declared,
        available=caps.available,
        policy=caps.policy,
        effective=caps.effective,
    )
    parsed = deserialize_execution_snapshots(serialized.payloads)
    assert parsed.execution_id == config.execution_id

    missing = dict(serialized.payloads)
    body = json.loads(missing["execution_config_snapshot"])
    del body["execution_id"]
    missing["execution_config_snapshot"] = json.dumps(body)
    with pytest.raises(ExecutionSnapshotError) as exc:
        deserialize_execution_snapshots(missing)
    assert exc.value.code == "snapshot_field_invalid"
    assert "execution_config_snapshot" in str(exc.value)

    wrong_version = dict(serialized.payloads)
    body = json.loads(wrong_version["declared_capabilities_snapshot"])
    body["schema_version"] = "v2"
    wrong_version["declared_capabilities_snapshot"] = json.dumps(body)
    with pytest.raises(ExecutionSnapshotError) as version_exc:
        deserialize_execution_snapshots(wrong_version)
    assert version_exc.value.code == "snapshot_field_invalid"

    unknown_column = dict(serialized.payloads)
    unknown_column["sixth_snapshot"] = "{}"
    with pytest.raises(ExecutionSnapshotError):
        deserialize_execution_snapshots(unknown_column)

    absent = dict(serialized.payloads)
    del absent["execution_policy_snapshot"]
    with pytest.raises(ExecutionSnapshotError) as absent_exc:
        deserialize_execution_snapshots(absent)
    assert absent_exc.value.code == "snapshot_payload_missing"


def test_serialize_enforces_one_startup_identity():
    shared = uuid4()
    config = make_config_snapshot(shared)
    caps = build_capability_snapshots(
        shared,
        make_resolution(),
        disabled_capabilities_digest=disabled_capabilities_digest(()),
        execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
    )
    divergent = caps.effective.model_copy(update={"execution_id": uuid4()})
    with pytest.raises(ExecutionSnapshotError) as exc:
        serialize_execution_snapshots(
            config=config,
            declared=caps.declared,
            available=caps.available,
            policy=caps.policy,
            effective=divergent,
        )
    assert exc.value.code == "snapshot_identity_mismatch"


# ---------------------------------------------------------------------------
# P3-UT-14  recursive denylist without echoing the rejected value
# ---------------------------------------------------------------------------

DENIED_KEY_SAMPLES = {
    "password": "hunter2",
    "passwd": "hunter2",
    "secret": "s",
    "token": "abc",
    "access_token": "abc",
    "refresh_token": "abc",
    "api_key": "abc",
    "apikey": "abc",
    "authorization": "Basic abc",
    "cookie": "session=1",
    "credential": "abc",
    "private_key": "abc",
    "connection_string": FAKE_CONNECTION,
    "customer_memory": "raw memory text",
    "summary_message": "raw summary text",
    "raw_memory": "raw memory text",
    "stderr": "traceback",
    "host_path": FAKE_HOST_PATH,
    "workdir_path": "/srv/work",
}


@pytest.mark.parametrize("key", sorted(DENIED_KEY_SAMPLES))
def test_p3_ut14_denylist_covers_every_planned_key_category(key: str):
    for carrier in (
        {"a": [{key: "v"}]},
        {"b": {"c": ({"nested": {key: "v"}},)}},
    ):
        with pytest.raises(ExecutionSnapshotError) as exc:
            assert_snapshot_payload_clean(carrier)
        assert exc.value.code == "snapshot_denied_field_name"
        assert key in exc.value.path[-1]


def test_p3_ut14_camel_case_and_separator_smuggling_is_normalized():
    for key in ("accessToken", "API-KEY", "X-Refresh-Token", "customerMemory", "hostPath"):
        with pytest.raises(ExecutionSnapshotError) as exc:
            assert_snapshot_payload_clean({"meta": [{key: "v"}]})
        assert exc.value.code == "snapshot_denied_field_name"


def test_p3_ut14_clean_schema_names_are_not_false_positives():
    config, caps = make_snapshot_set(uuid4())
    serialized = serialize_execution_snapshots(
        config=config,
        declared=caps.declared,
        available=caps.available,
        policy=caps.policy,
        effective=caps.effective,
    )
    for payload in serialized.payloads.values():
        assert_snapshot_payload_clean(json.loads(payload))
    assert_snapshot_payload_clean(
        {
            "workspace_id": "ws-1",
            "tokenizer_hint": "plain",
            "max_rounds": 6,
            "note": "the word token appears in prose but is not a key",
        }
    )


def test_p3_ut14_secret_shaped_values_rejected_at_any_depth_without_echo():
    for value, code in (
        (FAKE_API_KEY, "snapshot_denied_credential_value"),
        (FAKE_BEARER, "snapshot_denied_credential_value"),
        (FAKE_CONNECTION, "snapshot_denied_credential_value"),
        (FAKE_HOST_PATH, "snapshot_denied_host_path"),
        ("~/id_rsa", "snapshot_denied_host_path"),
        ("C:\\Users\\svc\\.ssh\\id_rsa", "snapshot_denied_host_path"),
    ):
        carrier = {"layers": [{"decisions": [{"deep": [value]}]}]}
        with pytest.raises(ExecutionSnapshotError) as exc:
            assert_snapshot_payload_clean(carrier)
        assert exc.value.code == code
        assert value not in str(exc.value)
        assert value not in repr(exc.value)
        assert FAKE_API_KEY not in str(exc.value)


def test_p3_ut14_snapshot_with_smuggled_secret_fails_before_write_and_stays_quiet(caplog):
    resolution = make_resolution(execution_tenant=FAKE_API_KEY)
    with pytest.raises(ExecutionSnapshotError) as exc:
        serialize_snapshot(build_effective_capabilities_snapshot(uuid4(), resolution))
    assert exc.value.code == "snapshot_denied_credential_value"
    assert FAKE_API_KEY not in str(exc.value)
    assert exc.value.path[-1] == "tenant_id"
    # No log record may carry the rejected value either.
    with caplog.at_level(logging.DEBUG):
        try:
            serialize_snapshot(build_effective_capabilities_snapshot(uuid4(), resolution))
        except ExecutionSnapshotError:
            pass
    assert FAKE_API_KEY not in caplog.text
    for record in caplog.records:
        assert FAKE_API_KEY not in record.getMessage()


# ---------------------------------------------------------------------------
# P3-UT-15  canonical stability and read-only replay
# ---------------------------------------------------------------------------


def test_p3_ut15_repeated_serialization_is_byte_identical():
    execution_id = uuid4()
    first_config, first_caps = make_snapshot_set(execution_id)
    second_config, second_caps = make_snapshot_set(execution_id)
    assert first_config == second_config
    for left, right in (
        (first_caps.declared, second_caps.declared),
        (first_caps.available, second_caps.available),
        (first_caps.policy, second_caps.policy),
        (first_caps.effective, second_caps.effective),
    ):
        assert serialize_snapshot(left) == serialize_snapshot(right)
    payload = serialize_snapshot(first_caps.available)
    for _ in range(3):
        assert serialize_snapshot(first_caps.available) == payload
    body = json.loads(payload)
    assert payload == json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    for key in ("observed_at", "resolved_at"):
        for dto in (first_caps.available, first_caps.policy):
            dumped = dto.model_dump(mode="json")
            if key in dumped:
                assert re.search(r"[+-]\d{2}:\d{2}$|Z$", dumped[key]), dumped[key]


def test_p3_ut15_round_trip_reparse_is_stable():
    execution_id = uuid4()
    config, caps = make_snapshot_set(execution_id)
    serialized = serialize_execution_snapshots(
        config=config,
        declared=caps.declared,
        available=caps.available,
        policy=caps.policy,
        effective=caps.effective,
    )
    parsed = deserialize_execution_snapshots(serialized.payloads)
    again = serialize_execution_snapshots(
        config=parsed.config,
        declared=parsed.declared,
        available=parsed.available,
        policy=parsed.policy,
        effective=parsed.effective,
    )
    assert dict(again.payloads) == dict(serialized.payloads)
    assert parsed.available.observed_at == caps.available.observed_at


def test_p3_ut15_replay_touches_no_engine_and_does_not_mutate_snapshots():
    env = build_env(descriptors=(make_descriptor(),))

    async def scenario() -> tuple:
        assert await env.resolver.warm(env.request) is True
        resolution = await env.resolver.resolve(env.request)
        probe_calls, policy_calls = len(env.probe.calls), len(env.policy.calls)
        execution_id = uuid4()
        config = make_config_snapshot(execution_id)
        caps = build_capability_snapshots(
            execution_id,
            resolution,
            disabled_capabilities_digest=disabled_capabilities_digest(
                env.request.disabled_capabilities
            ),
            execution_restriction_digest=env.request.execution_restriction_digest,
        )
        payloads = dict(
            serialize_execution_snapshots(
                config=config,
                declared=caps.declared,
                available=caps.available,
                policy=caps.policy,
                effective=caps.effective,
            ).payloads
        )
        return payloads, resolution, (probe_calls, policy_calls)

    payloads, resolution, counters = asyncio.run(scenario())
    parsed = deserialize_execution_snapshots(payloads)
    # Read-only replay: every snapshot layer keeps the exact resolution content.
    assert parsed.effective.items == resolution.effective.items
    assert parsed.available.items == resolution.available.items
    assert parsed.available.observed_at == resolution.available.observed_at
    assert parsed.policy.decisions == resolution.policy.decisions
    assert parsed.declared.capabilities == resolution.declared.capabilities
    replay = serialize_execution_snapshots(
        config=parsed.config,
        declared=parsed.declared,
        available=parsed.available,
        policy=parsed.policy,
        effective=parsed.effective,
    )
    assert dict(replay.payloads) == payloads

    async def replay_only() -> None:
        for _ in range(2):
            await asyncio.sleep(0)

    asyncio.run(replay_only())
    assert (len(env.probe.calls), len(env.policy.calls)) == counters
    assert env.created == []  # no adapter/Engine instance was ever produced
    asyncio.run(env.resolver.aclose())


# ---------------------------------------------------------------------------
# T5 rework D-9  denylist branches that previously had no assertion
# ---------------------------------------------------------------------------

# Synthetic PEM/OpenSSH armors: shape-matching only, never real key material.
FAKE_PEM_RSA = "-----BEGIN RSA PRIVATE KEY-----\n" + "Q" * 40 + "\n-----END RSA PRIVATE KEY-----"
FAKE_PEM_OPENSSH = "-----BEGIN OPENSSH PRIVATE KEY-----\n" + "b3BlbnNzaC1rZXk" + "\n-----END"


@pytest.mark.parametrize("material", [FAKE_PEM_RSA, FAKE_PEM_OPENSSH])
def test_p3_ut14_private_key_value_shape_is_denied_under_a_benign_key_name(material: str):
    """D-9(a): the PEM branch of the value deny actually fires.

    The key name is deliberately neutral (``private_key`` would already be
    caught by the key deny), so this is the only assertion that covers the
    ``-----BEGIN ... PRIVATE KEY-----`` alternative in
    ``_CREDENTIAL_PATTERNS``.
    """

    carrier = {"layers": [{"decisions": [{"material": material}]}]}
    with pytest.raises(ExecutionSnapshotError) as exc:
        assert_snapshot_payload_clean(carrier)
    assert exc.value.code == "snapshot_denied_credential_value"
    assert exc.value.path == ("layers", "0", "decisions", "0", "material")
    assert "PRIVATE KEY" not in str(exc.value)


LEGAL_VALUE_SHAPES = [
    "local",
    "tenant-a",
    "another-tenant",
    "phase3-migration",
    "ws_1",
    "a.b.c.internal",
    "v1",
    "客户支持部",
    "profiles/prod",
    "https://engine.internal/native",
    "",
    "relative\\path\\segment",
]


def test_p3_ut14_legal_identifier_shapes_are_not_false_positives():
    """D-9(b): the host-path deny is a narrowing, not a blanket id reject.

    Real tenant ids in this repository are bare slugs (``local``,
    ``tenant-a``, ``phase3-migration``) and the module docstring states that
    *any* string value starting with a path separator is denied on purpose.
    These shapes must therefore keep passing.
    """

    for value in LEGAL_VALUE_SHAPES:
        assert_snapshot_payload_clean({"tenant_id": value, "nested": [{"note": value}]})


def test_p3_ut14_leading_separator_values_are_denied_by_design():
    """The narrowing is deliberate: every value that starts with a separator fails."""

    for value in ("/srv/work", "./run", "../etc/passwd", "~/id_rsa", "C:\\Users\\svc"):
        with pytest.raises(ExecutionSnapshotError) as exc:
            assert_snapshot_payload_clean({"note": value})
        assert exc.value.code == "snapshot_denied_host_path"
        assert value not in str(exc.value)


# ---------------------------------------------------------------------------
# T5 rework D-5  serialize_snapshot re-validates the completion invariants
# ---------------------------------------------------------------------------


def _completeness_bypass_cases(snapshot: object) -> list[tuple[str, object]]:
    """``model_copy(update=...)`` variants that bypass every pydantic validator."""

    cases: list[tuple[str, object]] = []
    items = getattr(snapshot, "items", None)
    if items is not None:
        cases.append(("missing_item", snapshot.model_copy(update={"items": items[:-1]})))
        cases.append(
            ("duplicated_item", snapshot.model_copy(update={"items": items + (items[0],)}))
        )
        cases.append(("reordered_items", snapshot.model_copy(update={"items": items[::-1]})))
        contradictory = tuple(
            item.model_copy(update={"available": not item.available})
            if hasattr(item, "available")
            else item.model_copy(update={"effective": not item.effective})
            for item in items
        )
        cases.append(
            (
                "reason_contradicts_flag",
                snapshot.model_copy(update={"items": contradictory}),
            )
        )
    decisions = getattr(snapshot, "decisions", None)
    if decisions is not None:
        cases.append(("missing_decision", snapshot.model_copy(update={"decisions": decisions[:5]})))
        layers = decisions[0].layers
        cases.append(
            (
                "missing_policy_layer",
                snapshot.model_copy(
                    update={
                        "decisions": (decisions[0].model_copy(update={"layers": layers[:3]}),)
                        + decisions[1:]
                    }
                ),
            )
        )
    missing_required = getattr(snapshot, "required_capabilities_missing", None)
    if missing_required is not None:
        # F-3: the default fixture keeps every declared capability effective,
        # so the stored tuple is empty and "duplicate an existing entry" would
        # be vacuous. Build a *valid* non-empty precondition first — one item
        # narrowed to ineffective with a stable denial reason and named as the
        # required-missing entry — and prove with a serialize pre-check that
        # the precondition passes every other invariant. The duplicate below
        # then violates the uniqueness check and nothing else.
        base = snapshot
        if len(missing_required) == 0:
            flipped = items[0].model_copy(
                update={"effective": False, "reason_code": "agent_disabled"}
            )
            base = snapshot.model_copy(
                update={
                    "items": (flipped, *items[1:]),
                    "required_capabilities_missing": (flipped.name,),
                }
            )
            serialize_snapshot(base)  # valid precondition or the fixture lies
        duplicated_name = base.required_capabilities_missing[0]
        cases.append(
            (
                "duplicated_required_name",
                base.model_copy(
                    update={"required_capabilities_missing": (duplicated_name, duplicated_name)}
                ),
            )
        )
        if len(missing_required) == 0:
            cases.append(
                (
                    "required_names_effective",
                    snapshot.model_copy(update={"required_capabilities_missing": ("streaming",)}),
                )
            )
    return cases


def test_p3_ut13_serialization_revalidates_the_dto_completion_invariants():
    """D-5: a hand-copied DTO that violates its own invariants never reaches bytes.

    ``model_copy(update=...)`` skips pydantic validation, so the builders'
    completeness guarantees must be re-checked inside ``serialize_snapshot``
    before any payload can be written and later replayed as authorization.
    """

    execution_id = uuid4()
    config, caps = make_snapshot_set(execution_id)
    variants = _bypass_variants(caps)
    assert len(variants) >= 8, "the bypass catalogue must cover the real invariants"
    for dto_name, label, mutated in variants:
        with pytest.raises(ExecutionSnapshotError) as exc:
            serialize_snapshot(mutated)
        assert exc.value.code == "snapshot_field_invalid", (dto_name, label)
        assert dto_name in exc.value.path, (dto_name, label)
    # The untouched set still serializes: the guard must not reject valid DTOs.
    for snapshot in (config, caps.declared, caps.available, caps.policy, caps.effective):
        serialize_snapshot(snapshot)


def _bypass_variants(caps) -> list[tuple[str, str, object]]:
    out: list[tuple[str, str, object]] = []
    for snapshot in (caps.available, caps.policy, caps.effective):
        for label, mutated in _completeness_bypass_cases(snapshot):
            out.append((type(snapshot).__name__, label, mutated))
    return out


def test_p3_ut15_revalidation_does_not_change_canonical_bytes():
    """The D-5 guard is a validator, not a re-serializer.

    P3-UT-15 pins byte-identical repeated serialization; re-validating the
    canonical text must not alter it (the DTO equality check below proves the
    round-trip is lossless, so stability is preserved, not weakened).
    """

    execution_id = uuid4()
    config, caps = make_snapshot_set(execution_id)
    for snapshot in (config, caps.declared, caps.available, caps.policy, caps.effective):
        payload = serialize_snapshot(snapshot)
        assert type(snapshot).model_validate_json(payload) == snapshot
        assert serialize_snapshot(snapshot) == payload


def test_p3_ut13_five_class_serialization_also_revalidates():
    config, caps = make_snapshot_set(uuid4())
    broken = caps.available.model_copy(update={"items": caps.available.items[:-1]})
    with pytest.raises(ExecutionSnapshotError) as exc:
        serialize_execution_snapshots(
            config=config,
            declared=caps.declared,
            available=broken,
            policy=caps.policy,
            effective=caps.effective,
        )
    assert exc.value.code == "snapshot_field_invalid"


# ---------------------------------------------------------------------------
# T5 rework D-1  what the replay guard does and does not promise
# ---------------------------------------------------------------------------


def test_p3_ut15_replay_rejects_payloads_with_divergent_startup_identity():
    """D-1(a): five individually valid payloads must still share one identity."""

    shared = uuid4()
    config, caps = make_snapshot_set(shared)
    payloads = dict(
        serialize_execution_snapshots(
            config=config,
            declared=caps.declared,
            available=caps.available,
            policy=caps.policy,
            effective=caps.effective,
        ).payloads
    )
    foreign = uuid4()
    payloads["execution_policy_snapshot"] = serialize_snapshot(
        build_execution_policy_snapshot(
            foreign,
            make_resolution(),
            disabled_capabilities_digest=disabled_capabilities_digest(()),
            execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
        )
    )
    with pytest.raises(ExecutionSnapshotError) as exc:
        deserialize_execution_snapshots(payloads)
    assert exc.value.code == "snapshot_identity_mismatch"
    assert str(foreign) not in str(exc.value)
    assert str(shared) not in str(exc.value)


def test_p3_ut15_replay_rejects_missing_illegal_and_unknown_fields_without_echo():
    """D-1(b): replay re-runs the strict schema, so edited rows fail closed."""

    execution_id = uuid4()
    config, caps = make_snapshot_set(execution_id)

    def _five() -> dict[str, str]:
        return dict(
            serialize_execution_snapshots(
                config=config,
                declared=caps.declared,
                available=caps.available,
                policy=caps.policy,
                effective=caps.effective,
            ).payloads
        )

    cases: list[tuple[str, str, dict[str, str]]] = []

    tampered = _five()
    body = json.loads(tampered["available_capabilities_snapshot"])
    del body["probe_id"]
    tampered["available_capabilities_snapshot"] = json.dumps(
        body, sort_keys=True, separators=(",", ":")
    )
    cases.append(("missing_required", "available_capabilities_snapshot", tampered))

    tampered = _five()
    body = json.loads(tampered["available_capabilities_snapshot"])
    body["items"][0]["reason_code"] = "obviously_not_a_reason"
    tampered["available_capabilities_snapshot"] = json.dumps(
        body, sort_keys=True, separators=(",", ":")
    )
    cases.append(("illegal_enum", "available_capabilities_snapshot", tampered))

    tampered = _five()
    body = json.loads(tampered["effective_capabilities_snapshot"])
    body["injected"] = SMUGGLED_MARKER
    tampered["effective_capabilities_snapshot"] = json.dumps(
        body, sort_keys=True, separators=(",", ":")
    )
    cases.append(("unknown_key", "effective_capabilities_snapshot", tampered))

    tampered = _five()
    body = json.loads(tampered["execution_config_snapshot"])
    body["engine"]["adapter_version"] = "v999-not-a-version"
    tampered["execution_config_snapshot"] = json.dumps(body, sort_keys=True, separators=(",", ":"))
    cases.append(("illegal_version", "execution_config_snapshot", tampered))

    for label, column, payloads in cases:
        with pytest.raises(ExecutionSnapshotError) as exc:
            deserialize_execution_snapshots(payloads)
        assert exc.value.code == "snapshot_field_invalid", label
        assert column in exc.value.path, label
        assert SMUGGLED_MARKER not in str(exc.value)
        assert "obviously_not_a_reason" not in str(exc.value)

    # A secret-shaped smuggled value is denied before the schema even sees it,
    # and the rejection still names only the path.
    tampered = _five()
    body = json.loads(tampered["execution_policy_snapshot"])
    body["layer_note"] = FAKE_API_KEY
    tampered["execution_policy_snapshot"] = json.dumps(body, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ExecutionSnapshotError) as secret_exc:
        deserialize_execution_snapshots(tampered)
    assert secret_exc.value.code == "snapshot_denied_credential_value"
    assert FAKE_API_KEY not in str(secret_exc.value)
    assert secret_exc.value.path[-1] == "layer_note"


def test_p3_ut15_replay_accepts_pretty_printed_but_semantically_equal_payloads():
    """D-1(c): the guard is documented as semantic, so this is intended behavior.

    PostgreSQL ``jsonb`` re-encodes stored text (key order, whitespace), so a
    byte-exact comparison would reject legitimate read-backs. Replay therefore
    performs a strict re-validation plus an identity check and compares the
    canonicalized forms: a re-indented payload with unchanged semantics is
    accepted, while any semantic edit is rejected by the tests above. Byte
    level tamper evidence is not a Phase 3 property.
    """

    execution_id = uuid4()
    config, caps = make_snapshot_set(execution_id)
    serialized = serialize_execution_snapshots(
        config=config,
        declared=caps.declared,
        available=caps.available,
        policy=caps.policy,
        effective=caps.effective,
    )
    pretty = {
        column: json.dumps(json.loads(payload), indent=2, sort_keys=True, ensure_ascii=False)
        for column, payload in serialized.payloads.items()
    }
    parsed = deserialize_execution_snapshots(pretty)
    assert parsed.execution_id == execution_id
    replay = serialize_execution_snapshots(
        config=parsed.config,
        declared=parsed.declared,
        available=parsed.available,
        policy=parsed.policy,
        effective=parsed.effective,
    )
    assert dict(replay.payloads) == dict(serialized.payloads)


# ---------------------------------------------------------------------------
# T5 rework D-6  the row that comes back from PostgreSQL is decoded, not text
# ---------------------------------------------------------------------------


def test_p3_ut15_replay_accepts_decoded_mapping_payloads_from_a_db_row():
    """``RunRepository.get`` yields ``dict`` values; replay must consume them.

    Before the rework a decoded row raised ``snapshot_payload_missing`` even
    though every value was present — a wiring trap for T7 and any audit tool.
    """

    execution_id = uuid4()
    config, caps = make_snapshot_set(execution_id)
    serialized = serialize_execution_snapshots(
        config=config,
        declared=caps.declared,
        available=caps.available,
        policy=caps.policy,
        effective=caps.effective,
    )
    row_view = {column: json.loads(payload) for column, payload in serialized.payloads.items()}
    parsed = deserialize_execution_snapshots(row_view)
    assert parsed.execution_id == execution_id
    assert parsed.available.items == caps.available.items

    # Missing (NULL) and wrong-typed values now carry different codes.
    nulls = dict(row_view)
    nulls["execution_policy_snapshot"] = None
    with pytest.raises(ExecutionSnapshotError) as missing_exc:
        deserialize_execution_snapshots(nulls)
    assert missing_exc.value.code == "snapshot_payload_missing"

    wrong_type = dict(row_view)
    wrong_type["execution_policy_snapshot"] = ["not", "an", "object"]
    with pytest.raises(ExecutionSnapshotError) as type_exc:
        deserialize_execution_snapshots(wrong_type)
    assert type_exc.value.code == "snapshot_payload_type_invalid"
    assert type_exc.value.path == ("execution_policy_snapshot",)

    broken_text = {"execution_config_snapshot": "{not json"}
    with pytest.raises(ExecutionSnapshotError) as parse_exc:
        deserialize_execution_snapshots({**row_view, **broken_text})
    assert parse_exc.value.code == "snapshot_field_invalid"


# ---------------------------------------------------------------------------
# T5 rework D-2  startup identity of the row, not of the caller's argument
# ---------------------------------------------------------------------------


@pytest.mark.postgres
def test_p3_it18_entry_guard_rejects_foreign_startup_identity_before_database():
    """D-2: the row's startup identity is the run id, not the caller's argument.

    ``ExecutionSnapshotPayloads.execution_id`` is only the guard parameter; the
    identity inside the snapshot payloads *is* this row's startup identity
    (R-9). Before the rework an all-NULL row accepted another run's
    ``execution_id`` and reported success, so a foreign audit trail could be
    parked on a live claim. Both the DTO parameter and the payload bodies are
    checked, the refusal is a distinct content-free outcome, and the write
    never reaches the database at all.

    F-4 evidence discipline: the listener counts *every* statement executed on
    the engine (``before_execute`` with no marker filter) and is registered
    before submit/claim, so "does not access the database" means zero SQL
    statements of any kind inside each guarded call — not merely zero
    snapshot-write statements. The window is measured by clearing the log
    immediately before each call and reading it immediately after; statements
    from submit/claim and from the read-back are outside the window by
    construction.
    """

    async def scenario() -> tuple:
        url = _snapshot_database_url()
        tenant = "p3-snap-guard-" + uuid4().hex[:12]
        engine, repo = _repository(url, tenant)
        observed: list[str] = []

        @event.listens_for(engine.sync_engine, "before_execute")
        def _observe(conn, clauseelement, multiparams, params, execution_options):
            observed.append(str(clauseelement))

        try:
            claimed = await _claimed_run(repo, tenant)
            run_id = claimed["row"]["id"]

            foreign = make_payloads(uuid4())
            observed.clear()
            guard_hit = await repo.write_execution_snapshots(run_id, claimed["owner"], foreign)
            during_guard = list(observed)

            # The guard parameter is honest, the payload bodies are not.
            bodies = make_payloads(run_id)
            forged_config, forged_caps = make_snapshot_set(uuid4())
            forged = replace(
                bodies,
                execution_config_snapshot=serialize_snapshot(forged_config),
                declared_capabilities_snapshot=serialize_snapshot(forged_caps.declared),
            )
            observed.clear()
            body_hit = await repo.write_execution_snapshots(run_id, claimed["owner"], forged)
            during_body = list(observed)
            stored = await _raw_snapshots(engine, run_id)
            return guard_hit, body_hit, during_guard, during_body, stored, run_id
        finally:
            await _cleanup(engine, tenant)

    guard_hit, body_hit, during_guard, during_body, stored, run_id = asyncio.run(scenario())
    assert guard_hit.outcome == "audit_conflict"
    assert body_hit.outcome == "audit_conflict"
    # Fail-closed *before* the database: no statement of any kind was executed.
    assert during_guard == []
    assert during_body == []
    assert all(stored[column] is None for column in SNAPSHOT_COLUMNS)
    # The refusal is content-free: nothing from the rejected payloads leaks out.
    assert str(run_id) not in str(guard_hit)
    assert repr(guard_hit) == "SnapshotWriteResult(outcome='audit_conflict')"


# ---------------------------------------------------------------------------
# T5 rework D-15  payload entry validation before CAST(... AS jsonb)
# ---------------------------------------------------------------------------


@pytest.mark.postgres
def test_p3_it08_write_entry_rejects_non_canonical_payload_strings():
    """T7 bypassing the serializer must get a domain error, not a DB error."""

    async def scenario(bad: object) -> tuple:
        url = _snapshot_database_url()
        tenant = "p3-snap-mal-" + uuid4().hex[:12]
        engine, repo = _repository(url, tenant)
        try:
            claimed = await _claimed_run(repo, tenant)
            run_id = claimed["row"]["id"]
            payloads = replace(make_payloads(run_id), execution_config_snapshot=bad)
            try:
                outcome = await repo.write_execution_snapshots(run_id, claimed["owner"], payloads)
                return ("returned", outcome, "", (), None)
            except ExecutionSnapshotError as exc:
                stored = await _raw_snapshots(engine, run_id)
                return ("raised", exc.code, str(exc), exc.path, stored)
        finally:
            await _cleanup(engine, tenant)

    for bad in ("", "{not json", '"just a string"', "[]", "null", FAKE_API_KEY):
        kind, code, message, path, stored = asyncio.run(scenario(bad))
        assert kind == "raised", (bad, kind)
        assert code == "snapshot_field_invalid", bad
        # Only the column name and the stable code may surface: no payload text.
        assert message == "snapshot_field_invalid: execution_config_snapshot"
        assert path == ("execution_config_snapshot",)
        assert all(stored[column] is None for column in SNAPSHOT_COLUMNS)

    # A non-string column is a type fault, reported apart from unparseable text.
    kind, code, message, path, stored = asyncio.run(scenario({"execution_id": "x"}))
    assert kind == "raised"
    assert code == "snapshot_payload_type_invalid"
    assert message == "snapshot_payload_type_invalid: execution_config_snapshot"
    assert all(stored[column] is None for column in SNAPSHOT_COLUMNS)


# ---------------------------------------------------------------------------
# R-22  capability snapshot builders accept only CapabilityResolution
# ---------------------------------------------------------------------------


def test_r22_builder_signatures_are_pinned_to_capability_resolution():
    builders = (
        build_declared_capabilities_snapshot,
        build_available_capabilities_snapshot,
        build_execution_policy_snapshot,
        build_effective_capabilities_snapshot,
        build_capability_snapshots,
    )
    for builder in builders:
        parameters = inspect.signature(builder).parameters
        assert parameters["resolution"].annotation is CapabilityResolution, builder


def test_r22_builders_reject_layer_dto_cache_lookup_and_raw_dict():
    resolution = make_resolution()
    builder_inputs = (
        resolution.available,
        resolution.effective,
        resolution.policy,
        CacheLookup(status="fresh", value=resolution.available),
        CacheLookup(status="cold", value=None),
        {"available": resolution.available},
    )
    for builder in (
        build_declared_capabilities_snapshot,
        build_available_capabilities_snapshot,
        build_effective_capabilities_snapshot,
    ):
        for wrong in builder_inputs:
            with pytest.raises(ExecutionSnapshotError) as exc:
                builder(uuid4(), wrong)  # type: ignore[arg-type]
            assert exc.value.code == "snapshot_resolution_required"
    for wrong in builder_inputs:
        with pytest.raises(ExecutionSnapshotError) as exc:
            build_execution_policy_snapshot(
                uuid4(),
                wrong,  # type: ignore[arg-type]
                disabled_capabilities_digest=disabled_capabilities_digest(()),
                execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
            )
        assert exc.value.code == "snapshot_resolution_required"


def test_capability_snapshots_copy_the_narrowed_views_verbatim():
    env = build_env(
        descriptors=(
            make_descriptor(
                declared=EngineCapabilities(
                    streaming=True,
                    cancellation=True,
                    tool_calling=True,
                    native_events=True,
                    workspace_required=True,
                )
            ),
        ),
    )
    # No trusted workspace generation registered: the read path must narrow
    # workspace_required, and the snapshot must inherit that narrowing.
    request = make_request()

    async def scenario():
        assert await env.resolver.warm(request) is True
        resolution = await env.resolver.resolve(request)
        execution_id = uuid4()
        available = build_available_capabilities_snapshot(execution_id, resolution)
        effective = build_effective_capabilities_snapshot(execution_id, resolution)
        return resolution, available, effective

    resolution, available_snapshot, effective_snapshot = asyncio.run(scenario())
    narrowed = {item.name: item for item in resolution.available.items}["workspace_required"]
    assert narrowed.available is False
    assert narrowed.reason_code == "workspace_unavailable"
    snapshot_items = {item.name: item for item in available_snapshot.items}
    assert snapshot_items["workspace_required"] == narrowed
    assert tuple(item.name for item in available_snapshot.items) == CAPABILITY_ORDER
    effective_items = {item.name: item for item in effective_snapshot.items}
    assert effective_items["workspace_required"].effective is False
    assert effective_items["workspace_required"].reason_code == "workspace_unavailable"
    asyncio.run(env.resolver.aclose())


def test_policy_snapshot_requires_a_resolved_policy_and_pins_digests():
    execution_id = uuid4()
    resolution = make_resolution()
    blocked = CapabilityResolution(
        declared=resolution.declared,
        available=resolution.available,
        policy=None,
        effective=resolution.effective,
        availability_status="fresh",
        policy_status="error",
    )
    with pytest.raises(ExecutionSnapshotError) as exc:
        build_execution_policy_snapshot(
            execution_id,
            blocked,
            disabled_capabilities_digest=disabled_capabilities_digest(()),
            execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
        )
    assert exc.value.code == "snapshot_policy_unavailable"

    snapshot = build_execution_policy_snapshot(
        execution_id,
        resolution,
        disabled_capabilities_digest=disabled_capabilities_digest(("terminal_execution",)),
        execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
    )
    assert snapshot.policy_revision == resolution.policy.policy_revision
    assert snapshot.disabled_capabilities_digest == disabled_capabilities_digest(
        ("terminal_execution",)
    )
    assert snapshot.execution_restriction_digest == NO_EXECUTION_RESTRICTIONS


def test_capability_snapshot_set_returns_all_four_layer_snapshots():
    execution_id = uuid4()
    caps = build_capability_snapshots(
        execution_id,
        make_resolution(),
        disabled_capabilities_digest=disabled_capabilities_digest(()),
        execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
    )
    assert isinstance(caps, CapabilitySnapshotSet)
    for snapshot in (caps.declared, caps.available, caps.policy, caps.effective):
        assert snapshot.execution_id == execution_id
    assert caps.declared.engine == EngineIdentity(
        engine_id="react", protocol_id="native", adapter_version="v1"
    )


# ---------------------------------------------------------------------------
# P3-IT-06/07/08/18 + P3-CM-06  repository write-once persistence (real PG)
# ---------------------------------------------------------------------------

SNAPSHOT_WRITE_MARKER = "SET execution_config_snapshot"

# F-1 / F-1b: the payload-side identity clause each snapshot column must carry
# inside the barrier statement itself. These tests compare, strip and count
# this exact text, so the repository has to spell every clause identically.
# ``SNAPSHOT_PAYLOAD_PARAMS`` is the bind name a column's payload travels under
# (the SET clause and the identity clause share it), which is what lets the
# clause be derived per column instead of hand-copied here.
SNAPSHOT_PAYLOAD_PARAMS = {
    "execution_config_snapshot": "config",
    "declared_capabilities_snapshot": "declared",
    "available_capabilities_snapshot": "available",
    "effective_capabilities_snapshot": "effective",
    "execution_policy_snapshot": "policy",
}

# Pinned here rather than left to the derivation below: a column missing from the
# mapping would otherwise surface as a ``KeyError`` while this module is being
# imported (a collection error that reads like a broken test file), and a column
# added to ``SNAPSHOT_COLUMNS`` without a bind name would silently shrink every
# derived expectation. Same five columns, one bind name each.
assert set(SNAPSHOT_PAYLOAD_PARAMS) == set(SNAPSHOT_COLUMNS), SNAPSHOT_PAYLOAD_PARAMS
assert len(SNAPSHOT_PAYLOAD_PARAMS) == len(SNAPSHOT_COLUMNS) == 5


def _payload_identity_clause(column: str) -> str:
    """The one-row identity binding for ``column``'s incoming payload body."""

    param = SNAPSHOT_PAYLOAD_PARAMS[column]
    return f"AND CAST(:{param} AS jsonb)->>'execution_id'=CAST(id AS TEXT)"


PAYLOAD_IDENTITY_CLAUSES = tuple(_payload_identity_clause(column) for column in SNAPSHOT_COLUMNS)


def _barrier_statement() -> str:
    """The live snapshot-write statement, extracted verbatim from repository.py.

    F-1 evidence must run the *same* SQL the barrier runs, so the text is read
    from production source instead of being duplicated here (a copy could
    drift and would prove nothing about the shipped statement).
    """

    source = _repository_source()
    start = source.index("WITH target AS (")
    tail = source.index("SELECT EXISTS(SELECT 1 FROM applied)", start)
    end = source.index("AS was_absent", tail) + len("AS was_absent")
    statement = source[start:end]
    assert "UPDATE runtime_runs SET execution_config_snapshot" in statement
    return statement


async def _raw_snapshots(engine, run_id: UUID) -> dict:
    async with engine.connect() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT " + ",".join(SNAPSHOT_COLUMNS) + " FROM runtime_runs WHERE id=:id"
                    ),
                    {"id": run_id},
                )
            )
            .mappings()
            .first()
        )
    assert row is not None
    return dict(row)


async def _raw_status(engine, run_id: UUID) -> str:
    async with engine.connect() as conn:
        status = await conn.scalar(
            text("SELECT status FROM runtime_runs WHERE id=:id"), {"id": run_id}
        )
    return str(status)


def _snapshot_bodies(stored: dict) -> dict[str, dict]:
    bodies: dict[str, dict] = {}
    for column in SNAPSHOT_COLUMNS:
        value = stored[column]
        bodies[column] = value if isinstance(value, dict) else json.loads(value)
    return bodies


@pytest.mark.postgres
def test_pg_snapshots_write_once_in_a_single_statement_after_claim():
    url = _snapshot_database_url()
    tenant = "p3-snap-06-" + uuid4().hex[:12]

    async def scenario() -> tuple:
        engine, repo = _repository(url, tenant)
        try:
            claimed = await _claimed_run(repo, tenant)
            run_id = claimed["row"]["id"]
            writes: list[str] = []

            @event.listens_for(engine.sync_engine, "before_execute")
            def _observe(conn, clauseelement, multiparams, params, execution_options):
                sql = str(clauseelement)
                if SNAPSHOT_WRITE_MARKER in sql:
                    writes.append(sql)

            payloads = make_payloads(run_id)
            first = await repo.write_execution_snapshots(run_id, claimed["owner"], payloads)
            stored = await _raw_snapshots(engine, run_id)
            events = await repo.events(run_id, tenant)
            return first, writes, run_id, stored, [ev["type"] for ev in events]
        finally:
            await _cleanup(engine, tenant)

    first, writes, run_id, stored, event_types = asyncio.run(scenario())
    assert first.outcome == "written"
    assert first.succeeded is True
    assert len(writes) == 1  # one conditional statement, one transaction
    assert all(stored[column] is not None for column in SNAPSHOT_COLUMNS)
    for body in _snapshot_bodies(stored).values():
        assert body["execution_id"] == str(run_id)
        assert body["schema_version"] == "v1"
    # run.started keeps its Phase 2 position: emitted by claim, before the
    # snapshot write, and the write itself adds no public event.
    assert event_types == ["run.queued", "run.started"]


@pytest.mark.postgres
def test_pg_conditional_write_identity_rules():
    """D-3: the four refusal causes are now four distinguishable outcomes.

    ``audit_conflict`` (stored audit disagrees with this startup) must never be
    collapsed with ``not_claimed`` / ``lease_lost`` (the existing lost-lease
    path); T7 maps them to different run terminations.
    """

    url = _snapshot_database_url()
    tenant = "p3-snap-18-" + uuid4().hex[:12]

    async def scenario() -> dict:
        engine, repo = _repository(url, tenant)
        try:
            claimed = await _claimed_run(repo, tenant)
            run_id = claimed["row"]["id"]
            owner = claimed["owner"]
            payloads = make_payloads(run_id)
            first = await repo.write_execution_snapshots(run_id, owner, payloads)
            reuse = await repo.write_execution_snapshots(run_id, owner, payloads)
            other_payloads = make_payloads(uuid4())
            different_identity = await repo.write_execution_snapshots(run_id, owner, other_payloads)
            same_identity_changed = make_payloads(run_id)
            tampered = replace(
                same_identity_changed,
                execution_policy_snapshot=serialize_snapshot(
                    build_execution_policy_snapshot(
                        run_id,
                        make_resolution(),
                        disabled_capabilities_digest=disabled_capabilities_digest(("streaming",)),
                        execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
                    ),
                ),
            )
            changed_decision = await repo.write_execution_snapshots(run_id, owner, tampered)
            wrong_owner = await repo.write_execution_snapshots(run_id, uuid4(), payloads)
            # Same owner, lease expired: this is lease loss, never an audit fault.
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE runtime_runs SET lease_until=now()-interval '1 second' WHERE id=:id"
                    ),
                    {"id": run_id},
                )
            expired_lease = await repo.write_execution_snapshots(run_id, owner, payloads)
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE runtime_runs SET lease_until=now()+interval '120 second' WHERE id=:id"
                    ),
                    {"id": run_id},
                )
            queued_row = await repo.submit(
                tenant,
                RunRequest(conversation_id="snap-queued", message="not claimed"),
                {"fingerprint": "phase3-t5"},
                10000,
                100,
                120,
            )
            queued_write = await repo.write_execution_snapshots(
                queued_row["id"], uuid4(), make_payloads(queued_row["id"])
            )
            # A row that does not exist at all (identity matches the phantom id,
            # so only the "no such row" rule can refuse it).
            ghost = uuid4()
            missing_run = await repo.write_execution_snapshots(ghost, uuid4(), make_payloads(ghost))
            stored = await _raw_snapshots(engine, run_id)
            return {
                "first": first,
                "reuse": reuse,
                "different_identity": different_identity,
                "changed_decision": changed_decision,
                "wrong_owner": wrong_owner,
                "expired_lease": expired_lease,
                "queued_write": queued_write,
                "missing_run": missing_run,
                "run_id": run_id,
                "stored": stored,
            }
        finally:
            await _cleanup(engine, tenant)

    outcomes = asyncio.run(scenario())
    assert outcomes["first"].outcome == "written"
    assert outcomes["reuse"].outcome == "reused"
    assert outcomes["reuse"].succeeded is True
    assert outcomes["different_identity"].outcome == "audit_conflict"
    assert outcomes["changed_decision"].outcome == "audit_conflict"
    # Owner mismatch and expired lease are lease semantics, not audit faults.
    assert outcomes["wrong_owner"].outcome == "lease_lost"
    assert outcomes["expired_lease"].outcome == "lease_lost"
    assert outcomes["queued_write"].outcome == "not_claimed"
    assert outcomes["missing_run"].outcome == "not_claimed"
    for result in outcomes.values():
        if isinstance(result, SnapshotWriteResult):
            # Every result is a bare category: no payload, no identity, no path.
            assert set(result.__dataclass_fields__) == {"outcome"}
            assert result.outcome in SNAPSHOT_WRITE_OUTCOMES
    for body in _snapshot_bodies(outcomes["stored"]).values():
        # Only the original startup payloads survived every rejected attempt.
        assert body["execution_id"] == str(outcomes["run_id"])


@pytest.mark.postgres
def test_pg_write_barrier_sql_binds_payload_identity_without_entry_guard():
    """F-1: the SQL itself refuses a fully foreign startup, guard or no guard.

    The repository's entry guard is the first gate, not the only one: 03 §5.3
    claims that even a caller that skipped the Python checks cannot point a row
    at another run. That claim is only true if the UPDATE statement binds every
    *incoming* payload body to the row's own ``id`` (the ``:execution_id``
    parameter is itself derived from those payloads, so binding to it would
    prove nothing), so this test executes the barrier statement extracted
    verbatim from ``repository.py`` directly — a deliberate guard bypass in the
    test (no production test backdoor).

    Two directions, each against a freshly claimed all-NULL row in its own
    throwaway tenant:

    * with all five payload-side clauses stripped (the pre-F-1 statement shape,
      which bound none of them), a fully consistent foreign startup LANDS and
      poisons the row — this is the hole F-1 closes, and it proves the
      assertion would fail without the fix;
    * with the deployed statement as written, the same foreign startup is
      refused (zero rows applied, columns stay NULL), and the row's own
      identity still lands afterwards — the clauses bind without over-blocking.

    The all-foreign shape below is only the coarsest split. Per-column
    coverage — one column foreign, four own and the reverse, i.e. the
    one-against-four shape the payload-side clause on ``:config`` alone cannot
    see — lives in
    :func:`test_pg_write_barrier_sql_binds_payload_identity_of_every_column`.
    """

    url = _snapshot_database_url()

    async def attempt(strip_payload_clause: bool) -> dict:
        tenant = "p3-snap-f1-" + uuid4().hex[:12]
        engine, repo = _repository(url, tenant)
        try:
            claimed = await _claimed_run(repo, tenant)
            run_id = claimed["row"]["id"]
            owner = claimed["owner"]
            foreign_id = uuid4()
            foreign = make_payloads(foreign_id)
            sql = _barrier_statement()
            if strip_payload_clause:
                # Pre-F-1 shape: no payload body is bound to the row at all.
                for clause in PAYLOAD_IDENTITY_CLAUSES:
                    sql = sql.replace(clause, "", 1)
            params = {
                "id": run_id,
                "owner": owner,
                "execution_id": str(foreign_id),
                "config": foreign.execution_config_snapshot,
                "declared": foreign.declared_capabilities_snapshot,
                "available": foreign.available_capabilities_snapshot,
                "effective": foreign.effective_capabilities_snapshot,
                "policy": foreign.execution_policy_snapshot,
            }
            async with engine.begin() as conn:
                outcome = (await conn.execute(text(sql), params)).mappings().one()
            stored = await _raw_snapshots(engine, run_id)
            own_applied = None
            stored_after_own = stored
            if not strip_payload_clause:
                own_payloads = make_payloads(run_id)
                own_params = {
                    **params,
                    "execution_id": str(run_id),
                    "config": own_payloads.execution_config_snapshot,
                    "declared": own_payloads.declared_capabilities_snapshot,
                    "available": own_payloads.available_capabilities_snapshot,
                    "effective": own_payloads.effective_capabilities_snapshot,
                    "policy": own_payloads.execution_policy_snapshot,
                }
                async with engine.begin() as conn:
                    own = (
                        (await conn.execute(text(_barrier_statement()), own_params))
                        .mappings()
                        .one()
                    )
                own_applied = own["applied"]
                stored_after_own = await _raw_snapshots(engine, run_id)
            return {
                "run_id": run_id,
                "foreign_id": foreign_id,
                "applied": outcome["applied"],
                "stored": stored,
                "own_applied": own_applied,
                "stored_after_own": stored_after_own,
            }
        finally:
            await _cleanup(engine, tenant)

    vulnerable = asyncio.run(attempt(True))
    # Without any payload-side binding the guard-bypassing foreign startup
    # would land on the empty row — the statement alone could not stop it.
    assert vulnerable["applied"] is True
    poisoned = _snapshot_bodies(vulnerable["stored"])
    assert poisoned["execution_config_snapshot"]["execution_id"] == str(vulnerable["foreign_id"])

    fixed = asyncio.run(attempt(False))
    # The deployed statement refuses the same foreign startup by itself...
    assert fixed["applied"] is False
    assert all(fixed["stored"][column] is None for column in SNAPSHOT_COLUMNS)
    # ...while the row's own identity still passes the same raw path.
    assert fixed["own_applied"] is True
    own_bodies = _snapshot_bodies(fixed["stored_after_own"])
    assert {body["execution_id"] for body in own_bodies.values()} == {str(fixed["run_id"])}


def _split_payloads(
    own_id: UUID, foreign_id: UUID, foreign_columns: tuple[str, ...]
) -> ExecutionSnapshotPayloads:
    """Payloads that carry ``own_id`` everywhere except ``foreign_columns``.

    The DTO-level ``execution_id`` stays ``own_id`` in every variant, because
    that is the value the repository would derive ``:execution_id`` from — so
    the stored-side branch is satisfied and only the payload-body binding can
    refuse the write.
    """

    own = make_payloads(own_id)
    foreign = make_payloads(foreign_id)
    return replace(own, **{column: getattr(foreign, column) for column in foreign_columns})


def _barrier_binds(run_id: UUID, owner: UUID, payloads: ExecutionSnapshotPayloads) -> dict:
    """The exact bind set ``write_execution_snapshots`` would send."""

    return {
        "id": run_id,
        "owner": owner,
        "execution_id": str(payloads.execution_id),
        **{param: getattr(payloads, column) for column, param in SNAPSHOT_PAYLOAD_PARAMS.items()},
    }


async def _raw_barrier_attempt(
    foreign_columns: tuple[str, ...],
    strip_columns: tuple[str, ...] = (),
) -> dict:
    """Run the extracted barrier on a fresh all-NULL claimed row, no entry guard.

    ``foreign_columns`` names which payload bodies carry a foreign startup id;
    ``strip_columns`` drops just those columns' payload-side identity clause,
    which is how the mutation half proves each clause is load-bearing.
    """

    url = _snapshot_database_url()
    tenant = "p3-snap-f1b-" + uuid4().hex[:12]
    engine, repo = _repository(url, tenant)
    try:
        claimed = await _claimed_run(repo, tenant)
        run_id = claimed["row"]["id"]
        foreign_id = uuid4()
        payloads = _split_payloads(run_id, foreign_id, foreign_columns)
        sql = _barrier_statement()
        for column in strip_columns:
            sql = sql.replace(_payload_identity_clause(column), "", 1)
        async with engine.begin() as conn:
            outcome = (
                (await conn.execute(text(sql), _barrier_binds(run_id, claimed["owner"], payloads)))
                .mappings()
                .one()
            )
        stored = await _raw_snapshots(engine, run_id)
        applied = bool(outcome["applied"])
        return {
            "run_id": run_id,
            "foreign_id": foreign_id,
            "applied": applied,
            "absent": [column for column in SNAPSHOT_COLUMNS if stored[column] is None],
            "ids": {
                column: body["execution_id"] for column, body in _snapshot_bodies(stored).items()
            }
            if applied
            else {},
        }
    finally:
        await _cleanup(engine, tenant)


@pytest.mark.postgres
def test_pg_write_barrier_sql_binds_payload_identity_of_every_column():
    """F-1b: all five payload bodies are bound, not just ``:config``.

    One payload-side clause (on ``:config``) leaves the other four columns'
    bodies unchecked by the SQL, so a caller that skipped the entry guard could
    park a foreign startup in them: the ``config`` identity matched the row, the
    stored-side branch passed, and the write landed. That shape — own id in one
    column, foreign ids in the other four — is what this test pins, again with
    the statement extracted verbatim from ``repository.py``.

    Each case writes nothing through the repository method: a freshly claimed
    all-NULL row in its own throwaway tenant, raw barrier SQL, entry guard
    bypassed on purpose.

    * per column: with *only that column's* clause stripped, a split whose only
      foreign body is that column LANDS on it (clause is load-bearing, so the
      assertion would fail without it);
    * per column: with the shipped statement, the same split is refused and the
      atomic write leaves all five columns NULL;
    * one-against-four: with the four non-``config`` clauses stripped — the
      pre-F-1b shape — ``config`` keeps the row's own id while the other four
      take the foreign one; the shipped statement refuses it;
    * all five foreign stays refused (F-1 regression);
    * all five own still lands (the clauses must not over-block).
    """

    for column in SNAPSHOT_COLUMNS:
        hole = asyncio.run(_raw_barrier_attempt((column,), strip_columns=(column,)))
        assert hole["applied"] is True, column
        assert hole["ids"][column] == str(hole["foreign_id"]), column
        assert {hole["ids"][other] for other in SNAPSHOT_COLUMNS if other != column} == {
            str(hole["run_id"])
        }, column
        refused = asyncio.run(_raw_barrier_attempt((column,)))
        assert refused["applied"] is False, column
        assert refused["absent"] == list(SNAPSHOT_COLUMNS), column

    non_config = SNAPSHOT_COLUMNS[1:]
    pre_f1b = asyncio.run(_raw_barrier_attempt(non_config, strip_columns=non_config))
    # The pre-F-1b statement: the row's own ``config`` body let the write
    # through and the four unbound columns took the foreign startup.
    assert pre_f1b["applied"] is True
    assert pre_f1b["ids"]["execution_config_snapshot"] == str(pre_f1b["run_id"])
    assert {pre_f1b["ids"][column] for column in non_config} == {str(pre_f1b["foreign_id"])}

    split = asyncio.run(_raw_barrier_attempt(non_config))
    assert split["applied"] is False
    assert split["absent"] == list(SNAPSHOT_COLUMNS)

    all_foreign = asyncio.run(_raw_barrier_attempt(SNAPSHOT_COLUMNS))
    assert all_foreign["applied"] is False
    assert all_foreign["absent"] == list(SNAPSHOT_COLUMNS)

    own = asyncio.run(_raw_barrier_attempt(()))
    assert own["applied"] is True
    assert own["absent"] == []
    assert set(own["ids"].values()) == {str(own["run_id"])}


def test_snapshot_write_result_is_content_free():
    """D-3: the outcome object may be logged without leaking snapshot content."""

    execution_id = uuid4()
    payloads = make_payloads(execution_id)
    config_body = json.loads(payloads.execution_config_snapshot)
    for outcome in sorted(SNAPSHOT_WRITE_OUTCOMES):
        result = SnapshotWriteResult(outcome)  # type: ignore[arg-type]
        rendered = f"{result!r} {result!s} {result.outcome}"
        assert payloads.execution_config_snapshot[:40] not in rendered
        assert str(execution_id) not in rendered
        for value in (config_body["provider_id"], config_body["engine"]["engine_id"]):
            assert str(value) not in rendered
    assert SnapshotWriteResult("written").succeeded is True
    assert SnapshotWriteResult("reused").succeeded is True
    for failure in ("audit_conflict", "not_claimed", "lease_lost"):
        assert SnapshotWriteResult(failure).succeeded is False  # type: ignore[arg-type]
    with pytest.raises(FrozenInstanceError):
        SnapshotWriteResult("written").outcome = "reused"  # type: ignore[misc]
    # F-5: the outcome vocabulary is closed at construction time, so a typo
    # cannot spread into logs or the T7 mapping table as a sixth category.
    for near_miss in ("bogus", "Written", "written ", "audit-conflict", "", None):
        with pytest.raises(ValueError):
            SnapshotWriteResult(near_miss)  # type: ignore[arg-type]
    # The rejection message stays content-free too (payload-shaped values are
    # never echoed back), mirroring the exception/logging discipline above.
    smuggled = f"written {payloads.execution_config_snapshot[:40]}"
    with pytest.raises(ValueError) as exc:
        SnapshotWriteResult(smuggled)  # type: ignore[arg-type]
    assert payloads.execution_config_snapshot[:40] not in str(exc.value)
    assert str(execution_id) not in str(exc.value)


@pytest.mark.postgres
def test_pg_concurrent_snapshot_writers():
    url = _snapshot_database_url()

    async def scenario(mode: str) -> tuple:
        tenant = "p3-snap-race-" + uuid4().hex[:12]
        engine, repo = _repository(url, tenant)
        try:
            claimed = await _claimed_run(repo, tenant)
            run_id = claimed["row"]["id"]
            other_eid = uuid4()
            if mode == "same":
                left = make_payloads(run_id)
                right = make_payloads(run_id)
            else:
                left = make_payloads(run_id)
                right = make_payloads(other_eid)
            results = await asyncio.gather(
                repo.write_execution_snapshots(run_id, claimed["owner"], left),
                repo.write_execution_snapshots(run_id, claimed["owner"], right),
            )
            stored = await _raw_snapshots(engine, run_id)
            return run_id, other_eid, tuple(results), stored
        finally:
            await _cleanup(engine, tenant)

    run_id_same, _other, same_results, stored_same = asyncio.run(scenario("same"))
    # Concurrent identical startups both satisfy the barrier; which one labeled
    # itself written vs reused is diagnostic only (see the repository docstring).
    assert [result.succeeded for result in same_results] == [True, True]
    assert {result.outcome for result in same_results} <= {"written", "reused"}
    assert all(stored_same[column] is not None for column in SNAPSHOT_COLUMNS)
    for body in _snapshot_bodies(stored_same).values():
        assert body["execution_id"] == str(run_id_same)

    run_id_diff, other_eid, diff_results, stored_diff = asyncio.run(scenario("different"))
    # The foreign startup is refused by the identity rule, the own one lands.
    assert sorted(result.outcome for result in diff_results) == ["audit_conflict", "written"]
    ids = {body["execution_id"] for body in _snapshot_bodies(stored_diff).values()}
    # The winner's identity survived intact; the loser rewrote nothing.
    assert ids == {str(run_id_diff)}
    assert other_eid not in ids


@pytest.mark.postgres
def test_pg_commit_failure_leaves_no_partial_snapshot_row():
    """D-7 + F-6: the UPDATE really runs server-side, then the txn dies.

    The injection point is ``after_cursor_execute``: PostgreSQL has already
    executed the snapshot UPDATE when the exception fires, and the exception
    arrives *before* SQLAlchemy issues COMMIT — so the surrounding transaction
    rolls back. For the barrier's atomicity claim this rollback is equivalent
    to a commit-stage failure (the write never becomes durable), but it is not
    literally a failure inside COMMIT and the test does not claim that; the
    earlier ``before_execute`` injection never ran the statement at all and
    proved nothing, and the statement is observed twice below so the all-NULL
    result is evidence, not a tautology.
    """

    url = _snapshot_database_url()
    tenant = "p3-snap-fail-" + uuid4().hex[:12]

    async def scenario() -> tuple:
        engine, repo = _repository(url, tenant)
        executed: list[str] = []

        @event.listens_for(engine.sync_engine, "after_cursor_execute")
        def _fail_first_time(conn, cursor, statement, parameters, context, executemany):
            if SNAPSHOT_WRITE_MARKER not in statement:
                return
            executed.append(statement)
            if len(executed) == 1:
                raise RuntimeError("injected failure after execution, before commit")

        try:
            claimed = await _claimed_run(repo, tenant)
            run_id = claimed["row"]["id"]
            payloads = make_payloads(run_id)
            with pytest.raises(RuntimeError):
                await repo.write_execution_snapshots(run_id, claimed["owner"], payloads)
            row = await repo.get(run_id, tenant)
            assert row is not None and row["status"] == "running"
            stored = await _raw_snapshots(engine, run_id)
            # Prove the injection was a real rolled-back write, not a dead
            # connection: the same barrier lands once the fault is gone.
            after = await repo.write_execution_snapshots(run_id, claimed["owner"], payloads)
            recovered = await _raw_snapshots(engine, run_id)
            return executed, stored, after, recovered
        finally:
            await _cleanup(engine, tenant)

    executed, stored, after, recovered = asyncio.run(scenario())
    assert len(executed) == 2  # both barrier statements really reached PG
    # The single-statement transaction lands all five columns or none: a
    # rollback after the executed UPDATE (commit never reached) can never
    # produce a half-written barrier row.
    assert all(stored[column] is None for column in SNAPSHOT_COLUMNS)
    assert after.outcome == "written"
    assert all(recovered[column] is not None for column in SNAPSHOT_COLUMNS)


def _decision_fields(bodies: dict[str, dict]) -> dict:
    """The decision-bearing fields P3-IT-07 names, extracted for explicit diffing.

    A future regression that keeps ``execution_id``/``schema_version`` intact
    but rewrites a decision (rounds budget, a narrowed flag, a layer reason)
    must be caught by name, not only through the whole-document comparison.
    """

    return {
        "max_model_rounds": bodies["execution_config_snapshot"]["config"]["react"][
            "max_model_rounds"
        ],
        "declared": dict(bodies["declared_capabilities_snapshot"]["capabilities"]),
        "available": [
            (item["name"], item["available"], item["reason_code"])
            for item in bodies["available_capabilities_snapshot"]["items"]
        ],
        "effective": [
            (item["name"], item["effective"], item["reason_code"])
            for item in bodies["effective_capabilities_snapshot"]["items"]
        ],
        "required_capabilities_missing": bodies["effective_capabilities_snapshot"][
            "required_capabilities_missing"
        ],
        "policy_layers": [
            (decision["name"], layer["layer"], layer["allowed"], layer["reason_code"])
            for decision in bodies["execution_policy_snapshot"]["decisions"]
            for layer in decision["layers"]
        ],
        "disabled_capabilities_digest": bodies["execution_policy_snapshot"][
            "disabled_capabilities_digest"
        ],
    }


# ---------------------------------------------------------------------------
# Per-column write-once retry matrix (03 §5.3 point 5)
# ---------------------------------------------------------------------------
# The reuse branch of the barrier is a conjunction of one ``jsonb`` equality per
# column: a retry may answer ``reused`` only when the stored row equals *this*
# startup's payloads, column for column. ``test_pg_conditional_write_identity_
# rules`` proves the two wholesale shapes (a foreign ``execution_id``, a changed
# ``policy`` payload), but nothing yet proved the per-column half: same identity,
# only one column's payload carrying a different decision. Dropping any one of
# the five comparisons therefore has to fail a behaviour test here, not only the
# static statement-text gate in
# ``test_repository_sql_is_parameterized_and_only_the_barrier_touches_snapshots``
# (which can be out-foxed by a semantically equivalent SQL rewrite).
#
# Each builder below keeps the run's own ``execution_id`` in every column and
# changes exactly one decision field inside exactly one column, going through
# the production builders so the difference is the decision itself and nothing
# else (``serialize_snapshot`` re-validates every column, and the control write
# in the test shows a fresh row accepts the same shape as its first startup).
# The other four columns stay at the baseline on purpose: this is a retry whose
# own audit moved in exactly one place, not a recomputed whole startup. The
# reason codes move with the boolean because the contract DTOs forbid ``allowed``
# paired with a denial
# (``CapabilityDecision``/``EffectiveCapabilityDecision``/``PolicyLayerDecision``),
# so each flip is one decision, not two.


def _variant_config_snapshot(execution_id: UUID) -> ExecutionConfigSnapshot:
    """Same startup, one bounded round budget raised."""

    return build_execution_config_snapshot(
        execution_id=execution_id,
        agent_id=AGENT_ID,
        agent_version=3,
        config=ExecutionConfig(react=ReactConfig(max_model_rounds=7)),
        provider_id="react-native",
        provider_version="v1",
    )


def _variant_declared_snapshot(execution_id: UUID) -> DeclaredCapabilitiesSnapshot:
    """Same startup, one declared flag narrowed off."""

    capabilities = EngineCapabilities(
        streaming=True,
        cancellation=True,
        native_events=True,
    )
    declared = DeclaredCapabilities(
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        declaration_schema_version="v1",
        # Recomputed so the variant stays self-consistent: the decision change
        # is the flag, the digest only follows it.
        declaration_digest=canonical_digest(capabilities),
        capabilities=capabilities,
    )
    return build_declared_capabilities_snapshot(
        execution_id, replace(make_resolution(), declared=declared)
    )


def _variant_available_snapshot(execution_id: UUID) -> AvailableCapabilitiesSnapshot:
    """Same startup, one availability observation turned into a probe failure."""

    resolution = make_resolution()
    items = tuple(
        CapabilityDecision(name=item.name, available=False, reason_code="probe_unavailable")
        if item.name == "streaming"
        else item
        for item in resolution.available.items
    )
    narrowed = resolution.available.model_copy(update={"items": items})
    return build_available_capabilities_snapshot(
        execution_id, replace(resolution, available=narrowed)
    )


def _variant_effective_snapshot(execution_id: UUID) -> EffectiveCapabilitiesSnapshot:
    """Same startup, one effective decision turned off by a trusted layer."""

    resolution = make_resolution()
    items = tuple(
        EffectiveCapabilityDecision(name=item.name, effective=False, reason_code="agent_disabled")
        if item.name == "tool_calling"
        else item
        for item in resolution.effective.items
    )
    narrowed = resolution.effective.model_copy(update={"items": items})
    return build_effective_capabilities_snapshot(
        execution_id, replace(resolution, effective=narrowed)
    )


def _variant_policy_snapshot(execution_id: UUID) -> ExecutionPolicySnapshot:
    """Same startup, one policy layer decision turned from allowed to denied."""

    resolution = make_resolution()
    decisions = []
    for decision in resolution.policy.decisions:
        if decision.name != "cancellation":
            decisions.append(decision)
            continue
        layers = tuple(
            PolicyLayerDecision(
                layer=layer.layer,
                allowed=False,
                source=layer.source,
                reason_code="agent_disabled",
            )
            if layer.layer == "agent"
            else layer
            for layer in decision.layers
        )
        decisions.append(CapabilityPolicy(name=decision.name, layers=layers))
    narrowed = resolution.policy.model_copy(update={"decisions": tuple(decisions)})
    return build_execution_policy_snapshot(
        execution_id,
        replace(resolution, policy=narrowed),
        disabled_capabilities_digest=disabled_capabilities_digest(()),
        execution_restriction_digest=NO_EXECUTION_RESTRICTIONS,
    )


# ``changed_fields`` names the keys of ``_decision_fields`` the variant moves,
# which is how the test proves the edit landed on a decision field of *this*
# column instead of on identity, provenance, or an adjacent column.
SNAPSHOT_RETRY_VARIANTS: dict[str, dict] = {
    "execution_config_snapshot": {
        "build": _variant_config_snapshot,
        "decision": "config.react.max_model_rounds 6 -> 7",
        "changed_fields": frozenset({"max_model_rounds"}),
    },
    "declared_capabilities_snapshot": {
        "build": _variant_declared_snapshot,
        "decision": "capabilities.tool_calling True -> False",
        "changed_fields": frozenset({"declared"}),
    },
    "available_capabilities_snapshot": {
        "build": _variant_available_snapshot,
        "decision": "items[streaming] available True -> False (reason probe_unavailable)",
        "changed_fields": frozenset({"available"}),
    },
    "effective_capabilities_snapshot": {
        "build": _variant_effective_snapshot,
        "decision": "items[tool_calling] effective True -> False (reason agent_disabled)",
        "changed_fields": frozenset({"effective"}),
    },
    "execution_policy_snapshot": {
        "build": _variant_policy_snapshot,
        "decision": "decisions[cancellation].layers[agent] allowed True -> False",
        "changed_fields": frozenset({"policy_layers"}),
    },
}
assert set(SNAPSHOT_RETRY_VARIANTS) == set(SNAPSHOT_COLUMNS), SNAPSHOT_RETRY_VARIANTS
assert len(SNAPSHOT_RETRY_VARIANTS) == 5


def make_variant_payloads(execution_id: UUID, column: str) -> ExecutionSnapshotPayloads:
    """This startup's payloads with only ``column``'s body carrying a new decision."""

    base = make_payloads(execution_id)
    variant = SNAPSHOT_RETRY_VARIANTS[column]["build"](execution_id)
    return replace(base, **{column: serialize_snapshot(variant)})


@pytest.mark.postgres
@pytest.mark.parametrize("column", sorted(SNAPSHOT_RETRY_VARIANTS))
def test_pg_retry_changing_one_column_decision_is_refused(column: str):
    """P3-IT-07/03 §5.3 point 5: the reuse branch verifies *all five* columns.

    One case per snapshot column. A first write lands the row (``written``) and
    the complete stored five-column payload is captured as the baseline. A retry
    with the *same* ``execution_id`` everywhere and one changed decision inside
    only ``column`` must be refused as ``audit_conflict`` (never ``reused``), and
    must leave every stored column byte-for-semantic-field equal to the baseline:
    the branch that answers ``reused`` is allowed to *verify* equality only, so
    an unequal retry may not rewrite audit.
    """

    url = _snapshot_database_url()
    tenant = "p3-snap-col-" + uuid4().hex[:12]

    async def scenario() -> dict:
        engine, repo = _repository(url, tenant)
        try:
            claimed = await _claimed_run(repo, tenant)
            run_id = claimed["row"]["id"]
            owner = claimed["owner"]
            payloads = make_payloads(run_id)
            first = await repo.write_execution_snapshots(run_id, owner, payloads)
            baseline = await _raw_snapshots(engine, run_id)
            variant_payloads = make_variant_payloads(run_id, column)
            retry = await repo.write_execution_snapshots(run_id, owner, variant_payloads)
            after = await _raw_snapshots(engine, run_id)
            # The untouched audit must still answer ``reused`` for the startup
            # that actually owns the row.
            reuse = await repo.write_execution_snapshots(run_id, owner, payloads)
            # Control: the same variant is a legal startup payload — on a fresh
            # all-NULL row it lands. Without this the refusal above could have
            # come from payload rejection or identity binding instead of the
            # write-once comparison.
            control = await _claimed_run(repo, tenant)
            control_id = control["row"]["id"]
            control_variant = make_variant_payloads(control_id, column)
            control_write = await repo.write_execution_snapshots(
                control_id, control["owner"], control_variant
            )
            control_stored = await _raw_snapshots(engine, control_id)
            return {
                "run_id": run_id,
                "first": first,
                "baseline": baseline,
                "retry": retry,
                "after": after,
                "reuse": reuse,
                "variant_payloads": variant_payloads,
                "control_write": control_write,
                "control_variant": control_variant,
                "control_stored": control_stored,
            }
        finally:
            await _cleanup(engine, tenant)

    case = asyncio.run(scenario())
    variant = SNAPSHOT_RETRY_VARIANTS[column]
    assert case["first"].outcome == "written"
    assert case["retry"].outcome == "audit_conflict", variant["decision"]
    assert case["retry"].succeeded is False
    assert case["reuse"].outcome == "reused"
    assert case["control_write"].outcome == "written"

    baseline_bodies = _snapshot_bodies(case["baseline"])
    after_bodies = _snapshot_bodies(case["after"])
    # The refused retry rewrote nothing: raw column text and the whole parsed
    # payload, column by column.
    for name in SNAPSHOT_COLUMNS:
        assert case["after"][name] == case["baseline"][name], name
    assert after_bodies == baseline_bodies
    assert _decision_fields(after_bodies) == _decision_fields(baseline_bodies)
    for name, body in after_bodies.items():
        assert body["execution_id"] == str(case["run_id"])
        assert body["schema_version"] == "v1"

    # The change really landed on exactly one decision field of exactly this
    # column, so the refusal above cannot be an artefact of the fixture.
    variant_bodies = {
        name: json.loads(getattr(case["variant_payloads"], name)) for name in SNAPSHOT_COLUMNS
    }
    changed_columns = {
        name for name in SNAPSHOT_COLUMNS if variant_bodies[name] != baseline_bodies[name]
    }
    assert changed_columns == {column}
    baseline_fields = _decision_fields(baseline_bodies)
    variant_fields = _decision_fields(variant_bodies)
    changed_fields = {
        name for name in baseline_fields if baseline_fields[name] != variant_fields[name]
    }
    assert changed_fields == variant["changed_fields"], variant["decision"]
    # The control row stored exactly the payloads it was handed (its own id, the
    # same single changed decision), so the variant shape is a startup the entry
    # guard and the payload identity binding both accept.
    control_bodies = {
        name: json.loads(getattr(case["control_variant"], name)) for name in SNAPSHOT_COLUMNS
    }
    assert _snapshot_bodies(case["control_stored"]) == control_bodies


@pytest.mark.postgres
def test_pg_terminal_paths_never_rewrite_snapshots():
    """P3-IT-07 (F-2): every terminal path is checked against the full payload.

    The previous version compared only ``execution_id`` and ``schema_version``,
    so a regression that preserved the identity while rewriting a decision —
    exactly the mutation the write-once barrier exists to prevent — would have
    passed. Each path now captures the complete stored five-column payload
    right after the barrier write and asserts, field by field, that the row is
    byte-for-semantic-field unchanged after the terminal transition (plus the
    named decision fields extracted by name).
    """

    url = _snapshot_database_url()
    tenant = "p3-snap-term-" + uuid4().hex[:12]

    async def write_and_baseline(engine, repo, claimed) -> tuple[UUID, dict]:
        run_id = claimed["row"]["id"]
        assert (
            await repo.write_execution_snapshots(run_id, claimed["owner"], make_payloads(run_id))
        ).succeeded
        return run_id, await _raw_snapshots(engine, run_id)

    async def full_scenario() -> dict:
        engine, repo = _repository(url, tenant)
        evidence: dict = {"runs": {}}
        try:
            # completed
            claimed = await _claimed_run(repo, tenant)
            run_id, baseline = await write_and_baseline(engine, repo, claimed)
            await repo.finish(run_id, claimed["owner"], "completed", output="done", history=[])
            evidence["runs"]["completed"] = (run_id, baseline, await _raw_snapshots(engine, run_id))
            # failed
            claimed = await _claimed_run(repo, tenant)
            run_id, baseline = await write_and_baseline(engine, repo, claimed)
            await repo.finish(run_id, claimed["owner"], "failed", error="boom")
            evidence["runs"]["failed"] = (run_id, baseline, await _raw_snapshots(engine, run_id))
            # lease loss -> reaper
            claimed = await _claimed_run(repo, tenant)
            run_id, baseline = await write_and_baseline(engine, repo, claimed)
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE runtime_runs SET lease_until=now()-interval '1 second' WHERE id=:id"
                    ),
                    {"id": run_id},
                )
            await repo.reap(tenant)
            evidence["runs"]["reaped"] = (run_id, baseline, await _raw_snapshots(engine, run_id))
            evidence["reaped_status"] = await _raw_status(engine, run_id)
            # cancel request + late finish attempt
            claimed = await _claimed_run(repo, tenant)
            run_id, baseline = await write_and_baseline(engine, repo, claimed)
            await repo.cancel(run_id, tenant)
            await repo.finish(run_id, claimed["owner"], "completed", output="late", history=[])
            evidence["runs"]["cancelled"] = (run_id, baseline, await _raw_snapshots(engine, run_id))
            # A post-terminal write attempt with this row's own identity must be
            # refused as "not claimed" (a terminal state), never rewrite audit.
            completed_id, completed_baseline, _ = evidence["runs"]["completed"]
            late = await repo.write_execution_snapshots(
                completed_id, uuid4(), make_payloads(completed_id)
            )
            assert late.outcome == "not_claimed"
            assert late.succeeded is False
            evidence["late"] = (
                completed_id,
                completed_baseline,
                await _raw_snapshots(engine, completed_id),
            )
            return evidence
        finally:
            await _cleanup(engine, tenant)

    evidence = asyncio.run(full_scenario())
    for label, (run_id, baseline, after) in [
        *evidence["runs"].items(),
        ("late write", evidence["late"]),
    ]:
        baseline_bodies = _snapshot_bodies(baseline)
        after_bodies = _snapshot_bodies(after)
        # Whole stored payload, column by column, field by field: the terminal
        # transitions moved status/lease only, never audit content.
        assert after_bodies == baseline_bodies, label
        for column in SNAPSHOT_COLUMNS:
            assert after[column] == baseline[column], (label, column)
        assert _decision_fields(after_bodies) == _decision_fields(baseline_bodies), label
        for body in after_bodies.values():
            assert body["execution_id"] == str(run_id)
            assert body["schema_version"] == "v1"
    assert evidence["reaped_status"] == "failed"  # state moved, snapshots did not


@pytest.mark.postgres
def test_pg_historical_null_rows_are_never_backfilled_by_reads():
    url = _snapshot_database_url()
    tenant = "p3-snap-hist-" + uuid4().hex[:12]

    async def scenario() -> tuple:
        engine, repo = _repository(url, tenant)
        try:
            claimed = await _claimed_run(repo, tenant)
            run_id = claimed["row"]["id"]
            await repo.finish(run_id, claimed["owner"], "failed", error="boom")
            for _ in range(3):
                assert await repo.get(run_id, tenant) is not None
            stored = await _raw_snapshots(engine, run_id)
            # Claimed rows also expose the new columns as NULL; claim itself
            # must not write anything.
            other = await _claimed_run(repo, tenant)
            row = await repo.get(other["row"]["id"], tenant)
            assert row is not None
            assert all(row[column] is None for column in SNAPSHOT_COLUMNS)
            return stored
        finally:
            await _cleanup(engine, tenant)

    stored = asyncio.run(scenario())
    # Reads never UPDATE: a Phase-2-era row stays NULL forever (AC-11).
    assert all(stored[column] is None for column in SNAPSHOT_COLUMNS)


def _repository_source() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "src"
        / "agent_platform"
        / "core_platform"
        / "agent_runtime"
        / "repository.py"
    ).read_text(encoding="utf-8")


def _flat(sql: str) -> str:
    return re.sub(r"\s+", "", sql)


def _methods(source: str) -> dict[str, str]:
    """Map every method name to its full source text (body *and* docstring)."""

    starts = list(re.finditer(r"^    (?:async )?def (\w+)", source, flags=re.MULTILINE))
    assert starts, "the repository must expose methods"
    out: dict[str, str] = {}
    for index, match in enumerate(starts):
        stop = starts[index + 1].start() if index + 1 < len(starts) else len(source)
        out[match.group(1)] = source[match.start() : stop]
    return out


BARRIER_UPDATE_HEAD = _flat("UPDATE runtime_runs SET")
# ``column=CAST(:param AS jsonb)`` flattened: the lazy parameter group is bounded
# by the ``ASjsonb)`` tail, so the bind name is read out instead of guessed.
SET_ASSIGNMENT = re.compile(r"(\w+)=CAST\(:([A-Za-z_]+?)ASjsonb\)")


def _set_clause(flat_body: str) -> str:
    """The barrier's SET segment: ``SET`` up to the first ``WHERE``.

    F-1b: the column-to-bind pairing has to be judged inside this segment only.
    The reuse branch of the same statement compares the stored row against the
    incoming bodies with the *identical* text (a jsonb equality comparison of
    ``column=CAST(:param AS jsonb)`` form), so a substring search over the whole
    method finds the pair even when the SET clause writes that column from a
    different payload. Slicing is layout-independent because both markers are
    taken from the flattened text.
    """

    assert flat_body.count(BARRIER_UPDATE_HEAD) == 1, flat_body
    start = flat_body.index(BARRIER_UPDATE_HEAD) + len(BARRIER_UPDATE_HEAD)
    return flat_body[start : flat_body.index("WHERE", start)]


def _set_bindings(flat_body: str) -> dict[str, str]:
    """``column -> bind name`` for every assignment the SET clause performs."""

    bindings = dict(SET_ASSIGNMENT.findall(_set_clause(flat_body)))
    assert len(bindings) == len(SNAPSHOT_COLUMNS), bindings
    return bindings


# The reuse branch of the same statement: the ``OR (...)`` alternative that
# answers a retry with ``reused`` once the stored row equals this startup's
# payloads. The branch opens with its own identity test and the statement closes
# at ``RETURNING id``. The outer stored branch repeats that same identity test,
# but there it follows ``IS NULL OR`` instead of being opened by a parenthesis,
# so the anchor below occurs exactly once — asserted, so a restructure that
# breaks the anchor turns the gate red instead of silently slicing the wrong
# text.
REUSE_BRANCH_HEAD = _flat("OR (execution_config_snapshot->>'execution_id'=:execution_id")
BARRIER_TAIL = _flat("RETURNING id")


def _comparison_pattern(column: str) -> re.Pattern[str]:
    """``column=CAST(:param AS jsonb)`` for one *known* column, flattened.

    The column name is matched literally rather than captured by ``\\w+`` the way
    ``SET_ASSIGNMENT`` does for the SET clause: flattening deletes the whitespace
    that separated a column from the preceding token, so a generic capture would
    read ``ANDdeclared_capabilities_snapshot`` inside the reuse branch (the SET
    clause is comma-separated, which is why it does not have this problem).
    """

    return re.compile(rf"{re.escape(column)}=CAST\(:([A-Za-z_]+?)ASjsonb\)")


SNAPSHOT_COMPARISONS = {column: _comparison_pattern(column) for column in SNAPSHOT_COLUMNS}


def _comparison_bindings(clause: str) -> dict[str, list[str]]:
    """``column -> every bind name it is jsonb-compared to`` inside ``clause``.

    A list per column, not a dict: a mutation that compares one column twice must
    stay visible instead of collapsing into a key.
    """

    return {column: pattern.findall(clause) for column, pattern in SNAPSHOT_COMPARISONS.items()}


def _reuse_clause(flat_body: str) -> str:
    """The barrier's reuse branch, sliced out of the flattened statement."""

    assert flat_body.count(REUSE_BRANCH_HEAD) == 1, flat_body
    assert flat_body.count(BARRIER_TAIL) == 1, flat_body
    start = flat_body.index(REUSE_BRANCH_HEAD) + len(REUSE_BRANCH_HEAD)
    return flat_body[start : flat_body.index(BARRIER_TAIL, start)]


# D-12: deliberately *not* marked postgres. It only reads a source file, so a
# postgres marker made it vanish from the default ``-m "not postgres"`` run.
def test_repository_sql_is_parameterized_and_only_the_barrier_touches_snapshots():
    """D-11: the whole file is scanned, not just the code above one method.

    The previous version split on ``def write_execution_snapshots`` and only
    looked at what came *before* it, which left heartbeat/finish/cancel/reap
    outside the gate. Now every ``UPDATE runtime_runs`` statement in the module
    is accounted for, and the five snapshot columns may appear in exactly one
    method.
    """

    source = _repository_source()
    assert 'f"""UPDATE runtime_runs' not in source
    assert "f'''UPDATE runtime_runs" not in source
    assert 'f"UPDATE runtime_runs' not in source

    methods = _methods(source)
    for name in ("submit", "claim", "append", "heartbeat", "finish", "cancel", "reap"):
        assert name in methods, name
    # Every statement lives inside a method that this test can attribute.
    assert len(re.findall(r"UPDATE runtime_runs", source)) == sum(
        len(re.findall(r"UPDATE runtime_runs", body)) for body in methods.values()
    )

    touched = sorted(
        name for name, body in methods.items() if any(column in body for column in SNAPSHOT_COLUMNS)
    )
    assert touched == ["write_execution_snapshots"]

    body = _flat(methods["write_execution_snapshots"])
    assert body.count("UPDATEruntime_runsSET") == 1  # one conditional statement
    assert "{execution_config_snapshot}" not in methods["write_execution_snapshots"]
    for column in SNAPSHOT_COLUMNS:
        assert f"{column}=CAST(:" in body, column
    # D-2: the stored branch is pinned to this startup's identity parameter.
    assert (
        _flat("execution_config_snapshot IS NULL OR execution_config_snapshot->>'execution_id'")
        in body
    )
    assert body.count("execution_config_snapshot->>'execution_id'=:execution_id") == 2
    # F-1 / F-1b: every *incoming* payload body is bound to the row's own id
    # inside the SQL, so "a caller that skipped the entry guard cannot point a
    # row at another run" is a property of the statement itself, not only of
    # the Python entry check. The bound value has to be the row's own ``id``
    # column: ``:execution_id`` is derived from the caller's payloads
    # (repository.py binds it from ``payloads.execution_id``), so a clause
    # against that parameter would pin the claim without proving it.
    # Counting all five clauses - and requiring exactly five - is what makes
    # deleting any single column's binding a red test; the previous version of
    # this gate looked at ``:config`` only, which left the other four bodies
    # unbound while the docstring still claimed full coverage.
    # What each check below pins down (each is scoped to one segment, because
    # the barrier repeats the same text in several places):
    # * the predicate loop + count (whole statement text) catch a *missing or
    #   duplicated* payload-to-row-id binding for any column; they say nothing
    #   about which payload the SET clause writes or which payload the reuse
    #   branch compares against, because the bind names they search for also
    #   occur in those two segments;
    # * the SET-segment pairing (``_set_bindings``) catches a SET clause that
    #   assigns a column from another column's payload (a swapped or mis-bound
    #   ``:param``). It has to be scoped to the SET segment: the reuse branch
    #   spells the same ``column=CAST(:param AS jsonb)`` text, so a single
    #   whole-text pairing could not attribute a comparison to either segment;
    # * the reuse-segment pairing below catches what neither of the two above
    #   can see: an edit that leaves the SET clause, the identity predicates and
    #   the bind vocabulary untouched and changes only *which payload a stored
    #   column is compared against*. That branch is what answers a retry with
    #   ``reused``, and 03 §5.3 point 5 / 08 T7 let it do nothing but *verify*
    #   equality. Measured shapes (repository.py mutated, then restored):
    #   deleting one of the five comparisons lets a retry whose payload for that
    #   column really differs be answered ``reused`` while the same statement
    #   rewrites the column - audit drift, and no PG test noticed; swapping two
    #   comparison targets is milder (legitimate retries come back
    #   ``audit_conflict``) and *is* also caught by
    #   ``test_pg_conditional_write_identity_rules`` /
    #   ``test_pg_concurrent_snapshot_writers``, which are skipped whenever
    #   ``TEST_DATABASE_URL`` is unset - so the pairing is asserted from the
    #   statement text here as well;
    # * both sides derive their text from ``SNAPSHOT_PAYLOAD_PARAMS``, so a
    #   predicate cannot reference a bind the barrier never assigns — renaming a
    #   bind in the repository without renaming it here turns the predicate loop
    #   and the pairing red together.
    for clause in PAYLOAD_IDENTITY_CLAUSES:
        assert _flat(clause) in body, clause
        assert body.count(_flat(clause)) == 1, clause
    assert body.count("->>'execution_id'=CAST(idASTEXT)") == len(SNAPSHOT_COLUMNS)
    bindings = _set_bindings(body)
    for column, param in SNAPSHOT_PAYLOAD_PARAMS.items():
        assert bindings.get(column) == param, f"{column} is SET from :{bindings.get(column)}"
        assert _flat(_payload_identity_clause(column)) in body, column
    # The reuse branch, judged on its own text (see ``_reuse_clause``): every
    # stored column has to be compared against the very payload the SET clause
    # writes it from, exactly once.
    reuse = _comparison_bindings(_reuse_clause(body))
    for column in SNAPSHOT_COLUMNS:
        compared = reuse[column]
        assert len(compared) == 1, f"{column} is reuse-compared {len(compared)} times"
        assert compared[0] == bindings[column], f"{column} reuse-compares :{compared[0]}"
    # And the two segments are the only places this comparison text occurs, so
    # the slice above cannot be looking at a duplicated or relocated branch:
    # per column, SET once + reuse once, both bound to the column's own payload.
    everywhere = _comparison_bindings(body)
    for column, param in SNAPSHOT_PAYLOAD_PARAMS.items():
        assert everywhere[column] == [param, param], (
            f"{column} compared against {[':' + p for p in everywhere[column]]}"
        )


@pytest.mark.postgres
def test_pg_public_views_and_events_never_expose_snapshot_columns():
    url = _snapshot_database_url()
    tenant = "p3-snap-view-" + uuid4().hex[:12]

    async def scenario() -> dict:
        engine, repo = _repository(url, tenant)
        try:
            claimed = await _claimed_run(repo, tenant)
            run_id = claimed["row"]["id"]
            assert (
                await repo.write_execution_snapshots(
                    run_id, claimed["owner"], make_payloads(run_id)
                )
            ).succeeded
            row = await repo.get(run_id, tenant)
            await repo.finish(run_id, claimed["owner"], "failed", error="boom")
            events = await repo.events(run_id, tenant)
            return {"row": row, "events": events}
        finally:
            await _cleanup(engine, tenant)

    result = asyncio.run(scenario())
    row = result["row"]
    assert row is not None
    # Internal rows do carry the columns...
    assert all(column in row for column in SNAPSHOT_COLUMNS)
    # ...but the whitelisted public view drops them.
    view = RunView.model_validate(row).model_dump(mode="json")
    assert set(view) == {
        "id",
        "conversation_id",
        "status",
        "cancel_requested",
        "output",
        "error_code",
        "created_at",
        "started_at",
        "finished_at",
    }
    assert not set(SNAPSHOT_COLUMNS) & set(RunView.model_fields)
    dumped = json.dumps(view)
    assert "snapshot" not in dumped
    for persisted_event in result["events"]:
        data = persisted_event["data"]
        body = data if isinstance(data, dict) else json.loads(data)
        flat = json.dumps(body)
        assert "snapshot" not in flat
        assert "execution_id" not in flat


@pytest.mark.postgres
def test_pg_read_back_row_replays_without_re_encoding():
    """D-6: the end-to-end write -> read -> replay wiring against real PG.

    This is the exact shape T7 and any audit tool will use: the repository
    hands back one row, and the replay entry point must consume it as-is.
    """

    url = _snapshot_database_url()
    tenant = "p3-snap-replay-" + uuid4().hex[:12]

    async def scenario() -> tuple:
        engine, repo = _repository(url, tenant)
        try:
            claimed = await _claimed_run(repo, tenant)
            run_id = claimed["row"]["id"]
            payloads = make_payloads(run_id)
            written = await repo.write_execution_snapshots(run_id, claimed["owner"], payloads)
            row = await repo.get(run_id, tenant)
            return written, payloads, row, run_id
        finally:
            await _cleanup(engine, tenant)

    written, payloads, row, run_id = asyncio.run(scenario())
    assert written.outcome == "written"
    assert row is not None
    stored = {column: row[column] for column in SNAPSHOT_COLUMNS}
    # asyncpg decodes jsonb, so the read-back values are dicts, not text.
    assert all(isinstance(value, dict) for value in stored.values())
    replay = deserialize_execution_snapshots(stored)
    assert replay.execution_id == run_id
    assert replay.available.items == make_resolution().available.items
    again = serialize_execution_snapshots(
        config=replay.config,
        declared=replay.declared,
        available=replay.available,
        policy=replay.policy,
        effective=replay.effective,
    )
    assert dict(again.payloads) == {
        column: getattr(payloads, column) for column in SNAPSHOT_COLUMNS
    }
    # Passing the row itself (extra columns and all) is the trap this guards:
    # unknown keys are refused rather than silently ignored.
    with pytest.raises(ExecutionSnapshotError) as exc:
        deserialize_execution_snapshots(row)
    assert exc.value.code == "snapshot_field_invalid"
    # A NULL snapshot column is reported as missing, a wrong-typed one as a
    # type fault — never the same code for both.
    nullish = dict(stored)
    nullish["declared_capabilities_snapshot"] = None
    with pytest.raises(ExecutionSnapshotError) as missing_exc:
        deserialize_execution_snapshots(nullish)
    assert missing_exc.value.code == "snapshot_payload_missing"
    odd = dict(stored)
    odd["declared_capabilities_snapshot"] = 17
    with pytest.raises(ExecutionSnapshotError) as type_exc:
        deserialize_execution_snapshots(odd)
    assert type_exc.value.code == "snapshot_payload_type_invalid"


def test_snapshot_payloads_dataclass_is_the_repository_contract():
    execution_id = uuid4()
    payloads = make_payloads(execution_id)
    assert payloads.execution_id == execution_id
    fields = {field.name for field in payloads.__dataclass_fields__.values()}
    assert fields == {"execution_id", *SNAPSHOT_COLUMNS}
    with pytest.raises(FrozenInstanceError):
        payloads.execution_id = uuid4()  # type: ignore[misc]


def test_error_messages_only_carry_field_paths_and_stable_codes():
    carrier = {"nested": {"refresh_token": FAKE_API_KEY}}
    with pytest.raises(ExecutionSnapshotError) as exc:
        assert_snapshot_payload_clean(carrier)
    message = str(exc.value)
    assert "refresh_token" in message
    assert FAKE_API_KEY not in message
    assert exc.value.path == ("nested", "refresh_token")
    # Codes are a closed stable vocabulary. ``snapshot_payload_type_invalid`` is
    # the D-6 entry that separates "the column is NULL/absent" from "a value is
    # present but is neither canonical JSON text nor a decoded JSON object".
    codes = {
        "snapshot_resolution_required",
        "snapshot_policy_unavailable",
        "snapshot_field_invalid",
        "snapshot_payload_missing",
        "snapshot_payload_type_invalid",
        "snapshot_denied_field_name",
        "snapshot_denied_credential_value",
        "snapshot_denied_host_path",
        "snapshot_not_serializable",
        "snapshot_size_exceeded",
        "snapshot_invalid_limit",
        "snapshot_identity_mismatch",
    }
    assert exc.value.code in codes


# ---------------------------------------------------------------------------
# P3-IT-08 / R-51: the repository entry cleaning gate is a strict re-validation
# ---------------------------------------------------------------------------

GATE_COLUMNS = tuple(sorted(SNAPSHOT_COLUMNS))
GATE_DENIED_KEY = "api_key"
GATE_BENIGN_FIELD = "gate_note"


def _gate_denied_key(body: dict) -> dict:
    """A denylisted key at the payload root: the recursive scan's own face."""
    body[GATE_DENIED_KEY] = "abc"
    return body


def _gate_credential_value(body: dict) -> dict:
    """A credential-shaped *value* under a schema-legal key name."""
    body[GATE_BENIGN_FIELD] = FAKE_API_KEY
    return body


def _gate_host_path_value(body: dict) -> dict:
    """A filesystem-shaped value, the other half of the value scan."""
    body[GATE_BENIGN_FIELD] = FAKE_HOST_PATH
    return body


def _gate_drop_last(body: dict, key: str) -> dict:
    """Drop one entry from a coverage-checked collection or a required field."""
    if key in body and isinstance(body[key], list):
        body[key] = body[key][:-1]
    else:
        del body[key]
    return body


def _gate_duplicate_first(body: dict, key: str) -> dict:
    """Repeat one entry in place, which a scan alone cannot see."""
    body[key] = [body[key][0], dict(body[key][0]), *body[key][1:]]
    return body


def _gate_duplicate_disabled_capability(body: dict) -> dict:
    """Repeat one capability name in the canonical config payload.

    The config snapshot has no item list, but its ``disabled_capabilities`` is a
    set-like sequence the DTO de-duplicates: the strict re-validation therefore
    has to notice that the re-produced canonical text no longer equals the
    stored one, which is precisely the coverage a clean-key scan does not have.
    """
    body["config"]["disabled_capabilities"] = ["streaming", "streaming"]
    return body


# (class, column) -> (tamper, expected code). The two code shapes are the point of
# R-51: the first three classes are what ``assert_snapshot_payload_clean`` already
# caught, while a missing or duplicated entry is only refused by the strict
# re-validation (required fields, exact capability coverage and the canonical
# round-trip), which is why the gate may not be a clean-key scan.
GATE_CASES: dict[tuple[str, str], tuple[Callable[[dict], dict], str]] = {
    # Every column: the denylist and the value scans are depth-independent.
    **{
        (kind, column): (tamper, code)
        for kind, tamper, code in (
            ("denied_key", _gate_denied_key, "snapshot_denied_field_name"),
            ("credential_value", _gate_credential_value, "snapshot_denied_credential_value"),
            ("host_path_value", _gate_host_path_value, "snapshot_denied_host_path"),
        )
        for column in GATE_COLUMNS
    },
    ("missing_item", "execution_config_snapshot"): (
        lambda body: _gate_drop_last(body, "engine"),
        "snapshot_field_invalid",
    ),
    ("missing_item", "declared_capabilities_snapshot"): (
        lambda body: _gate_drop_last(body, "capabilities"),
        "snapshot_field_invalid",
    ),
    ("missing_item", "available_capabilities_snapshot"): (
        lambda body: _gate_drop_last(body, "items"),
        "snapshot_field_invalid",
    ),
    ("missing_item", "execution_policy_snapshot"): (
        lambda body: _gate_drop_last(body, "decisions"),
        "snapshot_field_invalid",
    ),
    ("missing_item", "effective_capabilities_snapshot"): (
        lambda body: _gate_drop_last(body, "items"),
        "snapshot_field_invalid",
    ),
    # ``declared_capabilities_snapshot`` carries no repeated-entry collection at
    # all (its capability layer is a fixed-shape object, and a duplicated JSON
    # key collapses before any gate can see it), so the duplicate class is
    # structurally inexpressible there and is exercised on the other four.
    ("duplicate_item", "execution_config_snapshot"): (
        _gate_duplicate_disabled_capability,
        "snapshot_field_invalid",
    ),
    ("duplicate_item", "available_capabilities_snapshot"): (
        lambda body: _gate_duplicate_first(body, "items"),
        "snapshot_field_invalid",
    ),
    ("duplicate_item", "execution_policy_snapshot"): (
        lambda body: _gate_duplicate_first(body, "decisions"),
        "snapshot_field_invalid",
    ),
    ("duplicate_item", "effective_capabilities_snapshot"): (
        lambda body: _gate_duplicate_first(body, "items"),
        "snapshot_field_invalid",
    ),
}


def test_gate_case_matrix_covers_every_class_per_expressible_column():
    """The matrix itself is a judgement: no class may quietly lose a column."""
    expected = {
        (kind, column)
        for kind in ("denied_key", "credential_value", "host_path_value", "missing_item")
        for column in GATE_COLUMNS
    } | {
        ("duplicate_item", column)
        for column in GATE_COLUMNS
        if column != "declared_capabilities_snapshot"
    }
    assert set(GATE_CASES) == expected


@pytest.mark.postgres
@pytest.mark.parametrize(("kind", "column"), sorted(GATE_CASES))
def test_pg_barrier_entry_clean_gate_refuses_every_payload_class_before_sql(kind, column):
    """R-51/P3-IT-08: the gate is at the repository entry and it is strict.

    Each tamper lands on exactly one of the five columns while the other four
    stay serializer output, so a pass can never be explained by an accidentally
    malformed whole payload. Three things are asserted together: the stable code,
    that no barrier statement was ever executed (the gate runs before
    ``engine.begin()``), and that the row keeps all five columns NULL afterwards.
    The error text must not repeat the smuggled value.
    """

    tamper, expected_code = GATE_CASES[(kind, column)]
    url = _snapshot_database_url()
    tenant = "p3-it08-" + uuid4().hex[:12]

    async def scenario() -> tuple:
        engine, repo = _repository(url, tenant)
        statements: list[str] = []

        @event.listens_for(engine.sync_engine, "before_execute")
        def _observe(conn, clauseelement, multiparams, params, execution_options):
            sql = str(clauseelement)
            if SNAPSHOT_WRITE_MARKER in sql:
                statements.append(sql)

        try:
            claimed = await _claimed_run(repo, tenant)
            run_id = claimed["row"]["id"]
            payloads = make_payloads(run_id)
            body = json.loads(getattr(payloads, column))
            tampered = replace(payloads, **{column: json.dumps(tamper(body), default=str)})
            with pytest.raises(ExecutionSnapshotError) as raised:
                await repo.write_execution_snapshots(run_id, claimed["owner"], tampered)
            stored = await _raw_snapshots(engine, run_id)
            return raised.value, list(statements), stored
        finally:
            await _cleanup(engine, tenant)

    error, statements, stored = asyncio.run(scenario())

    assert error.code == expected_code, (kind, column)
    assert statements == [], (kind, column)
    assert all(stored[gate_column] is None for gate_column in SNAPSHOT_COLUMNS)
    assert FAKE_API_KEY not in str(error)
    assert FAKE_HOST_PATH not in str(error)
