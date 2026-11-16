"""Contract tests for the Phase 5 Codex configuration primitives."""

import pytest
from pydantic import ValidationError

from agent_platform.core_platform.agent_execution.adapters.codex.app_server import (
    AppServerProtocolError,
    CodexAppServerAdapter,
    decode_message,
    encode_request,
)
from agent_platform.core_platform.agent_execution.adapters.codex.cli_exec import (
    CODEX_CLI_FIXED_ARGV,
    build_cli_invocation,
)
from agent_platform.core_platform.agent_execution.adapters.codex.config import (
    CodexConfig,
    CodexProtocol,
    CodexStageGate,
)
from agent_platform.core_platform.agent_execution.adapters.codex.events import (
    CodexEventParser,
    parse_usage,
)
from agent_platform.core_platform.agent_execution.adapters.codex.jsonrpc import JsonRpcState
from agent_platform.core_platform.agent_execution.host.host_models import MAX_STDIN_PAYLOAD_BYTES


def test_stage_gate_fails_closed_and_keeps_protocols_independent() -> None:
    gate = CodexStageGate(
        cli_enabled=True,
        app_server_enabled=False,
        allowed_versions=("1.0.0",),
        trusted_tenants=("tenant-a",),
        stage_a_verified=True,
    )

    assert gate.permits(CodexProtocol.CLI_EXEC, version="1.0.0", tenant_id="tenant-a")
    assert not gate.permits(CodexProtocol.APP_SERVER, version="1.0.0", tenant_id="tenant-a")
    assert not gate.permits(CodexProtocol.CLI_EXEC, version="1.1.0", tenant_id="tenant-a")
    assert not gate.permits(CodexProtocol.CLI_EXEC, version="1.0.0", tenant_id="tenant-b")


def test_codex_config_rejects_host_paths_and_unknown_options() -> None:
    with pytest.raises(ValidationError):
        CodexConfig(version="1.0.0", executable="/usr/local/bin/codex")
    with pytest.raises(ValidationError):
        CodexConfig(version="1.0.0", unexpected=True)


def test_event_parser_is_bounded_and_usage_is_explicitly_unknown() -> None:
    parser = CodexEventParser(max_line_bytes=100)
    events = parser.parse_lines([b'{"type":"turn.completed","usage":{"input_tokens":2}}'])
    assert events[0].event_type == "turn.completed"
    assert parse_usage(events[0].payload) == {"input_tokens": 2}
    assert parse_usage({}) == {"status": "unknown"}

    with pytest.raises(ValueError, match="Malformed"):
        parser.parse_lines([b"not-json"])
    with pytest.raises(ValueError, match="size limit"):
        parser.parse_lines([b"x" * 101])


def test_jsonrpc_state_rejects_duplicates_and_ignores_late_responses() -> None:
    state = JsonRpcState()
    state.register("1")
    with pytest.raises(ValueError, match="duplicate"):
        state.register("1")
    assert state.resolve("1") is True
    assert state.resolve("1") is False
    assert state.pending() == ()


def test_cli_invocation_is_bounded_and_contains_no_host_path_or_secret() -> None:
    """08 R18: the prompt is stdin bytes; the argv stays the fixed constants."""
    invocation = build_cli_invocation(
        CodexConfig(version="0.169.0", credential_ref="secret-ref"),
        "inspect the workspace",
    )
    assert invocation.argv == CODEX_CLI_FIXED_ARGV
    assert "secret-ref" not in invocation.argv
    assert all("/" not in arg for arg in invocation.argv)
    # The prompt is nowhere in the argv; it is the stdin payload, byte for byte.
    assert "inspect the workspace" not in invocation.argv
    assert invocation.stdin_payload == b"inspect the workspace"
    assert invocation.env == ()

    with pytest.raises(ValueError, match="protocol"):
        build_cli_invocation(
            CodexConfig(version="0.169.0", protocol=CodexProtocol.APP_SERVER),
            "prompt",
        )


def test_cli_invocation_enforces_the_stdin_byte_ceiling() -> None:
    """The helper and the Host share one ceiling, so neither can drift."""
    config = CodexConfig(version="0.169.0")
    # Exactly at the ceiling is legal; one byte over is not.
    at_ceiling = "a" * MAX_STDIN_PAYLOAD_BYTES
    assert len(build_cli_invocation(config, at_ceiling).stdin_payload) == (MAX_STDIN_PAYLOAD_BYTES)
    with pytest.raises(ValueError, match="bounded"):
        build_cli_invocation(config, "a" * (MAX_STDIN_PAYLOAD_BYTES + 1))
    with pytest.raises(ValueError, match="non-empty"):
        build_cli_invocation(config, "")


def test_app_server_request_correlation_is_private_and_bounded() -> None:
    adapter = CodexAppServerAdapter(
        CodexConfig(version="0.169.0", protocol=CodexProtocol.APP_SERVER)
    )
    request = adapter.request("1", "turn/start", {"prompt": "hello"})
    assert b'"method":"turn/start"' in request.encode()
    assert adapter.handle_response({"id": "1", "result": {}})
    assert not adapter.handle_response({"id": "1", "result": {}})


def test_app_server_frames_are_private_bounded_jsonrpc() -> None:
    frame = encode_request("1", "initialize", {"clientInfo": {"name": "nexusdesk"}})
    message = decode_message(frame)
    assert message["method"] == "initialize"
    assert message["params"]["clientInfo"]["name"] == "nexusdesk"
    with pytest.raises(AppServerProtocolError, match="malformed"):
        decode_message(b"not-json")
    with pytest.raises(AppServerProtocolError, match="size limit"):
        decode_message(b"x" * 10, max_bytes=2)
