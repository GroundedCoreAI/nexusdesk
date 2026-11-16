"""Safe command construction for the Codex CLI adapter.

The adapter only builds an argv vector. Process creation and workspace policy
remain RuntimeHost responsibilities (Phase 4 08 R-1: no second process owner).

Stage A pins the whole command line: the executable id and every token are code
constants, and the adapter supplies **zero** trailing parameters. That is what
makes ``ProcessSpec.argv`` identical to the trusted descriptor's ``fixed_prefix``
and leaves the Host's bounded-parameter validator nothing to interpolate.

The trailing ``-`` is Codex's "read the prompt from stdin" marker, and stdin is
where the prompt now travels: the Host's opt-in bounded stdin channel delivers
it and closes the pipe (08 R18), so ``codex exec … -`` starts its turn. The
prompt is therefore never an argv element - the argv stays exactly the seven
code constants below, for every execution, whatever the prompt says.
"""

from dataclasses import dataclass

from ...host.host_models import MAX_STDIN_PAYLOAD_BYTES
from .config import CodexConfig, CodexProtocol

# The one executable id the Composition may trust for the Codex CLI lane.
CODEX_CLI_EXECUTABLE_ID = "codex"

# Stage A fixed command line. Every token is a code constant: no credential, no
# absolute path, no host environment value, and no prompt text may appear here.
CODEX_CLI_FIXED_ARGV: tuple[str, ...] = (
    "exec",
    "--json",
    "--sandbox",
    "read-only",
    "--skip-git-repo-check",
    "--ephemeral",
    "-",
)


@dataclass(frozen=True)
class CodexCliInvocation:
    """Provider-private invocation data; never expose it in public events.

    ``stdin_payload`` is the prompt as UTF-8 bytes, matching
    :attr:`~...host.host_models.ProcessSpec.stdin_payload`. Keeping it on this
    dataclass (rather than in ``argv``) is what makes "the prompt is never a
    command-line argument" checkable instead of aspirational.
    """

    argv: tuple[str, ...]
    stdin_payload: bytes = b""
    env: tuple[tuple[str, str], ...] = ()


def build_cli_invocation(config: CodexConfig, prompt: str) -> CodexCliInvocation:
    """Build the bounded non-interactive CLI invocation for one prompt.

    This is the contract-shape helper: it documents which flags Stage A pins and
    proves that neither a credential nor the prompt enters the argv. The prompt
    is UTF-8 encoded here for the stdin channel, with the same byte ceiling the
    Host enforces (08 R18), so an over-ceiling prompt fails at construction
    rather than at spawn.
    """
    if config.protocol is not CodexProtocol.CLI_EXEC:
        raise ValueError("CLI invocation requires cli_exec protocol")
    if not prompt:
        raise ValueError("prompt must be non-empty")
    payload = prompt.encode("utf-8")
    if not payload or len(payload) > MAX_STDIN_PAYLOAD_BYTES:
        raise ValueError("prompt must be non-empty and bounded")
    return CodexCliInvocation(argv=CODEX_CLI_FIXED_ARGV, stdin_payload=payload)
