"""Phase 6 R-18(b): redaction applied at real SSE/Outbox emission sites.

The actual sse_payload and OutboxDispatcher paths must redact Secrets, not just
the standalone redactor. A canary in event data never reaches the wire verbatim.
"""

from uuid import uuid4

from agent_platform.core_platform.agent_execution.events.outbox import (
    OutboxDispatcher,
    _PendingRow,
)
from agent_platform.core_platform.agent_execution.events.replay import sse_payload
from agent_platform.core_platform.agent_execution.security.redaction import SecretRedactor

CANARY = "launch-secret-canary"


def test_sse_payload_redacts_secret_from_emission():
    redactor = SecretRedactor([CANARY])
    row = {
        "data": {"output": f"ok {CANARY}", "note": "x"},
        "event_id": uuid4(),
        "schema_version": "v1",
        "source": "engine_native",
        "trace_id": None,
    }
    payload = sse_payload(row, redactor=redactor)
    assert CANARY not in str(payload)
    assert payload["note"] == "x"
    assert payload["_execution"]["event_id"] == str(row["event_id"])


def test_outbox_envelope_redacts_secret_before_publish():
    redactor = SecretRedactor([CANARY])
    pending = _PendingRow(
        run_id=uuid4(),
        seq=1,
        event_id=uuid4(),
        attempts=0,
        event_type="extension.note",
        data={"note": f"value {CANARY}"},
        trace_id=None,
        tenant_id="t",
    )
    envelope = pending.envelope(redactor=redactor)
    assert CANARY not in str(envelope.payload)
    assert envelope.idempotency_key == str(pending.event_id)


def test_outbox_dispatcher_applies_redactor_to_envelope():
    redactor = SecretRedactor([CANARY])
    dispatcher = OutboxDispatcher(
        engine=None,
        publisher=None,
        redactor=redactor,
    )
    pending = _PendingRow(
        run_id=uuid4(),
        seq=1,
        event_id=uuid4(),
        attempts=0,
        event_type="extension.note",
        data={"note": CANARY},
        trace_id=None,
        tenant_id="t",
    )
    # The dispatcher's redactor is applied at the real publish seam.
    envelope = dispatcher._envelope_for(pending)
    assert CANARY not in str(envelope.payload)
