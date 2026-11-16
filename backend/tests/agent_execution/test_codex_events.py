"""Codex native event parsing and mapping bounds (04 P5-UT-06/07/17)."""

import json
from uuid import UUID

import pytest

from agent_platform.core_platform.agent_execution.adapters.codex.events import (
    EVENT_PAYLOAD_MAX_BYTES,
    CodexEventMapper,
    CodexEventParser,
    CodexNativeEvent,
    normalize_event_type,
    parse_usage,
)
from agent_platform.core_platform.agent_execution.contracts import (
    AdapterExecutionError,
    AgentEvent,
    ExecutionErrorCode,
    ExecutionHandle,
    ensure_event_identity,
)

EXECUTION_ID = UUID("00000000-0000-4000-8000-000000000601")
SESSION = "sess-1"


def _mapper() -> CodexEventMapper:
    return CodexEventMapper.for_cli(
        execution_id=EXECUTION_ID,
        engine_session_id=SESSION,
    )


def _handle() -> ExecutionHandle:
    return ExecutionHandle(
        execution_id=EXECUTION_ID,
        engine_id="codex",
        protocol_id="cli_exec",
        adapter_version="v1",
        provider_session_id=SESSION,
    )


def test_multi_line_payload_is_parsed_per_line_in_order() -> None:
    parser = CodexEventParser()
    lines = [
        b'{"type":"turn.started","turn_id":"t1"}\n',
        '{"type":"message.completed","text":"hi"}\n',
        b"\n",
        b'{"type":"turn.completed","usage":{"input_tokens":1}}\n',
    ]
    events = parser.parse_lines(lines)
    assert [event.event_type for event in events] == [
        "turn.started",
        "message.completed",
        "turn.completed",
    ]
    assert events[1].payload["text"] == "hi"


def test_chunk_boundaries_reassemble_into_complete_events() -> None:
    """D8/D16: a byte stream split mid-token yields the same events as one blob.

    ``CodexEventParser`` takes whole lines, so reassembly is the caller's job.
    This pins the reassembly rule the adapter relies on: splitting on ``b"\\n"``
    across arbitrary chunk boundaries must produce the identical event list, and
    a trailing partial line is not a complete event.
    """
    transcript = (
        b'{"type":"turn.started","turn_id":"t1"}\n'
        b'{"type":"item.completed","item":{"id":"item_1","type":"agent_message",'
        b'"text":"a longer answer split across chunks"}}\n'
        b'{"type":"turn.completed","usage":{"input_tokens":7}}\n'
    )
    whole = CodexEventParser().parse_lines(transcript.splitlines())

    # Feed the same bytes in 7-byte chunks through a line reassembler.
    buffer = b""
    reassembled: list[bytes] = []
    for offset in range(0, len(transcript), 7):
        buffer += transcript[offset : offset + 7]
        while b"\n" in buffer:
            line, _, buffer = buffer.partition(b"\n")
            reassembled.append(line)
    chunked = CodexEventParser().parse_lines(reassembled)

    assert [event.event_type for event in chunked] == [event.event_type for event in whole]
    assert [event.payload for event in chunked] == [event.payload for event in whole]
    # The trailing partial line never became an event.
    assert buffer == b""

    parser = CodexEventParser()
    assert [e.event_type for e in parser.parse_lines([transcript.split(b"\n")[0]])] == [
        "turn.started"
    ]


def test_malformed_and_oversized_lines_are_bounded_errors() -> None:
    parser = CodexEventParser(max_line_bytes=32)
    with pytest.raises(ValueError, match="Malformed"):
        parser.parse_lines([b"not-json"])
    with pytest.raises(ValueError, match="size limit"):
        parser.parse_lines([b"x" * 33])
    with pytest.raises(ValueError, match="type is missing"):
        parser.parse_lines([b'{"payload":{}}'])


def test_usage_reports_every_measured_field_or_unknown() -> None:
    measured = {
        "usage": {
            "input_tokens": 3,
            "output_tokens": 5,
            "total_tokens": 8,
            "cached_input_tokens": 1,
            "cache_write_input_tokens": 2,
            "reasoning_output_tokens": 4,
        }
    }
    assert parse_usage(measured) == measured["usage"]

    partial = parse_usage({"usage": {"input_tokens": 2}})
    assert partial == {"input_tokens": 2}
    assert "output_tokens" not in partial  # never zero-filled

    assert parse_usage({}) == {"status": "unknown"}
    assert parse_usage({"usage": None}) == {"status": "unknown"}


def test_event_type_normalization_satisfies_the_public_grammar() -> None:
    assert normalize_event_type("turn.completed") == "codex.turn.completed"
    assert normalize_event_type("item/Started") == "codex.item.started"
    assert normalize_event_type("Weird Type!") == "codex.weird_type"
    assert normalize_event_type("   ") == "codex.unknown"
    assert len(normalize_event_type("a" * 400)) <= 100


