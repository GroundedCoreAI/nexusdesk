"""JSON-RPC state machine and App-Server codec/negotiation (04 P5-UT-11/12)."""

import json

import pytest

from agent_platform.core_platform.agent_execution.adapters.codex.app_server import (
    AppServerProtocolError,
    CodexAppServerAdapter,
    CodexAppServerProtocol,
    classify_message,
    decode_message,
    encode_request,
    validate_initialize_result,
)
from agent_platform.core_platform.agent_execution.adapters.codex.config import (
    CodexConfig,
    CodexProtocol,
)
from agent_platform.core_platform.agent_execution.adapters.codex.jsonrpc import JsonRpcState


def _config(protocol: CodexProtocol = CodexProtocol.APP_SERVER) -> CodexConfig:
    if protocol is CodexProtocol.APP_SERVER:
        return CodexConfig(protocol=protocol, version="0.169.0", credential_ref="deployment-ref")
    return CodexConfig(protocol=protocol, version="0.169.0")


def _frame(payload: dict) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode() + b"\n"


def test_pending_set_is_bounded_and_frees_slots_on_resolve() -> None:
    state = JsonRpcState(max_pending=2)
    state.register("a")
    state.register("b")
    with pytest.raises(ValueError, match="full"):
        state.register("c")
    assert state.resolve("a") is True
    state.register("c")
    assert state.pending() == ("b", "c")
    with pytest.raises(ValueError, match="positive integer"):
        JsonRpcState(max_pending=0)


def test_duplicate_and_late_ids_keep_the_frozen_semantics() -> None:
    state = JsonRpcState()
    state.register("1")
    with pytest.raises(ValueError, match="duplicate"):
        state.register("1")
    state.register("2")
    assert state.resolve("2") is True
    # A duplicate/late response is ignored, never replayed.
    assert state.resolve("2") is False
    assert state.resolve("never-registered") is False
    assert state.pending() == ("1",)
    state.clear()
    assert state.pending() == ()


def test_frame_decode_is_bounded_and_requires_jsonrpc_2() -> None:
    assert decode_message(_frame({"jsonrpc": "2.0", "id": "1", "result": {}}))["id"] == "1"
    with pytest.raises(AppServerProtocolError, match="malformed"):
        decode_message(b"not-json")
    with pytest.raises(AppServerProtocolError, match="size limit"):
        decode_message(b"x" * 10, max_bytes=2)
    with pytest.raises(AppServerProtocolError, match="malformed"):
        decode_message(_frame({"jsonrpc": "1.0", "id": "1", "result": {}}))
    with pytest.raises(AppServerProtocolError, match="malformed"):
        decode_message("not-bytes")  # type: ignore[arg-type]


def test_message_classification_covers_response_notification_and_request() -> None:
    assert classify_message({"jsonrpc": "2.0", "id": "1", "result": {}}) == "response"
    assert classify_message({"jsonrpc": "2.0", "method": "turn/event"}) == "notification"
    assert classify_message({"jsonrpc": "2.0", "id": "9", "method": "session/approve"}) == "request"
    with pytest.raises(AppServerProtocolError):
        classify_message({"jsonrpc": "2.0"})


def test_initialize_result_requires_a_supported_version() -> None:
    negotiated = validate_initialize_result({"protocolVersion": "1", "serverName": "codex"})
    assert negotiated.protocol_version == "1"
    assert negotiated.server_name == "codex"

    with pytest.raises(AppServerProtocolError, match="protocol version"):
        validate_initialize_result({})
    with pytest.raises(AppServerProtocolError, match="unsupported"):
        validate_initialize_result({"protocolVersion": "99"})
    with pytest.raises(AppServerProtocolError, match="server name"):
        validate_initialize_result({"protocolVersion": "1", "serverName": "x" * 201})


def test_protocol_handshake_negotiates_then_refuses_a_bad_version() -> None:
    protocol = CodexAppServerProtocol(_config())
    request = protocol.initialize_request()
    assert b'"method":"initialize"' in request.encode()
    # Method names and ids stay inside the provider-private frame.
    assert (
        protocol.initialize(
            _frame({"jsonrpc": "2.0", "id": request.request_id, "result": {"protocolVersion": "1"}})
        ).protocol_version
        == "1"
    )
    assert protocol.initialized is not None

    new_protocol = CodexAppServerProtocol(_config())
    bad = new_protocol.initialize_request()
    with pytest.raises(AppServerProtocolError, match="unsupported"):
        new_protocol.initialize(
            _frame({"jsonrpc": "2.0", "id": bad.request_id, "result": {"protocolVersion": "x"}})
        )


def test_initialize_error_response_is_refused() -> None:
    protocol = CodexAppServerProtocol(_config())
    request = protocol.initialize_request()
    with pytest.raises(AppServerProtocolError, match="initialize failed"):
        protocol.initialize(
            _frame({"jsonrpc": "2.0", "id": request.request_id, "error": {"code": -1}})
        )


def test_handle_frame_ignores_late_responses_and_never_replays() -> None:
    protocol = CodexAppServerProtocol(_config())
    first = protocol.request("turn/start", {"prompt": "hi"})
    frame = _frame({"jsonrpc": "2.0", "id": first.request_id, "result": {"status": "completed"}})

    assert protocol.handle_frame(frame) == "response"
    assert protocol.handle_frame(frame) == "late-response"
    assert (
        protocol.handle_frame(_frame({"jsonrpc": "2.0", "method": "turn/event"})) == "notification"
    )


def test_frames_are_private_and_never_carry_credentials() -> None:
    protocol = CodexAppServerProtocol(_config())
    request = protocol.request("turn/start", {"prompt": "hello"})
    encoded = request.encode()
    assert b"deployment-ref" not in encoded
    assert b'"_token"' not in encoded
    assert set(json.loads(encoded)) == {"jsonrpc", "id", "method", "params"}


def test_protocol_requires_the_app_server_configuration() -> None:
    with pytest.raises(ValueError, match="app_server protocol"):
        CodexAppServerProtocol(_config(CodexProtocol.CLI_EXEC))
    with pytest.raises(ValueError, match="app_server protocol"):
        CodexAppServerAdapter(CodexConfig(version="0.169.0"))


def test_bounded_method_length_is_enforced() -> None:
    protocol = CodexAppServerProtocol(_config())
    with pytest.raises(AppServerProtocolError, match="method"):
        protocol.request("m" * 129)
    with pytest.raises(AppServerProtocolError, match="method"):
        encode_request("", "m")


def test_disconnect_drops_waiters_without_inventing_responses() -> None:
    protocol = CodexAppServerProtocol(_config())
    protocol.request("turn/start", {})
    protocol.disconnect()
    assert protocol.state.pending() == ()
