"""Phase 6 T-01: frozen internal ownership, event, and credential DTOs.

TDD contract for the reliability foundation: these are internal-only value
objects. The tests pin strict identity validation, the additive AgentEvent
metadata (producer identity and adapter-local sequence are never the durable
sequence), the internal replay publication exclusion, and the rule that a
credential DTO can expose administrative metadata without ever exposing the
encrypted secret or a plaintext token.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from agent_platform.core_platform.agent_execution.contracts import AgentEvent
from agent_platform.core_platform.agent_execution.credentials.models import (
    ExecutionCredentialGrant,
    ExecutionCredentialRecord,
)
from agent_platform.core_platform.agent_execution.events.envelope import (
    EVENT_SCHEMA_VERSION,
    EventProducerIdentity,
    EventWriteResult,
    from_agent_event,
    is_publishable,
)
from agent_platform.core_platform.agent_execution.reliability.ownership import (
    FENCING_DENIAL_REASONS,
    OWNERSHIP_OPERATIONS,
    ExecutionOwnership,
    FencingDenial,
)


def test_execution_ownership_keeps_strict_monotonic_identity():
    run_id, owner = uuid4(), uuid4()
    ownership = ExecutionOwnership(run_id=run_id, owner=owner, lease_epoch=1)

    assert ownership.run_id == run_id
    assert ownership.owner == owner
    assert ownership.lease_epoch == 1
    assert ownership == ExecutionOwnership(run_id=run_id, owner=owner, lease_epoch=1)


@pytest.mark.parametrize("lease_epoch", [0, -1, True, "1", 1.0, None])
def test_execution_ownership_rejects_nonpositive_or_noninteger_epoch(lease_epoch):
    with pytest.raises((TypeError, ValueError)):
        ExecutionOwnership(run_id=uuid4(), owner=uuid4(), lease_epoch=lease_epoch)


def test_execution_ownership_rejects_foreign_identity_shapes():
    with pytest.raises((TypeError, ValueError)):
        ExecutionOwnership(run_id="not-a-uuid", owner=uuid4(), lease_epoch=1)  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError)):
        ExecutionOwnership(run_id=uuid4(), owner=None, lease_epoch=1)  # type: ignore[arg-type]


def test_fencing_denial_vocabulary_is_closed_and_content_free():
    denial = FencingDenial(
        run_id=uuid4(),
        operation="append",
        reason="stale_epoch",
        stale_owner=uuid4(),
        stale_lease_epoch=1,
        current_owner=uuid4(),
        current_lease_epoch=2,
    )

    assert denial.operation in OWNERSHIP_OPERATIONS
    assert denial.reason in FENCING_DENIAL_REASONS
    assert not hasattr(denial, "payload")
    assert not hasattr(denial, "detail")
    with pytest.raises(ValueError):
        FencingDenial(run_id=uuid4(), operation="drop-database", reason="stale_epoch")
    with pytest.raises(ValueError):
        FencingDenial(run_id=uuid4(), operation="append", reason="made_up_reason")


def test_ownership_operations_cover_every_fenced_write_surface():
    assert set(OWNERSHIP_OPERATIONS) == {
        "snapshot",
        "append",
        "finish",
        "heartbeat",
        "usage",
        "tool_replay",
        "process",
        "workdir",
        "resource_release",
    }


def _agent_event(*, event_id=None, sequence=1, event_type="tool.result") -> AgentEvent:
    return AgentEvent(
        event_id=event_id or uuid4(),
        execution_id=uuid4(),
        engine_id="react",
        protocol_id="native",
        adapter_version="v1",
        sequence=sequence,
        event_type=event_type,
        source="engine_native",
        timestamp=datetime.now(UTC),
        payload={"ok": True},
        trace_id=None,
    )


def test_agent_event_write_preserves_identity_and_keeps_adapter_sequence_metadata():
    event = _agent_event(sequence=7)
    producer = EventProducerIdentity(producer_id="react", producer_event_id="native-7")

    write = from_agent_event(event, producer=producer)

    assert write.event_id == event.event_id
    assert write.schema_version == EVENT_SCHEMA_VERSION
    assert write.event_type == "tool.result"
    assert write.source == "engine_native"
    assert write.engine_session_id == event.engine_session_id
    assert write.payload == {"ok": True}
    assert write.producer_sequence == 7
    assert write.producer_id == "react"
    assert write.producer_event_id == "native-7"
    assert write.durable_sequence is None


def test_agent_event_write_rejects_a_foreign_run_binding():
    event = _agent_event()
    with pytest.raises(ValueError):
        from_agent_event(event, run_id=uuid4())


def test_event_producer_identity_requires_both_halves_or_neither():
    assert EventProducerIdentity().dedup_key() is None
    identity = EventProducerIdentity(producer_id="react", producer_event_id="e-1")
    assert identity.dedup_key() == ("react", "e-1")
    for kwargs in (
        {"producer_id": "react"},
        {"producer_event_id": "e-1"},
        {"producer_id": "x" * 201, "producer_event_id": "e-1"},
    ):
        with pytest.raises(ValueError):
            EventProducerIdentity(**kwargs)


def test_internal_replay_is_identity_bearing_but_never_publishable():
    assert is_publishable("run.completed") is True
    assert is_publishable("codex.turn.completed") is True
    assert is_publishable("tool.replay") is False


def test_event_write_result_is_a_content_free_duplicate_marker():
    event_id, seq = uuid4(), 12
    first = EventWriteResult(seq=seq, event_id=event_id, duplicate=False)
    duplicate = EventWriteResult(seq=seq, event_id=event_id, duplicate=True)

    assert first.seq == seq and first.event_id == event_id
    assert duplicate.duplicate is True
    with pytest.raises((TypeError, ValueError)):
        EventWriteResult(seq=0, event_id=event_id, duplicate=False)


def _credential(**overrides) -> ExecutionCredentialRecord:
    now = datetime.now(UTC)
    values = {
        "credential_id": uuid4(),
        "credential_ref": uuid4(),
        "tenant_id": "tenant-a",
        "name": "engine-key",
        "credential_type": "api_key",
        "encrypted_secret": "fernet:ciphertext",
        "key_version": "k1",
        "version": 1,
        "status": "active",
        "allowed_engines": ("react", "codex"),
        "allowed_workspaces": ("default",),
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return ExecutionCredentialRecord(**values)


def test_credential_public_metadata_never_exposes_the_secret():
    record = _credential()

    public = record.public_metadata()

    assert "encrypted_secret" not in public
    assert "fernet:ciphertext" not in repr(public)
    assert public["credential_ref"] == str(record.credential_ref)
    assert public["status"] == "active"
    assert public["version"] == 1
    assert public["allowed_engines"] == ("react", "codex")


def test_credential_record_rejects_unknown_lifecycle_values():
    with pytest.raises(ValueError):
        _credential(status="deleted")
    with pytest.raises(ValueError):
        _credential(version=0)
    with pytest.raises(ValueError):
        _credential(tenant_id="")


def _grant(**overrides) -> ExecutionCredentialGrant:
    issued = datetime.now(UTC)
    values = {
        "grant_id": uuid4(),
        "grant_hash": "a" * 64,
        "credential_id": uuid4(),
        "credential_version": 1,
        "run_id": uuid4(),
        "tenant_id": "tenant-a",
        "engine_id": "react",
        "protocol_id": "native",
        "workspace_id": "default",
        "scopes": ("execution.read",),
        "issued_at": issued,
        "expires_at": issued + timedelta(seconds=300),
    }
    values.update(overrides)
    return ExecutionCredentialGrant(**values)


def test_grant_binds_one_execution_and_a_positive_ttl():
    grant = _grant()

    assert str(grant.run_id)
    assert grant.expires_at > grant.issued_at
    with pytest.raises(ValueError):
        _grant(expires_at=grant.issued_at)
    with pytest.raises(ValueError):
        _grant(engine_id="")
    with pytest.raises(ValueError):
        _grant(scopes=())
    with pytest.raises(ValueError):
        _grant(grant_hash="short")


def test_grant_identity_is_opaque_and_not_a_replayable_token():
    grant = _grant()
    assert not hasattr(grant, "token")
    assert not hasattr(grant, "plaintext")
    assert UUID(str(grant.grant_id))