def test_mapped_events_are_public_identity_consistent_and_monotone() -> None:
    mapper = _mapper()
    natives = [
        CodexNativeEvent(event_type="turn.started", payload={"turn_id": "t1"}),
        CodexNativeEvent(event_type="message.completed", payload={"text": "hi"}),
        CodexNativeEvent(event_type="turn.completed", payload={"usage": {"input_tokens": 1}}),
    ]
    events = [mapper.map(native) for native in natives]

    assert [event.sequence for event in events] == [1, 2, 3]
    assert [event.event_type for event in events] == [
        "codex.turn.started",
        "codex.message.completed",
        "codex.turn.completed",
    ]
    assert all(event.source == "engine_native" for event in events)
    assert all(event.engine_session_id == SESSION for event in events)
    assert len({event.event_id for event in events}) == len(events)

    handle = _handle()
    for event in events:
        ensure_event_identity(handle, event)
        assert isinstance(event, AgentEvent)


def test_unknown_native_types_are_preserved_not_dropped() -> None:
    event = _mapper().map(CodexNativeEvent(event_type="brand.new.thing", payload={"x": 1}))
    assert event.event_type == "codex.brand.new.thing"
    assert event.payload == {"x": 1}


def test_oversized_payload_is_truncated_and_marked() -> None:
    mapper = _mapper()
    event = mapper.map(
        CodexNativeEvent(event_type="message.completed", payload={"text": "x" * 40_000})
    )

    assert event.payload["truncated"] is True
    assert event.payload["native_type"] == "message.completed"
    encoded = json.dumps(event.payload, separators=(",", ":"), sort_keys=True)
    assert len(encoded.encode("utf-8")) <= EVENT_PAYLOAD_MAX_BYTES
    assert "truncated" in event.payload


def test_malformed_line_mapping_is_a_bounded_protocol_error_without_raw_text() -> None:
    mapper = _mapper()
    with pytest.raises(AdapterExecutionError) as caught:
        mapper.map_lines([b"secret-like raw stderr content"], max_line_bytes=1024)

    error = caught.value
    assert error.error.code is ExecutionErrorCode.PROTOCOL_ERROR
    # The only diagnostic is the static catalog sentence; the raw provider line
    # and the parser's own exception text are both absent from the message.
    assert str(error) == "Adapter protocol failed."
    assert "secret-like" not in str(error)
    assert error.args == ("Adapter protocol failed.",)
    assert error.__cause__ is None
    assert error.__suppress_context__ is True


def test_mapping_a_non_native_object_is_a_protocol_error() -> None:
    with pytest.raises(AdapterExecutionError) as caught:
        _mapper().map({"type": "turn.started"})  # type: ignore[arg-type]
    assert caught.value.error.code is ExecutionErrorCode.PROTOCOL_ERROR


# ---------------------------------------------------------------------------
# D12: provider-private keys never reach the public payload
# ---------------------------------------------------------------------------


def test_process_started_pid_is_stripped_from_the_public_payload() -> None:
    event = _mapper().map(
        CodexNativeEvent(
            event_type="process.started",
            payload={"type": "process.started", "pid": 4242, "process_group_id": 4242},
        )
    )
    assert "pid" not in event.payload
    assert "process_group_id" not in event.payload
    assert event.payload == {"type": "process.started"}


def test_jsonrpc_envelope_keys_are_stripped_but_nested_item_id_survives() -> None:
    event = _mapper().map(
        CodexNativeEvent(
            event_type="turn.event",
            payload={
                "jsonrpc": "2.0",
                "id": "r7",
                "method": "turn/event",
                "params": {"type": "item.completed"},
                "item": {"id": "item_1", "type": "agent_message", "text": "ok"},
            },
        )
    )
    for key in ("jsonrpc", "id", "method", "params"):
        assert key not in event.payload
    # A nested business id is not the JSON-RPC envelope id and must survive.
    assert event.payload["item"]["id"] == "item_1"


def test_environment_and_credential_keys_never_enter_the_payload() -> None:
    event = _mapper().map(
        CodexNativeEvent(
            event_type="turn.completed",
            payload={
                "type": "turn.completed",
                "environment": {"PATH": "/usr/bin"},
                "credential_ref": "deployment-ref",
                "token": "canary",
                "usage": {"input_tokens": 1},
            },
        )
    )
    for key in ("environment", "credential_ref", "token"):
        assert key not in event.payload
    assert event.payload["usage"] == {"input_tokens": 1}


def test_raw_std_streams_never_enter_the_payload() -> None:
    event = _mapper().map(
        CodexNativeEvent(
            event_type="turn.event",
            payload={"type": "turn.event", "stdout": "raw", "stderr": "raw"},
        )
    )
    assert "stdout" not in event.payload
    assert "stderr" not in event.payload
