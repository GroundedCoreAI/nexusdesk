"""Codex execution adapter contracts.

Provider-private primitives plus the Stage A CLI adapter. The App-Server
surface here is protocol codec/state only: no transport or Session object is
shipped while Stage B is locked (Phase 5 C3).
"""

from .adapter import CodexCliAdapter, declared_capabilities
from .app_server import (
    AppServerProtocolError,
    CodexAppServerAdapter,
    CodexAppServerProtocol,
    InitializeResult,
    JsonRpcRequest,
    validate_initialize_result,
)
from .config import CodexConfig, CodexProtocol, CodexStageGate
from .events import CodexEventMapper, CodexEventParser, parse_usage
from .jsonrpc import JsonRpcState

__all__ = [
    "AppServerProtocolError",
    "CodexAppServerAdapter",
    "CodexAppServerProtocol",
    "CodexCliAdapter",
    "CodexConfig",
    "CodexEventMapper",
    "CodexEventParser",
    "CodexProtocol",
    "CodexStageGate",
    "InitializeResult",
    "JsonRpcRequest",
    "JsonRpcState",
    "declared_capabilities",
    "parse_usage",
    "validate_initialize_result",
]
