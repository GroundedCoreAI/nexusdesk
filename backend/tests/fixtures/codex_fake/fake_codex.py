"""Deterministic fake Codex CLI/App-Server used only by integration tests.

Run it as ``python fake_codex.py``: the shebang was removed deliberately so the
repository-wide ``ruff check`` stays green (EXE001) and the fixture behaves the
same on every platform. Integration tests build the trusted target from an
explicit interpreter path instead of relying on an executable bit.

The CLI mode **reads its prompt from stdin** (08 R18). That is not cosmetic: a
fixture that ignores stdin lets a small prompt "succeed" merely by fitting in
the 64 KiB pipe buffer, which would hide a Host that never delivers anything.
Reading first is what proves consumption rather than acceptance.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from typing import Any

# One byte above the Host's payload ceiling (08 R18): the fixture can never
# buffer more than the largest thing the Host may legitimately send.
_STDIN_READ_LIMIT = 1_000_001


def emit(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def read_prompt() -> bytes:
    """Consume the whole prompt up to EOF, exactly like ``codex exec … -``."""
    return sys.stdin.buffer.read(_STDIN_READ_LIMIT)


def run_child() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    emit({"type": "process.started", "pid": child.pid})
    try:
        time.sleep(600)
    finally:
        child.terminate()


def run_cli() -> int:
    scenario = os.getenv("FAKE_CODEX_SCENARIO", "success")
    # Read the prompt first in every scenario, including ``hang``: the Host
    # writes and closes the pipe before this process does anything, so a
    # failure here is a real delivery failure rather than a fixture artifact.
    prompt = read_prompt()
    if scenario == "hang":
        time.sleep(600)
        return 0
    if scenario == "child":
        run_child()
        return 0
    emit({"type": "thread.started", "thread_id": "fake-thread-1"})
    emit({"type": "turn.started"})
    if scenario == "malformed":
        sys.stdout.write("{not-json}\n")
        sys.stdout.flush()
        return 0
    if scenario == "prompt-digest":
        # 08 R18: the answer IS the consumed-prompt summary, so an integration
        # assertion can prove the Host delivered exactly those bytes.
        digest = hashlib.sha256(prompt).hexdigest()[:16]
        text = f"stdin={len(prompt)}:{digest}"
    else:
        text = "fake codex result"
    # Measured Codex 0.169.0 CLI shape: the answer is a nested item whose type is
    # ``agent_message``; diagnostics use ``item.type == "error"``. Usage has no
    # ``total_tokens`` field at all.
    emit(
        {
            "type": "item.completed",
            "item": {"id": "item_0", "type": "agent_message", "text": text},
        }
    )
    emit(
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8},
        }
    )
    return 0
    # Measured Codex 0.169.0 CLI shape: the answer is a nested item whose type is
    # ``agent_message``; diagnostics use ``item.type == "error"``. Usage has no
    # ``total_tokens`` field at all.
    emit(
        {
            "type": "item.completed",
            "item": {"id": "item_0", "type": "agent_message", "text": "fake codex result"},
        }
    )
    emit(
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8},
        }
    )
    return 0


def run_app_server() -> int:
    scenario = os.getenv("FAKE_CODEX_SCENARIO", "success")
    for line in sys.stdin:
        if scenario == "hang":
            time.sleep(600)
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            emit(
                {"jsonrpc": "2.0", "error": {"code": -32700, "message": "parse error"}, "id": None}
            )
            continue
        request_id = request.get("id")
        method = request.get("method")
        if scenario == "malformed":
            sys.stdout.write("{not-json}\n")
            sys.stdout.flush()
            continue
        if method == "initialize":
            emit(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"protocolVersion": "fake-1", "capabilities": {}},
                }
            )
            emit(
                {
                    "jsonrpc": "2.0",
                    "method": "session/ready",
                    "params": {"session_id": "fake-session-1"},
                }
            )
        elif method in {"turn/start", "turn/start_async"}:
            emit(
                {
                    "jsonrpc": "2.0",
                    "method": "turn/event",
                    "params": {"type": "message.completed", "text": "fake codex result"},
                }
            )
            emit(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "status": "completed",
                        "usage": {"input_tokens": 3, "output_tokens": 5},
                    },
                }
            )
        else:
            emit(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": "method not found"},
                }
            )
    return 0


def main() -> int:
    mode = os.getenv("FAKE_CODEX_MODE", "cli")
    return run_app_server() if mode == "app-server" else run_cli()


if __name__ == "__main__":
    raise SystemExit(main())
