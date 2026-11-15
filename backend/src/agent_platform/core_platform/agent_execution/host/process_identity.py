"""Standard-library start-identity probes (Phase 4, 08 T7/R-6, 03 §4.4).

No psutil and no third-party dependency: identity sources differ per OS, so
every probe is narrow, explicit and fail-closed. An unavailable or unparsable
identity always counts as *mismatch*, which means zero signals and manual
remediation - never a heuristic kill. ``pgid`` uses ``os.getpgid``; the token
format is ``linux:<starttime-ticks>:<cmdline-sha-prefix>`` or
``macos:<lstart-normalized>:<comm>``.
"""

import asyncio
import hashlib
import os
import platform
import re
import subprocess
import sys

# Signal-0 style liveness is a permission probe, never a kill: ESRCH means the
# pid is gone, EPERM means someone else's process exists (identity mismatch
# then gates any later action).
_LIVENESS_SIGNAL = 0


def process_alive(pid: int) -> bool:
    """True when the pid exists; foreign-owned processes still count as alive."""
    try:
        os.kill(pid, _LIVENESS_SIGNAL)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def group_alive(pgid: int) -> bool:
    """True when any process is still in the group (killpg with signal 0)."""
    try:
        os.killpg(pgid, _LIVENESS_SIGNAL)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def read_pgid(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except OSError:
        return None


def _linux_token(pid: int) -> str | None:
    """starttime field 22 plus a cmdline digest from /proc (both unparsable -> None)."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    # comm may contain spaces/parentheses: locate the closing ')' first.
    end = raw.rfind(b")")
    if end < 0:
        return None
    fields = raw[end + 1 :].split()
    if len(fields) < 20:  # field 22 overall == index 20 after ")"+state
        return None
    start_ticks = fields[19]
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            cmdline = handle.read()
    except OSError:
        return None
    if not cmdline:
        return None
    digest = hashlib.sha256(cmdline).hexdigest()[:16]
    return f"linux:{start_ticks.decode('ascii', 'ignore')}:{digest}"


def _macos_token(pid: int) -> str | None:
    """Best-effort ``ps -o lstart=,comm=`` probe; any parse failure -> None."""
    try:
        completed = subprocess.run(  # fixed argv, never a caller string
            ["ps", "-o", "lstart=,comm=", "-p", str(pid)],
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    text = completed.stdout.decode("utf-8", "ignore").strip()
    if not text:
        return None
    # lstart is "Fri Nov 14 10:23:45 2026" (5 whitespace-separated fields),
    # then the command name to end of line.
    match = re.match(
        r"^([A-Z][a-z]{2})\s+([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})\s+(\d{4})\s+(.*)$",
        text,
    )
    if match is None:
        return None
    lstart = " ".join(match.group(i) for i in range(1, 6))
    comm = match.group(6).strip()
    if not comm:
        return None
    return f"macos:{lstart}:{comm}"


def capture_start_token(pid: int) -> str | None:
    """Capture the OS start identity for one pid right after spawn.

    Dispatch is by ``sys.platform``; any platform without an implemented and
    parsable source returns None, which downstream means mismatch/no-signal.
    """
    if sys.platform.startswith("linux"):
        return _linux_token(pid)
    if sys.platform == "darwin":
        return _macos_token(pid)
    return None


async def capture_start_token_async(pid: int) -> str | None:
    """Thread-shimmed capture so the async Runner never blocks the loop."""
    return await asyncio.to_thread(capture_start_token, pid)


def current_platform_label() -> str:
    """Environment string for honest test reporting (08 R-3/T16)."""
    return f"{sys.platform}/{platform.machine()}/{platform.release()}"


def identity_matches(expected_token: str | None, probed_token: str | None) -> bool:
    """Fail-closed comparison: missing on either side is a mismatch (08 R-6)."""
    if expected_token is None or probed_token is None:
        return False
    return expected_token == probed_token
