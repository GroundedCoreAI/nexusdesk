"""Provider-private App-Server JSON-RPC primitives: frames, negotiation, state.

Pure functions and one state machine only. There is no transport, no connection
owner and no Session object in this phase (Phase 5 C3), which is what keeps the
"Stage B locked" claim honest: the modules exist, the lane does not.

The public DTOs at the bottom of this module deliberately exclude method names
and request ids from any field a caller could serialize outward: those values
live only inside the provider-private request object and the negotiated result.
"""

import json
from dataclasses import dataclass
from typing import Any

from .config import CodexConfig, CodexProtocol
from .jsonrpc import JsonRpcState, JsonRpcStateError

MAX_FRAME_BYTES = 1_048_576
MAX_METHOD_LENGTH = 128

# Stage B is blocked, so this is the only protocol version this code shapes
# frames for. A peer answering anything else fails negotiation (FR-7).
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = ("1",)


class AppServerProtocolError(ValueError):
    """Raised when a provider-private JSON-RPC frame or result is invalid."""


@dataclass(frozen=True)
class JsonRpcRequest:
    """One provider-private request. ``method``/``request_id`` are never public."""

    request_id: str
    method: str
    params: dict[str, Any]

    def encode(self) -> bytes:
        return (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": self.request_id,
                    "method": self.method,
                    "params": self.params,
                },
                separators=(",", ":"),
            )
            + "\n"
        ).encode()


def encode_request(request_id: str, method: str, params: dict[str, Any] | None = None) -> bytes:
    if not request_id or not method:
        raise AppServerProtocolError("request id and method are required")
    return JsonRpcRequest(request_id, method, params or {}).encode()


def decode_message(frame: bytes, *, max_bytes: int = MAX_FRAME_BYTES) -> dict[str, Any]:
    """Decode one bounded JSON-RPC object; every rejection is a protocol error."""
    if not isinstance(frame, bytes):
        raise AppServerProtocolError("malformed JSON-RPC message")
    if len(frame) > max_bytes:
        raise AppServerProtocolError("message exceeds size limit")
    try:
        value = json.loads(frame)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppServerProtocolError("malformed JSON-RPC message") from exc
    if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
        raise AppServerProtocolError("malformed JSON-RPC message")
    return value


def classify_message(message: dict[str, Any]) -> str:
    """Return ``response``/``notification``/``request`` without exposing fields.

    A message carrying an ``id`` and a ``result``/``error`` is a response; one
    with ``method`` and no ``id`` is a notification (server events, approvals);
    one with both is a server-initiated request (Stage B approval/input flow).
    """
    if not isinstance(message, dict):
        raise AppServerProtocolError("malformed JSON-RPC message")
    has_id = message.get("id") is not None
    is_error_or_result = "error" in message or "result" in message
    has_method = isinstance(message.get("method"), str) and bool(message.get("method"))
    if has_id and is_error_or_result:
        return "response"
    if has_method and not has_id:
        return "notification"
    if has_method and has_id:
        return "request"
    raise AppServerProtocolError("malformed JSON-RPC message")


@dataclass(frozen=True)
class InitializeResult:
    """Validated shape of one ``initialize`` response.

    ``protocol_version`` is the negotiated value; ``server_name`` is a bounded
    label. Capabilities are passed through as the peer's opaque object because
    Stage A does not act on them; nothing from this DTO is exposed publicly.
    """

    protocol_version: str
    server_name: str | None = None
    capabilities: dict[str, Any] | None = None


def validate_initialize_result(result: object) -> InitializeResult:
    """Validate the negotiated version, refusing an unsupported one (FR-7)."""
    if not isinstance(result, dict):
        raise AppServerProtocolError("initialize result must be an object")
    version = result.get("protocolVersion", result.get("protocol_version"))
    if not isinstance(version, str) or not version:
        raise AppServerProtocolError("initialize result is missing the protocol version")
    if version not in SUPPORTED_PROTOCOL_VERSIONS:
        raise AppServerProtocolError("unsupported App-Server protocol version")
    server_name = result.get("serverName", result.get("server_name"))
    if server_name is not None and (not isinstance(server_name, str) or len(server_name) > 200):
        raise AppServerProtocolError("initialize result has an invalid server name")
    capabilities = result.get("capabilities")
    if capabilities is not None and not isinstance(capabilities, dict):
        raise AppServerProtocolError("initialize result has invalid capabilities")
    return InitializeResult(
        protocol_version=version,
        server_name=server_name,
        capabilities=capabilities,
    )


