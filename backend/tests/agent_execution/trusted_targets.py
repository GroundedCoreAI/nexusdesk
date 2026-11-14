"""Fixed trusted test targets executed by the Runtime Host lanes (08 §1.9).

This is the repository-internal workload directory extension required by
P4-IT: the Runner's allowlist always runs *this file's* dispatched cases via
the interpreter, so no user-supplied code and no arbitrary argv ever reaches
``exec``. Cases are selected by one bounded lowercase token; every parameter
is numeric or slug-shaped and re-validated here as the second line of defense.
"""

import os
import signal
import subprocess
import sys
import time

CASES = (
    "exit",
    "sleep",
    "ignore-term",
    "leaf-ignore-term",
    "flood-stdout",
    "flood-stderr",
    "json-events",
    "kv-events",
    "workdir-marker",
    "signal-crash",
    "env-silent",
    "cpu-burn",
    "alloc-write",
    "child-group-probe",
)


def _write(stream, payload: bytes) -> None:
    stream.write(payload)
    stream.flush()


def main(argv: list[str]) -> int:
    if len(argv) < 1 or argv[0] not in CASES:
        return 99
    case = argv[0]
    param = argv[1] if len(argv) > 1 else ""

    if case == "exit":
        return int(param or "0")
    if case == "sleep":
        time.sleep(min(float(param or "30"), 120.0))
        return 0
    if case in ("ignore-term", "leaf-ignore-term"):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if case == "ignore-term":
            # Nested descendant in the same process group that also ignores
            # TERM: only the group-wide KILL can take it down (AC-3, P4-IT-06).
            child = subprocess.Popen(  # fixed argv: this file, bounded token
                [sys.executable, os.path.abspath(__file__), "leaf-ignore-term", "60"],
                start_new_session=False,
            )
            _write(sys.stdout.buffer, f"child-pid={child.pid}".encode() + b"\n")
            _leaf_wait(child)
        else:
            _write(sys.stderr.buffer, b"leaf-alive\n")
            deadline = time.monotonic() + min(float(param or "60"), 120.0)
            while time.monotonic() < deadline:
                time.sleep(0.05)
        return 0
    if case in ("flood-stdout", "flood-stderr"):
        limit = min(int(param or "65536"), 16_777_216)
        stream = sys.stdout.buffer if case == "flood-stdout" else sys.stderr.buffer
        chunk = b"f" * 8192
        written = 0
        while written < limit:
            payload = chunk[: min(len(chunk), limit - written)]
            _write(stream, payload)
            written += len(payload)
        # Stay alive after the flood so the supervisor-side breach decision
        # (terminate the group) is the thing under test, not a voluntary exit.
        time.sleep(60)
        return 0
    if case == "json-events":
        # Protocol A (line-json): one JSON object per line.
        _write(
            sys.stdout.buffer,
            b'{"seq": 1, "type": "engine.message.delta", "payload": {"text": "hello"}}\n',
        )
        _write(
            sys.stdout.buffer,
            b'{"seq": 2, "type": "engine.run.completed", "payload": {"answer": "hello"}}\n',
        )
        return 0
    if case == "kv-events":
        # Protocol B (key-value): blank-line-separated records, distinct parser.
        _write(sys.stdout.buffer, b"seq=1\ntype=engine.message.delta\ntext=hello\n\n")
        _write(sys.stdout.buffer, b"seq=2\ntype=engine.run.completed\nanswer=hello\n\n")
        return 0
    if case == "workdir-marker":
        with open("marker.txt", "wb") as handle:
            handle.write(b"inside-workdir")
        return 0
    if case == "signal-crash":
        os.kill(os.getpid(), signal.SIGSEGV)
        time.sleep(5)  # unreachable when the signal lands
        return 0
    if case == "env-silent":
        # Prints nothing about the environment; used to prove environment
        # values never leak into output or logs (P4-UT-21).
        return 0
    if case == "cpu-burn":
        # Busy loop: RLIMIT_CPU is the kernel's own kill clock (approximate
        # per-process mechanism of 03 §4.6; the sampler never enforces it).
        import time as _time

        start = _time.monotonic()
        budget = float(param or "5")
        while _time.monotonic() - start < budget:
            pass
        return 0
    if case == "alloc-write":
        # Write until an external RLIMIT_FSIZE bound trips. Hosts differ in
        # whether the kernel kills with SIGXFSZ or the write fails with
        # EFBIG first, so the trusted target normalizes both into the
        # agreed excess contract: stderr marker + exit code 86
        # (TARGET_EXIT_RESOURCE_EXCEEDED in the resource lane).
        import errno as _errno
        import signal as _signal

        def _exceeded(*args):
            _write(sys.stderr.buffer, b"resource-exceeded=fsize\n")
            os._exit(86)

        _signal.signal(_signal.SIGXFSZ, _exceeded)
        limit = min(int(param or "16777216"), 16_777_216)
        written = 0
        try:
            with open("resource.bin", "wb") as handle:
                while written < limit:
                    handle.write(b"w" * 8192)
                    handle.flush()
                    written += 8192
        except OSError as exc:
            if exc.errno == _errno.EFBIG:
                _exceeded()
            raise
        return 0
    if case == "child-group-probe":
        # Same-session descendant: its process-group id must equal the
        # leader's for the group-wide kill to reach it (P4-IT-05).
        child = subprocess.Popen(  # fixed argv: this file, bounded token
            [sys.executable, os.path.abspath(__file__), "sleep", "20"],
            start_new_session=False,
        )
        own = os.getpgrp()
        same = os.getpgid(child.pid) == own
        _write(sys.stdout.buffer, f"group-match={int(same)}\n".encode())
        try:
            child.wait(timeout=25)
        except subprocess.TimeoutExpired:  # pragma: no cover
            pass
        return 0
    return 99  # pragma: no cover - CASES gate above


def _leaf_wait(child: subprocess.Popen) -> None:
    try:
        child.wait(timeout=120)
    except subprocess.TimeoutExpired:  # pragma: no cover - KILL takes the group
        pass


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
