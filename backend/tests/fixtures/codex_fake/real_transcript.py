"""Measured Codex CLI 0.169.0 transcript shapes, frozen as test fixtures.

These strings were captured from a real ``codex exec --json`` run, not invented.
They are the contract evidence for D6: the answer is nested under ``item`` and
the measured usage carries **no** ``total_tokens`` field. Keep them byte-exact;
a test pins the adapter against this file so a future "simplification" back to
the flat fixture syntax fails loudly.
"""

from __future__ import annotations

# One successful Turn exactly as the real CLI emitted it (trimmed to the event
# families that matter here, with the volatile thread id kept as a literal).
REAL_CODEX_SUCCESS_TRANSCRIPT = (
    '{"type":"thread.started","thread_id":"0199f0c1-9c8c-7a71-a0f4-0d6b0a2f1c11"}\n'
    '{"type":"turn.started"}\n'
    '{"type":"item.completed","item":{"id":"item_0","type":"error",'
    '"message":"model runner refused the sandbox probe"}}\n'
    '{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"ok"}}\n'
    '{"type":"turn.completed","usage":{"input_tokens":10525,'
    '"cached_input_tokens":10240,"cache_write_input_tokens":0,'
    '"output_tokens":2,"reasoning_output_tokens":0}}\n'
)

# The same Turn with the diagnostic item removed: the minimal success shape.
REAL_CODEX_MINIMAL_SUCCESS = (
    '{"type":"thread.started","thread_id":"0199f0c1-9c8c-7a71-a0f4-0d6b0a2f1c11"}\n'
    '{"type":"turn.started"}\n'
    '{"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"ok"}}\n'
    '{"type":"turn.completed","usage":{"input_tokens":10525,'
    '"cached_input_tokens":10240,"cache_write_input_tokens":0,'
    '"output_tokens":2,"reasoning_output_tokens":0}}\n'
)

# Usage as measured: six real fields, no ``total_tokens``.
REAL_CODEX_USAGE = {
    "input_tokens": 10525,
    "cached_input_tokens": 10240,
    "cache_write_input_tokens": 0,
    "output_tokens": 2,
    "reasoning_output_tokens": 0,
}

# The two error surfaces the real CLI prints on stderr for the environment gap
# recorded as R10 in the implementation breakdown (never echoed publicly).
REAL_CODEX_ENV_FAILURE_STDERR = b"env: node: No such file or directory\n"