class CodexAppServerProtocol:
    """Bounded frame/state machine. No transport, no Session, no process.

    Stage B is locked by the deployment gate, so this class is exercised only by
    unit tests: it exists to keep the protocol semantics reviewable rather than
    to ship a half-connected lane.
    """

    def __init__(
        self,
        config: CodexConfig,
        *,
        max_pending: int = 256,
        max_frame_bytes: int = MAX_FRAME_BYTES,
    ) -> None:
        if config.protocol is not CodexProtocol.APP_SERVER:
            raise ValueError("App-Server protocol requires app_server protocol")
        self._config = config
        self._max_frame_bytes = max_frame_bytes
        self.state = JsonRpcState(max_pending=max_pending)
        self._initialized: InitializeResult | None = None
        self._next_id = 0

    @property
    def initialized(self) -> InitializeResult | None:
        return self._initialized

    def next_request_id(self) -> str:
        """Provider-private monotone id; never derived from an input payload."""
        candidate = f"r{self._next_id}"
        while candidate in self.state.pending():
            self._next_id += 1
            candidate = f"r{self._next_id}"
        self._next_id += 1
        return candidate

    def request(self, method: str, params: dict[str, Any] | None = None) -> JsonRpcRequest:
        if not isinstance(method, str) or not method or len(method) > MAX_METHOD_LENGTH:
            raise AppServerProtocolError("method must be non-empty and bounded")
        if params is not None and not isinstance(params, dict):
            raise AppServerProtocolError("params must be an object")
        request_id = self.next_request_id()
        try:
            self.state.register(request_id)
        except JsonRpcStateError as exc:
            raise AppServerProtocolError("JSON-RPC correlation is unavailable") from exc
        return JsonRpcRequest(request_id, method, params or {})

    def initialize_request(self) -> JsonRpcRequest:
        """The one Stage B handshake frame, with fixed, non-sensitive params."""
        return self.request(
            "initialize",
            {"clientInfo": {"name": "nexusdesk", "version": "v1"}},
        )

    def handle_frame(self, frame: bytes) -> str | None:
        """Classify and correlate one frame; returns the kind for assertions.

        A response resolves exactly one pending id. Duplicate and late
        responses are ignored (``resolve`` returns ``False``) rather than
        replayed, and an ``initialize`` result is validated and stored once.
        """
        message = decode_message(frame, max_bytes=self._max_frame_bytes)
        kind = classify_message(message)
        if kind != "response":
            return kind
        request_id = message.get("id")
        if not isinstance(request_id, str):
            raise AppServerProtocolError("response id must be a string")
        resolved = self.state.resolve(request_id)
        if not resolved:
            return "late-response"
        if self._initialized is None:
            result = message.get("result")
            if isinstance(result, dict) and (
                "protocolVersion" in result or "protocol_version" in result
            ):
                self._initialized = validate_initialize_result(result)
        return "response"

    def initialize(self, frame: bytes) -> InitializeResult:
        """Handle exactly the initialize response, refusing anything else."""
        message = decode_message(frame, max_bytes=self._max_frame_bytes)
        if classify_message(message) != "response":
            raise AppServerProtocolError("initialize requires a response frame")
        request_id = message.get("id")
        if not isinstance(request_id, str) or not self.state.resolve(request_id):
            raise AppServerProtocolError("initialize response does not match a request")
        if "error" in message:
            raise AppServerProtocolError("initialize failed")
        self._initialized = validate_initialize_result(message.get("result"))
        return self._initialized

    def disconnect(self) -> None:
        """Drop every pending correlation; no response is invented on close."""
        self.state.clear()


class CodexAppServerAdapter:
    """Stage B request builder retained for correlation-only contract tests.

    It owns no transport and no Session. Method names and request ids stay
    provider-private: the class never exposes them through a public DTO, and the
    protocol lane is still disabled at the deployment gate. The newer
    :class:`CodexAppServerProtocol` adds frame classification, initialize
    validation and version negotiation on top of the same state machine.
    """

    def __init__(self, config: CodexConfig) -> None:
        if config.protocol is not CodexProtocol.APP_SERVER:
            raise ValueError("App-Server adapter requires app_server protocol")
        self.config = config
        self.state = JsonRpcState()

    def request(
        self, request_id: str, method: str, params: dict[str, Any] | None = None
    ) -> JsonRpcRequest:
        if not method or len(method) > MAX_METHOD_LENGTH:
            raise AppServerProtocolError("method must be non-empty and bounded")
        self.state.register(request_id)
        return JsonRpcRequest(request_id, method, params or {})

    def handle_response(self, message: dict[str, Any]) -> bool:
        """Resolve one response; late/duplicate ids return ``False``."""
        request_id = message.get("id") if isinstance(message, dict) else None
        return isinstance(request_id, str) and self.state.resolve(request_id)
